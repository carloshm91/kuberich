"""S04: real CLI/TTY exec inside a newly created, explicitly owned kind cluster."""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import yaml
from kubernetes_asyncio import client

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.config.catalog import load_catalog
from kubetrol.domain.connections import ConnectionRequest
from scripts.verify_eks_auth import verify as verify_eks_auth
from tests.terminal.pty_support import TerminalSession

NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)
SHELL_IMAGE = "alpine@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b"


async def prepare(path: Path, context: str, namespace: str) -> tuple[dict, str]:
    request = ConnectionRequest(kubeconfig=str(path), context=context, namespace=namespace)
    selected = load_catalog(request, {}).select(context)
    session = KubernetesSession(selected, 15)
    try:
        await session.open()
        assert session.api is not None
        api = client.CoreV1Api(session.api)
        await api.create_namespace({"metadata": {"name": namespace}})
        await api.create_namespaced_pod(
            namespace,
            {
                "metadata": {"name": "owned-shell-pod", "namespace": namespace},
                "spec": {
                    "containers": [
                        {
                            "name": name,
                            "image": SHELL_IMAGE,
                            "command": ["/bin/sh", "-c", "while true; do sleep 60; done"],
                            "env": [
                                {"name": "KUBETROL_OWNED_CONTAINER", "value": name},
                                {"name": "PS1", "value": "OWNED-SHELL> "},
                            ],
                        }
                        for name in ["app-a", "app-b"]
                    ]
                },
            },
        )
        async with asyncio.timeout(180):
            while True:
                pod = await api.read_namespaced_pod("owned-shell-pod", namespace)
                if pod.status.container_statuses and all(
                    value.ready for value in pod.status.container_statuses
                ):
                    break
                await asyncio.sleep(0.5)
        await api.create_namespaced_service_account(
            namespace, {"metadata": {"name": "shell-reader"}}
        )
        rbac = client.RbacAuthorizationV1Api(session.api)
        await rbac.create_namespaced_role(
            namespace,
            {
                "metadata": {"name": "shell-reader"},
                "rules": [
                    {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]}
                ],
            },
        )
        await rbac.create_namespaced_role_binding(
            namespace,
            {
                "metadata": {"name": "shell-reader"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "shell-reader",
                },
                "subjects": [
                    {"kind": "ServiceAccount", "name": "shell-reader", "namespace": namespace}
                ],
            },
        )
        await api.create_namespaced_service_account(
            namespace, {"metadata": {"name": "shell-operator"}}
        )
        await rbac.create_namespaced_role(
            namespace,
            {
                "metadata": {"name": "shell-operator"},
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["pods", "pods/log"],
                        "verbs": ["get", "list", "watch"],
                    },
                    {"apiGroups": [""], "resources": ["pods/exec"], "verbs": ["create"]},
                ],
            },
        )
        await rbac.create_namespaced_role_binding(
            namespace,
            {
                "metadata": {"name": "shell-operator"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "shell-operator",
                },
                "subjects": [
                    {"kind": "ServiceAccount", "name": "shell-operator", "namespace": namespace}
                ],
            },
        )
        token = await api.create_namespaced_service_account_token(
            "shell-reader",
            namespace,
            {"spec": {"expirationSeconds": 1800}},
        )
        return {"uid": pod.metadata.uid, "namespace": namespace}, token.status.token
    finally:
        await session.close()


def trial(
    path: Path,
    context: str,
    namespace: str,
    directory: Path,
    *,
    scenario: str,
    kubectl: Path,
    launch_overrides: tuple[str, ...] = (),
) -> None:
    directory.mkdir()
    preferences = {"schema_version": 1}
    if scenario == "configured":
        preferences["shell"] = ["/bin/sh", "-i"]
    if scenario == "missing-shell":
        preferences["shell"] = ["/no-such-owned-shell"]
    (directory / "preferences.yaml").write_text(yaml.safe_dump(preferences))
    wrapper = directory / "launch.py"
    wrapper.write_text(
        "import os,sys\nfrom pathlib import Path\nos.environ['PATH']=str(Path(sys.argv[1]).parent)+os.pathsep+os.environ.get('PATH','')\nos.execv(sys.argv[2],sys.argv[2:])\n"
    )
    command = [
        sys.executable,
        str(wrapper),
        str(kubectl),
        sys.executable,
        "-m",
        "kubetrol",
        "--kubeconfig",
        str(path),
        "--context",
        context,
        "--namespace",
        namespace,
        *launch_overrides,
    ]
    before = path.read_bytes()
    attempts = 2 if scenario == "success" else 1
    try:
        with TerminalSession(command, directory) as terminal:
            terminal.wait_for(b"owned-shell-pod", timeout=30)
            terminal.wait_for(b"1 pod", timeout=30)
            if scenario == "success":
                changed = yaml.safe_load(before)
                changed["clusters"][0]["cluster"]["server"] = "https://127.0.0.1:9"
                path.write_text(yaml.safe_dump(changed))
            marker = terminal.send(b":shell\r")
            terminal.wait_for(b"Containers", since=marker)
            terminal.wait_for(b"app-b", since=marker)
            terminal.send(b"\x1b[B")
            for attempt in range(attempts):
                marker = terminal.send(b"s")
                terminal.wait_for_screen("Kubetrol · Container shell", timeout=30)
                terminal.wait_for_screen("Context: kubetrol-test-Alias")
                terminal.wait_for_screen("Pod: kubetrol-shell-test/owned-shell-pod")
                terminal.wait_for_screen("Container: app-b")
                assert b"\x1b[?1049l" not in terminal.transcript[marker:]
                if scenario in {
                    "denied",
                    "token-denied",
                    "impersonation-denied",
                    "missing-shell",
                    "eks-denied",
                    "aks-denied",
                }:
                    terminal.wait_for(b"kubectl exec failed", since=marker, timeout=30)
                    terminal.wait_for(b"pods/exec", since=marker)
                    assert b"OWNED-SHELL> " not in terminal.transcript[marker:]
                    break
                terminal.wait_for_screen("OWNED-SHELL> ", timeout=30)
                marker = terminal.send(b"printf 'REMOTE_%s\\n' \"$KUBETROL_OWNED_CONTAINER\"\n")
                terminal.wait_for_screen("REMOTE_app-b")
                marker = terminal.resize(80, 25)
                terminal.wait_for_screen("╰" + "─" * 78 + "╯")
                terminal.send(b"stty size\n")
                terminal.wait_for_screen("19 78")
                if scenario == "success" and attempt == 0:
                    marker = terminal.send(b"vi /tmp/owned-shell-trial\n")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial 1/1")
                    marker = terminal.resize(100, 30)
                    terminal.wait_for_screen("╰" + "─" * 98 + "╯")
                    terminal.wait_for_screen("Container: app-b")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial 1/1", row=27)
                    marker = terminal.resize(80, 25)
                    terminal.wait_for_screen("╰" + "─" * 78 + "╯")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial 1/1", row=22)
                    marker = terminal.send(b"iOWNED_REMOTE_EDIT")
                    terminal.wait_for_screen("OWNED_REMOTE_EDIT")
                    terminal.wait_for_screen("I /tmp/owned-shell-trial", row=22)
                    marker = terminal.send(b"\x1b")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial", row=22)
                    marker = terminal.send(b":wq\r")
                    assert b"\x1b[?1049l" not in terminal.transcript[marker:]
                    terminal.wait_for_screen("OWNED-SHELL> ")
                    marker = terminal.send(b"cat /tmp/owned-shell-trial\n")
                    terminal.wait_for_screen("OWNED_REMOTE_EDIT")
                    marker = terminal.send(b"printf 'SLEEP_%s\\n' READY; sleep 30\n")
                    terminal.wait_for_screen("SLEEP_READY")
                    terminal.send(b"\x03")
                    terminal.wait_for_screen("OWNED-SHELL> ")
                    marker = terminal.send(b"printf 'AFTER_%s\\n' \"$KUBETROL_OWNED_CONTAINER\"\n")
                    terminal.wait_for_screen("AFTER_app-b")
                marker = terminal.send(b"exit\n")
                terminal.wait_for(b"Shell closed", since=marker)
                terminal.resize(100, 30)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Sort NAME", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for(b"Containers", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Sort NAME", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("kind-shell-" + scenario)
    finally:
        path.write_bytes(before)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--evidence", default="artifacts/cluster/shell.json")
    arguments = parser.parse_args()
    kubectl = Path(arguments.kubectl).absolute()
    version = json.loads(
        subprocess.check_output([str(kubectl), "version", "--client", "-o", "json"])
    )["clientVersion"]["gitVersion"]
    assert version == "v1.36.4", "Use the matching verified kubectl 1.36.4 binary for this trial."
    owned_cluster_name = "kubetrol-test-" + uuid4().hex[:12]
    namespace = "kubetrol-shell-test"
    with TemporaryDirectory(prefix="kubetrol-shell-kind-") as folder:
        directory = Path(folder)
        path = directory / "owned-kubeconfig"
        environment = {**os.environ, "KUBECONFIG": str(path)}
        try:
            print("Creating owned disposable kind cluster.", flush=True)
            subprocess.run(
                [
                    arguments.kind,
                    "create",
                    "cluster",
                    "--name",
                    owned_cluster_name,
                    "--kubeconfig",
                    str(path),
                    "--image",
                    NODE_IMAGE,
                    "--wait",
                    "180s",
                ],
                env=environment,
                check=True,
                timeout=300,
            )
            data = yaml.safe_load(path.read_text())
            context = "kind-" + owned_cluster_name
            assert data["current-context"] == context
            data["contexts"].append(
                {"name": "kubetrol-test-Alias", "context": dict(data["contexts"][0]["context"])}
            )
            context = "kubetrol-test-Alias"
            path.write_text(yaml.safe_dump(data))
            print("Preparing owned two-container shell and limited-RBAC fixtures.", flush=True)
            resource, token = asyncio.run(prepare(path, context, namespace))
            for scenario in ["success", "configured", "missing-shell"]:
                trial(
                    path,
                    context,
                    namespace,
                    directory / scenario,
                    scenario=scenario,
                    kubectl=kubectl,
                )
                print("Real shell trial passed: " + scenario, flush=True)
            captured = yaml.safe_load(path.read_text())
            captured["clusters"].append(
                {
                    "name": "owned-override-cluster",
                    "cluster": dict(captured["clusters"][0]["cluster"]),
                }
            )
            captured["users"].append(
                {"name": "owned-override-user", "user": dict(captured["users"][0]["user"])}
            )
            path.write_text(yaml.safe_dump(captured))
            material_paths = {}
            for material_name, source in [
                ("certificate-authority", captured["clusters"][0]["cluster"]),
                ("client-certificate", captured["users"][0]["user"]),
                ("client-key", captured["users"][0]["user"]),
            ]:
                material_path = directory / material_name
                material_path.write_bytes(
                    base64.b64decode(source[material_name + "-data"], validate=True)
                )
                material_path.chmod(0o600)
                material_paths[material_name] = str(material_path)
            overrides = (
                "--cluster",
                "owned-override-cluster",
                "--user",
                "owned-override-user",
                "--refresh",
                "0.2",
                "--insecure-skip-tls-verify=false",
                "--certificate-authority",
                material_paths["certificate-authority"],
                "--client-certificate",
                material_paths["client-certificate"],
                "--client-key",
                material_paths["client-key"],
                "--as",
                f"system:serviceaccount:{namespace}:shell-operator",
                "--as-group",
                "system:authenticated",
                "--as-group",
                "system:serviceaccounts",
            )
            trial(
                path,
                context,
                namespace,
                directory / "overrides",
                scenario="overrides",
                kubectl=kubectl,
                launch_overrides=overrides,
            )
            print("Real TLS/alias/impersonated shell overrides passed.", flush=True)
            trial(
                path,
                context,
                namespace,
                directory / "impersonation-denied",
                scenario="impersonation-denied",
                kubectl=kubectl,
                launch_overrides=(
                    "--as",
                    f"system:serviceaccount:{namespace}:shell-reader",
                    "--as-group",
                    "system:authenticated",
                ),
            )
            trial(
                path,
                context,
                namespace,
                directory / "token-denied",
                scenario="token-denied",
                kubectl=kubectl,
                launch_overrides=("--token", token),
            )
            limited = yaml.safe_load(path.read_text())
            limited["users"] = [{"name": "shell-reader", "user": {"token": token}}]
            for value in limited["contexts"]:
                value["context"]["user"] = "shell-reader"
            restricted = directory / "restricted-config"
            restricted.write_text(yaml.safe_dump(limited))
            restricted.chmod(0o600)
            trial(
                restricted,
                context,
                namespace,
                directory / "denied",
                scenario="denied",
                kubectl=kubectl,
            )
            # EKS-shaped exec contract against a real API and real kubectl.
            # The helper is a local synthetic shim using this owned kind token;
            # none of these observations establish real AWS/EKS qualification.
            eks_directory = directory / "eks-contract"
            eks_directory.mkdir(mode=0o700)
            token_path = eks_directory / "owned-token"
            token_path.write_text(token)
            token_path.chmod(0o600)
            helper = eks_directory / "aws"
            helper.write_text(
                f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
                "from datetime import datetime,timedelta,timezone\n"
                "assert sys.argv[1:]==['eks','get-token','--cluster-name','synthetic-kind','--output','json','--role-arn','synthetic-role']\n"
                "assert os.environ['AWS_PROFILE']=='synthetic-kind-profile'\n"
                "info=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\n"
                "assert info['spec']['interactive'] is False\n"
                f"token=Path({str(token_path)!r}).read_text()\n"
                "print(json.dumps({'kind':'ExecCredential','apiVersion':info['apiVersion'],'status':{'token':token,'expirationTimestamp':(datetime.now(timezone.utc)+timedelta(minutes=14)).isoformat()}}))\n"
            )
            helper.chmod(0o700)
            eks = yaml.safe_load(restricted.read_text())
            eks["users"][0]["user"] = {
                "exec": {
                    "apiVersion": "client.authentication.k8s.io/v1beta1",
                    "command": str(helper),
                    "args": [
                        "eks",
                        "get-token",
                        "--cluster-name",
                        "synthetic-kind",
                        "--output",
                        "json",
                        "--role-arn",
                        "synthetic-role",
                    ],
                    "env": [{"name": "AWS_PROFILE", "value": "synthetic-kind-profile"}],
                }
            }
            eks_path = eks_directory / "owned-config"
            eks_path.write_text(yaml.safe_dump(eks))
            eks_path.chmod(0o600)
            eks_evidence = asyncio.run(
                verify_eks_auth(
                    ConnectionRequest(
                        kubeconfig=str(eks_path), context=context, namespace=namespace, timeout=30
                    ),
                    kubectl,
                )
            )
            trial(
                eks_path,
                context,
                namespace,
                directory / "eks-denied",
                scenario="eks-denied",
                kubectl=kubectl,
            )
            print(
                "Synthetic EKS helper, actual kubectl reads and exec RBAC denial passed on owned kind.",
                flush=True,
            )
            # AKS uses the same real API/token identity, with declared Azure
            # helper arguments/env. No Entra login or tenant request is made.
            azure_helper = eks_directory / "kubelogin"
            azure_helper.write_text(
                f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
                "from datetime import datetime,timedelta,timezone\n"
                "assert sys.argv[1:]==['get-token','--server-id','synthetic-kind','--login','workloadidentity']\n"
                "assert os.environ['AZURE_TENANT_ID']=='synthetic-kind-tenant'\n"
                "assert os.environ['AZURE_FEDERATED_TOKEN_FILE']=='synthetic-declared-jwt'\n"
                "info=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\n"
                "assert info['spec']['interactive'] is False\n"
                f"token=Path({str(token_path)!r}).read_text()\n"
                "print(json.dumps({'kind':'ExecCredential','apiVersion':info['apiVersion'],'status':{'token':token,'expirationTimestamp':(datetime.now(timezone.utc)+timedelta(minutes=14)).isoformat()}}))\n"
            )
            azure_helper.chmod(0o700)
            aks = yaml.safe_load(restricted.read_text())
            aks["users"][0]["user"] = {
                "exec": {
                    "apiVersion": "client.authentication.k8s.io/v1",
                    "interactiveMode": "Never",
                    "command": str(azure_helper),
                    "args": [
                        "get-token",
                        "--server-id",
                        "synthetic-kind",
                        "--login",
                        "workloadidentity",
                    ],
                    "env": [
                        {"name": "AZURE_TENANT_ID", "value": "synthetic-kind-tenant"},
                        {"name": "AZURE_FEDERATED_TOKEN_FILE", "value": "synthetic-declared-jwt"},
                    ],
                }
            }
            aks_path = eks_directory / "owned-azure-config"
            aks_path.write_text(yaml.safe_dump(aks))
            aks_path.chmod(0o600)
            aks_evidence = asyncio.run(
                verify_eks_auth(
                    ConnectionRequest(
                        kubeconfig=str(aks_path), context=context, namespace=namespace, timeout=30
                    ),
                    kubectl,
                    provider="aks",
                )
            )
            trial(
                aks_path,
                context,
                namespace,
                directory / "aks-denied",
                scenario="aks-denied",
                kubectl=kubectl,
            )
            print(
                "Synthetic Azure helper, actual kubectl reads and exec RBAC denial passed on owned kind.",
                flush=True,
            )
            output = Path(arguments.evidence)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "result": "passed",
                        "kind": "0.33.0",
                        "kubernetes": "1.36.4",
                        "kubectl": version,
                        "node_image": NODE_IMAGE,
                        "shell_image": SHELL_IMAGE,
                        "owned_cluster": owned_cluster_name,
                        "resource": resource,
                        "real_two_container_selection": True,
                        "embedded_shell_and_persistent_captured_heading": True,
                        "configured_shell": True,
                        "changed_source_config_does_not_retarget": True,
                        "real_keyboard_resize_ctrl_c": True,
                        "real_fullscreen_vi": True,
                        "repeated_shell_return": True,
                        "missing_shell_actionable": True,
                        "real_rbac_exec_denial": True,
                        "terminal_restored": True,
                        "explicit_cluster_user_tls_overrides": True,
                        "explicit_token_replaces_client_certificates": True,
                        "impersonated_shell_and_actual_rbac_denial": True,
                        "synthetic_eks_exec_contract_on_real_kind": eks_evidence,
                        "synthetic_eks_real_kubectl_exec_denial": True,
                        "real_aws_eks_qualified": False,
                        "synthetic_aks_exec_contract_on_real_kind": aks_evidence,
                        "synthetic_aks_real_kubectl_exec_denial": True,
                        "real_azure_aks_qualified": False,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                "Real Kubernetes shell, fullscreen program, permissions and return passed.",
                flush=True,
            )
        finally:
            subprocess.run(
                [arguments.kind, "delete", "cluster", "--name", owned_cluster_name],
                env=environment,
                check=True,
                timeout=90,
            )
            remaining = subprocess.check_output(
                [arguments.kind, "get", "clusters"], text=True
            ).splitlines()
            assert owned_cluster_name not in remaining, "The owned cluster must be deleted."
            print("Owned disposable cluster deleted and absence verified.", flush=True)


if __name__ == "__main__":
    main()
