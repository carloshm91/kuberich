"""Resource adapters project real records into actual UID-keyed table widgets."""

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.views import ViewObservation
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.ui.controllers.base import RenderPort, RenderRequest, ViewDriver
from kuberich.ui.controllers.filtering import FilterOptions, ResourceFilter
from kuberich.ui.controllers.namespaces import NamespaceController
from kuberich.ui.controllers.pods import PodController
from kuberich.ui.controllers.standard import StandardController
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.standard import StandardTable
from tests.support.controller_rows import observed


class ResourceHost(App[None]):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.table = (
            PodTable()
            if kind == "pods"
            else NamespaceTable()
            if kind == "namespaces"
            else StandardTable()
        )

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        if self.kind == "services":
            self.table.configure(RESOURCE_ALIASES[self.kind])
        elif not self.table.columns:
            self.table.setup()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "namespaces", "services"])
async def test_resource_controllers_preserve_real_projection_filter_viewport_and_retirement(kind):
    data, route = observed(kind)
    app, prepared = ResourceHost(kind), []
    filtering = ResourceFilter(MetadataFilter(), lambda _: FilterOptions())
    arguments = (
        app.table,
        filtering,
        lambda view: prepared.append(view),
        lambda _: frozenset({"inspect"}),
    )
    controller = (
        PodController(*arguments)
        if kind == "pods"
        else NamespaceController(*arguments)
        if kind == "namespaces"
        else StandardController(app.table, lambda: app.table.definition, *arguments[1:])
    )
    driver: RenderPort = ViewDriver(controller)
    view = ViewObservation(revision=3, context="owned", snapshot=data)
    request = RenderRequest(view, "", lambda: True, route)
    async with app.run_test() as pilot:
        outcome = await driver.render(request)
        assert outcome.applied and outcome.count == outcome.filtered == 2
        assert controller.projection.cached_count == 2 and prepared == [view]
        app.table.move_cursor(row=1)
        await pilot.pause()
        before = driver.capture_viewport()
        result = await driver.render(replace(request, query="beta"))
        assert result.applied and result.count == 2 and result.filtered == 1
        assert driver.capture_viewport().selected == before.selected
        assert driver.available_actions(request) == frozenset({"inspect"})
        assert not (await driver.render(replace(request, current=lambda: False))).applied
        assert app.table.row_count == 1
        assert (await driver.render(request)).applied
        driver.restore_viewport(before)
        assert driver.capture_viewport().selected == before.selected
        await controller.retire_projection()
        assert controller.projection.cached_count == 0
        assert (
            await driver.render(replace(request, observation=replace(view, snapshot=None)))
        ).count == 0
        assert app.table.row_count == 0


@pytest.mark.asyncio
async def test_standard_controller_replaces_the_projection_for_the_actual_selected_definition():
    app = ResourceHost("services")
    controller = StandardController(
        app.table,
        lambda: app.table.definition,
        ResourceFilter(MetadataFilter(), lambda _: FilterOptions()),
        lambda _: None,
        lambda _: frozenset(),
    )
    driver = ViewDriver(controller)
    async with app.run_test():
        data, route = observed("services")
        request = RenderRequest(ViewObservation(snapshot=data), "", lambda: True, route)
        assert (await driver.render(request)).applied
        first = controller.projection
        assert (await driver.render(request)).applied and controller.projection is first
        app.table.configure(RESOURCE_ALIASES["jobs"])
        data, route = observed("jobs")
        result = await driver.render(
            replace(request, observation=ViewObservation(revision=1, snapshot=data), route=route)
        )
        assert result.applied and result.count == app.table.row_count == 2
        assert controller.projection is not first
        assert "succeeded" in app.table.columns
        assert app.table.get_row_at(0)[2].text == "Complete"
