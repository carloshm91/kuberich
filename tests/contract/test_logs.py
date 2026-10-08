"""Real HTTP log framing, identity checks, stream ownership and backpressure."""

import asyncio
from dataclasses import replace

import aiohttp
import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionProblem, ConnectionState
from kuberich.domain.logs import LogBuffer, LogOptions
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.logs import LogStream
from tests.support.pods import pod
from tests.support.resources import reader_fixture
from tests.support.workspace import wait_for


def manifest(*, uid="owned-api", name="api"):
    value = pod(name, uid=uid)
    value["spec"]["initContainers"] = [{"name": "init"}]
    return value


def stream_for(reader, *, container="app", current=lambda: True):
    return LogStream(
        reader.session,
        ResourceTarget(
            SessionIdentity(reader.session.context.name, 1),
            "",
            "pods",
            "team",
            "api",
            "owned-api",
            container,
        ),
        AccessPolicy(True),
        current,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("container,previous", [("app", False), ("init", True)])
async def test_stream_selected_container_options_split_unicode_and_normal_eof(
    tmp_path, container, previous
):
    queries, gets = [], []

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer synthetic"
        if not request.path.endswith("/log"):
            gets.append(request.path)
            return web.json_response(manifest())
        # API routing negotiates Kubernetes serializers before returning text.
        # A narrow plaintext Accept caused a real kube-apiserver 406.
        if request.headers.get("Accept") not in {"*/*", "application/json"}:
            return web.Response(status=406)
        queries.append(dict(request.query))
        response = web.StreamResponse()
        await response.prepare(request)
        for value in [b"first\n\xe4", b"\xbd\xa0", b"\xe5\xa5\xbd\npartial"]:
            await response.write(value)
        await response.write_eof()
        return response

    async with reader_fixture(tmp_path, handler) as reader:
        output = []

        async def sink(line):
            output.append(line)

        count = await stream_for(reader, container=container).run(
            LogOptions(follow=False, previous=previous, since_seconds=30), sink
        )
        assert count == 3 and [line.text for line in output] == ["first", "你好", "partial"]
        assert len(gets) == 2 and queries == [
            {
                "container": container,
                "follow": "false",
                "previous": str(previous).lower(),
                "timestamps": "true",
                "tailLines": "1000",
                "sinceSeconds": "30",
            }
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,previous,expected",
    [
        (403, False, "Permission denied"),
        (404, False, "deleted"),
        (400, True, "Previous"),
        (500, False, "HTTP 500"),
        (401, False, "credentials"),
        (400, False, "may not have started"),
    ],
)
async def test_clear_safe_rbac_deleted_previous_and_other_errors(
    tmp_path, status, previous, expected
):
    async def handler(request):
        return (
            web.Response(status=status, text="synthetic-hidden-server-body")
            if request.path.endswith("/log")
            else web.json_response(manifest())
        )

    async with reader_fixture(tmp_path, handler) as reader:

        async def sink(line):
            pytest.fail("Failed requests cannot emit output")

        with pytest.raises(ConnectionProblem, match=expected) as problem:
            await stream_for(reader).run(LogOptions(previous=previous), sink)
        assert "synthetic-hidden-server-body" not in str(problem.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "initial",
        "after-get",
        "after-open",
        "replacement-before-open",
        "replacement-after-open",
        "wrong-name",
        "container",
        "context",
        "namespace",
        "resource",
    ],
)
async def test_invalid_target_or_uid_recreation_never_emits_other_pod_logs(tmp_path, kind):
    reads = 0

    async def handler(request):
        nonlocal reads
        if request.path.endswith("/log"):
            return web.Response(body=b"replacement-must-not-display\n")
        reads += 1
        return web.json_response(
            manifest(
                uid="new"
                if kind == "replacement-before-open"
                or (kind == "replacement-after-open" and reads > 1)
                else "owned-api",
                name="other" if kind == "wrong-name" else "api",
            )
        )

    valid = True

    def current():
        return valid and not (
            kind == "initial"
            or (kind == "after-get" and reads >= 1)
            or (kind == "after-open" and reads >= 2)
        )

    async with reader_fixture(tmp_path, handler) as reader:
        service = stream_for(
            reader, container="missing" if kind == "container" else "app", current=current
        )
        if kind == "context":
            service.target = replace(service.target, session=SessionIdentity("other", 1))
        if kind == "namespace":
            service.target = replace(service.target, namespace=None)
        if kind == "resource":
            service.target = replace(service.target, resource="secrets")

        async def sink(line):
            pytest.fail("Stale target cannot emit output")

        with pytest.raises(AppError):
            await service.run(LogOptions(), sink)


@pytest.mark.asyncio
async def test_quiet_follow_survives_request_timeout_and_cancel_closes_connection(tmp_path):
    opened, closed = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if not request.path.endswith("/log"):
            return web.json_response(manifest())
        response = web.StreamResponse()
        await response.prepare(request)
        opened.set()
        try:
            await wait_for(lambda: request.transport is None or request.transport.is_closing())
        finally:
            closed.set()
        return response

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:

        async def sink(line):
            pytest.fail("Quiet follow has no output")

        task = asyncio.create_task(stream_for(reader).run(LogOptions(), sink))
        await opened.wait()
        await asyncio.sleep(0.25)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await closed.wait()


@pytest.mark.asyncio
async def test_consumer_backpressure_cancellation_and_retention_are_bounded(tmp_path):
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(request):
        if not request.path.endswith("/log"):
            return web.json_response(manifest())
        response = web.StreamResponse()
        await response.prepare(request)
        try:
            await response.write(b"line\n" * 5000)
            await wait_for(lambda: request.transport is None or request.transport.is_closing())
        finally:
            closed.set()
        return response

    async with reader_fixture(tmp_path, handler) as reader:
        buffer = LogBuffer(max_lines=10, max_bytes=100)

        async def sink(line):
            buffer.append(line)
            entered.set()
            await release.wait()

        task = asyncio.create_task(stream_for(reader).run(LogOptions(), sink))
        await entered.wait()
        await asyncio.sleep(0.02)
        assert len(buffer.lines) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await closed.wait()


@pytest.mark.asyncio
async def test_abrupt_disconnect_reports_failure_without_automatic_replay(tmp_path):
    requests = []

    async def handler(request):
        requests.append(request.path)
        if not request.path.endswith("/log"):
            return web.json_response(manifest())
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(b"before\n")
        request.transport.abort()
        return response

    async with reader_fixture(tmp_path, handler) as reader:
        output = []

        async def sink(line):
            output.append(line)

        with pytest.raises(ConnectionProblem, match="disconnected"):
            await stream_for(reader).run(LogOptions(), sink)
        assert sum(path.endswith("/log") for path in requests) == 1


@pytest.mark.asyncio
async def test_snapshot_and_header_timeout_are_explicit(tmp_path):
    release = asyncio.Event()

    async def handler(request):
        if not request.path.endswith("/log"):
            return web.json_response(manifest())
        await release.wait()
        return web.Response(body=b"late\n")

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:

        async def sink(line):
            pytest.fail("Timed-out stream cannot emit output")

        with pytest.raises(ConnectionProblem) as problem:
            await stream_for(reader).run(LogOptions(follow=False), sink)
        assert problem.value.state is ConnectionState.TIMEOUT
        release.set()


@pytest.mark.asyncio
async def test_scope_changes_during_consumer_work_reject_remaining_lines_and_close(tmp_path):
    valid = True
    closed = asyncio.Event()

    async def handler(request):
        if not request.path.endswith("/log"):
            return web.json_response(manifest())
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(b"first\nsecond\n")
        await wait_for(lambda: request.transport is None or request.transport.is_closing())
        closed.set()
        return response

    async with reader_fixture(tmp_path, handler) as reader:
        output = []

        async def sink(line):
            nonlocal valid
            output.append(line.text)
            valid = False

        with pytest.raises(AppError, match="stale"):
            await stream_for(reader, current=lambda: valid).run(LogOptions(), sink)
        assert output == ["first"]
        await closed.wait()


@pytest.mark.asyncio
async def test_tls_failure_is_safe_and_does_not_include_certificate_or_url_credentials(
    tmp_path, monkeypatch
):
    async def handler(request):
        return web.json_response(manifest())

    async with reader_fixture(tmp_path, handler) as reader:

        async def broken(*args, **kwargs):
            raise aiohttp.ClientSSLError(None, OSError("synthetic-sensitive-tls"))

        monkeypatch.setattr(reader.session.api.rest_client.pool_manager, "get", broken)
        with pytest.raises(ConnectionProblem) as problem:
            async for _ in reader.session.log_bytes(
                "/api/v1/namespaces/team/pods/api/log", {}, follow=True
            ):
                pytest.fail("TLS failure cannot emit chunks")
        assert problem.value.state is ConnectionState.TLS_ERROR
        assert "synthetic-sensitive-tls" not in str(problem.value)
