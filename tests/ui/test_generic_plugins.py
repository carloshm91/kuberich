"""Qualified discovery routes retain plugin UID and loading guards without execution."""

import asyncio
import logging
import sys

import pytest

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, Settings
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import GenericResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.plugins import PluginScreen
from tests.support.connections import catalog_fixture
from tests.support.custom import GROUP, custom_api
from tests.support.workspace import wait_for
from tests.ui.test_custom_resources import loaded


def app_for(tmp_path, url):
    settings = Settings(read_only=True)
    document = ConfigDocument(
        settings=settings,
        extensions={
            "plugins": {
                "schema_version": 1,
                "commands": {
                    "inspect": {
                        "command": sys.executable,
                        "args": ["-c", "print('owned preview')"],
                        "scopes": [GROUP + "/v1/widgets"],
                        "trusted_read_only": True,
                        "dangerous": False,
                    }
                },
            }
        },
    )
    return KubeRichApp(
        settings,
        logging.Logger("generic-plugin-preview", level=100),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=GenericResourceCommand("widgets", GROUP, "v1"),
        preferences=PreferenceSource(ConfigLocation(tmp_path / "preferences.yaml", True), document),
    )


@pytest.mark.asyncio
async def test_qualified_generic_plugin_reviews_the_selected_uid_without_execution(tmp_path):
    async with custom_api() as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await wait_for(lambda: bool(app.plugins.plugins))
            app.custom_table.move_cursor(row=app.custom_table.get_row_index("owned-two"))
            await pilot.pause()
            source = app.plugins.capture_source()
            assert source.selection.target.uid == "owned-two"
            assert source.selection.resource == GROUP + "/v1/widgets"
            await pilot.press("colon", *"plugin inspect", "enter")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            screen = app.screen
            assert screen.source.selection.target.uid == "owned-two"
            screen.prepare()
            await wait_for(lambda: screen.review is not None)
            assert screen.review.command.argv[0] == sys.executable
            assert not app.plugins.manager.jobs
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not app.plugins.manager.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "error"),
    [
        ("gadgets." + GROUP + "/v1beta1", "resource view is loading"),
        ("widgets." + GROUP + "/v1beta1", "resource version is loading"),
    ],
)
async def test_generic_plugin_refuses_previous_name_or_version_observation(
    tmp_path, monkeypatch, command, error
):
    async with custom_api() as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test():
            await loaded(app)
            original = app.workspace.store.observation
            owners = []

            def pending_selection(selection):
                # Keep the old published observation while the actual frontend
                # command changes its resource selection.
                task = asyncio.create_task(asyncio.sleep(0))
                owners.append(task)
                return task

            monkeypatch.setattr(app.workspace, "select_resource", pending_selection)
            try:
                assert app.command_input.submit is not None
                app.command_input.submit(command)
                assert app.workspace.store.observation is original
                with pytest.raises(AppError, match=error):
                    app.plugins.capture_source()
                assert not app.plugins.manager.jobs
            finally:
                await asyncio.gather(*owners)
