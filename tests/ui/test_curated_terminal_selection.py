"""A sorted row order does not replace the selected resource's stable identity."""

import pytest

from kuberich.ui.inspection import InspectionScreen
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, loaded, ordered_uids, started


@pytest.mark.asyncio
async def test_sort_preserves_uid_then_native_first_row_selects_exact_fresh_inspector(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            resource = api.resource(
                "mutatingwebhookconfigurations", group="admissionregistration.k8s.io"
            )
            await app.run_command("mutatingwebhookconfigurations")
            await loaded(app, pilot, resource)
            table = app.standard_table
            root_screen = app.screen
            bodies = sorted(api.objects(resource), key=lambda body: body["metadata"]["name"])
            a, b = (body["metadata"]["uid"] for body in bodies)
            table.restore_sort("name", False)
            await pilot.press("g")
            assert table.selected_uid == a

            # Sorting changes numeric order while deliberately retaining selected UID A.
            table.restore_sort("timeout-max", False)
            await pilot.pause()
            assert ordered_uids(table) == (b, a)
            assert table.selected_uid == a and table.cursor_row == 1

            # The former terminal helper sent bare Enter, which correctly inspected A.
            read_from = len(api.requests)
            await pilot.press("enter")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            screen = app.screen
            assert isinstance(screen, InspectionScreen)
            assert screen.service.resource == resource
            assert screen.service.target.name == "owned-a" and screen.service.target.uid == a
            assert any(
                entry.method == "GET"
                and entry.path == resource.path() + "/owned-a"
                and "watch" not in entry.query
                for entry in api.requests[read_from:]
            )
            await pilot.press("escape")
            await wait_for(lambda: app.screen is root_screen and screen.operation_count == 0)
            await table.wait_for_refresh()
            assert table.selected_uid == a

            # Explicit native g selects first; Enter must inspect commanded raw UID B.
            read_from = len(api.requests)
            await pilot.press("g", "enter")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            screen = app.screen
            assert isinstance(screen, InspectionScreen)
            assert screen.service.resource == resource
            assert screen.service.target.name == "owned-b" and screen.service.target.uid == b
            assert any(
                entry.method == "GET"
                and entry.path == resource.path() + "/owned-b"
                and "watch" not in entry.query
                for entry in api.requests[read_from:]
            )
            assert table.selected_uid == b and table.cursor_row == 0
