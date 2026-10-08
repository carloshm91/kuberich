"""Pilot drives actual context/namespace selectors against owned fake APIs."""

import asyncio
import logging
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Static

from kuberich.config.catalog import Entry
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest, ConnectionState
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from kuberich.ui.scopes import ConnectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.workspace import wait_for
from tests.support.workspace import workspace_api as fake_api


async def connected(app: KubeRichApp) -> None:
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
        app = KubeRichApp(Settings(read_only=True), logging.Logger("contexts"), catalog=catalog)
        async with app.run_test(size=size) as pilot:
            await connected(app)
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert "No pods in this scope" in str(app.query_one("#empty-title", Static).content)
            assert "Read-only" in str(app.status.content) and "Insecure transport" in str(
                app.status.content
            )
            assert app.resources.row_count == 0
            old = app.sessions.observation.identity
            await pilot.press("f2")
            await wait_for(lambda: app.context_table.row_count == 2)
            assert app._resource_name == "contexts" and len(app.screen_stack) == 1
            await pilot.press("f2", "f1")
            assert len(app.screen_stack) == 2
            assert await pilot.click("#close-help")
            await pilot.press("f2")
            app.context_table.move_cursor(row=app.context_table.get_row_index("kuberich-test-Two"))
            await pilot.press("enter")
            await connected(app)
            assert app.sessions.observation.identity.context == "kuberich-test-Two"
            assert app.sessions.observation.identity.connection_id != old.connection_id
            await pilot.press("f3", "f3", "pagedown")
            assert len(app.screen_stack) == 1
            await wait_for(lambda: app.namespace_table.row_count == 52)
            await pilot.press("pagedown")
            await pilot.pause()
            assert app.namespace_table.scroll_y > 0
            await pilot.press("0")
            await app._connection_task
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
        app = KubeRichApp(
            Settings(), logging.Logger("limited"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test() as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.LIMITED
            await pilot.press("colon")
            app.command_input.value = "ctx kuberich-test-Two"
            await pilot.press("enter")
            await app._connection_task
            assert app.sessions.observation.identity.context == "kuberich-test-Two"
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
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
            assert app._resource_name == "namespaces" and len(app.screen_stack) == 1
            assert "403" in str(app.status.content)
            await pilot.press("escape")
            await pilot.press("colon")
            app.command_input.value = "ctx"
            await pilot.press("enter")
            assert app._resource_name == "contexts" and len(app.screen_stack) == 1
            await pilot.press("escape", "q")


@pytest.mark.asyncio
async def test_delayed_probe_does_not_block_input_context_switch_or_quit(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.sleep(1)
        return namespaces("default")

    async with fake_api(handler) as url:
        app = KubeRichApp(
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
    app = KubeRichApp(Settings(), logging.Logger("empty"))
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
        catalog.contexts["kuberich-test-one"].data["user"] = "rejected"
        app = KubeRichApp(Settings(), logging.Logger("navigation"), catalog=catalog)
        async with app.run_test(size=size) as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.AUTH_ERROR
            await pilot.press("colon", *"status", "enter")
            assert isinstance(app.screen, ConnectionScreen)
            assert "401" in str(app.screen.query_one("#connection-details", Static).content)
            await pilot.press("escape", "c", "c")
            await wait_for(lambda: app.context_table.row_count == 2)
            assert app._resource_name == "contexts" and len(app.screen_stack) == 1
            app.context_table.move_cursor(row=app.context_table.get_row_index("kuberich-test-Two"))
            await pilot.press("enter")
            await connected(app)
            await pilot.pause()
            assert str(app.query_one("#connection", Static).content) == "State: Connected"
            assert "401" not in str(app.status.content)
            assert str(app.query_one("#context", Static).content) == "Context: kuberich-test-Two"
            await pilot.press("n", "n")
            assert len(app.screen_stack) == 1
            await wait_for(lambda: app.namespace_table.row_count == 2)
            app.namespace_table.move_cursor(row=app.namespace_table.get_row_index("namespace-team"))
            await pilot.press("enter")
            await app._connection_task
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
            assert app._resource_name == "namespaces" and len(app.screen_stack) == 1
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
        app = KubeRichApp(
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
    from kuberich.ui.scopes import ConnectionScreen

    async def handler(request):
        return web.Response(status=401, text="opaque-secret")

    async with fake_api(handler) as url:
        app = KubeRichApp(
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
    from kuberich.domain.connections import SessionObservation
    from kuberich.domain.targets import SessionIdentity

    started = asyncio.Event()

    async def ignores_cancellation(context):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return SessionObservation(
                ConnectionState.CONNECTED, "Stale result", SessionIdentity(context, 1), "default"
            )

    app = KubeRichApp(Settings(), logging.Logger("late"))
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

    app = KubeRichApp(Settings(), logging.Logger("broken"))
    monkeypatch.setattr(app.sessions, "connect", broken)
    with pytest.raises(RuntimeError, match="opaque-sensitive-background-value"):
        async with app.run_test() as pilot:
            app._start_connection("owned")
            await pilot.pause()
    assert app.return_code == 1 and app.sessions.client is None
