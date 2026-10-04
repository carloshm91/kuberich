"""Launch flags change visible widgets and preserve guards during input/resize."""

import logging
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
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(f"#{hidden}").display
        assert app.resources.region.height > 0
        assert str(app.status.content).startswith("Read-only")
        screenshot = app.export_screenshot(title="Kubetrol launch presentation")
        if presentation.headless or presentation.logoless:
            assert ">kubetrol<" not in screenshot
        if presentation.crumbsless:
            assert "Context:" not in screenshot and "Namespace:" not in screenshot
        output = Path(__file__).resolve().parents[2] / "artifacts/ui"
        output.mkdir(parents=True, exist_ok=True)
        identity = f"{int(presentation.headless)}{int(presentation.logoless)}{int(presentation.crumbsless)}"
        (output / f"launch-{identity}.svg").write_text(screenshot)
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
