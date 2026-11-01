"""The context adapter runs real projection, filtering and native table guards."""

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.ui.contexts import ContextTable
from kuberich.ui.controllers.base import RenderPort, RenderRequest, ViewDriver
from kuberich.ui.controllers.contexts import ContextController
from tests.support.connections import catalog_fixture


class ContextHost(App[None]):
    def __init__(self):
        super().__init__()
        self.table = ContextTable()

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self) -> None:
        self.table.setup()


@pytest.mark.asyncio
async def test_real_context_controller_preserves_filter_cursor_and_stale_guard(tmp_path):
    catalog = catalog_fixture(tmp_path, "http://127.0.0.1:1")
    app = ContextHost()
    controller = ContextController(
        app.table, lambda: catalog, lambda request: frozenset({"contexts"})
    )
    driver: RenderPort = ViewDriver(controller)
    view = ViewObservation(context="kuberich-test-Two")
    request = RenderRequest(view, "", lambda: True, ViewRoute.contexts())
    async with app.run_test() as pilot:
        result = await driver.render(request)
        assert result.count == result.filtered == app.table.row_count == 2
        assert result.applied and result.unknown == 0 and result.problem is None
        app.table.move_cursor(row=app.table.get_row_index("kuberich-test-Two"))
        await pilot.pause()
        before = driver.capture_viewport()
        assert before.selected == "kuberich-test-Two"
        result = await driver.render(replace(request, query="Two"))
        assert result.count == 2 and result.filtered == app.table.row_count == 1
        assert driver.capture_viewport().selected == before.selected
        assert driver.available_actions(request) == frozenset({"contexts"})
        result = await driver.render(replace(request, current=lambda: False))
        assert not result.applied and app.table.row_count == 1
        result = await driver.render(replace(request, query="re:["))
        assert result.applied and result.filtered == 2 and "Invalid regex" in result.problem
        app.table.move_cursor(row=0)
        driver.restore_viewport(before)
        assert driver.capture_viewport().selected == before.selected


@pytest.mark.asyncio
async def test_context_controller_rechecks_the_guard_during_real_chunked_apply(tmp_path):
    catalog = catalog_fixture(tmp_path, "http://127.0.0.1:1")
    entry = catalog.contexts["kuberich-test-one"]
    catalog.contexts.clear()
    catalog.contexts.update({f"owned-{index:04d}": entry for index in range(300)})
    app = ContextHost()
    driver: RenderPort = ViewDriver(
        ContextController(app.table, lambda: catalog, lambda _: frozenset())
    )
    checks = 0

    def current():
        nonlocal checks
        checks += 1
        return checks < 3

    async with app.run_test():
        result = await driver.render(
            RenderRequest(ViewObservation(), "", current, ViewRoute.contexts())
        )
        assert result.count == result.filtered == 300
        assert not result.applied and checks >= 3 and 0 < app.table.row_count < 300


@pytest.mark.asyncio
async def test_driver_retains_projection_guard_in_addition_to_live_request(tmp_path, monkeypatch):
    catalog = catalog_fixture(tmp_path, "http://127.0.0.1:1")
    app = ContextHost()
    controller = ContextController(app.table, lambda: catalog, lambda _: frozenset())
    original = controller.project

    async def replaced_projection(request):
        projected = await original(request)
        return replace(projected, current=lambda: False)

    monkeypatch.setattr(controller, "project", replaced_projection)
    async with app.run_test():
        result = await ViewDriver(controller).render(
            RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.contexts())
        )
        assert result.count == result.filtered == 2
        assert not result.applied and app.table.row_count == 0
