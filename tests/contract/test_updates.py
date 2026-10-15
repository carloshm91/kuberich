"""Owned HTTP, cache files, deadlines and repeated-cancellation release checks."""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web

from kuberich.errors import AppError
from kuberich.services import updates
from kuberich.services.updates import MAX_RESPONSE_BYTES, UpdateService, read_cache, write_cache
from tests.unit.test_releases import release


@asynccontextmanager
async def releases(body=None, *, status=200, hold=False):
    seen, started, stop = [], asyncio.Event(), asyncio.Event()

    async def handle(request):
        seen.append(dict(request.headers))
        started.set()
        if hold:
            await stop.wait()
        value = release() if body is None else body
        return web.Response(
            status=status,
            body=value if isinstance(value, bytes) else json.dumps(value).encode(),
            headers={"Location": "http://127.0.0.1:1/never-follow"} if status == 302 else {},
        )

    app = web.Application()
    app.router.add_get("/latest", handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}/latest", seen, started, stop
    finally:
        stop.set()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_verified_notice_uses_no_credentials_and_reuses_private_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "owned-never-send-token")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    cache = tmp_path / "private" / "release.json"
    async with releases() as (url, seen, _, _):
        service = UpdateService("0.1.0", cache, endpoint=url)
        first, second = await service.check(), await service.check()
        assert first.release.version == "0.2.0" and not first.cached
        assert second.release == first.release and second.cached and len(seen) == 1
        assert seen[0]["User-Agent"] == "KubeRich/0.1.0"
        assert seen[0]["Accept-Encoding"] == "identity"
        assert "Authorization" not in seen[0] and "Cookie" not in seen[0]
        assert "owned-never-send-token" not in repr(first) + cache.read_text()
        assert (
            cache.stat().st_mode & 0o777 == 0o600 and cache.parent.stat().st_mode & 0o777 == 0o700
        )
        service.current = "0.3.0"
        assert (await service.check()).release is None and len(seen) == 1
        service.current = "invalid"
        assert "unavailable" in (await service.check()).message and len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 304, 401, 403, 404, 429, 500])
async def test_unavailable_private_rate_limited_and_redirect_responses_make_no_notice(
    tmp_path, status
):
    async with releases(b"private-server-response", status=status) as (url, seen, _, _):
        result = await UpdateService("0.1.0", tmp_path / "release.json", endpoint=url).check()
        assert result.release is None and "unavailable" in result.message
        assert "private-server-response" not in repr(result) and len(seen) == 1
        assert not (tmp_path / "release.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"private-invalid-json",
        b"x" * (MAX_RESPONSE_BYTES + 1),
        release(draft=True),
        release(prerelease=True),
        release("v0.2.0rc1"),
        release(html_url="https://evil.invalid/"),
        {"private": "unverified"},
    ],
)
async def test_invalid_oversized_nonpublic_or_unstable_bodies_are_content_free(tmp_path, body):
    async with releases(body) as (url, _, _, _):
        result = await UpdateService("0.1.0", tmp_path / "release.json", endpoint=url).check()
        assert (
            result.release is None
            and "unavailable" in result.message
            and "private" not in repr(result)
        )


@pytest.mark.asyncio
async def test_timeout_and_offline_failure_are_nonfatal(tmp_path):
    async with releases(hold=True) as (url, _, _, _):
        result = await asyncio.wait_for(
            UpdateService("0.1.0", tmp_path / "r", endpoint=url).check(), 5
        )
        assert not result.release and "offline" in result.message
    result = await UpdateService(
        "0.1.0", tmp_path / "r", endpoint="http://127.0.0.1:1/latest"
    ).check()
    assert not result.release


@pytest.mark.asyncio
async def test_cache_write_failure_preserves_verified_result_and_malformed_cache_refetches(
    tmp_path,
):
    cache = tmp_path / "release.json"
    cache.write_bytes(b"private-not-json")
    async with releases() as (url, seen, _, _):
        assert (await UpdateService("0.1.0", cache, endpoint=url).check()).release is not None
        assert len(seen) == 1
        blocked = tmp_path / "not-directory"
        blocked.write_text("owned")
        assert (
            await UpdateService("0.1.0", blocked / "cache", endpoint=url).check()
        ).release is not None


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_real_http_session_cleanup(tmp_path, monkeypatch):
    entered, released = asyncio.Event(), asyncio.Event()
    original, closed = aiohttp.ClientSession.close, []

    async def close(session):
        entered.set()
        await released.wait()
        await original(session)
        closed.append(session.closed)

    monkeypatch.setattr(aiohttp.ClientSession, "close", close)
    async with releases(hold=True) as (url, _, started, stop):
        task = asyncio.create_task(UpdateService("0.1.0", tmp_path / "r", endpoint=url).check())
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        released.set()
        stop.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [True] and not (tmp_path / "r").exists()


def test_cache_files_are_bounded_regular_and_symlink_safe(tmp_path):
    path = tmp_path / "cache"
    record = updates.release_record(release())
    write_cache(path, record, 1)
    before = path.read_bytes()
    assert read_cache(path)["checked_at"] == 1
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        read_cache(link)
    with pytest.raises(AppError, match="symbolic"):
        write_cache(link, record, 2)
    assert path.read_bytes() == before
    path.write_bytes(b"x" * 4097)
    with pytest.raises(AppError, match="size"):
        read_cache(path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(AppError, match="regular"):
        read_cache(fifo)


def test_cache_stream_failure_removes_its_temporary_file_and_preserves_previous(
    tmp_path, monkeypatch
):
    path = tmp_path / "cache"
    record = updates.release_record(release())
    write_cache(path, record, 1)
    original, closed = os.close, []

    def refused(*args, **kwargs):
        raise OSError("owned-refused")

    def close(descriptor):
        closed.append(descriptor)
        original(descriptor)

    monkeypatch.setattr(updates.os, "fdopen", refused)
    monkeypatch.setattr(updates.os, "close", close)
    with pytest.raises(OSError):
        write_cache(path, record, 2)
    assert len(closed) == 1 and not list(tmp_path.glob(".version-*"))
    assert json.loads(path.read_text())["checked_at"] == 1
