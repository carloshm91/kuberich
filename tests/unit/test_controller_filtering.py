"""Controller filtering retains metadata policy and live local preference reads."""

from dataclasses import replace

import pytest

from kuberich.domain.namespaces import namespace_row
from kuberich.domain.pods import pod_row
from kuberich.domain.pulse import PulseDrilldown, PulsePredicate
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.ui.controllers.base import RenderRequest
from kuberich.ui.controllers.filtering import FilterOptions, ResourceFilter
from tests.support.controller_rows import observed
from tests.support.pods import pod, snapshot


@pytest.mark.asyncio
async def test_controller_filter_combines_errors_and_namespace_favorites_without_hiding_problems():
    data, route = observed("namespaces")
    rows = tuple(namespace_row(record) for record in data.items)
    options = FilterOptions(favorites=True, namespaces=("beta",))
    contexts = []

    def current(context):
        contexts.append(context)
        return options

    service = ResourceFilter(MetadataFilter(), current)
    request = RenderRequest(
        ViewObservation(context="owned", snapshot=data), "", lambda: True, route
    )
    result = await service.apply(rows, request)
    assert [row.name for row in result.rows] == ["beta"] and result.problem is None
    assert contexts == ["owned", "owned"]
    result = await service.apply(rows, replace(request, query="re:["))
    assert result.rows == rows and "Invalid regex" in result.problem
    data = snapshot(pod("healthy"), pod("unhealthy", ready=False))
    options = FilterOptions(errors=True)
    result = await service.apply(
        tuple(pod_row(record) for record in data.items),
        replace(request, observation=ViewObservation(snapshot=data), route=ViewRoute.pods()),
    )
    assert [row.name for row in result.rows] == ["unhealthy"]
    assert result.problem == "Errors only · 1/2 pods · 0 unknown omitted"


@pytest.mark.asyncio
async def test_controller_filter_observes_changed_options_after_the_public_filter_boundary(
    monkeypatch,
):
    data, route = observed("namespaces")
    rows = tuple(namespace_row(record) for record in data.items)
    options = FilterOptions()
    metadata = MetadataFilter()
    actual = metadata.apply

    async def changed(*args, **kwargs):
        nonlocal options
        result = await actual(*args, **kwargs)
        options = FilterOptions(favorites=True, namespaces=("alpha",))
        return result

    monkeypatch.setattr(metadata, "apply", changed)
    service = ResourceFilter(metadata, lambda _: options)
    result = await service.apply(
        rows, RenderRequest(ViewObservation(snapshot=data), "", lambda: True, route)
    )
    assert [row.name for row in result.rows] == ["alpha"]


@pytest.mark.asyncio
async def test_captured_pulse_predicate_and_uid_filter_before_local_search():
    data = snapshot(pod("ready"), pod("unready", ready=False), pod("other", ready=False))
    rows = tuple(pod_row(record) for record in data.items)
    drilldown = PulseDrilldown(data.resource, "team", PulsePredicate.POD_NOT_READY)
    service = ResourceFilter(MetadataFilter(), lambda _: FilterOptions())
    request = RenderRequest(
        ViewObservation(snapshot=data), "", lambda: True, ViewRoute.pods(), drilldown
    )
    assert [row.name for row in (await service.apply(rows, request)).rows] == ["unready", "other"]
    selected = replace(request, drilldown=replace(drilldown, uid="owned-unready"))
    assert [row.name for row in (await service.apply(rows, selected)).rows] == ["unready"]
    assert not (await service.apply(rows, replace(selected, query="ready-but-missing"))).rows
    # An absent captured UID never silently expands to all matching resources.
    assert not (
        await service.apply(rows, replace(request, drilldown=replace(drilldown, uid="gone")))
    ).rows
