"""Exact local disclosure, real filesystem saves and owned editor-screen cleanup."""

import asyncio
import json
from pathlib import Path

import pytest
from textual.widgets import Button, Checkbox

from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.processes import ProcessRunner
from kuberich.ui.manifest_editor import ManifestEditorScreen
from tests.support.manifest_ui import ManifestTestApp, click_ready
from tests.support.workspace import wait_for


async def editor_fixture(tmp_path, *, read_only=False):
    path = tmp_path / "owned.yaml"
    path.write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\ndata: {private: editor-ui-secret}\n"
    )
    local = LocalManifestService(
        AccessPolicy(read_only), {"KUBERICH_EDITOR": "/bin/true"}, tmp_path
    )
    await local.open_root(tmp_path)
    runner = ProcessRunner(local.policy)
    screen = ManifestEditorScreen(service=local, runner=runner, relative="owned.yaml")
    return local, runner, screen, path


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 36), (80, 24)])
async def test_disclosed_editor_private_draft_and_separate_local_save(tmp_path, monkeypatch, size):
    local, runner, screen, path = await editor_fixture(tmp_path)
    before = path.read_bytes()
    handed = []

    async def handoff(app, runner, command, *, guard):
        guard()
        draft = Path(command.argv[-1])
        handed.append(draft)
        assert b"editor-ui-secret" in draft.read_bytes()
        value = json.loads(
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "owned", "labels": {"example.io/edit": "reviewed"}},
                    "data": {"private": "editor-ui-new-secret"},
                }
            )
        )
        draft.write_text(json.dumps(value))
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr("kuberich.ui.manifest_editor.terminal_handoff", handoff)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: screen.disclosure is not None and screen.operation_count == 0)
            assert app.focused.id == "manifest-editor-back"
            assert screen.disclosure.source.sha256 in str(
                screen.query_one("#manifest-editor-file").content
            )
            await click_ready(app, pilot, screen.query_one("#manifest-editor-open", Button))
            assert not handed and path.read_bytes() == before
            screen.query_one("#manifest-editor-disclosure", Checkbox).value = True
            await click_ready(app, pilot, screen.query_one("#manifest-editor-open", Button))
            await wait_for(lambda: screen.intent is not None and screen.operation_count == 0)
            assert len(handed) == 1 and path.read_bytes() == before
            assert (
                "editor-ui-secret" not in screen.viewer.text
                and "editor-ui-new-secret" not in screen.viewer.text
            )
            assert "reviewed" in screen.viewer.text
            assert not screen.query_one("#manifest-editor-disclosure", Checkbox).value
            assert app.focused.id == "manifest-editor-back"
            await click_ready(app, pilot, screen.query_one("#manifest-editor-save", Button))
            await wait_for(
                lambda: local.last_file_outcome is not None and screen.operation_count == 0
            )
            assert b"editor-ui-new-secret" in path.read_bytes()
            assert local.current_source is None and not handed[0].parent.exists()
            assert screen.query_one("#manifest-editor-save", Button).disabled
    finally:
        await screen.stop_owned()
        await runner.close()
        await local.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["noop", "failed", "invalid", "source-change", "disclosure-change", "cancel"]
)
async def test_editor_failures_never_implicitly_save_or_reuse_disclosure(
    tmp_path, monkeypatch, scenario
):
    local, runner, screen, path = await editor_fixture(tmp_path)
    before = path.read_bytes()
    entered = asyncio.Event()
    draft_paths = []

    async def handoff(app, runner, command, *, guard):
        guard()
        draft = Path(command.argv[-1])
        draft_paths.append(draft)
        entered.set()
        if scenario == "cancel":
            await asyncio.Event().wait()
        if scenario == "invalid":
            draft.write_text("invalid: [editor-ui-secret")
        if scenario == "source-change":
            draft.write_bytes(before + b"\n# edited\n")
            path.write_bytes(before + b"\n# external change\n")
        return ProcessResult(
            ProcessStatus.FAILED if scenario == "failed" else ProcessStatus.SUCCEEDED,
            8 if scenario == "failed" else 0,
        )

    monkeypatch.setattr("kuberich.ui.manifest_editor.terminal_handoff", handoff)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            await wait_for(lambda: screen.disclosure is not None and screen.operation_count == 0)
            old = screen.disclosure
            if scenario == "disclosure-change":
                path.write_bytes(before + b"\n# changed after disclosure\n")
            screen.query_one("#manifest-editor-disclosure", Checkbox).value = True
            await click_ready(app, pilot, screen.query_one("#manifest-editor-open", Button))
            if scenario == "cancel":
                await wait_for(entered.is_set)
                await click_ready(app, pilot, screen.query_one("#manifest-editor-stop", Button))
            await wait_for(lambda: screen.operation_count == 0)
            assert (
                screen.intent is None and screen.query_one("#manifest-editor-save", Button).disabled
            )
            assert "editor-ui-secret" not in screen.viewer.text
            if scenario == "disclosure-change":
                assert not draft_paths
            else:
                assert draft_paths
            if scenario not in {"source-change", "disclosure-change"}:
                assert path.read_bytes() == before
            if scenario != "cancel":
                assert screen.disclosure is not old
            await screen.action_back()
            assert all(not draft.parent.exists() for draft in draft_paths)
    finally:
        await screen.stop_owned()
        await runner.close()
        await local.close()


@pytest.mark.asyncio
async def test_editor_read_only_and_default_back_do_not_disclose(tmp_path):
    local, runner, screen, path = await editor_fixture(tmp_path, read_only=True)
    app = ManifestTestApp(screen)
    before = path.read_bytes()
    try:
        async with app.run_test() as pilot:
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.disclosure is None
            assert screen.query_one("#manifest-editor-open", Button).disabled
            assert screen.query_one("#manifest-editor-save", Button).disabled
            await pilot.press("enter")
            await wait_for(lambda: not screen.is_attached)
            assert path.read_bytes() == before and local.operation_count == 0
    finally:
        await screen.stop_owned()
        await runner.close()
        await local.close()
