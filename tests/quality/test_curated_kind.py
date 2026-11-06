"""Verifier declarations, ownership refusals and receipts; no real cluster is operated."""

import asyncio
import copy
import ipaddress
import json
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ResponseLimitExceeded
from kuberich.domain.curated import curated_cells, curated_families
from kuberich.domain.events import EventOptions, EventSourceState, event_fact, group_events
from kuberich.domain.relationships import structured_selector
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    Discovery,
    ResourceRecord,
    resource_record,
)
from kuberich.domain.tables import TableDecoder
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewObservation, ViewStatus
from kuberich.errors import AppError
from scripts import curated_kind as fixtures
from scripts import verify_curated_resources_kind as runner
from scripts.curated_kind import (
    CASES,
    RAW_REPRESENTATION_BYTES,
    READ_SECONDS,
    VERIFY_SECONDS,
    check_native_projection,
    create_document,
    endpoint_manifests,
    event_manifests,
    events_ready,
    evidence_json,
    fixture_manifests,
    inspection_closed,
    inspection_lifecycle,
    observed,
    open_details,
    persist,
    require_owned,
    required_uid,
    until,
    verify_curated_resources,
    vpa_crd,
    wait_for_crd_established,
    wait_for_inspection_closed,
    write,
)
from scripts.owned_kind import SHELL_IMAGE, OwnedCluster
from tests.support.connections import catalog_fixture
from tests.support.curated_resources import curated_resources_api
from tests.ui.test_curated_resources import app_for, loaded, started

NAMESPACE = "kuberich-curated-contract"
OTHER = "kuberich-curated-empty"
AT = datetime(2026, 11, 6, 12, tzinfo=UTC)


def descriptor(family):
    return ApiResource(
        family.group,
        "v2" if family.resource == "horizontalpodautoscalers" else "v1",
        family.resource,
        family.kind,
        family.namespaced,
        frozenset({"get", "list", "watch"}),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.resource)
def test_planned_native_families_have_two_real_declarations_and_distinct_typed_expectations(case):
    family = next(item for item in curated_families() if item.resource == case.resource)
    resource = descriptor(family)
    manifests = (
        endpoint_manifests(NAMESPACE, "actual-owned-pod-uid")
        if resource.name == "endpointslices"
        else fixture_manifests(NAMESPACE, OTHER)
    )
    selected = [body for body in manifests if body["kind"] == resource.kind]
    assert len(selected) == 2
    values = []
    for index, body in enumerate(selected):
        assert body["apiVersion"] == resource.api_version
        assert ("namespace" in body["metadata"]) == resource.namespaced
        assert "uid" not in body["metadata"] and "status" not in body
        normalized = copy.deepcopy(body)
        normalized["metadata"].update(uid="test-api-uid-" + str(index), resourceVersion="1")
        record = resource_record(resource, normalized)
        cell = dict(curated_cells(resource, record).values)[case.field]
        values.append(cell)
    assert tuple(value.text for value in values) == (case.first, case.second)
    assert all(value.sort is not None for value in values)
    assert tuple(sorted(range(2), key=lambda index: values[index].sort)) == case.ascending


def test_hpa_and_pod_manifests_respect_real_validation_without_executing_workloads():
    values = fixture_manifests(NAMESPACE, OTHER)
    hpas = [item for item in values if item["kind"] == "HorizontalPodAutoscaler"]
    assert all(item["spec"]["minReplicas"] == 1 for item in hpas)
    assert [
        item["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] for item in hpas
    ] == [70, 90]
    pods = [item for item in values if item["kind"] == "Pod"]
    assert all(
        item["spec"]["nodeSelector"] == {"curated.kind/absent-node": "true"} for item in pods
    )
    assert all(item["spec"]["automountServiceAccountToken"] is False for item in pods)
    assert {item["spec"]["containers"][0]["image"] for item in pods} == {SHELL_IMAGE}
    assert all(item["spec"]["replicas"] == 0 for item in values if item["kind"] == "Deployment")


def test_webhooks_cannot_intercept_created_namespace_or_served_test_resources():
    values = fixture_manifests(NAMESPACE, OTHER)
    namespaces = [item for item in values if item["kind"] == "Namespace"]
    hooks = [hook for item in values for hook in item.get("webhooks", [])]
    assert len(hooks) == 6
    for hook in hooks:
        assert hook["failurePolicy"] == "Ignore" and hook["sideEffects"] == "None"
        assert hook["namespaceSelector"] == {"matchLabels": {"curated.kind/never-admit": "true"}}
        assert not any(
            item["metadata"]["labels"].get("curated.kind/never-admit") == "true"
            for item in namespaces
        )
        assert hook["rules"] == [
            {
                "operations": ["CREATE"],
                "apiGroups": ["unserved.curated.kind"],
                "apiVersions": ["v1"],
                "resources": ["widgets"],
                "scope": "Namespaced",
            }
        ]
        client = hook["clientConfig"]
        assert ("service" in client) != ("url" in client)


def test_minimal_vpa_crd_is_structural_status_separate_and_never_a_controller():
    body = vpa_crd()
    assert body["apiVersion"] == "apiextensions.k8s.io/v1"
    assert body["spec"]["scope"] == "Namespaced"
    (version,) = body["spec"]["versions"]
    assert version["name"] == "v1" and version["served"] and version["storage"]
    schema = version["schema"]["openAPIV3Schema"]
    assert schema["type"] == "object" and set(schema["properties"]) == {"spec", "status"}
    assert all(
        value == {"type": "object", "x-kubernetes-preserve-unknown-fields": True}
        for value in schema["properties"].values()
    )
    assert version["subresources"] == {"status": {}}
    assert "image" not in json.dumps(body)


def test_minimal_vpa_crd_declares_unapproved_experimental_fixture_without_claiming_api_approval():
    body = vpa_crd()
    assert body["spec"]["group"] == "autoscaling.k8s.io"
    # Declaration/provenance control only. Actual missing-annotation admission
    # failed422 in retained kind001; this assertion does not simulate admission.
    assert body["metadata"].get("annotations", {}) == {
        "api-approved.kubernetes.io": "unapproved, experimental-only"
    }


@pytest.mark.parametrize(
    "first,second", [("bad/name", OTHER), (NAMESPACE, "bad/name"), (NAMESPACE, NAMESPACE)]
)
def test_fixture_namespace_controls_are_validated_and_distinct(first, second):
    with pytest.raises((AppError, ValueError)):
        fixture_manifests(first, second)


def test_fixture_documents_do_not_alias_one_another_or_later_preparations():
    values = fixture_manifests(NAMESPACE, OTHER)
    role = next(item for item in values if item["kind"] == "Role")
    cluster = next(item for item in values if item["kind"] == "ClusterRole")
    role["rules"][0]["verbs"].append("delete")
    assert "delete" not in cluster["rules"][0]["verbs"]
    assert "delete" not in json.dumps(fixture_manifests(NAMESPACE, OTHER))


def label_maps(value, path="root"):
    if isinstance(value, dict):
        for key, item in value.items():
            location = path + "." + key
            if key in {"labels", "matchLabels", "nodeSelector"} or (
                key == "selector"
                and isinstance(item, dict)
                and not set(item) & {"matchLabels", "matchExpressions"}
            ):
                yield location, item
            yield from label_maps(item, location)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from label_maps(item, path + f"[{index}]")


def test_every_static_and_dynamic_manifest_label_and_match_label_is_a_valid_literal():
    documents = (
        vpa_crd(),
        *fixture_manifests(NAMESPACE, OTHER),
        *endpoint_manifests(NAMESPACE, "actual-owned-pod-uid"),
        *event_manifests(NAMESPACE, "actual-owned-pod-uid", AT),
    )
    declarations = tuple(label_maps(documents))
    assert len(declarations) > len(documents)
    for path, labels in declarations:
        try:
            selector = structured_selector(labels, direct=True)
        except AppError as error:
            raise AssertionError("Invalid fixture label declaration at " + path) from error
        assert {item.key: item.values[0] for item in selector.requirements} == labels


def test_dynamic_slice_and_event_admission_declarations_preserve_their_distinct_name_rules():
    slices = endpoint_manifests(NAMESPACE, "actual-owned-pod-uid")
    for body in slices:
        assert (
            body["metadata"]["labels"]["endpointslice.kubernetes.io/managed-by"]
            == "curated.kind.fixture"
        )
        assert body["addressType"] == "IPv4" and len(body["endpoints"]) <= 1000
        for endpoint in body["endpoints"]:
            assert 1 <= len(endpoint["addresses"]) <= 100
            assert all(ipaddress.ip_address(value).version == 4 for value in endpoint["addresses"])
            assert all(type(value) is bool for value in endpoint.get("conditions", {}).values())
        for port in body["ports"]:
            assert port["protocol"] in {"TCP", "UDP", "SCTP"}
            assert 1 <= port["port"] <= 65535
    for body in event_manifests(NAMESPACE, "actual-owned-pod-uid", AT):
        assert body["reportingController"] == "curated.kind/fixture"
        # A qualified reporter name is distinct from an object label value.
        structured_selector({body["reportingController"]: "reporter"}, direct=True)
        assert 1 <= len(body["reportingInstance"]) <= 128
        assert 1 <= len(body["action"]) <= 128 and 1 <= len(body["reason"]) <= 128
        assert len(body["note"]) <= 1024 and body["type"] in {"Normal", "Warning"}
        assert datetime.fromisoformat(body["eventTime"].replace("Z", "+00:00")).tzinfo is not None
        assert not set(body) & {
            "deprecatedCount",
            "deprecatedFirstTimestamp",
            "deprecatedLastTimestamp",
            "deprecatedSource",
        }
        if "series" in body:
            assert type(body["series"]["count"]) is int and body["series"]["count"] >= 2
            assert body["series"]["lastObservedTime"] == body["eventTime"]


def test_actual_uid_placeholder_contract_preserves_tri_state_and_separate_event_members():
    slices = endpoint_manifests(NAMESPACE, "actual-created-pod-uid")
    assert slices[0]["endpoints"][0]["targetRef"]["uid"] == "actual-created-pod-uid"
    assert slices[0]["endpoints"][2].get("conditions") is None
    assert slices[1]["endpoints"] == []
    resource = ApiResource("events.k8s.io", "v1", "events", "Event", True, frozenset({"list"}))
    documents = event_manifests(NAMESPACE, "actual-created-pod-uid", AT)
    records = []
    for index, body in enumerate(documents):
        assert body["eventTime"] == "2026-11-06T12:00:00.000000Z"
        assert body["reportingController"] and body["reportingInstance"] and body["action"]
        body["metadata"].update(uid="test-event-" + str(index), resourceVersion="1")
        records.append(resource_record(resource, body))
    facts = tuple(event_fact(resource, record) for record in records)
    groups = group_events(facts, EventOptions(grouped=True, warnings_only=True))
    assert len(groups) == 1 and groups[0].known_occurrences == 5
    assert groups[0].member_uids == ("test-event-0", "test-event-1")
    assert all(fact.regarding.uid == "actual-created-pod-uid" for fact in facts)


def owned(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir()
    path = directory / "owned-kubeconfig"
    path.write_text("private-controlled-test-data")
    path.chmod(0o600)
    cluster = OwnedCluster(
        "kuberich-test-contract", path, directory, "kind-kuberich-test-contract", ("owned-node-id",)
    )
    session = SimpleNamespace(context=SimpleNamespace(name=cluster.context), api=object())
    return cluster, SimpleNamespace(session=session), SimpleNamespace(names=(cluster.context,))


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "name",
        "context",
        "nodes",
        "empty-node",
        "relative-directory",
        "relative-path",
        "foreign-parent",
        "mode",
        "catalog",
        "session-context",
        "closed",
    ],
)
def test_prewrite_guard_refuses_unowned_cluster_catalog_or_session(tmp_path, fault):
    cluster, reader, catalog = owned(tmp_path)
    if fault == "name":
        cluster = replace(cluster, name="customer")
    elif fault == "context":
        cluster = replace(cluster, context="customer")
    elif fault == "nodes":
        cluster = replace(cluster, node_ids=("a", "b"))
    elif fault == "empty-node":
        cluster = replace(cluster, node_ids=("",))
    elif fault == "relative-directory":
        cluster = replace(cluster, directory=Path("private"))
    elif fault == "relative-path":
        cluster = replace(cluster, path=Path("owned-kubeconfig"))
    elif fault == "foreign-parent":
        cluster = replace(cluster, directory=tmp_path)
    elif fault == "mode":
        cluster.path.chmod(0o644)
    elif fault == "catalog":
        catalog.names = (cluster.context, "customer")
    elif fault == "session-context":
        reader.session.context.name = "customer"
    elif fault == "closed":
        reader.session.api = None
    if fault is None:
        require_owned(cluster, reader, catalog)
    else:
        with pytest.raises(ValueError, match="verified owned"):
            require_owned(cluster, reader, catalog)


@pytest.mark.asyncio
async def test_failed_prewrite_guard_performs_no_discovery_or_write(tmp_path):
    cluster, reader, catalog = owned(tmp_path)
    reader.discover = AsyncMock()
    with pytest.raises(ValueError):
        await verify_curated_resources(
            reader,
            catalog,
            replace(cluster, context="customer"),
            evidence_dir=tmp_path / "evidence",
        )
    reader.discover.assert_not_called()
    assert not (tmp_path / "evidence").exists()


@asynccontextmanager
async def writer_api(tmp_path):
    calls = []

    async def handle(request):
        calls.append(
            (request.method, request.path, request.headers["Content-Type"], await request.json())
        )
        return web.json_response(
            {"kind": "Status", "status": "Success"}, status=201 if request.method == "POST" else 200
        )

    application = web.Application()
    application.router.add_route("*", "/{path:.*}", handle)
    server = web.AppRunner(application)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    address = server.addresses[0]
    session = KubernetesSession(
        catalog_fixture(tmp_path, f"http://127.0.0.1:{address[1]}").select("kuberich-test-one"), 5
    )
    try:
        await session.open()
        yield session, calls
    finally:
        await session.close()
        await server.cleanup()


@pytest.mark.asyncio
async def test_write_uses_real_owned_sdk_http_method_endpoint_and_merge_patch_type(tmp_path):
    async with writer_api(tmp_path) as (session, calls):
        assert await write(session, "/owned/a", "POST", {"value": 1}) == {
            "kind": "Status",
            "status": "Success",
        }
        await write(session, "/owned/a", "PATCH", {"value": 2})
        await write(session, "/owned/a", "DELETE", {"preconditions": {"uid": "actual-owned"}})
    assert calls == [
        ("POST", "/owned/a", "application/json", {"value": 1}),
        ("PATCH", "/owned/a", "application/merge-patch+json", {"value": 2}),
        ("DELETE", "/owned/a", "application/json", {"preconditions": {"uid": "actual-owned"}}),
    ]
    assert session.api is None


@pytest.mark.asyncio
async def test_write_refuses_closed_session_before_sdk_io():
    with pytest.raises(AppError, match="not open"):
        await write(SimpleNamespace(api=None), "/owned", "POST", {})


@asynccontextmanager
async def crd_api(tmp_path, states, *, requests=None):
    calls, received = [], asyncio.Event()

    async def handle(request):
        assert request.method == "GET"
        calls.append(request.path)
        if requests is not None:
            requests.append((request.path, dict(request.query), request.headers.get("Accept", "")))
        received.set()
        return web.json_response(states[min(len(calls) - 1, len(states) - 1)])

    application = web.Application()
    application.router.add_get("/{path:.*}", handle)
    server = web.AppRunner(application)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    address = server.addresses[0]
    session = KubernetesSession(
        catalog_fixture(tmp_path, f"http://127.0.0.1:{address[1]}").select("kuberich-test-one"), 5
    )
    try:
        await session.open()
        yield session, calls, received
    finally:
        await session.close()
        await server.cleanup()


def slice_table(bodies):
    return {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "Table",
        "columnDefinitions": [{"name": "Name", "type": "string"}],
        "rows": [{"object": body, "cells": [body["metadata"]["name"]]} for body in bodies],
    }


def diagnostic_slices(*, null):
    resource = descriptor(
        next(item for item in curated_families() if item.resource == "endpointslices")
    )
    bodies = list(endpoint_manifests(NAMESPACE, "controlled-actual-pod-uid"))
    for index, body in enumerate(bodies):
        body["metadata"].update(
            uid="controlled-slice-" + str(index), resourceVersion="owned/observed-1"
        )
    if null:
        bodies[1]["endpoints"] = None
    selected = TableDecoder(resource, NAMESPACE).records(slice_table(bodies))
    return resource, bodies, selected


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_get_empty", [False, True])
async def test_failed_native_comparison_retains_actual_values_and_distinct_get_table_shapes_before_assert(
    tmp_path, raw_get_empty
):
    resource, bodies, selected = diagnostic_slices(null=True)
    get_bodies = copy.deepcopy(bodies)
    if raw_get_empty:
        get_bodies[1]["endpoints"] = []
    states = [get_bodies[0], slice_table([bodies[0]]), get_bodies[1], slice_table([bodies[1]])]
    requests = []
    case = replace(next(item for item in CASES if item.resource == "endpointslices"), second="99")
    directory = tmp_path / "evidence"
    async with crd_api(tmp_path, states, requests=requests) as (session, calls, _):
        with pytest.raises(AssertionError):
            await check_native_projection(
                SimpleNamespace(session=session), case, resource, selected, directory
            )
        assert len(calls) == 4 and session.api is not None
    observed = json.loads((directory / "native-endpointslices-observation.json").read_text())
    assert observed["stage"] == "observed-before-assert"
    assert observed["values"][0] == "3" and observed["values"][1] != "99"
    assert observed["expected"] == ["3", "99"]
    assert (
        observed["source_notices"]
        and observed["records"][1]["resource_version"] == "owned/observed-1"
    )
    raw = json.loads((directory / "endpoint-raw-representations.json").read_text())
    assert raw[1]["selected_uid"] == "controlled-slice-1"
    assert raw[1]["selected_resource_version"] == "owned/observed-1"
    assert raw[1]["get"]["body"]["endpoints"] == ([] if raw_get_empty else None)
    assert raw[1]["table"]["body"]["rows"][0]["object"]["endpoints"] is None
    assert [query for _, query, _ in requests] == [
        {},
        {"includeObject": "Object"},
        {},
        {"includeObject": "Object"},
    ]
    assert ["as=Table" in accept for _, _, accept in requests] == [False, True, False, True]


@pytest.mark.asyncio
async def test_successful_native_comparison_also_records_actual_full_table_and_raw_objects(
    tmp_path,
):
    resource, bodies, selected = diagnostic_slices(null=False)
    states = [bodies[0], slice_table([bodies[0]]), bodies[1], slice_table([bodies[1]])]
    case = next(item for item in CASES if item.resource == "endpointslices")
    directory = tmp_path / "evidence"
    async with crd_api(tmp_path, states) as (session, calls, _):
        result = await check_native_projection(
            SimpleNamespace(session=session), case, resource, selected, directory
        )
        assert result["values"] == ("3", "0") and len(calls) == 4
    assert json.loads((directory / "native-current-family.json").read_text())["values"] == [
        "3",
        "0",
    ]


@pytest.mark.asyncio
async def test_raw_slice_diagnostics_enforce_actual_http_one_mib_body_ceiling(tmp_path):
    resource, bodies, selected = diagnostic_slices(null=False)
    oversized = {**bodies[0], "controlled-extra": "x" * RAW_REPRESENTATION_BYTES}
    directory = tmp_path / "evidence"
    async with crd_api(tmp_path, [oversized]) as (session, calls, _):
        with pytest.raises(ResponseLimitExceeded):
            await check_native_projection(
                SimpleNamespace(session=session),
                next(item for item in CASES if item.resource == "endpointslices"),
                resource,
                selected,
                directory,
            )
        assert len(calls) == 1
    assert RAW_REPRESENTATION_BYTES == 1024 * 1024
    assert (
        json.loads((directory / "native-current-family.json").read_text())["stage"]
        == "capturing-projection"
    )
    assert not (directory / "endpoint-raw-representations.json").exists()


@pytest.mark.asyncio
async def test_actual_app_native_verifier_sequence_closes_inspection_by_stack_detach_and_drained_ownership(
    tmp_path,
):
    directory = tmp_path / "lifecycle-evidence"
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(120, 36)) as pilot:
            await started(app, pilot)
            await app.run_command("hpa team")
            resource = api.resource("horizontalpodautoscalers")
            await loaded(app, pilot, resource)
            bodies = sorted(api.objects(resource), key=lambda body: body["metadata"]["name"])
            first, second = (body["metadata"]["uid"] for body in bodies)
            table = app.standard_table
            assert (table.get_cell(first, "max").text, table.get_cell(second, "max").text) == (
                "5",
                "15",
            )
            table.restore_sort("max", False)
            await pilot.pause()
            table.action_reverse_sort()
            await pilot.pause()
            table.move_cursor(row=table.get_row_index(first))
            await asyncio.wait_for(api.watch(resource.path("team")).entered.wait(), 5)
            body = copy.deepcopy(bodies[0])
            body["metadata"]["resourceVersion"] = "owned/lifecycle-watched"
            api.emit(resource.path("team"), body)
            await until(
                lambda: (
                    app.workspace.store.observation.snapshot is not None
                    and app.workspace.store.observation.snapshot.resource_version
                    == "owned/lifecycle-watched"
                )
            )
            assert (
                app.check_action("edit", ()) is False
                and app.check_action("review_delete", ()) is False
            )
            await pilot.press("E", "ctrl+d")
            await pilot.pause()
            assert len(app.screen_stack) == 1
            inspection = await open_details(app)
            persist(directory, "before-escape.json", inspection_lifecycle(app, inspection))
            assert not inspection_closed(app, inspection)
            await pilot.press("escape")
            await wait_for_inspection_closed(app, inspection, directory, "owned-http")
            after = inspection_lifecycle(app, inspection)
            persist(directory, "after-escape.json", after)
            assert after["is_mounted"] is True
            assert after["is_attached"] is after["in_actual_stack"] is False
            assert after["operation_count"] == after["retained_general_inspections"] == 0
            assert inspection_closed(app, inspection)
            closed = json.loads((directory / "owned-http-inspection-closed.json").read_text())
            assert closed["is_attached"] is closed["in_actual_stack"] is False
            assert closed["operation_count"] == closed["retained_general_inspections"] == 0
            assert table.selected_uid == first
        assert app.sessions.client is None


@pytest.mark.parametrize("fault", [None, "stack", "attached", "operations", "retained"])
def test_inspection_close_contract_never_accepts_active_stack_dom_or_owned_work(fault):
    inspection = SimpleNamespace(
        is_mounted=True,
        is_attached=fault == "attached",
        operation_count=1 if fault == "operations" else 0,
    )
    app = SimpleNamespace(
        screen_stack=(inspection,) if fault == "stack" else (),
        operations=SimpleNamespace(
            retained_general_inspection_count=1 if fault == "retained" else 0
        ),
    )
    assert inspection_closed(app, inspection) is (fault is None)


@pytest.mark.asyncio
async def test_real_http_crd_null_and_omitted_conditions_remain_pending_until_established(
    tmp_path, monkeypatch
):
    deadlines = []

    async def observe_deadline(predicate, *, timeout):
        deadlines.append(timeout)
        return await observed(predicate, timeout=timeout)

    monkeypatch.setattr(fixtures, "observed", observe_deadline)
    states = [
        {"status": {"conditions": None}},
        {},
        {"status": None},
        {"status": {}},
        {"status": {"conditions": []}},
        {"status": {"conditions": [{"type": "NamesAccepted", "status": "True"}]}},
        {"status": {"conditions": [{"type": "Established", "status": "False"}]}},
        {"status": {"conditions": [{"type": "Established", "status": True}]}},
        {"status": {"conditions": [{"type": "Established", "status": "True"}]}},
    ]
    async with crd_api(tmp_path, states) as (session, calls, _):
        await wait_for_crd_established(session)
        assert len(calls) == len(states)
        assert set(calls) == {
            "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/verticalpodautoscalers.autoscaling.k8s.io"
        }
        assert deadlines == [45] and session.api is not None
    assert session.api is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        {"status": "invalid"},
        {"status": []},
        {"status": 0},
        {"status": {"conditions": "invalid"}},
        {"status": {"conditions": {}}},
        {"status": {"conditions": [None]}},
    ],
)
async def test_real_http_crd_malformed_status_is_never_accepted_as_established(tmp_path, state):
    async with crd_api(tmp_path, [state]) as (session, calls, _):
        with pytest.raises(AssertionError, match="malformed"):
            await wait_for_crd_established(session)
        assert len(calls) == 1 and session.api is not None


@pytest.mark.asyncio
async def test_real_http_crd_permanent_pending_remains_unready_and_caller_cancellation_drains(
    tmp_path,
):
    async with crd_api(tmp_path, [{"status": {"conditions": None}}]) as (session, calls, received):
        task = asyncio.create_task(wait_for_crd_established(session))
        try:
            await asyncio.wait_for(received.wait(), 5)
            await until(lambda: len(calls) >= 2, timeout=5)
            assert not task.done()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert task.done() and session.api is not None
    assert session.api is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "wrong-version", "wrong-group", "ambiguous", "scope"])
async def test_create_resolves_exact_actual_discovery_and_scope_before_sdk_io(tmp_path, fault):
    resource = ApiResource("owned.kind", "v1", "things", "Thing", True, frozenset({"create"}))
    document = {
        "apiVersion": "owned.kind/v1",
        "kind": "Thing",
        "metadata": {"name": "a", "namespace": NAMESPACE},
    }
    if fault == "wrong-version":
        document["apiVersion"] = "owned.kind/v2"
    elif fault == "wrong-group":
        document["apiVersion"] = "other.kind/v1"
    elif fault == "scope":
        document["metadata"].pop("namespace")
    discovery = (
        Discovery((resource, replace(resource, name="other-things")))
        if fault == "ambiguous"
        else Discovery((resource,))
    )
    async with writer_api(tmp_path) as (session, calls):
        if fault is None:
            await create_document(SimpleNamespace(session=session), discovery, document)
            assert calls[0][1] == f"/apis/owned.kind/v1/namespaces/{NAMESPACE}/things"
        else:
            with pytest.raises(AssertionError):
                await create_document(SimpleNamespace(session=session), discovery, document)
            assert calls == []


@pytest.mark.parametrize(
    "fault",
    [None, "no-source", "old-revision", "other-scope", "loading", "hidden", "wrong-options"],
)
def test_event_readiness_requires_accepted_source_and_options_not_just_visible_rows(fault):
    resource = ApiResource("events.k8s.io", "v1", "events", "Event", True, frozenset({"list"}))
    scope = ResourceScope(SessionIdentity("owned", 1), resource, NAMESPACE)
    options = EventOptions(grouped=True, warnings_only=True)
    source = EventSourceState(scope, 2, CollectionState(), ViewStatus.LIVE, AT)
    observation = ViewObservation(revision=2, scope=scope, status=ViewStatus.LIVE)
    table = SimpleNamespace(display=True, source=source, options=options, row_count=20)
    if fault == "no-source":
        table.source = None
    elif fault == "old-revision":
        table.source = replace(source, revision=1)
    elif fault == "other-scope":
        table.source = replace(source, scope=replace(scope, namespace=OTHER))
    elif fault == "loading":
        observation = replace(observation, status=ViewStatus.LOADING)
    elif fault == "hidden":
        table.display = False
    elif fault == "wrong-options":
        table.options = EventOptions()
    app = SimpleNamespace(
        events_table=table,
        workspace=SimpleNamespace(store=SimpleNamespace(observation=observation)),
    )
    assert events_ready(app, resource, options) is (fault is None)


@pytest.mark.asyncio
async def test_bounded_observation_waits_for_evidence_and_preserves_failure_or_cancellation():
    assert READ_SECONDS == 15 and VERIFY_SECONDS == 300
    evidence = object()
    predicate = AsyncMock(side_effect=[None, evidence])
    assert await observed(predicate) is evidence and predicate.await_count == 2
    assert await observed(AsyncMock(return_value=False)) is False
    with pytest.raises(TimeoutError):
        await until(lambda: False, timeout=0)
    with pytest.raises(TimeoutError):
        await observed(AsyncMock(return_value=None), timeout=0)
    with pytest.raises(RuntimeError):
        await observed(AsyncMock(side_effect=RuntimeError("owned-probe-failure")))
    with pytest.raises(asyncio.CancelledError):
        await observed(AsyncMock(side_effect=asyncio.CancelledError))


@pytest.mark.parametrize("value", [None, "", 0])
def test_uid_acceptance_cannot_count_absence_as_actual_identity(value):
    with pytest.raises(AssertionError):
        required_uid(ResourceRecord("owned", value, NAMESPACE, "1", None, b"{}"))


def test_prepare_mode_retains_source_pins_without_any_docker_or_kube_call(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No cluster call is permitted in prepare-only mode")

    monkeypatch.setattr(runner, "owned_cluster", forbidden)
    monkeypatch.setattr(runner, "verify", forbidden)
    evidence = tmp_path / "new" / "evidence.json"
    runner.main(["--kind", "not-executed", "--prepare-only", "--evidence", str(evidence)])
    data = json.loads(evidence.read_text())
    assert data["status"] == "prepared" and data["executed_family_count"] == 0
    assert data["inputs_unchanged"]
    assert data["prepared"]["family_count"] == 19
    assert data["prepared"]["fixture_images"] == [SHELL_IMAGE]
    assert all(url.startswith("https://") for url in data["prepared"]["source_pins"].values())


def test_prepare_refuses_preexisting_evidence_including_failed_directory(tmp_path):
    (tmp_path / "original-failure.log").write_text("retain")
    with pytest.raises(ValueError, match="fresh evidence directory"):
        runner.main(
            ["--kind", "not-executed", "--prepare-only", "--evidence", str(tmp_path / "new.json")]
        )
    assert (tmp_path / "original-failure.log").read_text() == "retain"


@pytest.mark.parametrize(
    "mutation",
    ["python", "css", "css-added", "css-removed", "fixture", "entrypoint", "ownership"],
)
def test_exact_inputs_bind_runtime_stylesheets_and_all_owned_verifier_sources(tmp_path, mutation):
    paths = {
        "python": "src/kuberich/ui/app.py",
        "css": "src/kuberich/ui/kuberich.tcss",
        "fixture": "scripts/curated_kind.py",
        "entrypoint": "scripts/verify_curated_resources_kind.py",
        "ownership": "scripts/owned_kind.py",
        "project": "pyproject.toml",
        "lock": "uv.lock",
    }
    for relative in paths.values():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("owned original input\n")
    before = runner.input_hashes(tmp_path)
    if mutation == "css-added":
        changed = tmp_path / "src/kuberich/ui/new.tcss"
        changed.write_text("Screen { color: red; }\n")
    elif mutation == "css-removed":
        changed = tmp_path / paths["css"]
        changed.unlink()
    else:
        changed = tmp_path / paths[mutation]
        changed.write_text("owned changed input\n")
    after = runner.input_hashes(tmp_path)
    key = str(changed.relative_to(tmp_path))
    assert after != before
    if mutation == "css-added":
        assert key not in before and key in after
    elif mutation == "css-removed":
        assert key in before and key not in after
    else:
        assert before[key] != after[key]
    assert all(before[name] == after[name] for name in set(before) & set(after) if name != key)


def nested_kind_result():
    """Real result field/type shape with synthetic identities; not a cluster replay."""
    documents = (
        *fixture_manifests(NAMESPACE, OTHER),
        *endpoint_manifests(NAMESPACE, "synthetic-pod"),
    )
    ordinary, native = [], []
    for case in CASES:
        resource = descriptor(
            next(item for item in curated_families() if item.resource == case.resource)
        )
        bodies = [copy.deepcopy(body) for body in documents if body["kind"] == resource.kind]
        selected = []
        for index, body in enumerate(bodies):
            body["metadata"].update(
                uid=f"synthetic-{case.resource}-{index}", resourceVersion="synthetic-rv"
            )
            selected.append(resource_record(resource, body))
        projected = [curated_cells(resource, record) for record in selected]
        uids = [record.uid for record in selected]
        ordinary.append(
            {
                "resource": asdict(resource),
                "namespace": NAMESPACE if resource.namespaced else None,
                "command": case.resource,
                "uids": uids,
                "field": case.field,
                "values": [case.first, case.second],
                "ascending": tuple(uids[index] for index in case.ascending),
                "descending": tuple(uids[index] for index in reversed(case.ascending)),
                "actual_list_watch_get": True,
                "fresh_inspection_resource_version": "synthetic-rv",
                "source_payload_hidden": True,
                "family_read_only_with_settings_false": True,
            }
        )
        native.append(
            {
                "stage": "observed-before-assert",
                "resource": asdict(resource),
                "source_path": resource.path(NAMESPACE if resource.namespaced else None),
                "observed_at": AT.isoformat(),
                "actual_table_full_objects": True,
                "uids": uids,
                "records": [
                    {
                        "name": record.name,
                        "uid": record.uid,
                        "namespace": record.namespace,
                        "resource_version": record.resource_version,
                        "metadata_only": record.metadata_only,
                    }
                    for record in selected
                ],
                "field": case.field,
                "expected": [case.first, case.second],
                "values": tuple(dict(item.values)[case.field].text for item in projected),
                "source_notices": [item.notices for item in projected],
                "cells": [{key: asdict(value) for key, value in item.values} for item in projected],
            }
        )
    events = ApiResource(
        "events.k8s.io",
        "v1",
        "events",
        "Event",
        True,
        frozenset({"watch", "get", "list"}),
        ("event", "ev"),
    )
    links = {
        "selected_pod_uid": "synthetic-pod",
        "omitted_selector_admitted_as_all_namespace_pods": True,
        "endpoint_declared_service_uid": "synthetic-service",
        "endpoint_target_requires_actual_uid": True,
        "runtimeclass_selected_namespace_pod_uid": "synthetic-pod",
        "ingressclass_selected_namespace_ingress_uid": "synthetic-ingress",
        "group_kind_only_parameters_actual_uid": "synthetic-parameters",
        "role_authorization_intent_present": True,
    }
    return {
        "ordinary_families": ordinary,
        "ordinary_count": 18,
        "events": {
            "resource": asdict(events),
            "created_event_uids": [
                "synthetic-event-a",
                "synthetic-event-b",
                "synthetic-event-normal",
            ],
            "warning_member_uids": ("synthetic-event-a", "synthetic-event-b"),
            "known_reported_occurrences": 5,
            "normal_event_excluded": True,
            "core_v1_same_actual_event_uids": [
                "synthetic-event-a",
                "synthetic-event-b",
                "synthetic-event-normal",
            ],
            "actual_regarding_uid": "synthetic-pod",
            "replacement_uid": "synthetic-replacement",
            "replacement_link_rejected": True,
            "limits": "Authored Event API fixtures; no event-controller durability claim.",
        },
        "events_count": 1,
        "hpa_same_uid_real_v1_v2": "synthetic-hpa",
        "compact_real_metadata_fallback": True,
        "actual_other_namespace_empty": True,
        "links": links,
        "owned_app_closed": True,
        "native_projections": native,
        "actual_policy_rbac_denial": 403,
        "minimal_owned_vpa_crd_only": True,
        "native_vpa_preinstallation_absent": True,
        "no_autoscaler_controller_or_network_health_claim": True,
        "owned_kubeconfig_unchanged": True,
        "owned_session_closed": True,
    }


def test_evidence_json_roundtrips_declared_nested_types_with_stable_sorted_sets():
    value = {
        "verbs": frozenset({"watch", "get", "list"}),
        "nested": [{"at": AT, "quantity": Decimal("0.0100"), "session": UUID(int=1)}],
    }
    encoded = evidence_json(value)
    decoded = json.loads(encoded)
    assert decoded == {
        "verbs": ["get", "list", "watch"],
        "nested": [
            {
                "at": "2026-11-06T12:00:00+00:00",
                "quantity": "0.0100",
                "session": "00000000-0000-0000-0000-000000000001",
            }
        ],
    }
    assert (
        evidence_json({"nested": value["nested"], "verbs": frozenset(["list", "watch", "get"])})
        == encoded
    )


@pytest.mark.parametrize(
    "value",
    [
        frozenset({1, "get"}),
        {"get"},
        Decimal("NaN"),
        datetime(2026, 11, 6),
        float("nan"),
        float("inf"),
    ],
)
def test_evidence_json_rejects_undeclared_or_nonfinite_types(value):
    with pytest.raises((TypeError, ValueError)):
        evidence_json({"value": value})


def test_evidence_json_never_renders_arbitrary_objects():
    class Opaque:
        def __str__(self):
            raise AssertionError("Arbitrary evidence must never be stringified")

        __repr__ = __str__

    with pytest.raises(TypeError, match="Unsupported evidence type: Opaque"):
        evidence_json({"nested": [Opaque()]})


@pytest.mark.parametrize(
    "mode", ["success", "failure", "cancel", "incomplete", "changed-inputs", "cleanup-failure"]
)
def test_entry_receipts_preserve_real_run_outcome_and_owned_cleanup_controls(
    tmp_path, monkeypatch, mode
):
    private = tmp_path / "private"
    private.mkdir()
    path = private / "generated"
    path.write_text("private-owned-test-only")
    cluster = OwnedCluster(
        "kuberich-test-fixture", path, private, "kind-kuberich-test-fixture", ("actual-fake-node",)
    )
    exited = []

    @contextmanager
    def owned_cluster(kind, *, docker):
        assert (kind, docker) == ("owned-kind", "owned-docker")
        try:
            yield cluster
        finally:
            path.unlink()
            private.rmdir()
            exited.append(True)
            if mode == "cleanup-failure":
                raise RuntimeError("owned-cleanup-failure")

    async def verify(observed_cluster, directory):
        assert observed_cluster is cluster
        if mode == "failure":
            raise LookupError("owned-run-failure")
        if mode == "cancel":
            raise asyncio.CancelledError
        result = nested_kind_result()
        result["events_count"] = 0 if mode == "incomplete" else 1
        return result

    monkeypatch.setattr(runner, "owned_cluster", owned_cluster)
    monkeypatch.setattr(runner, "verify", verify)
    if mode == "changed-inputs":
        captured = iter([{"source": "before"}, {"source": "changed"}, {"source": "changed"}])
        monkeypatch.setattr(runner, "input_hashes", lambda root: next(captured))
    evidence = tmp_path / "evidence" / "result.json"
    arguments = ["--kind", "owned-kind", "--docker", "owned-docker", "--evidence", str(evidence)]
    expected = {
        "failure": LookupError,
        "cancel": asyncio.CancelledError,
        "incomplete": AssertionError,
        "changed-inputs": AssertionError,
        "cleanup-failure": RuntimeError,
    }.get(mode)
    if expected is None:
        runner.main(arguments)
    else:
        with pytest.raises(expected):
            runner.main(arguments)
    data = json.loads(evidence.read_text())
    assert exited == [True] and data["private_directory_deleted"]
    assert data["status"] == ("passed" if mode == "success" else "failed")
    assert data["owned_cluster_deleted"] is (mode != "cleanup-failure")
    if mode == "incomplete":
        assert data["executed_family_count"] == 18
    if mode in {"success", "incomplete", "changed-inputs", "cleanup-failure"}:
        assert len(data["ordinary_families"]) == len(data["native_projections"]) == 18
        assert data["ordinary_families"][0]["resource"]["verbs"] == ["get", "list", "watch"]
        assert data["events"]["resource"]["verbs"] == ["get", "list", "watch"]
        assert data["events"]["known_reported_occurrences"] == 5
        runtime = next(
            item
            for item in data["native_projections"]
            if item["resource"]["name"] == "runtimeclasses"
        )
        assert runtime["cells"][0]["overhead-memory"]["sort"] == "67108864"
    if mode in {"failure", "cancel"}:
        assert data["executed_family_count"] == 0
        assert data["qualification_failure_type"] == (
            "LookupError" if mode == "failure" else "CancelledError"
        )
