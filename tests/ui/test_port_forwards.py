"""Real owned API/processes with responsive forward controls and context cleanup."""

import asyncio
import logging
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Static

from kuberich.config.schema import Settings
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.port_forwards import ForwardPrompt, ForwardScreen
from tests.support.connections import catalog_fixture
from tests.support.port_forwards import executable
from tests.support.standard import standard_api
from tests.support.workspace import wait_for


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_start_filter_stop_return_and_context_cleanup_keep_listener_ownership(tmp_path, size):
    async with standard_api(tmp_path) as (url, _reads):
        app = KubeRichApp(
            Settings(),
            logging.getLogger("owned-forward-ui"),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=ResourceCommand(RESOURCE_ALIASES["svc"], "team"),
        )
        app._process_environment = executable(tmp_path)
        app._process_directory = tmp_path
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.pause()
            before = app.standard_table.capture_viewport()
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardPrompt))
            app.screen.query_one("#forward-mappings", Input).value = "bad mapping"
            await pilot.press("enter")
            assert isinstance(app.screen, ForwardPrompt) and not app.forwards.infos
            assert "local:remote" in str(app.screen.query_one("#forward-feedback", Static).content)
            app.screen.query_one("#forward-mappings", Input).value = ":80"
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, ForwardScreen))
            await wait_for(
                lambda: (
                    bool(app.forwards.infos) and app.forwards.infos[0].state is ForwardState.READY
                )
            )
            screen = app.screen
            screen.refresh_sessions()
            ready = app.forwards.infos[0]
            assert (
                screen.table.row_count == 1
                and screen._shown[str(ready.identity)].target.namespace == "team"
            )
            assert not screen.query_one("#forward-list-stop", Button).disabled
            await pilot.pause()
            if size == (40, 12):
                assert screen.table.region.height >= 3
                assert "kuberich-test-one" in screen.table.render_line(1).text
            screen.action_filter()
            await pilot.press(*"missing")
            await wait_for(lambda: screen.table.row_count == 0)
            screen.query_one("#forward-list-filter", Input).value = ""
            await pilot.press("enter")
            await wait_for(lambda: screen.table.row_count == 1)
            await pilot.press("escape")
            assert len(app.screen_stack) == 1 and app.standard_table.capture_viewport() == before
            app._namespace_selected("other")
            await wait_for(lambda: app.sessions.observation.namespace == "other")
            await asyncio.sleep(0.05)
            assert app.forwards.infos[0].state is ForwardState.READY
            app.action_port_forwards()
            await wait_for(lambda: isinstance(app.screen, ForwardScreen))
            await pilot.press("s")
            await wait_for(lambda: app.forwards.infos[0].state is ForwardState.STOPPED)
            assert not app.forwards.active_count
            await pilot.press("escape")
            app._select_resource("services")
            await wait_for(
                lambda: app.standard_table.row_count == 1 and app._resource_name == "services"
            )
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardPrompt))
            app.screen.query_one("#forward-mappings", Input).value = ":80"
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    len(app.forwards.infos) == 2
                    and app.forwards.infos[-1].state is ForwardState.READY
                )
            )
            await pilot.press("escape")
            old = app.sessions.client
            app.action_retry()
            await wait_for(
                lambda: app.sessions.client is not None and app.sessions.client is not old
            )
            await wait_for(lambda: app.forwards.infos[-1].state is ForwardState.STOPPED)
            assert app.forwards.infos[-1].message == "Stopped for connection change."
            assert not Path(old.directory.name).exists()
            assert app.forwards.active_count == 0
        assert app.sessions.client is None and app.processes.active_count == 0


@pytest.mark.asyncio
async def test_readonly_listing_and_input_routing_are_safe(tmp_path):
    app = KubeRichApp(
        Settings(read_only=True),
        logging.getLogger("owned-forward-readonly"),
        catalog=catalog_fixture(tmp_path, "http://127.0.0.1:1"),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_port_forward()
        assert "Read-only" in str(app.status.content) and not app.forwards.infos
        app.action_port_forwards()
        await wait_for(lambda: isinstance(app.screen, ForwardScreen))
        assert app.screen.table.row_count == 0
        await pilot.press("s")
        assert not app.forwards.infos
        app.screen.action_filter()
        await pilot.press("s")
        assert app.screen.query_one("#forward-list-filter", Input).value == "s"
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
        app._display_resource("deployments")
        assert app.check_action("port_forward", ()) is False


@pytest.mark.asyncio
async def test_cancel_stale_selection_and_non_loopback_intent_do_not_start_work(tmp_path):
    async with standard_api(tmp_path) as (url, _reads):
        app = KubeRichApp(
            Settings(),
            logging.getLogger("owned-forward-intent"),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=ResourceCommand(RESOURCE_ALIASES["svc"], "team"),
        )
        app._process_environment = executable(tmp_path)
        app._process_directory = tmp_path
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardPrompt))
            app.screen.query_one("#forward-address", Input).value = "0.0.0.0"
            await pilot.press("enter")
            assert "explicit permission" in str(
                app.screen.query_one("#forward-feedback", Static).content
            )
            assert not app.forwards.infos
            app.screen.cancel()
            await pilot.pause()
            assert len(app.screen_stack) == 1
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardPrompt))
            app._select_resource("deployments")
            await wait_for(lambda: app._resource_name == "deployments")
            await pilot.press("enter")
            assert "target changed" in str(
                app.screen.query_one("#forward-feedback", Static).content
            )
            assert not app.forwards.infos
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_session_updates_preserve_selected_row_and_both_scroll_axes(tmp_path):
    from dataclasses import replace
    from uuid import uuid4

    from kuberich.domain.port_forwards import parse_mappings
    from kuberich.domain.targets import ResourceTarget, SessionIdentity
    from kuberich.services.port_forwards import ForwardInfo

    app = KubeRichApp(
        Settings(),
        logging.getLogger("owned-forward-table"),
        catalog=catalog_fixture(tmp_path, "http://127.0.0.1:1"),
    )
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        for index in range(32):
            target = ResourceTarget(
                SessionIdentity("owned-table-context", 1),
                "",
                "pods",
                "team",
                f"pod-{index:02}",
                f"uid-{index:02}",
            )
            app.forwards._record_changed(
                ForwardInfo(
                    uuid4(), target, parse_mappings(":80"), "127.0.0.1", state=ForwardState.STOPPED
                )
            )
        app.action_port_forwards()
        await wait_for(lambda: isinstance(app.screen, ForwardScreen))
        await pilot.pause()
        screen = app.screen
        screen.table.move_cursor(row=23)
        await pilot.pause()
        screen.table.scroll_to(20, 19, animate=False, immediate=True, force=True)
        await pilot.pause()
        selected = screen.table.coordinate_to_cell_key(screen.table.cursor_coordinate).row_key.value
        position = (screen.table.scroll_x, screen.table.scroll_y)
        app.forwards._record_changed(
            replace(app.forwards.infos[1], message="Updated public status")
        )
        screen.refresh_sessions()
        await pilot.pause()
        assert (
            screen.table.coordinate_to_cell_key(screen.table.cursor_coordinate).row_key.value
            == selected
        )
        assert (screen.table.scroll_x, screen.table.scroll_y) == position
        screen.action_filter()
        await pilot.press(*"pod-23")
        await pilot.press("enter")
        assert screen.table.row_count == 1 and screen.table.cursor_row == 0
        await pilot.press("escape")
