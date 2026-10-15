"""Disclosure through the actual workspace; no implicit payloads or stale copies."""

import asyncio
import base64
import logging

import pytest

from kuberich.config.schema import Settings
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.configuration_data import ConfigurationScreen
from tests.support.configuration_data import TEXT, data_api
from tests.support.connections import catalog_fixture
from tests.support.workspace import wait_for


def app_for(tmp_path, url, kind):
    return KubeRichApp(
        Settings(read_only=True),
        logging.Logger("configuration-data", level=100),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=ResourceCommand(
            RESOURCE_ALIASES["secret" if kind == "Secret" else "cm"], "team"
        ),
    )


async def opened(app, pilot):
    await wait_for(lambda: app.standard_table.row_count == 1)
    await pilot.press("enter")
    await wait_for(
        lambda: isinstance(app.screen, ConfigurationScreen) and app.screen.index is not None
    )
    await pilot.pause()
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,size", [("Secret", (100, 30)), ("ConfigMap", (40, 12))])
async def test_hidden_keys_reveal_encoding_copy_controls_and_table_return(tmp_path, kind, size):
    async with data_api(kind) as (url, _):
        app = app_for(tmp_path, url, kind)
        async with app.run_test(size=size) as pilot:
            screen = await opened(app, pilot)
            assert screen.viewer.text == "" and app.clipboard == ""
            assert screen.keys.row_count == 2 and "Data keys" in str(app.header.shortcuts)
            assert TEXT not in repr(screen.index)
            await pilot.press("r")
            await wait_for(lambda: screen.revealed)
            assert screen.viewer.text == escape_controls(TEXT, allow_newlines=True)
            assert "[red]" in screen.viewer.text and "\x1b" not in screen.viewer.text
            with pytest.raises(AppError, match="configuration data"):
                app.export_screenshot()
            assert app.deliver_screenshot("refused.svg", str(tmp_path)) is None
            await pilot.pause()
            assert not (tmp_path / "refused.svg").exists() and app.is_running
            await pilot.press("r")
            assert screen.viewer.text == "" and not screen.revealed
            await pilot.press("ctrl+y")
            await wait_for(lambda: app.clipboard == TEXT)
            assert screen.viewer.text == ""  # Copy is explicit but does not reveal on screen.
            await pilot.press("x", "r")
            await wait_for(lambda: screen.revealed)
            assert screen.viewer.text == base64.b64encode(TEXT.encode()).decode()
            await pilot.press("down")
            assert screen.viewer.text == ""
            await pilot.press("r")
            await wait_for(lambda: screen.revealed)
            assert screen.viewer.text == "/wA="
            await pilot.press("x", "r")
            await wait_for(lambda: "binary" in str(screen.status.content))
            assert screen.viewer.text == ""
            await pilot.press("escape")
            await wait_for(lambda: not screen._tasks)
            assert screen.index is None and screen.viewer.text == ""
            assert app.focused is app.standard_table
            assert "<svg" in app.export_screenshot()
            app.deliver_screenshot("workspace.svg", str(tmp_path))
            await wait_for(lambda: (tmp_path / "workspace.svg").exists())
            assert TEXT not in (tmp_path / "workspace.svg").read_text()


@pytest.mark.asyncio
async def test_navigation_and_busy_disclosure_do_not_discard_owned_metadata_reload(tmp_path):
    async with data_api() as (url, api):
        app = app_for(tmp_path, url, "Secret")
        async with app.run_test() as pilot:
            screen = await opened(app, pilot)
            await pilot.press("down")
            selected = screen._selected().identity
            api.hold = True
            api.started.clear()
            await pilot.press("R")
            await asyncio.wait_for(api.started.wait(), 5)
            await pilot.press("up", "down", "x", "r")
            assert screen.viewer.text == "" and "in progress" in str(screen.status.content)
            api.value["metadata"]["resourceVersion"] = "navigation-reloaded"
            api.release.set()
            await wait_for(
                lambda: (
                    screen.index is not None
                    and screen.index.resource_version == "navigation-reloaded"
                )
            )
            await pilot.pause()
            assert screen._selected().identity == selected and not screen._tasks
            assert screen.viewer.text == "" and screen.encoded
            await pilot.press("question_mark")
            assert "Navigation · data" in app.screen.text
            await pilot.press("escape", "r")
            await wait_for(lambda: screen.revealed)
            assert screen.viewer.text == "/wA="


@pytest.mark.asyncio
async def test_changed_version_rejects_reveal_and_reload_refreshes_metadata(tmp_path):
    async with data_api() as (url, api):
        app = app_for(tmp_path, url, "Secret")
        async with app.run_test() as pilot:
            screen = await opened(app, pilot)
            api.value["metadata"]["resourceVersion"] = "changed"
            await pilot.press("r")
            await wait_for(lambda: "changed" in str(screen.status.content))
            assert not screen.revealed and screen.viewer.text == ""
            await pilot.press("R")
            await wait_for(
                lambda: screen.index is not None and screen.index.resource_version == "changed"
            )
            await pilot.pause()
            await pilot.press("enter")
            await wait_for(lambda: screen.revealed)


@pytest.mark.asyncio
async def test_clipboard_exception_is_generic_and_viewer_stays_hidden(tmp_path, monkeypatch):
    async with data_api() as (url, _):
        app = app_for(tmp_path, url, "Secret")
        async with app.run_test() as pilot:
            screen = await opened(app, pilot)

            def refused(value):
                raise RuntimeError(TEXT)

            monkeypatch.setattr(app, "copy_to_clipboard", refused)
            await pilot.press("ctrl+y")
            await wait_for(lambda: "Clipboard write failed" in str(screen.status.content))
            assert TEXT not in str(screen.status.content) and not screen.viewer.text


@pytest.mark.asyncio
async def test_held_read_is_hidden_on_mode_change_and_drained_before_client_close(tmp_path):
    async with data_api() as (url, api):
        app = app_for(tmp_path, url, "Secret")
        async with app.run_test() as pilot:
            screen = await opened(app, pilot)
            api.started.clear()
            api.hold = True
            await pilot.press("r")
            await asyncio.wait_for(api.started.wait(), 5)
            await pilot.press("x")
            api.release.set()
            await wait_for(lambda: not screen._tasks)
            assert not screen.revealed and screen.viewer.text == ""
            await app._close_client_operations(screen.service.client)
            assert screen._data_stopped and not screen._tasks and screen.index is None
            screen.action_reveal()
            assert "stopped" in str(screen.status.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["empty", "invalid", "denied"])
async def test_empty_and_refused_data_stay_hidden_and_back_button_restores_table(tmp_path, problem):
    async with data_api() as (url, api):
        if problem == "empty":
            api.value["data"] = {}
        elif problem == "invalid":
            api.value["data"]["chosen"] = "sensitive-invalid-base64!"
        else:
            api.read_status = 403
        app = app_for(tmp_path, url, "Secret")
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.press("v")
            await wait_for(lambda: isinstance(app.screen, ConfigurationScreen))
            screen = app.screen
            await wait_for(lambda: not screen._tasks)
            assert not screen.viewer.text and app.clipboard == ""
            assert "sensitive-invalid" not in str(screen.status.content)
            assert screen.keys.row_count == 0
            screen.action_reveal()
            await wait_for(lambda: "Select a current" in str(screen.status.content))
            await pilot.click("#configuration-back")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert app.focused is app.standard_table


@pytest.mark.asyncio
async def test_long_value_preview_is_bounded_and_oversized_clipboard_is_refused(tmp_path):
    async with data_api("ConfigMap") as (url, api):
        api.value["data"]["chosen"] = "owned-long-value" * 5000
        app = app_for(tmp_path, url, "ConfigMap")
        async with app.run_test() as pilot:
            screen = await opened(app, pilot)
            await pilot.click("#configuration-reveal")
            await wait_for(lambda: screen.revealed)
            assert screen.viewer.text.endswith("[Preview limited to 16384 characters]")
            assert len(screen.viewer.text) < 16500
            await pilot.click("#configuration-copy")
            await wait_for(lambda: "64 KiB" in str(screen.status.content))
            assert not screen.viewer.text and app.clipboard == ""
            await pilot.click("#configuration-encoding")
            assert screen.encoded
            await pilot.click("#configuration-reload")
            await wait_for(lambda: screen.index is not None and not screen._tasks)
            assert not screen.viewer.text


@pytest.mark.asyncio
async def test_changed_scope_clears_revealed_value_and_cancels_held_copy(tmp_path):
    async with data_api() as (url, api):
        app = app_for(tmp_path, url, "Secret")
        async with app.run_test() as pilot:
            screen = await opened(app, pilot)
            await pilot.press("r")
            await wait_for(lambda: screen.revealed)
            screen.validate_target()
            assert screen.revealed  # An unchanged captured target remains usable.
            api.started.clear()
            api.hold = True
            screen.action_copy()
            await asyncio.wait_for(api.started.wait(), 5)
            screen.action_reveal()
            assert "in progress" in str(screen.status.content)
            screen.service.current = lambda: False
            screen.validate_target()
            api.release.set()
            await wait_for(lambda: not screen._tasks)
            assert not screen.viewer.text and screen.index is None and not app.clipboard
            assert "changed" in str(screen.status.content)
