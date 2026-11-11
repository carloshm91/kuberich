"""Public lifecycle policy, drift, one-use approval and uncertain owned write outcomes."""

import asyncio
import shutil
from uuid import uuid4

import pytest

from kuberich.domain.helm import HelmApproval, HelmOutcome
from kuberich.domain.helm_lifecycle import HelmLifecycleKind, HelmLifecycleOptions
from kuberich.errors import AppError
from kuberich.services.processes import ProcessRunner
from tests.support.helm_lifecycle import ADDRESS, MANIFEST
from tests.support.helm_lifecycle_faults import effect_source
from tests.support.workspace import wait_for


async def review(fixture, operation=HelmLifecycleKind.INSTALL, **changes):
    return await fixture.service.prepare_lifecycle(
        fixture.request,
        ADDRESS,
        operation,
        fixture.chart if operation is not HelmLifecycleKind.UNINSTALL else None,
        **changes,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(HelmLifecycleKind))
async def test_public_one_use_write_observes_exact_revision_or_uninstalled_storage(
    tmp_path, operation
):
    async with effect_source(
        tmp_path, existing=operation is not HelmLifecycleKind.INSTALL
    ) as fixture:
        intent = await review(fixture, operation)
        assert fixture.writes() == [] and "owned-secret-value" not in repr(intent)
        approval = fixture.service.confirm_lifecycle(intent)
        task = fixture.service.execute_lifecycle(approval)
        assert isinstance(task, asyncio.Task)
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(approval)
        result = await task
        assert result.outcome is HelmOutcome.SUCCEEDED and result.may_have_started
        assert fixture.service.last_operation is result and len(fixture.writes()) == 1
        if operation is HelmLifecycleKind.INSTALL:
            assert result.observed.revision == 1
        elif operation is HelmLifecycleKind.UPGRADE:
            assert result.observed.revision == 2
        else:
            assert result.observed is None and fixture.state()["status"] == "uninstalled"
        assert "owned-secret-value" not in repr(result)
        assert not fixture.input_directories()


@pytest.mark.asyncio
async def test_uninstall_purge_is_explicit_and_observed_as_no_history(tmp_path):
    async with effect_source(tmp_path, existing=True) as fixture:
        intent = await review(
            fixture, HelmLifecycleKind.UNINSTALL, options=HelmLifecycleOptions(keep_history=False)
        )
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is HelmOutcome.SUCCEEDED
        assert fixture.state()["revision"] == 0 and not fixture.state()["resource"]
        assert "--keep-history=false" in fixture.writes()[0]["argv"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(HelmLifecycleKind))
async def test_readonly_refuses_before_namespace_catalog_editor_or_native_effects(
    tmp_path, operation
):
    async with effect_source(tmp_path, read_only=True) as fixture:
        with pytest.raises(AppError, match="Read-only"):
            await review(fixture, operation)
        with pytest.raises(AppError, match="Read-only"):
            await fixture.service.create_values(fixture.request, ADDRESS, fixture.chart)
        with pytest.raises(AppError, match="Read-only"):
            await fixture.service.catalog.add(
                "owned", fixture.origin + "/charts", allow_loopback_http=True
            )
        assert fixture.api.requests == [] and fixture.calls() == []
        assert not fixture.input_directories() and not (tmp_path / "catalog").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "namespace_uid",
        "namespace_terminating",
        "storage_uid_suffix",
        "live_uid",
        "live_version",
        "rendered_manifest",
    ],
)
async def test_review_identity_or_render_drift_blocks_without_write_or_rebase(tmp_path, fault):
    async with effect_source(tmp_path, existing=True) as fixture:
        intent = await review(fixture, HelmLifecycleKind.UPGRADE)
        value = {
            "namespace_uid": "replacement-namespace",
            "namespace_terminating": True,
            "storage_uid_suffix": "-replacement",
            "live_uid": "replacement-resource",
            "live_version": "22",
            "rendered_manifest": MANIFEST.replace("owned-lifecycle", "changed-since-review"),
        }[fault]
        fixture.change(**{fault: value})
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is HelmOutcome.STALE and not result.may_have_started
        assert fixture.writes() == [] and not fixture.input_directories()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("apply-error", HelmOutcome.FAILED),
        ("no-change", HelmOutcome.UNKNOWN),
        ("revision-jump", HelmOutcome.UNKNOWN),
        ("before-error", HelmOutcome.UNKNOWN),
    ],
)
async def test_nonzero_partial_or_zero_unverified_writes_never_become_false_success(
    tmp_path, mode, expected
):
    async with effect_source(tmp_path, write_mode=mode) as fixture:
        intent = await review(fixture)
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is expected and result.may_have_started
        assert len(fixture.writes()) == 1 and not fixture.input_directories()
        assert "owned-secret-value" not in result.message
        if expected is HelmOutcome.FAILED:
            assert result.observed.status == "failed" and fixture.state()["resource"]


@pytest.mark.asyncio
async def test_cancel_after_effect_keeps_unknown_and_never_replays_owned_write(tmp_path):
    async with effect_source(tmp_path, write_mode="hold-after") as fixture:
        intent = await review(fixture)
        approval = fixture.service.confirm_lifecycle(intent)
        task = fixture.service.execute_lifecycle(approval)
        await wait_for(fixture.entered.exists)
        assert fixture.state()["revision"] == 1 and fixture.state()["resource"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert fixture.service.last_operation.outcome is HelmOutcome.UNKNOWN
        assert fixture.service.last_operation.may_have_started
        assert len(fixture.writes()) == 1 and not fixture.input_directories()
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(approval)


@pytest.mark.asyncio
async def test_owned_process_timeout_after_effect_is_unknown_without_observe_or_retry(
    tmp_path, monkeypatch
):
    original = ProcessRunner.capture

    async def bounded(self, command, *, timeout=30, guard=None):
        write = (
            command.purpose.name == "HELM_MUTATE"
            and "--dry-run=server" not in command.argv
            and "--dry-run=true" not in command.argv
        )
        return await original(self, command, timeout=0.1 if write else timeout, guard=guard)

    monkeypatch.setattr(ProcessRunner, "capture", bounded)
    async with effect_source(tmp_path, write_mode="timeout") as fixture:
        intent = await review(fixture)
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is HelmOutcome.UNKNOWN and result.may_have_started
        assert fixture.state()["resource"] and len(fixture.writes()) == 1
        assert fixture.calls()[-1]["command"] == "install" and not fixture.input_directories()


@pytest.mark.asyncio
async def test_preview_and_selected_values_remain_private_and_revalidate_edited_mapping(tmp_path):
    async with effect_source(tmp_path, existing=True) as fixture:
        supplied = await fixture.service.create_values(
            fixture.request, ADDRESS, fixture.chart, source="supplied"
        )
        assert supplied.source == "supplied"
        disclosure = await fixture.service.prepare_values_editor(supplied)
        command = await fixture.service.open_values_editor(
            fixture.service.confirm_values_editor(disclosure)
        )
        path = next(argument for argument in command.argv if argument.endswith("manifest.yaml"))
        from pathlib import Path

        Path(path).write_text("message: edited\npassword: owned-secret-value\n")
        edited = await fixture.service.finish_values_editor()
        intent = await fixture.service.prepare_lifecycle(
            fixture.request, ADDRESS, HelmLifecycleKind.UPGRADE, fixture.chart, edited
        )
        assert "owned-secret-value" not in intent.preview_text and edited.source == "edited"
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is HelmOutcome.SUCCEEDED and not Path(path).exists()


@pytest.mark.asyncio
async def test_policy_tightening_consumes_approval_without_launch(tmp_path):
    async with effect_source(tmp_path) as fixture:
        intent = await review(fixture)
        approval = fixture.service.confirm_lifecycle(intent)
        fixture.service.policy.tighten()
        with pytest.raises(AppError, match="Read-only"):
            fixture.service.execute_lifecycle(approval)
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(approval)
        await wait_for(lambda: fixture.service.operation_count == 0)
        assert fixture.writes() == [] and not fixture.input_directories()


@pytest.mark.asyncio
async def test_forged_confirmation_retires_real_authority_and_cleans_its_exact_inputs(tmp_path):
    async with effect_source(tmp_path) as fixture:
        intent = await review(fixture)
        approval = fixture.service.confirm_lifecycle(intent)
        forged = HelmApproval(approval.intent, uuid4())
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(forged)
        assert fixture.writes() == []
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(approval)
        await wait_for(lambda: fixture.service.operation_count == 0)
        assert not fixture.input_directories()


@pytest.mark.asyncio
async def test_cross_operation_confirmation_cannot_leave_a_lifecycle_token_reusable(tmp_path):
    async with effect_source(tmp_path) as fixture:
        intent = await review(fixture)
        approval = fixture.service.confirm_lifecycle(intent)
        with pytest.raises(AppError):
            fixture.service.rollback(approval)
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(approval)
        await fixture.service.close_values_editor()
        assert fixture.writes() == [] and not fixture.input_directories()


@pytest.mark.asyncio
@pytest.mark.parametrize("immediate_shutdown", [False, True])
async def test_cancellation_before_owned_coroutine_entry_drains_inputs_without_authority(
    tmp_path, immediate_shutdown
):
    async with effect_source(tmp_path) as fixture:
        intent = await review(fixture)
        approval = fixture.service.confirm_lifecycle(intent)
        task = fixture.service.execute_lifecycle(approval)
        task.cancel()
        if immediate_shutdown:
            await fixture.service.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        await wait_for(lambda: fixture.service.operation_count == 0)
        assert not fixture.input_directories() and fixture.writes() == []
        assert fixture.service.last_operation.outcome is HelmOutcome.BLOCKED
        assert not fixture.service.last_operation.may_have_started
        with pytest.raises(AppError):
            fixture.service.execute_lifecycle(approval)


@pytest.mark.asyncio
@pytest.mark.parametrize("admission_failure", [False, True])
@pytest.mark.parametrize("callback_failure", [False, True])
async def test_shutdown_refused_private_cleanup_still_closes_every_other_owner(
    tmp_path, monkeypatch, admission_failure, callback_failure
):
    from kuberich.adapters.helm import HelmAdapter
    from kuberich.adapters.helm_files import HelmCommandFiles
    from kuberich.adapters.manifests import ManifestAdapter
    from kuberich.services.helm_catalog import HelmCatalogService

    staging = tmp_path / "captured-input-owner"
    staging.mkdir()
    created = []
    closed = []

    def owned_files(_parent, **inputs):
        result = HelmCommandFiles(staging, **inputs)
        created.append(result)
        return result

    monkeypatch.setattr("kuberich.services.helm_lifecycle.HelmCommandFiles", owned_files)
    for owner, label in (
        (ManifestAdapter, "admission"),
        (HelmCatalogService, "catalog"),
        (HelmAdapter, "native"),
    ):
        original = owner.close

        async def tracked(self, original=original, label=label):
            await original(self)
            closed.append(label)
            if label == "admission" and admission_failure:
                raise AppError("Owned admission cleanup failure.")

        monkeypatch.setattr(owner, "close", tracked)
    expected = BaseExceptionGroup if admission_failure or callback_failure else AppError
    with pytest.raises(expected, match=r"shutdown|cleanup") as problem:
        async with effect_source(tmp_path / "fixture") as fixture:
            intent = await review(fixture)
            original_path = created[0].path
            retired = staging / "retired-inputs"
            original_path.rename(retired)
            original_path.mkdir(mode=0o700)
            sentinel = original_path / "replacement-sentinel"
            sentinel.write_text("replacement must survive")
            if callback_failure:
                task = fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await wait_for(lambda: fixture.service.operation_count == 0)
    assert closed == ["admission", "catalog", "native"]
    assert fixture.service.operation_count == 0
    assert sentinel.read_text() == "replacement must survive"
    assert (retired / "chart.tgz").exists()
    assert "owned-secret-value" not in str(problem.value)
    if admission_failure or callback_failure:
        assert len(problem.value.exceptions) == 2
    shutil.rmtree(original_path)
    retired.rename(original_path)
    created[0].close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [HelmLifecycleKind.UPGRADE, HelmLifecycleKind.UNINSTALL])
@pytest.mark.parametrize("namespace_value", ["", None, "absent"])
async def test_all_namespace_release_uses_pinned_default_for_absent_empty_or_null_namespace(
    tmp_path, operation, namespace_value
):
    import yaml

    body = yaml.safe_load(MANIFEST)
    if namespace_value != "absent":
        body["metadata"]["namespace"] = namespace_value
    async with effect_source(
        tmp_path, existing=True, namespace=None, rendered_manifest=yaml.safe_dump(body)
    ) as fixture:
        intent = await review(fixture, operation)
        assert intent.address.namespace == ADDRESS.namespace
        assert any(
            path == "/api/v1/namespaces/" + ADDRESS.namespace + "/configmaps/owned-release-settings"
            for method, path, query in fixture.api.requests
        )
        assert not any(
            "/namespaces/default/" in path for method, path, query in fixture.api.requests
        )
        assert fixture.writes() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace_value", [False, 0, []])
async def test_malformed_namespace_never_defaults_to_a_real_destination(tmp_path, namespace_value):
    import yaml

    body = yaml.safe_load(MANIFEST)
    body["metadata"]["namespace"] = namespace_value
    async with effect_source(tmp_path, rendered_manifest=yaml.safe_dump(body)) as fixture:
        with pytest.raises(AppError, match="namespace"):
            await review(fixture)
        assert fixture.writes() == [] and not fixture.input_directories()
        assert not fixture.api.validations


@pytest.mark.asyncio
async def test_named_create_admission_is_explicit_nonpersistent_and_repeated_before_write(tmp_path):
    async with effect_source(tmp_path) as fixture:
        intent = await review(fixture)
        assert len(fixture.api.validations) == 1 and fixture.api.mutations == []
        assert not fixture.state()["resource"] and fixture.state()["revision"] == 0
        assert any("whole-batch quota" in effect for effect in intent.effects)
        assert any("named-create admission passed" in effect for effect in intent.effects)
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is HelmOutcome.SUCCEEDED
        assert len(fixture.api.validations) == 2 and fixture.api.mutations == []


@pytest.mark.asyncio
async def test_named_create_admission_refusal_cleans_review_before_confirmation(tmp_path):
    path = "/api/v1/namespaces/" + ADDRESS.namespace + "/configmaps"
    async with effect_source(tmp_path, denied_paths=[path]) as fixture:
        with pytest.raises(AppError, match="admission dry-run"):
            await review(fixture)
        assert fixture.writes() == [] and not fixture.state()["resource"]
        assert not fixture.input_directories() and fixture.api.mutations == []


@pytest.mark.asyncio
async def test_admission_change_after_review_blocks_without_replaying_any_write(tmp_path):
    async with effect_source(tmp_path) as fixture:
        intent = await review(fixture)
        fixture.change(denied_paths=["/api/v1/namespaces/" + ADDRESS.namespace + "/configmaps"])
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert result.outcome is HelmOutcome.STALE and not result.may_have_started
        assert fixture.writes() == [] and not fixture.input_directories()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["collision", "pending", "foreign"])
async def test_ineligible_history_or_live_ownership_never_becomes_an_implicit_adoption(
    tmp_path, fault
):
    changes = (
        {"resource": True}
        if fault == "collision"
        else {"status": "pending-upgrade"}
        if fault == "pending"
        else {"foreign_owner": True}
    )
    async with effect_source(tmp_path, existing=fault != "collision", **changes) as fixture:
        with pytest.raises(AppError):
            await review(
                fixture,
                HelmLifecycleKind.INSTALL if fault == "collision" else HelmLifecycleKind.UPGRADE,
            )
        assert not fixture.input_directories() and fixture.writes() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("hooks", [False, True])
async def test_uninstall_reviews_stored_hooks_scope_events_order_and_retention_even_when_disabled(
    tmp_path, hooks
):
    hook = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "owned-delete-hook",
            "annotations": {"helm.sh/hook": "pre-delete,post-delete"},
        },
        "data": {"password": "owned-secret-value"},
    }
    import json

    async with effect_source(
        tmp_path,
        existing=True,
        hooks=[
            {
                "manifest": json.dumps(hook),
                "events": ["pre-delete", "post-delete"],
                "weight": -3,
                "delete_policies": ["hook-succeeded"],
            }
        ],
    ) as fixture:
        intent = await review(
            fixture, HelmLifecycleKind.UNINSTALL, options=HelmLifecycleOptions(run_hooks=hooks)
        )
        effects = "\n".join(intent.effects)
        assert "ConfigMap/release-team/owned-delete-hook" in effects
        assert "pre-delete, post-delete" in effects and "weight -3" in effects
        assert "hook-succeeded" in effects and "outlive the release" in effects
        assert "separate from ordinary resources" in intent.preview_text
        assert "owned-secret-value" not in intent.preview_text and fixture.writes() == []
        assert "--no-hooks=" + str(not hooks).lower() in fixture.calls()[-1]["argv"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,fact",
    [
        ({"retain_resource": True}, "retained by resource-policy keep"),
        ({"retain_resource": True, "deleting_resource": True}, "deletion pending"),
        ({"after_write": {"resource": True}}, "deletion or retention is not verified"),
    ],
)
async def test_uninstalled_storage_does_not_claim_retained_or_pending_resources_are_gone(
    tmp_path, changes, fact
):
    async with effect_source(tmp_path, existing=True, **changes) as fixture:
        intent = await review(fixture, HelmLifecycleKind.UNINSTALL)
        result = await fixture.service.execute_lifecycle(fixture.service.confirm_lifecycle(intent))
        assert (
            result.outcome is HelmOutcome.SUCCEEDED and fixture.state()["status"] == "uninstalled"
        )
        assert any(fact in value for value in result.resources)
        assert fixture.state()["resource"] and not fixture.input_directories()
