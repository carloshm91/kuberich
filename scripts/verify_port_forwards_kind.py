"""S05: actual kubectl TCP transport, UID loss and cleanup on an owned kind cluster."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kubetrol.config.catalog import load_catalog
from kubetrol.domain.connections import ConnectionRequest
from kubetrol.domain.port_forwards import ForwardState, parse_mappings
from kubetrol.domain.targets import ResourceTarget
from kubetrol.services.access import AccessPolicy
from kubetrol.services.port_forwards import ForwardInfo, ForwardManager, ForwardService
from kubetrol.services.processes import ProcessRunner
from kubetrol.services.sessions import SessionService
from scripts.owned_kind import NODE_IMAGE, OwnedCluster, owned_cluster, run_owned

FORWARD_IMAGE = (
    "busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e"
)


async def observed(manager: ForwardManager, state: ForwardState) -> ForwardInfo:
    async with asyncio.timeout(30):
        while True:
            info = manager.infos[-1]
            if info.state is state:
                return info
            if info.state is ForwardState.FAILED and state is not ForwardState.FAILED:
                raise AssertionError(info.message)
            await asyncio.sleep(0.03)


async def payload(port: int) -> None:
    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"GET / HTTP/1.0\r\nHost: owned\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            assert b"200 OK" in response and b"OWNED-FORWARD-HTTP" in response
        finally:
            writer.close()
            await writer.wait_closed()


async def gone(info: ForwardInfo) -> None:
    assert info.pid is not None
    try:
        os.kill(info.pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Forward child still exists.")
    for bound in info.ports:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", bound.local)
        except OSError:
            continue
        writer.close()
        await writer.wait_closed()
        raise AssertionError("Forward listener still accepts connections.")


async def verify(cluster: OwnedCluster, kubectl: Path) -> dict[str, Any]:
    namespace = "kubetrol-owned-forward"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    sessions = SessionService(load_catalog(request, {}), request)
    policy = AccessPolicy(False)
    before = cluster.path.read_bytes()
    async with ProcessRunner(policy) as processes:
        manager = ForwardManager(processes, check_interval=0.1)
        sessions.before_close = manager.stop_for_client
        try:
            await sessions.connect(cluster.context)
            connection = sessions.client
            identity = sessions.observation.identity
            assert connection is not None and connection.api is not None and identity is not None
            api = client.CoreV1Api(connection.api)
            await api.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            )
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
                                    "mkdir /tmp/www; echo OWNED-FORWARD-HTTP >/tmp/www/index.html; "
                                    "httpd -p 8081 -h /tmp/www; exec httpd -f -p 8080 -h /tmp/www",
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
                    await asyncio.sleep(0.5)
            service = await api.create_namespaced_service(
                namespace,
                client.V1Service(
                    metadata=client.V1ObjectMeta(name="owned-http"),
                    spec=client.V1ServiceSpec(
                        selector={"app": "owned-http"},
                        ports=[client.V1ServicePort(port=80, target_port=8080)],
                    ),
                ),
            )
            directory = Path(connection.directory.name)
            environment = {
                **os.environ,
                "PATH": str(kubectl.parent) + os.pathsep + os.environ.get("PATH", ""),
            }

            def source(resource: str) -> ForwardService:
                target = ResourceTarget(
                    identity,
                    "",
                    resource,
                    namespace,
                    "owned-http",
                    pod.metadata.uid if resource == "pods" else service.metadata.uid,
                )
                return ForwardService(
                    connection,
                    target,
                    policy,
                    lambda: sessions.client is connection,
                    environment=environment,
                    directory=cluster.directory,
                )

            manager.start(source("pods"), parse_mappings(":8080,:8081"))
            pod_forward = await observed(manager, ForwardState.READY)
            assert len(pod_forward.ports) == 2
            for bound in pod_forward.ports:
                await payload(bound.local)
            sessions.select_namespace("default")
            assert manager.infos[-1].state is ForwardState.READY
            await manager.stop(pod_forward.identity)
            await gone(pod_forward)
            assert not list(directory.glob("forward-*.json"))
            print(
                "Actual Pod forward: two dynamic TCP mappings, payload, namespace retention and stop passed.",
                flush=True,
            )

            # Reuse an explicitly freed local port; Service port 80 maps to backend 8080.
            manager.start(source("services"), parse_mappings(f"{pod_forward.ports[0].local}:80"))
            service_forward = await observed(manager, ForwardState.READY)
            assert service_forward.ports[0].remote == 8080
            await payload(service_forward.ports[0].local)
            await api.delete_namespaced_service("owned-http", namespace)
            deleted = await observed(manager, ForwardState.FAILED)
            assert "404" in deleted.message or "unavailable" in deleted.message
            await gone(service_forward)
            assert not list(directory.glob("forward-*.json"))
            print(
                "Actual Service forward: explicit local port, translated backend, payload and deletion cleanup passed.",
                flush=True,
            )

            manager.start(source("pods"), parse_mappings(":8080"))
            reconnect_forward = await observed(manager, ForwardState.READY)
            await payload(reconnect_forward.ports[0].local)
            await sessions.connect(cluster.context)
            reconnected = manager.infos[-1]
            assert reconnected.state is ForwardState.STOPPED
            assert reconnected.message == "Stopped for connection change."
            await gone(reconnect_forward)
            assert not directory.exists()
            print(
                "Actual reconnect: child and listener stopped before old TLS directory cleanup.",
                flush=True,
            )

            current = sessions.client
            current_identity = sessions.observation.identity
            assert current is not None and current.api is not None and current_identity is not None
            final_source = ForwardService(
                current,
                ResourceTarget(
                    current_identity, "", "pods", namespace, "owned-http", pod.metadata.uid
                ),
                policy,
                lambda: sessions.client is current,
                environment=environment,
                directory=cluster.directory,
            )
            manager.start(final_source, parse_mappings(":8080"))
            exit_forward = await observed(manager, ForwardState.READY)
            await payload(exit_forward.ports[0].local)
            await manager.close()
            await gone(exit_forward)
            exited = manager.infos[-1]
            assert exited.state is ForwardState.STOPPED
            assert manager.active_count == processes.active_count == 0
            assert not list(Path(current.directory.name).glob("forward-*.json"))
            assert cluster.path.read_bytes() == before
            return {
                "pod_dynamic_mappings": 2,
                "service_target_port": 8080,
                "checks": [
                    "real-http",
                    "stop",
                    "repeat",
                    "namespace-retained",
                    "service-deleted",
                    "reconnect",
                    "application-exit",
                ],
                "node_image": NODE_IMAGE,
                "http_image": FORWARD_IMAGE,
            }
        finally:
            await manager.close()
            await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--evidence", default="artifacts/cluster/port-forwards.json")
    arguments = parser.parse_args()
    kubectl = Path(arguments.kubectl).absolute()
    version = json.loads(run_owned([str(kubectl), "version", "--client", "-o", "json"], os.environ))
    assert version["clientVersion"]["gitVersion"] == "v1.36.4"
    with owned_cluster(arguments.kind) as cluster:
        result = asyncio.run(verify(cluster, kubectl))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    evidence = Path(arguments.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Real owned-kind port-forward trials passed.", flush=True)


if __name__ == "__main__":
    main()
