"""Real HTTP metrics APIs, scope ownership, bounded polling and identity races."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.metrics import MetricStatus
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    Discovery,
    DiscoveryIssue,
    ResourceSnapshot,
    resource_record,
    split_api_version,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope
from kuberich.errors import AppError
from kuberich.services.metrics import MetricsPoller, reconcile, supports_metrics
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.support.connections import catalog_fixture, namespaces
from tests.support.metrics import (
    NOW,
    ExpiryGate,
    budgeted,
    metric_resource,
    metric_roots,
    sample,
    sample_list,
    samples,
)
from tests.support.pods import record, snapshot
from tests.support.resources import collection, pod_resource, reader_fixture
from tests.support.standard import api as standard_api
from tests.support.standard import row_record
from tests.support.workspace import stable_watch, wait_for, workspace_api


def scope_for(resource=None, namespace="team"):
    return ResourceScope(SessionIdentity("owned-context", 1), resource or pod_resource(), namespace)


def poller_for(reader, discovery, selected=None, **kwargs):
    selected = selected or snapshot(budgeted())
    return MetricsPoller(
        reader, discovery, scope_for(), lambda: selected, lambda: True, now=lambda: NOW, **kwargs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v1", "v1beta1", "v9"])
async def test_discovered_metrics_version_and_uidless_records_use_same_explicit_session(
    tmp_path, version
):
    calls = []
    roots = metric_roots(version)

    async def handler(request):
        calls.append((request.path, request.headers.get("Authorization")))
        if request.path in roots:
            return web.json_response(roots[request.path])
        assert request.path == f"/apis/metrics.k8s.io/{version}/namespaces/team/pods"
        return web.json_response(sample_list(sample(version=version), version=version))

    async with reader_fixture(tmp_path, handler) as reader:
        discovery = await reader.discover()
        result = await poller_for(reader, discovery).poll(snapshot(budgeted()))
        report = result.report("owned-api", NOW)
        assert report.status is MetricStatus.VALID and report.cpu.usage == Decimal(".25")
        assert report.cpu.percent("request") == 250
        assert {auth for _, auth in calls} == {"Bearer synthetic"}
        assert sum("/namespaces/team/pods" in path for path, _ in calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,state",
    [
        (403, MetricStatus.FORBIDDEN),
        (404, MetricStatus.UNAVAILABLE),
        (503, MetricStatus.UNAVAILABLE),
        (401, MetricStatus.ERROR),
        (500, MetricStatus.ERROR),
    ],
)
async def test_http_availability_retains_requests_and_never_becomes_zero(tmp_path, code, state):
    async def handler(request):
        return web.Response(status=code)

    async with reader_fixture(tmp_path, handler) as reader:
        discovery = Discovery((pod_resource(), metric_resource()))
        selected = snapshot(budgeted())
        result = await poller_for(reader, discovery).poll(selected)
        report = result.report("owned-api", NOW)
        assert report.status is state and report.cpu.usage is None
        assert report.cpu.request == Decimal(".1") and report.cpu.limit == 1
        assert f"HTTP {code}" in report.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issues,state",
    [
        ((), MetricStatus.UNAVAILABLE),
        ((DiscoveryIssue("/apis", "forbidden", 403),), MetricStatus.FORBIDDEN),
        ((DiscoveryIssue("metrics.k8s.io/v1", "forbidden", 403),), MetricStatus.FORBIDDEN),
        ((DiscoveryIssue("other.test/v1", "forbidden", 403),), MetricStatus.UNAVAILABLE),
        (
            (DiscoveryIssue("metrics.k8s.io.example/v1", "forbidden", 403),),
            MetricStatus.UNAVAILABLE,
        ),
    ],
)
async def test_missing_discovered_api_differs_from_forbidden_discovery_and_no_sample(
    tmp_path, issues, state
):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.Response(status=500)

    async with reader_fixture(tmp_path, handler) as reader:
        result = await poller_for(reader, Discovery((pod_resource(),), issues)).poll(
            snapshot(budgeted())
        )
        report = result.report("owned-api", NOW)
        assert (
            report.status is state
            and report.cpu.usage is None
            and report.cpu.request == Decimal(".1")
        )
        assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,state,usage",
    [
        ("empty", MetricStatus.NO_SAMPLE, None),
        ("zero", MetricStatus.VALID, Decimal(0)),
        ("stale", MetricStatus.STALE, None),
        ("malformed", MetricStatus.ERROR, None),
        ("oversized", MetricStatus.ERROR, None),
        ("timeout", MetricStatus.ERROR, None),
    ],
)
async def test_empty_zero_stale_http200_malformed_bounds_and_timeout_are_distinct(
    tmp_path, mode, state, usage
):
    async def handler(request):
        if mode == "timeout":
            await asyncio.sleep(0.1)
        if mode == "malformed":
            value = sample(containers=[{"name": "unknown", "usage": {}}])
        elif mode == "oversized":
            value = sample(containers=[{"name": "app"}] * 129)
        else:
            value = sample(
                cpu="0" if mode == "zero" else "250m",
                memory="0" if mode == "zero" else "64Mi",
                now=NOW - timedelta(seconds=61) if mode == "stale" else NOW,
            )
        return web.json_response(sample_list(*(() if mode == "empty" else (value,))))

    async with reader_fixture(
        tmp_path, handler, timeout=0.05 if mode == "timeout" else 5
    ) as reader:
        report = (
            await poller_for(reader, Discovery((pod_resource(), metric_resource()))).poll(
                snapshot(budgeted())
            )
        ).report("owned-api", NOW)
        assert report.status is state and report.cpu.usage == usage


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement,created", [(True, None), (False, NOW + timedelta(seconds=1))])
async def test_name_only_metrics_cannot_attach_to_replacement_or_precreation_sample(
    tmp_path, replacement, created
):
    selected = snapshot(budgeted(created=created))
    current = selected

    async def handler(request):
        nonlocal current
        if replacement:
            current = snapshot(budgeted(uid="replacement"))
        return web.json_response(sample_list(sample()))

    async with reader_fixture(tmp_path, handler) as reader:
        poller = MetricsPoller(
            reader,
            Discovery((pod_resource(), metric_resource())),
            scope_for(),
            lambda: current,
            lambda: True,
            now=lambda: NOW,
        )
        result = await poller.poll(selected)
        assert result.report("owned-api", NOW).cpu.usage is None
        assert result.report("replacement", NOW).cpu.usage is None


@pytest.mark.asyncio
async def test_poll_loop_serializes_batches_replaces_current_cache_and_drains_cancellation(
    tmp_path,
):
    active = peak = reads = 0
    entered = asyncio.Event()
    releases = asyncio.Queue()

    async def handler(request):
        nonlocal active, peak, reads
        reads += 1
        active += 1
        peak = max(active, peak)
        entered.set()
        try:
            await releases.get()
            return web.json_response(sample_list(sample(cpu=f"{reads}m")))
        finally:
            active -= 1

    async with reader_fixture(tmp_path, handler) as reader:
        current = True
        selected = snapshot(budgeted())
        observed = []
        poller = MetricsPoller(
            reader,
            Discovery((pod_resource(), metric_resource())),
            scope_for(),
            lambda: selected,
            lambda: current,
            interval=0.01,
            now=lambda: NOW,
        )
        task = asyncio.create_task(poller.run(observed.append))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await asyncio.sleep(0.03)
            assert reads == peak == 1
            await releases.put(None)
            await wait_for(lambda: len(observed) == 1)
            await wait_for(lambda: reads == 2)
            await releases.put(None)
            await wait_for(lambda: len(observed) == 2)
            assert observed[0].report("owned-api", NOW).cpu.usage == Decimal(".001")
            assert observed[1].report("owned-api", NOW).cpu.usage == Decimal(".002")
            await wait_for(lambda: reads == 3)
            current = False
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(observed) == 2 and peak == 1
        finally:
            current = False
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await releases.put(None)


@pytest.mark.asyncio
async def test_waiting_poller_wakes_for_first_snapshot_and_rejects_late_generation(tmp_path):
    selected = None
    current = True

    async def handler(request):
        nonlocal current
        current = False
        return web.json_response(sample_list(sample()))

    async with reader_fixture(tmp_path, handler) as reader:
        observed = []
        poller = MetricsPoller(
            reader,
            Discovery((pod_resource(), metric_resource())),
            scope_for(),
            lambda: selected,
            lambda: current,
            interval=0.01,
            now=lambda: NOW,
        )
        task = asyncio.create_task(poller.run(observed.append))
        await asyncio.sleep(0.01)
        assert not task.done() and not observed
        selected = snapshot(budgeted())
        poller.wake()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not observed


def owner(record, parent, kind, version):
    value = record.manifest
    value["metadata"]["ownerReferences"] = [
        {
            "apiVersion": version,
            "kind": kind,
            "name": parent.name,
            "uid": parent.uid,
            "controller": True,
        }
    ]
    return resource_record(
        ApiResource(
            *split_api_version(value["apiVersion"]),
            "fixtures",
            value["kind"],
            record.namespace is not None,
            frozenset({"get", "list", "watch"}),
        ),
        value,
        record.namespace,
    )


@pytest.mark.parametrize(
    "kind,intermediate_name,intermediate_kind",
    [
        ("deployments", "replicasets", "ReplicaSet"),
        ("cronjobs", "jobs", "Job"),
        ("replicasets", None, None),
        ("statefulsets", None, None),
        ("daemonsets", None, None),
        ("jobs", None, None),
    ],
)
def test_workload_totals_follow_actual_uid_controller_chains_not_desired_replicas_or_labels(
    kind, intermediate_name, intermediate_kind
):
    definition = RESOURCE_ALIASES[kind]
    resource = standard_api(definition)
    target = row_record(definition, uid="workload")
    selected = ResourceSnapshot(resource, "team", "rv", (target,))
    scope = scope_for(resource)
    intermediates = None
    if intermediate_name:
        mid_definition = RESOURCE_ALIASES[intermediate_name]
        mid = owner(
            row_record(mid_definition, uid="intermediate"),
            target,
            resource.kind,
            resource.api_version,
        )
        intermediates = ResourceSnapshot(standard_api(mid_definition), "team", "rv", (mid,))
        parent = mid
        parent_version = standard_api(mid_definition).api_version
    else:
        parent, parent_version = target, resource.api_version
    member = owner(record(budgeted()), parent, intermediate_kind or resource.kind, parent_version)
    # A same-name controller with another UID, and matching labels, is not membership.
    outsider = owner(
        record(budgeted(name="outsider")),
        replace(parent, uid="other-controller"),
        intermediate_kind or resource.kind,
        parent_version,
    )
    pods = replace(snapshot(), items=(member, outsider))
    result = reconcile(
        scope,
        selected,
        pods,
        pods,
        samples(sample(), sample("outsider", cpu="9")),
        intermediates,
        NOW,
    )
    report = result.report(target.uid, NOW)
    assert report.status is MetricStatus.VALID and report.cpu.usage == Decimal(".25")
    assert report.cpu.request == Decimal(".1") and report.cpu.limit == 1
    assert "1/1 Pods" in report.detail
    missing = reconcile(
        scope,
        selected,
        pods,
        replace(pods, collection=CollectionState(complete=False)),
        samples(sample()),
        intermediates,
        NOW,
    )
    assert missing.report(target.uid, NOW).cpu.percent("request") is None


@pytest.mark.asyncio
async def test_workspace_namespace_context_switch_and_exit_cancel_old_metrics_http_reads(tmp_path):
    reads = []
    entered = asyncio.Event()

    async def ns(request):
        return namespaces("team", "default")

    async def handler(request):
        if request.path.startswith("/apis/metrics.k8s.io/"):
            reads.append((request.path, request.transport))
            entered.set()
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.001)
            return web.Response()
        if "watch" in request.query:
            return await stable_watch(request)
        namespace = "default" if "/namespaces/default/" in request.path else "team"
        return web.json_response(collection(budgeted(namespace=namespace)))

    async with workspace_api(ns, handler, discovery_roots=metric_roots) as url:
        config = catalog_fixture(tmp_path, url)
        before = (tmp_path / "fixture-config").read_bytes()
        workspace = WorkspaceService(SessionService(config, ConnectionRequest()))
        await workspace.connect("kuberich-test-one")
        await asyncio.wait_for(entered.wait(), 5)
        assert workspace.ownership.metrics_count == 1
        first_transport = reads[-1][1]
        entered.clear()
        await workspace.select_namespace("default")
        await asyncio.wait_for(entered.wait(), 5)
        await wait_for(first_transport.is_closing)
        assert reads[-1][0].endswith("/namespaces/default/pods")
        second_transport = reads[-1][1]
        entered.clear()
        await workspace.connect("kuberich-test-Two")
        await asyncio.wait_for(entered.wait(), 5)
        await wait_for(second_transport.is_closing)
        third_transport = reads[-1][1]
        await workspace.close()
        await wait_for(third_transport.is_closing)
        assert workspace.ownership.metrics_count == workspace.ownership.watch_count == 0
        assert workspace.sessions.client is None
        assert (tmp_path / "fixture-config").read_bytes() == before


def test_metrics_supported_views_and_poll_interval_bounds():
    assert supports_metrics(scope_for())
    assert not supports_metrics(scope_for(replace(pod_resource(), name="services")))
    for interval in (0, 61, float("nan")):
        with pytest.raises(AppError, match="interval"):
            MetricsPoller(None, None, None, None, None, interval=interval)


@pytest.mark.asyncio
@pytest.mark.parametrize("pod_code,node_code", [(200, 403), (403, 200)])
async def test_pod_and_node_metric_permissions_are_independent_on_same_client(
    tmp_path, pod_code, node_code
):
    node_api = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list", "watch"}))
    node = resource_record(
        node_api,
        {
            "metadata": {"name": "node", "uid": "node-uid", "resourceVersion": "rv"},
            "status": {"capacity": {"cpu": "4"}, "allocatable": {"cpu": "3"}},
        },
    )
    node_snapshot = ResourceSnapshot(node_api, None, "rv", (node,))
    pod_snapshot = snapshot(budgeted())
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path == "/api/v1/pods":
            return web.Response(status=403)  # namespace-only Pod list permission
        if request.path.endswith("/nodes"):
            return (
                web.Response(status=node_code)
                if node_code != 200
                else web.json_response(
                    sample_list(sample("node", namespace=None, cpu="1500m"), name="nodes")
                )
            )
        return (
            web.Response(status=pod_code)
            if pod_code != 200
            else web.json_response(sample_list(sample()))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        discovery = Discovery(
            (pod_resource(), node_api, metric_resource(), metric_resource("nodes"))
        )
        pod_poller = poller_for(reader, discovery, pod_snapshot)
        node_poller = MetricsPoller(
            reader,
            discovery,
            scope_for(node_api, None),
            lambda: node_snapshot,
            lambda: True,
            now=lambda: NOW,
        )
        first = (await pod_poller.poll(pod_snapshot)).report("owned-api", NOW)
        node_report = (await node_poller.poll(node_snapshot)).report("node-uid", NOW)
        again = (await pod_poller.poll(pod_snapshot)).report("owned-api", NOW)
        assert first == again
        if pod_code == 200:
            assert first.status is MetricStatus.VALID and first.cpu.usage == Decimal(".25")
            assert node_report.status is MetricStatus.FORBIDDEN and node_report.cpu.usage is None
        else:
            assert first.status is MetricStatus.FORBIDDEN and first.cpu.usage is None
            assert node_report.status is MetricStatus.VALID and node_report.cpu.usage == Decimal(
                "1.5"
            )
            assert node_report.cpu.percent("allocatable") == 50
        assert node_report.cpu.capacity == 4 and node_report.cpu.allocatable == 3
        assert node_report.value("cpu-req")[1] is None and "Pod membership" in node_report.detail
        assert calls.count("/apis/metrics.k8s.io/v1/namespaces/team/pods") == 2
        assert calls.count("/apis/metrics.k8s.io/v1/nodes") == 1


@pytest.mark.asyncio
async def test_workload_poller_reads_batched_actual_pod_and_replicaset_membership(tmp_path):
    definition = RESOURCE_ALIASES["deployments"]
    resource = standard_api(definition)
    target = row_record(definition)
    selected = ResourceSnapshot(resource, "team", "rv", (target,))
    rs_definition = RESOURCE_ALIASES["replicasets"]
    rs = owner(row_record(rs_definition, uid="rs"), target, "Deployment", "apps/v1")
    member = owner(record(budgeted()), rs, "ReplicaSet", "apps/v1")
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path.startswith("/apis/metrics.k8s.io/"):
            return web.json_response(sample_list(sample()))
        if request.path.endswith("/replicasets"):
            return web.json_response(
                {
                    "apiVersion": "apps/v1",
                    "kind": "ReplicaSetList",
                    "metadata": {"resourceVersion": "rv"},
                    "items": [rs.manifest],
                }
            )
        return web.json_response(collection(member.manifest))

    async with reader_fixture(tmp_path, handler) as reader:
        discovery = Discovery(
            (resource, standard_api(rs_definition), pod_resource(), metric_resource())
        )
        poller = MetricsPoller(
            reader, discovery, scope_for(resource), lambda: selected, lambda: True, now=lambda: NOW
        )
        report = (await poller.poll(selected)).report(target.uid, NOW)
        assert report.status is MetricStatus.VALID and report.cpu.usage == Decimal(".25")
        assert calls == [
            "/api/v1/namespaces/team/pods",
            "/apis/apps/v1/namespaces/team/replicasets",
            "/apis/metrics.k8s.io/v1/namespaces/team/pods",
            "/api/v1/namespaces/team/pods",
        ]


@pytest.mark.asyncio
async def test_node_poller_includes_only_scheduled_nonterminal_pod_requests(tmp_path):
    node_api = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list", "watch"}))
    node = resource_record(
        node_api,
        {
            "metadata": {"name": "node", "uid": "node", "resourceVersion": "rv"},
            "status": {"capacity": {"cpu": "4"}, "allocatable": {"cpu": "3"}},
        },
    )
    selected = ResourceSnapshot(node_api, None, "rv", (node,))
    live, terminal = budgeted(), budgeted("finished", request="9")
    live["spec"]["nodeName"] = terminal["spec"]["nodeName"] = "node"
    terminal["status"]["phase"] = "Succeeded"

    async def handler(request):
        if request.path.startswith("/apis/metrics.k8s.io/"):
            return web.json_response(
                sample_list(sample("node", namespace=None, cpu="1500m"), name="nodes")
            )
        return web.json_response(collection(live, terminal))

    async with reader_fixture(tmp_path, handler) as reader:
        poller = MetricsPoller(
            reader,
            Discovery((pod_resource(), metric_resource("nodes"))),
            scope_for(node_api, None),
            lambda: selected,
            lambda: True,
            now=lambda: NOW,
        )
        report = (await poller.poll(selected)).report("node", NOW)
        assert report.cpu.usage == Decimal("1.5") and report.cpu.request == Decimal(".1")
        assert report.cpu.percent("allocatable") == 50
        assert report.cpu.percent("request") == 1500


@pytest.mark.asyncio
@pytest.mark.parametrize("pod_cpu,unconfirmed", [("100000000n", False), ("99m", True)])
async def test_real_http_admitted_status_preserves_configured_percentages(
    tmp_path, pod_cpu, unconfirmed
):
    from tests.support.metrics import admitted

    value = admitted()
    observed = value["status"]["containerStatuses"][0]
    observed["allocatedResources"] = {"cpu": "0.1", "memory": "33554432"}
    observed["resources"] = {
        "requests": {"cpu": "100000000n", "memory": "32768Ki"},
        "limits": {"cpu": "1000m", "memory": "134217728"},
    }
    value["status"]["resources"]["requests"]["cpu"] = pod_cpu
    selected = snapshot(value)

    async def handler(request):
        return web.json_response(sample_list(sample()))

    async with reader_fixture(tmp_path, handler) as reader:
        result = await poller_for(
            reader, Discovery((pod_resource(), metric_resource())), selected
        ).poll(selected)
        report = result.report("owned-api", NOW)
        assert report.status is MetricStatus.VALID and not report.cpu.uncertain
        assert report.allocation_uncertain is unconfirmed
        assert report.cpu.request == Decimal(".1") and report.cpu.limit == 1
        assert report.memory.request == 32 * 2**20 and report.memory.limit == 128 * 2**20
        assert report.cpu.percent("request") == 250 and report.cpu.percent("limit") == 25
        assert report.memory.percent("request") == 200 and report.memory.percent("limit") == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["replace", "cancel", "obsolete"])
async def test_fresh_batch_drains_old_expiry_before_publication_and_preserves_parent_cancellation(
    tmp_path,
    retirement,
):
    expiry_started, cancelling, finish_retire = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reads, current = 0, True
    release_read = asyncio.Event()
    expiry_waits = []
    observed = []

    async def expiry_sleep(delay):
        index = len(expiry_waits)
        expiry_waits.append(delay)
        if index == 0:
            expiry_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await finish_retire.wait()  # A late timer completion must not clear the new batch.
        else:
            await asyncio.Event().wait()

    async def handler(request):
        nonlocal reads
        reads += 1
        if reads > 1:
            await release_read.wait()
        return web.json_response(sample_list(sample(cpu=f"{reads}m")))

    async with reader_fixture(tmp_path, handler) as reader:
        poller = MetricsPoller(
            reader,
            Discovery((pod_resource(), metric_resource())),
            scope_for(),
            lambda: snapshot(budgeted()),
            lambda: current,
            interval=0.01,
            now=lambda: NOW,
            expiry_sleep=expiry_sleep,
        )
        task = asyncio.create_task(poller.run(observed.append))
        try:
            await asyncio.wait_for(expiry_started.wait(), 5)
            await wait_for(lambda: reads == 2)
            release_read.set()
            await asyncio.wait_for(cancelling.wait(), 5)
            assert len(observed) == 1
            if retirement == "cancel":
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done() and len(expiry_waits) == 1
            elif retirement == "obsolete":
                current = False
            finish_retire.set()
            if retirement == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
                assert len(observed) == 1 and reads == 2 and len(expiry_waits) == 1
            elif retirement == "obsolete":
                await asyncio.wait_for(task, 5)
                assert len(observed) == 1 and reads == 2 and len(expiry_waits) == 1
            else:
                await wait_for(lambda: len(observed) >= 2 and len(expiry_waits) >= 2)
                assert not any(batch.cache_expired for batch in observed)
                assert observed[1].report("owned-api", NOW).cpu.usage == Decimal(".002")
        finally:
            finish_retire.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert not [
            task for task in asyncio.all_tasks() if task.get_name() == "kuberich-metrics-expiry"
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("hold_peer_eof", [False, True])
async def test_workspace_cancels_and_awaits_expiry_with_pending_reads_on_scope_context_and_exit(
    tmp_path, monkeypatch, hold_peer_eof
):
    expiry = ExpiryGate()
    held, releases = [], asyncio.Event()
    counts = {}
    peer_checked = asyncio.Event()
    peer_waiter = None

    def peers_closed():
        closed = all(transport.is_closing() for transport in held)
        if not closed:
            peer_checked.set()
        return closed

    class ControlledPoller(MetricsPoller):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, interval=0.01, now=lambda: NOW, expiry_sleep=expiry)

    monkeypatch.setattr("kuberich.services.workspace.MetricsPoller", ControlledPoller)

    async def ns(request):
        return namespaces("team", "default")

    async def handler(request):
        namespace = (
            request.path.split("/namespaces/")[1].split("/")[0]
            if "/namespaces/" in request.path
            else "team"
        )
        if request.path.startswith("/apis/metrics.k8s.io/"):
            counts[request.path] = counts.get(request.path, 0) + 1
            if counts[request.path] % 2 == 0:
                held.append(request.transport)
                await releases.wait()
            return web.json_response(sample_list(sample(namespace=namespace)))
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(budgeted(namespace=namespace)))

    async with workspace_api(ns, handler, discovery_roots=metric_roots) as url:
        config = catalog_fixture(tmp_path, url)
        before = (tmp_path / "fixture-config").read_bytes()
        workspace = WorkspaceService(SessionService(config, ConnectionRequest(timeout=300)))
        try:
            await workspace.connect("kuberich-test-one")
            await wait_for(lambda: len(held) == 1 and len(expiry.waits) == 1)
            await workspace.select_namespace("default")
            await wait_for(
                lambda: len(held) == 2 and len(expiry.waits) == 2 and held[0].is_closing()
            )
            assert 0 in expiry.finished and held[0].is_closing()
            await workspace.connect("kuberich-test-Two")
            await wait_for(
                lambda: len(held) == 3 and len(expiry.waits) == 3 and held[1].is_closing()
            )
            assert 1 in expiry.finished and held[1].is_closing()
            if hold_peer_eof:
                held[2].pause_reading()
                assert not held[2].is_reading() and not held[2].is_closing()
            await workspace.close()
            assert expiry.finished == {0, 1, 2}
            assert workspace.ownership.metrics_count == 0
            assert workspace.sessions.client is None
            assert (tmp_path / "fixture-config").read_bytes() == before
            assert not [
                task for task in asyncio.all_tasks() if task.get_name() == "kuberich-metrics-expiry"
            ]
            # Local owners are drained; peer EOF is a separate asynchronous observation.
            peer_waiter = asyncio.create_task(wait_for(peers_closed))
            if hold_peer_eof:
                await asyncio.wait_for(peer_checked.wait(), 5)
                assert not peer_waiter.done()
                held[2].resume_reading()
            await peer_waiter
            assert all(transport.is_closing() for transport in held)
        finally:
            for transport in held:
                if not transport.is_closing():
                    transport.resume_reading()
            if peer_waiter is not None:
                peer_waiter.cancel()
                await asyncio.gather(peer_waiter, return_exceptions=True)
            try:
                await workspace.close()
            finally:
                releases.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["empty", "stale", "forbidden", "obsolete"])
async def test_unusable_batches_have_no_expiry_loop_and_obsolete_expiry_cannot_publish(
    tmp_path, state
):
    expiry, release = ExpiryGate(), asyncio.Event()
    current, reads = True, 0
    observed = []

    async def handler(request):
        nonlocal reads
        reads += 1
        if reads > 1:
            await release.wait()
        if state == "forbidden":
            return web.Response(status=403)
        return web.json_response(
            sample_list(
                *(
                    []
                    if state == "empty"
                    else [sample(now=NOW - timedelta(seconds=61) if state == "stale" else NOW)]
                )
            )
        )

    async with reader_fixture(tmp_path, handler) as reader:
        selected = snapshot(budgeted())
        poller = MetricsPoller(
            reader,
            Discovery((pod_resource(), metric_resource())),
            scope_for(),
            lambda: selected,
            lambda: current,
            interval=0.01,
            now=lambda: NOW,
            expiry_sleep=expiry,
        )
        task = asyncio.create_task(poller.run(observed.append))
        try:
            await wait_for(lambda: reads == 2 and len(observed) == 1)
            if state == "obsolete":
                await wait_for(lambda: len(expiry.waits) == 1)
                current = False
                expiry.waits[0][1].set()
                await wait_for(lambda: expiry.finished == {0})
                assert not observed[0].cache_expired
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert not expiry.waits and observed[0].report("owned-api", NOW).cpu.usage is None
            assert len(observed) == 1 and reads == 2
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            release.set()
        assert not [
            task for task in asyncio.all_tasks() if task.get_name() == "kuberich-metrics-expiry"
        ]
