"""Custom rendering binds real rows to bounded, versioned server layouts."""

import asyncio
from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.custom import CustomLayout
from kuberich.domain.navigation import MAX_HISTORY
from kuberich.domain.resources import ResourceSnapshot, ServerColumn
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ResourceSelection, ViewObservation
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.ui.controllers.base import RenderRequest, ViewDriver
from kuberich.ui.controllers.custom import CustomController
from kuberich.ui.controllers.filtering import FilterOptions, ResourceFilter
from kuberich.ui.custom import CustomTable
from tests.support.tables import custom_resource
from tests.unit.test_custom_layout import captured


class CustomHost(App[None]):
    def __init__(self):
        super().__init__()
        self.table = CustomTable()

    def compose(self) -> ComposeResult:
        yield self.table


class Preferences:
    def __init__(self):
        self.prepared, self.configured = [], []
        self.columns = None

    def prepare(self, view, layout=None):
        self.prepared.append(view)
        return layout.configure(self.columns) if self.columns is not None else None

    def configure_custom(self, view):
        self.configured.append(view)


def request_for(*, name="widgets", version="v1", headers=(), records=(), revision=1):
    resource = custom_resource(name=name, version=version)
    return RenderRequest(
        ViewObservation(
            revision=revision,
            context="owned",
            snapshot=ResourceSnapshot(resource, "team", "owned", records, headers),
        ),
        "",
        lambda: True,
        ViewRoute.custom(ResourceSelection(name, resource.group, version, server_columns=True)),
    )


@pytest.mark.asyncio
async def test_custom_controller_projects_real_cells_preferences_filter_and_viewport():
    app, preferences = CustomHost(), Preferences()
    controller = CustomController(
        app.table,
        ResourceFilter(MetadataFilter(), lambda _: FilterOptions()),
        preferences,
        lambda _: frozenset({"inspect"}),
    )
    driver = ViewDriver(controller)
    headers = (ServerColumn("Level", "integer"), ServerColumn("Extra", "string", priority=1))
    records = (
        captured(headers, (3, "owned-a"), name="alpha"),
        captured(headers, (8, "owned-b"), name="beta"),
    )
    request = request_for(headers=headers, records=records)
    async with app.run_test() as pilot:
        assert (await driver.render(replace(request, observation=ViewObservation()))).count == 0
        result = await driver.render(request)
        assert result.applied and result.count == result.filtered == app.table.row_count == 2
        assert app.table.get_cell("owned-alpha", "c1").text == "3"
        assert preferences.prepared == preferences.configured == [request.observation]
        app.table.move_cursor(row=1)
        await pilot.pause()
        viewport = driver.capture_viewport()
        result = await driver.render(replace(request, query="beta"))
        assert result.applied and result.filtered == 1
        assert driver.capture_viewport().selected == viewport.selected
        assert driver.available_actions(request) == frozenset({"inspect"})
        preferences.columns = ("c2", "c1")
        assert (await driver.render(request)).applied
        assert app.table.get_cell("owned-alpha", "c2").text == "owned-a"
        driver.restore_viewport(viewport)
        assert driver.capture_viewport().selected == viewport.selected


@pytest.mark.asyncio
async def test_schema_changed_during_filter_refuses_the_captured_rows(monkeypatch):
    app, preferences, metadata = CustomHost(), Preferences(), MetadataFilter()
    entered, release = asyncio.Event(), asyncio.Event()
    actual = metadata.apply

    async def held(*args, **kwargs):
        entered.set()
        await release.wait()
        return await actual(*args, **kwargs)

    monkeypatch.setattr(metadata, "apply", held)
    driver = ViewDriver(
        CustomController(
            app.table,
            ResourceFilter(metadata, lambda _: FilterOptions()),
            preferences,
            lambda _: frozenset(),
        )
    )
    old_headers = (ServerColumn("Old", "string"),)
    new_headers = (ServerColumn("New", "integer"),)
    request = request_for(headers=old_headers, records=(captured(old_headers, ("old",)),))
    async with app.run_test():
        pending = asyncio.create_task(driver.render(request))
        try:
            await entered.wait()
            app.table.configure_layout(CustomLayout.build(custom_resource(), new_headers), 1)
        finally:
            release.set()
        outcome = await pending
        assert not outcome.applied and app.table.row_count == 0
        fresh = request_for(headers=new_headers, records=(captured(new_headers, (7,)),))
        assert (await driver.render(fresh)).applied
        assert app.table.get_cell("owned-one", "c1").text == "7"


@pytest.mark.asyncio
async def test_custom_layout_cache_is_bounded_context_owned_and_checks_full_resource(monkeypatch):
    app, built = CustomHost(), []
    controller = CustomController(
        app.table,
        ResourceFilter(MetadataFilter(), lambda _: FilterOptions()),
        Preferences(),
        lambda _: frozenset(),
    )
    actual = CustomLayout.build

    def observed(cls, resource, headers):
        built.append((resource, headers))
        return actual(resource, headers)

    monkeypatch.setattr(CustomLayout, "build", classmethod(observed))
    async with app.run_test():
        first = request_for(name="owned0")
        await controller.project(first)
        assert len(built) == 1
        await controller.project(first)
        assert len(built) == 1
        for index in range(1, MAX_HISTORY + 1):
            await controller.project(request_for(name=f"owned{index}"))
        assert len(built) == MAX_HISTORY + 1
        await controller.project(first)
        assert len(built) == MAX_HISTORY + 2
        controller.reset_context()
        await controller.project(first)
        assert len(built) == MAX_HISTORY + 3
        resource = replace(first.observation.snapshot.resource, kind="RenamedWidget")
        changed = replace(
            first,
            observation=replace(
                first.observation, snapshot=replace(first.observation.snapshot, resource=resource)
            ),
        )
        await controller.project(changed)
        assert built[-1][0] == resource and len(built) == MAX_HISTORY + 4
        await controller.project(request_for(name="owned0", version="v2"))
        assert built[-1][0].version == "v2" and len(built) == MAX_HISTORY + 5
