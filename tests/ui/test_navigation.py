"""Commands/completion/filter/history through the real UI and owned HTTP clients."""

import asyncio
import logging
import threading
from pathlib import Path

import pytest
from aiohttp import web
from textual.events import Paste
from textual.widgets import Static

from kubetrol.config.catalog import Entry
from kubetrol.config.schema import Settings
from kubetrol.domain.pods import PodColumn
from kubetrol.domain.views import ViewStatus
from kubetrol.services import filtering
from kubetrol.services.commands import Command, ScopedCommand
from kubetrol.ui.app import HelpScreen, KubetrolApp
from kubetrol.ui.commands import NavigationInput
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


def make_app(catalog=None, initial=Command.EMPTY):
    return KubetrolApp(
        Settings(read_only=True),
        logging.Logger("navigation", level=100),
        catalog=catalog,
        initial_command=initial,
    )


async def loaded(app, namespace="team"):
    await wait_for(
        lambda: (
            app.workspace.store.observation.status is ViewStatus.LIVE
            and app.workspace.store.observation.scope.namespace == namespace
            and app.resources.row_count == 4
        )
    )


def current_names(app):
    return [str(app.resources.get_cell(row.key, "name")) for row in app.resources.ordered_rows]


async def paste_command(app, pilot, value):
    await pilot.press("ctrl+a")
    app.command_input.post_message(Paste(value))
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_completion_commands_multiple_choices_tab_focus_and_literal_small_screen(size):
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await pilot.press("colon", "c")
        await pilot.pause()
        assert app.command_input.choices == ("context", "contexts", "ctx")
        assert app.completion.display
        assert "> context" in str(app.completion.content)
        assert app.completion.region.bottom <= app.filter_input.region.y
        await pilot.press("down", "down", "tab")
        assert app.command_input.value == "ctx" and app.focused is app.command_input
        assert not app.completion.display
        await pilot.press("enter")
        assert "No contexts found" in str(app.status.content)
        await pilot.press("colon", "p", "tab")
        assert app.command_input.value == "po"
        await pilot.press("escape")
        assert app.command_input.value == "" and app.focused is app.resources
        assert not app.completion.display
        await pilot.press("colon", "x", "tab")
        assert app.focused is app.resources  # no candidate: ordinary focus traversal
        await pilot.press("slash", "c", "n", "r", "q", "s", "colon", "slash")
        assert app.filter_input.value == "cnrqs:/" and app.is_running
        assert len(app.screen_stack) == 1 and not app.history.previous


@pytest.mark.asyncio
async def test_disconnected_namespace_candidates_are_absent_and_help_matches_actual_actions():
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        app.command_input.value = "ns "
        await pilot.pause()
        assert not app.command_input.choices and not app.completion.display
        await pilot.press("enter")
        assert "Connect to a context" in str(app.status.content)
        await pilot.press("alt+left")
        assert "No previous view" in str(app.status.content)
        await pilot.press("alt+right")
        assert "No next view" in str(app.status.content)
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        help_text = str(app.screen.query_one("#help-content", Static).content)
        for hint in ("Tab", "Up / Down", "Alt+Left", "re:PATTERN", "po/pod/pods"):
            assert hint in help_text


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_cached_scope_completions_filter_errors_and_history_restore_without_keystroke_io(
    tmp_path, size
):
    reads = []

    async def namespace_handler(request):
        reads.append(request.path)
        return namespaces("team", "team-blue", "team-green", "default")

    async def resources(request):
        reads.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        ns = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        return web.json_response(
            collection(
                *(
                    pod(name, namespace=ns, uid=ns + name, restarts=i)
                    for i, name in enumerate(["api", "api-worker", "payroll", "misc"])
                )
            )
        )

    async with workspace_api(namespace_handler, resources) as url:
        catalog = catalog_fixture(tmp_path, url)
        catalog.contexts["[red]Production[/red]"] = Entry(
            dict(catalog.contexts["kubetrol-test-one"].data), tmp_path
        )
        app = make_app(catalog)
        async with app.run_test(size=size) as pilot:
            await loaded(app)
            baseline = len(reads)
            await pilot.press("colon")
            await paste_command(app, pilot, "ctx [")
            assert app.command_input.choices == ("ctx [red]Production[/red]",)
            assert "[red]Production[/red]" in str(app.completion.content)
            assert app.completion.content.spans == []
            await pilot.press("escape", "colon")
            await paste_command(app, pilot, "ns t")
            assert app.command_input.choices == ("ns team", "ns team-blue", "ns team-green")
            await pilot.press("down", "tab")
            assert app.command_input.value == "ns team-blue"
            assert len(reads) == baseline
            await pilot.press("escape", "slash", "a", "p", "i", "enter")
            await wait_for(lambda: app.resources.row_count == 2)
            assert current_names(app) == ["api", "api-worker"]
            await pilot.press("s", "S", "down")
            await pilot.pause()
            selected = app.resources.selected_uid
            viewport = app.resources.capture_viewport()
            await pilot.press("colon")
            app.command_input.value = "ns team-blue"
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.workspace.store.observation.scope.namespace == "team-blue"
                    and app.resources.row_count == 2
                )
            )
            await pilot.press("escape", "slash")
            app.filter_input.value = "payroll"
            await pilot.press("enter")
            await wait_for(lambda: current_names(app) == ["payroll"])
            await pilot.press("alt+left")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.scope is not None
                    and app.workspace.store.observation.scope.namespace == "team"
                    and app.resources.selected_uid == selected
                )
            )
            await pilot.pause()
            assert app.filter_input.value == "api"
            assert app.resources.sort_column is PodColumn.READY and app.resources.descending
            assert app.resources.scroll_x == viewport.x
            assert app.resources.scroll_y == viewport.y
            await pilot.press("alt+right")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.scope is not None
                    and app.workspace.store.observation.scope.namespace == "team-blue"
                    and current_names(app) == ["payroll"]
                )
            )
            assert app.filter_input.value == "payroll"
            await pilot.press("slash")
            app.filter_input.value = "re:["
            await wait_for(lambda: "Invalid regex" in str(app.status.content))
            assert app.resources.row_count == 4
            app.filter_input.value = "re:^(?!.*api)"
            await wait_for(lambda: current_names(app) == ["misc", "payroll"])
            app.filter_input.value = "does-not-match"
            await wait_for(
                lambda: app.resources.row_count == 0 and "0/4 pods" in str(app.status.content)
            )
            assert "No pods match" in str(app.query_one("#empty-title", Static).content)
            await pilot.press("escape", "escape")
            await loaded(app, "team-blue")
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            await pilot.press("colon")
            await paste_command(app, pilot, "ns t")
            app.save_screenshot(filename=f"command-suggestions-{size[0]}.svg", path=str(evidence))
        assert app._view_task.done() and app._render_task.done() and app.sessions.client is None


@pytest.mark.asyncio
async def test_namespace_suggestions_are_invalidated_before_a_new_context_can_authenticate(
    tmp_path,
):
    release = asyncio.Event()
    calls = []

    async def namespace_handler(request):
        calls.append(request.path)
        if len(calls) > 1:
            await release.wait()
        return namespaces("team", "old-only")

    async with workspace_api(namespace_handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.press("colon")
            app.command_input.value = "ns old"
            await pilot.pause()
            assert app.command_input.choices == ("ns old-only",)
            app._start_connection("kubetrol-test-Two")
            await pilot.pause()
            assert not app.command_input.choices and not app.completion.display
            await pilot.press("tab")
            assert app.command_input.value == "ns old" and app.focused is app.resources
            release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial",
    [
        ScopedCommand(Command.NAMESPACES, "default"),
        ScopedCommand(Command.PODS, "*"),
        ScopedCommand(Command.CONTEXTS, "kubetrol-test-Two"),
    ],
)
async def test_scoped_initial_commands_connect_once_directly_to_the_requested_scope(
    tmp_path, initial
):
    namespace_calls, scopes = [], []

    async def namespace_handler(request):
        namespace_calls.append(request.path)
        return namespaces("team", "default")

    async def resources(request):
        scopes.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection())

    async with workspace_api(namespace_handler, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url), initial)
        async with app.run_test():
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            assert len(namespace_calls) == 1
            wanted = (
                "default"
                if initial.command is Command.NAMESPACES
                else None
                if initial.command is Command.PODS
                else "default"
            )
            assert app.workspace.store.observation.scope.namespace == wanted
            assert app.workspace.store.observation.context == (
                initial.argument if initial.command is Command.CONTEXTS else "kubetrol-test-one"
            )
            if wanted is None:
                assert all("/namespaces/" not in path for path in scopes)


@pytest.mark.asyncio
async def test_delayed_filter_cannot_repopulate_an_old_scope_and_latest_query_wins(
    tmp_path, monkeypatch
):
    started, release, ended = (threading.Event() for _ in range(3))
    original = filtering.filter_rows

    def controlled(rows, query):
        if query == "blocked":
            started.set()
            try:
                assert release.wait(5)
                return filtering.FilterResult(rows[:1])
            finally:
                ended.set()
        return original(rows, query)

    monkeypatch.setattr(filtering, "filter_rows", controlled)

    async def namespace_handler(request):
        return namespaces("team", "default")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        ns = request.path.split("/")[4]
        return web.json_response(
            collection(
                *(
                    pod(name, namespace=ns, uid=ns + name)
                    for name in ["api", "api-worker", "payroll", "misc"]
                )
            )
        )

    async with workspace_api(namespace_handler, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await loaded(app)
            app.filter_input.value = "blocked"
            await wait_for(started.is_set)
            try:
                await pilot.press("colon")
                app.command_input.value = "ns default"
                await pilot.press("enter")
                assert app.resources.row_count == 0
                app.filter_input.value = "api"
                await wait_for(
                    lambda: (
                        app.workspace.store.observation.status is ViewStatus.LIVE
                        and app.workspace.store.observation.scope.namespace == "default"
                    )
                )
                assert not ended.is_set() and app.resources.row_count == 0
            finally:
                release.set()
            await wait_for(lambda: app.resources.row_count == 2)
            assert current_names(app) == ["api", "api-worker"]
            assert all(row.namespace == "default" for row in app.resources._rows.values())
        assert ended.is_set() and app._render_task.done()


@pytest.mark.asyncio
async def test_exit_drains_the_filter_thread_and_closes_the_current_client(tmp_path, monkeypatch):
    started, release, ended = (threading.Event() for _ in range(3))

    def controlled(rows, query):
        started.set()
        try:
            assert release.wait(5)
            return filtering.FilterResult(rows)
        finally:
            ended.set()

    monkeypatch.setattr(filtering, "filter_rows", controlled)

    async def namespace_handler(request):
        return namespaces("team")

    async with workspace_api(namespace_handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))

        async def release_after_cancellation():
            try:
                await wait_for(lambda: app._render_task.cancelling() > 0)
                assert not app._render_task.done() and not ended.is_set()
            finally:
                release.set()

        monitor = None
        try:
            async with app.run_test():
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
                app.filter_input.value = "blocked"
                await wait_for(started.is_set)
                monitor = asyncio.create_task(release_after_cancellation())
                app.exit()
        finally:
            release.set()
            if monitor is not None:
                await monitor
        assert ended.is_set() and app._render_task.done() and app.sessions.client is None


@pytest.mark.asyncio
async def test_input_failure_releases_the_key_barrier_and_does_not_hang_exit():
    class BrokenInput(NavigationInput):
        def on_key(self, event):
            raise RuntimeError("owned-key-handler-failure")

    app = make_app()
    app.filter_input = BrokenInput(
        lambda: app.set_focus(app.resources), placeholder="Filter", id="filter"
    )
    async with asyncio.timeout(5):
        with pytest.raises(RuntimeError, match="owned-key-handler-failure"):
            async with app.run_test() as pilot:
                await pilot.press("slash", "x")
    assert app._input_completion is None and app.return_code == 1


@pytest.mark.asyncio
async def test_narrow_completions_keep_selected_choice_visible_and_cursor_edits_hide_them():
    app = make_app()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.press("colon", *(["down"] * 7))
        assert app.command_input.selected == 7
        selected = app.command_input.choices[7]
        assert "> " + selected in str(app.completion.content)
        assert app.completion.region.bottom <= app.filter_input.region.y
        await pilot.press("tab")
        assert app.command_input.value == selected
        await pilot.press("escape", "colon", "c", "left")
        assert not app.completion.display
        await pilot.press("right")
        assert app.completion.display
        await pilot.press("up", "tab")
        assert app.command_input.value == "ctx"


@pytest.mark.asyncio
async def test_limited_namespace_listing_suggests_only_known_current_scope_and_all(tmp_path):
    async def namespace_handler(request):
        return web.Response(status=403)

    async with workspace_api(namespace_handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            assert app._namespace_choices() == ("*", "team")
            app._namespace_selected("*")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.workspace.store.observation.scope.namespace is None
                )
            )
            assert app._namespace_choices() == ("*",)
            await pilot.press("colon")
            await paste_command(app, pilot, "ns def")
            assert not app.command_input.choices


@pytest.mark.asyncio
async def test_history_returns_from_a_failed_context_and_new_navigation_discards_forward(tmp_path):
    async def namespace_handler(request):
        return namespaces("team", "default")

    async with workspace_api(namespace_handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.press("colon")
            await paste_command(app, pilot, "ctx missing-context")
            await pilot.press("enter")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
            await pilot.press("alt+left")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            assert app.workspace.store.observation.context == "kubetrol-test-one"
            assert app.history.following
            await pilot.press("colon")
            await paste_command(app, pilot, "ns default")
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.workspace.store.observation.scope.namespace == "default"
                )
            )
            assert not app.history.following
