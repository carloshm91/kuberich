"""Public review controls, one-use submission and screen ownership over a controlled port."""

import asyncio

import pytest
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input

from kuberich.domain.helm_lifecycle import HelmLifecycleKind
from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.services.processes import ProcessRunner
from kuberich.ui.helm_lifecycle import HelmLifecycleScreen
from tests.support.helm_lifecycle_ui import LifecycleTestApp, LifecycleUiPort, ui_chart
from tests.support.workspace import wait_for


def screen_fixture(*, operation=HelmLifecycleKind.INSTALL, read_only=False):
    service = LifecycleUiPort(read_only=read_only)
    screen = HelmLifecycleScreen(
        service=service,
        request=service.request,
        address=service.address,
        operation=operation,
        chart=None if operation is HelmLifecycleKind.UNINSTALL else ui_chart(),
    )
    return service, screen, LifecycleTestApp(screen)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(HelmLifecycleKind))
@pytest.mark.parametrize("size", [(120, 36), (80, 24), (40, 12)])
async def test_native_review_is_separate_from_synchronous_one_use_confirmation(operation, size):
    service, screen, app = screen_fixture(operation=operation)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.focused.id == "helm-lifecycle-back"
        assert screen.query_one("#helm-lifecycle-confirm", Button).disabled
        assert screen.query_one("#helm-lifecycle-hooks", Checkbox).value is False
        assert screen.query_one("#helm-lifecycle-wait", Checkbox).value is True
        assert screen.query_one("#helm-lifecycle-timeout", Input).value == "300"
        for name in ("prepare", "confirm", "stop", "back"):
            button = screen.query_one("#helm-lifecycle-" + name, Button)
            assert button.region.width > 0 and button.region.height == 1
            assert button.region.bottom <= size[1]
        if operation is HelmLifecycleKind.UNINSTALL:
            assert screen.query_one("#helm-lifecycle-history", Checkbox).value is True
        else:
            assert screen.query_one("#helm-lifecycle-edit", Button).disabled
        screen.prepare()
        await wait_for(lambda: screen.intent is not None and screen.operation_count == 0)
        assert not service.admissions
        assert "Native Helm dry-run: passed" in screen.viewer.text
        assert "live/configmap/owned" in screen.viewer.text
        assert not screen.query_one("#helm-lifecycle-confirm", Button).disabled
        screen.confirm()
        screen.confirm()
        assert service.admissions == 1  # Happens in the button handler, before yielding.
        assert service.executions == 0
        await wait_for(lambda: screen.observation is not None and screen.operation_count == 0)
        assert service.executions == 1 and service.confirmations == 1
        assert "SUCCEEDED" in str(screen.status.content)
        assert screen.query_one("#helm-lifecycle-prepare", Button).disabled
        await screen.action_back()
        assert screen.intent is None and screen.viewer.text == "" and screen.operation_count == 0


@pytest.mark.asyncio
async def test_option_and_values_source_changes_expire_reviews_and_never_implicitly_execute():
    service, screen, app = screen_fixture(operation=HelmLifecycleKind.UPGRADE)
    async with app.run_test() as pilot:
        screen.prepare()
        await wait_for(lambda: screen.intent is not None and screen.operation_count == 0)
        old = screen.intent
        screen.query_one("#helm-lifecycle-hooks", Checkbox).value = True
        await pilot.pause()
        assert screen.intent is None and screen.viewer.text == ""
        assert screen.query_one("#helm-lifecycle-confirm", Button).disabled
        screen.confirm()
        assert service.admissions == 0
        screen.query_one("#helm-lifecycle-supplied", Checkbox).value = True
        await pilot.pause()
        assert screen.values is None
        screen.prepare()
        await wait_for(lambda: screen.intent is not None and screen.operation_count == 0)
        assert screen.intent is not old
        assert service.values_sources == ["defaults", "supplied"]
        assert service.preparations[-1][3].run_hooks
        screen.query_one("#helm-lifecycle-timeout", Input).value = ""
        await pilot.pause()
        screen.prepare()
        await wait_for(lambda: screen.operation_count == 0)
        assert "whole-number" in str(screen.status.content)
        assert screen.intent is None and service.admissions == 0


@pytest.mark.asyncio
async def test_read_only_blocks_preparation_and_editor_disclosure():
    service, screen, app = screen_fixture(read_only=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert screen.query_one("#helm-lifecycle-prepare", Button).disabled
        assert screen.query_one("#helm-lifecycle-confirm", Button).disabled
        assert screen.query_one("#helm-lifecycle-edit", Button).disabled
        screen.prepare()
        await wait_for(lambda: screen.operation_count == 0)
        assert "read-only" in str(screen.status.content).lower()
        assert (
            service.values_sources == [] and service.preparations == [] and service.admissions == 0
        )
        await pilot.press("escape")
        await wait_for(lambda: not screen.is_attached)
        assert screen.viewer.text == ""


@pytest.mark.asyncio
async def test_cover_and_scope_departure_cancel_pending_review_and_reject_late_results():
    service, screen, app = screen_fixture()
    service.block_prepare = True
    async with app.run_test() as pilot:
        screen.prepare()
        await service.prepare_entered.wait()
        cover = ModalScreen()
        app.push_screen(cover)
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.intent is None and screen.viewer.text == ""
        cover.dismiss()
        await pilot.pause()
        service.block_prepare = False
        screen.prepare()
        await wait_for(lambda: screen.intent is not None and screen.operation_count == 0)
        service.current_scope = False
        screen.validate_target()
        assert screen.invalidated and screen.intent is None and screen.viewer.text == ""
        screen.prepare()
        screen.confirm()
        assert service.admissions == 0
        assert screen.query_one("#helm-lifecycle-prepare", Button).disabled
        await screen.stop_owned()
        await screen.stop_owned()


@pytest.mark.asyncio
async def test_stopping_admitted_execution_does_not_offer_an_automatic_retry():
    service, screen, app = screen_fixture()
    service.block_execute = True
    async with app.run_test() as pilot:
        screen.prepare()
        await wait_for(lambda: screen.intent is not None and screen.operation_count == 0)
        screen.confirm()
        await service.execute_entered.wait()
        await screen.stop()
        assert screen.operation_count == 0 and service.admissions == 1
        assert "partial effects" in str(screen.status.content)
        assert screen.query_one("#helm-lifecycle-prepare", Button).disabled
        screen.prepare()
        screen.confirm()
        await pilot.pause()
        assert service.admissions == 1


@pytest.mark.asyncio
async def test_unexpected_preparation_failure_does_not_expose_private_exception_text():
    service, screen, app = screen_fixture()
    service.failure = RuntimeError("private-chart-token")
    async with app.run_test() as pilot:
        screen.prepare()
        await wait_for(lambda: screen.operation_count == 0)
        assert "private-chart-token" not in str(screen.status.content)
        assert "details were withheld" in str(screen.status.content)
        assert screen.intent is None and service.admissions == 0
        await pilot.press("escape")
        await wait_for(lambda: not screen.is_attached)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["accepted", "failed", "open", "finish", "cancel"])
async def test_editor_requires_one_use_disclosure_then_always_drains_private_draft(
    tmp_path, monkeypatch, scenario
):
    service, screen, app = screen_fixture()
    service.editor_directory = tmp_path
    service.editor_failure = scenario
    runner = ProcessRunner(service.policy)
    screen.runner = runner
    handed = []
    entered = asyncio.Event()

    async def handoff(app, process_runner, command, *, guard):
        assert process_runner is runner
        guard()
        handed.append(command)
        entered.set()
        if scenario == "cancel":
            await asyncio.Event().wait()
        return ProcessResult(
            ProcessStatus.FAILED if scenario == "failed" else ProcessStatus.SUCCEEDED,
            1 if scenario == "failed" else 0,
        )

    monkeypatch.setattr("kuberich.ui.helm_lifecycle.terminal_handoff", handoff)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen.edit_values()
            assert service.editor_events == []
            assert "disclosure" in str(screen.status.content)
            screen.query_one("#helm-lifecycle-disclosure", Checkbox).value = True
            await pilot.pause()
            screen.edit_values()
            assert not screen.query_one("#helm-lifecycle-disclosure", Checkbox).value
            if scenario == "cancel":
                await entered.wait()
                await screen.stop()
            await wait_for(lambda: screen.operation_count == 0)
            assert service.editor_events[:3] == ["prepare", "confirm", "open"]
            assert not (tmp_path / "values.yaml").exists()
            assert "owned-editor-private-value" not in screen.viewer.text
            assert "owned-editor-private-value" not in str(screen.status.content)
            assert screen.intent is None and service.admissions == 0
            if scenario == "accepted":
                assert screen.values.source == "edited"
                assert "accepted privately" in str(screen.status.content)
            else:
                assert screen.values.source == "defaults"
            if scenario != "open":
                assert len(handed) == 1
            await screen.action_back()
    finally:
        await screen.stop_owned()
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [False, True])
async def test_editor_outcome_is_published_only_after_private_cleanup_drains(
    tmp_path, monkeypatch, succeeded
):
    service, screen, app = screen_fixture()
    service.editor_directory = tmp_path
    service.hold_close = True
    runner = ProcessRunner(service.policy)
    screen.runner = runner

    async def handoff(app, process_runner, command, *, guard):
        guard()
        return ProcessResult(
            ProcessStatus.SUCCEEDED if succeeded else ProcessStatus.FAILED, 0 if succeeded else 9
        )

    monkeypatch.setattr("kuberich.ui.helm_lifecycle.terminal_handoff", handoff)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            original = screen.values
            screen.query_one("#helm-lifecycle-disclosure", Checkbox).value = True
            screen.edit_values()
            await service.close_entered.wait()
            assert (tmp_path / "values.yaml").is_file()
            assert "Opening private" in str(screen.status.content)
            assert "accepted privately" not in str(screen.status.content)
            assert "stopped or failed" not in str(screen.status.content)
            assert screen.operation_count == 1
            assert screen.values is original or screen.values.source == "defaults"
            service.close_release.set()
            await wait_for(lambda: screen.operation_count == 0)
            assert not (tmp_path / "values.yaml").exists()
            assert ("accepted privately" if succeeded else "stopped or failed") in str(
                screen.status.content
            )
    finally:
        service.close_release.set()
        await screen.stop_owned()
        await runner.close()
