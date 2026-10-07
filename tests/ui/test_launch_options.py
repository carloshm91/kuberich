"""Launch flags change visible widgets and preserve guards during input/resize."""

import logging
from datetime import timedelta
from pathlib import Path

import pytest

from kubetrol.config.schema import Settings
from kubetrol.services.commands import Command
from kubetrol.ui.app import HelpScreen, KubetrolApp
from kubetrol.ui.presentation import Presentation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "presentation,hidden",
    [
        (Presentation(headless=True), "app-header"),
        (Presentation(logoless=True), "brand"),
        (Presentation(crumbsless=True), "scope-bar"),
        (Presentation(True, True, True), "app-header"),
    ],
)
async def test_presentation_options_hide_the_requested_widgets_and_keep_controls(
    presentation: Presentation,
    hidden: str,
) -> None:
    app = KubetrolApp(
        Settings(read_only=True), logging.Logger("ui-launch"), presentation=presentation
    )
    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(f"#{hidden}").display
        assert app.resources.region.height > 0
        assert str(app.status.content).startswith("Read-only")
        screenshot = app.export_screenshot(title="Kubetrol launch presentation")
        if presentation.headless or presentation.logoless:
            assert app.query_one("#brand").region.height == 0
        if presentation.crumbsless:
            assert "Context:" not in screenshot and "Namespace:" not in screenshot
        output = Path(__file__).resolve().parents[2] / "artifacts/ui"
        output.mkdir(parents=True, exist_ok=True)
        identity = f"{int(presentation.headless)}{int(presentation.logoless)}{int(presentation.crumbsless)}"
        (output / f"launch-{identity}.svg").write_text(screenshot)
        await pilot.resize_terminal(100, 30)
        assert not app.query_one(f"#{hidden}").display
        await pilot.resize_terminal(40, 12)
        assert not app.query_one(f"#{hidden}").display
        assert app.command_input.region.bottom <= 12
        await pilot.press("colon")
        app.command_input.value = "shell"
        await pilot.press("enter")
        assert "Read-only mode blocks" in str(app.status.content)
        await pilot.press("slash", "x", "escape", "escape")
        assert str(app.status.content).startswith("Read-only")
        await pilot.press("q")
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_initial_help_opens_and_returns_to_the_real_workspace() -> None:
    app = KubetrolApp(Settings(), logging.Logger("ui-launch"), initial_command=Command.HELP)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        assert app.focused is app.resources and len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_initial_quit_exits_successfully() -> None:
    app = KubetrolApp(Settings(), logging.Logger("ui-launch"), initial_command=Command.QUIT)
    async with app.run_test():
        pass
    assert app.return_code == 0 and not app.is_running


@pytest.mark.asyncio
async def test_long_refresh_interval_keeps_watch_updates_immediate(tmp_path):
    import asyncio

    from aiohttp import web

    from tests.support.connections import catalog_fixture, namespaces
    from tests.support.pods import pod
    from tests.support.resources import collection
    from tests.support.watches import frame
    from tests.support.workspace import wait_for, workspace_api

    update = asyncio.Event()

    async def probe(request):
        return namespaces("team")

    async def resources(request):
        if "watch" not in request.query:
            return web.json_response(collection(pod("api", uid="api-uid")))
        response = web.StreamResponse()
        await response.prepare(request)
        await update.wait()
        changed = pod("api", uid="api-uid", restarts=7)
        changed["metadata"]["resourceVersion"] = "opaque/modified"
        await response.write(frame({"type": "MODIFIED", "object": changed}))
        while request.transport is not None and not request.transport.is_closing():
            await asyncio.sleep(0.01)
        return response

    async with workspace_api(probe, resources) as url:
        app = KubetrolApp(
            Settings(refresh_seconds=3600),
            logging.Logger("independent-watch"),
            catalog=catalog_fixture(tmp_path, url),
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            update.set()
            async with asyncio.timeout(2):
                await wait_for(lambda: str(app.resources.get_cell("api-uid", "restarts")) == "7")
            assert app.resources.selected_uid == "api-uid"
            await pilot.press("q")


@pytest.mark.asyncio
async def test_effective_identity_and_refresh_update_ages_without_polling_or_losing_focus(
    tmp_path, monkeypatch
):
    from aiohttp import web

    from kubetrol.domain.connection_overrides import ConnectionOverrides
    from kubetrol.domain.connections import ConnectionRequest
    from kubetrol.ui import pods
    from tests.support.connections import catalog_fixture, namespaces
    from tests.support.pods import NOW, pod
    from tests.support.resources import collection
    from tests.support.workspace import stable_watch, wait_for, workspace_api

    calls = []
    now = [NOW]
    monkeypatch.setattr(pods, "utc_now", lambda: now[0])

    async def probe(request):
        assert request.headers["Impersonate-User"] == "viewer"
        return namespaces("team")

    async def resources(request):
        calls.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            collection(pod("api", uid="api-uid", created=NOW - timedelta(seconds=5)))
        )

    async with workspace_api(probe, resources) as url:
        app = KubetrolApp(
            Settings(refresh_seconds=0.1),
            logging.Logger("override-preview"),
            catalog=catalog_fixture(tmp_path, url),
            connection=ConnectionRequest(
                overrides=ConnectionOverrides(cluster="owned", user="owned", as_user="viewer")
            ),
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.pause()
            assert app._header_identity()[1:3] == ("owned", "owned (as viewer)")
            count = len(calls)
            before = app.resources.get_row("api-uid")
            identity = app.sessions.observation.identity
            await pilot.press("slash", "a")
            now[0] += timedelta(minutes=2)
            await wait_for(lambda: app.resources.get_row("api-uid") != before)
            assert app.focused is app.filter_input and app.filter_input.value == "a"
            assert app.resources.selected_uid == "api-uid"
            assert len(calls) == count and app.sessions.observation.identity == identity
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename="connection-overrides-refresh.svg", path=str(evidence))
            await pilot.press("escape", "q")
        assert app.sessions.client is None and app._render_task.done()
