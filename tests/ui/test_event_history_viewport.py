"""Real App Event history retains its accepted viewport and activation options."""

import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from textual import events

from kuberich.domain.events import EventOptions
from kuberich.services.events import EventProjection
from tests.support.curated_events import CuratedEventsApi
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, started
from tests.ui.test_events import EventHost, rows
from tests.ui.test_events_workspace import events_ready


async def refreshed(table):
    complete = asyncio.get_running_loop().create_future()
    table.call_after_refresh(lambda: complete.set_result(None))
    table.refresh()
    await asyncio.wait_for(complete, 5)


def receipt(name, value):
    directory = Path("artifacts/issue232/events/viewport")
    directory.mkdir(parents=True, exist_ok=True)
    files = (
        "src/kuberich/ui/events.py",
        "src/kuberich/ui/workspace_navigation.py",
        "src/kuberich/ui/workspace_presenter.py",
        "src/kuberich/ui/controllers/events.py",
        "tests/ui/test_event_history_viewport.py",
    )
    value["source"] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}
    (directory / (name + ".json")).write_text(json.dumps(value, indent=2, default=str) + "\n")


@pytest.mark.asyncio
async def test_event_group_back_restores_nonzero_horizontal_viewport_after_native_refresh(tmp_path):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await events_ready(app, api.resource("events", group="events.k8s.io"), count=7)
            await pilot.press("w", "t")
            await wait_for(
                lambda: app.events_table.options == EventOptions(grouped=True, warnings_only=True)
            )
            table = app.events_table
            for row in table.ordered_rows:
                table.move_cursor(row=table.get_row_index(row.key), scroll=False)
                group = table.selected_group()
                if group is not None and len(group.member_uids) == 3:
                    break
            assert group is not None and len(group.member_uids) == 3
            await refreshed(table)
            table.scroll_to(60, 0, animate=False, immediate=True, force=True)
            await refreshed(table)
            before = table.capture_viewport()
            assert before.x == 60
            await asyncio.wait_for(pilot.press("enter"), 5)
            await wait_for(lambda: table.row_count == 3 and table.options.members is not None)
            saved = app.navigator.history.previous[-1]
            assert saved.events == EventOptions(grouped=True, warnings_only=True)
            assert saved.x == before.x and saved.selected == before.selected
            await asyncio.wait_for(pilot.press("escape"), 5)
            await wait_for(
                lambda: (
                    table.row_count == 4
                    and table.options == EventOptions(grouped=True, warnings_only=True)
                    and table.source is not None
                    and table.source.revision == app.workspace.store.observation.revision
                )
            )
            await refreshed(table)
            after = table.capture_viewport()
            receipt(
                "back-public-ports",
                {
                    "before": asdict(before),
                    "saved": asdict(saved),
                    "after": asdict(after),
                    "maximum_scroll_x": table.max_scroll_x,
                    "viewport_width": table.scrollable_content_region.width,
                    "columns": [column.get_render_width(table) for column in table.ordered_columns],
                },
            )
            assert after.selected == before.selected
            assert after.x == before.x
            app.views.request()
            await refreshed(table)
            assert table.capture_viewport().x == before.x
            await pilot.resize_terminal(40, 12)
            await refreshed(table)
            assert table.capture_viewport().selected == before.selected
            assert table.capture_viewport().x == before.x
            await pilot.resize_terminal(100, 30)
            await refreshed(table)
            assert table.capture_viewport().x == before.x


@pytest.mark.asyncio
async def test_enter_on_old_group_cannot_overwrite_a_new_warning_intent(tmp_path, monkeypatch):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await events_ready(app, api.resource("events", group="events.k8s.io"), count=7)
            await pilot.press("t")
            await wait_for(lambda: app.events_table.options == EventOptions(grouped=True))
            await refreshed(app.events_table)
            entered, release = asyncio.Event(), asyncio.Event()
            original = EventProjection.project
            latest = EventOptions(grouped=True, warnings_only=True)

            async def held(self, snapshot, source, options, **kwargs):
                if options == latest:
                    entered.set()
                    await release.wait()
                return await original(self, snapshot, source, options, **kwargs)

            monkeypatch.setattr(EventProjection, "project", held)
            app.navigator.events_options(latest)
            try:
                await asyncio.wait_for(entered.wait(), 5)
                assert app.events_table.options == EventOptions(grouped=True)
                await asyncio.wait_for(pilot.press("enter"), 5)
                observed = app.views.event_options
                receipt(
                    "stale-group-activation",
                    {
                        "latest_intent": asdict(latest),
                        "accepted_table_options": asdict(app.events_table.options),
                        "after_enter": asdict(observed),
                    },
                )
                assert observed == latest
            finally:
                release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["wheel", "cursor", "horizontal", "newer-restore", "reset"])
async def test_newer_input_or_generation_revokes_only_the_pending_event_restore(intent):
    app = EventHost()
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        assert await table.apply_rows(rows(), 1, lambda: True, source=None, options=EventOptions())
        await refreshed(table)
        before = table.capture_viewport()
        desired = replace(before, x=60)
        table.restore_viewport(desired)
        if intent == "wheel":
            table.post_message(events.MouseScrollDown(table, 5, 5, 0, 1, 0, False, False, False))
        elif intent == "cursor":
            table.move_cursor(row=3, scroll=False)
        elif intent == "horizontal":
            table.scroll_to(11, 0, animate=False, immediate=True, force=True)
        elif intent == "newer-restore":
            table.restore_viewport(replace(before, x=30))
        else:
            table.reset(2)
        await refreshed(table)
        if intent == "wheel":
            await pilot.pause()
            assert table.scroll_y > 0 and table.scroll_x == 0
        elif intent == "cursor":
            assert table.cursor_row == 3 and table.scroll_x == 0
        elif intent == "horizontal":
            assert table.scroll_x == 11
        elif intent == "newer-restore":
            assert table.scroll_x == 30
        else:
            assert not table.row_count and table.scroll_x == 0
