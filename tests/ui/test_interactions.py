"""Real Pilot interaction matrix against an owned HTTP resource/watch fixture."""

import asyncio

import pytest
from aiohttp import web

from kuberich.domain.views import ViewStatus
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.logs import LogScreen
from tests.support.connections import namespaces
from tests.support.pods import pod
from tests.support.resources import collection, legacy_roots
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation_preferences import app_for
from tests.ui.test_standard_resources import command


def writable_roots():
    roots = legacy_roots()
    roots["/api/v1"]["resources"][0]["verbs"].append("delete")
    return roots


async def ns(request):
    return namespaces("team", "default")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (120, 35)])
async def test_filters_wide_uid_ranges_copy_history_favorites_and_runtime_chrome(tmp_path, size):
    values = [pod("api"), pod("worker", ready=False), pod("unknown")]
    values[0]["metadata"]["labels"] = {"app": "api"}
    values[0]["spec"]["nodeName"] = "node-a"
    values[0]["status"].update(podIP="10.8.0.2", qosClass="Burstable")
    values[2]["status"] = {}

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(*values))

    async with workspace_api(ns, handler) as url:
        app, path = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 3)
            for query, names in [
                ("label:app=api", ["api"]),
                ("field:spec.nodeName=node-a", ["api"]),
                ("fuzzy:wrkr", ["worker"]),
                ("!re:api", ["unknown", "worker"]),
            ]:
                app.filter_input.value = query
                await wait_for(
                    lambda names=names: (
                        [
                            app.resources._rows[row.key.value].name
                            for row in app.resources.ordered_rows
                        ]
                        == names
                    )
                )
            app.filter_input.value = ""
            await wait_for(lambda: app.resources.row_count == 3)
            await command(app, pilot, "errors")
            await wait_for(lambda: app.resources.row_count == 1)
            assert "1 unknown omitted" in str(app.status.content)
            await command(app, pilot, "errors")
            await wait_for(lambda: app.resources.row_count == 3)
            await command(app, pilot, "wide")
            await wait_for(lambda: len(app.resources.columns) == 9)
            assert app.resources.get_row("owned-api")[6].plain == "node-a"
            await command(app, pilot, "wide")
            await wait_for(lambda: len(app.resources.columns) == 6)
            await pilot.press("g", "space", "shift+down")
            assert app.interactions.selection.marked == {"owned-api", "owned-unknown"}
            assert app.resources.rows["owned-api"].label.plain == "●"
            await command(app, pilot, "copy")
            assert app.clipboard == "api\nunknown"
            await command(app, pilot, "copyns")
            assert app.clipboard == "team"
            await command(app, pilot, "copytext")
            assert "api" in app.clipboard and "unknown" in app.clipboard
            await command(app, pilot, "selectnone")
            assert not app.interactions.selection.marked
            await command(app, pilot, "selectall")
            assert len(app.interactions.selection.marked) == 3
            app.filter_input.value = "api"
            await wait_for(
                lambda: (
                    app.resources.row_count == 1
                    and app.interactions.selection.marked == {"owned-api"}
                )
            )
            assert app.interactions.selection.marked == {"owned-api"}
            app.filter_input.value = ""
            await wait_for(lambda: app.resources.row_count == 3)
            await command(app, pilot, "favorite add team")
            await wait_for(lambda: app.interactions._favorite_task.done())
            assert dict(app.navigation.favorites)["kuberich-test-one"] == ("team",)
            assert "favorites" in path.read_text()
            await command(app, pilot, "favorites")
            await wait_for(lambda: app.namespace_table.row_count == 1)
            await command(app, pilot, "ns")
            await wait_for(lambda: app.namespace_table.row_count == 2)
            await command(app, pilot, "po")
            await wait_for(lambda: app.resources.row_count == 3)
            await pilot.press("colon", *"unfinished", "alt+up")
            assert app.command_input.value == "po"
            await pilot.press("alt+down")
            assert app.command_input.value == "unfinished"
            await pilot.press("escape")
            for verb in (
                "headless",
                "crumbsless",
                "fullscreen",
                "fullscreen",
                "crumbsless",
                "headless",
            ):
                await command(app, pilot, verb)
            assert not app.interactions.fullscreen and not app._presentation.headless
            assert app.focused is app.resources
            await command(app, pilot, "!!")
            assert app._presentation.headless
            assert app.interactions.history.entries[-1] == "headless"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["namespace", "permission"])
async def test_live_container_rows_preserve_focus_and_nested_streams_are_drained(tmp_path, failure):
    updates = asyncio.Queue()
    value = pod("api")
    value["spec"]["containers"].append({"name": "worker", "image": "synthetic"})

    async def handler(request):
        if request.path.endswith("/log"):
            return await stable_watch(request, {"line": "owned log"})
        if "watch" in request.query:
            response = web.StreamResponse()
            await response.prepare(request)
            while request.transport is not None and not request.transport.is_closing():
                try:
                    update = await asyncio.wait_for(updates.get(), 0.02)
                    await response.write(frame(update))
                except TimeoutError:
                    continue
            return response
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app, _ = app_for(tmp_path, url)
        async with app.run_test(size=(70, 20)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "G", "colon", *"draft")
            screen = app.screen
            assert isinstance(screen, ContainerScreen)
            assert app.focused is screen.command_input
            value["metadata"]["resourceVersion"] = "updated"
            value["status"]["containerStatuses"].append(
                {"name": "worker", "ready": True, "restartCount": 7, "state": {"running": {}}}
            )
            await updates.put({"type": "MODIFIED", "object": value})
            await wait_for(lambda: screen.table.get_row("worker")[4].plain == "7")
            assert screen._selected_name() == "worker"
            assert app.focused is screen.command_input and screen.command_input.value == "draft"
            await pilot.press("escape", "enter")
            logs = app.screen
            assert isinstance(logs, LogScreen)
            await wait_for(lambda: logs.history.entries)
            await pilot.press("colon", *"scale 3", "enter")
            assert app.screen is logs and not logs.closed
            if failure == "namespace":
                await pilot.press("colon", *"ns default", "enter")
                await wait_for(
                    lambda: (
                        len(app.screen_stack) == 1
                        and app.sessions.observation.namespace == "default"
                    )
                )
            else:
                await updates.put(
                    {
                        "type": "ERROR",
                        "object": {
                            "apiVersion": "v1",
                            "kind": "Status",
                            "code": 403,
                            "reason": "Forbidden",
                            "message": "owned denial",
                        },
                    }
                )
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
                await wait_for(
                    lambda: screen.invalidated and logs.stale and logs._controller.done()
                )
                assert not screen.table.row_count and not logs.history.entries
                screen.observe_record(app.workspace.store.observation.snapshot.items[0])
                assert not screen.table.row_count
                await pilot.press("escape", "escape")
            assert logs._controller.done() and logs._renderer.done()
            assert screen.invalidated


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_readonly_document_and_help_have_independent_text_keys_and_shared_frame(
    tmp_path, size
):
    from textual.containers import VerticalScroll

    from kuberich.ui.app import HelpScreen
    from tests.ui.test_inspection import viewer_loaded

    value = pod("api")
    value["spec"]["containers"] = [
        {"name": f"app-{i:03}", "image": "synthetic/你好-image-long-long-long-long-long:preview"}
        for i in range(50)
    ]

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            collection(value) if request.path.endswith(("/pods", "/events")) else value
        )

    async with workspace_api(ns, handler) as url:
        app, _ = app_for(
            tmp_path,
            url,
            raw={"navigation": {"schema_version": 1, "keys": {"table": {"down": "b"}}}},
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            frame_y = app.query_one("#resource-view").region.y
            await pilot.press("y")
            screen = await viewer_loaded(app)
            await pilot.pause()
            assert screen.query_one("#inspection-dialog").region.y == frame_y
            assert screen.query_one("#workspace-top").region.height == app.header.region.height
            await pilot.press("g", "j", "j", "k")
            assert screen.viewer.cursor_location[0] == 1
            await pilot.press("G")
            assert screen.viewer.cursor_location[0] == screen.viewer.document.line_count - 1
            await pilot.press("ctrl+b")
            row = screen.viewer.cursor_location[0]
            assert row < screen.viewer.document.line_count - 1
            await pilot.press("ctrl+u")
            assert screen.viewer.cursor_location[0] < row
            await pilot.press("ctrl+d", "g", "end")
            assert screen.viewer.cursor_location[0] == 0 and screen.viewer.cursor_location[1] > 0
            await pilot.press("home")
            assert screen.viewer.cursor_location == (0, 0)
            await pilot.press("l", "h")
            await pilot.press("colon", *"copy", "enter")
            assert app.clipboard == "api" and app.screen is screen
            await pilot.press("colon", *"fullscreen", "enter")
            await pilot.pause()
            assert screen.status.display and screen.status.region.height == 1
            assert screen.viewer.scrollable_content_region.height >= 2
            await pilot.press("colon", *"fullscreen", "enter")
            await pilot.pause()
            assert screen.status.display is (size[1] >= 16)
            await pilot.press("colon", *"ns default", "enter")
            await wait_for(
                lambda: (
                    len(app.screen_stack) == 1 and app.sessions.observation.namespace == "default"
                )
            )
            assert screen.invalidated and screen._load_task.done()
            await pilot.press("question_mark")
            help_screen = app.screen
            assert isinstance(help_screen, HelpScreen)
            scroll = help_screen.query_one("#help-scroll", VerticalScroll)
            await pilot.press("G")
            await pilot.pause()
            assert scroll.scroll_y == scroll.max_scroll_y
            await pilot.press("g")
            await pilot.pause()
            assert scroll.scroll_y == 0
            await pilot.press("j", "ctrl+f", "ctrl+b", "ctrl+d", "ctrl+u", "h", "l", "escape")
            assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_generic_wide_reprojects_server_values_without_losing_metadata_matches(
    tmp_path, monkeypatch
):
    from tests.support import custom as fixture
    from tests.support.custom import custom_api
    from tests.ui.test_custom_resources import app_for as custom_app
    from tests.ui.test_custom_resources import loaded

    original = fixture.table

    def with_wide(*args, **kwargs):
        value = original(*args, **kwargs)
        value["columnDefinitions"].append({"name": "Node", "type": "string", "priority": 1})
        for row in value["rows"]:
            row["cells"].append("wide-only")
        return value

    monkeypatch.setattr(fixture, "table", with_wide)
    async with custom_api() as (url, _owner):
        app = custom_app(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            table = app.custom_table
            before = tuple(table.columns)
            table.move_cursor(row=table.get_row_index("owned-two"))
            app.filter_input.value = "field:metadata.name=two"
            await wait_for(lambda: table.row_count == 1)
            await command(app, pilot, "wide")
            await wait_for(lambda: len(table.columns) > len(before) and table.row_count == 1)
            assert table.selected_uid == "owned-two" and "c4" in table.columns
            assert table.get_cell("owned-two", "c4").text == "wide-only"
            await command(app, pilot, "wide")
            await wait_for(lambda: tuple(table.columns) == before and table.row_count == 1)
            assert table.selected_uid == "owned-two"


@pytest.mark.asyncio
async def test_container_projection_coalesces_and_client_close_drains_the_owned_worker(
    tmp_path, monkeypatch
):
    import threading

    from kuberich.ui import containers as module
    from tests.support.pods import record

    value = pod("api")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value))

    async with workspace_api(ns, handler) as url:
        app, _ = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            screen = app.screen
            assert isinstance(screen, ContainerScreen)
            entered, release = threading.Event(), threading.Event()
            original = module._project_containers
            calls = []

            def controlled(item):
                calls.append(item.resource_version)
                if item.resource_version == "blocked":
                    entered.set()
                    assert release.wait(10)
                return original(item)

            monkeypatch.setattr(module, "_project_containers", controlled)
            value["metadata"]["resourceVersion"] = "blocked"
            screen.observe_record(record(value))
            assert await asyncio.to_thread(entered.wait, 5)
            for version in ("intermediate", "latest"):
                value["metadata"]["resourceVersion"] = version
                screen.observe_record(record(value))
            await pilot.press("colon", *"still-responsive")
            assert screen.command_input.value == "still-responsive"
            closing = asyncio.create_task(app.sessions.close())
            await wait_for(lambda: screen.invalidated)
            assert not closing.done()
            release.set()
            await closing
            assert screen._rows_task.done() and not screen.table.row_count
            assert calls == ["blocked"]  # Closing rejects every late/pending result.
            assert app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_nested_delete_review_keeps_captured_uid_and_never_retargets_hidden_cursor(
    tmp_path, stale
):
    from kuberich.ui.operations import ResourceOperationScreen
    from tests.ui.test_inspection import viewer_loaded

    values = [pod("api-a"), pod("api-b")]
    requests = []

    async def handler(request):
        requests.append(request.method)
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(*values))
        if request.path.endswith("/events"):
            return web.json_response(collection())
        return web.json_response(values[0])

    async with workspace_api(ns, handler, discovery_roots=writable_roots) as url:
        app, _ = app_for(tmp_path, url, readonly=False)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 2)
            await pilot.press("g", "d")
            screen = await viewer_loaded(app)
            app.resources.move_cursor(row=app.resources.get_row_index("owned-api-b"))
            if stale:
                # Fatal scope loss is also covered through the real watch test;
                # this boundary deliberately rejects the captured origin guard.
                screen.service.current = lambda: False
            await pilot.press("colon", *"delete", "enter")
            await wait_for(lambda: app._nested_route_task.done())
            if stale:
                assert app.screen is screen
                assert not isinstance(app.screen, ResourceOperationScreen)
            else:
                assert isinstance(app.screen, ResourceOperationScreen)
                assert app.screen.sources[0].target.uid == "owned-api-a"
                assert app.focused.id == "operation-cancel"
            assert set(requests) == {"GET"}


@pytest.mark.asyncio
async def test_marked_batch_review_contains_only_marked_uids_with_default_cancel(tmp_path):
    from kuberich.ui.operations import ResourceOperationScreen

    values = [pod("api-a"), pod("api-b"), pod("api-c")]

    async def handler(request):
        assert request.method == "GET"
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(*values))

    async with workspace_api(ns, handler, discovery_roots=writable_roots) as url:
        app, _ = app_for(tmp_path, url, readonly=False)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 3)
            await pilot.press("g", "space", "shift+down")
            await command(app, pilot, "deletebatch")
            review = app.screen
            assert isinstance(review, ResourceOperationScreen)
            assert [source.target.uid for source in review.sources] == [
                "owned-api-a",
                "owned-api-b",
            ]
            assert app.focused.id == "operation-cancel"
            await pilot.press("enter")
            assert len(app.screen_stack) == 1
