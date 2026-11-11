"""Prove real Vegeta load, exact Pod forwarding, retained results and owned cancellation."""

import argparse
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as sdk

from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.config.catalog import load_catalog
from kuberich.domain.benchmarks import LoadOptions, RequestOptions
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmarks import BenchmarkManager, BenchmarkService, BenchmarkState
from kuberich.services.port_forwards import ForwardInfo, ForwardManager
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from scripts.benchmark_tools import VEGETA_COMMIT, verify_benchmark_binary
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


VERIFY_SECONDS = 300
PROOF_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/benchmark_tools.py",
    "scripts/benchmark_native.py",
    "scripts/owned_kind.py",
    "scripts/diagnostics_tools.py",
    "scripts/verify_node_maintenance_kind.py",
    "scripts/verify_port_forwards_kind.py",
    "scripts/verify_benchmarks_kind.py",
    "tests/support/benchmark_terminal.py",
    "tests/support/benchmark_forward.c",
    "tests/terminal/pty_support.py",
)
BENCHMARK_CHECKS = (
    "review-without-traffic",
    "exact-service-and-ready-pod",
    "single-backend-owned-forward",
    "actual-vegeta-statistics",
    "redacted-persistence-and-restart",
    "observed-forward-loss-cancels",
    "replacement-traffic-stops-after-drain",
    "no-forward-reconnect-or-review-replay",
    "children-listeners-private-files-drained",
    "caller-kubeconfig-preserved",
)


@dataclass
class ReplacementTraffic:
    """Keep the cancellation window distinct from traffic after confirmed drain."""

    drained: bool = False
    connections_before_drain: int = 0
    connections_after_drain: int = 0
    requests_before_drain: int = 0
    requests_after_drain: int = 0

    def connect(self) -> None:
        if self.drained:
            self.connections_after_drain += 1
        else:
            self.connections_before_drain += 1

    def request(self) -> None:
        if self.drained:
            self.requests_after_drain += 1
        else:
            self.requests_before_drain += 1

    def snapshot(self) -> dict[str, bool | int]:
        return asdict(self)

    def require_stopped(self) -> None:
        assert self.drained and self.connections_after_drain == self.requests_after_drain == 0


async def require_retired(
    owner: BenchmarkService, review: Any, forwards: ForwardManager, identity: Any
) -> None:
    try:
        forwards.owned_source(identity, 0)
    except AppError:
        pass
    else:
        raise AssertionError("A lost forward became READY again.")
    try:
        await owner.run(review)
    except AppError:
        pass
    else:
        raise AssertionError("A consumed benchmark review was replayed.")


def input_hashes(root: Path) -> dict[str, str]:
    paths = [
        *(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        *(root / name for name in PROOF_INPUTS),
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def source_identity(root: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True, timeout=10).strip()

    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Commit and freeze clean tracked source before the benchmark proof.")
    return git("rev-parse", "HEAD")


def require_gone(pids: tuple[int, ...]) -> None:
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise AssertionError("An owned benchmark child still exists.")


async def verify(
    cluster: OwnedCluster, progress: dict[str, Any], kubectl: Path, vegeta: Path
) -> dict[str, Any]:
    before = cluster.path.read_bytes()
    progress["phase"] = "owned-fixture-setup"
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

            progress["phase"] = "review-without-traffic"
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
            assert await count() == 0
            progress["phase"] = "actual-vegeta-complete"
            result = await owner.run(review)
            assert (
                result.completion == "complete"
                and result.metrics is not None
                and result.metrics.attempts == 2
            )
            assert await count() == 2 and not owner.save_failed
            pids = owner.process_ids
            progress["owned_process_ids"] = list(pids)
            require_gone(pids)
            progress["complete_run_children_reaped"] = True
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
            progress["phase"] = "forward-loss-cancellation"
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
            observed_loss = asyncio.Event()

            def lost(info: ForwardInfo) -> None:
                if info.identity == forward.identity and info.state is ForwardState.FAILED:
                    observed_loss.set()

            unsubscribe = forwards.subscribe(lost)
            traffic = ReplacementTraffic()
            handlers: set[asyncio.Task[None]] = set()
            handler_errors: list[str] = []
            progress["replacement_traffic"] = traffic.snapshot()
            progress["owned_process_ids"] = [*pids, *loss.process_ids]
            progress["owned_forward_pid"] = forward.pid

            async def replacement(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ) -> None:
                try:
                    async with asyncio.timeout(1):
                        data = await reader.read(4096)
                    if data:
                        traffic.request()
                        progress["replacement_traffic"] = traffic.snapshot()
                except (OSError, TimeoutError):
                    pass
                finally:
                    writer.close()
                    with suppress(OSError):
                        await writer.wait_closed()

            def completed(task: asyncio.Task[None]) -> None:
                handlers.discard(task)
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        handler_errors.append(type(error).__name__)
                        progress["replacement_handler_errors"] = list(handler_errors)

            def accepted(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                traffic.connect()
                progress["replacement_traffic"] = traffic.snapshot()
                task = asyncio.create_task(replacement(reader, writer))
                handlers.add(task)
                task.add_done_callback(completed)

            os.kill(forward.pid, signal.SIGKILL)
            await asyncio.wait_for(observed_loss.wait(), 10)
            unsubscribe()
            progress["forward_loss_observed"] = True
            replacement_server = await asyncio.start_server(
                accepted, "127.0.0.1", forward.ports[0].local, reuse_address=True
            )
            try:
                incomplete = await asyncio.wait_for(running, 10)
                require_gone(loss.process_ids)
                progress["loss_run_children_reaped"] = True
                # Finish handlers admitted during cancellation before declaring
                # the post-drain observation window. In-flight requests cannot
                # be retroactively unsent by the forward-loss notification.
                while handlers:
                    await asyncio.gather(*tuple(handlers))
                assert not handler_errors
                traffic.drained = True
                progress["replacement_traffic"] = traffic.snapshot()
                await require_retired(loss, review2, forwards, forward.identity)
                progress["retired_forward_and_review_refused"] = True
                await asyncio.sleep(0.4)
                traffic.require_stopped()
            finally:
                replacement_server.close()
                await replacement_server.wait_closed()
                for handler in tuple(handlers):
                    handler.cancel()
                await asyncio.gather(*tuple(handlers), return_exceptions=True)
                progress["replacement_handlers_drained"] = True
                progress["replacement_traffic"] = traffic.snapshot()
                assert not handler_errors
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
                "checks": list(BENCHMARK_CHECKS),
                "phase": "verified",
                "replacement_traffic": traffic.snapshot(),
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
            progress["application_cleanup_complete"] = True
            require_gone(tuple(progress.get("owned_process_ids", ())))
            progress["recorded_children_reaped_after_cleanup"] = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", type=Path, required=True)
    parser.add_argument("--kubectl", type=Path, required=True)
    parser.add_argument("--vegeta", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.evidence.exists() or args.evidence.is_symlink():
        raise ValueError("Use fresh benchmark evidence paths; retain original outcomes.")
    for path in (args.kind, args.kubectl, args.vegeta):
        if not path.is_absolute():
            raise ValueError("Use explicit absolute verified tool paths.")
    if sha256_file(args.kind) != KIND_SHA256 or sha256_file(args.kubectl) != KUBECTL_SHA256:
        raise ValueError("Owned cluster tools differ from the reviewed pins.")
    root = Path(__file__).resolve().parents[1]
    commit, captured = source_identity(root), input_hashes(root)
    tool_digest = verify_benchmark_binary(args.vegeta)
    result: dict[str, Any] = {
        "status": "failed",
        "source_commit": commit,
        "input_hashes": captured,
        "deadline_seconds": VERIFY_SECONDS,
        "owned_cluster_deleted": False,
        "tools": {
            "kind_sha256": KIND_SHA256,
            "kubectl_sha256": KUBECTL_SHA256,
            "vegeta_sha256": tool_digest,
            "vegeta_version": "12.13.0",
            "vegeta_source_commit": VEGETA_COMMIT,
            "signatures_verified": False,
        },
    }
    started, cluster = time.monotonic(), None
    failure: BaseException | None = None
    try:
        with owned_cluster(str(args.kind), docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:

                async def bounded() -> dict[str, Any]:
                    async with asyncio.timeout(VERIFY_SECONDS):
                        return await verify(cluster, result, args.kubectl, args.vegeta)

                result.update(asyncio.run(bounded()))
            except BaseException as error:
                failure = error
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = (
            input_hashes(root) == captured and source_identity(root) == commit
        )
        assert result["inputs_unchanged"] and result["private_directory_deleted"]
        if failure is not None:
            raise failure
        result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        frames = []
        trace = error.__traceback__
        while trace is not None:
            filename = Path(trace.tb_frame.f_code.co_filename).resolve()
            if filename.is_relative_to(root):
                frames.append(
                    {
                        "file": str(filename.relative_to(root)),
                        "line": trace.tb_lineno,
                        "function": trace.tb_frame.f_code.co_name,
                    }
                )
            trace = trace.tb_next
        result["failure_locations"] = frames
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        with args.evidence.open("x") as output:
            output.write(json.dumps(result, indent=2) + "\n")
    print("Real owned-kind HTTP benchmark trials passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned benchmark proof failed ({type(error).__name__}); retain evidence.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
