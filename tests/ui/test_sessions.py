"""Pilot drives actual context/namespace selectors against owned fake APIs."""

import asyncio
import logging
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import OptionList, Static

from kubetrol.config.catalog import Entry
from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.domain.views import ViewStatus
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.scopes import ConnectionScreen, ScopeScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.workspace import wait_for
from tests.support.workspace import workspace_api as fake_api


async def connected(app: KubetrolApp) -> None:
    async with asyncio.timeout(3):
        while app.sessions.observation.state is not ConnectionState.CONNECTED:
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_select_context_namespace_scroll_and_retry_without_rewriting_file(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    async def handler(request):
        return namespaces("default", "team", *(f"team-{i}" for i in range(50)))

    async with fake_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url)
        before = (tmp_path / "fixture-config").read_bytes()
        app = KubetrolApp(Settings(read_only=True), logging.Logger("contexts"), catalog=catalog)
        async with app.run_test(size=size) as pilot:
            await connected(app)
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert "Resource data ready" in str(app.query_one("#empty-title", Static).content)
            assert "Read-only" in str(app.status.content) and "Insecure transport" in str(
                app.status.content
            )
            assert app.resources.row_count == 0
            old = app.sessions.observation.identity
            await pilot.press("f2")
            assert isinstance(app.screen, ScopeScreen)
            await pilot.press("f2", "f1")
            assert len(app.screen_stack) == 2
            assert await pilot.click("#scope-close")
            await pilot.press("f2")
            options = app.screen.query_one("#scope-options", OptionList)
            options.highlighted = catalog.names.index("kubetrol-test-Two")
            await pilot.press("enter")
            await connected(app)
            assert app.sessions.observation.identity.context == "kubetrol-test-Two"
            assert app.sessions.observation.identity.connection_id != old.connection_id
            await pilot.press("f3", "f3", "pagedown")
            assert len(app.screen_stack) == 2
            await pilot.pause()
            options = app.screen.query_one("#scope-options", OptionList)
            assert options.scroll_y > 0
            options.highlighted = 0
            await pilot.press("enter")
            assert app.sessions.observation.namespace is None
            assert str(app.query_one("#namespace", Static).content) == "Namespace: All"
            await pilot.press("f4")
            await connected(app)
            assert app.sessions.observation.namespace is None
            await pilot.press("slash", "a", "escape", "escape")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert "Live" in str(app.status.content)
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"context-sessions-{size[0]}.svg", path=str(evidence))
            await pilot.press("q")
        assert app.sessions.client is None
        assert (tmp_path / "fixture-config").read_bytes() == before


@pytest.mark.asyncio
async def test_case_preserved_commands_and_manual_namespace_for_restricted_rbac(
    tmp_path: Path,
) -> None:
    async def handler(request):
        return web.Response(status=403)

    async with fake_api(handler) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("limited"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test() as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.LIMITED
            await pilot.press("colon")
            app.command_input.value = "ctx kubetrol-test-Two"
            await pilot.press("enter")
            await app._connection_task
            assert app.sessions.observation.identity.context == "kubetrol-test-Two"
            await pilot.press("colon")
            app.command_input.value = "ns allowed"
            await pilot.press("enter")
            assert app.sessions.observation.namespace == "allowed"
            await pilot.press("colon")
            app.command_input.value = "ns INVALID"
            await pilot.press("enter")
            assert "DNS label" in str(app.status.content)
            assert app.sessions.observation.namespace == "allowed"
            await pilot.press("colon")
            app.command_input.value = "ns"
            await pilot.press("enter")
            assert isinstance(app.screen, ScopeScreen)
            await pilot.press("escape")
            await pilot.press("colon")
            app.command_input.value = "ctx"
            await pilot.press("enter")
            assert isinstance(app.screen, ScopeScreen)
            await pilot.press("escape", "q")


@pytest.mark.asyncio
async def test_delayed_probe_does_not_block_input_context_switch_or_quit(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.sleep(1)
        return namespaces("default")

    async with fake_api(handler) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("slow"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test() as pilot:
            await started.wait()
            old = app.sessions.client.api
            await pilot.press("slash", "a", "f3")
            assert app.filter_input.value == "a"
            assert "Connect to a context" in str(app.status.content)
            await pilot.press("escape", "f2", "enter")
            # The previous request is cancelled/awaited before opening the new client.
            async with asyncio.timeout(2):
                while not old.rest_client.pool_manager.closed:
                    await asyncio.sleep(0.01)
            await pilot.press("ctrl+q")
        assert app.sessions.client is None
        assert app._connection_task.done()


@pytest.mark.asyncio
async def test_no_config_context_namespace_retry_and_cancel_are_actionable() -> None:
    app = KubetrolApp(Settings(), logging.Logger("empty"))
    async with app.run_test() as pilot:
        await pilot.press("f2")
        assert "No contexts" in str(app.status.content)
        await pilot.press("f3")
        assert "Connect to a context" in str(app.status.content)
        await pilot.press("f4")
        assert "No contexts" in str(app.status.content)
        app._context_selected(None)
        app._namespace_selected(None)
        app._namespace_selected("default")
        assert "Connect to a context" in str(app.status.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_navigation_without_function_keys_and_recovery_from_auth_failure(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    async def handler(request):
        if request.headers.get("Authorization") == "Bearer rejected":
            return web.Response(status=401, text="opaque-secret")
        assert request.headers["Authorization"] == "Bearer synthetic"
        return namespaces("default", "team")

    async with fake_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url)
        catalog.users["rejected"] = Entry({"token": "rejected"}, tmp_path)
        catalog.contexts["kubetrol-test-one"].data["user"] = "rejected"
        app = KubetrolApp(Settings(), logging.Logger("navigation"), catalog=catalog)
        async with app.run_test(size=size) as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.AUTH_ERROR
            await pilot.press("colon", *"status", "enter")
            assert isinstance(app.screen, ConnectionScreen)
            assert "401" in str(app.screen.query_one("#connection-details", Static).content)
            await pilot.press("escape", "c", "c", "n", "i")
            assert isinstance(app.screen, ScopeScreen) and len(app.screen_stack) == 2
            options = app.screen.query_one("#scope-options", OptionList)
            options.highlighted = catalog.names.index("kubetrol-test-Two")
            await pilot.press("enter")
            await connected(app)
            await pilot.pause()
            assert str(app.query_one("#connection", Static).content) == "Connected"
            assert "401" not in str(app.status.content)
            assert str(app.query_one("#context", Static).content) == "Context: kubetrol-test-Two"
            await pilot.press("n", "n")
            assert isinstance(app.screen, ScopeScreen) and len(app.screen_stack) == 2
            options = app.screen.query_one("#scope-options", OptionList)
            options.highlighted = app.screen.values.index("team")
            await pilot.press("enter")
            assert app.sessions.observation.namespace == "team"
            identity = app.sessions.observation.identity
            await pilot.press("r")
            await app._connection_task
            assert app.sessions.observation.identity.connection_id != identity.connection_id
            assert app.sessions.observation.namespace == "team"
            await pilot.press("i", "escape", "colon", *"retry", "enter")
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.CONNECTED
            await pilot.press("slash", *"cnri")
            assert app.filter_input.value == "cnri" and len(app.screen_stack) == 1
            await pilot.press("escape", "colon", *"cnri")
            assert app.command_input.value == "cnri" and len(app.screen_stack) == 1
            await pilot.press("escape", "colon", *"ns", "enter")
            assert isinstance(app.screen, ScopeScreen)
            await pilot.press("escape", "colon", *"status unexpected", "enter")
            assert len(app.screen_stack) == 1
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"context-navigation-{size[0]}.svg", path=str(evidence))
            await pilot.press("q")
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_explicit_unknown_context_error_then_choose_valid_context(tmp_path: Path) -> None:
    async def handler(request):
        return namespaces("default")

    async with fake_api(handler) as url:
        app = KubetrolApp(
            Settings(),
            logging.Logger("invalid"),
            catalog=catalog_fixture(tmp_path, url),
            connection=ConnectionRequest(context="missing"),
        )
        async with app.run_test() as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.CONFIG_ERROR
            assert str(app.query_one("#empty-title", Static).content) == "Connection unavailable"
            await pilot.press("f2", "enter")
            await connected(app)
            await pilot.press("q")


@pytest.mark.asyncio
async def test_full_connection_message_is_accessible_and_literal_at_minimum_size(
    tmp_path: Path,
) -> None:
    from kubetrol.ui.scopes import ConnectionScreen

    async def handler(request):
        return web.Response(status=401, text="opaque-secret")

    async with fake_api(handler) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("error-details"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test(size=(40, 12)) as pilot:
            await app._connection_task
            await pilot.press("f5")
            assert isinstance(app.screen, ConnectionScreen)
            assert (
                app.screen.query_one("#connection-details", Static).content.plain
                == app.sessions.observation.message
            )
            assert "Complete provider login" in app.sessions.observation.message
            await pilot.press("f5")
            assert len(app.screen_stack) == 2
            assert await pilot.click("#connection-close")
            assert len(app.screen_stack) == 1
            app._start_connection("bad\ncontext")
            assert "unsupported control" in str(app.status.content)
            assert app.is_running
            await pilot.press("q")


@pytest.mark.asyncio
async def test_late_result_from_a_cancelled_adapter_cannot_update_new_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kubetrol.domain.connections import SessionObservation
    from kubetrol.domain.targets import SessionIdentity

    started = asyncio.Event()

    async def ignores_cancellation(context):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return SessionObservation(
                ConnectionState.CONNECTED, "Stale result", SessionIdentity(context, 1), "default"
            )

    app = KubetrolApp(Settings(), logging.Logger("late"))
    monkeypatch.setattr(app.sessions, "connect", ignores_cancellation)
    async with app.run_test() as pilot:
        app._start_connection("old")
        await started.wait()
        app._start_connection("new")
        await pilot.pause()
        assert "Stale result" not in str(app.status.content)
        assert str(app.query_one("#context", Static).content) == "Context: new"
        await pilot.press("ctrl+q")


@pytest.mark.asyncio
async def test_background_failure_preserves_error_hook_and_hides_exception_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(context):
        raise RuntimeError("opaque-sensitive-background-value")

    app = KubetrolApp(Settings(), logging.Logger("broken"))
    monkeypatch.setattr(app.sessions, "connect", broken)
    with pytest.raises(RuntimeError, match="opaque-sensitive-background-value"):
        async with app.run_test() as pilot:
            app._start_connection("owned")
            await pilot.pause()
    assert app.return_code == 1 and app.sessions.client is None
