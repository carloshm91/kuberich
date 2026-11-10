"""Accessible browser controls, replacement selection and owned render cancellation."""

import asyncio
import json

import pytest
from textual.widgets import Button

from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.processes import ProcessRunner
from kuberich.ui.manifest_browser import ManifestBrowserScreen
from kuberich.ui.manifest_editor import ManifestEditorScreen
from tests.support.manifest_ui import ManifestTestApp, click_ready
from tests.support.workspace import wait_for


class OwnedRenderer:
    def __init__(self):
        self.calls = []
        self.operation_count = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.hold = False

    async def render(self, files, relative, *, guard):
        self.calls.append((files, relative))
        self.operation_count += 1
        self.entered.set()
        try:
            if self.hold:
                await self.release.wait()
            guard()
            return b"apiVersion: v1\nkind: ConfigMap\nmetadata: {name: rendered-one}\n---\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: rendered-two}\n"
        finally:
            self.operation_count -= 1

    async def close(self):
        assert self.operation_count == 0


@pytest.mark.asyncio
async def test_real_buttons_directory_explicit_render_resource_selection_and_local_editor(tmp_path):
    (tmp_path / "source.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: ordinary-source}\n"
    )
    renderer = OwnedRenderer()
    local = LocalManifestService(AccessPolicy(False), {}, tmp_path, renderer=renderer)
    runner = ProcessRunner(local.policy)
    reviews = []
    screen = ManifestBrowserScreen(
        service=local,
        runner=runner,
        open_review=lambda source, action: reviews.append((source, action)),
    )
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            await wait_for(lambda: screen.listing is not None and screen.operation_count == 0)
            assert not renderer.calls
            await click_ready(app, pilot, screen.query_one("#manifests-directory", Button))
            await wait_for(lambda: screen.source is not None and screen.operation_count == 0)
            assert screen.source.kind == "directory" and not renderer.calls
            for action in ("apply", "delete"):
                await click_ready(app, pilot, screen.query_one("#manifests-" + action, Button))
            assert [action for _, action in reviews] == ["apply", "delete"]
            (tmp_path / "kustomization.yaml").write_text("resources: [source.yaml]\n")
            await click_ready(app, pilot, screen.query_one("#manifests-refresh", Button))
            await wait_for(lambda: screen.operation_count == 0)
            await click_ready(app, pilot, screen.query_one("#manifests-render", Button))
            await wait_for(lambda: screen.source is not None and screen.operation_count == 0)
            assert screen.source.kind == "kustomize" and len(renderer.calls) == 1
            screen.resources.focus()
            await pilot.press("down")
            await wait_for(
                lambda: "rendered-two" in screen.viewer.text and screen.operation_count == 0
            )
            screen.table.move_cursor(row=0 if screen.table.cursor_row else 1)
            await wait_for(lambda: screen.source is None)
            assert screen.query_one("#manifests-apply", Button).disabled
            await click_ready(app, pilot, screen.query_one("#manifests-edit", Button))
            await wait_for(
                lambda: (
                    isinstance(app.screen, ManifestEditorScreen)
                    and app.screen.disclosure is not None
                )
            )
            await click_ready(app, pilot, app.screen.query_one("#manifest-editor-back", Button))
            await wait_for(lambda: app.screen is screen)
            screen.location.value = str(tmp_path / "missing")
            await pilot.pause()
            screen.location.focus()
            await pilot.press("enter")
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.listing is None and "root" in str(screen.status.content).lower()
            screen.action_inspect()
            screen.action_edit()
            await click_ready(app, pilot, screen.query_one("#manifests-back", Button))
            await wait_for(lambda: screen.stopped)
            screen.action_refresh()
            assert screen.operation_count == 0
    finally:
        await screen.stop_owned()
        await local.close()
        await runner.close()


@pytest.mark.asyncio
async def test_source_selection_cancels_renderer_and_preview_pages_remain_reachable(tmp_path):
    (tmp_path / "kustomization.yaml").write_text("resources: [source.yaml]\n")
    (tmp_path / "source.yaml").write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "wide-preview",
                    "labels": {f"example.io/part-{index}": "x" * 50000 for index in range(6)},
                },
            }
        )
    )
    renderer = OwnedRenderer()
    renderer.hold = True
    local = LocalManifestService(AccessPolicy(True), {}, tmp_path, renderer=renderer)
    runner = ProcessRunner(local.policy)
    screen = ManifestBrowserScreen(
        service=local, runner=runner, open_review=lambda source, action: None
    )
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            await wait_for(lambda: screen.listing is not None and screen.operation_count == 0)
            await click_ready(app, pilot, screen.query_one("#manifests-render", Button))
            await wait_for(renderer.entered.is_set)
            screen.table.move_cursor(row=1)
            await wait_for(lambda: screen.operation_count == 0)
            renderer.release.set()
            assert screen.source is None and local.operation_count == 0
            screen.action_edit()
            assert "read-only" in str(screen.status.content)
            await click_ready(app, pilot, screen.query_one("#manifests-inspect", Button))
            await wait_for(lambda: screen.source is not None and screen.operation_count == 0)
            assert len(screen.pages) > 1
            await click_ready(app, pilot, screen.query_one("#manifests-next", Button))
            assert screen.page == 1
            await click_ready(app, pilot, screen.query_one("#manifests-previous", Button))
            assert screen.page == 0
            assert screen.query_one("#manifests-apply", Button).disabled
            await click_ready(app, pilot, screen.query_one("#manifests-parent", Button))
            await wait_for(lambda: screen.operation_count == 0)
    finally:
        await screen.stop_owned()
        await local.close()
        await runner.close()
