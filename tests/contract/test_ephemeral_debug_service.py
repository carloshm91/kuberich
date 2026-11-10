"""HTTP and ownership evidence for reviewed append and existing-process attach."""

import asyncio
from contextlib import suppress
from dataclasses import replace

import pytest

from kuberich.domain.connections import HttpProblem
from kuberich.domain.mutations import MutationState
from kuberich.errors import AppError
from kuberich.services.ephemeral_debug import EphemeralDebugManager
from kuberich.services.mutations import MutationManager
from tests.support.ephemeral_debug_service import OPTIONS, PODS, debug_source


async def append(source, options=OPTIONS):
    review = await source.prepare(options)
    return await source.execute(source.confirm(review))


@pytest.mark.asyncio
async def test_exact_dry_run_review_append_receipt_then_private_attach(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        review = await source.prepare(OPTIONS)
        assert "ephemeralContainers" not in api.pod["spec"]
        proof = source.confirm(review)
        admitted = source.execute(proof)
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        mutations = MutationManager()
        # The already-consumed coroutine owns exactly one append.
        assert (await admitted).state is MutationState.SUCCEEDED
        assert source.observation.code == "ready"
        assert [r[2] for r in api.requests] == [
            {"fieldValidation": "Strict", "dryRun": "All"},
            {"fieldValidation": "Strict"},
        ]
        assert api.requests[0][3] == api.requests[1][3]
        assert api.requests[1][3][:2] == [
            {"op": "test", "path": "/metadata/uid", "value": "pod-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "opaque-before"},
        ]
        shell, request = await source.prepare_shell(OPTIONS.name)
        assert not request.path.exists()
        async with shell.stage(request) as command:
            assert request.path.exists()
            assert command.argv[-1] == "api" and "attach" in command.argv
            assert "--container=debug-one" in command.argv
            with pytest.raises(AppError, match="already"):
                await source.prepare_shell(OPTIONS.name)
        assert not request.path.exists()
        assert source.observation.remote.rows[0].state == "running"
        assert len(api.pod["spec"]["ephemeralContainers"]) == 1
        assert all(r[0] == "PATCH" for r in api.requests)
        await mutations.close()


@pytest.mark.asyncio
async def test_mutation_manager_registers_and_drains_production_source(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        manager = MutationManager()
        review = await source.prepare(OPTIONS)
        identity = manager.start(source, source.confirm(review))
        assert (await manager.wait(identity)).state is MutationState.SUCCEEDED
        assert manager.records[0].effects == review.effects
        assert source.observation.outcomes[0].append.target.uid == "pod-uid"
        await manager.stop_for_client(source.client)
        await manager.close()
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_readonly_inspects_but_blocks_all_effectful_preparation(tmp_path):
    async with debug_source(tmp_path, read_only=True) as (source, api, _):
        assert (await source.observe()).remote.rows == ()
        source.start()
        with pytest.raises(AppError, match="Read-only"):
            await source.prepare(OPTIONS)
        with pytest.raises(AppError, match="Read-only"):
            await source.prepare_shell("existing")
        assert api.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "version", "target", "readonly", "generation"])
async def test_fresh_revalidation_never_rebases_review(tmp_path, change):
    async with debug_source(tmp_path) as (source, api, current):
        review = await source.prepare(OPTIONS)
        proof = source.confirm(review)
        if change == "uid":
            api.pod["metadata"]["uid"] = "replacement"
        elif change == "version":
            api.pod["metadata"]["resourceVersion"] = "changed"
        elif change == "target":
            api.pod["status"]["containerStatuses"][0]["restartCount"] = 1
        elif change == "readonly":
            source.policy.tighten()
        else:
            current[0] = False
        result = await source.execute(proof)
        assert result.state in {MutationState.BLOCKED, MutationState.CONFLICT}
        assert len(api.requests) == 1
        assert "ephemeralContainers" not in api.pod["spec"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 415, 422, 429, 500])
async def test_apply_refusals_do_not_retry_or_expose_status_body(tmp_path, status):
    async with debug_source(tmp_path) as (source, api, _):
        review = await source.prepare(OPTIONS)
        api.status = status
        result = await source.execute(source.confirm(review))
        assert result.state is not MutationState.SUCCEEDED
        assert "server-secret" not in result.message
        assert len(api.requests) == 2
        assert "ephemeralContainers" not in api.pod["spec"]


@pytest.mark.asyncio
async def test_unknown_commit_is_never_adopted_for_attach(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        api.mode = "drop"
        result = await append(source)
        assert result.state is MutationState.UNCERTAIN
        assert source.observation.outcomes[-1].append is None
        assert (await source.observe()).remote.rows[0].state == "running"
        with pytest.raises(AppError, match="no verified"):
            await source.prepare_shell(OPTIONS.name)
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_known_append_with_unverified_profile_stays_permanent_and_blocks_attach(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        api.mode = "bad-profile"
        result = await append(source)
        assert result.state is MutationState.SUCCEEDED
        assert source.observation.outcomes[-1].append.name == OPTIONS.name
        assert "server-secret" not in repr(source.observation)
        with pytest.raises(AppError, match="no verified"):
            await source.prepare_shell(OPTIONS.name)
        assert len(api.pod["spec"]["ephemeralContainers"]) == 1


@pytest.mark.asyncio
async def test_cancel_after_commit_drains_receipt_under_repeated_cancellation(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        api.mode = "stall"
        review = await source.prepare(OPTIONS)
        task = asyncio.create_task(source.execute(source.confirm(review)))
        await api.entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done()
        api.release.set()
        assert (await task).state is MutationState.SUCCEEDED
        assert source.observation.outcomes[-1].append.name == OPTIONS.name
        assert source.operation_count == 0
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_cancel_fresh_read_is_known_unsent(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        review = await source.prepare(OPTIONS)
        api.block_read = True
        task = asyncio.create_task(source.execute(source.confirm(review)))
        await api.read_entered.wait()
        task.cancel()
        assert (await task).state is MutationState.CANCELLED
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_failed_reads_retain_stale_rows_and_collector_has_no_overlapping_gets(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        await append(source)
        observed = await source.observe()
        api.read_status = 403
        with pytest.raises(HttpProblem):
            await source.observe()
        assert source.observation.stale
        assert source.observation.remote == observed.remote
        api.read_status = None
        api.block_read = True
        source.start()
        await api.read_entered.wait()
        manual = asyncio.create_task(source.observe())
        await asyncio.sleep(0.01)
        assert api.maximum_reads == 1
        api.read_release.set()
        await manual
        assert api.maximum_reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "target", "debug", "readonly"])
async def test_active_attach_stops_locally_on_observed_identity_or_policy_change(tmp_path, change):
    async with debug_source(tmp_path) as (source, api, _):
        await append(source)
        shell, request = await source.prepare_shell(OPTIONS.name)
        entered = asyncio.Event()

        async def terminal():
            async with shell.stage(request):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(terminal())
        await entered.wait()
        if change == "uid":
            api.pod["metadata"]["uid"] = "replacement"
        elif change == "target":
            api.pod["status"]["containerStatuses"][0]["restartCount"] = 1
        elif change == "debug":
            api.pod["status"]["ephemeralContainerStatuses"][0]["containerID"] = "new-instance"
        else:
            source.policy.tighten()
        with suppress(AppError):
            await source.observe()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and not request.path.exists()
        assert len(api.requests) == 2
        assert api.pod["spec"]["ephemeralContainers"][0]["name"] == OPTIONS.name


@pytest.mark.asyncio
async def test_manager_retains_owner_until_ongoing_append_drained_before_client_close(tmp_path):
    async with debug_source(tmp_path) as (seed, api, current):
        manager = EphemeralDebugManager()
        source = manager.create(
            seed.client,
            PODS,
            seed.target,
            seed.policy,
            lambda: current[0],
            environment={},
            directory=tmp_path,
        )
        api.mode = "stall"
        review = await source.prepare(OPTIONS)
        write = asyncio.create_task(source.execute(source.confirm(review)))
        await api.entered.wait()
        closing = asyncio.create_task(manager.close_for_client(seed.client))
        await asyncio.sleep(0.01)
        assert manager.active_count == 1 and not closing.done()
        closing.cancel()
        api.release.set()
        await closing
        assert manager.active_count == 0
        assert (await write).state is MutationState.SUCCEEDED
        assert manager.records[-1].append.name == OPTIONS.name
        assert seed.client.configuration is not None
        await manager.close()


@pytest.mark.asyncio
async def test_new_draft_supersedes_deferred_execute_without_releasing_other_write_lease(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        first = await source.prepare(OPTIONS)
        old = source.execute(source.confirm(first))
        second = await source.prepare(replace(OPTIONS, name="debug-two"))
        api.mode = "stall"
        write = asyncio.create_task(source.execute(source.confirm(second)))
        await api.entered.wait()
        assert (await old).state is MutationState.BLOCKED
        with pytest.raises(AppError, match="already active"):
            await source.prepare(replace(OPTIONS, name="debug-three"))
        api.release.set()
        assert (await write).state is MutationState.SUCCEEDED
        assert len(api.requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["discovery", "dry-refuse"])
async def test_preparation_refusal_never_enables_confirmation(tmp_path, failure):
    async with debug_source(tmp_path) as (source, api, _):
        if failure == "discovery":
            api.discovery = False
        else:
            api.mode = failure
        with pytest.raises(AppError):
            await source.prepare(OPTIONS)
        assert source.intent is None
        assert "ephemeralContainers" not in api.pod["spec"]


@pytest.mark.asyncio
async def test_prepare_reserves_single_review_before_await_and_foreign_review_is_rejected(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        api.block_read = True
        preparing = asyncio.create_task(source.prepare(OPTIONS))
        await api.read_entered.wait()
        with pytest.raises(AppError, match="already active"):
            await source.prepare(OPTIONS)
        api.read_release.set()
        review = await preparing
        with pytest.raises(AppError, match="exact"):
            source.confirm(replace(review))
        assert (
            await append(source, replace(OPTIONS, name="debug-two"))
        ).state is MutationState.SUCCEEDED
        assert len(api.requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [(403, MutationState.DENIED), (404, MutationState.NOT_FOUND), (500, MutationState.REJECTED)],
)
async def test_revalidation_read_refusal_is_recorded_as_unsent(tmp_path, status, expected):
    async with debug_source(tmp_path) as (source, api, _):
        review = await source.prepare(OPTIONS)
        api.read_status = status
        result = await source.execute(source.confirm(review))
        assert result.state is expected
        assert source.observation.outcomes[-1].result == result
        assert source.observation.outcomes[-1].append is None
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_client_request_timeout_bounds_uncertain_append_without_replay(tmp_path):
    async with debug_source(tmp_path, timeout=0.1) as (source, api, _):
        api.mode = "stall"
        async with asyncio.timeout(2):
            result = await append(source)
        assert result.state is MutationState.UNCERTAIN
        assert source.observation.outcomes[-1].append is None
        assert len(api.pod["spec"]["ephemeralContainers"]) == 1
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_startup_deadline_leaves_known_append_and_pending_remote_state(tmp_path, monkeypatch):
    import kuberich.services.ephemeral_debug as module

    assert module.STARTUP_SECONDS == 60
    monkeypatch.setattr(module, "STARTUP_SECONDS", 0.03)
    async with debug_source(tmp_path) as (source, api, _):
        api.running = False
        result = await append(source)
        assert result.state is MutationState.PARTIAL
        assert source.observation.code == "startup_timeout"
        assert source.observation.outcomes[-1].result.state is MutationState.SUCCEEDED
        assert source.observation.outcomes[-1].append.name == OPTIONS.name
        assert source.observation.remote.rows[0].state == "waiting"
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_image_failure_keeps_known_append_without_privilege_or_image_fallback(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        api.running = False
        api.wait_reason = "ImagePullBackOff"
        assert (await append(source)).state is MutationState.PARTIAL
        assert source.observation.code == "start_failed"
        assert source.observation.outcomes[-1].append.name == OPTIONS.name
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_reattach_prior_receipt_after_repeated_append_and_no_remote_cleanup(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        await append(source)
        await append(source, replace(OPTIONS, name="debug-two"))
        for name in (OPTIONS.name, "debug-two", OPTIONS.name):
            shell, request = await source.prepare_shell(name)
            async with shell.stage(request):
                assert request.path.exists()
            assert not request.path.exists()
        assert len(api.requests) == 4
        assert all(r[0] == "PATCH" for r in api.requests)


@pytest.mark.asyncio
async def test_terminal_double_stage_and_instance_changed_before_stage_refuse(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        await append(source)
        shell, request = await source.prepare_shell(OPTIONS.name)
        async with shell.stage(request):
            with pytest.raises(AppError, match="already"):
                async with shell.stage(request):
                    pytest.fail("second terminal must never start")
        shell, request = await source.prepare_shell(OPTIONS.name)
        api.pod["status"]["ephemeralContainerStatuses"][0]["containerID"] = "changed"
        with pytest.raises(AppError, match="changed"):
            async with shell.stage(request):
                pytest.fail("stale instance must never attach")
        assert not request.path.exists()


@pytest.mark.asyncio
async def test_manager_single_owner_readonly_retired_client_and_closed_manager(tmp_path):
    async with debug_source(tmp_path, read_only=True) as (seed, _, current):
        manager = EphemeralDebugManager()
        kwargs = {"environment": {}, "directory": tmp_path}
        source = manager.create(
            seed.client, PODS, seed.target, seed.policy, lambda: current[0], **kwargs
        )
        assert manager.records == ()
        await source.observe()
        with pytest.raises(AppError, match="active"):
            manager.create(
                seed.client, PODS, seed.target, seed.policy, lambda: current[0], **kwargs
            )
        await manager.close_for_client(seed.client)
        with pytest.raises(AppError, match="active"):
            manager.create(
                seed.client, PODS, seed.target, seed.policy, lambda: current[0], **kwargs
            )
        await manager.close()
        await source.close()


@pytest.mark.asyncio
async def test_retained_outcomes_and_owner_records_are_bounded_and_listeners_are_removable(
    tmp_path,
):
    async with debug_source(tmp_path) as (source, api, _):
        observed = []
        remove = source.subscribe(observed.append)

        def broken(observation):
            raise ValueError("untrusted consumer failed")

        source.subscribe(broken)
        for i in range(34):
            assert (
                await append(source, replace(OPTIONS, name=f"debug-{i}"))
            ).state is MutationState.SUCCEEDED
        assert len(source.observation.outcomes) == 32
        assert source.observation.outcomes[0].name == "debug-2"
        remove()
        before = len(observed)
        await source.observe()
        assert len(observed) == before
        assert len(api.pod["spec"]["ephemeralContainers"]) == 34


@pytest.mark.asyncio
async def test_launch_checks_named_running_session_beyond_display_cap(tmp_path):
    async with debug_source(tmp_path) as (source, api, _):
        api.pod["spec"]["ephemeralContainers"] = [
            {"name": f"old-{i}", "image": "synthetic"} for i in range(256)
        ]
        assert (await append(source)).state is MutationState.SUCCEEDED
        assert source.observation.code == "ready"
        assert len(source.observation.remote.rows) == 256
        assert source.observation.remote.incomplete
        shell, request = await source.prepare_shell(OPTIONS.name)
        async with shell.stage(request):
            assert request.path.exists()
        assert not request.path.exists()
