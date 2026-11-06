"""Actual HTTP watch framing, continuity, recovery, backpressure and cancellation."""

import asyncio
import concurrent.futures
import contextvars
import json
import sys
import threading
import weakref
from contextlib import aclosing, asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import ClientSession, ClientTimeout, web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.resources import api_resource
from kuberich.domain.watches import EventType, SyncStatus
from kuberich.errors import AppError
from kuberich.services import watches
from kuberich.services.watches import ListWatch
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
    opened = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        if "watch" not in request.query:
            return web.json_response(collection())
        calls += 1
        if calls == 5:
            return web.Response(status=403)
        if calls == 4:
            return web.Response(status=503)
        if calls == 3:
            opened.clear()
            response = web.StreamResponse()
            await response.prepare(request)
            await opened.wait()
            clock.now += 2
            await response.write_eof()
            return response
        return web.Response(body=b"")

    async def sink(update):
        if update.status is SyncStatus.LIVE:
            opened.set()

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem):
            await follower(reader, clock).run(pod_resource(), None, sink)
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
async def test_live_state_bound_keeps_a_healthy_explicit_incomplete_watch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kuberich.domain import watches as domain

    monkeypatch.setattr(domain, "MAX_RESOURCE_ITEMS", 1)
    updates = []

    class ObservedLimit(Exception):
        pass

    async def observe(update):
        updates.append(update)
        if update.snapshot is not None and update.snapshot.collection.limited:
            raise ObservedLimit

    async def handler(request):
        return (
            web.Response(body=frame(event(name="second")))
            if "watch" in request.query
            else web.json_response(collection(item()))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ObservedLimit):
            await ListWatch(reader).run(pod_resource(), "team", observe)
    assert len(updates[-1].snapshot.items) == 1
    assert updates[-1].status is SyncStatus.LIVE and updates[-1].problem is None
    assert not updates[-1].snapshot.collection.complete


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
        while request.transport is not None and not request.transport.is_closing():
            await asyncio.sleep(0.01)
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
@pytest.mark.parametrize("checkpoint", [False, True])
@pytest.mark.parametrize("slow_initial_list", [False, True])
async def test_quiet_watch_outlives_request_deadline_and_renews_without_stale_state(
    tmp_path: Path, checkpoint: bool, slow_initial_list: bool
) -> None:
    lists, versions, updates, clock = [], [], [], Clock()
    release_initial_list, drained = asyncio.Event(), asyncio.Event()
    baseline = None
    active = 0

    async def handler(request):
        nonlocal active
        active += 1
        drained.clear()
        try:
            if "watch" not in request.query:
                lists.append(True)
                if slow_initial_list and len(lists) == 1:
                    # Release only after the finite LIST deadline has actually
                    # expired, independently of host scheduling speed.
                    await release_initial_list.wait()
                return web.json_response(collection(item(), rv="initial-checkpoint"))
            versions.append(request.query["resourceVersion"])
            assert request.query["timeoutSeconds"] == "1"
            response = web.StreamResponse()
            await response.prepare(request)
            if checkpoint and len(versions) == 1:
                await response.write(frame(bookmark("renewed-checkpoint")))
            if len(versions) == 3:
                while request.transport is not None and not request.transport.is_closing():
                    await asyncio.sleep(0.01)
            else:
                await asyncio.sleep(int(request.query["timeoutSeconds"]))
                await response.write_eof()
            return response
        finally:
            active -= 1
            if active == 0:
                drained.set()

    async def sink(update):
        nonlocal baseline
        if update.status is SyncStatus.SNAPSHOT:
            assert baseline is None, "Quiet watch unexpectedly relisted after its snapshot."
            assert versions == []
            # Watch establishment and every renewal remain inside the observed
            # interval; finite cold-LIST failures precede that contract.
            baseline = len(lists), tuple(clock.delays), len(updates)
        updates.append(update)
        if update.status is SyncStatus.RETRYING and baseline is None:
            assert update.problem.state is ConnectionState.TIMEOUT
            assert update.snapshot is None
            if lists:
                release_initial_list.set()
        if update.status is SyncStatus.LIVE and len(versions) == 3:
            raise Finished

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:
        pool = reader.session.api.rest_client.pool_manager
        before = (tmp_path / "fixture-config").read_bytes()
        async with asyncio.timeout(5):
            with pytest.raises(Finished):
                await ListWatch(reader, sleep=clock.sleep).run(pod_resource(), "team", sink)
            await drained.wait()
        assert active == 0 and not pool.connector._acquired
        assert (tmp_path / "fixture-config").read_bytes() == before
    assert pool.closed and reader.session.api is None
    assert versions == [
        "initial-checkpoint",
        "renewed-checkpoint" if checkpoint else "initial-checkpoint",
        "renewed-checkpoint" if checkpoint else "initial-checkpoint",
    ]
    assert baseline is not None
    list_count, startup_delays, snapshot_index = baseline
    assert len(lists) == list_count, "Quiet watch unexpectedly relisted after its snapshot."
    assert tuple(clock.delays) == startup_delays, "Quiet watch unexpectedly backed off."
    startup = updates[1:snapshot_index]
    assert updates[0].status is SyncStatus.LOADING
    assert all(
        update.status is SyncStatus.RETRYING
        and update.problem.state is ConnectionState.TIMEOUT
        and update.snapshot is None
        for update in startup
    )
    assert len(startup) == len(startup_delays)
    if slow_initial_list:
        assert list_count >= 2 and startup
    assert updates[snapshot_index].status is SyncStatus.SNAPSHOT
    assert all(update.status is SyncStatus.LIVE for update in updates[snapshot_index + 1 :])
    assert updates[-1].snapshot.items[0].uid == "owned-one"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,reason",
    [(503, "Quiet watch unexpectedly backed off"), (410, "Quiet watch unexpectedly relisted")],
)
async def test_quiet_watch_contract_rejects_failure_after_establishment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, reason: str
) -> None:
    original_fixture = reader_fixture
    watch_requests = 0
    cleanup = []

    @asynccontextmanager
    async def failing_fixture(directory, handler, *, timeout):
        async def fail_renewal(request):
            nonlocal watch_requests
            if "watch" in request.query:
                watch_requests += 1
                if watch_requests == 2:
                    return web.Response(status=status)
            return await handler(request)

        try:
            async with original_fixture(directory, fail_renewal, timeout=timeout) as reader:
                pool = reader.session.api.rest_client.pool_manager
                yield reader
        finally:
            cleanup.append((pool.closed, reader.session.api is None))

    monkeypatch.setattr(sys.modules[__name__], "reader_fixture", failing_fixture)
    with pytest.raises(AssertionError, match=reason):
        await test_quiet_watch_outlives_request_deadline_and_renews_without_stale_state(
            tmp_path, checkpoint=True, slow_initial_list=True
        )
    assert watch_requests == (4 if status == 503 else 2)
    assert cleanup == [(True, True)]


@pytest.mark.asyncio
async def test_established_idle_client_timeout_resets_previous_failure_backoff(tmp_path: Path):
    calls, lists, active, updates, clock = 0, 0, 0, [], Clock()

    async def handler(request):
        nonlocal calls, lists, active
        active += 1
        try:
            if "watch" not in request.query:
                lists += 1
                return web.json_response(collection(rv="kept-version"))
            calls += 1
            assert request.query["resourceVersion"] == "kept-version"
            assert request.query["timeoutSeconds"] == "1"
            if calls < 3:
                return web.Response(status=503)
            assert calls == 3
            response = web.StreamResponse()
            await response.prepare(request)
            # Deliberately ignore timeoutSeconds: this is an actual failed stream.
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.01)
            return response
        finally:
            active -= 1

    async def sleep(delay):
        await clock.sleep(delay)
        if len(clock.delays) == 3:
            raise Finished

    async with reader_fixture(tmp_path, handler) as reader:
        pool = reader.session.api.rest_client.pool_manager

        async def sink(update):
            updates.append(update)
            if update.status is SyncStatus.SNAPSHOT:
                assert reader.session.timeout == 5
                reader.session.timeout = 0.1

        async with asyncio.timeout(5):
            with pytest.raises(Finished):
                await ListWatch(reader, sleep=sleep, jitter=lambda: 0.5).run(
                    pod_resource(), None, sink
                )
    assert calls == 3 and lists == 1
    assert active == 0 and pool.closed and reader.session.api is None
    assert clock.delays == [0.25, 0.5, 0.25]
    retries = [update for update in updates if update.status is SyncStatus.RETRYING]
    assert len(retries) == 3
    for update in retries[:2]:
        assert isinstance(update.problem, HttpProblem) and update.problem.status == 503
    assert retries[-1].problem.state is ConnectionState.TIMEOUT
    assert sum(update.status is SyncStatus.LIVE for update in updates) == 1
    assert all(
        update.snapshot.resource_version == "kept-version"
        for update in updates
        if update.snapshot is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["slow_headers", "slow_error"])
async def test_failed_watch_establishment_does_not_reset_failure_backoff(tmp_path: Path, result):
    clock, calls, lists, updates = Clock(), 0, 0, []

    async def handler(request):
        nonlocal calls, lists
        if "watch" not in request.query:
            lists += 1
            return web.json_response(collection())
        calls += 1
        if result == "slow_headers":
            await asyncio.sleep(0.2)
        else:
            clock.now += 2
        return web.Response(status=503)

    async def pause(delay):
        await clock.sleep(delay)
        if len(clock.delays) == 2:
            raise Finished

    async with reader_fixture(tmp_path, handler) as reader:

        async def consume(update):
            if update.status is SyncStatus.SNAPSHOT:
                assert clock.delays == []
                if result == "slow_headers":
                    reader.session.timeout = 0.1
            await collect(updates, update)

        with pytest.raises(Finished):
            await ListWatch(reader, sleep=pause, monotonic=clock.monotonic, jitter=lambda: 0.5).run(
                pod_resource(), None, consume
            )
    assert lists == 1 and calls == 2
    assert sum(update.status is SyncStatus.SNAPSHOT for update in updates) == 1
    assert clock.delays == [0.25, 0.5]
    assert not any(update.status is SyncStatus.LIVE for update in updates)
    retries = [update for update in updates if update.status is SyncStatus.RETRYING]
    assert len(retries) == 2
    expected = ConnectionState.TIMEOUT if result == "slow_headers" else ConnectionState.API_ERROR
    assert all(update.problem.state is expected for update in retries)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout,seconds", [(0.1, "1"), (1.25, "2"), (5, "5"), (3600, "60")])
async def test_watch_server_interval_is_an_independent_bounded_integer(
    tmp_path, monkeypatch, timeout, seconds
):
    class EmptyResponse:
        status = 200

        def __init__(self):
            self.content = self
            self.chunk_sizes = []
            self.entered = self.exited = self.exhausted = False

        async def __aenter__(self):
            self.entered = True
            return self

        async def __aexit__(self, *args):
            self.exited = True

        def iter_chunked(self, size):
            self.chunk_sizes.append(size)
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            self.exhausted = True
            raise StopAsyncIteration

    response, requests = EmptyResponse(), []

    async def request(pool, url, **kwargs):
        requests.append((pool, url, kwargs))
        assert kwargs["params"]["timeoutSeconds"] == seconds
        assert kwargs["params"]["resourceVersion"] == "opaque"
        assert kwargs["params"]["watch"] == "true"
        assert kwargs["params"]["allowWatchBookmarks"] == "true"
        budget = kwargs["timeout"]
        assert isinstance(budget, ClientTimeout)
        lifetime = int(seconds) + min(timeout, 60.0) + 1.0
        assert budget.total == budget.sock_read == lifetime
        assert budget.connect == min(timeout, lifetime)
        return response

    async def handler(request):
        pytest.fail("Protocol generation uses the public HTTP-call boundary, not a cold connection")

    # Real-HTTP header/body deadline and quiet-renewal cases remain separate.
    monkeypatch.setattr(ClientSession, "get", request)
    async with (
        reader_fixture(tmp_path, handler, timeout=timeout) as reader,
        aclosing(reader.session.watch_json("/api/v1/pods", "opaque")) as stream,
    ):
        pool = reader.session.api.rest_client.pool_manager
        assert reader.session.timeout == timeout
        assert type(reader.session.watch_seconds) is int
        assert reader.session.watch_seconds == int(seconds)
        assert await anext(stream) is None
        assert [value async for value in stream] == []
        assert len(requests) == 1 and requests[0][0] is pool
        assert requests[0][1].endswith("/api/v1/pods")
        assert response.entered and response.exited and response.exhausted
        assert response.chunk_sizes == [16384]
    assert reader.session.api is None and pool.closed


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
        session = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 1)
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
        session = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 1)
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


@pytest.mark.asyncio
async def test_initial_parser_completion_retains_no_deleted_record_while_worker_unwinds(
    tmp_path: Path, monkeypatch
) -> None:
    from kuberich.services import resources

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    phase = contextvars.ContextVar("initial_resource_parse", default=False)
    worker = threading.local()
    published, release = asyncio.Event(), threading.Event()
    original_to_thread = asyncio.to_thread
    original_parse = resources.parse_owned
    original_publish = concurrent.futures.Future.set_result
    parse_calls, publications = 0, []
    initial, uid = None, None

    async def owned_to_thread(operation, /, *args, **kwargs):
        selected = phase.get()
        context = contextvars.copy_context()

        def run():
            try:
                return context.run(operation, *args, **kwargs)
            finally:
                worker.selected = selected

        return await loop.run_in_executor(executor, run)

    async def initial_parse(operation):
        nonlocal parse_calls
        parse_calls += 1
        if parse_calls != 1:
            return await original_parse(operation)
        token = phase.set(True)
        try:
            return await original_parse(operation)
        finally:
            phase.reset(token)

    def publish(future, result):
        selected = getattr(worker, "selected", False)
        original_publish(future, result)
        if selected:
            publications.append((id(future), result is None))
            loop.call_soon_threadsafe(published.set)
            try:
                release.wait()
            finally:
                worker.selected = False

    monkeypatch.setattr(asyncio, "to_thread", owned_to_thread)
    monkeypatch.setattr(resources, "parse_owned", initial_parse)
    monkeypatch.setattr(concurrent.futures.Future, "set_result", publish)

    async def handler(request):
        return (
            web.Response(body=frame(event("DELETED", version="deletion")))
            if "watch" in request.query
            else web.json_response(collection(item()))
        )

    async def sink(update):
        nonlocal initial, uid
        if update.status is SyncStatus.SNAPSHOT:
            initial = weakref.ref(update.snapshot.items[0])
            uid = update.snapshot.items[0].uid
        if update.event is not None:
            async with asyncio.timeout(5):
                await published.wait()
            assert update.event.type is EventType.DELETED
            assert update.event.record.uid == uid
            assert not update.snapshot.items
            assert initial is not None and initial() is None
            assert len(publications) == 1 and publications[0][1] is True
            assert not release.is_set()
            raise Finished

    try:
        async with reader_fixture(tmp_path, handler) as reader:
            with pytest.raises(Finished):
                await ListWatch(reader).run(pod_resource(), None, sink)
    finally:
        release.set()
        monkeypatch.setattr(asyncio, "to_thread", original_to_thread)
        await original_to_thread(executor.shutdown, wait=True)
    assert parse_calls == 1
