"""S05: actual kubectl TCP transport, UID loss and cleanup on an owned kind cluster."""

import argparse
import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.forward_presets import ForwardTransport, annotation_preset, resolve_mappings
from kuberich.domain.port_forwards import ForwardState, parse_mappings
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.port_forwards import ForwardInfo, ForwardManager, ForwardService
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
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


async def payload(port: int, *, expected: bytes = b"OWNED-FORWARD-HTTP") -> None:
    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"GET / HTTP/1.0\r\nHost: owned\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            assert b"200 OK" in response and expected in response
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
    namespace = "kuberich-owned-forward"
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
                    metadata=client.V1ObjectMeta(
                        name="owned-http",
                        labels={"app": "owned-http"},
                        annotations={"k9scli.io/auto-port-forwards": "http::0:web,http::0:admin"},
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="http",
                                image=FORWARD_IMAGE,
                                ports=[
                                    client.V1ContainerPort(name="web", container_port=8080),
                                    client.V1ContainerPort(name="admin", container_port=8081),
                                ],
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
                        ports=[client.V1ServicePort(name="http", port=80, target_port=8080)],
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

            raw_pod = connection.api.sanitize_for_serialization(pod)
            preset = annotation_preset(raw_pod, "pods")
            assert preset is not None and preset[1]
            manager.start(
                source("pods"),
                resolve_mappings(preset[0].ports, "pods", raw_pod),
                transport=ForwardTransport.WEBSOCKET,
                intent=preset[0].intent,
            )
            pod_forward = await observed(manager, ForwardState.READY)
            assert (
                dict(manager._live[pod_forward.identity].request.command.environment)[
                    "KUBECTL_PORT_FORWARD_WEBSOCKETS"
                ]
                == "true"
            )
            assert len(pod_forward.ports) == 2
            for bound in pod_forward.ports:
                await payload(bound.local)
            try:
                manager.start(source("pods"), parse_mappings(f"{pod_forward.ports[0].local}:8080"))
            except AppError as error:
                assert "reserves" in str(error)
            else:
                raise AssertionError("An owned listener collision was accepted.")
            occupied = await asyncio.start_server(
                lambda _reader, writer: writer.close(), "127.0.0.1", 0
            )
            try:
                occupied_port = occupied.sockets[0].getsockname()[1]
                manager.start(source("pods"), parse_mappings(f"{occupied_port}:8080"))
                collision = await observed(manager, ForwardState.FAILED)
                assert "Cannot bind" in collision.message and collision.pid is None
            finally:
                occupied.close()
                await occupied.wait_closed()
            sessions.select_namespace("default")
            retained = next(info for info in manager.infos if info.identity == pod_forward.identity)
            assert retained.state is ForwardState.READY
            await manager.stop(pod_forward.identity)
            await gone(pod_forward)
            assert not list(directory.glob("forward-*.json"))
            print(
                "Actual Pod forward: two dynamic TCP mappings, payload, namespace retention and stop passed.",
                flush=True,
            )

            # Reuse an explicitly freed local port; Service port 80 maps to backend 8080.
            manager.start(
                source("services"),
                resolve_mappings(
                    f"{pod_forward.ports[0].local}:http",
                    "services",
                    connection.api.sanitize_for_serialization(service),
                ),
                transport=ForwardTransport.SPDY,
                retries=1,
                intent=f"{pod_forward.ports[0].local}:http",
            )
            service_forward = await observed(manager, ForwardState.READY)
            assert (
                dict(manager._live[service_forward.identity].request.command.environment)[
                    "KUBECTL_PORT_FORWARD_WEBSOCKETS"
                ]
                == "false"
            )
            assert service_forward.ports[0].remote == 8080
            await payload(service_forward.ports[0].local)
            # Change the Service backend deliberately. The old process keeps its
            # original pod until a real disconnect; a bounded retry resolves anew.
            await api.create_namespaced_pod(
                namespace,
                client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        name="owned-alternate", labels={"app": "owned-alternate"}
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="http",
                                image=FORWARD_IMAGE,
                                command=[
                                    "/bin/sh",
                                    "-c",
                                    "mkdir /tmp/www; echo OWNED-FORWARD-HTTP-ALTERNATE >/tmp/www/index.html; exec httpd -f -p 8081 -h /tmp/www",
                                ],
                                readiness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/", port=8081)
                                ),
                            )
                        ]
                    ),
                ),
            )
            async with asyncio.timeout(180):
                while True:
                    alternate = await api.read_namespaced_pod("owned-alternate", namespace)
                    if (
                        alternate.status.container_statuses
                        and alternate.status.container_statuses[0].ready
                    ):
                        break
                    await asyncio.sleep(0.5)
            await api.patch_namespaced_service(
                "owned-http",
                namespace,
                {
                    "spec": {
                        "selector": {"app": "owned-alternate"},
                        "ports": [{"name": "http", "port": 80, "targetPort": 8081}],
                    }
                },
            )
            assert service_forward.pid is not None
            os.kill(service_forward.pid, signal.SIGTERM)
            await observed(manager, ForwardState.RECONNECTING)
            await gone(service_forward)
            rebound = await observed(manager, ForwardState.READY)
            assert rebound.attempt == 1 and rebound.identity == service_forward.identity
            assert rebound.ports[0].remote == 8081
            await payload(rebound.ports[0].local, expected=b"OWNED-FORWARD-HTTP-ALTERNATE")
            await api.delete_namespaced_service("owned-http", namespace)
            deleted = await observed(manager, ForwardState.FAILED)
            assert "404" in deleted.message or "unavailable" in deleted.message
            await gone(rebound)
            assert not list(directory.glob("forward-*.json"))
            print(
                "Actual Service forward: explicit local port, translated backend, payload and deletion cleanup passed.",
                flush=True,
            )

            remote_source = source("pods")
            try:
                manager.start(remote_source, parse_mappings(":8080"), "0.0.0.0")
            except AppError as error:
                assert "explicit permission" in str(error)
            else:
                raise AssertionError("Unreviewed non-loopback forward was accepted.")
            manager.start(remote_source, parse_mappings(":8080"), "0.0.0.0", allow_remote=True)
            remote = await observed(manager, ForwardState.READY)
            await payload(remote.ports[0].local)
            await manager.stop(remote.identity)
            await gone(remote)

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
                "service_reconnect_target_port": 8081,
                "service_backend_replaced": True,
                "transport_modes": ["websocket-preferred", "spdy"],
                "annotation_named_ports": True,
                "remote_bind_optin": True,
                "owned_and_external_listener_collisions": True,
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
