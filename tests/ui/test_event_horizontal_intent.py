"""Horizontal boundary keys supersede real motion and queued Event restorations."""

import asyncio
from dataclasses import replace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from kuberich.domain.events import EventOptions
from kuberich.ui.events import EventsTable
from tests.support.workspace import wait_for
from tests.ui.test_event_history_viewport import refreshed
from tests.ui.test_events import rows


class HorizontalHost(App[None]):
    CSS = "DataTable { width: 1fr; height: 1fr; }"

    def __init__(self, *, native=False):
        super().__init__()
        self.animation_level = "full"
        self.table = DataTable(cursor_type="row") if native else EventsTable()

    def compose(self) -> ComposeResult:
        yield self.table

    async def on_mount(self):
        if isinstance(self.table, EventsTable):
            self.table.setup()
            await self.table.apply_rows(
                rows(4), 1, lambda: True, source=None, options=EventOptions()
            )
        else:
            self.table.add_column("Name", key="name", width=200)
            self.table.add_row("owned-row", key="owned")
        self.table.focus()


async def moving(table, key):
    start, target = (0, 60) if key == "home" else (60, 0)
    table.scroll_to(start, 0, animate=False, immediate=True, force=True)
    table.scroll_to(target, 0, animate=True, duration=0.5, immediate=True, force=True)
    await wait_for(lambda: 0 < table.scroll_x < 60)
    assert table.scroll_target_x == target
    return target


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["home", "end"])
async def test_pinned_native_boundary_assignment_leaves_the_old_animation_running(key, monkeypatch):
    app = HorizontalHost(native=True)
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        await refreshed(table)
        target = await moving(table, key)
        original = getattr(DataTable, "action_scroll_" + key)
        delivered = []

        def boundary(self):
            original(self)
            delivered.append((self.scroll_x, self.scroll_target_x))

        monkeypatch.setattr(DataTable, "action_scroll_" + key, boundary)
        await asyncio.wait_for(pilot.press(key), 5)
        assert delivered == [(0 if key == "home" else table.max_scroll_x, target)]
        # Characterize the pinned native behavior that the Events adapter fixes.
        assert table.scroll_x == table.scroll_target_x == target


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["home", "end"])
@pytest.mark.parametrize("cursor_burst", [False, True])
async def test_event_boundary_key_wins_after_pending_animation_and_cursor_actions(
    key, cursor_burst
):
    app = HorizontalHost()
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        await refreshed(table)
        await moving(table, key)
        if cursor_burst:
            table.action_scroll_top()
            table.action_cursor_down()
        selected = table.selected_uid
        await asyncio.wait_for(pilot.press(key), 5)
        desired = 0 if key == "home" else table.max_scroll_x
        assert table.scroll_x == table.scroll_target_x == desired
        assert table.selected_uid == selected


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["home", "end"])
async def test_no_movement_boundary_intent_revokes_an_older_queued_restore(key):
    app = HorizontalHost()
    async with app.run_test(size=(100, 30)):
        table = app.table
        await refreshed(table)
        current = 0 if key == "home" else table.max_scroll_x
        table.scroll_to(current, 0, animate=False, immediate=True, force=True)
        await refreshed(table)
        viewport = table.capture_viewport()
        table.restore_viewport(replace(viewport, x=60))
        getattr(table, "action_scroll_" + key)()
        await refreshed(table)
        assert table.scroll_x == current


@pytest.mark.asyncio
async def test_normal_arrow_motion_starts_from_the_new_boundary_target():
    app = HorizontalHost()
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        await refreshed(table)
        await moving(table, "home")
        await asyncio.wait_for(pilot.press("home", "right"), 5)
        assert table.scroll_x == table.scroll_target_x == 1
        await asyncio.wait_for(pilot.press("end", "left"), 5)
        assert table.scroll_x == table.scroll_target_x == table.max_scroll_x - 1
