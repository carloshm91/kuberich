"""Shared boundary keys supersede older motion without replacing resource identity."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.ui.presentation import FrameTable
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, loaded, started


@asynccontextmanager
async def ordinary_table(tmp_path, kind):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        app.animation_level = "full"
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            if kind == "standard":
                resource = api.resource(
                    "mutatingwebhookconfigurations", group="admissionregistration.k8s.io"
                )
                await app.run_command("mutatingwebhookconfigurations")
                await loaded(app, pilot, resource)
                table = app.standard_table
            else:
                table = app.resources
            await table.wait_for_refresh()
            table.focus()
            yield app, pilot, table


async def moving(table, key):
    start, target = (0, 60) if key == "home" else (60, 0)
    table.scroll_to(start, 0, animate=False, immediate=True, force=True)
    table.scroll_to(target, 0, animate=True, duration=0.5, immediate=True, force=True)
    await wait_for(lambda: 0 < table.scroll_x < 60)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard"])
@pytest.mark.parametrize("key", ["home", "end"])
async def test_real_ordinary_boundary_key_wins_over_pending_animation(tmp_path, kind, key):
    async with ordinary_table(tmp_path, kind) as (_, pilot, table):
        selected = table.selected_uid
        await moving(table, key)
        await asyncio.wait_for(pilot.press(key), 5)
        desired = 0 if key == "home" else table.max_scroll_x
        assert table.scroll_x == table.scroll_target_x == desired
        assert table.selected_uid == selected


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard"])
@pytest.mark.parametrize("key", ["home", "end"])
async def test_no_movement_boundary_key_revokes_old_restore_but_allows_new_restore(
    tmp_path, kind, key
):
    async with ordinary_table(tmp_path, kind) as (_, _, table):
        current = 0 if key == "home" else table.max_scroll_x
        table.scroll_to(current, 0, animate=False, immediate=True, force=True)
        await table.wait_for_refresh()
        viewport = table.capture_viewport()
        table.restore_viewport(replace(viewport, x=60))
        getattr(table, "action_scroll_" + key)()
        await table.wait_for_refresh()
        assert table.scroll_x == current and table.selected_uid == viewport.selected
        table.restore_viewport(replace(viewport, x=60))
        await table.wait_for_refresh()
        assert table.scroll_x == 60 and table.selected_uid == viewport.selected


class CursorHost(App[None]):
    CSS = "DataTable { width: 1fr; height: 1fr; }"

    def __init__(self, cursor_type, show_cursor):
        super().__init__()
        self.animation_level = "full"
        self.table = FrameTable(cursor_type=cursor_type, show_cursor=show_cursor)

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        for index in range(3):
            self.table.add_column(f"Column {index}", key=str(index), width=100)
        self.table.add_row("one", "two", "three", key="owned-a")
        self.table.add_row("four", "five", "six", key="owned-b")
        self.table.move_cursor(row=1, column=1)
        self.table.focus()


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor_type", ["row", "cell", "column"])
@pytest.mark.parametrize("show_cursor", [False, True])
@pytest.mark.parametrize("key", ["home", "end"])
async def test_shared_boundary_keeps_native_cursor_semantics(cursor_type, show_cursor, key):
    app = CursorHost(cursor_type, show_cursor)
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        await table.wait_for_refresh()
        await moving(table, key)
        await asyncio.wait_for(pilot.press(key), 5)
        desired = 0 if key == "home" else table.max_scroll_x
        assert table.scroll_x == table.scroll_target_x == desired
        assert table.cursor_row == 1
        assert table.cursor_column == (
            (0 if key == "home" else 2) if show_cursor and cursor_type in {"cell", "column"} else 1
        )


@pytest.mark.asyncio
async def test_new_arrow_motion_starts_from_the_requested_boundary():
    app = CursorHost("row", True)
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        await table.wait_for_refresh()
        await moving(table, "home")
        await asyncio.wait_for(pilot.press("home", "right"), 5)
        assert table.scroll_x == table.scroll_target_x == 1
        await asyncio.wait_for(pilot.press("end", "left"), 5)
        assert table.scroll_x == table.scroll_target_x == table.max_scroll_x - 1
