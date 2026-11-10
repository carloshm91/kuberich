"""Actual HTTP recovery: explicit scope, single use and no unknown-UID adoption."""

import asyncio
import os
import stat
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from kuberich.domain.connections import HttpProblem
from kuberich.domain.mutations import MutationState
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import Confirmation
from kuberich.services.node_shell_recovery import NodeShellRecovery, RecoveryJournalError
from tests.contract.test_node_shell import create, source_fixture


@asynccontextmanager
async def recovery_fixture(tmp_path, *, unknown=False):
    async with source_fixture(tmp_path) as values:
        manager, client, api, policy, current, _ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.mode = "drop" if unknown else "normal"
        result = await owner.execute(owner.confirm(intent))
        if unknown:
            assert result.state is MutationState.UNCERTAIN and owner.owned is None
        else:
            assert result.state is MutationState.SUCCEEDED
            api.delete_status = 403
            await owner.close()
        (record,) = await manager.scan()
        recovery = NodeShellRecovery(manager.journal, client, policy, lambda: current[0])
        try:
            yield recovery, record, values
        finally:
            await recovery.close()


@pytest.mark.asyncio
async def test_denied_cleanup_is_explicitly_reviewed_then_deletes_only_recorded_uid(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        initial_deletes = len(api.deletes)
        assert initial_deletes == 1 and record.pod_uid == "returned-owned-uid"
        observed = await recovery.inspect(record)
        assert (
            observed.pod_present and observed.code == "present_owned" and observed.record == record
        )
        review = await recovery.prepare_cleanup(record)
        assert review.record == record and review.action == "cleanup"
        assert len(api.deletes) == initial_deletes
        api.delete_status = 200
        proof = recovery.confirm(review)
        result = await recovery.cleanup(proof)
        assert result.state is MutationState.SUCCEEDED
        assert api.pod is None and len(api.deletes) == initial_deletes + 1
        assert api.deletes[-1]["preconditions"] == {"uid": record.pod_uid}
        assert await manager.scan() == ()
        assert (await recovery.cleanup(proof)).state is MutationState.BLOCKED
        with pytest.raises(AppError, match="exact current"):
            recovery.confirm(review)


@pytest.mark.asyncio
@pytest.mark.parametrize("present", [False, True])
async def test_unknown_create_inspection_never_promotes_name_to_ownership(tmp_path, present):
    async with recovery_fixture(tmp_path, unknown=True) as (recovery, record, values):
        manager, _, api, *_ = values
        assert record.pod_uid is None and len(api.posts) == 1 and api.deletes == []
        if not present:
            api.pod = None
        observation = await recovery.inspect(record)
        assert observation.pod_present is present
        assert observation.code == ("present_unowned" if present else "absent")
        with pytest.raises(AppError, match="No returned Pod UID"):
            await recovery.prepare_cleanup(record)
        assert (await manager.scan()) == (record,) and api.deletes == []
        assert len(api.posts) == 1  # Neither inspection nor recovery replays creation.


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_local_forget_needs_explicit_review_but_no_connection_or_write_mode(
    tmp_path, unknown
):
    async with recovery_fixture(tmp_path, unknown=unknown) as (_, record, values):
        manager, _, api, *_ = values
        pod = api.pod.copy()
        count = len(api.deletes)
        recovery = NodeShellRecovery(manager.journal, None, AccessPolicy(True), lambda: False)
        try:
            review = await recovery.prepare_forget(record)
            assert review.action == "forget" and review.record == record
            proof = recovery.confirm(review)
            result = await recovery.forget(proof)
            assert result.state is MutationState.SUCCEEDED and "no remote Pod" in result.message
            assert api.pod == pod and len(api.deletes) == count and len(api.posts) == 1
            assert await manager.scan() == ()
            assert (await recovery.forget(proof)).state is MutationState.BLOCKED
        finally:
            await recovery.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [False, True])
async def test_absent_original_or_same_name_replacement_removes_only_local_record(
    tmp_path, replacement
):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        count = len(api.deletes)
        if replacement:
            api.pod["metadata"]["uid"] = "unrelated-replacement-uid"
        else:
            api.pod = None
        observed = await recovery.inspect(record)
        assert observed.code == ("replacement" if replacement else "absent")
        review = await recovery.prepare_cleanup(record)
        result = await recovery.cleanup(recovery.confirm(review))
        assert result.state is MutationState.SUCCEEDED and len(api.deletes) == count
        assert await manager.scan() == ()
        if replacement:
            assert api.pod["metadata"]["uid"] == "unrelated-replacement-uid"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["fingerprint", "namespace", "context", "selection", "closed"])
async def test_scope_mismatches_never_issue_delete(tmp_path, change):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, client, api, _, current, _ = values
        count = len(api.deletes)
        if change == "fingerprint":
            changed = replace(record, connection_fingerprint="f" * 64)
            lease = await manager.journal.acquire()
            try:
                await lease.write(changed)
            finally:
                await lease.close()
            record = changed
        elif change == "namespace":
            api.namespace_uid = "replaced-namespace"
        elif change == "context":
            client.context = replace(client.context, name="different-context")
        elif change == "selection":
            current[0] = False
        else:
            await client.close()
        with pytest.raises(AppError):
            await recovery.prepare_cleanup(record)
        assert len(api.deletes) == count
        assert (await manager.scan()) == (record,)


@pytest.mark.asyncio
async def test_read_only_recovery_can_inspect_but_cannot_prepare_or_start_delete(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, policy, *_ = values
        count = len(api.deletes)
        policy.tighten()
        assert (await recovery.inspect(record)).code == "present_owned"
        with pytest.raises(AppError, match="Read-only"):
            await recovery.prepare_cleanup(record)
        assert len(api.deletes) == count and await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_policy_tightening_after_review_blocks_recovered_delete(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, policy, *_ = values
        review = await recovery.prepare_cleanup(record)
        proof = recovery.confirm(review)
        policy.tighten()
        result = await recovery.cleanup(proof)
        assert result.state is MutationState.BLOCKED and len(api.deletes) == 1
        assert await manager.scan() == (record,)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cleanup", "forget"])
async def test_cancel_before_coroutine_entry_consumes_the_exact_review(tmp_path, action):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        prepare = recovery.prepare_cleanup if action == "cleanup" else recovery.prepare_forget
        review = await prepare(record)
        proof = recovery.confirm(review)
        operation = getattr(recovery, action)
        task = asyncio.create_task(operation(proof))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await operation(proof)).state is MutationState.BLOCKED
        with pytest.raises(AppError, match="exact current"):
            recovery.confirm(review)
        await recovery.close()
        assert len(api.deletes) == 1 and await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_invalid_confirmation_cannot_consume_or_change_a_valid_review(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_forget(record)
        proof = recovery.confirm(review)
        assert (
            await recovery.forget(Confirmation(uuid4(), uuid4()))
        ).state is MutationState.BLOCKED
        assert (await recovery.cleanup(proof)).state is MutationState.BLOCKED
        assert (await recovery.forget(proof)).state is MutationState.SUCCEEDED
        assert len(api.deletes) == 1 and await manager.scan() == ()


@pytest.mark.asyncio
async def test_changed_local_record_requires_new_capture_and_releases_lease(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        lease = await manager.journal.acquire()
        changed = replace(record, result_code="failed")
        try:
            await lease.write(changed)
        finally:
            await lease.close()
        with pytest.raises(AppError, match="record changed"):
            await recovery.prepare_forget(record)
        assert await manager.scan() == (changed,) and len(api.deletes) == 1


@pytest.mark.asyncio
async def test_delete_denial_retains_record_without_automatic_retry(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_cleanup(record)
        result = await recovery.cleanup(recovery.confirm(review))
        assert result.state is MutationState.DENIED and len(api.deletes) == 2
        (pending,) = await manager.scan()
        assert pending.pod_uid == record.pod_uid and api.pod is not None
        assert "private" not in result.message


@pytest.mark.asyncio
async def test_close_releases_retained_review_and_prohibits_later_forget(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_forget(record)
        proof = recovery.confirm(review)
        with pytest.raises(AppError, match="already retains"):
            await recovery.prepare_forget(record)
        await recovery.close()
        assert (await recovery.forget(proof)).state is MutationState.BLOCKED
        with pytest.raises(AppError, match="closed"):
            await recovery.prepare_forget(record)
        assert await manager.scan() == (record,) and len(api.deletes) == 1


@pytest.mark.asyncio
async def test_concurrent_preparation_cannot_replace_or_close_another_capture(
    tmp_path, monkeypatch
):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        original = manager.journal.acquire
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def held_acquire():
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return await original()

        monkeypatch.setattr(manager.journal, "acquire", held_acquire)
        first = asyncio.create_task(recovery.prepare_forget(record))
        await entered.wait()
        try:
            with pytest.raises(AppError, match="already retains"):
                await recovery.prepare_forget(record)
        finally:
            release.set()
            result = await asyncio.gather(first, return_exceptions=True)
            await recovery.close()
        assert len(result) == 1 and not isinstance(result[0], BaseException)
        assert calls == 1 and len(api.deletes) == 1
        assert await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_close_cancels_and_drains_held_local_preparation(tmp_path, monkeypatch):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        original = manager.journal.acquire
        entered = asyncio.Event()

        async def held_acquire():
            entered.set()
            await asyncio.Event().wait()
            return await original()

        monkeypatch.setattr(manager.journal, "acquire", held_acquire)
        task = asyncio.create_task(recovery.prepare_forget(record))
        await entered.wait()
        await recovery.close()
        assert task.done() and task.cancelled() and len(api.deletes) == 1
        monkeypatch.setattr(manager.journal, "acquire", original)
        assert await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_close_during_recovered_scope_recheck_sends_no_delete(tmp_path, monkeypatch):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, client, api, *_ = values
        review = await recovery.prepare_cleanup(record)
        proof = recovery.confirm(review)
        original = client.get_json
        entered = asyncio.Event()

        async def held_get(path, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
            return await original(path, *args, **kwargs)

        monkeypatch.setattr(client, "get_json", held_get)
        task = asyncio.create_task(recovery.cleanup(proof))
        await entered.wait()
        await recovery.close()
        assert task.done() and task.cancelled() and len(api.deletes) == 1
        assert await manager.scan() == (record,)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["kind", "name", "namespace", "uid"])
async def test_malformed_pod_observation_is_not_absence_or_replacement(tmp_path, fault):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        if fault == "kind":
            api.pod["kind"] = "WrongKind"
        elif fault == "uid":
            del api.pod["metadata"]["uid"]
        else:
            api.pod["metadata"][fault] = "different"
        with pytest.raises(AppError):
            await recovery.inspect(record)
        assert len(api.deletes) == 1 and await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_denied_get_is_not_interpreted_as_absence(tmp_path, monkeypatch):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, client, api, *_ = values
        original = client.get_json

        async def denied_get(path, *args, **kwargs):
            if "/pods/" in path:
                raise HttpProblem(403)
            return await original(path, *args, **kwargs)

        monkeypatch.setattr(client, "get_json", denied_get)
        with pytest.raises(HttpProblem):
            await recovery.inspect(record)
        assert len(api.deletes) == 1 and await manager.scan() == (record,)


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before_delete", "after_unlink"])
async def test_local_durability_failure_propagates_after_lease_drain(tmp_path, monkeypatch, when):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_cleanup(record)
        proof = recovery.confirm(review)
        api.delete_status = 200
        original = os.fsync

        def broken_sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode) and (
                when == "before_delete" or api.pod is None
            ):
                raise OSError("synthetic-private-filesystem-value")
            return original(descriptor)

        monkeypatch.setattr(os, "fsync", broken_sync)
        with pytest.raises(RecoveryJournalError, match="durability failed") as error:
            await recovery.cleanup(proof)
        assert "private" not in str(error.value)
        assert len(api.deletes) == (1 if when == "before_delete" else 2)
        monkeypatch.setattr(os, "fsync", original)
        records = await manager.scan()
        if when == "before_delete":
            assert len(records) == 1 and records[0].pod_uid == record.pod_uid
            assert api.pod is not None
        else:
            assert records == () and api.pod is None


@pytest.mark.asyncio
async def test_prepared_forget_coroutine_cannot_change_state_after_owner_close(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_forget(record)
        operation = recovery.forget(recovery.confirm(review))
        await recovery.close()
        assert (await operation).state is MutationState.BLOCKED
        assert len(api.deletes) == 1 and await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_prepared_cleanup_coroutine_cannot_delete_after_owner_close(tmp_path):
    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_cleanup(record)
        operation = recovery.cleanup(recovery.confirm(review))
        await recovery.close()
        assert (await operation).state is MutationState.BLOCKED
        assert len(api.deletes) == 1 and await manager.scan() == (record,)


@pytest.mark.asyncio
async def test_delete_conflict_does_not_retry_and_retains_the_same_uid(tmp_path, monkeypatch):
    from kuberich.services import node_shell_recovery

    async with recovery_fixture(tmp_path) as (recovery, record, values):
        manager, _, api, *_ = values
        review = await recovery.prepare_cleanup(record)
        api.delete_status = 409
        monkeypatch.setattr(node_shell_recovery, "RECOVERY_SECONDS", 0.02)
        result = await recovery.cleanup(recovery.confirm(review))
        assert result.state is MutationState.CONFLICT and len(api.deletes) == 2
        (pending,) = await manager.scan()
        assert pending.pod_uid == record.pod_uid and api.pod is not None
