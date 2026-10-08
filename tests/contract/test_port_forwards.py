"""Real subprocess/listener behavior against explicit owned HTTP API fixtures."""

import asyncio
import json
import os
import signal
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web

from kuberich.domain.port_forwards import ForwardState, parse_mappings
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from tests.support.port_forwards import manifest, source
from tests.support.resources import reader_fixture


async def state(manager, identity, *desired):
    async with asyncio.timeout(5):
        while True:
            info = next(info for info in manager.infos if info.identity == identity)
            if info.state in desired:
                return info
            await asyncio.sleep(0.005)


async def unavailable(port, address="127.0.0.1"):
    with pytest.raises(OSError):
        _reader, writer = await asyncio.open_connection(address, port)
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["pods", "services"])
@pytest.mark.parametrize("mode", ["normal", "partial"])
@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
async def test_actual_owned_tcp_listener_scope_readiness_and_deliberate_stop(
    tmp_path, resource, mode, address
):
    reads = []

    async def handler(request):
        reads.append(request.path)
        return web.json_response(manifest(resource))

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner, check_interval=0.05)
        captured = source(api, tmp_path, mode=mode, resource=resource)
        identity = manager.start(captured, parse_mappings(":80"), address)
        info = await state(manager, identity, ForwardState.READY, ForwardState.FAILED)
        assert info.state is ForwardState.READY, info.message
        assert info.ports[0].remote == (81 if resource == "services" else 80)
        assert info.pid and manager.active_count == 1
        stream, writer = await asyncio.open_connection(address, info.ports[0].local)
        writer.write(b"owned-payload")
        await writer.drain()
        assert await stream.read(64) == b"owned-response:owned-payload"
        writer.close()
        await writer.wait_closed()
        argv = json.loads((tmp_path / "forward-argv.json").read_text())
        assert argv[1:3] == ["--context=kuberich-test-one", "--namespace=team"]
        assert argv[-2:] == [f"{'pod' if resource == 'pods' else 'service'}/web", "0:80"]
        assert reads[:2] == [f"/api/v1/namespaces/team/{resource}/web"] * 2
        path = Path(argv[0].split("=", 1)[1])
        assert path.exists()
        await manager.stop(identity)
        assert (
            await state(manager, identity, ForwardState.STOPPED)
        ).message == "Stopped by operator."
        assert manager.active_count == 0 and not path.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(info.pid, 0)
        await unavailable(info.ports[0].local, address)
        await manager.stop(identity)
        await manager.close()
        await manager.close()
        assert not manager._live and all(
            not hasattr(history, "configuration") for history in manager.infos
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fail", "silent", "wrong", "flood"])
async def test_startup_failures_are_not_ready_and_clean_children_and_files(tmp_path, mode):
    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner, startup_timeout=0.3)
        identity = manager.start(source(api, tmp_path, mode=mode), parse_mappings(":80"))
        info = await state(manager, identity, ForwardState.FAILED)
        assert "opaque-private-body" not in repr(info) and "private-synthetic" not in repr(info)
        if mode == "fail":
            assert "permission" in info.message
        if mode == "silent":
            assert "timed out" in info.message
        if (tmp_path / "forward-child.pid").exists():
            with pytest.raises(ProcessLookupError):
                os.kill(int((tmp_path / "forward-child.pid").read_text()), 0)
        assert not list(Path(api.session.directory.name).glob("forward-*.json"))
        assert runner.active_count == 0
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["death", "replacement", "deleted", "denied", "connection"])
async def test_active_session_ends_on_process_or_captured_target_loss(tmp_path, reason):
    changed = False

    async def handler(request):
        if changed and reason in {"deleted", "denied"}:
            return web.Response(status=404 if reason == "deleted" else 403, text="private-error")
        return web.json_response(
            manifest(uid="other-uid" if changed and reason == "replacement" else "web-uid")
        )

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner, check_interval=0.03)
        captured = source(api, tmp_path, current=lambda: not (changed and reason == "connection"))
        identity = manager.start(captured, parse_mappings(":80"))
        ready = await state(manager, identity, ForwardState.READY)
        changed = True
        if reason == "death":
            os.kill(ready.pid, signal.SIGTERM)
        info = await state(manager, identity, ForwardState.FAILED)
        assert "private-error" not in info.message
        await unavailable(ready.ports[0].local)
        with pytest.raises(ProcessLookupError):
            os.kill(ready.pid, 0)
        await manager.close()


@pytest.mark.asyncio
async def test_collisions_immediate_stop_context_barrier_and_bounded_history(tmp_path):
    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        captured = source(api, tmp_path)
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        collision = manager.start(captured, parse_mappings(f"{port}:80"))
        assert "Cannot bind" in (await state(manager, collision, ForwardState.FAILED)).message
        server.close()
        await server.wait_closed()
        first = manager.start(captured, parse_mappings(":80"))
        ready = await state(manager, first, ForwardState.READY)
        with pytest.raises(AppError, match="reserves"):
            manager.start(captured, parse_mappings(f"{ready.ports[0].local}:443"))
        await manager.stop_for_client(api.session)
        assert (
            await state(manager, first, ForwardState.STOPPED)
        ).message == "Stopped for connection change."
        await unavailable(ready.ports[0].local)
        with pytest.raises(AppError, match="closing"):
            manager.start(captured, parse_mappings(":80"))
        with pytest.raises(AppError):
            await manager.stop(uuid4())
        await manager.close()
        with pytest.raises(AppError, match="closed"):
            manager.start(captured, parse_mappings(":80"))
        fresh = ForwardManager(runner)
        for _ in range(35):
            identity = fresh.start(captured, parse_mappings(":80"))
            await fresh.stop(identity)
            assert (await state(fresh, identity, ForwardState.STOPPED)).pid is None
        assert len(fresh.infos) == 32 and fresh.active_count == 0 and not fresh._live
        await fresh.close()


@pytest.mark.asyncio
async def test_readonly_and_non_loopback_are_guarded_before_files_or_network(tmp_path):
    reads = []

    async def handler(request):
        reads.append(request.path)
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        with pytest.raises(AppError, match="Read-only"):
            manager.start(source(api, tmp_path, readonly=True), parse_mappings(":80"))
        captured = source(api, tmp_path)
        with pytest.raises(AppError, match="explicit"):
            captured.capture(parse_mappings(":80"), "0.0.0.0")
        request = captured.capture(parse_mappings(":80"), "0.0.0.0", allow_remote=True)
        assert not request.path.exists() and not reads
        with pytest.raises(AppError):
            async with captured.stage(
                replace(request, command=replace(request.command, target=None))
            ):
                pytest.fail("foreign target")
        assert not reads
        await manager.close()


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan"), 61, "1"])
def test_unbounded_or_invalid_monitor_intervals_are_rejected(value):
    with pytest.raises(AppError, match="bounded"):
        ForwardManager(ProcessRunner(AccessPolicy(False)), startup_timeout=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 500])
async def test_api_loss_before_start_never_stages_credentials_or_launches(tmp_path, status):
    async def handler(request):
        return web.Response(status=status, text="token=opaque-private-api-error")

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        identity = manager.start(source(api, tmp_path), parse_mappings(":80"))
        info = await state(manager, identity, ForwardState.FAILED)
        assert info.pid is None and "opaque-private-api-error" not in info.message
        assert not list(Path(api.session.directory.name).glob("forward-*.json"))
        await manager.close()


@pytest.mark.asyncio
async def test_session_limit_reserves_starting_work_before_any_child_is_launched(tmp_path):
    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        captured = source(api, tmp_path)
        for _ in range(8):
            manager.start(captured, parse_mappings(":80"))
        with pytest.raises(AppError, match="Eight"):
            manager.start(captured, parse_mappings(":80"))
        await manager.close()
        assert runner.active_count == 0 and all(
            info.state is ForwardState.STOPPED for info in manager.infos
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["context", "exit", "operator"])
async def test_repeated_cancellation_drains_private_file_creation_and_cleanup(
    tmp_path, monkeypatch, operation
):
    import threading

    from kuberich.services.delegation import ConnectionFile

    started, release = threading.Event(), threading.Event()
    original = ConnectionFile.write

    def delayed(self, configuration):
        original(self, configuration)
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(ConnectionFile, "write", delayed)

    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        identity = manager.start(source(api, tmp_path), parse_mappings(":80"))
        assert await asyncio.to_thread(started.wait, 3)
        closing = asyncio.create_task(
            manager.close()
            if operation == "exit"
            else manager.stop(identity)
            if operation == "operator"
            else manager.stop_for_client(api.session)
        )
        await asyncio.sleep(0.01)
        closing.cancel()
        await asyncio.sleep(0)
        closing.cancel()
        await asyncio.sleep(0.01)
        assert not closing.done() and list(Path(api.session.directory.name).glob("forward-*.json"))
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert all(info.state is ForwardState.STOPPED for info in manager.infos)
        assert runner.active_count == 0 and not list(
            Path(api.session.directory.name).glob("forward-*.json")
        )
        await manager.close()


@pytest.mark.asyncio
async def test_cancel_during_collision_probe_drains_the_owned_thread(tmp_path, monkeypatch):
    import threading

    from kuberich.services import port_forwards

    started, release = threading.Event(), threading.Event()

    def delayed(address, mappings):
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(port_forwards, "_available", delayed)

    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        manager.start(source(api, tmp_path), parse_mappings(":80"))
        assert await asyncio.to_thread(started.wait, 3)
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0.02)
        assert not closing.done() and not list(
            Path(api.session.directory.name).glob("forward-*.json")
        )
        release.set()
        await closing
        assert runner.active_count == 0 and manager.infos[-1].state is ForwardState.STOPPED


@pytest.mark.asyncio
async def test_unexpected_preparation_failure_still_cleans_private_material(tmp_path, monkeypatch):
    from kuberich.services.delegation import ConnectionFile

    original = ConnectionFile.write

    def failing(self, configuration):
        original(self, configuration)
        raise RuntimeError("opaque private implementation failure")

    monkeypatch.setattr(ConnectionFile, "write", failing)

    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        identity = manager.start(source(api, tmp_path), parse_mappings(":80"))
        info = await state(manager, identity, ForwardState.FAILED)
        assert (
            info.message == "Port-forward failed unexpectedly; its owned resources were cleaned up."
        )
        assert (
            not list(Path(api.session.directory.name).glob("forward-*.json"))
            and runner.active_count == 0
        )
        await manager.close()


def test_delegated_purpose_cannot_use_an_unrecognized_private_file_prefix(tmp_path):
    from kuberich.services.delegation import capture_delegation

    with pytest.raises(AppError, match="Unsupported"):
        capture_delegation(None, {}, tmp_path, prefix="other")
