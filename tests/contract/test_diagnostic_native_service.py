"""Real owned HTTP diagnostics: exact ownership, evidence, permission and action reads."""

import asyncio
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.domain.cluster_diagnostics import DiagnosticCategory as Category
from kuberich.domain.cluster_diagnostics import DiagnosticSourceKind as Kind
from kuberich.domain.cluster_diagnostics import DiagnosticStatus as Status
from kuberich.domain.resources import Discovery
from kuberich.errors import AppError
from kuberich.services import cluster_diagnostics as native
from kuberich.services.access import AccessPolicy
from kuberich.services.cluster_diagnostics import DiagnosticService
from tests.support.diagnostic_native import (
    DEPLOYMENTS,
    EVENTS,
    NEW_EVENTS,
    NOW,
    PODS,
    PVC,
    REPLICASETS,
    list_body,
    manifest,
    owner,
    ref,
    request,
)
from tests.support.resources import reader_fixture

pytestmark = pytest.mark.fast


def service(reader, req, resources=(PODS, EVENTS), current=lambda _: True):
    return DiagnosticService(
        reader, Discovery(tuple(resources)), AccessPolicy(True), current, now=lambda: NOW
    )


def image_pod(name="one", **fields):
    return manifest(
        PODS,
        name,
        status={
            "containerStatuses": [
                {
                    "name": "app",
                    "state": {
                        "waiting": {"reason": "ErrImagePull", "message": "Image was unavailable"}
                    },
                }
            ]
        },
        **fields,
    )


def event(name="event", **fields):
    return manifest(
        EVENTS,
        name,
        involvedObject={
            "apiVersion": "v1",
            "kind": "Pod",
            "namespace": "team",
            "name": "one",
            "uid": "owned-one",
        },
        reason="FailedMount",
        message="Mount unavailable",
        lastTimestamp=NOW.isoformat(),
        **fields,
    )


@pytest.mark.asyncio
async def test_overview_real_status_uid_events_incremental_sources_and_no_log_or_secret_reads(
    tmp_path,
):
    calls, values = [], []
    pod = image_pod()
    pod["spec"]["containers"][0].update(
        env=[{"name": "SECRET", "value": "PRIVATE"}], command=["PRIVATE"]
    )

    async def handler(req):
        calls.append(req.path)
        if req.path.endswith("/pods"):
            return web.json_response(list_body(PODS, pod))
        return web.json_response(list_body(EVENTS, event()))

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req).collect(req, values.append)
    assert result.native_requests_used == 2 and not result.collecting
    assert {f.category for f in result.findings} == {Category.IMAGE_PULL, Category.VOLUME}
    assert calls == ["/api/v1/namespaces/team/pods", "/api/v1/namespaces/team/events"]
    assert "PRIVATE" not in repr(result) and "env" not in repr(result)
    assert values[-1] == result and any(
        s.status is Status.LOADING for v in values for s in v.sources
    )
    assert all(s.status is Status.READY for s in result.sources)


@pytest.mark.asyncio
async def test_selected_deployment_exact_uid_chain_and_root_conditions(tmp_path):
    deployment = manifest(
        DEPLOYMENTS, status={"conditions": [{"type": "Available", "status": "False"}]}
    )
    children = [
        owner(manifest(REPLICASETS, "child"), DEPLOYMENTS),
        owner(manifest(REPLICASETS, "impostor"), DEPLOYMENTS, uid="old-uid"),
    ]
    pods = [
        owner(image_pod(), REPLICASETS, "child"),
        owner(image_pod("unrelated"), REPLICASETS, "impostor"),
        image_pod("labels-do-not-prove"),
    ]
    calls = []

    async def handler(req):
        calls.append(req.path)
        if req.path.endswith("/deployments/one"):
            return web.json_response(deployment)
        if req.path.endswith("/replicasets"):
            return web.json_response(list_body(REPLICASETS, *children))
        if req.path.endswith("/pods"):
            return web.json_response(list_body(PODS, *pods))
        return web.json_response(list_body(EVENTS))

    req = request(ref(DEPLOYMENTS))
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req, (PODS, EVENTS, DEPLOYMENTS, REPLICASETS)).collect(
            req, lambda _: None
        )
    assert {f.subject.name for f in result.findings} == {"one"}
    assert {f.category for f in result.findings} == {Category.WORKLOAD, Category.IMAGE_PULL}
    assert result.native_requests_used == 4 and len(calls) == 4


@pytest.mark.asyncio
async def test_root_pvc_duplicate_declarations_fetch_once_preserve_distinct_paths(tmp_path):
    pod = image_pod()
    pod["spec"]["volumes"] = [
        {"name": "first", "persistentVolumeClaim": {"claimName": "shared"}},
        {"name": "second", "persistentVolumeClaim": {"claimName": "shared", "optional": True}},
    ]
    calls = []

    async def handler(req):
        calls.append(req.path)
        if req.path.endswith("/pods/one"):
            return web.json_response(pod)
        if req.path.endswith("/persistentvolumeclaims/shared"):
            return web.json_response(manifest(PVC, "shared", status={"phase": "Pending"}))
        return web.json_response(list_body(EVENTS))

    req = request(ref())
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req, (PODS, EVENTS, PVC)).collect(req, lambda _: None)
    volume = next(f for f in result.findings if f.category is Category.VOLUME)
    assert len(volume.evidence) == 2 and len({e.field_path for e in volume.evidence}) == 2
    assert sum("persistentvolumeclaims/shared" in path for path in calls) == 1
    assert "does not prove" in volume.explanation


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", [403, 404, 500])
async def test_core_event_failure_never_falls_back_to_hide_denial(tmp_path, denial):
    paths = []

    async def handler(req):
        paths.append(req.path)
        if req.path.endswith("/pods"):
            return web.json_response(list_body(PODS, image_pod()))
        return web.Response(status=denial, text="PRIVATE raw error")

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req, (PODS, EVENTS, NEW_EVENTS)).collect(req, lambda _: None)
    assert paths == ["/api/v1/namespaces/team/pods", "/api/v1/namespaces/team/events"]
    assert result.findings and "PRIVATE" not in repr(result)
    assert result.sources[-1].status is (
        Status.FORBIDDEN
        if denial == 403
        else Status.UNAVAILABLE
        if denial == 404
        else Status.FAILED
    )


@pytest.mark.asyncio
async def test_fallback_only_when_core_not_discovered_and_unknown_sources(tmp_path):
    paths = []

    async def handler(req):
        paths.append(req.path)
        return web.json_response(
            list_body(NEW_EVENTS)
            if req.path == "/apis/events.k8s.io/v1/events"
            else list_body(PODS)
        )

    req = request(namespace=None)
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req, (PODS, NEW_EVENTS)).collect(req, lambda _: None)
        missing = await service(reader, req, ()).collect(req, lambda _: None)
    assert paths == ["/api/v1/pods", "/apis/events.k8s.io/v1/events"]
    assert not result.findings and "expired" in result.sources[-1].detail
    assert all(s.status is Status.UNAVAILABLE for s in missing.sources)


@pytest.mark.asyncio
async def test_replacement_uid_and_denied_or_unavailable_root_never_collect_children(tmp_path):
    responses = [
        web.json_response(manifest(PODS, uid="replacement")),
        web.Response(status=403),
        web.Response(status=404),
    ]
    paths = []

    async def handler(req):
        paths.append(req.path)
        return responses.pop(0)

    req = request(ref())
    async with reader_fixture(tmp_path, handler) as reader:
        for expected in [Status.PARTIAL, Status.FORBIDDEN, Status.UNAVAILABLE]:
            result = await service(reader, req).collect(req, lambda _: None)
            assert not result.findings and result.sources[0].status is expected
    assert paths == ["/api/v1/namespaces/team/pods/one"] * 3


@pytest.mark.asyncio
async def test_explicit_resolve_fresh_get_exact_descriptor_and_uid_with_separate_budget(tmp_path):
    value = image_pod()

    async def handler(req):
        return web.json_response(value)

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        api = service(reader, req)
        for _ in range(64):
            api.budget.charge()
        assert (await api.resolve(req, ref())).uid == "owned-one"
        assert api.budget.used == 64
        assert (await api.resolve(req, replace(ref(), uid=None))).uid == "owned-one"
        for invalid in [
            replace(ref(), resource=None),
            replace(ref(), api_version="v2"),
            replace(ref(), kind="Other"),
            replace(ref(), namespace=None),
            replace(ref(), namespace="other"),
            replace(ref(), resource=replace(PODS, version="v2")),
        ]:
            with pytest.raises(AppError, match="exact served"):
                await api.resolve(req, invalid)
        value["metadata"]["uid"] = "replacement"
        with pytest.raises(AppError, match="replaced"):
            await api.resolve(req, ref())


@pytest.mark.asyncio
async def test_stale_after_await_and_before_reads_cannot_publish(tmp_path):
    valid = True

    async def handler(req):
        nonlocal valid
        valid = False
        return web.json_response(list_body(PODS, image_pod()))

    req, values = request(), []
    async with reader_fixture(tmp_path, handler) as reader:
        api = service(reader, req, current=lambda _: valid)
        with pytest.raises(AppError, match="stale"):
            await api.collect(req, values.append)
        with pytest.raises(AppError, match="stale"):
            await api.resolve(req, ref())
    assert all(not v.findings for v in values)


@pytest.mark.asyncio
async def test_partial_pages_malformed_evidence_and_unmatched_events_remain_visible(tmp_path):
    async def handler(req):
        if req.path.endswith("/pods"):
            if req.query.get("continue"):
                return web.Response(status=403)
            return web.json_response(
                list_body(
                    PODS,
                    image_pod(),
                    manifest(PODS, "malformed", status={"conditions": "bad"}),
                    token="next",
                )
            )
        bad = event("unrelated")
        bad["involvedObject"]["uid"] = "old-uid"
        malformed = event("malformed")
        malformed["series"] = 7
        return web.json_response(list_body(EVENTS, bad, malformed))

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req).collect(req, lambda _: None)
    assert result.findings and result.native_requests_used == 3
    assert all(s.status is Status.PARTIAL for s in result.sources)
    assert result.sources[0].omitted_findings == 1
    assert "completed pages" in result.sources[0].detail
    assert "2 unrelated" in result.sources[-1].detail


@pytest.mark.asyncio
async def test_native_read_object_raw_fact_and_deadline_bounds(tmp_path, monkeypatch):
    calls = []

    async def handler(req):
        calls.append(req.path)
        resource = PODS if req.path.endswith("/pods") else EVENTS
        return web.json_response(
            list_body(
                resource,
                image_pod("pod-" + (req.query.get("continue") or "0")),
                token=str(int(req.query.get("continue") or "0") + 1),
            )
            if resource is PODS
            else list_body(EVENTS)
        )

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        # Real ResourceReader pagination consumes exactly the shared logical budget.
        api = service(reader, req)
        result = await api.collect(req, lambda _: None)
        assert result.native_requests_used == 64
        assert len(calls) == 64
        assert result.sources[0].status in {Status.PARTIAL, Status.FAILED}
        monkeypatch.setattr(native, "MAX_DIAGNOSTIC_FACT_BYTES", 1)
        result = await service(reader, req).collect(req, lambda _: None)
        assert not result.findings and any("fact retention" in s.detail for s in result.sources)
        monkeypatch.setattr(native, "MAX_DIAGNOSTIC_RAW_BYTES", 1)
        result = await service(reader, request(ref())).collect(request(ref()), lambda _: None)
        assert result.sources[0].status is Status.PARTIAL

    async def slow(req):
        await asyncio.sleep(0.03)
        return web.json_response(list_body(PODS))

    monkeypatch.setattr(native, "MAX_DIAGNOSTIC_RAW_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(native, "DIAGNOSTIC_DEADLINE", 0.005)
    req = request()
    async with reader_fixture(tmp_path, slow) as reader:
        result = await service(reader, req).collect(req, lambda _: None)
    assert not result.collecting and any("deadline" in s.detail for s in result.sources)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase", ["Pending", "Bound", "malformed", "denied", "missing-api", "many"]
)
async def test_pvc_outcomes_limits_and_evidence_omissions(tmp_path, phase):
    pod = image_pod()
    count = 17 if phase in {"many", "Pending"} else 1
    pod["spec"]["volumes"] = [
        {
            "name": f"vol{i}",
            "persistentVolumeClaim": {"claimName": f"claim{i}" if phase == "many" else "shared"},
        }
        for i in range(count)
    ]
    calls = []

    async def handler(req):
        calls.append(req.path)
        if req.path.endswith("/pods/one"):
            return web.json_response(pod)
        if "/persistentvolumeclaims/" in req.path:
            if phase == "denied":
                return web.Response(status=403)
            return web.json_response(
                manifest(
                    PVC,
                    req.path.rsplit("/", 1)[-1],
                    status=[]
                    if phase == "malformed"
                    else {"phase": "Pending" if phase == "many" else phase},
                )
            )
        return web.json_response(list_body(EVENTS))

    req = request(ref())
    resources = (PODS, EVENTS) if phase == "missing-api" else (PODS, EVENTS, PVC)
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req, resources).collect(req, lambda _: None)
    if phase in {"Pending", "many"}:
        assert any("limit" in s.detail or "omitted" in s.detail for s in result.sources)
        volume = next(f for f in result.findings if f.category is Category.VOLUME)
        assert len(volume.evidence) == 16
    elif phase == "Bound":
        assert not any(f.category is Category.VOLUME for f in result.findings)
    elif phase == "malformed":
        assert any("Malformed PVC" in s.detail for s in result.sources)
    else:
        assert any(s.status in {Status.FORBIDDEN, Status.UNAVAILABLE} for s in result.sources)
    assert sum("/persistentvolumeclaims/" in p for p in calls) <= 16


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["direct", "missing-controller", "denied-controller", "denied-pods", "oversize-root"]
)
async def test_direct_controller_unknown_membership_and_payload_limits(tmp_path, monkeypatch, mode):
    resource = REPLICASETS if mode == "direct" else DEPLOYMENTS
    root = manifest(resource)
    paths = []

    async def handler(req):
        paths.append(req.path)
        if req.path.endswith("/one"):
            return web.json_response(root)
        if req.path.endswith("/replicasets"):
            return web.Response(status=403)
        if req.path.endswith("/pods"):
            return (
                web.Response(status=403)
                if mode == "denied-pods"
                else web.json_response(list_body(PODS, owner(image_pod(), resource)))
            )
        return web.json_response(list_body(EVENTS))

    if mode == "oversize-root":
        monkeypatch.setattr(native, "MAX_DIAGNOSTIC_RAW_BYTES", 10)
    resources = (
        (PODS, EVENTS, resource)
        if mode != "denied-controller"
        else (PODS, EVENTS, DEPLOYMENTS, REPLICASETS)
    )
    req = request(ref(resource))
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req, resources).collect(req, lambda _: None)
    if mode == "direct":
        assert any(f.category is Category.IMAGE_PULL for f in result.findings)
    elif mode == "oversize-root":
        assert result.native_requests_used == 1 and not result.findings
    else:
        assert any(s.status in {Status.PARTIAL, Status.FORBIDDEN} for s in result.sources)
        assert not result.findings


@pytest.mark.asyncio
async def test_current_scheduling_condition_supersedes_recent_failure_event_and_event_fact_bound(
    tmp_path, monkeypatch
):
    scheduled = manifest(PODS, status={"conditions": [{"type": "PodScheduled", "status": "True"}]})

    async def handler(req):
        if req.path.endswith("/pods"):
            return web.json_response(list_body(PODS, scheduled))
        value = event()
        value["reason"] = "FailedScheduling"
        return web.json_response(list_body(EVENTS, value))

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req).collect(req, lambda _: None)
        finding = result.findings[0]
        assert finding.evidence[0].historical and "now scheduled" in finding.summary
        assert finding.severity.value == "info"
        monkeypatch.setattr(native, "MAX_DIAGNOSTIC_FACT_BYTES", 250)
        result = await service(reader, req).collect(req, lambda _: None)
        assert not result.findings and any("Event fact limit" in s.detail for s in result.sources)


@pytest.mark.asyncio
async def test_cancel_during_owned_projection_drains_thread_and_rejects_late_result(
    tmp_path, monkeypatch
):
    import threading

    original = native.diagnose_record
    entered, release = threading.Event(), threading.Event()
    publications = []

    def project(resource, record, observed_at):
        entered.set()
        assert release.wait(2), "Owned test worker was not released"
        return original(resource, record, observed_at)

    async def handler(req):
        return web.json_response(list_body(PODS, image_pod()))

    monkeypatch.setattr(native, "diagnose_record", project)
    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(service(reader, req).collect(req, publications.append))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not any(value.findings for value in publications)


@pytest.mark.asyncio
async def test_stale_root_api_and_malformed_owner_references_are_not_membership(tmp_path):
    values = [owner(image_pod("bad"), REPLICASETS), owner(image_pod("ignored"), REPLICASETS)]
    values[0]["metadata"]["ownerReferences"] = "malformed"
    values[1]["metadata"]["ownerReferences"] = [None, {"controller": True, "uid": 7}]

    async def handler(req):
        if req.path.endswith("/replicasets/one"):
            return web.json_response(manifest(REPLICASETS))
        if req.path.endswith("/pods"):
            return web.json_response(list_body(PODS, *values))
        return web.json_response(list_body(EVENTS))

    req = request(ref(REPLICASETS))
    async with reader_fixture(tmp_path, handler) as reader:
        missing = await service(reader, req).collect(req, lambda _: None)
        result = await service(reader, req, (PODS, EVENTS, REPLICASETS)).collect(
            req, lambda _: None
        )
    assert missing.native_requests_used == 0 and missing.sources[0].status is Status.UNAVAILABLE
    assert not result.findings and any(s.omitted_findings == 1 for s in result.sources)


@pytest.mark.asyncio
async def test_generic_uid_event_enriches_explicit_image_condition_without_guessing_cause(tmp_path):
    async def handler(req):
        if req.path.endswith("/pods"):
            return web.json_response(list_body(PODS, image_pod()))
        value = event()
        value["reason"] = "BackOff"
        return web.json_response(list_body(EVENTS, value))

    req = request()
    async with reader_fixture(tmp_path, handler) as reader:
        result = await service(reader, req).collect(req, lambda _: None)
    assert len(result.findings) == 1 and result.findings[0].category is Category.IMAGE_PULL
    assert {evidence.source for evidence in result.findings[0].evidence} == {
        Kind.CONDITION,
        Kind.EVENT,
    }
    assert result.findings[0].source is Kind.CONDITION
    assert "not established" in result.findings[0].explanation
