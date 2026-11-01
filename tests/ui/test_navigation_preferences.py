"""Effective input ownership and persisted typed views through owned HTTP and Pilot."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Button, Static

from kuberich.cli import main
from kuberich.config.navigation import navigation_from
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import parse_document
from kuberich.config.store import read_config, write_config
from kuberich.domain.connections import ConnectionState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.resource_preferences import ColumnSpec, ViewSpec, printer_signature
from kuberich.domain.views import ViewStatus
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command, GenericResourceCommand, ResourceCommand
from kuberich.ui.app import HelpScreen, KubeRichApp
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.keybindings import shortcut_keys
from kuberich.ui.logs import LogHelpScreen, LogScreen
from kuberich.ui.views import ViewScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.custom import GROUP, custom_api
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.standard import standard_api
from tests.support.workers import CoroutineCalls
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_custom_resources import loaded as custom_loaded
from tests.ui.test_standard_resources import command
from tests.ui.test_standard_resources import loaded as standard_loaded


def app_for(directory, url=None, *, raw=None, initial=Command.EMPTY, readonly=True):
    path = directory / "preferences.yaml"
    if not path.exists():
        write_config(
            path, parse_document({"schema_version": 1, "opaque": "retained", **(raw or {})})
        )
    document = read_config(path)
    return KubeRichApp(
        replace(document.settings, read_only=readonly),
        logging.Logger("navigation-preferences", level=100),
        preferences=PreferenceSource(ConfigLocation(path, True), document),
        catalog=catalog_fixture(directory, url) if url else None,
        initial_command=initial,
    ), path


@asynccontextmanager
async def pods_api(count=30):
    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.startswith("/api/v1/namespaces/") and request.path.count("/") == 4:
            name = request.path.rsplit("/", 1)[1]
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": name,
                        "uid": "namespace-" + name,
                        "resourceVersion": "owned",
                    },
                }
            )
        values = [
            pod(
                f"pod-{i:03}",
                uid=f"uid-{i:03}",
                namespace=request.path.split("/namespaces/")[1].split("/")[0]
                if "/namespaces/" in request.path
                else "team",
                restarts=10 if i == 0 else 2 if i == 1 else 0,
            )
            for i in range(count)
        ]
        return web.json_response(collection(*values))

    async def ns(request):
        return namespaces("team", "other", "default")

    async with workspace_api(ns, resources) as url:
        yield url


async def pods_loaded(app, count=30):
    await wait_for(
        lambda: (
            app.workspace.store.observation.status is ViewStatus.LIVE
            and app.resources.row_count == count
        )
    )


async def editor(app, pilot):
    await command(app, pilot, "views")
    await wait_for(lambda: isinstance(app.screen, ViewScreen))
    await pilot.pause()
    return app.screen


async def apply_view(screen, pilot, columns, sort="name", descending=False, mode="session"):
    screen.columns_input.value = columns
    screen.sort_input.value = sort
    screen.reverse.value = descending
    screen.set_focus(screen.query_one("#view-" + mode, Button))
    saves = CoroutineCalls()
    screen.apply = saves.observe(screen.apply)
    await pilot.press("enter")
    # The button posts its message; observe the actual public apply callback.
    await pilot.pause()
    if saves.latest is not None:
        await wait_for(saves.latest.done)
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_effective_keys_aliases_help_and_literal_text_keep_native_fallbacks(tmp_path, size):
    raw = {
        "navigation": {
            "schema_version": 1,
            "keys": {
                "resources": {
                    "down": "b",
                    "first": "H",
                    "last": "K",
                    "sort": "u",
                    "reverse_sort": "U",
                }
            },
            "aliases": {"work": "pods", "local": "ctx"},
        }
    }
    async with pods_api() as url:
        app, path = app_for(tmp_path, url, raw=raw)
        original = path.read_bytes()
        async with app.run_test(size=size) as pilot:
            await pods_loaded(app)
            await pilot.pause()
            await pilot.press("K")
            assert app.resources.selected_uid == "uid-029"
            await pilot.press("g", "j")
            assert app.resources.selected_uid == "uid-029"
            await pilot.press("H", "b")
            assert app.resources.selected_uid == "uid-001"
            await pilot.press("ctrl+end", "ctrl+home")
            assert app.resources.selected_uid == "uid-000"
            await pilot.press("J")
            assert app.resources.cursor_row > 0
            await pilot.press("ctrl+u")
            assert app.resources.cursor_row == 0
            await pilot.press("u", "U")
            assert app.resources.descending and "u column" in app.resources.sort_summary
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpScreen)
            help_text = str(app.screen.query_one("#help-content", Static).content)
            assert "H" in help_text and "First row" in help_text and ":work → pods" in help_text
            await pilot.press("escape")
            for key in ("colon", "slash"):
                await pilot.press(key, *"jklngG:/bHu")
                field = app.command_input if key == "colon" else app.filter_input
                assert field.value == "jklngG:/bHu"
                await pilot.press("ctrl+d")
                assert len(app.screen_stack) == 1
                await pilot.press("escape")
                if field is app.filter_input:
                    await pilot.press("escape")
            assert app.command_input.provider("wor") == ("work",)
            assert "work other" in app.command_input.provider("work o")
            await command(app, pilot, "work other")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.scope.namespace == "other"
                    and app.resources.row_count == 30
                )
            )
            await pilot.press("ctrl+d")
            assert len(app.screen_stack) == 1 and "read-only" in str(app.status.content).casefold()
            assert path.read_bytes() == original
            await command(app, pilot, "local")
            await wait_for(lambda: app.state.view_kind == "contexts")
            app.action_views()
            assert len(app.screen_stack) == 1 and "Kubernetes resource" in str(app.status.content)
    assert shortcut_keys(
        (("j/k", "Rows"), ("g/G", "Ends"), ("s/x", "Shell")), app.navigation_keymap, "resources"
    ) == (("b/k", "Rows"), ("H/K", "Ends"), ("s/x", "Shell"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "navigation",
    [
        {"schema_version": 1, "keys": {"resources": {"right": "l"}}},
        {"schema_version": 1, "aliases": {"recursive": "recursive"}},
        {"schema_version": 8},
    ],
)
async def test_invalid_overrides_leave_working_navigation_and_file_intact(
    tmp_path, navigation, capsys
):
    async with pods_api() as url:
        app, path = app_for(tmp_path, url, raw={"navigation": navigation})
        original = path.read_bytes()
        async with app.run_test() as pilot:
            await pods_loaded(app)
            await pilot.press("G", "g", "j")
            assert app.resources.selected_uid == "uid-001"
            screen = await editor(app, pilot)
            assert screen.query_one("#view-global", Button).disabled
            await pilot.press("escape")
        assert path.read_bytes() == original
        assert main(["--config", str(path), "config", "check"]) != 0
        assert capsys.readouterr().err and path.read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_pod_columns_hidden_typed_sort_context_save_and_reopen(tmp_path, size):
    async with pods_api() as url:
        app, path = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await pods_loaded(app)
            app.resources.move_cursor(row=1)
            await pilot.pause()
            screen = await editor(app, pilot)
            await apply_view(screen, pilot, "name:18:center age:8", "restarts", True, "context")
            await wait_for(
                lambda: (
                    tuple(c.value for c in app.resources.columns) == ("name", "age")
                    and app.resources.row_count == 30
                )
            )
            assert app.resources.selected_uid == "uid-001"
            assert [row.key.value for row in app.resources.ordered_rows][:2] == [
                "uid-000",
                "uid-001",
            ]
            assert app.resources.columns["name"].width == 18
            assert app.resources.get_cell("uid-001", "name").__rich__().justify == "center"
            saved = read_config(path)
            choice = navigation_from(saved).choices("v1/pods", "kuberich-test-one")[0]
            assert choice.columns == (ColumnSpec("name", 18, "center"), ColumnSpec("age", 8))
            assert choice.sort == "restarts" and choice.descending and not saved.settings.read_only
            assert saved.unknown == {"opaque": "retained"}
            screen = await editor(app, pilot)
            await apply_view(screen, pilot, "name", mode="global")
            await wait_for(lambda: app.resources.row_count == 30)
            assert tuple(c.value for c in app.resources.columns) == ("name", "age")
            await command(app, pilot, "ctx kuberich-test-Two")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.context == "kuberich-test-Two"
                    and app.resources.row_count == 30
                )
            )
            assert tuple(c.value for c in app.resources.columns) == ("name",)
            await command(app, pilot, "po *")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.scope.namespace is None
                    and "namespace" in app.resources.columns
                )
            )
            assert tuple(c.value for c in app.resources.columns) == ("namespace", "name")
            output = Path("artifacts/ui").resolve()
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"navigation-view-{size[0]}.svg", path=str(output))
        reopened, _ = app_for(tmp_path, url)
        async with reopened.run_test() as pilot:
            await pods_loaded(reopened)
            assert tuple(c.value for c in reopened.resources.columns) == ("name", "age")
            assert reopened.resources.sort_column == "restarts" and reopened.resources.descending


@pytest.mark.asyncio
async def test_native_resource_preferences_and_namespace_sorting_are_resource_specific(tmp_path):
    raw = {
        "navigation": {
            "schema_version": 1,
            "views": {
                "apps/v1/deployments": {
                    "columns": [
                        {"key": "name"},
                        {"key": "ready", "alignment": "right", "width": 8},
                    ],
                    "sort": {"key": "desired", "descending": True},
                },
                "v1/namespaces": {
                    "columns": [{"key": "status"}, {"key": "name", "width": 20}],
                    "sort": {"key": "status"},
                },
            },
        }
    }
    async with standard_api(tmp_path) as (url, _):
        app, path = app_for(
            tmp_path, url, raw=raw, initial=ResourceCommand(RESOURCE_ALIASES["deploy"])
        )
        async with app.run_test() as pilot:
            await standard_loaded(app, "deployments")
            assert tuple(c.value for c in app.standard_table.columns) == ("name", "ready")
            assert app.standard_table.sort_column == "desired" and app.standard_table.descending
            screen = await editor(app, pilot)
            await apply_view(screen, pilot, "ready:9:center name:16", "ready", mode="global")
            await wait_for(
                lambda: (
                    tuple(c.value for c in app.standard_table.columns) == ("ready", "name")
                    and app.standard_table.row_count == 1
                )
            )
            assert (
                app.standard_table.get_cell("owned-owned-one", "ready").__rich__().justify
                == "center"
            )
            await command(app, pilot, "ns")
            await wait_for(lambda: app.namespace_table.row_count == 3)
            assert tuple(c.value for c in app.namespace_table.columns) == ("STATUS", "NAME")
            await pilot.press("s", "S")
            assert app.namespace_table.sort_column == "name" and app.namespace_table.descending
            screen = await editor(app, pilot)
            await apply_view(screen, pilot, "name:20 age:8", "age", mode="context")
            await wait_for(
                lambda: (
                    tuple(c.value for c in app.namespace_table.columns) == ("NAME", "AGE")
                    and app.namespace_table.row_count == 3
                )
            )
            assert (
                navigation_from(read_config(path))
                .choices("v1/namespaces", "kuberich-test-one")[0]
                .sort
                == "age"
            )


@pytest.mark.asyncio
async def test_unknown_native_fields_fall_back_without_rewriting_preferences(tmp_path, capsys):
    raw = {
        "navigation": {
            "schema_version": 1,
            "views": {"v1/pods": {"sort": {"key": "not-a-pod-field"}}},
        }
    }
    async with pods_api() as url:
        app, path = app_for(tmp_path, url, raw=raw)
        original = path.read_bytes()
        async with app.run_test() as pilot:
            await pods_loaded(app)
            assert app.resources.sort_column == "name"
            assert "unavailable" in str(app.status.content)
            await pilot.press("G")
            assert app.resources.selected_uid == "uid-029"
        assert path.read_bytes() == original
        assert main(["--config", str(path), "config", "check"]) != 0
        assert "unavailable" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_custom_persistence_hidden_typed_sort_and_schema_change_reject_stale_editor(tmp_path):
    async with custom_api() as (url, api):
        app, path = app_for(tmp_path, url, initial=GenericResourceCommand("widgets", GROUP))
        async with app.run_test() as pilot:
            await custom_loaded(app)
            screen = await editor(app, pilot)
            await apply_view(screen, pilot, "name:22 c3:8:center", "c2", mode="context")
            await wait_for(
                lambda: (
                    tuple(c.value for c in app.custom_table.columns) == ("name", "c3")
                    and app.custom_table.row_count == 3
                )
            )
            assert [r.key.value for r in app.custom_table.ordered_rows] == [
                "owned-two",
                "owned-ten",
                "owned-missing",
            ]
            saved = navigation_from(read_config(path)).choices(
                "server:" + GROUP + "/v1/widgets", "kuberich-test-one"
            )[0]
            assert saved.printer_signature == printer_signature(
                app.custom_table.resource_layout.headers
            )
            await pilot.press("slash", *"10", "enter")
            await wait_for(lambda: app.custom_table.row_count == 1)
            assert app.custom_table.selected_uid == "owned-ten"
            assert tuple(c.value for c in app.custom_table.columns) == ("name", "c3")
            await pilot.press("escape")
            await custom_loaded(app)
            screen = await editor(app, pilot)
            api.changed = True
            await api.update("/apis/" + GROUP + "/v1/namespaces/team/widgets", changed=True)
            await wait_for(
                lambda: (
                    app.workspace.store.observation.snapshot.columns
                    != app.custom_table.resource_layout.headers
                )
            )
            await apply_view(screen, pilot, "name c2", "c2", mode="global")
            assert app.screen is screen and "changed" in str(screen.feedback.content)
            await pilot.press("escape")
            await wait_for(
                lambda: (
                    app.custom_table.row_count == 3
                    and app.custom_table.resource_layout.headers
                    == app.workspace.store.observation.snapshot.columns
                )
            )
            assert "changed" in str(app.status.content) and app.custom_table.sort_column == "name"
            assert (
                navigation_from(read_config(path)).choices(
                    "server:" + GROUP + "/v1/widgets", "kuberich-test-one"
                )[0]
                == saved
            )


@pytest.mark.asyncio
async def test_cancel_validation_and_competing_file_failures_do_not_save_or_trap_focus(tmp_path):
    app, path = app_for(tmp_path)
    original = path.read_bytes()
    async with app.run_test(size=(40, 12)) as pilot:
        screen = await editor(app, pilot)
        await pilot.press("ctrl+a", "ctrl+k", *"name:24:center age:8")
        assert (
            screen.columns_input.value == "name:24:center age:8"
            and app.focused is screen.columns_input
        )
        await apply_view(screen, pilot, "age", "name")
        assert "name column" in str(screen.feedback.content)
        screen.columns_input.value = "name:24"
        screen.sort_input.value = "name"
        write_config(
            path, parse_document({"schema_version": 1, "opaque": "competing"}), overwrite=True
        )
        await apply_view(screen, pilot, "name:24", mode="global")
        await wait_for(lambda: "changed on disk" in str(screen.feedback.content))
        assert "changed on disk" in str(screen.feedback.content)
        await pilot.press("escape")
        assert len(app.screen_stack) == 1 and app.focused is app.resources
    assert path.read_bytes() != original


@pytest.mark.asyncio
async def test_owner_specific_remaps_keep_container_actions_and_log_input_copy_search(tmp_path):
    value = pod("api")
    value["spec"]["containers"] += [{"name": f"worker-{n:02}"} for n in range(20)]

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            return web.Response(
                text="\n".join(f"owned line {n:03} " + "x" * 150 for n in range(100))
            )
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async def ns(request):
        return namespaces("team")

    raw = {
        "navigation": {
            "schema_version": 1,
            "keys": {
                "resources": {"sort": "a"},
                "containers": {"first": "H", "last": "K"},
                "logs": {"first": "H", "last": "K"},
            },
        }
    }
    async with workspace_api(ns, resources) as url:
        app, path = app_for(tmp_path, url, raw=raw)
        async with app.run_test(size=(80, 24)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            assert isinstance(app.screen, ContainerScreen)
            container = app.screen
            await pilot.press("K")
            assert container.table.cursor_row == 20
            await pilot.press("H")
            assert container.table.cursor_row == 0
            await pilot.press("a")
            assert (
                app.screen is container and "read-only" in str(container.status.content).casefold()
            )
            await pilot.press("question_mark")
            assert "Navigation · containers" in app.screen.text and "s/x shell" in app.screen.text
            await pilot.press("escape", "l")
            await wait_for(
                lambda: isinstance(app.screen, LogScreen) and len(app.screen.body.rows) == 100
            )
            log = app.screen
            await pilot.press("H")
            assert log.body.scroll_y == 0
            await pilot.press("ctrl+d")
            assert log.body.scroll_y > 0 and app.screen is log
            await pilot.press("K")
            assert log.body.follow
            await pilot.press("question_mark")
            assert isinstance(app.screen, LogHelpScreen)
            assert "H" in str(app.screen.query_one("#help-scroll").children[0].content)
            await pilot.press("escape", "slash", *"jklngG:/HK")
            assert log.search.value == "jklngG:/HK" and app.screen is log
            await pilot.press("escape", "ctrl+y")
            assert "owned line" in app.clipboard
        assert path.exists()


@pytest.mark.asyncio
async def test_session_only_editor_and_explicit_save_guards_without_context_or_preference_source(
    tmp_path,
):
    app = KubeRichApp(
        parse_document({}).settings,
        logging.Logger("session-only", level=100),
        initial_command=Command.VIEWS,
    )
    async with app.run_test(size=(40, 12)) as pilot:
        await wait_for(lambda: isinstance(app.screen, ViewScreen))
        screen = app.screen
        assert app.state.connection is ConnectionState.DISCONNECTED
        assert screen.query_one("#view-global", Button).disabled
        with pytest.raises(AppError, match="Correct navigation"):
            await screen.apply(ViewSpec((ColumnSpec("name"),)), "global")
        await apply_view(screen, pilot, "name:18:right", mode="session")
        await wait_for(lambda: tuple(c.value for c in app.resources.columns) == ("name",))
        assert app.resources.visible_columns == (ColumnSpec("name", 18, "right"),)
        screen = await editor(app, pilot)
        screen.set_focus(screen.query_one("#view-back", Button))
        await pilot.press("enter")
        assert len(app.screen_stack) == 1
    app, path = app_for(tmp_path)
    async with app.run_test() as pilot:
        screen = await editor(app, pilot)
        assert screen.query_one("#view-context", Button).disabled
        with pytest.raises(AppError, match="Select a context"):
            await screen.apply(ViewSpec((ColumnSpec("name"),)), "context")
        await pilot.press("escape")
        await app.run_command("ctx")
        app.view_preferences.remember_sort()
    assert path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", [False, True])
async def test_requested_save_is_owned_across_duplicate_requests_escape_and_graceful_exit(
    tmp_path, monkeypatch, closing
):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    saves = CoroutineCalls()
    unmounting = asyncio.Event()
    original_unmount = ViewScreen.on_unmount

    async def observed_unmount(screen):
        unmounting.set()
        await original_unmount(screen)

    monkeypatch.setattr(ViewScreen, "on_unmount", observed_unmount)
    app, path = app_for(tmp_path)
    real_save = app.preferences.save_navigation

    async def held_save(navigation):
        saves.capture()
        calls.append(navigation)
        entered.set()
        await release.wait()
        await real_save(navigation)

    monkeypatch.setattr(app.preferences, "save_navigation", held_save)
    ready, exit_owner = asyncio.Event(), asyncio.Event()

    async def trial():
        async with app.run_test() as pilot:
            screen = await editor(app, pilot)
            screen.columns_input.value = "name:19"
            screen.sort_input.value = "name"
            button = screen.query_one("#view-global", Button)
            screen.set_focus(button)
            await pilot.press("enter")
            await asyncio.wait_for(entered.wait(), 5)
            await pilot.press("enter", "escape")
            assert app.screen is screen and "wait before closing" in str(screen.feedback.content)
            assert len(calls) == 1 and "navigation" not in read_config(path).extensions
            ready.set()
            await exit_owner.wait()

    owner = asyncio.create_task(trial())
    try:
        await asyncio.wait_for(ready.wait(), 5)
        if closing:
            exit_owner.set()
            await asyncio.wait_for(unmounting.wait(), 5)
            assert not owner.done() and not saves.latest.done()
        release.set()
        await wait_for(saves.latest.done)
        if not closing:
            await wait_for(lambda: len(app.screen_stack) == 1)
            exit_owner.set()
        await asyncio.wait_for(owner, 5)
    finally:
        release.set()
        exit_owner.set()
        await owner
    assert navigation_from(read_config(path)).choices("v1/pods", None)[0].columns == (
        ColumnSpec("name", 19),
    )


@pytest.mark.asyncio
async def test_session_layout_cache_is_bounded_across_real_resource_navigation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("kuberich.ui.views.MAX_HISTORY", 2)
    async with standard_api(tmp_path) as (url, _):
        app, _ = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            for name in ("deploy", "cm", "sec"):
                await command(app, pilot, name)
                await standard_loaded(app, RESOURCE_ALIASES[name].name)
                screen = await editor(app, pilot)
                await apply_view(screen, pilot, "name:19")
            # Both retained resource preferences survive navigation; the evicted
            # oldest preference returns to defaults through the real UI.
            for name in ("cm", "sec"):
                await command(app, pilot, name)
                await standard_loaded(app, RESOURCE_ALIASES[name].name)
                await pilot.pause()
                assert app.standard_table.view_spec.columns == (ColumnSpec("name", 19),)
            await command(app, pilot, "deploy")
            await standard_loaded(app, "deployments")
            await pilot.pause()
            assert app.standard_table.view_spec.columns != (ColumnSpec("name", 19),)
