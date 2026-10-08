"""Captured editor UI with actual local draft/HTTP validation and deliberate persistence."""

import asyncio
import json
import logging
import threading

import pytest
from textual.widgets import Button, Checkbox, Static

from kuberich.adapters import kubernetes
from kuberich.adapters.editing import ManifestFile
from kuberich.config.schema import Settings
from kuberich.domain.mutations import MutationState
from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.editing import EditingScreen
from tests.support.connections import catalog_fixture
from tests.support.editing import editing_api
from tests.support.workspace import wait_for


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", ["retry", "exit", "escape"])
@pytest.mark.parametrize("stage", ["read", "create"])
async def test_pending_preparation_drains_before_client_or_screen_cleanup(
    tmp_path, monkeypatch, closing, stage
):
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    ready, finish_trial, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    decode, paths, state = kubernetes._decode, [], {}

    def held_decode(data):
        if json.loads(data).get("kind") == "ConfigMap":
            entered.set()
            try:
                assert released.wait(10)
                return decode(data)
            finally:
                finished.set()
        return decode(data)

    def held_create(data):
        entered.set()
        try:
            assert released.wait(10)
            file = ManifestFile(data)
            paths.append(file.path)
            return file
        finally:
            finished.set()

    async def forbidden_editor(*args, **kwargs):
        pytest.fail("Cancelled preparation launched an editor")

    monkeypatch.setattr("kuberich.ui.editing.terminal_handoff", forbidden_editor)
    async with editing_api() as (url, api):
        app = app_fixture(tmp_path, url)

        async def trial():
            async with app.run_test() as pilot:
                screen = await open_screen(app, pilot)
                screen.query_one("#edit-disclosure", Checkbox).value = True
                await pilot.pause()
                if stage == "read":
                    monkeypatch.setattr(kubernetes, "_decode", held_decode)
                else:
                    monkeypatch.setattr("kuberich.services.editing.ManifestFile", held_create)
                old, close = app.sessions.client, app.sessions.client.close

                async def checked_close():
                    assert finished.is_set() and screen._operation_task.done()
                    assert all(not path.parent.exists() for path in paths)
                    closed.set()
                    await close()

                monkeypatch.setattr(old, "close", checked_close)
                state.update(screen=screen, old=old, pilot=pilot)
                screen.open_editor()
                await wait_for(entered.is_set)
                ready.set()
                await finish_trial.wait()

        owner, pressing = asyncio.create_task(trial()), None
        try:
            await wait_for(ready.is_set)
            screen, old, pilot = state["screen"], state["old"], state["pilot"]
            if closing == "exit":
                finish_trial.set()
            else:
                pressing = asyncio.create_task(
                    pilot.press("f4" if closing == "retry" else "escape")
                )
            await wait_for(lambda: screen._operation_task.cancelling())
            another_drain = asyncio.create_task(screen.stop_owned())
            await asyncio.sleep(0)
            assert screen._operation_task.cancelling() == 1
            assert not closed.is_set() and old.configuration is not None
            assert not finished.is_set() and not api.requests
            assert app.screen is screen
            operation = screen._operation_task
            screen.open_editor()
            screen.validate()
            assert screen._operation_task is operation
            released.set()
            await another_drain
            assert finished.is_set() and all(not path.parent.exists() for path in paths)
            if pressing is not None:
                await pressing
            if closing == "retry":
                await wait_for(lambda: app.sessions.client is not old)
            elif closing == "escape":
                await wait_for(lambda: len(app.screen_stack) == 1)
        finally:
            released.set()
            finish_trial.set()
            if pressing is not None:
                await pressing
            await owner
        assert closed.is_set() and not api.requests


def app_fixture(tmp_path, url, *, read_only=False):
    return KubeRichApp(
        Settings(read_only=read_only),
        logging.getLogger("owned-edit-ui"),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=ResourceCommand(RESOURCE_ALIASES["cm"], "team"),
    )


async def open_screen(app, pilot):
    await wait_for(lambda: app.standard_table.row_count == 1)
    app._submit_command(":edit")
    await wait_for(lambda: isinstance(app.screen, EditingScreen))
    await pilot.pause()
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_editor_disclosure_diff_validation_cancel_and_separate_apply(
    tmp_path, monkeypatch, size
):
    seen = []

    async def editor(app, runner, command, *, guard):
        guard()
        source = app.screen.source
        seen.append(source.file.path)
        assert command.target == source.target and command.argv[-1] == str(source.file.path)
        value = source.snapshot.manifest
        value.pop("status", None)
        value["metadata"].pop("managedFields", None)
        value["metadata"].setdefault("labels", {})["example.io/edit"] = "owned-label"
        value["data"]["edited"] = "sensitive-editor-content"
        source.file.path.write_text(json.dumps(value))
        return ProcessResult(ProcessStatus.SUCCEEDED, 0, b"", b"")

    monkeypatch.setattr("kuberich.ui.editing.terminal_handoff", editor)
    async with editing_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            screen = await open_screen(app, pilot)
            assert app.focused is screen.query_one("#edit-cancel", Button)
            screen.open_editor()
            assert screen.source.file is None and not api.requests
            await pilot.press("enter")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert screen.source.file is None and not api.requests
            screen = await open_screen(app, pilot)
            screen.query_one("#edit-disclosure", Checkbox).value = True
            await pilot.pause()
            screen.open_editor()
            await wait_for(lambda: screen.source.intent is not None)
            await wait_for(lambda: not screen._busy())
            assert not api.requests and app.focused is screen.query_one("#edit-cancel", Button)
            assert "owned-label" in str(screen.query_one("#edit-diff", Static).content)
            assert "sensitive-editor-content" not in str(
                screen.query_one("#edit-diff", Static).content
            )
            screen.apply()
            assert not api.requests
            await pilot.press("enter")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not seen[0].parent.exists() and not api.requests
            screen = await open_screen(app, pilot)
            screen.query_one("#edit-disclosure", Checkbox).value = True
            await pilot.pause()
            screen.open_editor()
            await wait_for(lambda: screen.source.intent is not None)
            await wait_for(lambda: not screen._busy())
            screen.validate()
            await wait_for(lambda: screen.source.validated is not None)
            await wait_for(lambda: not screen._busy())
            assert len(api.requests) == 1 and "edited" not in api.value["data"]
            assert app.focused is screen.query_one("#edit-cancel", Button)
            screen.apply()
            await wait_for(
                lambda: app.mutations.records and app.mutations.records[-1].result is not None
            )
            assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
            assert (
                len(api.requests) == 2 and api.value["data"]["edited"] == "sensitive-editor-content"
            )
            assert "sensitive-editor-content" not in repr(app.mutations.records)
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not seen[1].parent.exists()
        assert app.sessions.client is None and not app.mutations._live


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["noop", "failure", "invalid", "validation-denied", "conflict"])
async def test_editor_cancellation_failures_noops_denial_and_conflicts_are_safe(
    tmp_path, monkeypatch, mode
):
    async def editor(app, runner, command, *, guard):
        source = app.screen.source
        if mode == "invalid":
            source.file.path.write_text("broken: [sensitive-value")
        elif mode not in {"noop", "failure"}:
            value = source.snapshot.manifest
            value.pop("status", None)
            value["metadata"].pop("managedFields", None)
            value["data"]["new"] = "sensitive-value"
            source.file.path.write_text(json.dumps(value))
        return ProcessResult(
            ProcessStatus.FAILED if mode == "failure" else ProcessStatus.SUCCEEDED,
            9 if mode == "failure" else 0,
            b"",
            b"",
        )

    monkeypatch.setattr("kuberich.ui.editing.terminal_handoff", editor)
    async with editing_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            screen = await open_screen(app, pilot)
            screen.query_one("#edit-disclosure", Checkbox).value = True
            await pilot.pause()
            screen.open_editor()
            await wait_for(
                lambda: screen._operation_task is not None and screen._operation_task.done()
            )
            path = screen.source.file.path
            screen.apply()
            assert not api.requests
            if mode == "validation-denied":
                api.validation_status = 403
                screen.validate()
                await wait_for(lambda: len(api.requests) == 1 and not screen._busy())
                assert screen.query_one("#edit-apply", Button).disabled
            elif mode == "conflict":
                api.value["metadata"]["resourceVersion"] = "concurrent"
                screen.validate()
                await wait_for(lambda: not screen._busy())
                assert "changed" in str(screen.query_one("#edit-feedback", Static).content)
                assert not api.requests
            else:
                assert screen.query_one("#edit-validate", Button).disabled
            assert "sensitive-value" not in str(screen.query_one("#edit-feedback", Static).content)
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not path.parent.exists()


@pytest.mark.asyncio
async def test_readonly_commands_and_shortcut_never_open_editor(tmp_path):
    async with editing_api() as (url, api):
        app = app_fixture(tmp_path, url, read_only=True)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":edit")
            app.action_edit()
            await pilot.press("E")
            assert len(app.screen_stack) == 1 and not api.requests
            assert "Read-only" in str(app.status.content)
