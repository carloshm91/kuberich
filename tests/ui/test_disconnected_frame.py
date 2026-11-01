"""The initial local frame survives rendering and only a real connection replaces it."""

import logging

import pytest
from aiohttp import web
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import Command
from kuberich.ui.app import KubeRichApp
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


def initial_frame(app):
    assert str(app.query_one("#resource-view").border_title) == "Resources · no connection"
    assert str(app.query_one("#empty-title", Static).content) == "No cluster connection"
    assert str(app.query_one("#empty-description", Static).content) == (
        "Live resources are not connected in this preview."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial", [Command.EMPTY, Command.THEMES, Command.ABOUT, Command.HELP, Command.VIEWS]
)
async def test_no_context_frame_survives_initial_commands_and_local_rendering(initial):
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-disconnected-frame"),
        catalog=KubeCatalog(),
        initial_command=initial,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        if isinstance(app.screen, ModalScreen):
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
        await pilot.pause()
        initial_frame(app)
        app.filter_input.value = "owned-filter"
        await pilot.pause()
        initial_frame(app)
        assert app.state.context is None and app.sessions.client is None


@pytest.mark.asyncio
async def test_local_context_back_restores_initial_frame_and_real_connection_replaces_it(
    tmp_path, monkeypatch
):
    opened = []
    original = KubernetesSession.open

    async def observed(client, **options):
        opened.append(client)
        return await original(client, **options)

    monkeypatch.setattr(KubernetesSession, "open", observed)

    async def namespace_handler(request):
        return namespaces("team", "default")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("api")))

    async with workspace_api(namespace_handler, resources) as url:
        app = KubeRichApp(
            Settings(),
            logging.Logger("owned-frame-transition"),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=Command.THEMES,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            initial_frame(app)
            await app.run_command("ctx")
            await wait_for(lambda: app.context_table.row_count == 2)
            await pilot.press("escape")
            await pilot.pause()
            initial_frame(app)
            assert not opened
            await app.run_command("ctx kuberich-test-one")
            await wait_for(
                lambda: app.state.status is ViewStatus.LIVE and app.resources.row_count == 1
            )
            await pilot.pause()
            assert len(opened) == 1 and "pods(team)[1]" in str(
                app.query_one("#resource-view").border_title
            )
            assert "Live" in str(app.status.content)
