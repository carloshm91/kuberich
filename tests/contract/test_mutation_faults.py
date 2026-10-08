"""Confirmation tampering, helper refresh, pre-send faults and repeated cancellation."""

import asyncio
import socket
import sys
import threading
from dataclasses import replace

import pytest

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.adapters.mutations import conditional_patch
from kubetrol.domain.mutations import MutationState, annotation_intent
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.mutations import MutationManager, MutationService
from tests.contract.test_mutations import source_fixture
from tests.support.connections import catalog_fixture
from tests.unit.test_mutations import selection


@pytest.mark.asyncio
async def test_confirmed_payload_cannot_be_replaced_or_retargeted(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        with pytest.raises(AppError):
            source.confirm(None)
        proof = source.confirm(intent)
        source.intent = replace(intent)
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        source.intent = replace(intent, target=replace(intent.target, namespace="other"))
        with pytest.raises(AppError):
            source.confirm(source.intent)
        source.intent = intent
        source.policy = AccessPolicy(True)
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert not api.requests


@pytest.mark.asyncio
async def test_known_read_timeout_and_cancellation_do_not_send_write(tmp_path):
    async with source_fixture(tmp_path, timeout=0.1) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        proof = source.confirm(intent)
        api.read_delay = 0.3
        assert (await source.execute(proof)).state is MutationState.TIMEOUT
        api.read_delay = 0
        intent = await source.prepare_annotation("key", "value")
        api.read_delay = 1
        task = asyncio.create_task(source.execute(source.confirm(intent)))
        await asyncio.sleep(0.02)
        task.cancel()
        assert (await task).state is MutationState.CANCELLED
        assert not api.requests


@pytest.mark.asyncio
async def test_closed_connection_and_repeated_receipt_cancellation_are_owned(tmp_path, monkeypatch):
    from kubetrol.adapters import mutations

    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        entered, release = threading.Event(), threading.Event()
        original = mutations._receipt

        def receipt(data, captured):
            entered.set()
            assert release.wait(3)
            original(data, captured)

        monkeypatch.setattr(mutations, "_receipt", receipt)
        task = asyncio.create_task(source.execute(source.confirm(intent)))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
        finally:
            release.set()
        assert (await task).state is MutationState.UNCERTAIN
        assert len(api.requests) == 1
        await source.client.close()
        assert (
            await conditional_patch(source.client, intent, source.require_current)
        ).state is MutationState.STALE


@pytest.mark.asyncio
async def test_real_exec_token_write_401_never_refreshes_or_replays(tmp_path):
    counter = tmp_path / "helper-count"
    helper = tmp_path / "owned-helper.py"
    helper.write_text(
        "import json,sys\nfrom pathlib import Path\np=Path(sys.argv[1])\np.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nprint(json.dumps({'apiVersion':'client.authentication.k8s.io/v1','kind':'ExecCredential','status':{'token':'synthetic-helper-token','expirationTimestamp':'2099-01-01T00:00:00Z'}}))\n"
    )
    user = {
        "exec": {
            "apiVersion": "client.authentication.k8s.io/v1",
            "command": sys.executable,
            "args": [str(helper), str(counter)],
            "interactiveMode": "Never",
        }
    }
    async with source_fixture(tmp_path, user=user) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        api.patch_status = 401
        assert (await source.execute(source.confirm(intent))).state is MutationState.AUTH_ERROR
        assert counter.read_text() == "1" and len(api.requests) == 1


@pytest.mark.asyncio
async def test_bounded_history_active_limit_and_unprepared_source(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        manager = MutationManager()
        with pytest.raises(AppError, match="Prepare"):
            manager.start(source, None)
        for index in range(35):
            intent = await source.prepare_annotation("key", str(index))
            identity = manager.start(source, source.confirm(intent))
            assert (await manager.wait(identity)).state is MutationState.SUCCEEDED
        assert len(manager.records) == 32 and len(api.requests) == 35
        intent = await source.prepare_annotation("key", "next")
        proof = source.confirm(intent)
        tasks = [manager.start(source, proof) for _ in range(8)]
        with pytest.raises(AppError, match="Eight"):
            manager.start(source, proof)
        await manager.close()
        results = [await manager.wait(identity) for identity in tasks]
        assert all(result.state is MutationState.CANCELLED for result in results)


@pytest.mark.asyncio
async def test_anonymous_owned_transport_and_known_connection_refusal(tmp_path):
    async with source_fixture(tmp_path, user={}) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        assert (await source.execute(source.confirm(intent))).state is MutationState.SUCCEEDED
        assert "Authorization" not in dict(api.requests[0][1])
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))  # Own the numeric port without accepting connections.
        url = f"http://127.0.0.1:{unused.getsockname()[1]}"
        client = KubernetesSession(
            catalog_fixture(tmp_path, url, user={}).select("kubetrol-test-one"), 0.2
        )
        await client.open()
        resource, target, record = selection()
        source = MutationService(client, resource, target, AccessPolicy(False), lambda: True)
        try:
            intent = annotation_intent(resource, target, record, "key", "value")
            assert (
                await conditional_patch(client, intent, source.require_current)
            ).state is MutationState.UNREACHABLE
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_unexpected_failure_after_actual_write_retains_uncertain_result(
    tmp_path, monkeypatch
):
    async with source_fixture(tmp_path) as (source, api, _):
        original = source.execute

        async def fail_after_write(proof):
            assert (await original(proof)).state is MutationState.SUCCEEDED
            raise RuntimeError("private-unexpected-diagnostic-value")

        monkeypatch.setattr(source, "execute", fail_after_write)
        intent = await source.prepare_annotation("key", "value")
        manager = MutationManager()
        identity = manager.start(source, source.confirm(intent))
        result = await manager.wait(identity)
        assert result.state is MutationState.UNCERTAIN and "private-" not in result.message
        assert len(api.requests) == 1 and api.value["metadata"]["annotations"]["key"] == "value"
        await manager.close()
