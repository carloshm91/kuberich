"""Exercise production reviewed Node maintenance in an owned three-node kind cluster."""

import argparse
import asyncio
import hashlib
import json
import os
import ssl
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as sdk
from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import Entry, load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.mutations import MutationState
from kuberich.domain.node_maintenance import DrainOptions, MaintenanceMode, NodeState, PodState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.node_maintenance import NodeMaintenanceService
from kuberich.services.resources import ResourceReader
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

NAMESPACE = "kuberich-node-maintenance"
VERIFY_SECONDS = 600
KUBECTL_SHA256 = "8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a"


class MaintenanceProxy:
    """Observe production requests separately from fixtures; optionally lose one receipt."""

    def __init__(self, upstream: Any, endpoint: str) -> None:
        self.upstream, self.endpoint = upstream, endpoint
        self.receipts: list[dict[str, Any]] = []
        self.drop_uid: str | None = None

    async def handle(self, request: Any) -> Any:
        from aiohttp import web

        body = await request.read()
        if len(body) > 1024 * 1024:
            raise ValueError("Owned maintenance request exceeded its fixed bound.")
        eviction = request.method == "POST" and request.path.endswith("/eviction")
        receipt: dict[str, Any] = {"method": request.method, "path": request.path}
        uid = None
        if eviction:
            value = json.loads(body)
            conditions = value["deleteOptions"]["preconditions"]
            assert set(conditions) == {"uid", "resourceVersion"}
            assert isinstance(conditions["uid"], str) and isinstance(
                conditions["resourceVersion"], str
            )
            uid = conditions["uid"]
            receipt["preconditions"] = conditions
            receipt["normal_grace"] = "gracePeriodSeconds" not in value["deleteOptions"]
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"accept", "content-type", "impersonate-user", "impersonate-group"}
        }
        async with self.upstream.request(
            request.method,
            self.endpoint + request.raw_path,
            data=body if body else None,
            headers=headers,
            allow_redirects=False,
        ) as response:
            payload = await response.read()
            assert len(payload) <= 8 * 1024 * 1024
            receipt["status"] = response.status
            retry_after = response.headers.get("Retry-After")
        drop = eviction and uid == self.drop_uid
        if drop:
            self.drop_uid = None
            receipt["owned_fault"] = "post-commit-response-loss"
        self.receipts.append(receipt)
        if drop:
            request.transport.abort()
            return web.Response()
        result_headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return web.Response(
            status=receipt["status"],
            body=payload,
            content_type="application/json",
            headers=result_headers,
        )


@asynccontextmanager
async def observed_client(
    connection: KubernetesSession, *, as_user: str | None = None
) -> AsyncIterator[tuple[KubernetesSession, MaintenanceProxy]]:
    """Use one owned loopback forwarder with the explicit cluster's certificate identity."""
    import aiohttp
    from aiohttp import web

    configuration = connection.configuration
    assert configuration is not None and configuration.cert_file and configuration.key_file
    context = ssl.create_default_context(cafile=configuration.ssl_ca_cert)
    context.load_cert_chain(configuration.cert_file, configuration.key_file)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=context), timeout=aiohttp.ClientTimeout(total=20)
    ) as upstream:
        proxy = MaintenanceProxy(upstream, str(configuration.host))
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_route("*", "/{path:.*}", proxy.handle)
        server = web.AppRunner(app, shutdown_timeout=1)
        await server.setup()
        site = web.TCPSite(server, "127.0.0.1", 0)
        await site.start()
        selected = replace(
            connection.context,
            cluster=Entry(
                {"server": f"http://127.0.0.1:{server.addresses[0][1]}"},
                connection.context.cluster.directory,
            ),
            user=Entry({"as": as_user} if as_user else {}, connection.context.user.directory),
        )
        client = KubernetesSession(selected, 15)
        private = Path(client.directory.name)
        try:
            await client.open()
            yield client, proxy
        finally:
            try:
                await client.close()
            finally:
                await server.cleanup()
            assert not private.exists()


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


async def verify_extended(
    connection: KubernetesSession,
    product: KubernetesSession,
    proxy: MaintenanceProxy,
    owner: Callable[..., NodeMaintenanceService],
    operate: Callable[..., Awaitable[NodeMaintenanceService]],
    target: ResourceTarget,
    mirror_target: ResourceTarget,
    other: str,
    tasks: list[asyncio.Task[Any]],
    progress: dict[str, Any],
    stack: AsyncExitStack,
) -> list[str]:
    """Run real effects and separately labelled owned HTTP faults on reviewed Pod UIDs."""
    assert connection.api is not None
    core, policy, rbac = (
        sdk.CoreV1Api(connection.api),
        sdk.PolicyV1Api(connection.api),
        sdk.RbacAuthorizationV1Api(connection.api),
    )
    checks: list[str] = []
    progress["extended"] = {}
    progress["fixture_deletes"] = []

    async def pod(
        name: str,
        *,
        emptydir: bool = False,
        finalizer: bool = False,
        node: str = target.name,
    ) -> Any:
        created = await core.create_namespaced_pod(
            NAMESPACE,
            sdk.V1Pod(
                api_version="v1",
                kind="Pod",
                metadata=sdk.V1ObjectMeta(
                    name=name,
                    namespace=NAMESPACE,
                    labels={"maintenance": name},
                    finalizers=["kuberich.test/fixture-hold"] if finalizer else None,
                ),
                spec=sdk.V1PodSpec(
                    node_name=node,
                    termination_grace_period_seconds=1,
                    containers=[
                        sdk.V1Container(
                            name="workload", image=SHELL_IMAGE, command=["/bin/sleep", "600"]
                        )
                    ],
                    volumes=[sdk.V1Volume(name="scratch", empty_dir=sdk.V1EmptyDirVolumeSource())]
                    if emptydir
                    else None,
                ),
            ),
        )

        async def ready() -> bool:
            observed = await core.read_namespaced_pod(name, NAMESPACE)
            return any(
                condition.type == "Ready" and condition.status == "True"
                for condition in observed.status.conditions or []
            )

        await wait_for(ready)
        return await core.read_namespaced_pod(created.metadata.name, NAMESPACE)

    async def absent(name: str, uid: str) -> bool:
        try:
            observed = await core.read_namespaced_pod(name, NAMESPACE)
        except ApiException as error:
            if error.status != 404:
                raise
            return True
        return bool(observed.metadata.uid != uid)

    async def remove(value: Any) -> None:
        name, uid = value.metadata.name, value.metadata.uid
        if await absent(name, uid):
            return
        observed = await core.read_namespaced_pod(name, NAMESPACE)
        if observed.metadata.finalizers:
            await core.patch_namespaced_pod(name, NAMESPACE, {"metadata": {"finalizers": None}})
        if observed.metadata.deletion_timestamp is None:
            progress["fixture_deletes"].append({"name": name, "uid": uid})
            await core.delete_namespaced_pod(
                name,
                NAMESPACE,
                body=sdk.V1DeleteOptions(
                    grace_period_seconds=0, preconditions=sdk.V1Preconditions(uid=uid)
                ),
            )
        await wait_for(lambda: absent(name, uid), seconds=15)

    async def budget(name: str) -> None:
        body: Any = {
            "apiVersion": "policy/v1",
            "kind": "PodDisruptionBudget",
            "metadata": {"name": name},
            "spec": {"minAvailable": 1, "selector": {"matchLabels": {"maintenance": name}}},
        }
        await policy.create_namespaced_pod_disruption_budget(NAMESPACE, body)

        async def blocked() -> bool:
            observed = await policy.read_namespaced_pod_disruption_budget(name, NAMESPACE)
            return bool(
                observed.status
                and observed.status.observed_generation == observed.metadata.generation
                and observed.status.disruptions_allowed == 0
            )

        await wait_for(blocked)

    async def start(
        options: DrainOptions,
        *,
        client: KubernetesSession = product,
        node_target: ResourceTarget = target,
    ) -> tuple[NodeMaintenanceService, asyncio.Task[Any]]:
        source = owner(client, node_target=node_target)
        review = await source.prepare(MaintenanceMode.DRAIN, options)
        assert not review.blockers
        operation = asyncio.create_task(source.execute(source.confirm(review)))
        tasks.append(operation)
        return source, operation

    async def state(
        source: NodeMaintenanceService, operation: asyncio.Task[Any], uid: str, expected: PodState
    ) -> bool:
        if operation.done():
            if not operation.cancelled() and operation.exception() is None:
                record("stopped-before-" + expected.name.lower(), source, operation.result())
            raise AssertionError("Owned maintenance stopped before the requested observation.")
        return any(item.uid == uid and item.state is expected for item in source.progress.pods)

    def record(name: str, source: NodeMaintenanceService, result: Any) -> None:
        progress["extended"][name] = {
            "state": result.state.value,
            "message": result.message,
            "final_node": {
                "state": source.progress.node.state.value,
                "uid": source.progress.node.uid,
                "observed_at": source.progress.node.observed_at,
            },
            "pods": [
                {
                    "uid": item.uid,
                    "name": item.name,
                    "namespace": item.namespace,
                    "state": item.state.value,
                    "attempts": item.attempts,
                    "http_status": item.http_status,
                }
                for item in source.progress.pods
            ],
        }

    async def finish(
        source: NodeMaintenanceService,
        operation: asyncio.Task[Any],
        name: str,
        expected: MutationState,
        node_state: NodeState = NodeState.CORDONED,
    ) -> Any:
        result = await operation
        record(name, source, result)
        assert result.state is expected
        assert source.progress.node.state is node_state
        assert source.progress.node.uid == source.target.uid
        await source.close()
        return result

    sentinel = await pod("unrelated-sentinel", node=other)
    progress["phase"] = "real-finalizer-accepted-not-absent-deadline"
    held = await pod("finalizer-pending", finalizer=True)
    source, operation = await start(
        DrainOptions(force=True, leave_daemonsets=True, timeout_seconds=4)
    )
    await wait_for(
        lambda: state(source, operation, held.metadata.uid, PodState.TERMINATING), seconds=3
    )
    observed = await core.read_namespaced_pod(held.metadata.name, NAMESPACE)
    assert observed.metadata.uid == held.metadata.uid and observed.metadata.deletion_timestamp
    assert observed.metadata.finalizers == ["kuberich.test/fixture-hold"]
    await finish(source, operation, "finalizer-deadline", MutationState.PARTIAL)
    pending = next(item for item in source.progress.pods if item.uid == held.metadata.uid)
    assert pending.attempts == 1 and pending.state is PodState.TERMINATING
    assert not await absent(held.metadata.name, held.metadata.uid)
    await remove(held)
    await operate(MaintenanceMode.UNCORDON)
    checks.append("real-accepted-finalizer-pending-not-absent-deadline-no-shortening-or-uncordon")

    progress["phase"] = "real-independent-consents-retained-daemonsets-mirror-pdb"
    local = await pod("consent-local", emptydir=True, node=mirror_target.name)
    await budget(local.metadata.name)
    source = owner(node_target=mirror_target)
    for options, message in (
        (DrainOptions(leave_daemonsets=True), "force"),
        (DrainOptions(force=True, leave_daemonsets=True), "emptyDir"),
        (DrainOptions(delete_emptydir_data=True, leave_daemonsets=True), "force"),
        (DrainOptions(force=True, delete_emptydir_data=True), "DaemonSet"),
    ):
        review = await source.prepare(MaintenanceMode.DRAIN, options)
        assert any(message in item for item in review.blockers)
        try:
            source.confirm(review)
        except AppError:
            pass
        else:
            raise AssertionError("Missing independent consent authorized a drain.")
    review = await source.prepare(
        MaintenanceMode.DRAIN,
        DrainOptions(
            force=True, delete_emptydir_data=True, leave_daemonsets=True, timeout_seconds=4
        ),
    )
    assert not review.blockers
    retained = {item.target.uid for item in review.pods if item.retained}
    mirror_uids = {item.target.uid for item in review.pods if item.mirror}
    assert mirror_uids and any(item.daemonset for item in review.pods)
    progress["static_mirror_node"] = {
        "name": mirror_target.name,
        "uid": mirror_target.uid,
        "mirror_pod_uids": sorted(mirror_uids),
    }
    operation = asyncio.create_task(source.execute(source.confirm(review)))
    tasks.append(operation)
    await finish(source, operation, "both-consents-pdb-refusal-deadline", MutationState.PARTIAL)
    refused = next(item for item in source.progress.pods if item.uid == local.metadata.uid)
    assert refused.attempts >= 1 and refused.http_status == 429
    independent_uids = {
        item.target.uid
        for item in review.pods
        if not item.retained and item.target.uid != local.metadata.uid
    }
    assert independent_uids and all(
        item.state in {PodState.ACCEPTED, PodState.TERMINATING, PodState.ABSENT}
        for item in source.progress.pods
        if item.uid in independent_uids
    )
    assert (
        await core.read_namespaced_pod(local.metadata.name, NAMESPACE)
    ).metadata.uid == local.metadata.uid
    await policy.delete_namespaced_pod_disruption_budget(local.metadata.name, NAMESPACE)
    source, operation = await start(
        DrainOptions(
            force=True, delete_emptydir_data=True, leave_daemonsets=True, timeout_seconds=30
        ),
        node_target=mirror_target,
    )
    await finish(source, operation, "both-consents-reviewed-uid-evicted", MutationState.SUCCEEDED)
    assert await absent(local.metadata.name, local.metadata.uid)
    current = await core.list_pod_for_all_namespaces(
        field_selector=f"spec.nodeName={mirror_target.name}"
    )
    assert retained <= {item.metadata.uid for item in current.items}
    await operate(MaintenanceMode.UNCORDON, mirror_target)
    checks.append("real-independent-force-emptydir-daemonset-consents-pdb-not-bypassed")
    checks.append("real-owned-control-plane-static-mirror-and-daemonset-uids-retained")

    progress["phase"] = "real-cancel-partial-absence-while-other-pdb-refused"
    independent, blocked = await pod("a-independent"), await pod("z-pdb-blocked")
    await budget(blocked.metadata.name)
    source, operation = await start(
        DrainOptions(force=True, leave_daemonsets=True, timeout_seconds=30)
    )

    async def partial() -> bool:
        observed = await state(
            source, operation, independent.metadata.uid, PodState.ABSENT
        ) and await state(source, operation, blocked.metadata.uid, PodState.RETRYING)
        now = time.monotonic()
        return observed and all(
            item.state
            in {
                PodState.ABSENT,
                PodState.SKIPPED,
                PodState.ACCEPTED,
                PodState.TERMINATING,
                PodState.RETRYING,
            }
            and (
                item.state is not PodState.RETRYING
                or (item.retry_at is not None and item.retry_at > now + 1)
            )
            for item in source.progress.pods
        )

    await wait_for(partial, seconds=15)
    retry_at = next(
        item.retry_at for item in source.progress.pods if item.uid == blocked.metadata.uid
    )
    assert retry_at is not None
    retry_remaining = max(0.0, retry_at - time.monotonic())
    assert retry_remaining <= 30
    operation.cancel()
    await finish(source, operation, "cancel-partial-absent-and-refused", MutationState.PARTIAL)
    attempts = len(proxy.receipts)
    await asyncio.sleep(max(0.0, retry_at - time.monotonic()) + 0.2)
    assert len(proxy.receipts) == attempts
    progress["stop_retry_oracle"] = {
        "remaining_retry_seconds_at_stop": retry_remaining,
        "observed_beyond_retry_deadline": time.monotonic() > retry_at,
        "production_requests_after_stop": len(proxy.receipts) - attempts,
    }
    assert await absent(independent.metadata.name, independent.metadata.uid)
    assert (
        await core.read_namespaced_pod(blocked.metadata.name, NAMESPACE)
    ).metadata.uid == blocked.metadata.uid
    await policy.delete_namespaced_pod_disruption_budget(blocked.metadata.name, NAMESPACE)
    await remove(blocked)
    await operate(MaintenanceMode.UNCORDON)
    checks.append(
        "real-stop-retains-independent-absence-refused-pod-no-later-retry-separate-uncordon"
    )

    progress["phase"] = "real-rbac-eviction-denial-after-cordon"
    denied = await pod("rbac-denied")
    reader = "kuberich-owned-maintenance-reader"
    await rbac.create_cluster_role(
        sdk.V1ClusterRole(
            metadata=sdk.V1ObjectMeta(name="owned-maintenance-reader"),
            rules=[
                sdk.V1PolicyRule(
                    api_groups=[""], resources=["nodes", "pods"], verbs=["get", "list"]
                ),
                sdk.V1PolicyRule(api_groups=[""], resources=["nodes"], verbs=["patch"]),
                sdk.V1PolicyRule(api_groups=["apps"], resources=["daemonsets"], verbs=["get"]),
                sdk.V1PolicyRule(
                    api_groups=["policy"], resources=["poddisruptionbudgets"], verbs=["list"]
                ),
            ],
        )
    )
    await rbac.create_cluster_role_binding(
        sdk.V1ClusterRoleBinding(
            metadata=sdk.V1ObjectMeta(name="owned-maintenance-reader"),
            role_ref=sdk.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="ClusterRole",
                name="owned-maintenance-reader",
            ),
            subjects=[
                sdk.RbacV1Subject(kind="User", name=reader, api_group="rbac.authorization.k8s.io")
            ],
        )
    )
    restricted, restricted_proxy = await stack.enter_async_context(
        observed_client(connection, as_user=reader)
    )
    progress["restricted_http_receipts"] = restricted_proxy.receipts
    source, operation = await start(
        DrainOptions(force=True, leave_daemonsets=True, timeout_seconds=20), client=restricted
    )
    await finish(source, operation, "rbac-403-after-cordon", MutationState.DENIED)
    assert any(
        item["method"] == "POST" and item["status"] == 403 for item in restricted_proxy.receipts
    )
    assert all(item["method"] != "DELETE" for item in restricted_proxy.receipts)
    assert (
        await core.read_namespaced_pod(denied.metadata.name, NAMESPACE)
    ).metadata.uid == denied.metadata.uid
    await remove(denied)
    await operate(MaintenanceMode.UNCORDON)
    checks.append("real-restricted-rbac-403-after-cordon-no-delete-fallback-final-observation")

    progress["phase"] = "owned-http-postcommit-eviction-response-loss"
    lost = await pod("response-loss")
    proxy.drop_uid = lost.metadata.uid
    source, operation = await start(
        DrainOptions(force=True, leave_daemonsets=True, timeout_seconds=20)
    )
    await finish(source, operation, "owned-http-postcommit-response-loss", MutationState.UNCERTAIN)
    await wait_for(lambda: absent(lost.metadata.name, lost.metadata.uid))
    writes = [
        item
        for item in proxy.receipts
        if item.get("preconditions", {}).get("uid") == lost.metadata.uid
    ]
    assert len(writes) == 1 and writes[0]["status"] == 201
    assert writes[0]["owned_fault"] == "post-commit-response-loss"
    await operate(MaintenanceMode.UNCORDON)
    checks.append(
        "owned-http-real-upstream-201-response-loss-uncertain-no-replay-original-uid-absent"
    )

    progress["phase"] = "real-same-name-replacement-before-execution"
    old = await pod("replaced-name")
    source = owner()
    review = await source.prepare(
        MaintenanceMode.DRAIN, DrainOptions(force=True, leave_daemonsets=True)
    )
    await remove(old)
    replacement = await pod("replaced-name")
    assert replacement.metadata.uid != old.metadata.uid
    result = await source.execute(source.confirm(review))
    record("same-name-replacement", source, result)
    assert result.state is MutationState.CONFLICT and all(
        item.attempts == 0 for item in source.progress.pods
    )
    assert (
        await core.read_namespaced_pod(replacement.metadata.name, NAMESPACE)
    ).metadata.uid == replacement.metadata.uid
    await source.close()
    await remove(replacement)
    checks.append("real-replaced-pod-uid-never-adopted-or-evicted-by-old-review")

    progress["phase"] = "real-new-arrival-after-accepted-eviction"
    held = await pod("arrival-held", finalizer=True)
    source, operation = await start(
        DrainOptions(force=True, leave_daemonsets=True, timeout_seconds=30)
    )
    await wait_for(
        lambda: state(source, operation, held.metadata.uid, PodState.TERMINATING), seconds=15
    )
    arrival = await pod("unreviewed-arrival")
    await remove(held)
    await finish(source, operation, "new-arrival-not-in-confirmation", MutationState.PARTIAL)
    assert (
        await core.read_namespaced_pod(arrival.metadata.name, NAMESPACE)
    ).metadata.uid == arrival.metadata.uid
    assert not any(
        item.get("preconditions", {}).get("uid") == arrival.metadata.uid for item in proxy.receipts
    )
    await remove(arrival)
    await operate(MaintenanceMode.UNCORDON)
    checks.append("real-new-arrival-blocks-drained-completion-no-unreviewed-eviction")

    progress["phase"] = "real-external-uncordon-stops-pdb-retry"
    blocked = await pod("external-uncordon")
    await budget(blocked.metadata.name)
    source, operation = await start(
        DrainOptions(force=True, leave_daemonsets=True, timeout_seconds=30)
    )
    await wait_for(
        lambda: state(source, operation, blocked.metadata.uid, PodState.RETRYING), seconds=15
    )
    await core.patch_node(target.name, {"spec": {"unschedulable": False}})
    await finish(source, operation, "external-uncordon", MutationState.STALE, NodeState.SCHEDULABLE)
    writes = [
        item
        for item in proxy.receipts
        if item.get("preconditions", {}).get("uid") == blocked.metadata.uid
    ]
    assert len(writes) == 1 and writes[0]["status"] == 429
    assert (
        await core.read_namespaced_pod(blocked.metadata.name, NAMESPACE)
    ).metadata.uid == blocked.metadata.uid
    await policy.delete_namespaced_pod_disruption_budget(blocked.metadata.name, NAMESPACE)
    await remove(blocked)
    assert (
        await core.read_namespaced_pod(sentinel.metadata.name, NAMESPACE)
    ).metadata.uid == sentinel.metadata.uid
    final_node = await core.read_node(target.name)
    progress["final_fresh_node"] = {
        "uid": final_node.metadata.uid,
        "unschedulable_field": final_node.spec.unschedulable,
        "observed_at": time.time(),
    }
    assert final_node.metadata.uid == target.uid
    assert final_node.spec.unschedulable is None or final_node.spec.unschedulable is False
    progress["unrelated_sentinel_uid"] = sentinel.metadata.uid
    progress["phase"] = "all-real-scenarios-observed"
    checks.append(
        "real-external-uncordon-stops-further-eviction-final-schedulable-sentinel-preserved"
    )
    return checks


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
    stack = AsyncExitStack()
    owners: list[NodeMaintenanceService] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with asyncio.timeout(VERIFY_SECONDS):
            await connection.open()
            assert connection.api is not None and connection.credentials is None
            product, proxy = await stack.enter_async_context(observed_client(connection))
            progress["production_http_receipts"] = proxy.receipts
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

            def owner(
                client: KubernetesSession = product, node_target: ResourceTarget = target
            ) -> NodeMaintenanceService:
                service = NodeMaintenanceService(
                    client, descriptor, node_target, discovery, AccessPolicy(False), lambda: True
                )
                owners.append(service)
                return service

            async def operate(
                mode: MaintenanceMode, node_target: ResourceTarget = target
            ) -> NodeMaintenanceService:
                service = owner(node_target=node_target)
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
            progress["pdb_recovery_result"] = {
                "state": result.state.value,
                "message": result.message,
                "node": {
                    "state": drain.progress.node.state.value,
                    "uid": drain.progress.node.uid,
                    "observed_at": drain.progress.node.observed_at,
                },
                "pods": [
                    {
                        "uid": pod.uid,
                        "namespace": pod.namespace,
                        "name": pod.name,
                        "state": pod.state.value,
                        "attempts": pod.attempts,
                        "http_status": pod.http_status,
                    }
                    for pod in drain.progress.pods
                ],
                "reviewed_uid": reviewed.target.uid,
                "reviewed_resource_version": reviewed.resource_version,
            }
            try:
                observed = await core.read_namespaced_pod(reviewed.target.name, NAMESPACE)
                progress["pdb_recovery_result"]["current_pod"] = {
                    "uid": observed.metadata.uid,
                    "resource_version": observed.metadata.resource_version,
                    "terminating": observed.metadata.deletion_timestamp is not None,
                    "node": observed.spec.node_name,
                }
            except ApiException as error:
                progress["pdb_recovery_result"]["current_pod"] = {"http_status": error.status}
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
            control_plane = next(node for node in nodes.items if node not in workers)
            mirror_target = replace(
                target, name=control_plane.metadata.name, uid=control_plane.metadata.uid
            )
            checks.extend(
                await verify_extended(
                    connection,
                    product,
                    proxy,
                    owner,
                    operate,
                    target,
                    mirror_target,
                    other,
                    tasks,
                    progress,
                    stack,
                )
            )
            writes = [receipt for receipt in proxy.receipts if receipt["method"] != "GET"]
            assert all(receipt["method"] in {"PATCH", "POST"} for receipt in writes)
            assert all(
                receipt["path"]
                in {f"/api/v1/nodes/{node.name}" for node in (target, mirror_target)}
                if receipt["method"] == "PATCH"
                else receipt["path"].endswith("/eviction")
                for receipt in writes
            )
            reviewed_versions = {
                (pod.target.uid, pod.resource_version)
                for service in owners
                if service.intent is not None
                for pod in service.intent.pods
            }
            assert all(
                (receipt["preconditions"]["uid"], receipt["preconditions"]["resourceVersion"])
                in reviewed_versions
                for receipt in writes
                if "preconditions" in receipt
            )
            assert all(receipt["normal_grace"] for receipt in writes if "preconditions" in receipt)
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
        try:
            await stack.aclose()
        finally:
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
