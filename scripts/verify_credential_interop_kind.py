"""C08: actual TLS, generic credentials, logs, exec and forwards on owned kind."""

import argparse
import asyncio
import base64
import json
import os
import sys
from functools import partial
from pathlib import Path
from typing import Any

import yaml
from kubernetes_asyncio import client

from kuberich.adapters.credentials import _execute
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest, ConnectionState
from kuberich.domain.port_forwards import ForwardState, parse_mappings
from kuberich.domain.targets import ResourceTarget
from kuberich.services.access import AccessPolicy
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.port_forwards import ForwardManager, ForwardService
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from scripts.owned_kind import NODE_IMAGE, OwnedCluster, owned_cluster
from scripts.verify_port_forwards_kind import FORWARD_IMAGE, observed, payload
from tests.support.http_proxy import http_proxy


def current(sessions: SessionService, connection: KubernetesSession) -> bool:
    return sessions.client is connection


async def verify(cluster: OwnedCluster, kubectl: Path) -> dict[str, Any]:
    original = cluster.path.read_bytes()
    request = ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context, timeout=15)
    admin = SessionService(load_catalog(request, {}), request)
    checks: dict[str, bool] = {}
    namespace = "kuberich-credential-interop"
    try:
        assert (await admin.connect(cluster.context)).state is ConnectionState.CONNECTED
        assert admin.client is not None and admin.client.api is not None
        api = client.CoreV1Api(admin.client.api)
        await api.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace)))
        await api.create_namespaced_pod(
            namespace,
            client.V1Pod(
                metadata=client.V1ObjectMeta(name="owned-http", labels={"app": "owned-http"}),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="http",
                            image=FORWARD_IMAGE,
                            command=[
                                "/bin/sh",
                                "-c",
                                "mkdir /tmp/www; echo OWNED-FORWARD-HTTP >/tmp/www/index.html; echo OWNED-INTEROP-LOG; exec httpd -f -p 8080 -h /tmp/www",
                            ],
                            readiness_probe=client.V1Probe(
                                http_get=client.V1HTTPGetAction(path="/", port=8080)
                            ),
                        )
                    ]
                ),
            ),
        )
        async with asyncio.timeout(180):
            while True:
                pod = await api.read_namespaced_pod("owned-http", namespace)
                if pod.status.container_statuses and pod.status.container_statuses[0].ready:
                    break
                await asyncio.sleep(0.2)
        await api.create_namespaced_service_account(
            namespace,
            client.V1ServiceAccount(metadata=client.V1ObjectMeta(name="owned-credential")),
        )
        await client.RbacAuthorizationV1Api(admin.client.api).create_cluster_role_binding(
            client.V1ClusterRoleBinding(
                metadata=client.V1ObjectMeta(name="kuberich-owned-credential"),
                role_ref=client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="ClusterRole", name="cluster-admin"
                ),
                subjects=[
                    client.RbacV1Subject(
                        kind="ServiceAccount", name="owned-credential", namespace=namespace
                    )
                ],
            )
        )
        issued = await api.create_namespaced_service_account_token(
            "owned-credential",
            namespace,
            client.AuthenticationV1TokenRequest(
                spec=client.V1TokenRequestSpec(audiences=[], expiration_seconds=1800)
            ),
        )
        source = yaml.safe_load(original)
        settings = source["clusters"][0]["cluster"]
        certificate = source["users"][0]["user"]
        environment = dict(os.environ)
        environment["PATH"] = str(kubectl.parent) + os.pathsep + environment.get("PATH", "")
        async with http_proxy(settings["server"]) as (proxy, witness):
            for mechanism in ("relative-cert", "exec-cert", "token-file", "oidc-token"):
                directory = cluster.directory / mechanism
                directory.mkdir()
                user: dict[str, Any]
                effective_cluster = {**settings, "proxy-url": proxy, "tls-server-name": "127.0.0.1"}
                if mechanism == "relative-cert":
                    user = {}
                    for field in ("client-certificate", "client-key"):
                        path = directory / field
                        path.write_bytes(base64.b64decode(certificate[field + "-data"]))
                        path.chmod(0o600)
                        user[field] = field
                    ca = directory / "ca.pem"
                    ca.write_bytes(
                        base64.b64decode(effective_cluster.pop("certificate-authority-data"))
                    )
                    ca.chmod(0o600)
                    effective_cluster["certificate-authority"] = "ca.pem"
                elif mechanism == "token-file":
                    token_file = directory / "token"
                    token_file.write_text(issued.status.token + "\n")
                    token_file.chmod(0o600)
                    user = {"tokenFile": "token"}
                else:
                    status = (
                        {
                            "clientCertificateData": base64.b64decode(
                                certificate["client-certificate-data"]
                            ).decode(),
                            "clientKeyData": base64.b64decode(
                                certificate["client-key-data"]
                            ).decode(),
                        }
                        if mechanism == "exec-cert"
                        else {"token": issued.status.token}
                    )
                    secret = directory / "credential.json"
                    secret.write_text(
                        json.dumps(
                            {
                                "apiVersion": "client.authentication.k8s.io/v1",
                                "kind": "ExecCredential",
                                "status": status,
                            }
                        )
                    )
                    secret.chmod(0o600)
                    helper = directory / "credential-helper"
                    helper.write_text(
                        f"#!{sys.executable}\nimport json,os\nfrom pathlib import Path\ni=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\nassert i['spec']['interactive'] is False\nassert i['spec']['cluster']['proxy-url']=={proxy!r}\nassert i['spec']['cluster']['server']=={settings['server']!r}\nprint(Path('credential.json').read_text())\n"
                    )
                    helper.chmod(0o700)
                    user = {
                        "exec": {
                            "command": "./credential-helper",
                            "apiVersion": "client.authentication.k8s.io/v1",
                            "interactiveMode": "Never",
                            "provideClusterInfo": True,
                        }
                    }
                # Catalogue merging must preserve each entry's original directory.
                cluster_path, user_path = directory / "cluster.yaml", directory / "user.yaml"
                cluster_path.write_text(
                    yaml.safe_dump(
                        {
                            "current-context": cluster.context,
                            "contexts": [
                                {
                                    "name": cluster.context,
                                    "context": {
                                        "cluster": "owned",
                                        "user": "owned",
                                        "namespace": namespace,
                                    },
                                }
                            ],
                            "clusters": [{"name": "owned", "cluster": effective_cluster}],
                        }
                    )
                )
                user_path.write_text(yaml.safe_dump({"users": [{"name": "owned", "user": user}]}))
                cluster_path.chmod(0o600)
                user_path.chmod(0o600)
                inputs = cluster_path.read_bytes(), user_path.read_bytes()
                selected_request = ConnectionRequest(
                    context=cluster.context, namespace=namespace, timeout=15
                )
                catalog = load_catalog(
                    selected_request,
                    {"KUBECONFIG": os.pathsep.join(map(str, (cluster_path, user_path)))},
                )
                sessions = SessionService(catalog, selected_request)
                try:
                    assert (
                        await sessions.connect(cluster.context)
                    ).state is ConnectionState.CONNECTED
                    connection, identity = sessions.client, sessions.observation.identity
                    assert connection is not None and identity is not None
                    checks[mechanism + "_merged_tls_browse"] = (
                        namespace in await connection.namespaces()
                    )
                    chunks = [
                        chunk
                        async for chunk in connection.log_bytes(
                            f"/api/v1/namespaces/{namespace}/pods/owned-http/log",
                            params={"container": "http", "tailLines": "10"},
                            follow=False,
                        )
                        if chunk is not None
                    ]
                    checks[mechanism + "_api_logs"] = b"OWNED-INTEROP-LOG" in b"".join(chunks)
                    delegation = capture_delegation(
                        connection, environment, directory, prefix="exec"
                    )
                    async with stage_connection(delegation.path, delegation.configuration):
                        assert delegation.path.stat().st_mode & 0o777 == 0o600
                        inherited = dict(delegation.environment)
                        inherited["KUBECONFIG"] = str(delegation.path)
                        common = [
                            str(kubectl),
                            f"--kubeconfig={delegation.path}",
                            f"--context={cluster.context}",
                            f"--namespace={namespace}",
                            "--request-timeout=15s",
                        ]
                        result = await _execute(
                            [
                                *common,
                                "exec",
                                "owned-http",
                                "-c",
                                "http",
                                "--",
                                "/bin/sh",
                                "-c",
                                "printf OWNED-INTEROP-EXEC",
                            ],
                            inherited,
                            delegation.directory,
                            30,
                        )
                        checks[mechanism + "_delegated_exec"] = result == b"OWNED-INTEROP-EXEC"
                    checks[mechanism + "_private_config_cleaned"] = not delegation.path.exists()
                    policy = AccessPolicy(False)
                    async with ProcessRunner(policy) as processes:
                        manager = ForwardManager(processes, check_interval=0.1)
                        sessions.before_close = manager.stop_for_client
                        forward = ForwardService(
                            connection,
                            ResourceTarget(
                                identity, "", "pods", namespace, "owned-http", pod.metadata.uid
                            ),
                            policy,
                            partial(current, sessions, connection),
                            environment=environment,
                            directory=directory,
                        )
                        try:
                            manager.start(forward, parse_mappings("0:8080"), "127.0.0.1")
                            live = await observed(manager, ForwardState.READY)
                            await payload(live.ports[0].local)
                            checks[mechanism + "_actual_forward"] = True
                        finally:
                            await manager.close()
                    private_directory = Path(connection.directory.name)
                finally:
                    await sessions.close()
                checks[mechanism + "_session_cleanup"] = not private_directory.exists()
                assert inputs == (cluster_path.read_bytes(), user_path.read_bytes())
            checks["http_connect_actual_transport"] = bool(witness.requests) and all(
                method == "CONNECT" for method, _ in witness.requests
            )
        checks["proxy_lifecycle_drained"] = not witness.active
    finally:
        await admin.close()
    assert cluster.path.read_bytes() == original and all(checks.values())
    return {
        "result": "passed",
        "scope": "owned disposable kind only; no cloud certification",
        "node_image": NODE_IMAGE,
        "python": sys.version.split()[0],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--kubectl", required=True, type=Path)
    parser.add_argument(
        "--evidence", type=Path, default=Path("artifacts/cluster/credential-interop-kind.json")
    )
    args = parser.parse_args()
    previous_path = os.environ.get("PATH")
    os.environ["PATH"] = (
        str(args.kubectl.absolute().parent) + os.pathsep + (previous_path or os.defpath)
    )
    try:
        with owned_cluster(args.kind) as cluster:
            result = asyncio.run(verify(cluster, args.kubectl.absolute()))
    finally:
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path
    result["checks"]["owned_cluster_removed"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
