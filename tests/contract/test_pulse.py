"""Real controlled HTTP collections qualify Pulse scope, bounds and worker cleanup."""

import asyncio
import threading
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.history import HistorySnapshot, HistoryStatus
from kuberich.domain.metrics import MetricStatus
from kuberich.domain.pulse import FAMILIES, PulsePredicate, PulseScope, PulseStatus
from kuberich.domain.resources import Discovery, DiscoveryIssue
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceSelection, ViewStatus
from kuberich.errors import AppError
from kuberich.services.pulse import PulseAccumulator, PulseService
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.support.connections import catalog_fixture, namespaces
from tests.support.metrics import NOW, ExpiryGate, metric_resource, sample, sample_list
from tests.support.pulse import pulse_object, pulse_resource, pulse_roots
from tests.support.resources import collection, reader_fixture
from tests.support.workspace import stable_watch, wait_for, workspace_api


def scope_for(namespace="team"):
    return PulseScope(SessionIdentity("owned-context", 1), namespace)


def family_collection(name, *values, token=""):
    return {**collection(*values, token=token), "apiVersion": pulse_resource(name).api_version}


def overview_response(request):
    name = request.path.rsplit("/", 1)[1]
    namespace = request.path.split("/")[-2] if "/namespaces/" in request.path else "team"
    if "/metrics.k8s.io/" in request.path:
        return web.json_response(
            sample_list(sample(namespace=None if name == "nodes" else namespace), name=name)
        )
    return web.json_response(family_collection(name, pulse_object(name, namespace=namespace)))


def immediate(response):
    async def handler(request):
        return response(request)

    return handler


@pytest.mark.asyncio
async def test_real_serialized_families_progressive_pages_rbac_and_distinct_metrics(tmp_path):
    roots = pulse_roots()
    active = 0
    peak = 0
    calls = []
    observations = []

    async def handler(request):
        nonlocal active, peak
        if request.path in roots:
            return web.json_response(roots[request.path])
        active += 1
        peak = max(peak, active)
        calls.append((request.path, dict(request.query), request.headers.get("Authorization")))
        try:
            await asyncio.sleep(0)
            if request.path.endswith("/jobs"):
                return web.Response(status=403)
            if request.path == "/api/v1/namespaces/team/pods":
                if not request.query.get("continue"):
                    return web.json_response(
                        family_collection("pods", pulse_object(), token="next")
                    )
                return web.json_response(
                    family_collection(
                        "pods", pulse_object(identity="second", status={"phase": "Pending"})
                    )
                )
            return overview_response(request)
        finally:
            active -= 1

    async with reader_fixture(tmp_path, handler) as reader:
        service = PulseService(
            reader, await reader.discover(), scope_for(), lambda: True, now=lambda: NOW
        )
        result = await service.collect(observations.append)
        sources = {source.key: source for source in result.sources}
        assert peak == 1 and len(sources) == 10
        assert sources["jobs"].status is PulseStatus.FORBIDDEN and sources["jobs"].count is None
        assert sources["pods"].complete and sources["pods"].count == 2
        assert sources["pod_metrics"].status is PulseStatus.PARTIAL
        assert result.node_metrics.cpu.capacity == 4
        assert (
            result.node_metrics.cpu.usage != result.pod_metrics.cpu.usage
            or result.pod_metrics.cpu.partial
        )
        pending = next(row for row in result.rows if row.key == "pods:pod-unscheduled")
        assert pending.count == 1 and pending.drilldown.predicate is PulsePredicate.POD_UNSCHEDULED
        assert pending.drilldown.resource == sources["pods"].resource
        assert any(
            any(
                source.key == "pods" and source.count == 1 and not source.complete
                for source in observation.sources
            )
            for observation in observations
        )
        assert all(auth == "Bearer synthetic" for _, _, auth in calls)
        assert not any("watch" in query for _, query, _ in calls)
        assert service.retained_count == service.retained_bytes == 0
        assert result.observed_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (403, PulseStatus.FORBIDDEN),
        (404, PulseStatus.UNAVAILABLE),
        (503, PulseStatus.UNAVAILABLE),
        (401, PulseStatus.FAILED),
        (500, PulseStatus.FAILED),
    ],
)
async def test_read_failures_are_per_source_not_healthy_or_fabricated_zero(tmp_path, code, status):
    async def handler(request):
        return web.Response(status=code)

    async with reader_fixture(tmp_path, handler) as reader:
        discovery = Discovery(tuple(pulse_resource(name) for _, name in FAMILIES))
        result = await PulseService(reader, discovery, scope_for(), lambda: True).collect(
            lambda _: None
        )
        assert all(
            source.status is status for source in result.sources if source.resource is not None
        )
        assert all(row.count is None for row in result.rows)
        assert result.node_metrics.cpu.usage is result.pod_metrics.cpu.usage is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issues,status",
    [
        ((), PulseStatus.UNAVAILABLE),
        ((DiscoveryIssue("/apis", "forbidden", 403),), PulseStatus.FORBIDDEN),
        ((DiscoveryIssue("metrics.k8s.io/v1", "forbidden", 403),), PulseStatus.FORBIDDEN),
    ],
)
async def test_missing_metrics_and_discovery_denial_remain_distinct(tmp_path, issues, status):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return overview_response(request)

    async with reader_fixture(tmp_path, handler) as reader:
        service = PulseService(
            reader, Discovery((pulse_resource(),), issues), scope_for(), lambda: True
        )
        result = await service.collect(lambda _: None)
        assert [source.status for source in result.sources if source.key.endswith("_metrics")] == [
            status,
            status,
        ]
        assert len(calls) == 1 and result.pod_metrics.cpu.request is not None
        assert result.pod_metrics.cpu.usage is None


@pytest.mark.asyncio
async def test_large_collections_share_a_combined_retention_bound_and_keep_subset_status(tmp_path):
    roots = pulse_roots()
    observations = []

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        name = request.path.rsplit("/", 1)[1]
        if "/metrics.k8s.io/" in request.path:
            return web.json_response(
                sample_list(
                    *(
                        sample(f"item-{index}", namespace=None if name == "nodes" else "team")
                        for index in range(100)
                    ),
                    name=name,
                )
            )
        return web.json_response(
            family_collection(name, *(pulse_object(name, f"item-{index}") for index in range(100)))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        service = PulseService(
            reader,
            await reader.discover(),
            scope_for(),
            lambda: True,
            max_items=4,
            max_retained_bytes=65536,
            now=lambda: NOW,
        )
        result = await service.collect(observations.append)
        assert service.peak_retained_count <= 4 and service.peak_retained_bytes <= 65536
        assert service.retained_count == 0
        assert all(
            source.limited and source.status is PulseStatus.PARTIAL for source in result.sources
        )
        assert result.node_metrics.cpu.uncertain and result.pod_metrics.cpu.uncertain
        assert all(row.drilldown is not None for row in result.rows)
        assert len(observations) <= 32


@pytest.mark.asyncio
async def test_name_replacement_during_metrics_read_cannot_inherit_old_usage(tmp_path):
    roots = pulse_roots()
    counts = {}

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        name = request.path.rsplit("/", 1)[1]
        if "/metrics.k8s.io/" in request.path:
            return overview_response(request)
        counts[name] = counts.get(name, 0) + 1
        value = pulse_object(name)
        if name in {"pods", "nodes"} and counts[name] > 1:
            value["metadata"]["uid"] = "new-owner"
        return web.json_response(family_collection(name, value))

    async with reader_fixture(tmp_path, handler) as reader:
        result = await PulseService(
            reader, await reader.discover(), scope_for(), lambda: True, now=lambda: NOW
        ).collect(lambda _: None)
        assert result.node_metrics.cpu.usage is result.pod_metrics.cpu.usage is None
        assert result.node_metrics.cpu.capacity == 4
        assert result.pod_metrics.cpu.request is not None and result.pod_metrics.cpu.uncertain


@pytest.mark.asyncio
async def test_metrics_and_history_expire_while_next_refresh_is_blocked_and_timer_drains(tmp_path):
    roots = pulse_roots()
    block = asyncio.Event()
    reached = asyncio.Event()
    gate = ExpiryGate()
    clock = [NOW]
    observations = []
    blocked = [False]

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        if (
            blocked[0]
            and request.path.endswith("/nodes")
            and "/metrics.k8s.io/" not in request.path
        ):
            reached.set()
            await block.wait()
        return overview_response(request)

    async def history():
        return HistorySnapshot(HistoryStatus.VALID, observed_at=NOW)

    async with reader_fixture(tmp_path, handler) as reader:
        service = PulseService(
            reader,
            await reader.discover(),
            scope_for(),
            lambda: True,
            history=history,
            interval=0.01,
            now=lambda: clock[0],
            expiry_sleep=gate,
        )
        task = asyncio.create_task(service.run(observations.append))
        try:
            await wait_for(lambda: service.snapshot.history is not None)
            assert service.snapshot.node_metrics.cpu.usage is not None
            blocked[0] = True
            await asyncio.wait_for(reached.wait(), 5)
            clock[0] = NOW + timedelta(seconds=61)
            await wait_for(lambda: bool(gate.waits))
            gate.waits[0][1].set()
            await wait_for(lambda: service.snapshot.history.status is HistoryStatus.STALE)
            assert service.snapshot.node_metrics.cpu.usage is None
            assert service.snapshot.pod_metrics.cpu.usage is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            block.set()
        assert len(gate.finished) == len(gate.waits) and service.retained_count == 0


@pytest.mark.asyncio
async def test_cancelled_incremental_worker_is_drained_before_scope_can_retire(
    tmp_path, monkeypatch
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = PulseAccumulator.apply

    def apply(self, snapshot):
        started.set()
        release.wait(5)
        try:
            return original(self, snapshot)
        finally:
            finished.set()

    monkeypatch.setattr(PulseAccumulator, "apply", apply)
    async with reader_fixture(tmp_path, immediate(overview_response)) as reader:
        service = PulseService(reader, Discovery((pulse_resource(),)), scope_for(), lambda: True)
        task = asyncio.create_task(service.collect(lambda _: None))
        try:
            await wait_for(started.is_set)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_workspace_native_pulse_stops_watch_preserves_namespace_and_drains_before_context(
    tmp_path,
):
    calls = []
    history_scopes = []

    async def namespace_handler(request):
        return namespaces("default", "team")

    async def resources(request):
        calls.append((request.path, "watch" in request.query))
        if "watch" in request.query:
            return await stable_watch(request)
        return overview_response(request)

    async def history(client, scope):
        history_scopes.append((client, scope))
        return HistorySnapshot()

    async with workspace_api(namespace_handler, resources, discovery_roots=pulse_roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()),
            pulse_history=history,
        )
        subscription = owner.subscribe()
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            await owner.select_pulse()
            await wait_for(
                lambda: (
                    owner.store.observation.pulse is not None
                    and owner.store.observation.pulse.history is not None
                )
            )
            first = owner.store.observation
            assert owner.pulse_selected and owner.ownership.pulse_count == 1
            assert owner.ownership.watch_count == owner.ownership.metrics_count == 0
            assert first.scope is first.snapshot is None
            assert (await anext(subscription)) is first
            transition = owner.select_namespace("default")
            assert owner.store.observation.pulse is None
            await transition
            await wait_for(
                lambda: (
                    owner.store.observation.pulse is not None
                    and owner.store.observation.pulse.history is not None
                )
            )
            second = owner.store.observation
            assert second.pulse.scope.namespace == "default"
            assert second.pulse.scope.session.generation > first.pulse.scope.session.generation
            assert not owner.store.apply_pulse(first.revision, first.pulse)
            assert history_scopes[-1][0] is owner.sessions.client
            assert history_scopes[-1][1] == second.pulse.scope
            await owner.refresh_discovery()
            await wait_for(lambda: owner.store.observation.pulse is not None)
            await owner.select_resource(ResourceSelection())
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert not owner.pulse_selected and owner.store.observation.pulse is None
            assert owner.ownership.pulse_count == 0 and owner.ownership.watch_count == 1
        finally:
            await owner.close()
        assert owner.ownership.pulse_count == 0 and owner.ownership.close_complete
        assert owner.sessions.client is None


@pytest.mark.asyncio
async def test_workspace_preconnect_and_inflight_pulse_selection_is_a_real_mode(tmp_path):
    async def namespace_handler(request):
        return namespaces("team")

    async with workspace_api(
        namespace_handler,
        immediate(overview_response),
        discovery_roots=pulse_roots,
    ) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.select_pulse()
            assert owner.pulse_selected
            connect = owner.connect("kuberich-test-one")
            await owner.select_pulse()
            await connect
            await wait_for(
                lambda: (
                    owner.store.observation.pulse is not None
                    and owner.store.observation.status is ViewStatus.LIVE
                )
            )
            assert owner.store.observation.scope is None
            await owner.connect("kuberich-test-Two")
            await wait_for(lambda: owner.store.observation.pulse is not None)
            assert owner.store.observation.pulse.scope.session.context == "kuberich-test-Two"
        finally:
            await owner.close()
        with pytest.raises(AppError, match="closed"):
            owner.select_pulse()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": 0},
        {"max_items": 10001},
        {"max_items": True},
        {"max_retained_bytes": 3},
        {"max_retained_bytes": True},
        {"max_retained_bytes": 2**30},
        {"interval": 0},
        {"interval": 61},
    ],
)
async def test_invalid_pulse_bounds_fail_without_io(tmp_path, kwargs):
    async with reader_fixture(tmp_path, immediate(lambda _: web.Response(status=500))) as reader:
        with pytest.raises(AppError):
            PulseService(reader, Discovery(()), scope_for(), lambda: True, **kwargs)


@pytest.mark.asyncio
async def test_obsolete_scope_is_rejected_before_collection_and_publication(tmp_path):
    async with reader_fixture(tmp_path, immediate(lambda _: web.Response(status=500))) as reader:
        service = PulseService(reader, Discovery(()), scope_for(), lambda: False)
        with pytest.raises(asyncio.CancelledError):
            await service.collect(lambda _: pytest.fail("Old scope must not publish"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{"max_items": 0}, {"max_retained_bytes": 0}, {"max_items": 1}, {"max_retained_bytes": 1}],
)
async def test_reader_accepts_smaller_or_exhausted_retention_budgets_without_claiming_completeness(
    tmp_path, kwargs
):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(
            family_collection("pods", pulse_object(), pulse_object(identity="second"))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        result = await reader.list(pulse_resource(), "team", **kwargs)
        assert not result.collection.complete and result.collection.limited
        assert len(result.items) <= 1
        assert bool(calls) is all(value > 0 for value in kwargs.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": -1},
        {"max_items": True},
        {"max_items": 10001},
        {"max_retained_bytes": -1},
        {"max_retained_bytes": True},
        {"max_retained_bytes": 2**30},
    ],
)
async def test_reader_retention_cannot_raise_existing_ceilings(tmp_path, kwargs):
    async with reader_fixture(tmp_path, immediate(lambda _: web.Response(status=500))) as reader:
        with pytest.raises(AppError):
            await reader.list(pulse_resource(), "team", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", [403, 404, 500, "invalid-metrics", "invalid-collection", "invalid-budget"]
)
async def test_metrics_and_invalid_owned_payload_failures_preserve_known_capacity_and_budget(
    tmp_path, mode
):
    roots = pulse_roots()

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        name = request.path.rsplit("/", 1)[1]
        if "/metrics.k8s.io/" in request.path:
            if isinstance(mode, int):
                return web.Response(status=mode)
            if mode == "invalid-metrics":
                value = sample(namespace=None if name == "nodes" else "team")
                value["window"] = "untrusted"
                return web.json_response(sample_list(value, name=name))
        if name == "pods" and mode == "invalid-collection":
            return web.json_response({"items": "invalid"})
        if name == "pods" and mode == "invalid-budget":
            value = pulse_object()
            value["spec"]["containers"] = "invalid"
            return web.json_response(family_collection("pods", value))
        return overview_response(request)

    async with reader_fixture(tmp_path, handler) as reader:
        result = await PulseService(
            reader, await reader.discover(), scope_for(), lambda: True, now=lambda: NOW
        ).collect(lambda _: None)
        assert result.node_metrics.cpu.capacity == 4
        if mode in ("invalid-collection", "invalid-budget"):
            assert (
                next(source for source in result.sources if source.key == "pods").status
                is PulseStatus.FAILED
            )
            assert all(row.count is None for row in result.rows if row.source == "pods")
        else:
            assert result.pod_metrics.cpu.request is not None
            assert result.node_metrics.cpu.usage is result.pod_metrics.cpu.usage is None
            assert result.node_metrics.status in (
                MetricStatus.FORBIDDEN,
                MetricStatus.UNAVAILABLE,
                MetricStatus.ERROR,
            )


@pytest.mark.asyncio
async def test_metrics_endpoint_without_resource_membership_cannot_claim_verified_current_usage(
    tmp_path,
):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return overview_response(request)

    async with reader_fixture(tmp_path, handler) as reader:
        result = await PulseService(
            reader,
            Discovery((metric_resource(), metric_resource("nodes"))),
            scope_for(),
            lambda: True,
        ).collect(lambda _: None)
        assert not calls
        assert result.node_metrics.status is result.pod_metrics.status is MetricStatus.UNAVAILABLE
        assert all(
            "membership unavailable" in source.detail
            for source in result.sources
            if source.key.endswith("_metrics")
        )


@pytest.mark.asyncio
async def test_context_replacement_drains_pulse_parser_before_retiring_captured_client(
    tmp_path, monkeypatch
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = PulseAccumulator.apply

    def apply(self, snapshot):
        if not finished.is_set():
            started.set()
            release.wait(5)
            finished.set()
        return original(self, snapshot)

    monkeypatch.setattr(PulseAccumulator, "apply", apply)

    async def namespace_handler(request):
        return namespaces("team")

    async def resource_handler(request):
        return overview_response(request)

    async with workspace_api(
        namespace_handler, resource_handler, discovery_roots=pulse_roots
    ) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.select_pulse()
            await owner.connect("kuberich-test-one")
            await wait_for(started.is_set)
            client = owner.sessions.client
            previous_api = client.api
            previous_directory = client.directory.name
            replacement = owner.connect("kuberich-test-Two")
            assert owner.store.observation.pulse is None
            await asyncio.sleep(0.01)
            assert (
                owner.sessions.client is client and not previous_api.rest_client.pool_manager.closed
            )
            release.set()
            await replacement
            await wait_for(
                lambda: (
                    owner.store.observation.pulse is not None
                    and owner.store.observation.status is ViewStatus.LIVE
                )
            )
            assert finished.is_set() and previous_api.rest_client.pool_manager.closed
            assert not Path(previous_directory).exists()
            assert owner.store.observation.pulse.scope.session.context == "kuberich-test-Two"
        finally:
            release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_expiry_cleanup_and_inactive_run_needs_no_reads(
    tmp_path,
):
    started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    block = asyncio.Event()

    async def sleeping(delay):
        started.set()
        try:
            await block.wait()
        finally:
            cleanup.set()
            await release.wait()

    async def handler(request):
        await block.wait()
        return overview_response(request)

    async with reader_fixture(tmp_path, handler) as reader:
        inactive = PulseService(reader, Discovery(()), scope_for(), lambda: False)
        await inactive.run(lambda _: pytest.fail("Inactive collector must not publish"))
        service = PulseService(
            reader, Discovery((pulse_resource(),)), scope_for(), lambda: True, expiry_sleep=sleeping
        )
        task = asyncio.create_task(service.run(lambda _: None))
        try:
            await started.wait()
            task.cancel()
            await cleanup.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert service.retained_count == service.retained_bytes == 0
        finally:
            release.set()
            block.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_membership_loss_after_success_clears_usage_and_marks_retained_budgets_uncertain(
    tmp_path,
):
    roots = pulse_roots()
    failed = [False]
    clock = [NOW]

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        if failed[0] and "/metrics.k8s.io/" not in request.path:
            return web.Response(status=403)
        return overview_response(request)

    async with reader_fixture(tmp_path, handler) as reader:
        service = PulseService(
            reader, await reader.discover(), scope_for(), lambda: True, now=lambda: clock[0]
        )
        first = await service.collect(lambda _: None)
        assert first.node_metrics.cpu.usage == first.pod_metrics.cpu.usage
        assert first.node_metrics.cpu.usage is not None
        failed[0] = True
        clock[0] = NOW + timedelta(seconds=30)
        unavailable = await service.collect(lambda _: None)
        assert unavailable.node_metrics.cpu.usage is unavailable.pod_metrics.cpu.usage is None
        assert (
            unavailable.pod_metrics.cpu.uncertain and unavailable.pod_metrics.allocation_uncertain
        )
        assert unavailable.node_metrics.cpu.capacity == first.node_metrics.cpu.capacity
        for key in ("nodes", "pods"):
            retained_source = next(source for source in unavailable.sources if source.key == key)
            assert retained_source.observed_at == NOW
            assert retained_source.attempted_at == clock[0]
            assert retained_source.status is PulseStatus.FORBIDDEN
        assert unavailable.node_metrics.cpu.uncertain
        assert unavailable.capacity_observed_at == unavailable.budgets_observed_at == NOW
        assert all(row.count is None for row in unavailable.rows)
        assert (
            next(source for source in unavailable.sources if source.key == "pods").status
            is PulseStatus.FORBIDDEN
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,projection", [("nodes", "capacity_observed_at"), ("pods", "budgets_observed_at")]
)
async def test_held_progress_page_keeps_actual_projection_time_through_later_403(
    tmp_path, name, projection
):
    roots = pulse_roots()
    clock = [NOW]
    partial = [False]
    blocked, release = asyncio.Event(), asyncio.Event()
    observations = []

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        if (
            partial[0]
            and "/metrics.k8s.io/" not in request.path
            and request.path.endswith("/" + name)
        ):
            if request.query.get("continue"):
                blocked.set()
                await release.wait()
                return web.Response(status=403)
            return web.json_response(family_collection(name, pulse_object(name), token="held"))
        return overview_response(request)

    async with reader_fixture(tmp_path, handler) as reader:
        service = PulseService(
            reader, await reader.discover(), scope_for(), lambda: True, now=lambda: clock[0]
        )
        first = await service.collect(lambda _: None)
        assert getattr(first, projection) == NOW
        clock[0] = NOW + timedelta(seconds=30)
        partial[0] = True
        task = asyncio.create_task(service.collect(observations.append))
        try:
            await asyncio.wait_for(blocked.wait(), 5)
            during = observations[-1]
            source = next(source for source in during.sources if source.key == name)
            assert source.status is PulseStatus.PARTIAL and source.observed_at == clock[0]
            assert getattr(during, projection) == NOW
            report = during.node_metrics if name == "nodes" else during.pod_metrics
            assert report.cpu.capacity == 4 if name == "nodes" else report.cpu.request is not None
            release.set()
            failed = await task
            assert getattr(failed, projection) == NOW
            source = next(source for source in failed.sources if source.key == name)
            assert source.status is PulseStatus.FORBIDDEN and source.observed_at == NOW
            assert source.attempted_at == clock[0]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_previous_cache_from_another_session_or_namespace_fails_before_io(tmp_path):
    async with reader_fixture(tmp_path, immediate(lambda _: web.Response(status=500))) as reader:
        service = PulseService(reader, Discovery(()), scope_for(), lambda: True)
        service.snapshot = replace(service.snapshot, scope=scope_for("default"))
        with pytest.raises(AppError, match="captured session and scope"):
            await service.collect(lambda _: pytest.fail("Previous scope must not publish"))
