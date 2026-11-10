"""Prove real Vegeta load, exact Pod forwarding, retained results and owned cancellation."""

import argparse
import asyncio
import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as sdk

from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.config.catalog import load_catalog
from kuberich.domain.benchmarks import LoadOptions, RequestOptions
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.targets import ResourceTarget
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmarks import BenchmarkManager, BenchmarkService, BenchmarkState
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import NODE_IMAGE, OwnedCluster, owned_cluster, run_owned
from scripts.verify_node_maintenance_kind import KUBECTL_SHA256
from scripts.verify_port_forwards_kind import FORWARD_IMAGE, gone

NAMESPACE = "kuberich-benchmark"
HTTP_PROGRAM = """
mkdir -p /tmp/www/cgi-bin
printf '#!/bin/sh\nprintf "request\\n" >> /tmp/requests\nprintf "Content-Type: text/plain\\r\\n\\r\\nOWNED-BENCHMARK\\n"\n' > /tmp/www/cgi-bin/count
chmod 700 /tmp/www/cgi-bin/count
: >/tmp/requests
exec httpd -f -p 8080 -h /tmp/www
"""


def source_identity() -> dict[str, str]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True).strip()

    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Commit and freeze clean tracked source before the benchmark proof.")
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def require_gone(pids: tuple[int, ...]) -> None:
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise AssertionError("An owned benchmark child still exists.")


async def verify(cluster: OwnedCluster, kubectl: Path, vegeta: Path) -> dict[str, Any]:
    before = cluster.path.read_bytes()
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    sessions = SessionService(load_catalog(request, {}), request)
    policy = AccessPolicy(False)
    async with ProcessRunner(policy) as processes:
        forwards = ForwardManager(processes, check_interval=0.1)
        store = BenchmarkStore(cluster.directory / "saved-benchmarks")
        manager = BenchmarkManager(forwards, store)

        async def close_client(client: Any) -> None:
            await manager.close_for_client(client)
            await forwards.stop_for_client(client)

        sessions.before_close = close_client
        try:
            await sessions.connect(cluster.context)
            connection, identity = sessions.client, sessions.observation.identity
            assert connection is not None and connection.api is not None and identity is not None
            core = sdk.CoreV1Api(connection.api)
            await core.create_namespace(sdk.V1Namespace(metadata=sdk.V1ObjectMeta(name=NAMESPACE)))
            await core.create_namespaced_pod(
                NAMESPACE,
                sdk.V1Pod(
                    metadata=sdk.V1ObjectMeta(name="owned-http", labels={"app": "owned-http"}),
                    spec=sdk.V1PodSpec(
                        containers=[
                            sdk.V1Container(
                                name="http",
                                image=FORWARD_IMAGE,
                                command=["/bin/sh", "-c", HTTP_PROGRAM],
                                ports=[sdk.V1ContainerPort(name="web", container_port=8080)],
                                readiness_probe=sdk.V1Probe(
                                    tcp_socket=sdk.V1TCPSocketAction(port=8080), period_seconds=1
                                ),
                            )
                        ]
                    ),
                ),
            )
            async with asyncio.timeout(180):
                while True:
                    pod = await core.read_namespaced_pod("owned-http", NAMESPACE)
                    if pod.status.container_statuses and pod.status.container_statuses[0].ready:
                        break
                    await asyncio.sleep(0.2)
            service = await core.create_namespaced_service(
                NAMESPACE,
                sdk.V1Service(
                    metadata=sdk.V1ObjectMeta(name="owned-http"),
                    spec=sdk.V1ServiceSpec(
                        selector={"app": "owned-http"},
                        ports=[sdk.V1ServicePort(port=80, target_port="web")],
                    ),
                ),
            )
            target = ResourceTarget(
                identity, "", "services", NAMESPACE, "owned-http", service.metadata.uid
            )
            env = {
                **os.environ,
                "PATH": str(kubectl.parent) + os.pathsep + os.environ.get("PATH", ""),
            }
            settings = BenchmarkSettings(vegeta)

            def create() -> BenchmarkService:
                return manager.create(
                    connection,
                    target,
                    policy,
                    lambda: sessions.client is connection,
                    settings=settings,
                    environment=env,
                    directory=cluster.directory,
                )

            def count_sync() -> int:
                output = run_owned(
                    [
                        str(kubectl),
                        f"--kubeconfig={cluster.path}",
                        f"--context={cluster.context}",
                        f"--namespace={NAMESPACE}",
                        "exec",
                        "owned-http",
                        "--",
                        "wc",
                        "-l",
                        "/tmp/requests",
                    ],
                    env,
                )
                return int(output.split()[0])

            async def count() -> int:
                return await asyncio.to_thread(count_sync)

            owner = create()
            backends = await owner.candidates()
            assert len(backends) == 1 and backends[0].pod.uid == pod.metadata.uid
            review = await owner.review(
                backends[0],
                RequestOptions(
                    target="/cgi-bin/count",
                    headers=(("Authorization", "Bearer synthetic-private"),),
                ),
                LoadOptions(duration_seconds=2, timeout_seconds=1),
            )
            result = await owner.run(review)
            assert (
                result.completion == "complete"
                and result.metrics is not None
                and result.metrics.attempts == 2
            )
            assert await count() == 2 and not owner.save_failed
            pids = owner.process_ids
            require_gone(pids)
            assert forwards.active_count == processes.active_count == 0
            assert not list(Path(connection.directory.name).glob("benchmark-*"))
            saved = await store.scan()
            assert (
                len(saved) == 1
                and await BenchmarkStore(store.default_root).read(saved[0].ref) == result
            )
            assert (
                b"synthetic-private"
                not in (saved[0].ref.directory.path / saved[0].ref.name).read_bytes()
            )
            await owner.stop_owned()
            loss = create()
            selected = (await loss.candidates())[0]
            review2 = await loss.review(
                selected,
                RequestOptions(target="/cgi-bin/count"),
                LoadOptions(rate=5, duration_seconds=30, timeout_seconds=1),
            )
            running = asyncio.create_task(loss.run(review2))
            async with asyncio.timeout(30):
                while loss.state is not BenchmarkState.RUNNING or await count() < 3:
                    assert not running.done()
                    await asyncio.sleep(0.03)
            forward = forwards.infos[-1]
            assert forward.state is ForwardState.READY and forward.pid is not None
            os.kill(forward.pid, signal.SIGKILL)
            incomplete = await asyncio.wait_for(running, 10)
            assert incomplete.completion == "target_lost" and incomplete.metrics is None
            after_loss = await count()
            await asyncio.sleep(0.4)
            assert await count() == after_loss
            await gone(forward)
            require_gone(loss.process_ids)
            assert forwards.active_count == processes.active_count == loss.operation_count == 0
            assert not list(Path(connection.directory.name).glob("benchmark-*"))
            assert not list(Path(connection.directory.name).glob("forward-*.json"))
            await loss.stop_owned()
            assert manager.active_count == 0 and cluster.path.read_bytes() == before
            return {
                "complete_requests": 2,
                "loss_requests_total": after_loss,
                "source_pod_uid_checked": True,
                "service_uid_checked": True,
                "single_backend": True,
                "dedicated_forward_retries": 0,
                "persistence_restart": True,
                "load_drained_after_forward_loss": True,
                "private_files_removed": True,
                "owned_process_ids": [*pids, *loss.process_ids],
                "children_reaped": True,
                "node_image": NODE_IMAGE,
                "http_image": FORWARD_IMAGE,
            }
        finally:
            await manager.close()
            await forwards.close()
            await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", type=Path, required=True)
    parser.add_argument("--kubectl", type=Path, required=True)
    parser.add_argument("--vegeta", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.kind, args.kubectl, args.vegeta):
        if not path.is_absolute():
            raise ValueError("Use explicit absolute verified tool paths.")
    if sha256_file(args.kind) != KIND_SHA256 or sha256_file(args.kubectl) != KUBECTL_SHA256:
        raise ValueError("Owned cluster tools differ from the reviewed pins.")
    identity = source_identity()
    tool_digest = hashlib.sha256(args.vegeta.read_bytes()).hexdigest()
    with owned_cluster(str(args.kind)) as cluster:
        result = asyncio.run(verify(cluster, args.kubectl, args.vegeta))
        result["cluster"] = cluster.name
    result.update(source=identity, vegeta_sha256=tool_digest, owned_cluster_deleted=True)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Real owned-kind HTTP benchmark trials passed.", flush=True)


if __name__ == "__main__":
    main()
