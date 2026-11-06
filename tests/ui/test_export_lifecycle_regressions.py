"""Bounded diagnostics for unchanged protected log/browser production failures."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import OptionList, Static

from kuberich.config.schema import Settings
from kuberich.domain.commands import Command
from kuberich.domain.log_view import WINDOWS
from kuberich.services.aggregate_logs import AggregateLogs
from kuberich.ui.app import KubeRichApp
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.chrome import WorkspaceFrame
from kuberich.ui.log_body import LogBody
from kuberich.ui.scopes import ScopeScreen
from tests.support.connections import catalog_fixture
from tests.support.export_browser_geometry import seed_browser_artifact
from tests.support.export_ui import service_for
from tests.support.workspace import wait_for, workspace_api
from tests.terminal.pty_support import ROOT
from tests.ui.test_log_export_captures import (
    AT,
    ReadGate,
    choose_scope,
    ns,
    open_viewer,
    owned_app,
    press_until,
    single_api,
)


class BrowserHost(App):
    def __init__(self, service, directory):
        super().__init__()
        self.browser = ArtifactBrowserScreen(
            service=service,
            directory=directory,
            open_review=lambda *_: None,
            open_viewer=lambda *_: None,
            copy_to_clipboard=lambda *_: None,
        )

    def on_mount(self):
        self.push_screen(self.browser)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
@pytest.mark.parametrize("host", ["standalone", "kuberich"])
async def test_browser_full_filename_width_after_real_scan_and_filter_rebuild(tmp_path, size, host):
    directory = tmp_path / "exports"
    artifact = seed_browser_artifact(directory)
    service = service_for(tmp_path)
    app = (
        BrowserHost(service, directory)
        if host == "standalone"
        else KubeRichApp(
            Settings(read_only=True),
            logging.Logger("owned-browser-width-repro", 100),
            catalog=catalog_fixture(tmp_path, "http://127.0.0.1:1"),
            initial_command=Command.EXPORTS,
            export_service=service,
        )
    )
    async with app.run_test(size=size) as pilot:
        await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
        browser = app.screen
        try:
            await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
        except TimeoutError:
            raise AssertionError(
                (
                    str(browser.status.content),
                    browser.operation_count,
                    browser.is_mounted,
                    browser.is_attached,
                )
            ) from None
        assert await browser.table.wait_for_refresh()
        await pilot.pause()
        for value in ("", "owned", "no-match", ""):
            browser.filter.value = value
            await pilot.pause()
            assert await browser.table.wait_for_refresh()
            if value != "no-match":
                assert browser.table.row_count == 1
                column = browser.table.ordered_columns[0]
                assert browser.table.get_row_at(0)[0].plain == artifact.name
                assert column.auto_width and column.content_width >= len(artifact.name), (
                    host,
                    size,
                    value,
                    column.width,
                    column.content_width,
                    [
                        (item.label.plain, item.width, item.content_width)
                        for item in browser.table.ordered_columns
                    ],
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["frame", "status"])
@pytest.mark.parametrize("aggregate", [False, True])
async def test_aggregate_normal_quit_drains_renderer_before_log_frame_teardown(
    tmp_path, monkeypatch, boundary, aggregate
):
    api = single_api()
    frame_started = asyncio.Event()
    body_loaded = asyncio.Event()
    observed = []
    selected = None
    original_load = LogBody.load

    async def load(body, *args, **kwargs):
        result = await original_load(body, *args, **kwargs)
        if frame_started.is_set():
            body_loaded.set()
        return result

    async def frame_unmounted(frame):
        if frame.id != ("log-dialog" if boundary == "frame" else "log-status"):
            return
        observed.append(
            (
                bool(selected.query("#log-dialog")),
                selected.status.is_mounted,
                selected.closed,
                selected.owner.closed if aggregate else None,
            )
        )
        frame_started.set()
        await api.emit("pod-00", "app", b"2026-11-05T12:04:00Z owned-frame-teardown\n")
        await wait_for(body_loaded.is_set)

    monkeypatch.setattr(LogBody, "load", load)
    monkeypatch.setattr(
        WorkspaceFrame if boundary == "frame" else Static,
        "on_unmount",
        frame_unmounted,
        raising=False,
    )
    async with workspace_api(ns, api.handler) as url:
        app, _ = owned_app(tmp_path, url)
        try:
            async with app.run_test() as pilot:
                selected = await open_viewer(app, pilot, aggregate=aggregate, all_namespaces=True)
        finally:
            directory = ROOT / "artifacts/issue317/ui"
            directory.mkdir(parents=True, exist_ok=True)
            (
                directory
                / (
                    "log-teardown-fixed-"
                    + ("aggregate-" if aggregate else "single-")
                    + boundary
                    + ".json"
                )
            ).write_text(
                json.dumps(
                    {
                        "fields": [
                            "frame_present",
                            "status_mounted",
                            "screen_closed",
                            "owner_closed",
                        ],
                        "observed": observed,
                    },
                    indent=2,
                )
                + "\n"
            )
        assert frame_started.is_set() and body_loaded.is_set(), observed
        assert selected.closed and selected.active_count == 0
    assert api.active == 0 and api.watch_active == 0


@pytest.mark.asyncio
async def test_held_log_transition_observes_enter_without_global_animation_completion(
    tmp_path, monkeypatch
):
    gate = ReadGate(hold=True)
    monkeypatch.setattr(AggregateLogs, "run", gate.wrap(AggregateLogs.run))
    api = single_api()
    completion = None
    async with workspace_api(ns, api.handler) as url:
        app, _ = owned_app(tmp_path, url)
        async with app.run_test() as pilot:
            try:
                screen = await open_viewer(app, pilot, aggregate=True, all_namespaces=True)
                await press_until(pilot, "o", lambda: isinstance(app.screen, ScopeScreen))
                index = WINDOWS.index("Last 5m")
                app.screen.query_one(OptionList).highlighted = index
                # Pinned Textual leaves its public completion wait pending when a
                # delayed animation reaches an unchanged value while idle.
                value = SimpleNamespace(value=0.0)
                app.animator.animate(value, "value", 0.0, duration=0.01, delay=0.01)
                completion = asyncio.create_task(app.animator.wait_until_complete())
                await asyncio.sleep(0.05)
                assert not completion.done()
                await choose_scope(
                    app,
                    pilot,
                    index,
                    effect=lambda: screen.window == "Last 5m" and gate.draining.is_set(),
                )
                assert not completion.done()  # The key fixture did not disable animations.
                assert app.screen is screen and screen.window == "Last 5m"
                assert gate.draining.is_set() and not gate.drained.is_set()
                assert len(gate.calls) == 1 and not screen.capture_export(AT)
                gate.release.set()
                await wait_for(gate.drained.is_set)
                await wait_for(lambda: len(gate.calls) == 2)
            finally:
                gate.release.set()
                if completion is not None:
                    completion.cancel()
                    await asyncio.gather(completion, return_exceptions=True)
        assert all(task.done() for _, _, _, task in gate.calls)
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)
