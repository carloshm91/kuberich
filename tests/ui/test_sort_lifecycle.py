"""Queued sort messages cannot write to a removed or covered root frame."""

import pytest
from textual.containers import Vertical
from textual.screen import ModalScreen

from kuberich.ui.events import EventsTable
from kuberich.ui.workspace_screen import WorkspaceScreen
from tests.support.curated_events import CuratedEventsApi
from tests.support.curated_resources import curated_resources_api
from tests.ui.test_curated_resources import app_for, started
from tests.ui.test_events_workspace import events_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["active", "covered", "removed"])
async def test_queued_events_sort_respects_the_actual_root_frame_lifecycle(tmp_path, destination):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await events_ready(app, api.resource("events", group="events.k8s.io"), count=7)
            await pilot.pause()
            frame = app.query_one("#resource-view", Vertical)
            if destination == "covered":
                await app.push_screen(ModalScreen())
                await pilot.pause()
            elif destination == "removed":
                # Shutdown closes presentation before queued table messages drain.
                assert isinstance(app.screen, WorkspaceScreen)
                app.screen.foreground.close()
                await frame.remove()
                assert not frame.is_attached

            app.post_message(EventsTable.SortChanged())
            await pilot.pause()
            assert app.is_running and app.return_code is None
            if destination == "active":
                assert app.events_table.sort_summary in str(frame.border_subtitle)
            elif destination == "covered":
                await app.pop_screen()
                await pilot.pause()
                assert app.events_table.sort_summary in str(frame.border_subtitle)
