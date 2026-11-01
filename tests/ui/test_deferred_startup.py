"""Real startup input remains usable before deferred table ownership starts."""

import logging

import pytest
from textual.widgets import Input

from kuberich.config.schema import Settings
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import Command, ResourceCommand
from kuberich.ui import app as app_module
from kuberich.ui.app import KubeRichApp
from kuberich.ui.view_mounts import ViewMounts
from kuberich.ui.views import ViewScreen
from tests.support.connections import catalog_fixture
from tests.support.workspace import wait_for


class HeldStart(ViewMounts):
    """Hold this owned scheduler port; native widget Mount handlers stay real."""

    def start(self):
        pass


def hold_start(monkeypatch):
    owners = []

    def create(*args, **kwargs):
        owner = HeldStart(*args, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(app_module, "ViewMounts", create)
    return owners


@pytest.mark.asyncio
async def test_early_context_completion_mouse_and_rejected_scopes_work_before_background_mounts(
    tmp_path, monkeypatch
):
    owners = hold_start(monkeypatch)
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-startup", level=100),
        catalog=catalog_fixture(tmp_path, "http://127.0.0.1:9"),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.resources.is_mounted
        assert not app.is_mounted(app.context_table)
        assert not app.is_mounted(app.namespace_table)
        assert not app.is_mounted(app.standard_table)
        frame = app.query_one("#resource-view").region
        await pilot.press("colon", "c", "t", "tab", "enter")
        await wait_for(lambda: app.context_table.row_count == 2)
        assert app.context_table.display and app.focused is app.context_table
        for command in ("ns", "deploy", "ctx"):
            await pilot.press("colon", *command, "enter")
            assert app.context_table.display
        assert not app.is_mounted(app.namespace_table)
        assert not app.is_mounted(app.standard_table)
        assert app.query_one("#resource-view").region == frame
        assert await pilot.click("#filter")
        assert app.focused is app.filter_input
        await pilot.press(*"Two", "enter")
        await wait_for(lambda: app.context_table.row_count == 1)
        assert app.context_table.capture_viewport().selected == "kuberich-test-Two"
        assert app.sessions.client is None
        selected_region = app.context_table.region
        await app.workspace.close()
        ViewMounts.start(owners[0])
        await owners[0].wait_ready()
        await pilot.pause()
        assert app.context_table.region == selected_region
        assert app.context_table.capture_viewport().selected == "kuberich-test-Two"
        assert all(
            table.is_mounted
            for table in (
                app.resources,
                app.namespace_table,
                app.context_table,
                app.standard_table,
                app.custom_table,
            )
        )
        assert app.context_table.display and not app.resources.display
        await pilot.press("ctrl+q")
    assert app.return_code == 0 and app.sessions.client is None


@pytest.mark.asyncio
async def test_initial_deployment_table_retains_focus_columns_and_geometry_after_background_mounts(
    tmp_path, monkeypatch
):
    owners = hold_start(monkeypatch)
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-startup", level=100),
        initial_command=ResourceCommand(RESOURCE_ALIASES["deploy"]),
        catalog=catalog_fixture(tmp_path, "http://127.0.0.1:9"),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.standard_table
        assert table.is_mounted and app.focused is table and table.display
        region, columns = table.region, tuple(table.columns)
        assert not app.is_mounted(app.resources)
        await app.workspace.close()
        ViewMounts.start(owners[0])
        await owners[0].wait_ready()
        await pilot.pause()
        assert app.focused is table and table.region == region
        assert tuple(table.columns) == columns
        assert table.definition == RESOURCE_ALIASES["deploy"]
        assert table.display and not app.resources.display
        assert app.resources.is_mounted and app.namespace_table.is_mounted
        assert app.sessions.client is None
        await pilot.press("ctrl+q")
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_initial_namespace_columns_can_change_before_other_tables_enter_the_dom(
    tmp_path, monkeypatch
):
    owners = hold_start(monkeypatch)
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-startup", level=100),
        initial_command=Command.NAMESPACES,
        catalog=catalog_fixture(tmp_path, "http://127.0.0.1:9"),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.namespace_table.is_mounted and app.focused is app.namespace_table
        assert not app.is_mounted(app.resources)
        frame = app.query_one("#resource-view").region
        await pilot.press("colon", *"views", "enter")
        assert isinstance(app.screen, ViewScreen)
        app.screen.query_one("#view-columns", Input).value = "name:12 status"
        assert await pilot.click("#view-session")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert len(app.namespace_table.columns) == 2
        assert app.namespace_table.columns[next(iter(app.namespace_table.columns))].width == 12
        assert app.query_one("#resource-view").region == frame
        assert app.focused is app.namespace_table
        assert not app.is_mounted(app.standard_table) and app.sessions.client is None
        selected_region = app.namespace_table.region
        await app.workspace.close()
        ViewMounts.start(owners[0])
        await owners[0].wait_ready()
        await pilot.pause()
        assert app.namespace_table.region == selected_region
        assert len(app.namespace_table.columns) == 2
        assert app.namespace_table.display and not app.resources.display
        assert app.resources.is_mounted and app.standard_table.is_mounted
        await pilot.press("ctrl+q")
    assert app.return_code == 0 and app.sessions.client is None
