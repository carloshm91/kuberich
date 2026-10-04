"""Real Textual/Pilot behavior: navigation, typed input, mouse, sizing and failures."""

import logging
from pathlib import Path

import pytest
from rich.text import Text
from textual.events import Paste
from textual.widgets import Static

from kubetrol.config.schema import Settings
from kubetrol.diagnostics.logging import diagnostic_logging
from kubetrol.errors import AppError
from kubetrol.ui.app import DISCONNECTED_STATUS, HelpScreen, KubetrolApp


def make_app(settings: Settings | None = None) -> KubetrolApp:
    return KubetrolApp(settings or Settings(), logging.Logger("ui-test", level=100))


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (60, 18), (100, 12), (100, 30), (160, 50)])
async def test_startup_is_disconnected_and_core_controls_fit(size: tuple[int, int]) -> None:
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.resources.row_count == 0
        assert app.focused is app.resources
        assert str(app.query_one("#context", Static).content) == "Context: —"
        assert str(app.query_one("#namespace", Static).content) == "Namespace: —"
        assert str(app.query_one("#connection", Static).content) == "Disconnected"
        for identifier in ("context", "namespace", "connection", "filter", "command", "status"):
            region = app.query_one(f"#{identifier}").region
            assert region.width > 0 and region.height > 0
            assert region.x >= 0 and region.y >= 0
            assert region.right <= size[0] and region.bottom <= size[1]
        await pilot.press("q")
    assert not app.is_running
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_filter_focus_typing_submit_and_escape_are_consistent() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("slash", "a", "q", "slash", "colon", "question_mark")
        assert app.focused is app.filter_input
        assert app.filter_input.value == "aq/:?"
        assert app.is_running
        assert "Filter active" in str(app.status.content)
        await pilot.press("escape")
        assert app.focused is app.resources and app.filter_input.value == "aq/:?"
        await pilot.press("escape")
        assert app.filter_input.value == "" and str(app.status.content) == DISCONNECTED_STATUS
        await pilot.press("slash", "x", "enter")
        assert app.focused is app.resources and app.filter_input.value == "x"


@pytest.mark.asyncio
async def test_tab_shift_tab_and_mouse_change_focus() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("tab")
        assert app.focused is app.filter_input
        await pilot.press("tab")
        assert app.focused is app.command_input
        await pilot.press("shift+tab")
        assert app.focused is app.filter_input
        assert await pilot.click("#command")
        assert app.focused is app.command_input
        await pilot.press("a", "escape")
        assert app.focused is app.resources and app.command_input.value == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["question_mark", "f1"])
async def test_help_is_not_stacked_and_escape_restores_focus(key: str) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("colon", "a", "f1")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press(key, "f1", "slash", "colon")
        assert len(app.screen_stack) == 2
        assert not app.check_action("focus_filter", ())
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
        assert app.focused is app.command_input and app.command_input.value == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_help_close_button_is_visible_and_clickable(size: tuple[int, int]) -> None:
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await pilot.press("question_mark")
        close = app.screen.query_one("#close-help")
        assert close.region.bottom <= size[1] and close.region.right <= size[0]
        assert await pilot.click("#close-help")
        assert len(app.screen_stack) == 1 and app.focused is app.resources


@pytest.mark.asyncio
async def test_resize_while_help_is_open_updates_the_workspace() -> None:
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        assert not app.screen.has_class("compact")
        await pilot.press("question_mark")
        await pilot.resize_terminal(40, 12)
        await pilot.press("escape")
        assert app.screen.has_class("compact")
        assert app.command_input.region.bottom <= 12
        await pilot.resize_terminal(140, 40)
        assert not app.screen.has_class("compact")
        assert app.query_one("#build-info").display


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["help", ":help", "HELP", "?"])
async def test_help_commands_are_real_navigation(command: str) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        app.command_input.value = command
        await pilot.press("enter")
        assert isinstance(app.screen, HelpScreen)
        assert app.command_input.value == ""
        await pilot.press("escape")
        assert app.focused is app.resources


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["quit", "q", "exit"])
async def test_quit_commands_exit_cleanly(command: str) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        app.command_input.value = command
        await pilot.press("enter")
    assert app.return_code == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["q", "ctrl+q", "ctrl+c"])
async def test_quit_keys_exit_cleanly(key: str) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press(key)
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_unknown_and_empty_commands_do_not_echo_input_or_break_navigation() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        app.command_input.value = "[red]opaque-secret[/red]\x1b]52;c;danger\x07"
        await pilot.press("enter")
        assert str(app.status.content) == "Command unavailable in this preview. Use help or quit."
        assert app.command_input.value == "" and app.focused is app.resources
        await pilot.press("colon", "enter")
        assert str(app.status.content) == DISCONNECTED_STATUS


@pytest.mark.asyncio
async def test_mouse_selects_a_row_and_arrows_preserve_widget_navigation() -> None:
    # Fixture rows qualify the widget interaction; startup never adds sample resources.
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        for index in range(4):
            app.resources.add_row(
                *(Text(value) for value in ("fixture", f"row-{index}", "0/1", "Pending", "1m"))
            )
        await pilot.pause()
        assert await pilot.click("#resources", offset=(3, 3))
        assert app.focused is app.resources
        assert app.resources.cursor_row == 2
        await pilot.press("up")
        assert app.resources.cursor_row == 1
        await pilot.press("down")
        assert app.resources.cursor_row == 2


def test_unregistered_theme_is_a_safe_config_error() -> None:
    with pytest.raises(AppError, match="theme is unavailable"):
        make_app(Settings(theme="not-registered"))


@pytest.mark.asyncio
async def test_known_light_theme_and_readonly_preference_are_applied() -> None:
    app = make_app(Settings(theme="textual-light", read_only=True))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "textual-light"
        assert "Read-only preference" in str(app.query_one("#build-info", Static).content)


@pytest.mark.asyncio
async def test_monochrome_mode_and_unicode_filter_remain_navigable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    app = make_app()
    async with app.run_test() as pilot:
        assert app.no_color
        await pilot.press("slash", "c", "a", "f", "é")
        # Pilot 8.x cannot reverse emoji key names; use the real paste event.
        app.filter_input.post_message(Paste("🙂"))
        await pilot.pause()
        await pilot.press("enter")
        assert app.filter_input.value == "café🙂"
        assert app.focused is app.resources


@pytest.mark.asyncio
async def test_unhandled_error_reaches_tests_and_log_omits_exception_values(tmp_path: Path) -> None:
    class BrokenApp(KubetrolApp):
        def on_mount(self) -> None:
            super().on_mount()
            raise RuntimeError("opaque-sensitive-ui-value")

    path = tmp_path / "diagnostics.log"
    with diagnostic_logging(path, "DEBUG") as logger:
        app = BrokenApp(Settings(), logger)
        with pytest.raises(RuntimeError, match="opaque-sensitive-ui-value"):
            async with app.run_test():
                pass
    assert app.return_code == 1 and not app.is_running
    assert "exception=RuntimeError" in path.read_text()
    assert "opaque-sensitive-ui-value" not in path.read_text()


@pytest.mark.asyncio
async def test_error_cleanup_survives_unavailable_diagnostic_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenApp(KubetrolApp):
        def on_mount(self) -> None:
            raise RuntimeError("fixture-error")

    logger = logging.Logger("failed-diagnostics")

    def denied(*args: object, **kwargs: object) -> None:
        raise AppError("Cannot write diagnostic log.")

    monkeypatch.setattr(logger, "error", denied)
    app = BrokenApp(Settings(), logger)
    with pytest.raises(RuntimeError, match="fixture-error"):
        async with app.run_test():
            pass
    assert app.return_code == 1 and not app.is_running
