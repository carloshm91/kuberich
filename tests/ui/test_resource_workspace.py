"""The real workspace, namespace LIST/WATCH and nested routes over an owned API."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web
from textual.app import App, ComposeResult
from textual.events import Paste
from textual.widgets import Input, Static

from kuberich.domain.namespaces import namespace_row
from kuberich.domain.resources import resource_record
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import Command
from kuberich.ui.chrome import WorkspaceHeader
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.logs import LogScreen
from kuberich.ui.namespaces import NamespaceTable
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app
from tests.unit.test_namespaces import RESOURCE, namespace


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (60, 18), (100, 30), (180, 50)])
async def test_top_input_namespace_table_drilldown_escape_and_actual_view_hints(
    tmp_path, size, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    values = tuple(namespace(f"team-{i:02}") for i in range(40))

    async def ns(request):
        return web.json_response(collection(*values))

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        name = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        value = pod("api", namespace=name, uid=f"{name}-api")
        if request.path.endswith("/log"):
            return web.Response(text="owned workspace line\n")
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            assert app.theme == "k9s"
            assert app.filter_input.region.y < app.resources.region.y
            assert app.command_input.region.y < app.resources.region.y
            assert "owned" in str(app.header.query_one("#cluster", Static).content)
            assert "0.0.1.dev0" in str(app.header.query_one("#build-info", Static).content)
            await pilot.pause()
            frame = app.query_one("#resource-view").region
            identifiers = ("workspace-top", "scope-bar", "app-header", "view-actions", "brand")
            header_regions = tuple(app.screen.query_one(f"#{key}").region for key in identifiers)
            footer = app.breadcrumbs.region
            await pilot.press("colon", *"ns", "enter")
            await wait_for(lambda: app.namespace_table.row_count == 40)
            assert len(app.screen_stack) == 1 and app.focused is app.namespace_table
            assert app.workspace.store.observation.scope.resource.name == "namespaces"
            assert app.namespace_table.get_row("namespace-team-00")[1].plain == "Active"
            assert app.query_one("#resource-view").region == frame
            await pilot.press("slash", *"re:team-", "enter", "G", "up")
            await pilot.pause()
            uid = app.namespace_table.selected_uid
            viewport = app.namespace_table.capture_viewport()
            assert uid == "namespace-team-38" and viewport.y > 0
            out = Path("artifacts/ui").resolve()
            out.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"workspace-namespaces-{size[0]}.svg", path=str(out))
            await pilot.press("enter")
            await wait_for(lambda: app.resources.row_count == 1 and app._resource_name == "pods")
            assert app.workspace.store.observation.connection.namespace == "team-38"
            assert app.filter_input.value == ""
            assert "namespaces > pods" in str(app.breadcrumbs.content)
            assert "Esc → Namespaces" in str(app.breadcrumbs.content)
            assert app.query_one("#resource-view").region == frame
            await pilot.press("enter")
            assert isinstance(app.screen, ContainerScreen)
            containers = app.screen
            if size[1] >= 16:
                await pilot.pause()
                assert "Shell" in str(containers.query_one("#view-actions", Static).content)
            else:
                assert "shell" in str(containers.query_one("#container-hints", Static).content)
            assert "containers" in str(containers.query_one("#breadcrumbs", Static).content)
            assert containers.query_one("#container-dialog").region == frame
            assert containers.table.content_region.height >= 2
            assert containers.query_one("#container-back").region.bottom <= frame.y
            assert (
                tuple(containers.query_one(f"#{key}").region for key in identifiers)
                == header_regions
            )
            assert containers.query_one("#breadcrumbs").region == footer
            app.save_screenshot(filename=f"workspace-containers-{size[0]}.svg", path=str(out))
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and app.screen.body.rows)
            logs = app.screen
            if size[1] >= 16:
                assert "Pause" in str(logs.query_one("#view-actions", Static).content)
            assert "logs" in str(logs.breadcrumbs.content) and "Containers" in str(
                logs.breadcrumbs.content
            )
            assert logs.breadcrumbs.content.cell_len <= logs.breadcrumbs.size.width
            assert logs.search.region.y < logs.body.region.y
            assert logs.body.content_region.height >= 1
            assert logs.query_one("#log-dialog").region == frame
            assert tuple(logs.query_one(f"#{key}").region for key in identifiers) == header_regions
            assert logs.breadcrumbs.region == footer
            await pilot.click("#log-search")
            await pilot.pause()
            assert logs.focused is logs.search and logs.query_one("#log-dialog").region == frame
            await pilot.click("#log-pause")
            await pilot.pause()
            assert logs.paused and logs.query_one("#log-dialog").region == frame
            await pilot.click("#log-pause")
            await pilot.resize_terminal(80, 24)
            await pilot.resize_terminal(*size)
            await pilot.pause()
            assert logs.query_one("#log-dialog").region == frame
            app.save_screenshot(filename=f"workspace-logs-{size[0]}.svg", path=str(out))
            await pilot.press("slash", *"own")
            assert "Leave search" in str(logs.breadcrumbs.content)
            await pilot.press("escape", "z")
            assert not logs.query_one(WorkspaceHeader).display
            await pilot.press("z")
            assert logs.query_one(WorkspaceHeader).display
            await pilot.press("escape", "escape", "escape")
            await wait_for(
                lambda: app.namespace_table.row_count == 40 and app._resource_name == "namespaces"
            )
            await pilot.pause()
            assert app.filter_input.value == "re:team-"
            assert app.namespace_table.capture_viewport() == viewport
            await pilot.press("escape")
            assert app.filter_input.value == ""
            await pilot.press("0")
            await wait_for(
                lambda: (
                    app._resource_name == "pods"
                    and app.workspace.store.observation.connection.namespace is None
                )
            )
            await pilot.press("escape")
            await wait_for(
                lambda: app._resource_name == "namespaces" and app.namespace_table.row_count == 40
            )
            assert app.namespace_table.selected_uid == uid
            await pilot.press("escape")
            await wait_for(lambda: app._resource_name == "pods")
        assert app.sessions.client is None and app._render_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["empty", "forbidden", "stale", "replaced"])
async def test_namespace_api_errors_and_updates_preserve_live_identity_and_do_not_look_empty(
    tmp_path, state
):
    queue = asyncio.Queue()
    calls = []
    initial = namespace("team")

    async def ns(request):
        calls.append(request.path)
        if state == "forbidden":
            return web.Response(status=403)
        return web.json_response(collection(*(() if state == "empty" else (initial,))))

    async def resources(request):
        if request.path == "/api/v1/namespaces" and "watch" in request.query:
            if state == "stale":
                return web.Response(status=503)
            response = web.StreamResponse()
            await response.prepare(request)
            while request.transport and not request.transport.is_closing():
                try:
                    value = await asyncio.wait_for(queue.get(), 0.02)
                except TimeoutError:
                    continue
                await response.write(frame(value))
            return response
        if "watch" in request.query:
            return await stable_watch(request)
        name = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        return web.json_response(collection(pod("api", namespace=name)))

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            app.action_namespaces()
            if state == "empty":
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
                assert app.namespace_table.row_count == 0
                await wait_for(
                    lambda: "No namespaces" in str(app.query_one("#empty-title", Static).content)
                )
                assert app.query_one("#all-namespaces").display
            elif state == "forbidden":
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
                await wait_for(lambda: "403" in str(app.status.content))
                await wait_for(
                    lambda: (
                        "unavailable" in str(app.query_one("#empty-title", Static).content).lower()
                    )
                )
                await pilot.press("colon", *"ns allowed", "enter")
                await wait_for(
                    lambda: app._resource_name == "pods" and app.resources.row_count == 1
                )
            elif state == "stale":
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.STALE)
                await wait_for(lambda: app.namespace_table.row_count == 1)
                assert app.namespace_table.row_count == 1
                await wait_for(
                    lambda: "Stale" in str(app.status.content) and "503" in str(app.status.content)
                )
            else:
                await wait_for(lambda: app.namespace_table.row_count == 1)
                queue.put_nowait({"type": "DELETED", "object": initial})
                queue.put_nowait({"type": "ADDED", "object": namespace("team", uid="replacement")})
                await wait_for(lambda: app.namespace_table.selected_uid == "replacement")
                assert "namespace-team" not in app.namespace_table.rows
                await pilot.press("enter")
                await wait_for(
                    lambda: app._resource_name == "pods" and app.resources.row_count == 1
                )
            await pilot.press("ctrl+q")
        assert app.workspace._watch is None and app.sessions.client is None


@pytest.mark.asyncio
async def test_initial_namespaces_history_and_connecting_scope_guard_preserve_routes(
    tmp_path,
):
    async def ns(request):
        return namespaces("team", "default")

    async def resources(request):
        return (
            await stable_watch(request)
            if "watch" in request.query
            else web.json_response(collection(pod("api")))
        )

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url), initial=Command.NAMESPACES)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.namespace_table.row_count == 2)
            assert app.resources.row_count == 0 and app.focused is app.namespace_table
            await pilot.press("escape")
            await wait_for(lambda: app._resource_name == "pods" and app.resources.row_count == 1)
            await pilot.press("colon", *"ns", "enter")
            await wait_for(lambda: app.namespace_table.row_count == 2)
            await pilot.press("colon", *"po", "enter")
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("alt+left")
            await wait_for(
                lambda: app._resource_name == "namespaces" and app.namespace_table.row_count == 2
            )
            await pilot.press("alt+right")
            await wait_for(lambda: app._resource_name == "pods" and app.resources.row_count == 1)
            app.action_namespaces()
            app._start_connection("kuberich-test-Two")
            app._submit_command("po")
            assert app._resource_name == "namespaces"
            app._namespace_selected("default")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert app.workspace.store.observation.context == "kuberich-test-Two"
            assert not app._namespace_route and app._namespace_state is None
            assert len(app.screen_stack) == 1
            assert app.command_input.region.y < app.query_one("#resource-view").region.y


@pytest.mark.asyncio
async def test_shortcuts_reflow_when_logo_width_settles_without_another_header_resize():
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        brand = app.header.query_one("#brand", Static)
        brand.styles.width = 10
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        header_region = app.header.region
        actions = app.header.query_one("#view-actions", Static)
        assert actions.content_region.width == 61
        # Model the logo width settling after the header's resize was processed.
        brand.styles.width = 22
        await pilot.pause()
        assert app.header.region == header_region and actions.content_region.width == 49
        hints = str(actions.content)
        assert "<n / :ns> Namespaces" in hints and "<?> Help" in hints
        assert "<l/L> Logs / aggregate" in hints
        assert all(len(line) <= actions.content_region.width for line in hints.splitlines())


@pytest.mark.asyncio
@pytest.mark.parametrize("theme", ["k9s", "textual-light"])
async def test_theme_no_color_hostile_aliases_and_input_keys_remain_literal_and_work(
    tmp_path, monkeypatch, theme
):
    monkeypatch.setenv("NO_COLOR", "1")
    app = make_app()
    app.theme = theme
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.no_color
        await pilot.press("colon")
        app.command_input.post_message(Paste("ns [red]\x1b]52;c;bad\x07"))
        await pilot.pause()
        assert isinstance(app.focused, Input) and len(app.screen_stack) == 1
        await pilot.press("escape", "slash", *"cnri")
        assert app.filter_input.value == "cnri"
        await pilot.resize_terminal(40, 12)
        assert app.command_input.region.bottom <= 12


@pytest.mark.asyncio
async def test_batched_namespace_patch_rejects_obsolete_generation_and_preserves_live_uid():
    class TableApp(App):
        def compose(self) -> ComposeResult:
            yield NamespaceTable()

        def on_mount(self) -> None:
            self.query_one(NamespaceTable).setup()

    app = TableApp()
    async with app.run_test(size=(60, 18)) as pilot:
        table = app.query_one(NamespaceTable)
        values = tuple(
            namespace_row(resource_record(RESOURCE, namespace(f"team-{i:03}"))) for i in range(260)
        )
        checks = 0

        def current() -> bool:
            nonlocal checks
            checks += 1
            return checks <= 2

        assert not await table.apply_rows(values, 1, current)
        assert table.row_count == 128
        assert not await table.apply_rows(values, 2, lambda: False)
        assert table.row_count == 128
        assert await table.apply_rows(values, 2, lambda: True)
        await pilot.press("G", "up")
        await pilot.pause()
        selected = table.selected_uid
        viewport = table.capture_viewport()
        changed = tuple(
            replace(row, status="Terminating") if row.uid == selected else row for row in values[1:]
        )
        assert await table.apply_rows(changed, 2, lambda: True)
        table.refresh_ages()
        await pilot.pause()
        assert table.selected_uid == selected
        assert table.capture_viewport().top == viewport.top
        assert table.get_row(selected)[1].plain == "Terminating"
        assert values[0].uid not in table.rows
        assert await table.apply_rows((), 3, lambda: True)
        await pilot.pause()
        assert table.row_count == 0 and table.selected_uid is None


@pytest.mark.asyncio
async def test_delayed_namespace_list_cannot_repopulate_table_after_context_switch(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def ns(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            started.set()
            await release.wait()
            return web.json_response(collection(namespace("obsolete")))
        return namespaces("team", "default")

    async def resources(request):
        name = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        return (
            await stable_watch(request)
            if "watch" in request.query
            else web.json_response(collection(pod("api", namespace=name)))
        )

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            app.action_namespaces()
            await asyncio.wait_for(started.wait(), 5)
            app._select_resource("pods")
            app._start_connection("kuberich-test-Two")
            release.set()
            await wait_for(
                lambda: (
                    app.resources.row_count == 1
                    and app.workspace.store.observation.context == "kuberich-test-Two"
                )
            )
            await pilot.pause()
            assert app.namespace_table.row_count == 0
            assert "namespace-obsolete" not in app.namespace_table.rows
            assert app._resource_name == "pods" and len(app.screen_stack) == 1
            await pilot.press("ctrl+q")
        assert app.workspace._watch is None and app.sessions.client is None
