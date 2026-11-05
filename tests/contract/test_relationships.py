"""Real owned loopback HTTP exercises relationship identity and finite collection."""

import asyncio
import threading
from dataclasses import asdict, replace

import pytest
from aiohttp import web

from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.relationships import (
    RelationDirection,
    RelationKind,
    RelationshipMode,
    RelationshipRequest,
    RelationshipScope,
    RelationshipStatus,
)
from kuberich.domain.resources import Discovery, api_resource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services import relationships
from kuberich.services.relationships import DECLARING_FAMILIES, RelationshipService
from kuberich.services.resources import ResourceReader
from tests.support.resources import collection, descriptor, item, reader_fixture

pytestmark = pytest.mark.fast

KINDS = {
    "pods": "Pod",
    "nodes": "Node",
    "deployments": "Deployment",
    "replicasets": "ReplicaSet",
    "statefulsets": "StatefulSet",
    "daemonsets": "DaemonSet",
    "jobs": "Job",
    "cronjobs": "CronJob",
    "replicationcontrollers": "ReplicationController",
    "serviceaccounts": "ServiceAccount",
    "secrets": "Secret",
    "configmaps": "ConfigMap",
    "persistentvolumeclaims": "PersistentVolumeClaim",
    "persistentvolumes": "PersistentVolume",
    "priorityclasses": "PriorityClass",
    "services": "Service",
    "endpoints": "Endpoints",
    "endpointslices": "EndpointSlice",
    "widgets": "Widget",
}


def resource(name="pods", group="", version="v1"):
    return api_resource(
        f"{group}/{version}" if group else version,
        descriptor(
            name,
            kind=KINDS[name],
            namespaced=name not in {"nodes", "persistentvolumes", "priorityclasses"},
        ),
    )


def manifest(res, name="one", *, uid=None, namespace="team", **fields):
    value = item(name, uid=uid, namespace=namespace if res.namespaced else None)
    value.update(apiVersion=res.api_version, kind=res.kind)
    value.update(fields)
    return value


def workload(res, name="one", **pod_spec):
    value = manifest(res, name)
    spec = {"containers": [{"name": "app", "image": "synthetic"}], **pod_spec}
    if res.name == "pods":
        value["spec"] = spec
    elif res.name == "cronjobs":
        value["spec"] = {"jobTemplate": {"spec": {"template": {"spec": spec}}}}
    else:
        value["spec"] = {"replicas": 0, "template": {"spec": spec}}
    return value


def owner(value, res, name="one", uid=None, **extra):
    value["metadata"]["ownerReferences"] = [
        {
            "apiVersion": res.api_version,
            "kind": res.kind,
            "name": name,
            "uid": uid or f"owned-{name}",
            "controller": True,
            **extra,
        }
    ]
    return value


def list_body(res, *values, token="", rv="opaque/snapshot"):
    return {
        **collection(*values, token=token, rv=rv),
        "apiVersion": res.api_version,
        "kind": res.kind + "List",
    }


def request_for(
    res, *, name="one", mode=RelationshipMode.XRAY, namespace="team", expanded=frozenset({()})
):
    target = ResourceTarget(
        SessionIdentity("synthetic", 1),
        res.group,
        res.name,
        namespace if res.namespaced else None,
        name,
        f"owned-{name}",
    )
    scope = RelationshipScope(target, res, namespace, mode)
    return RelationshipRequest(scope, 1, expanded)


@pytest.mark.asyncio
async def test_reader_budget_covers_pages_410_restart_and_get_without_extra_http(tmp_path):
    calls = []
    pods = resource()

    async def handler(request):
        calls.append(dict(request.query))
        if len(calls) == 2:
            return web.Response(status=410)
        return web.json_response(list_body(pods, manifest(pods), token="next"))

    async with reader_fixture(tmp_path, handler) as base:
        budget = ReadBudget(2)
        reader = ResourceReader(base.session, budget=budget)
        result = await reader.list(pods, "team")
        assert result.items[0].uid == "owned-one"
        assert result.collection.limited and not result.collection.complete
        assert result.resource_version == "opaque/snapshot"
        with pytest.raises(ReadBudgetExceeded):
            await reader.get(pods, "one", "team")
        again = await reader.list(pods, "team")
        assert again.items == () and again.collection.limited
        assert budget.used == len(calls) == 2


@pytest.mark.asyncio
async def test_reader_budget_charges_discovery_and_table_fallback(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        if "as=Table" in request.headers.get("Accept", ""):
            return web.Response(status=406)
        return web.json_response(manifest(resource()))

    async with reader_fixture(tmp_path, handler) as base:
        budget = ReadBudget(1)
        reader = ResourceReader(base.session, tables=True, budget=budget)
        with pytest.raises(ReadBudgetExceeded):
            await reader.get(resource(), "one", "team")
        assert len(calls) == budget.used == 1
        with pytest.raises(ExceptionGroup) as caught:
            await reader.discover()
        assert all(isinstance(error, ReadBudgetExceeded) for error in caught.value.exceptions)
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_discovered_owner_custom_gvk_fallback_uid_and_path_local_cycles(tmp_path):
    pods, widgets = resource(), resource("widgets", "example.test", "v2")
    body = owner(manifest(pods), widgets)
    body["metadata"]["ownerReferences"][0]["apiVersion"] = "example.test/v1"
    widget = owner(manifest(widgets), pods)
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("/pods/one"):
            return web.json_response(body)
        if request.path.endswith("/widgets/one"):
            return web.json_response(widget)
        return web.Response(status=404)

    req = request_for(pods)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((pods, widgets)), req.scope, lambda _: True)
        first = await service.collect(req, lambda _: None)
        widget_row = next(row for row in first.rows if row.ref.kind == "Widget")
        assert widget_row.status is RelationshipStatus.READY
        second = await service.collect(
            replace(req, revision=2, expanded=frozenset({(), widget_row.path})), lambda _: None
        )
        cycle = next(row for row in second.rows if row.status is RelationshipStatus.CYCLE)
        assert cycle.ref.uid == req.scope.root.uid
        assert calls.count("/api/v1/namespaces/team/pods/one") == 2
        assert calls.count("/apis/example.test/v2/namespaces/team/widgets/one") == 1
        collapsed = await service.collect(
            replace(req, revision=3, expanded=frozenset()), lambda _: None
        )
        assert len(collapsed.rows) == 1
        assert collapsed.requests_used == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,status",
    [
        (403, RelationshipStatus.FORBIDDEN),
        (404, RelationshipStatus.MISSING),
        ("replaced", RelationshipStatus.REPLACED),
        ("invalid", RelationshipStatus.INVALID),
        ("undiscovered", RelationshipStatus.UNAVAILABLE),
    ],
)
async def test_owner_failures_remain_explanatory_without_server_messages(tmp_path, mode, status):
    pods, widgets = resource(), resource("widgets", "example.test")
    value = owner(manifest(pods), widgets, namespace="other" if mode == "invalid" else "team")

    async def handler(request):
        if request.path.endswith("/pods/one"):
            return web.json_response(value)
        if isinstance(mode, int):
            return web.json_response({"message": "PRIVATE-secret-server-message"}, status=mode)
        return web.json_response(manifest(widgets, uid="replacement"))

    req = request_for(pods)
    async with reader_fixture(tmp_path, handler) as reader:
        graph = await RelationshipService(
            reader,
            Discovery((pods,) if mode == "undiscovered" else (pods, widgets)),
            req.scope,
            lambda _: True,
        ).collect(req, lambda _: None)
        row = next(row for row in graph.rows if row.ref.kind == "Widget")
        assert row.status is status
        assert "PRIVATE-secret-server-message" not in repr(asdict(graph))
        if mode == "replaced":
            assert row.ref.uid == "owned-one" and row.observed_uid == "replacement"


@pytest.mark.asyncio
async def test_deployment_owned_chain_and_native_expression_match_are_distinct(tmp_path):
    deploy, rs, pods = resource("deployments", "apps"), resource("replicasets", "apps"), resource()
    root = workload(deploy)
    root["spec"]["selector"] = {
        "matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["other"]}]
    }
    child = owner(workload(rs, "replica"), deploy)
    pod = owner(workload(pods, "pod"), rs, "replica")
    pod["metadata"]["labels"] = {"tier": "app"}
    calls = []

    async def handler(request):
        calls.append((request.path, dict(request.query)))
        if request.path.endswith("deployments/one"):
            return web.json_response(root)
        if request.path.endswith("/replicasets"):
            return web.json_response(list_body(rs, child))
        if request.path.endswith("/pods"):
            return web.json_response(list_body(pods, pod))
        return web.Response(status=404)

    req = request_for(deploy)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(
            reader, Discovery((deploy, rs, pods)), req.scope, lambda _: True
        )
        first = await service.collect(req, lambda _: None)
        owned = next(row for row in first.rows if row.ref.kind == "ReplicaSet")
        inferred = next(row for row in first.rows if row.relation is RelationKind.SELECTOR)
        assert inferred.ref.name == "pod" and inferred.direction is RelationDirection.INCOMING
        second = await service.collect(
            replace(req, revision=2, expanded=frozenset({(), owned.path})), lambda _: None
        )
        assert any(
            row.relation is RelationKind.CONTROLLER_OWNER and row.ref.name == "pod"
            for row in second.rows
        )
        assert any(query.get("labelSelector") == "tier notin (other)" for _, query in calls)


@pytest.mark.asyncio
async def test_usedby_scans_every_supported_family_and_zero_replica_template_without_values(
    tmp_path,
):
    resources = tuple(resource(name, group) for group, name in DECLARING_FAMILIES)
    target = resource("secrets")
    deployments = next(res for res in resources if res.name == "deployments")
    source = workload(deployments, "zero", imagePullSecrets=[{"name": "one"}])
    sources = {res.path("team" if res.namespaced else None): list_body(res) for res in resources}
    sources[deployments.path("team")] = list_body(deployments, source)
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("/secrets/one"):
            return web.json_response(manifest(target, data={"token": "PRIVATE-secret-data"}))
        return web.json_response(sources[request.path])

    req = request_for(target, mode=RelationshipMode.USED_BY)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(
            reader, Discovery((*resources, target)), req.scope, lambda _: True
        )
        result = await service.collect(req, lambda _: None)
        assert any(
            row.ref.name == "zero" and row.relation is RelationKind.REFERENCE for row in result.rows
        )
        assert {
            source.family for source in result.sources if not source.family.startswith("get:")
        } == {f"{group}/{name}" for group, name in DECLARING_FAMILIES}
        assert all(source.observed_at is not None for source in result.sources)
        assert "PRIVATE-secret-data" not in repr(asdict(result)) + repr(vars(service))
        assert "/api/v1/persistentvolumes" in calls


@pytest.mark.asyncio
async def test_usedby_denied_or_invalid_scan_never_claims_unused(tmp_path):
    target, pods = resource("configmaps"), resource()

    async def handler(request):
        if request.path.endswith("configmaps/one"):
            return web.json_response(manifest(target, data={"key": "PRIVATE-config-data"}))
        return web.json_response({"message": "PRIVATE-server-error"}, status=403)

    req = request_for(target, mode=RelationshipMode.USED_BY)
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery((target, pods)), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        assert "incomplete scans cannot establish unused" in result.rows[0].details[0]
        assert any(source.status is RelationshipStatus.FORBIDDEN for source in result.sources)
        assert "PRIVATE" not in repr(asdict(result))


@pytest.mark.asyncio
async def test_service_selectorless_slices_actual_uid_and_address_only(tmp_path):
    services, slices, pods = (
        resource("services"),
        resource("endpointslices", "discovery.k8s.io"),
        resource(),
    )
    service = manifest(services, spec={})
    slice_body = manifest(
        slices,
        "slice",
        endpoints=[
            {
                "addresses": ["192.0.2.1"],
                "conditions": {"ready": False, "serving": True},
                "targetRef": {"kind": "Pod", "name": "pod", "uid": "old-pod"},
            },
            {"addresses": ["192.0.2.2"]},
        ],
        ports=[{"name": "http", "port": 80}],
    )
    slice_body["metadata"]["labels"] = {"kubernetes.io/service-name": "one"}
    calls = []

    async def handler(request):
        calls.append((request.path, dict(request.query)))
        if request.path.endswith("services/one"):
            return web.json_response(service)
        if request.path.endswith("/endpointslices"):
            return web.json_response(list_body(slices, slice_body))
        if request.path.endswith("pods/pod"):
            return web.json_response(manifest(pods, "pod", uid="new-pod"))
        return web.Response(status=404)

    req = request_for(services)
    async with reader_fixture(tmp_path, handler) as reader:
        owner = RelationshipService(
            reader, Discovery((services, slices, pods)), req.scope, lambda _: True
        )
        first = await owner.collect(req, lambda _: None)
        child = next(row for row in first.rows if row.ref.kind == "EndpointSlice")
        second = await owner.collect(
            replace(req, revision=2, expanded=frozenset({(), child.path})), lambda _: None
        )
        replaced = next(row for row in second.rows if row.ref.kind == "Pod")
        assert replaced.status is RelationshipStatus.REPLACED
        assert replaced.ref.uid == "old-pod" and replaced.observed_uid == "new-pod"
        assert any(
            row.ref.kind == "EndpointAddress" and row.status is RelationshipStatus.UNAVAILABLE
            for row in second.rows
        )
        assert any(
            query.get("labelSelector") == "kubernetes.io/service-name=one" for _, query in calls
        )
        assert any("http:80" in detail for detail in replaced.details)


@pytest.mark.asyncio
async def test_legacy_endpoints_fallback_preserves_denied_slice_source(tmp_path):
    services, slices, endpoints = (
        resource("services"),
        resource("endpointslices", "discovery.k8s.io"),
        resource("endpoints"),
    )

    async def handler(request):
        if request.path.endswith("services/one"):
            return web.json_response(manifest(services, spec={}))
        if request.path.endswith("/endpointslices"):
            return web.Response(status=403)
        return web.json_response(list_body(endpoints, manifest(endpoints, subsets=[])))

    req = request_for(services)
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery((services, slices, endpoints)), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        assert any(
            source.status is RelationshipStatus.FORBIDDEN
            and source.family.endswith("endpointslices")
            for source in result.sources
        )
        assert any(row.ref.kind == "Endpoints" for row in result.rows)


@pytest.mark.asyncio
async def test_node_scan_uses_search_namespace_and_placement_not_constraints(tmp_path):
    nodes, pods = resource("nodes"), resource()
    placed = workload(pods, "placed", nodeName="one")
    pending = workload(pods, "pending", nodeSelector={"kubernetes.io/hostname": "one"})
    calls = []

    async def handler(request):
        calls.append((request.path, dict(request.query)))
        return web.json_response(
            manifest(nodes)
            if request.path.endswith("nodes/one")
            else list_body(pods, placed, pending)
        )

    req = request_for(nodes, namespace="search")
    placed["metadata"]["namespace"] = pending["metadata"]["namespace"] = "search"
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery((nodes, pods)), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        assert [row.ref.name for row in result.rows] == ["one", "placed"]
        assert calls[1] == (
            "/api/v1/namespaces/search/pods",
            {"limit": "100", "continue": "", "fieldSelector": "spec.nodeName=one"},
        )


@pytest.mark.asyncio
async def test_stale_pending_root_and_repeated_cancellation_drain_owned_parser(
    tmp_path, monkeypatch
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = relationships.declared_references

    def extract(*args):
        started.set()
        release.wait(5)
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(relationships, "declared_references", extract)

    async def handler(request):
        return web.json_response(manifest(resource()))

    req = request_for(resource())
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((resource(),)), req.scope, lambda _: True)
        emitted = []
        task = asyncio.create_task(service.collect(req, emitted.append))
        try:
            async with asyncio.timeout(5):
                while not started.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set()
            assert all(
                snapshot.rows[0].status is RelationshipStatus.LOADING for snapshot in emitted
            )
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_changed_guard_rejects_held_http_result_before_any_publication(tmp_path):
    held, release = asyncio.Event(), asyncio.Event()
    current = [True]

    async def handler(request):
        held.set()
        await release.wait()
        return web.json_response(manifest(resource()))

    req = request_for(resource())
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(
            reader, Discovery((resource(),)), req.scope, lambda _: current[0]
        )
        emitted = []
        task = asyncio.create_task(service.collect(req, emitted.append))
        try:
            await asyncio.wait_for(held.wait(), 5)
            current[0] = False
            before = len(emitted)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(emitted) == before
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_shared_64_call_budget_stops_all_http_and_new_service_refreshes_it(tmp_path):
    widgets = resource("widgets", "example.test")
    root = manifest(widgets)
    root["metadata"]["ownerReferences"] = [
        {
            "apiVersion": widgets.api_version,
            "kind": widgets.kind,
            "name": f"owner-{i}",
            "uid": f"owned-owner-{i}",
            "controller": False,
        }
        for i in range(70)
    ]
    calls = []

    async def handler(request):
        calls.append(request.path)
        name = request.path.rsplit("/", 1)[-1]
        return web.json_response(root if name == "one" else manifest(widgets, name))

    req = request_for(widgets)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((widgets,)), req.scope, lambda _: True)
        result = await service.collect(req, lambda _: None)
        assert result.requests_used == len(calls) == 64
        assert any(row.status is RelationshipStatus.TRUNCATED for row in result.rows)
        again = await service.collect(replace(req, revision=2), lambda _: None)
        assert again.rows[0].status is RelationshipStatus.TRUNCATED
        assert len(calls) == 64
        refreshed = RelationshipService(reader, Discovery((widgets,)), req.scope, lambda _: True)
        await refreshed.collect(replace(req, expanded=frozenset()), lambda _: None)
        assert refreshed.budget.used == 1 and len(calls) == 65


@pytest.mark.asyncio
async def test_diamond_cache_reuse_is_not_a_cycle(tmp_path):
    widgets = resource("widgets", "example.test")
    root = manifest(widgets)
    root["metadata"]["ownerReferences"] = [
        {
            "apiVersion": widgets.api_version,
            "kind": widgets.kind,
            "name": name,
            "uid": "owned-" + name,
        }
        for name in ("left", "right")
    ]
    values = {name: owner(manifest(widgets, name), widgets, "shared") for name in ("left", "right")}
    values.update(one=root, shared=manifest(widgets, "shared"))
    calls = []

    async def handler(request):
        name = request.path.rsplit("/", 1)[-1]
        calls.append(name)
        return web.json_response(values[name])

    req = request_for(widgets)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((widgets,)), req.scope, lambda _: True)
        first = await service.collect(req, lambda _: None)
        second = await service.collect(
            replace(req, revision=2, expanded=frozenset(row.path for row in first.rows)),
            lambda _: None,
        )
        shared = [row for row in second.rows if row.ref.name == "shared"]
        assert len(shared) == 2 and shared[0].path != shared[1].path
        assert all(row.status is RelationshipStatus.READY for row in shared)
        assert calls.count("shared") == 1


@pytest.mark.asyncio
async def test_eight_level_expansion_ceiling_retains_visible_truncated_branch(tmp_path):
    widgets = resource("widgets", "example.test")

    async def handler(request):
        name = request.path.rsplit("/", 1)[-1]
        index = 0 if name == "one" else int(name.split("-")[1])
        return web.json_response(owner(manifest(widgets, name), widgets, f"level-{index + 1}"))

    req = request_for(widgets)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((widgets,)), req.scope, lambda _: True)
        for index in range(10):
            result = await service.collect(req, lambda _: None)
            req = replace(
                req, revision=index + 2, expanded=frozenset(row.path for row in result.rows)
            )
        assert max(len(row.path) for row in result.rows) == 8
        assert result.rows[-1].status is RelationshipStatus.TRUNCATED
        assert "depth limit" in result.rows[-1].details[-1]


@pytest.mark.asyncio
async def test_node_512_row_ceiling_preserves_partial_membership(tmp_path):
    nodes, pods = resource("nodes"), resource()

    async def handler(request):
        if request.path.endswith("nodes/one"):
            return web.json_response(manifest(nodes))
        return web.json_response(
            list_body(pods, *(workload(pods, f"pod-{i}", nodeName="one") for i in range(520)))
        )

    req = request_for(nodes)
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery((nodes, pods)), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        assert len(result.rows) == 512
        assert result.rows[0].status is RelationshipStatus.TRUNCATED
        assert "node or edge limit" in result.rows[0].details[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expressions",
    [
        [{"key": "present", "operator": "Exists"}, {"key": "absent", "operator": "DoesNotExist"}],
        [{"key": f"label-{index}", "operator": "Exists"} for index in range(9)],
        [],
    ],
)
async def test_native_selector_narrowing_and_bounded_scan_fallback(tmp_path, expressions):
    deploy, pods = resource("deployments", "apps"), resource()
    root = workload(deploy)
    root["spec"]["selector"] = {"matchExpressions": expressions}
    pod = workload(pods, "matched")
    pod["metadata"]["labels"] = {
        expression["key"]: "yes" for expression in expressions if expression["operator"] == "Exists"
    }
    queries = []

    async def handler(request):
        queries.append(dict(request.query))
        if request.path.endswith("deployments/one"):
            return web.json_response(root)
        if request.path.endswith("/pods"):
            return web.json_response(list_body(pods, pod))
        return web.Response(status=404)

    req = request_for(deploy)
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery((deploy, pods)), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        assert any(row.relation is RelationKind.SELECTOR for row in result.rows)
        query = next(query for query in queries if "limit" in query)
        if len(expressions) == 2:
            assert query["labelSelector"] == "present,!absent"
        else:
            assert "labelSelector" not in query


@pytest.mark.asyncio
async def test_pod_to_node_get_and_explicit_endpoint_namespace_are_preserved(tmp_path):
    pods, nodes, slices = (
        resource(),
        resource("nodes"),
        resource("endpointslices", "discovery.k8s.io"),
    )
    body = manifest(
        slices,
        endpoints=[
            {
                "targetRef": {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "namespace": "other",
                    "name": "placed",
                    "uid": "owned-placed",
                }
            }
        ],
    )
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("endpointslices/one"):
            return web.json_response(body)
        if request.path.endswith("pods/placed"):
            return web.json_response(
                manifest(
                    pods,
                    "placed",
                    namespace="other",
                    spec={"containers": [{"name": "app"}], "nodeName": "one"},
                )
            )
        if request.path.endswith("nodes/one"):
            return web.json_response(manifest(nodes))
        return web.Response(status=404)

    req = request_for(slices)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(
            reader, Discovery((pods, nodes, slices)), req.scope, lambda _: True
        )
        first = await service.collect(req, lambda _: None)
        child = next(row for row in first.rows if row.ref.kind == "Pod")
        assert child.status is RelationshipStatus.READY and child.ref.namespace == "other"
        second = await service.collect(
            replace(req, revision=2, expanded=frozenset({(), child.path})), lambda _: None
        )
        assert any(
            row.relation is RelationKind.NODE and row.status is RelationshipStatus.READY
            for row in second.rows
        )
        assert "/api/v1/namespaces/other/pods/placed" in calls
        assert "/api/v1/nodes/one" in calls


@pytest.mark.asyncio
async def test_usedby_complete_absence_and_pv_expected_uid_replacement(tmp_path):
    resources = tuple(resource(name, group) for group, name in DECLARING_FAMILIES)
    pvc = next(res for res in resources if res.name == "persistentvolumeclaims")
    pv = next(res for res in resources if res.name == "persistentvolumes")
    declared = [False]
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("persistentvolumeclaims/one"):
            return web.json_response(manifest(pvc, spec={}))
        res = next(
            res for res in resources if request.path == res.path("team" if res.namespaced else None)
        )
        values = (
            [
                manifest(
                    pv,
                    "volume",
                    spec={"claimRef": {"name": "one", "namespace": "team", "uid": "old-pvc"}},
                )
            ]
            if res == pv and declared[0]
            else []
        )
        return web.json_response(list_body(res, *values))

    req = request_for(pvc, mode=RelationshipMode.USED_BY)
    req = replace(req, scope=replace(req.scope, namespace="search"))
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery(resources), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        assert "completely scanned scope" in result.rows[0].details[0]
        declared[0] = True
        result = await RelationshipService(
            reader, Discovery(resources), req.scope, lambda _: True
        ).collect(req, lambda _: None)
        row = next(row for row in result.rows if row.ref.kind == "PersistentVolume")
        assert row.status is RelationshipStatus.REPLACED
        assert not any("/namespaces/search/" in path for path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["invalid", "arbitrary-missing-gvk", "budget", "deadline", "compare"]
)
async def test_invalid_and_exhausted_collection_paths_are_visible(tmp_path, monkeypatch, mode):
    pods, slices, secret = (
        resource(),
        resource("endpointslices", "discovery.k8s.io"),
        resource("secrets"),
    )
    selected = slices if mode == "arbitrary-missing-gvk" else secret if mode == "compare" else pods
    if mode == "budget":
        monkeypatch.setattr(relationships, "MAX_RELATIONSHIP_BYTES", 1)
    if mode == "deadline":
        monkeypatch.setattr(relationships, "MAX_COLLECTION_SECONDS", 0.01)
    if mode == "compare":
        monkeypatch.setattr(relationships, "MAX_COMPARISONS", 0)
    held = asyncio.Event()

    async def handler(request):
        if mode == "deadline":
            await held.wait()
        if request.path.endswith("/secrets/one"):
            return web.json_response(manifest(secret))
        if request.path.endswith("/pods"):
            return web.json_response(
                list_body(pods, workload(pods, imagePullSecrets=[{"name": "one"}]))
            )
        value = manifest(selected)
        if mode == "invalid":
            value["spec"]["containers"] = "invalid"
        if mode == "arbitrary-missing-gvk":
            value["endpoints"] = [{"targetRef": {"kind": "Widget", "name": "one"}}]
        return web.json_response(value)

    req = request_for(
        selected, mode=RelationshipMode.USED_BY if mode == "compare" else RelationshipMode.XRAY
    )
    async with reader_fixture(tmp_path, handler) as reader:
        try:
            result = await RelationshipService(
                reader, Discovery((pods, slices, secret)), req.scope, lambda _: True
            ).collect(req, lambda _: None)
            expected = (
                RelationshipStatus.FAILED
                if mode in {"invalid", "arbitrary-missing-gvk"}
                else RelationshipStatus.TRUNCATED
            )
            assert result.rows[0].status is expected
        finally:
            held.set()


@pytest.mark.asyncio
async def test_scope_validation_and_overlapping_collector_rejected(tmp_path):
    held, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        held.set()
        await release.wait()
        return web.json_response(manifest(resource()))

    req = request_for(resource())
    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(Exception, match="discovered resource"):
            RelationshipService(
                reader,
                Discovery(()),
                replace(req.scope, resource=resource("nodes")),
                lambda _: True,
            )
        with pytest.raises(Exception, match="namespace scope"):
            RelationshipService(
                reader,
                Discovery(()),
                replace(req.scope, root=replace(req.scope.root, namespace=None)),
                lambda _: True,
            )
        service = RelationshipService(reader, Discovery((resource(),)), req.scope, lambda _: True)
        task = asyncio.create_task(service.collect(req, lambda _: None))
        try:
            await asyncio.wait_for(held.wait(), 5)
            with pytest.raises(Exception, match="already owned"):
                await service.collect(req, lambda _: None)
        finally:
            release.set()
            await task


@pytest.mark.asyncio
async def test_partial_usedby_page_keeps_observation_time_and_rows_after_later_denial(tmp_path):
    secret, pods = resource("secrets"), resource()
    held, release = asyncio.Event(), asyncio.Event()
    publications = []

    async def handler(request):
        if request.path.endswith("/secrets/one"):
            return web.json_response(manifest(secret))
        if request.query.get("continue"):
            held.set()
            await release.wait()
            return web.Response(status=403)
        return web.json_response(
            list_body(
                pods, workload(pods, "declarer", imagePullSecrets=[{"name": "one"}]), token="held"
            )
        )

    req = request_for(secret, mode=RelationshipMode.USED_BY)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((secret, pods)), req.scope, lambda _: True)
        task = asyncio.create_task(service.collect(req, publications.append))
        try:
            await asyncio.wait_for(held.wait(), 5)
            before = next(source for source in publications[-1].sources if source.family == "/pods")
            assert before.collection.pages == 1 and before.observed_at is not None
            release.set()
            result = await task
            after = next(source for source in result.sources if source.family == "/pods")
            assert after.status is RelationshipStatus.FORBIDDEN
            assert after.observed_at == before.observed_at
            assert after.resource_version == before.resource_version == "opaque/snapshot"
            assert any(row.ref.name == "declarer" for row in result.rows)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_budget_limited_page_keeps_actual_observation_time_without_a_new_read(tmp_path):
    secret, pods = resource("secrets"), resource()
    calls = []
    publications = []

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("/secrets/one"):
            return web.json_response(manifest(secret))
        return web.json_response(
            list_body(
                pods, workload(pods, "declarer", imagePullSecrets=[{"name": "one"}]), token="more"
            )
        )

    req = request_for(secret, mode=RelationshipMode.USED_BY)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((secret, pods)), req.scope, lambda _: True)
        # The public shared budget is consumed by another owned read before collection.
        for _ in range(62):
            service.budget.charge()
        result = await service.collect(req, publications.append)
        observed = [
            source
            for snapshot in publications
            for source in snapshot.sources
            if source.family == "/pods" and source.observed_at is not None
        ]
        assert observed and {source.observed_at for source in observed} == {observed[0].observed_at}
        final = next(source for source in result.sources if source.family == "/pods")
        assert (
            final.status is RelationshipStatus.TRUNCATED
            and "logical read budget exhausted" in final.detail
        )
        assert len(calls) == 2 and result.requests_used == 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "last_label_length", [50, 61], ids=["selector-256-boundary", "dns-name-253-maximum"]
)
async def test_node_placement_selector_boundary_and_maximum_dns_name_keep_exact_membership(
    tmp_path, last_label_length
):
    nodes, pods = resource("nodes"), resource()
    node_name = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * last_label_length))
    other_node = node_name[:-1] + "e"
    assert len(node_name) == (242 if last_label_length == 50 else 253)
    placed = workload(pods, "placed", nodeName=node_name)
    neighbor = workload(pods, "neighbor", nodeName=other_node)
    constrained = workload(
        pods, "constrained", nodeSelector={"relationships.example.test/pool": "workers"}
    )
    for value in (placed, neighbor, constrained):
        value["metadata"]["namespace"] = "search"
    calls = []

    async def handler(request):
        calls.append((request.path, dict(request.query)))
        if request.path == nodes.path() + "/" + node_name:
            return web.json_response(
                manifest(
                    nodes,
                    node_name,
                    uid="node-uid",
                    spec={},
                    metadata={
                        "name": node_name,
                        "uid": "node-uid",
                        "resourceVersion": "1",
                        "labels": {"relationships.example.test/pool": "workers"},
                    },
                )
            )
        assert request.path == pods.path("search")
        # Return both assignments even for a narrowed request: the exact local
        # placement check must remain authoritative in both collection paths.
        return web.json_response(list_body(pods, placed, neighbor, constrained))

    req = request_for(nodes, name=node_name, namespace="search")
    req = replace(req, scope=replace(req.scope, root=replace(req.scope.root, uid="node-uid")))
    async with reader_fixture(tmp_path, handler) as reader:
        result = await RelationshipService(
            reader, Discovery((nodes, pods)), req.scope, lambda _: True
        ).collect(req, lambda _: None)
    assert result.rows[0].status is RelationshipStatus.READY
    assert [(row.ref.name, row.relation) for row in result.rows] == [
        (node_name, None),
        ("placed", RelationKind.NODE),
    ]
    assert result.rows[1].observed_uid == "owned-placed"
    assert result.requests_used == len(calls) == 2
    path, query = calls[1]
    assert path == "/api/v1/namespaces/search/pods"
    if last_label_length == 50:
        assert query["fieldSelector"] == "spec.nodeName=" + node_name
        assert len(query["fieldSelector"]) == 256
    else:
        assert "fieldSelector" not in query
    source = next(source for source in result.sources if source.family == "/pods")
    assert source.status is RelationshipStatus.READY
    assert source.collection.complete and not source.collection.limited


@pytest.mark.asyncio
async def test_node_to_pod_name_only_placement_detects_first_observed_node_repeat(tmp_path):
    nodes, pods = resource("nodes"), resource()
    placed = workload(pods, "placed", nodeName="one")
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path == nodes.path() + "/one":
            return web.json_response(manifest(nodes, spec={}))
        assert request.path == pods.path("team")
        return web.json_response(list_body(pods, placed))

    req = request_for(nodes)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(reader, Discovery((nodes, pods)), req.scope, lambda _: True)
        first = await service.collect(req, lambda _: None)
        pod_row = next(row for row in first.rows if row.ref.kind == "Pod")
        result = await service.collect(
            replace(req, revision=2, expanded=frozenset({(), pod_row.path})), lambda _: None
        )
    repeated = next(row for row in result.rows if row.path and row.ref.kind == "Node")
    assert repeated.path[:-1] == pod_row.path and len(repeated.path) == 2
    assert repeated.status is RelationshipStatus.CYCLE
    assert repeated.ref.uid is None  # spec.nodeName declares a name, not a Node UID.
    assert repeated.observed_uid == req.scope.root.uid
    assert not repeated.expandable
    assert not any(row.status is RelationshipStatus.TRUNCATED for row in result.rows)
    assert calls == [nodes.path() + "/one", pods.path("team"), nodes.path() + "/one"]
    assert result.requests_used == len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_uid", [None, "earlier-claim-uid"], ids=["name-only-cycle", "replaced-before-cycle"]
)
async def test_name_only_pvc_pv_descendants_use_observed_ancestor_uid_and_keep_status_precedence(
    tmp_path, claim_uid
):
    pods, claims, volumes = (
        resource(),
        resource("persistentvolumeclaims"),
        resource("persistentvolumes"),
    )
    pod = workload(pods, volumes=[{"persistentVolumeClaim": {"claimName": "claim"}}])
    claim = manifest(claims, "claim", uid="current-claim-uid", spec={"volumeName": "volume"})
    claim_reference = {"name": "claim", "namespace": "team"}
    if claim_uid is not None:
        claim_reference["uid"] = claim_uid
    volume = manifest(
        volumes, "volume", uid="current-volume-uid", spec={"claimRef": claim_reference}
    )
    objects = {
        pods.path("team") + "/one": pod,
        claims.path("team") + "/claim": claim,
        volumes.path() + "/volume": volume,
    }
    calls = []

    async def handler(request):
        calls.append(request.path)
        assert request.path in objects
        return web.json_response(objects[request.path])

    req = request_for(pods)
    async with reader_fixture(tmp_path, handler) as reader:
        service = RelationshipService(
            reader, Discovery((pods, claims, volumes)), req.scope, lambda _: True
        )
        first = await service.collect(req, lambda _: None)
        claim_row = next(row for row in first.rows if row.ref.kind == "PersistentVolumeClaim")
        assert claim_row.ref.uid is None and claim_row.observed_uid == "current-claim-uid"
        second = await service.collect(
            replace(req, revision=2, expanded=frozenset({(), claim_row.path})), lambda _: None
        )
        volume_row = next(row for row in second.rows if row.ref.kind == "PersistentVolume")
        assert volume_row.ref.uid is None and volume_row.observed_uid == "current-volume-uid"
        result = await service.collect(
            replace(req, revision=3, expanded=frozenset({(), claim_row.path, volume_row.path})),
            lambda _: None,
        )
    repeated = next(
        row for row in result.rows if len(row.path) == 3 and row.ref.kind == "PersistentVolumeClaim"
    )
    assert repeated.path[:-1] == volume_row.path
    assert repeated.status is (
        RelationshipStatus.CYCLE if claim_uid is None else RelationshipStatus.REPLACED
    )
    assert repeated.ref.uid == claim_uid
    assert repeated.observed_uid == "current-claim-uid"
    assert not repeated.expandable
    assert not any(row.status is RelationshipStatus.TRUNCATED for row in result.rows)
    assert calls.count(claims.path("team") + "/claim") == 1
    assert calls.count(volumes.path() + "/volume") == 1
    assert result.requests_used == len(calls) == 5
