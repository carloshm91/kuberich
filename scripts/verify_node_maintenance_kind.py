"""Exercise production reviewed Node maintenance in an owned three-node kind cluster."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as sdk
from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.mutations import MutationState
from kuberich.domain.node_maintenance import DrainOptions, MaintenanceMode, NodeState, PodState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.node_maintenance import NodeMaintenanceService
from kuberich.services.resources import ResourceReader
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

NAMESPACE = "kuberich-node-maintenance"
VERIFY_SECONDS = 600
KUBECTL_SHA256 = "8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a"


def input_hashes(root: Path) -> dict[str, str]:
    """Bind observations to every runtime input and the owned proof source."""
    paths = [
        *(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        root / "pyproject.toml",
        root / "uv.lock",
        root / "scripts/owned_kind.py",
        root / "scripts/verify_node_maintenance_kind.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


async def wait_for(predicate: Callable[[], Awaitable[bool]], *, seconds: float = 60) -> None:
    """Wait for an actual owned observation under one finite fixture deadline."""
    async with asyncio.timeout(seconds):
        while not await predicate():
            await asyncio.sleep(0.1)


async def verify(cluster: OwnedCluster, progress: dict[str, Any]) -> dict[str, Any]:
    original, environment = cluster.path.read_bytes(), dict(os.environ)
    sentinel = cluster.directory / "caller-kubeconfig-sentinel"
    sentinel_bytes = b"Owned synthetic ambient sentinel; never a kubeconfig.\n"
    sentinel.write_bytes(sentinel_bytes)
    selected = load_catalog(
        ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context),
        {**environment, "KUBECONFIG": str(sentinel)},
    ).select(cluster.context)
    connection = KubernetesSession(selected, 15)
    private = Path(connection.directory.name)
    owners: list[NodeMaintenanceService] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with asyncio.timeout(VERIFY_SECONDS):
            await connection.open()
            assert connection.api is not None and connection.credentials is None
            core, apps, policy = (
                sdk.CoreV1Api(connection.api),
                sdk.AppsV1Api(connection.api),
                sdk.PolicyV1Api(connection.api),
            )
            discovery = await ResourceReader(connection).discover()
            descriptor = discovery.find("nodes", group="", version="v1")
            nodes = await core.list_node()
            workers = sorted(
                (
                    node
                    for node in nodes.items
                    if "node-role.kubernetes.io/control-plane" not in (node.metadata.labels or {})
                ),
                key=lambda node: node.metadata.name,
            )
            assert len(nodes.items) == 3 and len(workers) == 2 and len(cluster.node_ids) == 3
            target = ResourceTarget(
                SessionIdentity(cluster.context, 1),
                "",
                "nodes",
                None,
                workers[0].metadata.name,
                workers[0].metadata.uid,
            )
            other = workers[1].metadata.name
            progress["target"] = {"name": target.name, "uid": target.uid}
            progress["other_worker"] = {"name": other, "uid": workers[1].metadata.uid}
            progress["owned_node_ids"] = list(cluster.node_ids)

            def owner() -> NodeMaintenanceService:
                service = NodeMaintenanceService(
                    connection, descriptor, target, discovery, AccessPolicy(False), lambda: True
                )
                owners.append(service)
                return service

            async def operate(mode: MaintenanceMode) -> NodeMaintenanceService:
                service = owner()
                review = await service.prepare(mode)
                assert not review.blockers
                result = await service.execute(service.confirm(review))
                assert result.state is MutationState.SUCCEEDED, result.state.value
                assert service.progress.node.state is (
                    NodeState.SCHEDULABLE
                    if mode is MaintenanceMode.UNCORDON
                    else NodeState.CORDONED
                )
                await service.close()
                return service

            async def ready_pods(count: int) -> bool:
                pods = await core.list_namespaced_pod(NAMESPACE, label_selector="app=managed")
                return len(pods.items) == count and all(
                    pod.metadata.deletion_timestamp is None
                    and any(
                        condition.type == "Ready" and condition.status == "True"
                        for condition in pod.status.conditions or []
                    )
                    for pod in pods.items
                )

            async def target_absent(name: str, uid: str) -> bool:
                try:
                    pod = await core.read_namespaced_pod(name, NAMESPACE)
                except ApiException as error:
                    if error.status != 404:
                        raise
                    return True
                return bool(pod.metadata.uid != uid)

            checks: list[str] = []
            progress["phase"] = "real-conditional-cordon-conflict-uncordon"
            await operate(MaintenanceMode.CORDON)
            stale = owner()
            review = await stale.prepare(MaintenanceMode.UNCORDON)
            await core.patch_node(
                target.name, {"metadata": {"annotations": {"kuberich.test/review-change": "owned"}}}
            )
            result = await stale.execute(stale.confirm(review))
            assert result.state is MutationState.CONFLICT
            assert (await core.read_node(target.name)).spec.unschedulable is True
            assert stale.progress.node.state is NodeState.CORDONED
            await stale.close()
            await operate(MaintenanceMode.UNCORDON)
            checks.append("real-uid-version-cordon-conflict-refusal-separate-uncordon")

            progress["phase"] = "owned-managed-deployment-pdb-fixture"
            await core.create_namespace(sdk.V1Namespace(metadata=sdk.V1ObjectMeta(name=NAMESPACE)))
            for worker in workers:
                await core.patch_node(
                    worker.metadata.name,
                    {"metadata": {"labels": {"kuberich.test/maintenance": "worker"}}},
                )
            await core.patch_node(other, {"spec": {"unschedulable": True}})
            deployment: Any = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "managed"},
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": "managed"}},
                    "template": {
                        "metadata": {"labels": {"app": "managed"}},
                        "spec": {
                            "nodeSelector": {"kuberich.test/maintenance": "worker"},
                            "terminationGracePeriodSeconds": 1,
                            "containers": [
                                {
                                    "name": "workload",
                                    "image": SHELL_IMAGE,
                                    "command": ["/bin/sleep", "600"],
                                }
                            ],
                        },
                    },
                },
            }
            await apps.create_namespaced_deployment(NAMESPACE, deployment)
            await wait_for(lambda: ready_pods(1), seconds=120)
            await core.patch_node(other, {"spec": {"unschedulable": False}})
            original_pod = (
                await core.list_namespaced_pod(NAMESPACE, label_selector="app=managed")
            ).items[0]
            assert original_pod.spec.node_name == target.name
            budget_definition: Any = {
                "apiVersion": "policy/v1",
                "kind": "PodDisruptionBudget",
                "metadata": {"name": "managed"},
                "spec": {"minAvailable": 1, "selector": {"matchLabels": {"app": "managed"}}},
            }
            await policy.create_namespaced_pod_disruption_budget(NAMESPACE, budget_definition)

            async def budget_ready() -> bool:
                budget = await policy.read_namespaced_pod_disruption_budget("managed", NAMESPACE)
                return bool(
                    budget.status
                    and budget.status.observed_generation == budget.metadata.generation
                    and budget.status.disruptions_allowed == 0
                )

            await wait_for(budget_ready)
            drain = owner()
            review = await drain.prepare(
                MaintenanceMode.DRAIN, DrainOptions(leave_daemonsets=True, timeout_seconds=90)
            )
            assert not review.blockers
            reviewed = next(
                pod for pod in review.pods if pod.target.uid == original_pod.metadata.uid
            )
            assert reviewed.managed and reviewed.pdbs and reviewed.pdbs[0].disruptions_allowed == 0
            operation = asyncio.create_task(drain.execute(drain.confirm(review)))
            tasks.append(operation)
            progress["phase"] = "production-pdb-429-refusal"

            async def refused() -> bool:
                if operation.done():
                    raise AssertionError("Drain stopped before the owned PDB refusal was observed.")
                return any(
                    pod.uid == reviewed.target.uid
                    and pod.state is PodState.RETRYING
                    and pod.attempts >= 1
                    for pod in drain.progress.pods
                )

            await wait_for(refused, seconds=20)
            unchanged = await core.read_namespaced_pod(reviewed.target.name, NAMESPACE)
            assert unchanged.metadata.uid == reviewed.target.uid
            assert unchanged.metadata.resource_version == reviewed.resource_version
            progress["pdb_refused"] = {
                "uid": reviewed.target.uid,
                "resource_version": reviewed.resource_version,
            }
            progress["phase"] = "production-pdb-allowance-recovery-same-reviewed-version"
            await apps.patch_namespaced_deployment("managed", NAMESPACE, {"spec": {"replicas": 2}})
            result = await operation
            assert result.state is MutationState.SUCCEEDED, result.state.value
            assert drain.progress.node.state is NodeState.CORDONED
            completed = next(pod for pod in drain.progress.pods if pod.uid == reviewed.target.uid)
            assert completed.state is PodState.ABSENT and completed.attempts >= 2
            assert await target_absent(reviewed.target.name, reviewed.target.uid)
            await wait_for(lambda: ready_pods(2))
            replacements = (
                await core.list_namespaced_pod(NAMESPACE, label_selector="app=managed")
            ).items
            assert all(pod.spec.node_name == other for pod in replacements)
            assert all(pod.metadata.uid != reviewed.target.uid for pod in replacements)
            progress["pdb_recovery"] = {
                "original_uid": reviewed.target.uid,
                "original_absent": True,
                "attempts": completed.attempts,
                "replacements": [
                    {"name": pod.metadata.name, "uid": pod.metadata.uid, "node": pod.spec.node_name}
                    for pod in replacements
                ],
                "final_node_state": drain.progress.node.state.value,
            }
            await drain.close()
            checks.append(
                "real-pdb-429-recovery-identical-reviewed-uid-resourceversion-conditional-eviction"
            )
            checks.append(
                "real-original-uid-absence-replacement-capacity-other-worker-final-cordon"
            )
            await operate(MaintenanceMode.UNCORDON)
            checks.append("real-deliberate-fresh-uncordon-after-drain")
            return {
                "checks": checks,
                "node_image": NODE_IMAGE,
                "shell_image": SHELL_IMAGE,
                "owned_kubeconfig_unchanged": cluster.path.read_bytes() == original,
                "environment_unchanged": dict(os.environ) == environment,
                "caller_sentinel_unchanged": sentinel.read_bytes() == sentinel_bytes,
            }
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for service in owners:
            await service.close()
        progress["owners_drained"] = all(service.operation_count == 0 for service in owners)
        await connection.close()
        progress["private_sessions_deleted"] = not private.exists()
        assert progress["owners_drained"] and progress["private_sessions_deleted"]
        assert cluster.path.read_bytes() == original and dict(os.environ) == environment
        assert sentinel.read_bytes() == sentinel_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, type=Path)
    parser.add_argument("--kubectl", required=True, type=Path)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    if args.evidence.exists():
        raise ValueError("Use fresh node-maintenance evidence paths; preserve previous outcomes.")
    if not args.kind.is_absolute() or not args.kubectl.is_absolute():
        raise ValueError("Use explicit verified kind and kubectl fixture paths.")
    if sha256_file(args.kind) != KIND_SHA256 or sha256_file(args.kubectl) != KUBECTL_SHA256:
        raise ValueError(
            "Use checksum-verified official kind v0.33.0 and kubectl v1.36.4 fixtures."
        )
    root = Path(__file__).resolve().parents[1]
    captured = input_hashes(root)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": captured,
        "deadline_seconds": VERIFY_SECONDS,
        "owned_cluster_deleted": False,
        "expected_worker_count": 2,
        "tools": {
            "kind_sha256": sha256_file(args.kind),
            "kubectl_sha256": sha256_file(args.kubectl),
        },
    }
    started, cluster = time.monotonic(), None
    failure: BaseException | None = None
    try:
        with owned_cluster(str(args.kind), docker=args.docker, worker_count=2) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(asyncio.run(verify(cluster, result)))
            except BaseException as error:
                failure = error
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        assert result["inputs_unchanged"] and result["private_directory_deleted"]
        if failure is not None:
            raise failure
        result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Owned-kind production Node maintenance proof passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned Node maintenance proof failed ({type(error).__name__}); retain evidence.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
