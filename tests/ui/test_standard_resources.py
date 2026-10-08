"""All advertised standard views use actual discovery, LIST/WATCH and UID-scoped GET."""

import asyncio
import logging
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain.registry import RESOURCE_ALIASES, STANDARD_RESOURCES
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from tests.support.connections import catalog_fixture
from tests.support.standard import api, manifest, standard_api
from tests.support.watches import frame
from tests.support.workspace import wait_for


def app_for(tmp_path, url, initial=None):
    options = {"initial_command": initial} if initial is not None else {}
    return KubeRichApp(
        Settings(read_only=True),
        logging.Logger("standard-views", level=100),
        catalog=catalog_fixture(tmp_path, url),
        **options,
    )


async def loaded(app, resource):
    await wait_for(
        lambda: (
            app._resource_name == resource
            and app.workspace.store.observation.status is ViewStatus.LIVE
            and app.standard_table.row_count > 0
        )
    )


async def command(app, pilot, value):
    await pilot.press("colon")
    app.command_input.value = value
    await pilot.press("enter")


@pytest.mark.asyncio
@pytest.mark.parametrize("definition", STANDARD_RESOURCES, ids=[d.name for d in STANDARD_RESOURCES])
async def test_every_resource_has_discovered_list_watch_detail_and_correct_hints(
    tmp_path, definition
):
    async with standard_api(tmp_path) as (url, reads):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await command(app, pilot, definition.aliases[0])
            await loaded(app, definition.name)
            await pilot.pause()
            resource = api(definition)
            path = resource.path("team" if definition.namespaced else None)
            assert any(p == path and "watch" not in q for p, q in reads)
            await wait_for(lambda: any(p == path and q.get("watch") == "true" for p, q in reads))
            assert any(p == path and q.get("resourceVersion") == "opaque/list" for p, q in reads)
            assert app.standard_table.selected_uid == "owned-owned-one"
            assert tuple(column.value for column in app.standard_table.columns) == tuple(
                column.key for column in definition.columns
            )
            assert "Shell" not in str(app.header.shortcuts) and "Logs" not in str(
                app.header.shortcuts
            )
            assert not app.resources.display and not app.namespace_table.display
            assert app.query_one("#resource-view").region.width == 98
            if not definition.namespaced:
                assert "(cluster)" in str(app.query_one("#resource-view").border_title)
            before = app.standard_table.capture_viewport()
            await pilot.press("enter")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            assert (
                app.screen.page == "details"
                and definition.name[:-1].casefold()[:5] in app.screen.viewer.text.casefold()
            )
            assert any(p == path + "/owned-one" for p, _ in reads)
            await pilot.press("y")
            assert "owned-owned-one" in app.screen.viewer.text
            assert "private-" not in app.screen.viewer.text
            await pilot.press("e")
            assert "No related events" in app.screen.viewer.text
            await pilot.press("escape")
            assert app.standard_table.capture_viewport() == before
            assert app.focused is app.standard_table
            await pilot.press("l")
            assert len(app.screen_stack) == 1 and app.check_action("logs", ()) is False
            assert app.check_action("shell", ()) is False
        assert app.sessions.client is None and app._render_task.done() and app._view_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["absent", "denied"])
async def test_absent_and_forbidden_are_failures_not_empty_success_and_recover(tmp_path, mode):
    async with standard_api(tmp_path, **{mode: "deployments"}) as (url, reads):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await command(app, pilot, "deploy")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
            await pilot.pause()
            assert app.standard_table.row_count == 0
            assert app.query_one("#empty-title").content == "Resource data unavailable"
            assert (
                "403" in str(app.status.content)
                if mode == "denied"
                else "unavailable" in str(app.status.content).lower()
            )
            assert not any(q.get("watch") for p, q in reads if p.endswith("/deployments"))
            await command(app, pilot, "svc other")
            await loaded(app, "services")
            assert app.workspace.store.observation.scope.namespace == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_scopes_filter_sort_vim_history_context_return_and_stable_geometry(tmp_path, size):
    async with standard_api(tmp_path) as (url, reads):
        app = app_for(tmp_path, url, ResourceCommand(RESOURCE_ALIASES["deploy"], "other"))
        async with app.run_test(size=size) as pilot:
            await loaded(app, "deployments")
            await pilot.pause()
            assert app.workspace.store.observation.scope.namespace == "other"
            bounds = app.query_one("#resource-view").region
            await pilot.press("s", "S", "G", "g", "j", "k")
            assert app.standard_table.sort_column == "ready" and app.standard_table.descending
            await pilot.press("slash", *"owned", "enter")
            await wait_for(lambda: "Filter active" in str(app.status.content))
            before = app.standard_table.capture_viewport()
            await command(app, pilot, "pv")
            await loaded(app, "persistentvolumes")
            assert (
                app.filter_input.value == ""
                and app.workspace.store.observation.scope.namespace is None
            )
            assert app.query_one("#resource-view").region == bounds
            await pilot.press("alt+left")
            await loaded(app, "deployments")
            await pilot.pause()
            assert app.filter_input.value == "owned"
            assert app.standard_table.sort_column == "ready" and app.standard_table.descending
            assert app.standard_table.capture_viewport() == before
            await pilot.press("c")
            await wait_for(lambda: app.context_table.row_count > 0)
            assert app._resource_name == "contexts"
            await pilot.press("escape")
            await loaded(app, "deployments")
            assert app.workspace.selection.group == "apps"
            await command(app, pilot, "deploy *")
            await loaded(app, "deployments")
            assert app.workspace.store.observation.scope.namespace is None
            assert any(
                path == "/apis/apps/v1/deployments" and "watch" not in query
                for path, query in reads
            )
            output = Path("artifacts/ui").resolve()
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"standard-resources-{size[0]}.svg", path=str(output))


@pytest.mark.asyncio
async def test_watch_updates_preserve_uid_and_replacement_uses_new_identity(tmp_path):
    release = asyncio.Event()
    watched = asyncio.Event()

    async def handler(request, definition):
        if definition.name != "deployments" or "watch" not in request.query:
            return None
        response = web.StreamResponse()
        await response.prepare(request)
        watched.set()
        await release.wait()
        changed = manifest(definition)
        changed["metadata"]["resourceVersion"] = "opaque/updated"
        changed["status"] = {"readyReplicas": 2}
        await response.write(frame({"type": "MODIFIED", "object": changed}))
        while request.transport is not None and not request.transport.is_closing():
            await asyncio.sleep(0.01)
        return response

    async with standard_api(tmp_path, handler) as (url, _):
        app = app_for(tmp_path, url, ResourceCommand(RESOURCE_ALIASES["deploy"]))
        async with app.run_test() as pilot:
            await loaded(app, "deployments")
            await watched.wait()
            uid = app.standard_table.selected_uid
            await pilot.press("s", "S")
            release.set()
            await wait_for(lambda: str(app.standard_table.get_cell(uid, "ready")) == "2")
            assert app.standard_table.selected_uid == uid and app.standard_table.descending
            assert app.standard_table.sort_column == "ready"
            await command(app, pilot, "sc")
            await loaded(app, "storageclasses")
            assert app.standard_table.definition.group == "storage.k8s.io"
