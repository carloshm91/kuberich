"""Actual bounded GET/event reads, UID recreation, RBAC and owned cancellation."""

import asyncio
from dataclasses import replace

import pytest
from aiohttp import web

from kubetrol.domain.connections import HttpProblem
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.inspection import InspectionService, read_error
from tests.support.pods import pod
from tests.support.resources import collection, pod_resource, reader_fixture
from tests.unit.test_inspection import event


def make_service(reader, *, current=lambda: True, resource=None, name="api", uid="owned-api"):
    return InspectionService(
        reader.session,
        resource or pod_resource(),
        ResourceTarget(
            SessionIdentity(reader.session.context.name, 1), "", "pods", "team", name, uid
        ),
        AccessPolicy(True),
        current,
    )


@pytest.mark.asyncio
async def test_get_and_uid_associated_events_use_captured_client_and_namespace(tmp_path):
    calls = []

    async def handler(request):
        calls.append((request.path, request.query.copy()))
        return web.json_response(
            pod("api") if request.path.endswith("/api") else collection(event().manifest)
        )

    async with reader_fixture(tmp_path, handler) as reader:
        result = await make_service(reader).load()
        assert "BackOff" in result.documents.events and result.events_error is None
        assert [path for path, _ in calls] == [
            "/api/v1/namespaces/team/pods/api",
            "/api/v1/namespaces/team/events",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 503])
async def test_event_errors_preserve_yaml_and_describe_and_identify_problem(tmp_path, status):
    async def handler(request):
        return (
            web.json_response(pod("api"))
            if request.path.endswith("/api")
            else web.Response(status=status)
        )

    async with reader_fixture(tmp_path, handler) as reader:
        result = await make_service(reader).load()
        assert "apiVersion: v1" in result.documents.yaml
        assert str(status) in result.events_error
        assert "Permission denied" in result.events_error if status == 403 else True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_resource_read_failures_do_not_return_stale_snapshot(tmp_path, status):
    async def handler(request):
        return web.Response(status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem) as error:
            await make_service(reader).load()
        assert str(status) in read_error(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "initial",
        "after-get",
        "after-events",
        "recreated",
        "wrong-name",
        "mismatch",
        "no-get",
        "unsafe-name",
    ],
)
async def test_stale_or_mismatched_target_fails_closed(tmp_path, kind):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if request.path.endswith("/events"):
            return web.json_response(collection())
        return web.json_response(
            pod(
                "other" if kind == "wrong-name" else "api",
                uid="new" if kind == "recreated" else "owned-api",
            )
        )

    def current():
        return not (
            kind == "initial"
            or (kind == "after-get" and calls >= 1)
            or (kind == "after-events" and calls >= 2)
        )

    resource = pod_resource()
    if kind == "mismatch":
        resource = replace(resource, name="other")
    if kind == "no-get":
        resource = replace(resource, verbs=frozenset({"list"}))
    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(AppError):
            await make_service(
                reader,
                current=current,
                resource=resource,
                name="bad/name" if kind == "unsafe-name" else "api",
            ).load()
        if kind in {"initial", "mismatch", "no-get", "unsafe-name"}:
            assert calls == 0


@pytest.mark.asyncio
async def test_cancelled_read_closes_owned_request_without_reading_events(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request.path)
        started.set()
        await release.wait()
        return web.json_response(pod("api"))

    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(make_service(reader).load())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert calls == ["/api/v1/namespaces/team/pods/api"]


@pytest.mark.asyncio
async def test_cancellation_drains_serializer_thread_and_stale_result_is_discarded(
    tmp_path, monkeypatch
):
    import threading

    from kubetrol.services import inspection
    from tests.support.workspace import wait_for

    started, release, ended = (threading.Event() for _ in range(3))
    original = inspection.inspection_documents

    def controlled(*args):
        started.set()
        try:
            assert release.wait(5)
            return original(*args)
        finally:
            ended.set()

    monkeypatch.setattr(inspection, "inspection_documents", controlled)

    async def handler(request):
        return web.json_response(pod("api") if request.path.endswith("/api") else collection())

    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(make_service(reader).load())
        await wait_for(started.is_set)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not ended.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ended.is_set()
        valid = True

        def delayed(*args):
            nonlocal valid
            valid = False
            return original(*args)

        monkeypatch.setattr(inspection, "inspection_documents", delayed)
        with pytest.raises(AppError, match="stale"):
            await make_service(reader, current=lambda: valid).load()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["context", "namespace"])
async def test_wrong_context_or_missing_namespace_is_rejected_before_io(tmp_path, kind):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(pod("api"))

    async with reader_fixture(tmp_path, handler) as reader:
        service = make_service(reader)
        service.target = replace(
            service.target,
            session=SessionIdentity("other-context", 1)
            if kind == "context"
            else service.target.session,
            namespace=None if kind == "namespace" else "team",
        )
        with pytest.raises(AppError, match="context" if kind == "context" else "namespace"):
            await service.load()
        assert calls == []
