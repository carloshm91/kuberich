"""Real inspection GETs retain literal RBAC names and build curated facts in the worker."""

import json
from dataclasses import asdict, replace

import pytest
from aiohttp import web

from kuberich.domain.events import event_fact
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.inspection import InspectionService
from tests.support.curated_access import access_manifest, access_resource
from tests.support.curated_scaling import api, record
from tests.support.resources import collection, reader_fixture


def service(reader, resource, raw, *, current=lambda: True):
    metadata = raw["metadata"]
    target = ResourceTarget(
        SessionIdentity(reader.session.context.name, 3),
        resource.group,
        resource.name,
        metadata.get("namespace"),
        metadata["name"],
        metadata["uid"],
    )
    return InspectionService(reader.session, resource, target, AccessPolicy(True), current)


@pytest.mark.asyncio
async def test_rbac_colon_name_is_a_literal_bounded_get_and_defaults_are_curated(tmp_path):
    resource = access_resource("ClusterRole")
    raw = access_manifest("ClusterRole")
    raw["metadata"].update(name="system:synthetic:reader", resourceVersion="fresh-rv")
    calls = []

    async def handler(request):
        calls.append((request.method, request.path, request.query.copy()))
        return web.json_response(collection() if request.path.endswith("/events") else raw)

    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, resource, raw).load()
        assert result.resource_version == "fresh-rv"
        assert result.curated is not None
        assert "PRIVATE_CURATED_ACCESS_CANARY" not in result.documents.details
        assert calls[0][1].endswith("/clusterroles/system:synthetic:reader")
        assert calls[0][2] == {}


@pytest.mark.asyncio
async def test_worker_curated_result_matches_fresh_get_rv_not_selected_snapshot(tmp_path):
    resource = api("HorizontalPodAutoscaler")
    raw = record(resource).manifest
    raw["metadata"]["resourceVersion"] = "fresh-inspection-rv"
    raw["spec"]["arbitrary"] = "synthetic-unlisted-canary"

    async def handler(request):
        return web.json_response(collection() if request.path.endswith("/events") else raw)

    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, resource, raw).load()
        assert result.resource_version == "fresh-inspection-rv"
        assert result.curated.links[0].key == "target"
        assert "synthetic-unlisted-canary" not in result.documents.details
        assert "synthetic-unlisted-canary" in result.documents.yaml


@pytest.mark.asyncio
async def test_known_unsupported_api_uses_metadata_fallback(tmp_path):
    resource = replace(api("HorizontalPodAutoscaler"), version="v9")
    raw = record(resource).manifest

    async def handler(request):
        return web.json_response(collection() if request.path.endswith("/events") else raw)

    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, resource, raw).load()
        assert result.curated is None
        assert "metadata only" in result.documents.details
        assert "scaleTargetRef" not in result.documents.details


@pytest.mark.asyncio
@pytest.mark.parametrize("uid", ["regarding-uid", None])
async def test_individual_event_safe_facts_and_uid_required_regarding_link(tmp_path, uid):
    resource = ApiResource("events.k8s.io", "v1", "events", "Event", True, frozenset({"get"}))
    raw = {
        "apiVersion": "events.k8s.io/v1",
        "kind": "Event",
        "metadata": {
            "name": "owned-event",
            "namespace": "team",
            "uid": "event-uid",
            "resourceVersion": "event-rv",
        },
        "type": "Warning",
        "reason": "SyntheticObservation",
        "note": "synthetic-event-note-canary",
        "regarding": {
            "apiVersion": "v1",
            "kind": "Pod",
            "name": "owned-pod",
            "namespace": "team",
            **({"uid": uid} if uid else {}),
        },
    }

    async def handler(request):
        return web.json_response(
            collection() if request.path == "/api/v1/namespaces/team/events" else raw
        )

    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, resource, raw).load()
        assert "synthetic-event-note-canary" not in result.documents.details
        assert "SyntheticObservation" in result.documents.details
        link = result.curated.links[0]
        assert (link.destination is not None) is (uid is not None)
        if uid:
            assert link.destination.require_uid and link.destination.ref.uid == uid


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["source", "events"])
async def test_client_context_replacement_during_real_read_never_publishes_inspection(
    tmp_path, stage
):
    resource = api("HorizontalPodAutoscaler")
    raw = record(resource).manifest
    captured_client, requests = [], []

    async def handler(request):
        requests.append(request.path)
        event_request = request.path.endswith("/events")
        if event_request is (stage == "events"):
            client = captured_client[0]
            client.context = replace(client.context, name="synthetic-other-context")
        return web.json_response(collection() if event_request else raw)

    async with reader_fixture(tmp_path, handler) as reader:
        captured_client.append(reader.session)
        original_context = reader.session.context
        owner = service(reader, resource, raw)
        try:
            with pytest.raises(AppError, match="context"):
                await owner.load()
            assert len(requests) == (1 if stage == "source" else 2)
        finally:
            reader.session.context = original_context


@pytest.mark.asyncio
@pytest.mark.parametrize("size,character", [(128, "c"), (8192, "\\"), (8192, "界")])
async def test_event_inspection_bounds_presentation_without_clipping_model_or_action_identity(
    tmp_path, size, character
):
    from tests.support.events import event_manifest, event_resource

    resource = event_resource()
    raw = event_manifest(reportingController=character * size, reportingInstance=character * size)
    declared_uid = "界" * 8192
    raw["regarding"]["uid"] = declared_uid
    fact = event_fact(resource, resource_record(resource, raw))
    reporter = fact.reporter
    assert len(reporter) > 256
    requests = []

    async def handler(request):
        requests.append((request.method, request.path))
        return web.json_response(
            collection() if request.path == "/api/v1/namespaces/team/events" else raw
        )

    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, resource, raw).load()
        observed = result.curated
        assert all(
            len(value) <= 256 for part in observed.sections for row in part.rows for value in row
        )
        assert (
            len(json.dumps(asdict(observed), ensure_ascii=False, separators=(",", ":")).encode())
            <= 65536
        )
        assert sum(len(part.rows) for part in observed.sections) + len(observed.links) <= 256
        assert observed.links[0].destination.ref.uid == declared_uid
        assert fact.reporter == reporter
        assert event_fact(resource, resource_record(resource, raw)).reporter == reporter
        assert any("clipped" in notice for notice in observed.notices)
        assert len(requests) == 2 and {method for method, _ in requests} == {"GET"}
