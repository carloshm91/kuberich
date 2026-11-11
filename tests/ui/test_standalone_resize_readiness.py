"""Controlled container geometry distinguishes an early key from compact-ready input."""

import asyncio
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.ui.chrome import WorkspaceChrome, WorkspaceHeader
from kuberich.ui.containers import ContainerScreen
from tests.support.workspace import wait_for


class ContainerResizeHost(App):
    def __init__(self):
        super().__init__()
        target = ResourceTarget(
            SessionIdentity("synthetic", 1), "", "pods", "default", "owned", "pod-uid"
        )
        self.containers = ContainerScreen(
            SimpleNamespace(target=target, require_current=lambda: None),
            {"spec": {"containers": [{"name": "app"}, {"name": "worker"}]}},
            chrome=WorkspaceChrome(
                lambda: ("synthetic", "synthetic", "synthetic", "default", "Ready"), "test"
            ),
            inspect_container=lambda _identity: None,
        )

    def compose(self) -> ComposeResult:
        yield Button("Root")

    def on_mount(self):
        self.push_screen(self.containers)


def visible_rows(table):
    return "\n".join(table.render_line(line).text for line in range(table.size.height))


def compact_geometry(app):
    hint = app.containers.query_one("#container-hints", Static)
    return hint.display and hint.region.y == 3 and app.size.width == 40 and app.size.height == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("compact_ready", [False, True])
async def test_single_last_row_key_waits_for_owned_compact_geometry(compact_ready):
    app = ContainerResizeHost()
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.containers.table
        assert table.row_count == 2 and "worker" in visible_rows(table)
        if not compact_ready:
            # Hold the compact layout until after the one key is handled.
            await pilot.press("G")
            assert table.cursor_row == 1 and table.scroll_y == 0
        await pilot.resize_terminal(40, 12)
        await wait_for(lambda: compact_geometry(app))
        if compact_ready:
            await pilot.press("G")
        assert table.cursor_row == 1
        assert ("worker" in visible_rows(table)) is compact_ready


@pytest.mark.asyncio
async def test_last_row_input_waits_for_a_held_public_layout_callback(monkeypatch):
    held, released, observed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    layout_header = WorkspaceHeader.layout_header

    def hold_compact_layout(header):
        if header.app.size.width == 40 and header.app.size.height == 12 and not released.is_set():
            held.set()
            return
        layout_header(header)

    monkeypatch.setattr(WorkspaceHeader, "layout_header", hold_compact_layout)
    app = ContainerResizeHost()
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.containers.table
        assert table.cursor_row == 0
        await pilot.resize_terminal(40, 12)
        await asyncio.wait_for(held.wait(), 5)
        assert app.size.width == 40 and app.size.height == 12 and not compact_geometry(app)

        def geometry_published():
            observed.set()
            return compact_geometry(app)

        async def select_when_published():
            await wait_for(geometry_published)
            await pilot.press("G")

        async with asyncio.TaskGroup() as tasks:
            selected = tasks.create_task(select_when_published())
            await asyncio.wait_for(observed.wait(), 5)
            assert not selected.done() and table.cursor_row == 0
            released.set()
            app.containers.query_one(WorkspaceHeader).layout_header()
            await selected
        assert compact_geometry(app) and table.cursor_row == 1 and "worker" in visible_rows(table)
