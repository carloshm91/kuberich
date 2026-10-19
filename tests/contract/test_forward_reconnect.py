"""Real process restarts recheck UID, retain ownership and obey a bounded opt-in."""

import asyncio
import json
import os
import signal

import pytest
from aiohttp import web

from kuberich.domain.forward_presets import ForwardTransport
from kuberich.domain.port_forwards import ForwardState, parse_mappings
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from tests.contract.test_port_forwards import state, unavailable
from tests.support.port_forwards import manifest, source
from tests.support.resources import reader_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["pods", "services"])
@pytest.mark.parametrize("transport", list(ForwardTransport))
async def test_reconnect_reaps_old_process_and_refreshes_private_capture(
    tmp_path, resource, transport
):
    observations = []
    reads = []

    async def handler(request):
        reads.append(request.path)
        return web.json_response(manifest(resource))

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(
            runner, changed=lambda: observations.append(manager.infos[-1]), check_interval=0.05
        )
        identity = manager.start(
            source(api, tmp_path, resource=resource),
            parse_mappings(":80"),
            transport=transport,
            retries=1,
        )
        first = await state(manager, identity, ForwardState.READY)
        old_config = json.loads((tmp_path / "forward-argv.json").read_text())[0]
        os.kill(first.pid, signal.SIGTERM)
        await state(manager, identity, ForwardState.RECONNECTING)
        with pytest.raises(ProcessLookupError):
            os.kill(first.pid, 0)
        await unavailable(first.ports[0].local)
        async with asyncio.timeout(5):
            while True:
                second = manager.infos[-1]
                if second.state is ForwardState.READY and second.attempt == 1:
                    break
                assert second.state is not ForwardState.FAILED, second.message
                await asyncio.sleep(0.01)
        with pytest.raises(ProcessLookupError):
            os.kill(first.pid, 0)
        assert second.pid != first.pid and second.transport is transport
        assert json.loads((tmp_path / "forward-argv.json").read_text())[0] != old_config
        assert any(
            info.state is ForwardState.RECONNECTING and info.pid is None for info in observations
        )
        assert len(reads) >= 4
        flag = json.loads((tmp_path / "forward-transport.json").read_text())
        assert flag == (
            "true"
            if transport is ForwardTransport.WEBSOCKET
            else "false"
            if transport is ForwardTransport.SPDY
            else os.environ.get("KUBECTL_PORT_FORWARD_WEBSOCKETS")
        )
        reader, writer = await asyncio.open_connection("127.0.0.1", second.ports[0].local)
        writer.write(b"reconnected")
        await writer.drain()
        assert await reader.read(64) == b"owned-response:reconnected"
        writer.close()
        await writer.wait_closed()
        os.kill(second.pid, signal.SIGTERM)
        final = await state(manager, identity, ForwardState.FAILED)
        assert final.attempt == 1 and "ended" in final.message
        await unavailable(second.ports[0].local)
        assert not runner.active_count
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cancel", "connection", "replacement", "denied", "deleted"])
async def test_reconnect_delay_is_owned_and_does_not_retry_stale_or_denied_targets(
    tmp_path, reason
):
    changed = False

    async def handler(request):
        if changed and reason in {"denied", "deleted"}:
            return web.Response(status=403 if reason == "denied" else 404)
        return web.json_response(
            manifest(uid="replacement" if changed and reason == "replacement" else "web-uid")
        )

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        identity = manager.start(
            source(api, tmp_path, current=lambda: not (changed and reason == "connection")),
            parse_mappings(":80"),
            retries=3,
        )
        first = await state(manager, identity, ForwardState.READY)
        os.kill(first.pid, signal.SIGTERM)
        await state(manager, identity, ForwardState.RECONNECTING)
        changed = True
        if reason == "cancel":
            await manager.stop(identity)
            assert (await state(manager, identity, ForwardState.STOPPED)).attempt == 1
        else:
            final = await state(manager, identity, ForwardState.FAILED)
            assert final.attempt == 1
            assert not any(
                info.state is ForwardState.READY and info.attempt for info in manager.infos
            )
        assert not runner.active_count
        await manager.close()


@pytest.mark.asyncio
async def test_transport_denial_never_reconnects_and_invalid_retry_budget_fails_before_capture(
    tmp_path,
):
    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner)
        captured = source(api, tmp_path, mode="fail")
        for retries in [-1, True, 4, "1"]:
            with pytest.raises(AppError, match="retries"):
                manager.start(captured, parse_mappings(":80"), retries=retries)
        identity = manager.start(captured, parse_mappings(":80"), retries=3)
        info = await state(manager, identity, ForwardState.FAILED)
        assert info.attempt == 0 and "permission" in info.message
        assert not runner.active_count
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before-start", "while-active", "during-reconnect"])
async def test_same_uid_service_port_reassignment_requires_new_review(tmp_path, when):
    changed = when == "before-start"

    async def handler(request):
        value = manifest("services")
        value["spec"] = {
            "ports": [{"name": "http", "port": 8080 if changed else 80, "targetPort": 8090}]
        }
        return web.json_response(value)

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner, check_interval=0.03)
        captured = source(api, tmp_path, resource="services")
        await captured.verify()
        with pytest.raises(AppError):
            captured.capture(parse_mappings(":80"), "127.0.0.1", intent="bad\nintent")
        identity = manager.start(captured, parse_mappings(":80"), intent=":http", retries=3)
        if when != "before-start":
            first = await state(manager, identity, ForwardState.READY)
            if when == "during-reconnect":
                os.kill(first.pid, signal.SIGTERM)
                await state(manager, identity, ForwardState.RECONNECTING)
            changed = True
        final = await state(manager, identity, ForwardState.FAILED)
        assert "ports changed" in final.message
        assert final.attempt == (1 if when == "during-reconnect" else 0)
        assert not runner.active_count
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["wrong", "silent", "flood"])
async def test_invalid_startup_is_not_a_retryable_disconnect(tmp_path, mode):
    async def handler(request):
        return web.json_response(manifest())

    async with (
        reader_fixture(tmp_path, handler) as api,
        ProcessRunner(AccessPolicy(False)) as runner,
    ):
        manager = ForwardManager(runner, startup_timeout=0.3)
        identity = manager.start(source(api, tmp_path, mode=mode), parse_mappings(":80"), retries=3)
        final = await state(manager, identity, ForwardState.FAILED)
        assert final.attempt == 0 and not runner.active_count
        await manager.close()
