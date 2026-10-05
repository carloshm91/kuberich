"""Actual HTTP watch framing, continuity, recovery, backpressure and cancellation."""

import asyncio
import json
import sys
import threading
import weakref
from contextlib import aclosing
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kubetrol.domain.resources import api_resource
from kubetrol.domain.watches import EventType, SyncStatus
from kubetrol.errors import AppError
from kubetrol.services import watches
from kubetrol.services.watches import ListWatch
from tests.support.connections import catalog_fixture, certificate, fake_api
from tests.support.resources import collection, descriptor, item, pod_resource, reader_fixture
from tests.support.watches import Clock, bookmark, error_event, event, frame


class Finished(Exception):
    """Own test consumer stops after its intended evidence, without a real cluster."""


async def collect(updates, update) -> None:
    updates.append(update)


def follower(reader, clock: Clock) -> ListWatch:
    return ListWatch(reader, sleep=clock.sleep, monotonic=clock.monotonic, jitter=lambda: 0.5)


@pytest.mark.asyncio
async def test_list_watch_gap_bookmark_duplicates_and_recreation_resume_last_checkpoint(
    tmp_path: Path,
) -> None:
    requests, updates = [], []
    clock = Clock()

    async def handler(request):
        assert request.path == "/api/v1/namespaces/team/pods"
        assert request.headers["Authorization"] == "Bearer synthetic"
        assert request.headers["Accept-Encoding"] == "identity"
        requests.append(dict(request.query))
        if "watch" not in request.query:
            return web.json_response(collection(rv="list-opaque"))
        if len(requests) == 2:
            assert request.query["resourceVersion"] == "list-opaque"
            assert request.query["allowWatchBookmarks"] == "true"
            assert request.query["timeoutSeconds"] == "5"
            values = [
                event(uid="old", version="z-first"),
                event("MODIFIED", uid="old", version="a-next"),
                bookmark("opaque-bookmark"),
                event("MODIFIED", uid="old", version="a-next"),
                event("DELETED", uid="old", version="delete"),
                event(uid="new", version="new-uid"),
                event("DELETED", uid="old", version="late-delete"),
            ]
            return web.Response(body=b"\n" + b"".join(frame(value) for value in values))
        assert request.query["resourceVersion"] == "late-delete"
        return web.Response(status=403, text="opaque-sensitive")

    async with reader_fixture(tmp_path, handler) as reader:
        before = (tmp_path / "fixture-config").read_bytes()
        with pytest.raises(HttpProblem) as problem:
            await follower(reader, clock).run(
                pod_resource(), "team", lambda update: collect(updates, update)
            )
        assert problem.value.status == 403
        assert (tmp_path / "fixture-config").read_bytes() == before
    assert len(requests) == 3 and clock.delays == [0.25]
    changed = [update for update in updates if update.event is not None]
    assert [update.event.type for update in changed] == [
        EventType.ADDED,
        EventType.MODIFIED,
        EventType.BOOKMARK,
        EventType.DELETED,
        EventType.ADDED,
        EventType.DELETED,
    ]
    assert changed[0].snapshot.items[0].uid == "old"
    assert changed[-1].snapshot.items[0].uid == "new"
    assert updates[-1].status is SyncStatus.FAILED and updates[-1].snapshot.items[0].uid == "new"
    assert "opaque-sensitive" not in str(problem.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("in_stream", [False, True])
async def test_expiration_clears_invalid_cache_and_relists_before_reopening(
    tmp_path: Path, in_stream: bool
) -> None:
    lists = 0
    versions, updates = [], []
    clock = Clock()

    async def handler(request):
        nonlocal lists
        if "watch" not in request.query:
            lists += 1
            return web.json_response(
                collection(item(uid="old" if lists == 1 else "new"), rv=f"list-{lists}")
            )
        versions.append(request.query["resourceVersion"])
        if len(versions) == 1:
            return (
                web.Response(body=frame(error_event(410)))
                if in_stream
                else web.Response(status=410)
            )
        return web.Response(status=403)

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(
                pod_resource(), "team", lambda update: collect(updates, update)
            )
    assert lists == 2 and versions == ["list-1", "list-2"]
    invalidated = next(update for update in updates if update.status is SyncStatus.RELISTING)
    assert invalidated.snapshot is None and invalidated.retry_in == 0.25
    snapshots = [update.snapshot for update in updates if update.status is SyncStatus.SNAPSHOT]
    assert [snapshot.items[0].uid for snapshot in snapshots] == ["old", "new"]


@pytest.mark.asyncio
@pytest.mark.parametrize("in_stream", [False, True])
async def test_repeated_expiration_uses_backoff_instead_of_hot_relist_loop(
    tmp_path: Path, in_stream: bool
) -> None:
    updates, clock = [], Clock()

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        if len(clock.delays) == 3:
            return web.Response(status=403)
        return web.Response(body=frame(error_event(410))) if in_stream else web.Response(status=410)

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(
                pod_resource(), None, lambda update: collect(updates, update)
            )
    assert clock.delays == [0.25, 0.5, 1]
    assert updates[-1].snapshot is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["empty", "unavailable", "truncated", "list_unavailable"])
async def test_retries_retain_checkpoint_and_exponentially_bound_failures(
    tmp_path: Path, mode: str
) -> None:
    lists, queries = [], []
    clock = Clock()

    async def handler(request):
        if "watch" not in request.query:
            lists.append(True)
            if mode == "list_unavailable" and len(clock.delays) < 4:
                return web.Response(status=503)
            return web.json_response(collection(rv="exact-opaque"))
        queries.append(request.query["resourceVersion"])
        if len(clock.delays) == 4:
            return web.Response(status=403)
        if mode == "unavailable":
            return web.Response(status=503)
        if mode == "truncated":
            return web.Response(body=b'{"type":"ADDED","object":')
        return web.Response(body=b"")

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(pod_resource(), None, lambda update: asyncio.sleep(0))
    assert clock.delays == [0.25, 0.5, 1, 2]
    assert set(queries) == {"exact-opaque"}
    assert len(lists) == (5 if mode == "list_unavailable" else 1)


@pytest.mark.asyncio
async def test_long_healthy_stream_resets_backoff_even_without_bookmarks(tmp_path: Path) -> None:
    clock = Clock()

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        if len(clock.delays) == 3:
            return web.Response(status=403)
        if len(clock.delays) == 2:
            clock.now += 2
        return web.Response(body=b"")

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(pod_resource(), None, lambda update: asyncio.sleep(0))
    assert clock.delays == [0.25, 0.5, 0.25]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delay,expected",
    [
        (None, 0.25),
        ("3", 3),
        ("99999999", 300),
        ("-1", 0.25),
        ("1.5", 0.25),
        ("bad", 0.25),
        ("é", 0.25),
    ],
)
async def test_retry_after_header_is_bounded_and_untrusted(
    tmp_path: Path, delay: str | None, expected: float
) -> None:
    clock = Clock()

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        if clock.delays:
            return web.Response(status=403)
        return web.Response(status=429, headers={"Retry-After": delay} if delay is not None else {})

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(pod_resource(), None, lambda update: asyncio.sleep(0))
    assert clock.delays == [expected]


@pytest.mark.asyncio
async def test_in_stream_retry_after_status_is_honored(tmp_path: Path) -> None:
    clock = Clock()

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        return (
            web.Response(status=403)
            if clock.delays
            else web.Response(body=frame(error_event(429, 7)))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(pod_resource(), None, lambda update: asyncio.sleep(0))
    assert clock.delays == [7]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,in_stream", [(401, False), (403, False), (404, False), (403, True), (401, True)]
)
async def test_terminal_auth_permission_and_missing_resource_failures_never_retry(
    tmp_path: Path, status: int, in_stream: bool
) -> None:
    calls, clock, updates = [], Clock(), []

    async def handler(request):
        calls.append(dict(request.query))
        if "watch" not in request.query:
            return web.json_response(collection(item()))
        return (
            web.Response(body=frame(error_event(status)))
            if in_stream
            else web.Response(status=status, text="private")
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem) as problem:
            await follower(reader, clock).run(
                pod_resource(), None, lambda update: collect(updates, update)
            )
        assert problem.value.status == status
    assert len(calls) == 2 and clock.delays == []
    assert updates[-1].status is SyncStatus.FAILED and len(updates[-1].snapshot.items) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [b"not-json\n", b"[]\n", b'{"value":NaN}\n', b"\xff\n", frame({"type": "WRONG", "object": {}})],
)
async def test_invalid_frames_stop_without_showing_empty_success(
    tmp_path: Path, payload: bytes
) -> None:
    updates, clock = [], Clock()

    async def handler(request):
        return (
            web.Response(body=payload)
            if "watch" in request.query
            else web.json_response(collection(item()))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as problem:
            await follower(reader, clock).run(
                pod_resource(), None, lambda update: collect(updates, update)
            )
        assert problem.value.state is ConnectionState.API_ERROR
    assert clock.delays == [] and updates[-1].snapshot.items[0].uid == "owned-one"


@pytest.mark.asyncio
async def test_live_state_bound_failure_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kubetrol.domain import watches as domain

    monkeypatch.setattr(domain, "MAX_RESOURCE_ITEMS", 1)
    updates = []

    async def handler(request):
        return (
            web.Response(body=frame(event(name="second")))
            if "watch" in request.query
            else web.json_response(collection(item()))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as problem:
            await ListWatch(reader).run(
                pod_resource(), "team", lambda update: collect(updates, update)
            )
        assert problem.value.state is ConnectionState.API_ERROR
    assert len(updates[-1].snapshot.items) == 1


@pytest.mark.asyncio
async def test_zero_list_version_cannot_start_a_watch_with_any_state_semantics(
    tmp_path: Path,
) -> None:
    updates = []

    async def handler(request):
        assert "watch" not in request.query
        return web.json_response(collection(rv="0"))

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as problem:
            await ListWatch(reader).run(
                pod_resource(), None, lambda update: collect(updates, update)
            )
        assert problem.value.state is ConnectionState.API_ERROR
    assert updates[-1].status is SyncStatus.FAILED and updates[-1].snapshot is None


@pytest.mark.asyncio
@pytest.mark.parametrize("with_newline", [False, True])
async def test_watch_frame_limit_rejects_oversized_complete_or_unfinished_event(
    tmp_path: Path, with_newline: bool
) -> None:
    async def handler(request):
        return web.Response(body=b"x" * 129 + (b"\n" if with_newline else b""))

    async with reader_fixture(tmp_path, handler) as reader:
        stream = reader.session.watch_json("/api/v1/pods", "opaque", max_bytes=128)
        async with aclosing(stream):
            assert await anext(stream) is None
            with pytest.raises(ConnectionProblem) as problem:
                await anext(stream)
            assert problem.value.state is ConnectionState.API_ERROR


@pytest.mark.asyncio
async def test_frames_split_across_chunks_decode_only_after_complete_line(tmp_path: Path) -> None:
    value = event()
    value["object"]["metadata"]["annotations"] = {"large": "🚀" * 5000}
    encoded = json.dumps(value, ensure_ascii=False).encode() + b"\n"

    async def handler(request):
        response = web.StreamResponse()
        await response.prepare(request)
        for offset in range(0, len(encoded), 101):
            await response.write(encoded[offset : offset + 101])
        await response.write_eof()
        return response

    async with (
        reader_fixture(tmp_path, handler) as reader,
        aclosing(reader.session.watch_json("/api/v1/pods", "opaque")) as stream,
    ):
        assert await anext(stream) is None
        assert await anext(stream) == value
        with pytest.raises(StopAsyncIteration):
            await anext(stream)


@pytest.mark.asyncio
async def test_slow_consumer_has_no_background_event_queue_and_owned_stream_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original = watches.watch_event

    def observed(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(watches, "watch_event", observed)

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        return web.Response(
            body=b"".join(
                frame(event(name=str(number), version=str(number))) for number in range(100)
            )
        )

    async def sink(update):
        if update.event:
            assert calls == 1
            await asyncio.sleep(0.03)
            assert calls == 1
            raise Finished

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(Finished):
            await ListWatch(reader).run(pod_resource(), None, sink)
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["read", "sink", "backoff"])
async def test_cancellation_owns_stream_and_waits_for_loop_cleanup(
    tmp_path: Path, when: str
) -> None:
    waiting = asyncio.Event()

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        response = web.StreamResponse()
        await response.prepare(request)
        if when == "backoff":
            await response.write_eof()
        else:
            if when == "sink":
                await response.write(frame(event()))
            else:
                waiting.set()
            await asyncio.sleep(5)
        return response

    async def sink(update):
        if when == "sink" and update.event:
            waiting.set()
            await asyncio.Event().wait()

    async def sleep(delay):
        assert delay >= 0.2
        waiting.set()
        await asyncio.Event().wait()

    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(ListWatch(reader, sleep=sleep).run(pod_resource(), None, sink))
        await asyncio.wait_for(waiting.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
async def test_cancel_awaits_owned_event_normalization_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    original = watches.watch_event

    def delayed(*args):
        entered.set()
        assert released.wait(timeout=3)
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(watches, "watch_event", delayed)

    async def handler(request):
        return (
            web.Response(body=frame(event()))
            if "watch" in request.query
            else web.json_response(collection())
        )

    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(
            ListWatch(reader).run(pod_resource(), None, lambda update: asyncio.sleep(0))
        )
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (
            finished.is_set()
            and not reader.session.api.rest_client.pool_manager.connector._acquired
        )


@pytest.mark.asyncio
async def test_watch_timeout_resumes_version_after_backoff(tmp_path: Path) -> None:
    count, updates = 0, []
    clock = Clock()

    async def handler(request):
        nonlocal count
        if "watch" not in request.query:
            return web.json_response(collection(rv="kept-version"))
        count += 1
        assert request.query["resourceVersion"] == "kept-version"
        if count == 2:
            return web.Response(status=403)
        response = web.StreamResponse()
        await response.prepare(request)
        await asyncio.sleep(1)
        return response

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(
                pod_resource(), None, lambda update: collect(updates, update)
            )
    assert clock.delays == [0.25]
    retry = next(update for update in updates if update.status is SyncStatus.RETRYING)
    assert retry.problem.state is ConnectionState.TIMEOUT


@pytest.mark.asyncio
async def test_closed_session_watch_is_disconnected_without_fallback(tmp_path: Path) -> None:
    async def handler(request):
        return web.Response(body=b"")

    async with reader_fixture(tmp_path, handler) as reader:
        await reader.session.close()
        async with aclosing(reader.session.watch_json("/api/v1/pods", "opaque")) as stream:
            with pytest.raises(ConnectionProblem) as problem:
                await anext(stream)
            assert problem.value.state is ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_watch_tls_verification_failure_is_terminal(tmp_path: Path) -> None:
    tls, _materials = certificate(tmp_path)

    async def handler(request):
        return web.Response(body=b"")

    async with fake_api(handler, tls=tls) as url:
        session = KubernetesSession(catalog_fixture(tmp_path, url).select("kubetrol-test-one"), 1)
        try:
            await session.open()
            async with aclosing(session.watch_json("/api/v1/namespaces", "opaque")) as stream:
                with pytest.raises(ConnectionProblem) as problem:
                    await anext(stream)
                assert problem.value.state is ConnectionState.TLS_ERROR
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_unreachable_watch_has_a_safe_retryable_error(tmp_path: Path) -> None:
    async def handler(request):
        return web.Response(body=b"")

    async with fake_api(handler) as url:
        session = KubernetesSession(catalog_fixture(tmp_path, url).select("kubetrol-test-one"), 1)
        await session.open()
    try:
        async with aclosing(session.watch_json("/api/v1/namespaces", "opaque")) as stream:
            with pytest.raises(ConnectionProblem) as problem:
                await anext(stream)
            assert problem.value.state is ConnectionState.UNREACHABLE
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_unsupported_watch_and_invalid_scope_fail_before_network(tmp_path: Path) -> None:
    calls = []

    async def handler(request):
        calls.append(True)
        return web.Response(body=b"")

    async with reader_fixture(tmp_path, handler) as reader:
        resource = api_resource("v1", {**descriptor(), "verbs": ["list"]})
        with pytest.raises(AppError, match="watch support"):
            await ListWatch(reader).run(resource, None, lambda update: asyncio.sleep(0))
        with pytest.raises(AppError, match="Namespace"):
            await ListWatch(reader).run(
                pod_resource(), "../escape", lambda update: asyncio.sleep(0)
            )
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected_twice", [False, True])
async def test_watch_401_refreshes_exec_token_once_and_owns_each_response(
    tmp_path: Path, rejected_twice: bool
) -> None:
    script = tmp_path / "helper.py"
    script.write_text("""import json
from pathlib import Path
path=Path('calls')
calls=path.read_text()+'x' if path.exists() else 'x'
path.write_text(calls)
print(json.dumps({'apiVersion':'client.authentication.k8s.io/v1','kind':'ExecCredential','status':{'token':calls}}))
""")
    user = {
        "exec": {
            "command": sys.executable,
            "args": ["helper.py"],
            "apiVersion": "client.authentication.k8s.io/v1",
            "interactiveMode": "Never",
        }
    }
    headers = []

    async def handler(request):
        headers.append(request.headers["Authorization"])
        if len(headers) == 1 or rejected_twice:
            return web.Response(status=401)
        return web.Response(body=frame(bookmark("ready")))

    async with (
        reader_fixture(tmp_path, handler, user=user) as reader,
        aclosing(reader.session.watch_json("/api/v1/pods", "opaque")) as stream,
    ):
        if rejected_twice:
            with pytest.raises(HttpProblem) as problem:
                await anext(stream)
            assert problem.value.status == 401
        else:
            assert await anext(stream) is None
            assert await anext(stream) == bookmark("ready")
    assert headers == ["Bearer x", "Bearer xx"]
    assert (tmp_path / "calls").read_text() == "xx"


@pytest.mark.asyncio
async def test_consumer_connection_error_is_not_retried_as_transport_failure(
    tmp_path: Path,
) -> None:
    clock = Clock()
    problem = ConnectionProblem(ConnectionState.UNREACHABLE, "owned consumer failure")

    async def handler(request):
        return (
            web.Response(body=frame(event()))
            if "watch" in request.query
            else web.json_response(collection())
        )

    async def sink(update):
        if update.event:
            raise problem

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as caught:
            await follower(reader, clock).run(pod_resource(), None, sink)
        assert caught.value is problem and clock.delays == []
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["resources", "namespaces"])
async def test_total_snapshot_deadline_spans_multiple_individually_fast_requests(
    tmp_path: Path, operation: str
) -> None:
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        await asyncio.sleep(0.06)
        return web.json_response(collection(token="next-page" if count == 1 else ""))

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:
        with pytest.raises(ConnectionProblem) as problem:
            if operation == "resources":
                await reader.list(pod_resource())
            else:
                await reader.session.namespaces()
        assert problem.value.state is ConnectionState.TIMEOUT
        assert "timed out" in str(problem.value)


@pytest.mark.asyncio
async def test_deleted_initial_records_are_released_when_consumer_keeps_no_history(
    tmp_path: Path,
) -> None:
    initial = None

    async def handler(request):
        return (
            web.Response(body=frame(event("DELETED", version="deletion")))
            if "watch" in request.query
            else web.json_response(collection(item()))
        )

    async def sink(update):
        nonlocal initial
        if update.status is SyncStatus.SNAPSHOT:
            initial = weakref.ref(update.snapshot.items[0])
        if update.event:
            assert initial is not None and initial() is None
            assert not update.snapshot.items
            raise Finished

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(Finished):
            await ListWatch(reader).run(pod_resource(), None, sink)
