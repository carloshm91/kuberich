"""Actual HTTP frames retain pull ownership through one JSON/domain worker."""

import asyncio
import json
import threading
from contextlib import aclosing
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web

from kuberich.adapters import kubernetes
from kuberich.domain.connections import ConnectionProblem, ConnectionState
from kuberich.domain.watches import SyncStatus
from kuberich.services import watches
from kuberich.services.resources import parse_owned
from kuberich.services.watches import ListWatch
from tests.support.resources import collection, pod_resource, reader_fixture
from tests.support.watches import event, frame


class Finished(Exception):
    """Stop the owned consumer after its intended observations."""


@pytest_asyncio.fixture
async def collected_loop_errors():
    loop = asyncio.get_running_loop()
    original = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda owner, context: errors.append(context))
    try:
        yield errors
        await asyncio.sleep(0)
        assert not errors
    finally:
        loop.set_exception_handler(original)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [b"private-invalid-json\n", b"[]\n", b'{"secret":NaN}\n', b"\xff\n", b"[" * 10000 + b"\n"],
)
async def test_json_compatibility_transport_rejects_invalid_frames_without_leaking_body(
    tmp_path, body
):
    async def handler(request):
        return web.Response(body=body)

    async with reader_fixture(tmp_path, handler) as reader:
        async with aclosing(reader.session.watch_json("/api/v1/pods", "opaque")) as stream:
            assert await anext(stream) is None
            with pytest.raises(ConnectionProblem) as problem:
                await anext(stream)
            assert problem.value.state is ConnectionState.API_ERROR
            assert str(problem.value) == "Invalid or oversized Kubernetes watch response."
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


async def wait_for_thread(entered: threading.Event) -> None:
    async with asyncio.timeout(3):
        while not entered.is_set():
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["get", "watch"])
@pytest.mark.parametrize("fail", [False, True])
async def test_json_transport_repeated_cancel_retains_parser_ownership(
    tmp_path, monkeypatch, transport, fail, collected_loop_errors
):
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    original = kubernetes.decode_json

    def held(data):
        entered.set()
        try:
            assert released.wait(timeout=5)
            if fail:
                raise ValueError("owned-private-json-failure")
            return original(data)
        finally:
            finished.set()

    monkeypatch.setattr(kubernetes, "decode_json", held)

    async def handler(request):
        return web.Response(body=frame(event()) if transport == "watch" else b'{"ok":true}')

    async with reader_fixture(tmp_path, handler) as reader:
        async with aclosing(reader.session.watch_json("/api/v1/pods", "opaque")) as stream:
            if transport == "watch":
                assert await anext(stream) is None
            operation = anext(stream) if transport == "watch" else reader.session.get_json("/api")
            task = asyncio.create_task(operation)
            try:
                await wait_for_thread(entered)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0.02)
                assert not task.done() and not finished.is_set()
            finally:
                released.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert finished.is_set()
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
@pytest.mark.parametrize("parser", ["compatibility", "domain"])
@pytest.mark.parametrize("fail", [False, True])
async def test_uncancelled_parser_preserves_result_and_original_error(
    monkeypatch, parser, fail, collected_loop_errors
):
    result = {"owned": "value"}
    failure = ValueError("owned-parser-failure")

    def operation(*args):
        if fail:
            raise failure
        return result

    if parser == "compatibility":
        monkeypatch.setattr(kubernetes, "decode_json", operation)
        awaitable = kubernetes._decode_owned(b'{"owned":"value"}')
    else:
        awaitable = parse_owned(operation)
    if fail:
        with pytest.raises(ValueError) as problem:
            await awaitable
        assert problem.value is failure
    else:
        assert await awaitable is result


@pytest.mark.asyncio
@pytest.mark.parametrize("decoded", [False, True])
async def test_split_unicode_crlf_and_blank_frames_keep_transport_order(tmp_path, decoded):
    values = [event(version="first"), event("MODIFIED", version="second")]
    values[0]["object"]["metadata"]["annotations"] = {"large": "🚀" * 5000}
    frames = [json.dumps(value, ensure_ascii=False).encode() for value in values]
    body = b"\n \r\n" + b"\r\n".join(frames) + b"\r\n"

    async def handler(request):
        response = web.StreamResponse()
        await response.prepare(request)
        for offset in range(0, len(body), 101):
            await response.write(body[offset : offset + 101])
        await response.write_eof()
        return response

    async with reader_fixture(tmp_path, handler) as reader:
        method = reader.session.watch_json if decoded else reader.session.watch_bytes
        async with aclosing(method("/api/v1/pods", "opaque")) as stream:
            assert await anext(stream) is None
            assert [value async for value in stream] == (
                values if decoded else [value + b"\r" for value in frames]
            )
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_raw_transport_refuses_oversize_before_consumer_parsing(tmp_path, complete):
    async def handler(request):
        return web.Response(body=b"x" * 129 + (b"\n" if complete else b""))

    async with reader_fixture(tmp_path, handler) as reader:
        async with aclosing(
            reader.session.watch_bytes("/api/v1/pods", "opaque", max_bytes=128)
        ) as stream:
            assert await anext(stream) is None
            with pytest.raises(ConnectionProblem) as problem:
                await anext(stream)
            assert problem.value.state is ConnectionState.API_ERROR
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
async def test_complete_raw_frame_at_limit_and_incomplete_tail_resume_safely(tmp_path):
    async def handler(request):
        return web.Response(body=b"x" * 128 + b"\n" + b'{"type":"MODIFIED"')

    async with reader_fixture(tmp_path, handler) as reader:
        async with aclosing(
            reader.session.watch_bytes("/api/v1/pods", "opaque", max_bytes=128)
        ) as stream:
            assert await anext(stream) is None
            assert await anext(stream) == b"x" * 128
            with pytest.raises(ConnectionProblem) as problem:
                await anext(stream)
            assert problem.value.state is ConnectionState.UNREACHABLE
            assert "incomplete event" in str(problem.value)
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
async def test_json_and_normalization_share_one_owned_worker_without_read_ahead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, released = threading.Event(), threading.Event()
    calls, submissions = [], []
    loop_thread = threading.get_ident()
    decode, normalize, to_thread = watches.decode_json, watches.watch_event, asyncio.to_thread

    def observed_decode(payload):
        calls.append(("json", threading.get_ident()))
        return decode(payload)

    def held_normalize(*args):
        calls.append(("domain", threading.get_ident()))
        entered.set()
        assert released.wait(timeout=5)
        return normalize(*args)

    async def observed_worker(operation, *args, **kwargs):
        submissions.append(operation)
        return await to_thread(operation, *args, **kwargs)

    monkeypatch.setattr(watches, "decode_json", observed_decode)
    monkeypatch.setattr(watches, "watch_event", held_normalize)
    monkeypatch.setattr(asyncio, "to_thread", observed_worker)

    async def handler(request):
        if "watch" not in request.query:
            return web.json_response(collection())
        return web.Response(body=b"".join(frame(event(version=str(index))) for index in range(100)))

    async def sink(update):
        if update.event is not None:
            assert update.snapshot.resource_version == "0"
            assert len(calls) == 2 and len(submissions) == 1
            await asyncio.sleep(0.03)
            assert len(calls) == 2 and len(submissions) == 1
            raise Finished
        if update.status is SyncStatus.LIVE:
            submissions.clear()

    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(ListWatch(reader).run(pod_resource(), None, sink))
        try:
            await wait_for_thread(entered)
            await asyncio.sleep(0.03)
            assert len(calls) == 2 and len(submissions) == 1
            assert calls[0][1] == calls[1][1] != loop_thread
        finally:
            released.set()
            with pytest.raises(Finished):
                await task
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["json", "domain"])
@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancel_drains_combined_worker_and_closes_http(
    tmp_path, monkeypatch, stage, fail
):
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    field = "decode_json" if stage == "json" else "watch_event"
    original = getattr(watches, field)
    emitted, loop_errors = [], []
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda owner, context: loop_errors.append(context))

    def held(*args):
        entered.set()
        try:
            assert released.wait(timeout=5)
            if fail:
                raise ValueError("owned-private-worker-failure")
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(watches, field, held)

    async def handler(request):
        return (
            web.Response(body=frame(event()))
            if "watch" in request.query
            else web.json_response(collection())
        )

    async def sink(update):
        if update.event is not None:
            emitted.append(update.event)

    try:
        async with reader_fixture(tmp_path, handler) as reader:
            task = asyncio.create_task(ListWatch(reader).run(pod_resource(), None, sink))
            try:
                await wait_for_thread(entered)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0.02)
                assert not task.done() and not finished.is_set()
            finally:
                released.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert finished.is_set() and not emitted
            assert not reader.session.api.rest_client.pool_manager.connector._acquired
        await asyncio.sleep(0)
        assert not loop_errors
    finally:
        loop.set_exception_handler(original_handler)
