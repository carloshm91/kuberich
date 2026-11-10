"""Independent public regressions for manifest review cancellation and write ownership."""

import asyncio

import pytest

from kuberich.domain.mutations import MutationState
from kuberich.services.mutations import MutationManager
from tests.contract.test_manifest_service import service_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [False, True])
async def test_stop_during_accepted_delete_observation_keeps_later_items_unsent(tmp_path, managed):
    async with service_fixture(tmp_path, count=2, existing=True) as (service, adapter, _, _):
        plan = await service.prepare("delete")
        adapter.write_states = [MutationState.ACCEPTED, MutationState.ACCEPTED]
        original_read = adapter.read
        observing = asyncio.Event()
        release = asyncio.Event()

        async def read(resource, address, guard):
            if adapter.writes and address.name == "0":
                observing.set()
                await release.wait()
            return await original_read(resource, address, guard)

        adapter.read = read
        manager = MutationManager()
        if managed:
            identity = manager.start(service, service.confirm(plan))
        else:
            execution = asyncio.create_task(service.execute(service.confirm(plan)))
        await asyncio.wait_for(observing.wait(), 2)
        if managed:
            result = await asyncio.wait_for(manager.cancel(identity), 2)
            assert manager.records[-1].result == result
        else:
            execution.cancel()
            result = await asyncio.wait_for(execution, 2)
        assert len(adapter.writes) == 1
        assert result.items[0][1].state is MutationState.ACCEPTED
        assert result.items[1][1].state is MutationState.BLOCKED
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [False, True])
async def test_stop_after_known_completed_write_preserves_success_and_sends_no_later_request(
    tmp_path, managed
):
    """An owned transport can finish a verified receipt while draining cancellation."""
    from kuberich.domain.mutations import MutationResult

    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        admitted = asyncio.Event()
        release = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            if len(adapter.writes) == 1:
                admitted.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    # Verified completion wins over an unproven uncertain result,
                    # but cancellation still ends the owning batch.
                    return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        manager = MutationManager()
        if managed:
            identity = manager.start(service, service.confirm(plan))
        else:
            execution = asyncio.create_task(service.execute(service.confirm(plan)))
        await asyncio.wait_for(admitted.wait(), 2)
        if managed:
            result = await asyncio.wait_for(manager.cancel(identity), 2)
        else:
            execution.cancel()
            result = await asyncio.wait_for(execution, 2)
        assert len(adapter.writes) == 1
        assert result.items[0][1].state is MutationState.SUCCEEDED
        assert result.items[1][1].state in {MutationState.CANCELLED, MutationState.BLOCKED}
        assert (
            "no request sent" in result.items[1][1].message
            or "Unsent" in result.items[1][1].message
        )
        assert result.items[2][1].state is MutationState.BLOCKED
        if managed:
            assert manager.records[-1].result == result
        await manager.close()


@pytest.mark.asyncio
async def test_helper_private_draft_cleanup_failure_is_safe_and_owner_close_retries(
    tmp_path, monkeypatch
):
    """A failed private-file removal remains owned after the preview task ends."""
    from kuberich.adapters.editing import ManifestFile
    from kuberich.domain.targets import ResourceTarget
    from kuberich.errors import AppError
    from tests.contract.test_manifest_preview import helper_environment
    from tests.contract.test_manifest_writes import (
        RESOURCE,
        SESSION,
        adapter_fixture,
        create_intent,
    )

    original = ManifestFile.close
    calls = 0

    def fail_once(draft):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("private-local-path-sentinel")
        return original(draft)

    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value)
        monkeypatch.setattr(ManifestFile, "close", fail_once)
        with pytest.raises(Exception) as failure:
            await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        await adapter.close()
        assert isinstance(failure.value, AppError) and "private-local-path-sentinel" not in str(
            failure.value
        )
        assert calls == 2


@pytest.mark.asyncio
async def test_cancel_before_operation_entry_consumes_the_admitted_confirmation(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        proof = service.confirm(plan)
        manager = MutationManager()
        identity = manager.start(service, proof)
        cancelled = await manager.cancel(identity)
        assert cancelled.state is MutationState.CANCELLED and not adapter.writes
        replay = await service.execute(proof)
        assert replay.state is MutationState.BLOCKED and not adapter.writes
        await manager.close()


@pytest.mark.asyncio
async def test_concurrent_confirmation_cannot_replace_an_active_batchs_completed_outcomes(tmp_path):
    from kuberich.domain.mutations import MutationResult
    from kuberich.errors import AppError

    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        second_entered = asyncio.Event()
        release = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            if intent.target.name == "1":
                second_entered.set()
                await release.wait()
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        first = asyncio.create_task(service.execute(service.confirm(plan)))
        await asyncio.wait_for(second_entered.wait(), 2)
        assert len(service.results) == 1 and service.results[0][1].state is MutationState.SUCCEEDED
        try:
            proof = service.confirm(plan)
        except AppError:
            pass
        else:
            rejected = await service.execute(proof)
            assert rejected.state in {MutationState.BLOCKED, MutationState.STALE}
        finally:
            release.set()
        result = await asyncio.wait_for(first, 2)
        assert len(adapter.writes) == 3
        assert len(result.items) == 3
        assert [target.name for target, _ in result.items] == ["0", "1", "2"]
        assert all(item.state is MutationState.SUCCEEDED for _, item in result.items)


@pytest.mark.asyncio
async def test_pre_entry_double_admission_cannot_replace_the_winning_batchs_outcomes(tmp_path):
    from kuberich.domain.mutations import MutationResult
    from kuberich.errors import AppError

    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        second_entered = asyncio.Event()
        release = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            if intent.target.name == "1":
                second_entered.set()
                await release.wait()
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        manager = MutationManager()
        first = manager.start(service, service.confirm(plan))
        try:
            proof = service.confirm(plan)
        except AppError:
            second = None
        else:
            second = manager.start(service, proof)
        await asyncio.wait_for(second_entered.wait(), 2)
        try:
            if second is not None:
                rejected = await asyncio.wait_for(manager.wait(second), 2)
                assert rejected.state in {MutationState.BLOCKED, MutationState.STALE}
        finally:
            release.set()
        result = await asyncio.wait_for(manager.wait(first), 2)
        assert len(adapter.writes) == 3 and len(result.items) == 3
        assert [target.name for target, _ in result.items] == ["0", "1", "2"]
        assert all(item.state is MutationState.SUCCEEDED for _, item in result.items)
        await manager.close()


@pytest.mark.asyncio
async def test_wait_publishes_a_just_completed_batch_before_done_callback_delivery(tmp_path):
    from kuberich.domain.mutations import MutationResult

    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        completed = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            completed.set()
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        manager = MutationManager()
        identity = manager.start(service, service.confirm(plan))
        await completed.wait()
        result = await manager.wait(identity)
        assert result.state is MutationState.SUCCEEDED and len(result.items) == 1
        assert manager.records[-1].result == result and manager.active_count == 0
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_pre_entry_cancel_retains_two_exact_targets_and_scoped_history(tmp_path, existing):
    async with service_fixture(tmp_path, count=2, existing=existing) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        manager = MutationManager()
        proof = service.confirm(plan)
        identity = manager.start(service, proof)
        result = await manager.cancel(identity)
        assert tuple(target for target, _ in result.items) == plan.targets
        assert len(result.items) == 2 and not adapter.writes
        assert all(
            item.state is MutationState.CANCELLED and "Unsent" in item.message
            for _, item in result.items
        )
        history = manager.records[-1]
        assert history.targets == plan.targets and history.result == result
        assert all(
            "namespace=team" in effect and "v1/configmaps/" in effect for effect in history.effects
        )
        assert tuple(target.uid for target in history.targets) == (
            ("uid-0", "uid-1") if existing else (None, None)
        )
        if existing:
            assert all("resourceVersion=1" in effect for effect in history.effects)
        else:
            assert all("UID=(not captured)" in effect for effect in history.effects)
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        await manager.close()
