"""Helm service authority, fresh disclosure and non-replayed rollback contracts."""

import asyncio
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.domain.helm import (
    HelmDocumentKind,
    HelmDriver,
    HelmOutcome,
    HelmProblem,
    HelmReleaseKey,
    HelmRollbackOptions,
)
from kuberich.errors import AppError
from kuberich.services import helm as helm_service
from kuberich.services.delegation import ConnectionFile
from kuberich.services.processes import ProcessRunner
from tests.support.helm import PRIVATE_VALUE, calls, helm_source, release


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", list(HelmDriver))
async def test_actual_cli_and_http_end_to_end_list_inspect_documents_and_rollback(tmp_path, driver):
    async with helm_source(tmp_path, real_cli=True, driver=driver) as (
        service,
        api,
        _,
        request,
        _,
        _,
        record,
    ):
        listing = await service.list(request)
        inspection = await service.inspect(request, listing.releases[0])
        assert PRIVATE_VALUE not in repr(inspection)
        assert inspection.target.head.uid == "owned-team-demo-3"
        assert inspection.status.notes_present and inspection.status.description_present
        for kind in HelmDocumentKind:
            document = await service.document(inspection.target, 1, kind)
            assert not document.disclosed and PRIVATE_VALUE not in document.text
            intent = await service.prepare_disclosure(inspection.target, 1, kind)
            approval = service.confirm(intent)
            disclosed = await service.disclose(approval)
            assert disclosed.disclosed and PRIVATE_VALUE in disclosed.text
            assert PRIVATE_VALUE not in repr(disclosed)
            with pytest.raises(HelmProblem, match="expired"):
                await service.disclose(approval)
        intent = await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        assert intent.selected.revision == 1 and intent.hooks[0].events == ("pre-rollback",)
        result = await service.rollback(service.confirm(intent))
        assert result.outcome is HelmOutcome.SUCCEEDED and result.observed.revision == 4
        assert result.may_have_started and PRIVATE_VALUE not in repr(result)
        commands = calls(record)
        assert len([item for item in commands if "version" in item["argv"]]) == 1
        rollback = next(item for item in commands if "rollback" in item["argv"])
        assert "--no-hooks=true" in rollback["argv"] and "--history-max=0" in rollback["argv"]
        assert all(
            item["config_mode"] == 0o600 for item in commands if item["argv"][0] != "version"
        )
        assert all(
            ("/secrets" if driver is HelmDriver.SECRET else "/configmaps") in path
            for path, _, _ in api.requests
        )
        assert service.operation_count == 0


@pytest.mark.asyncio
async def test_readonly_refuses_rollback_before_any_transport_or_approval(tmp_path):
    async with helm_source(tmp_path, read_only=True) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        before = tuple(adapter.calls)
        with pytest.raises(AppError, match="Read-only"):
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        assert tuple(adapter.calls) == before
        document = await service.document(inspection.target, 1, HelmDocumentKind.VALUES)
        assert document.text == "[REDACTED]"


@pytest.mark.asyncio
async def test_exact_prepared_object_and_exact_owned_approval_only(tmp_path):
    async with helm_source(tmp_path) as (service, _, _, request, *_):
        inspection = await service.inspect(request, release())
        intent = await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        with pytest.raises(HelmProblem, match="expired"):
            service.confirm(replace(intent))
        approval = service.confirm(intent)
        with pytest.raises(HelmProblem, match="expired"):
            service.confirm(intent)
        with pytest.raises(HelmProblem, match="expired"):
            await service.disclose(replace(approval))
        with pytest.raises(HelmProblem, match="expired"):
            await service.disclose(approval)
        fresh = await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        assert (await service.disclose(service.confirm(fresh))).disclosed


@pytest.mark.asyncio
async def test_new_review_and_cancel_expire_token_but_preserve_parent_inspection(tmp_path):
    async with helm_source(tmp_path) as (service, _, _, request, *_):
        inspection = await service.inspect(request, release())
        first = await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        approval = service.confirm(first)
        await service.prepare_disclosure(inspection.target, 2, HelmDocumentKind.VALUES)
        with pytest.raises(HelmProblem):
            await service.disclose(approval)
        second = await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        approval = service.confirm(second)
        service.cancel_review()
        with pytest.raises(HelmProblem):
            await service.disclose(approval)
        assert not (await service.document(inspection.target, 1, HelmDocumentKind.NOTES)).disclosed


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new-head", "uid", "rv", "status", "missing"])
async def test_review_fails_closed_after_storage_changes_without_spawn(tmp_path, change):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        if change == "new-head":
            head = adapter.identities[-1]
            adapter.identities = (
                *adapter.identities,
                replace(head, revision=4, storage_name="sh.helm.release.v1.demo.v4"),
            )
        elif change == "missing":
            adapter.identities = adapter.identities[1:]
        else:
            field = {"uid": "uid", "rv": "resource_version", "status": "status"}[change]
            value = "failed" if change == "status" else "replacement"
            adapter.identities = (
                replace(adapter.identities[0], **{field: value}),
                *adapter.identities[1:],
            )
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.STALE and not result.may_have_started
        assert "rollback" not in adapter.calls
        with pytest.raises(HelmProblem):
            await service.rollback(approval)


@pytest.mark.asyncio
async def test_concurrent_rollback_consumes_approval_before_await(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(
                inspection.target, 1, HelmRollbackOptions(True, True, 10)
            )
        )
        adapter.block = "storage-history"
        adapter.started.clear()
        operation = asyncio.create_task(service.rollback(approval))
        await adapter.started.wait()
        with pytest.raises(HelmProblem, match="expired"):
            await service.rollback(approval)
        adapter.release.set()
        assert (await operation).outcome is HelmOutcome.SUCCEEDED
        assert adapter.calls.count("rollback") == 1


@pytest.mark.asyncio
async def test_policy_tightening_after_confirmation_prevents_spawn_and_consumes_approval(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        service.policy.tighten()
        with pytest.raises(AppError, match="Read-only"):
            await service.rollback(approval)
        assert "rollback" not in adapter.calls
        with pytest.raises(HelmProblem):
            await service.rollback(approval)


@pytest.mark.asyncio
async def test_late_read_after_context_change_is_refused(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, current, *_):
        adapter.after = lambda _: current.__setitem__(0, False)
        with pytest.raises(HelmProblem, match="identity changed"):
            await service.list(request)
        assert service.operation_count == 0


@pytest.mark.asyncio
async def test_disclosure_is_fresh_and_rechecks_after_document_read(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.VALUES)
        )

        def replace_selected(operation):
            if operation == "document":
                adapter.identities = (
                    replace(adapter.identities[0], resource_version="changed"),
                    *adapter.identities[1:],
                )

        adapter.after = replace_selected
        with pytest.raises(HelmProblem, match="identity changed"):
            await service.disclose(approval)
        with pytest.raises(HelmProblem):
            await service.disclose(approval)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem",
    [
        HelmProblem("timeout", "Safe timeout."),
        HelmProblem("forbidden", "Safe refusal."),
        AppError("Safe failure."),
    ],
)
async def test_uncertain_rollback_failure_is_not_replayed_or_claimed_partial_success(
    tmp_path, problem
):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )

        def fail_at_spawn(operation):
            if operation == "rollback":
                adapter.problem = problem

        adapter.after = fail_at_spawn
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.UNKNOWN and result.may_have_started
        assert adapter.calls.count("rollback") == 1 and result.observed is None
        with pytest.raises(HelmProblem):
            await service.rollback(approval)


@pytest.mark.asyncio
async def test_exit_zero_without_observed_new_revision_is_unknown(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        adapter.rollback_effect = False
        result = await service.rollback(
            service.confirm(
                await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
            )
        )
        assert result.outcome is HelmOutcome.UNKNOWN and result.observed is None


@pytest.mark.asyncio
async def test_actual_nonzero_rollback_with_verified_failed_new_revision_is_failed(tmp_path):
    async with helm_source(tmp_path, real_cli=True) as (
        service,
        _,
        _,
        request,
        _,
        scenario,
        record,
    ):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions(True))
        )
        scenario.write_text(json.dumps({"rollback_mode": "rollback-error"}))
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.FAILED and result.may_have_started
        assert result.observed.revision == 4 and result.observed.status == "failed"
        assert "resources may have changed" in result.message and PRIVATE_VALUE not in repr(result)
        assert sum("rollback" in item["argv"] for item in calls(record)) == 1
        with pytest.raises(HelmProblem):
            await service.rollback(approval)


@pytest.mark.asyncio
async def test_actual_missing_tool_at_write_boundary_proves_no_write_started(tmp_path):
    async with helm_source(tmp_path, real_cli=True) as (service, _, _, request, _, _, record):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        Path(service.settings.executable).unlink()
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.BLOCKED and not result.may_have_started
        assert "install supported" in result.message
        assert not any("rollback" in item["argv"] for item in calls(record))


@pytest.mark.asyncio
async def test_staging_error_before_write_is_blocked_with_no_effect(tmp_path, monkeypatch):

    async with helm_source(tmp_path, real_cli=True) as (service, _, _, request, _, _, record):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )

        def fail_write(self, configuration):
            raise OSError("synthetic-private-helm-value")

        monkeypatch.setattr(ConnectionFile, "write", fail_write)
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.BLOCKED and not result.may_have_started
        assert PRIVATE_VALUE not in repr(result) and not any(
            "rollback" in item["argv"] for item in calls(record)
        )


@pytest.mark.asyncio
async def test_close_drains_detached_viewer_tasks_before_adapter_close(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        adapter.block = "document"
        adapter.started.clear()
        viewer = asyncio.create_task(service.document(inspection.target, 1, HelmDocumentKind.NOTES))
        await adapter.started.wait()
        await service.close()
        with pytest.raises(asyncio.CancelledError):
            await viewer
        assert adapter.closed and service.operation_count == 0
        await service.close()
        with pytest.raises(HelmProblem):
            await service.list(request)


@pytest.mark.asyncio
async def test_invalidate_retires_prior_targets_and_list_request_driver_must_match(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        with pytest.raises(HelmProblem):
            await service.list(
                replace(request, scope=replace(request.scope, driver=HelmDriver.CONFIGMAP))
            )
        assert not adapter.calls
        inspection = await service.inspect(request, release())
        service.invalidate()
        with pytest.raises(HelmProblem, match="current inspection"):
            await service.document(inspection.target, 1, HelmDocumentKind.NOTES)
        with pytest.raises(HelmProblem, match="positive"):
            await service.document(inspection.target, True, HelmDocumentKind.NOTES)


@pytest.mark.asyncio
async def test_driver_policy_is_enforced_for_injected_transport_before_calls(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        service.settings = replace(service.settings, driver=HelmDriver.CONFIGMAP)
        with pytest.raises(HelmProblem) as failure:
            await service.list(request)
        assert failure.value.kind == "unsupported-driver" and not adapter.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["namespace", "empty", "latest", "replaced", "history", "status"])
async def test_inspection_refuses_list_storage_status_and_history_inconsistency(tmp_path, fault):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        selected = release()
        if fault == "namespace":
            selected = release(key=HelmReleaseKey("other", "demo"))
        elif fault == "empty":
            adapter.identities = ()
        elif fault == "latest":
            selected = release(2)
        elif fault == "replaced":

            def recreate(operation):
                if operation == "history":
                    adapter.identities = (
                        *adapter.identities[:-1],
                        replace(adapter.identities[-1], uid="replacement"),
                    )

            adapter.after = recreate
        elif fault == "history":
            original = adapter.history

            async def missing_head(*args):
                history = await original(*args)
                return replace(history, revisions=history.revisions[:-1])

            adapter.history = missing_head
        else:
            original = adapter.status

            async def different_status(*args):
                return replace(await original(*args), status="failed")

            adapter.status = different_status
        with pytest.raises(HelmProblem, match="identity changed"):
            await service.inspect(request, selected)


@pytest.mark.asyncio
async def test_inspection_metadata_authority_is_bounded_and_duplicate_does_not_charge_twice(
    tmp_path,
):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        await service.inspect(request, release())
        await service.inspect(request, release())
        for number in range(1, 32):
            adapter.identities = (
                *adapter.identities[:-1],
                replace(adapter.identities[-1], uid=f"recreated-{number}"),
            )
            await service.inspect(request, release())
        adapter.identities = (
            *adapter.identities[:-1],
            replace(adapter.identities[-1], uid="over-limit"),
        )
        with pytest.raises(HelmProblem, match="Too many"):
            await service.inspect(request, release())


@pytest.mark.asyncio
async def test_identity_change_between_list_and_exact_get_refuses_default_document(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())

        def update(operation):
            if operation == "storage-get":
                adapter.identities = (
                    replace(adapter.identities[0], resource_version="changed"),
                    *adapter.identities[1:],
                )

        adapter.after = update
        with pytest.raises(HelmProblem):
            await service.document(inspection.target, 1, HelmDocumentKind.VALUES)


@pytest.mark.asyncio
async def test_default_document_get_rechecks_storage_after_cli_read(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())

        def update(operation):
            if operation == "document":
                adapter.identities = (
                    replace(adapter.identities[0], resource_version="changed"),
                    *adapter.identities[1:],
                )

        adapter.after = update
        with pytest.raises(HelmProblem):
            await service.document(inspection.target, 1, HelmDocumentKind.VALUES)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["history", "status", "after-status"])
async def test_rollback_preparation_revalidates_history_selected_status_and_storage(
    tmp_path, fault
):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        if fault == "history":
            original = adapter.history

            async def omitted(*args):
                result = await original(*args)
                return replace(result, revisions=result.revisions[1:])

            adapter.history = omitted
        elif fault == "status":
            original = adapter.status

            async def changed(*args):
                return replace(await original(*args), status="failed")

            adapter.status = changed
        else:

            def update(operation):
                if operation == "status":
                    adapter.identities = (
                        replace(adapter.identities[0], resource_version="changed"),
                        *adapter.identities[1:],
                    )

            adapter.after = update
        with pytest.raises(HelmProblem):
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        assert "rollback" not in adapter.calls


@pytest.mark.asyncio
async def test_disclosure_preparation_expiry_during_await_rejects_late_review(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        adapter.block = "storage-history"
        adapter.started.clear()
        operation = asyncio.create_task(
            service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        )
        await adapter.started.wait()
        service.cancel_review()
        adapter.release.set()
        with pytest.raises(HelmProblem, match="expired"):
            await operation


@pytest.mark.asyncio
async def test_wrong_operation_consumes_exact_approval_and_selected_recreation_refuses_disclosure(
    tmp_path,
):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        )
        with pytest.raises(HelmProblem, match="expired"):
            await service.rollback(approval)
        with pytest.raises(HelmProblem, match="expired"):
            await service.disclose(approval)
        approval = service.confirm(
            await service.prepare_disclosure(inspection.target, 1, HelmDocumentKind.NOTES)
        )
        adapter.identities = (
            replace(adapter.identities[0], uid="recreated"),
            *adapter.identities[1:],
        )
        with pytest.raises(HelmProblem, match="identity changed"):
            await service.disclose(approval)


@pytest.mark.asyncio
async def test_whole_preparation_timeout_and_rollback_timeout_before_write(tmp_path, monkeypatch):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        monkeypatch.setattr(helm_service, "MAX_OPERATION_SECONDS", 0.01)
        adapter.block = "storage-history"
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.BLOCKED and not result.may_have_started
        adapter.block = "list"
        with pytest.raises(HelmProblem) as problem:
            await service.list(request)
        assert problem.value.kind == "timeout"


@pytest.mark.asyncio
async def test_close_owner_drains_even_when_caller_is_cancelled_repeatedly(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        closing_started, release_close = asyncio.Event(), asyncio.Event()

        async def close():
            closing_started.set()
            await release_close.wait()
            adapter.closed = True

        adapter.close = close
        operation = asyncio.create_task(service.close())
        await closing_started.wait()
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
        release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert adapter.closed and service.operation_count == 0
        with pytest.raises(HelmProblem):
            await service.list(request)


@pytest.mark.asyncio
async def test_concurrent_actor_revision_jump_cannot_be_claimed_as_rollback_success(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )

        def revision_jump(operation):
            if operation == "list":
                adapter.identities = (
                    *adapter.identities[:-1],
                    replace(
                        adapter.identities[-1],
                        revision=5,
                        storage_name="sh.helm.release.v1.demo.v5",
                    ),
                )

        adapter.after = revision_jump
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.UNKNOWN and result.observed is None


@pytest.mark.asyncio
async def test_caller_cancel_after_write_boundary_records_uncertainty_and_drains(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        assert service.last_rollback is None
        adapter.block = "rollback"
        adapter.started.clear()
        operation = asyncio.create_task(service.rollback(approval))
        async with asyncio.timeout(2):
            while "rollback" not in adapter.calls:
                await asyncio.sleep(0)
        assert service.last_rollback.outcome is HelmOutcome.UNKNOWN
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert service.operation_count == 0 and service.last_rollback.may_have_started
        assert "cancellation does not undo" in service.last_rollback.message
        assert not (await service.document(inspection.target, 1, HelmDocumentKind.NOTES)).disclosed
        assert service.last_rollback.outcome is HelmOutcome.UNKNOWN


@pytest.mark.asyncio
@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_immediate_invalidate_does_not_leave_unawaited_nested_coroutine(tmp_path):
    import gc

    async with helm_source(tmp_path) as (service, _, _, request, *_):
        operation = asyncio.create_task(service.list(request))
        await asyncio.sleep(0)
        service.invalidate()
        service.invalidate()
        with pytest.raises(asyncio.CancelledError):
            await operation
        await service.close()
        gc.collect()
        assert service.operation_count == 0


@pytest.mark.asyncio
async def test_actual_write_timeout_records_unknown_and_does_not_refresh_or_replay(
    tmp_path, monkeypatch
):
    async with helm_source(tmp_path, real_cli=True) as (
        service,
        _,
        _,
        request,
        _,
        scenario,
        _,
    ):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        scenario.write_text(json.dumps({"rollback_mode": "sleep"}))
        original = ProcessRunner.capture

        async def deadline(self, command, *, timeout=30, guard=None):
            return await original(
                self, command, timeout=0.1 if "rollback" in command.argv else timeout, guard=guard
            )

        monkeypatch.setattr(ProcessRunner, "capture", deadline)
        loop = asyncio.get_running_loop()
        spawn = loop.subprocess_exec
        launches = []

        async def observe_spawn(protocol_factory, *argv, **options):
            transport, protocol = await spawn(protocol_factory, *argv, **options)
            launches.append((argv, transport))
            return transport, protocol

        monkeypatch.setattr(loop, "subprocess_exec", observe_spawn)
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.UNKNOWN and result.may_have_started
        assert service.last_rollback is result
        # The deadline can expire before Python reaches the fixture's log write.
        # A successful OS spawn independently proves one launch without a replay.
        assert len(launches) == 1 and "rollback" in launches[0][0]
        transport = launches[0][1]
        assert transport.get_returncode() is not None
        with pytest.raises(ProcessLookupError):
            os.kill(transport.get_pid(), 0)
        assert service.operation_count == 0
        assert not list(Path(service.client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_actual_staging_cancel_proves_write_not_started_and_drains_file(
    tmp_path, monkeypatch
):
    async with helm_source(tmp_path, real_cli=True) as (service, _, _, request, _, _, record):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        started, release_write = threading.Event(), threading.Event()
        original = ConnectionFile.write

        def block_write(self, configuration):
            original(self, configuration)
            started.set()
            release_write.wait(3)

        monkeypatch.setattr(ConnectionFile, "write", block_write)
        operation = asyncio.create_task(service.rollback(approval))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            operation.cancel()
            await asyncio.sleep(0.02)
            assert not operation.done()
        finally:
            release_write.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert (
            service.last_rollback.outcome is HelmOutcome.BLOCKED
            and not service.last_rollback.may_have_started
        )
        assert not any("rollback" in item["argv"] for item in calls(record))
        assert not list(Path(service.client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_actual_launched_write_cancel_keeps_unknown_and_drains_process_before_file(tmp_path):
    async with helm_source(tmp_path, real_cli=True) as (
        service,
        _,
        _,
        request,
        _,
        scenario,
        record,
    ):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )
        scenario.write_text(json.dumps({"rollback_mode": "sleep"}))
        operation = asyncio.create_task(service.rollback(approval))
        marker = Path(str(record) + ".child")
        async with asyncio.timeout(3):
            while not marker.exists():
                await asyncio.sleep(0.01)
        assert list(Path(service.client.directory.name).glob("helm-*"))
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert (
            service.last_rollback.outcome is HelmOutcome.UNKNOWN
            and service.last_rollback.may_have_started
        )
        assert service.operation_count == 0
        assert not list(Path(service.client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_changed_postwrite_identity_cannot_be_published_as_verified_success(tmp_path):
    async with helm_source(tmp_path) as (service, _, adapter, request, *_):
        inspection = await service.inspect(request, release())
        approval = service.confirm(
            await service.prepare_rollback(inspection.target, 1, HelmRollbackOptions())
        )

        def change(operation):
            if operation == "storage-get" and "rollback" in adapter.calls:
                adapter.identities = (
                    *adapter.identities[:-1],
                    replace(adapter.identities[-1], resource_version="concurrent-change"),
                )

        adapter.after = change
        result = await service.rollback(approval)
        assert result.outcome is HelmOutcome.UNKNOWN and result.observed is None
