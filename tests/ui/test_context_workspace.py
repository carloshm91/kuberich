"""Context browsing, selection and return run in the actual root workspace."""

from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web
from textual.app import App, ComposeResult
from textual.widgets import Static

from kuberich.config.catalog import Entry
from kuberich.domain.connections import ConnectionState
from kuberich.domain.navigation import ContextRow
from kuberich.services.commands import Command
from kuberich.ui.contexts import ContextTable
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (60, 18), (100, 30), (180, 50)])
async def test_contexts_share_frame_filter_locally_return_and_connect_exact_row(
    tmp_path, size, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    calls = []

    async def ns(request):
        calls.append(request.path)
        return namespaces("team", "default")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("api")))

    async with workspace_api(ns, resources) as url:
        catalog = catalog_fixture(tmp_path, url)
        for i in range(40):
            catalog.contexts[f"Team-{i:02}"] = Entry(
                {"cluster": "owned", "user": "owned", "namespace": "team"}, tmp_path
            )
        before = (tmp_path / "fixture-config").read_bytes()
        app = make_app(catalog)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("slash", *"api", "enter")
            await pilot.pause()
            parent = app.resources.capture_viewport()
            frame = app.query_one("#resource-view").region
            count = len(calls)
            for alias in ("ctx", "context", "contexts"):
                await pilot.press("colon", *alias, "enter")
                await wait_for(lambda: app.context_table.row_count == 42)
                await pilot.pause()
                assert app._resource_name == "contexts" and len(app.screen_stack) == 1
                assert app.focused is app.context_table and app.filter_input.value == ""
                assert app.query_one("#resource-view").region == frame
                assert app.context_table.get_row("kuberich-test-one")[0].plain == "*"
                assert tuple(cell.plain for cell in app.context_table.get_row("Team-00")[1:]) == (
                    "Team-00",
                    "owned",
                    "owned",
                    "team",
                )
                await pilot.press("escape")
                await wait_for(
                    lambda: app._resource_name == "pods" and app.resources.row_count == 1
                )
                await pilot.pause()
                assert (
                    app.filter_input.value == "api" and app.resources.capture_viewport() == parent
                )
            await pilot.press("f2", "G", "k", "j", "g", "G")
            await pilot.pause()
            assert app.context_table.scroll_y > 0
            await pilot.press("slash", *"re:^", "enter")
            await wait_for(lambda: app.context_table.row_count == 42)
            await pilot.press("escape", "slash", *"Team-38", "enter")
            await wait_for(lambda: app.context_table.row_count == 1)
            assert "1/42 contexts" in str(app.status.content)
            assert len(calls) == count
            assert app.query_one("#resource-view").region == frame
            bar = app.query_one("#command-bar")
            assert bar.region.height == (1 if size[1] < 16 else 3)
            assert bar.styles.border_left[0] == "solid" and bar.styles.border_right[0] == "solid"
            if size[1] >= 16:
                assert (
                    bar.styles.border_top[0] == "solid" and bar.styles.border_bottom[0] == "solid"
                )
            out = Path("artifacts/ui").resolve()
            out.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"workspace-contexts-{size[0]}.svg", path=str(out))
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    app.resources.row_count == 1
                    and app.sessions.observation.state is ConnectionState.CONNECTED
                )
            )
            assert (
                app.sessions.observation.identity.context == "Team-38"
                and app._resource_name == "pods"
            )
            await pilot.press("alt+left")
            await wait_for(
                lambda: app._resource_name == "contexts" and app.context_table.row_count == 1
            )
            assert app.filter_input.value == "Team-38"
            await pilot.press("alt+right")
            await wait_for(lambda: app._resource_name == "pods" and app.resources.row_count == 1)
        assert app.sessions.client is None and (tmp_path / "fixture-config").read_bytes() == before


@pytest.mark.asyncio
async def test_initial_context_table_without_current_context_runs_no_authentication_and_esc_is_safe(
    tmp_path,
):
    catalog = replace(catalog_fixture(tmp_path, "http://127.0.0.1:1"), current=None)
    # No connection exists; the configured helper must not execute while browsing.
    marker = tmp_path / "never-created"
    catalog.users["owned"].data.clear()
    catalog.users["owned"].data["exec"] = {"command": str(marker)}
    catalog.contexts["[red]Context[/red]"] = Entry({"cluster": None, "user": None}, tmp_path)
    app = make_app(catalog, initial=Command.CONTEXTS)
    async with app.run_test() as pilot:
        await wait_for(lambda: app.context_table.row_count == 3)
        assert app.sessions.client is None and app._connection_task is None and not marker.exists()
        row = app.context_table.get_row("[red]Context[/red]")
        assert row[1].plain == "[red]Context[/red]" and not row[1].spans
        assert tuple(cell.plain for cell in row[2:]) == ("—", "—", "default")
        await pilot.press("d")
        assert "local configuration" in str(app.status.content)
        assert len(app.screen_stack) == 1
        await pilot.press("slash", *"absent", "enter")
        await wait_for(lambda: app.context_table.row_count == 0)
        assert "No contexts match" in str(app.query_one("#empty-title", Static).content)
        await pilot.press("enter", "escape")
        await wait_for(lambda: app.context_table.row_count == 3)
        await pilot.press("escape")
        assert app._resource_name == "pods"
        await pilot.press("c")
        await wait_for(lambda: app._resource_name == "contexts")
        await pilot.press("colon", *"ctx missing", "enter")
        await app._connection_task
        assert (
            app.sessions.observation.state is ConnectionState.CONFIG_ERROR
            and app._resource_name == "pods"
        )


class ContextTestApp(App):
    def compose(self) -> ComposeResult:
        yield ContextTable()


@pytest.mark.asyncio
async def test_context_table_batches_preserve_identity_and_reject_obsolete_updates():
    app = ContextTestApp()
    rows = tuple(ContextRow(f"ctx-{i:03}", "cluster", "user", "default") for i in range(300))
    async with app.run_test(size=(40, 12)) as pilot:
        table = app.query_one(ContextTable)
        table.setup()
        assert not await table.apply_rows(rows, lambda: False)
        assert await table.apply_rows(rows, lambda: True)
        table.move_cursor(row=250)
        await pilot.pause()
        viewport = table.capture_viewport()
        assert await table.apply_rows(
            (*rows[:250], replace(rows[250], current=True), *rows[251:]), lambda: True
        )
        await pilot.pause()
        assert table.capture_viewport() == viewport and table.get_row("ctx-250")[0].plain == "*"
        assert await table.apply_rows(rows[100:], lambda: True)
        await pilot.pause()
        assert table.capture_viewport().selected == "ctx-250"
        assert await table.apply_rows((), lambda: True)
        await pilot.pause()
        assert table.capture_viewport().selected is None
        calls = 0

        def expires():
            nonlocal calls
            calls += 1
            return calls < 3

        assert not await table.apply_rows(rows, expires) and table.row_count == 128
        assert not await table.apply_rows(rows[:128], expires)
        assert not await table.apply_rows(rows[:128], iter((True, False)).__next__)
        # Old restoration must not overwrite the subsequently selected row.
        table.restore_viewport(viewport)
        table.move_cursor(row=3)
        await pilot.pause()
        assert table.cursor_row == 3


@pytest.mark.asyncio
async def test_namespace_parent_and_context_retry_keep_filter_cursor_and_scope(tmp_path):
    async def ns(request):
        return namespaces("team", "default")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("api")))

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("n")
            await wait_for(lambda: app.namespace_table.row_count == 2)
            await pilot.press("slash", *"team", "enter", "c")
            await wait_for(lambda: app.context_table.row_count == 2)
            await pilot.press("slash", *"owned", "enter", "G")
            await pilot.pause()
            viewport = app.context_table.capture_viewport()
            identity = app.sessions.observation.identity
            await pilot.press("r")
            await app._connection_task
            await pilot.pause()
            assert app._resource_name == "contexts" and app.filter_input.value == "owned"
            assert app.context_table.capture_viewport() == viewport
            assert app.sessions.observation.identity.connection_id != identity.connection_id
            await pilot.press("escape", "escape")
            await wait_for(
                lambda: app._resource_name == "namespaces" and app.namespace_table.row_count == 1
            )
            assert (
                app.filter_input.value == "team"
                and app.namespace_table.selected_uid == "namespace-team"
            )
            await pilot.press("c")
            await wait_for(lambda: app.context_table.row_count == 2)
            assert app.filter_input.value == "" and app.focused is app.context_table
            await pilot.press("colon", *"po", "enter")
            await wait_for(lambda: app._resource_name == "pods" and app.resources.row_count == 1)
