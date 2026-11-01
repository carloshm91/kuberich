"""The real root command/help route consumes the canonical command declarations."""

import logging

import pytest
from textual.widgets import Static

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.services.command_catalog import COMMAND_CATALOG
from kuberich.ui.app import KubeRichApp
from kuberich.ui.help import HelpScreen


@pytest.mark.asyncio
@pytest.mark.parametrize("readonly", [False, True])
async def test_actual_help_lists_every_declared_command_without_reserved_stubs(readonly):
    app = KubeRichApp(
        Settings(read_only=readonly), logging.Logger("owned-command-help"), catalog=KubeCatalog()
    )
    async with app.run_test() as pilot:
        await app.run_command("help")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        content = str(app.screen.query_one("#help-content", Static).content)
        for aliases, description in COMMAND_CATALOG.help_rows():
            assert f":{aliases.replace(' / ', '/')}  {description}" in content
        assert ":ssh " not in content and ":apply " not in content and ":patch " not in content
        assert tuple(app.interactions.history.entries) == ("help",)


@pytest.mark.asyncio
async def test_reloaded_aliases_are_used_by_the_actual_command_route(tmp_path):
    from kuberich.services.commands import Command
    from kuberich.ui.appearance import ThemeScreen
    from tests.support.workspace import wait_for
    from tests.ui.test_live_preferences import owned_app, save

    app, path, _notes = owned_app(tmp_path, {}, initial=Command.THEMES)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, ThemeScreen)
        await pilot.pause()
        await pilot.press("escape")
        await app.live_preferences.check()
        save(path, {"navigation": {"aliases": {"guide": "help"}}})
        await app.live_preferences.check()
        await app.run_command("guide")
        await wait_for(lambda: isinstance(app.screen, HelpScreen))
        await pilot.pause()
        assert tuple(app.interactions.history.entries) == ("guide",)
