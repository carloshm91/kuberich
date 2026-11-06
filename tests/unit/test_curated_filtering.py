"""Captured membership cannot expand across API, namespace or query changes."""

from dataclasses import replace
from uuid import UUID

import pytest

from kuberich.domain.curated_navigation import PodRuntimeClass, ResolvedCollectionBookmark
from kuberich.domain.pods import pod_row
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ResourceScope, ViewObservation
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.ui.controllers.base import RenderRequest
from kuberich.ui.controllers.filtering import FilterOptions, ResourceFilter
from tests.support.pods import pod, snapshot


def captured():
    selected, other, elsewhere = pod("selected"), pod("other"), pod("elsewhere", namespace="other")
    selected["spec"] = elsewhere["spec"] = {"runtimeClassName": "sandbox"}
    other["spec"] = {"runtimeClassName": "native"}
    data = snapshot(selected, other, elsewhere)
    bookmark = ResolvedCollectionBookmark(
        data.resource, "team", PodRuntimeClass("sandbox"), ResourceQuery()
    )
    scope = ResourceScope(SessionIdentity("owned", 1, UUID(int=232)), data.resource, "team")
    request = RenderRequest(
        ViewObservation(scope=scope, snapshot=data),
        "",
        lambda: True,
        ViewRoute.pods(),
        curated=bookmark,
    )
    return tuple(pod_row(record) for record in data.items), request


@pytest.mark.asyncio
async def test_membership_is_applied_before_search_and_never_broadens_with_an_empty_result():
    rows, request = captured()
    filtering = ResourceFilter(MetadataFilter(), lambda _: FilterOptions())
    result = await filtering.apply(rows, request)
    assert [row.name for row in result.rows] == ["selected"]
    assert not (await filtering.apply(rows, replace(request, query="other"))).rows
    all_namespaces = replace(
        request,
        observation=replace(
            request.observation, scope=replace(request.observation.scope, namespace=None)
        ),
        curated=replace(request.curated, namespace=None),
    )
    assert [row.name for row in (await filtering.apply(rows, all_namespaces)).rows] == [
        "selected",
        "elsewhere",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", ["scope", "api", "namespace", "query", "snapshot", "snapshot-api"]
)
async def test_obsolete_collection_never_filters_a_replacement_source(mismatch):
    rows, request = captured()
    view, scope = request.observation, request.observation.scope
    if mismatch == "scope":
        view = replace(view, scope=None)
    elif mismatch == "api":
        view = replace(view, scope=replace(scope, resource=replace(scope.resource, version="v99")))
    elif mismatch == "namespace":
        view = replace(view, scope=replace(scope, namespace="other"))
    elif mismatch == "query":
        view = replace(view, scope=replace(scope, query=ResourceQuery(label_selector="app=other")))
    elif mismatch == "snapshot":
        view = replace(view, snapshot=None)
    else:
        view = replace(
            view,
            snapshot=replace(view.snapshot, resource=replace(scope.resource, group="other.test")),
        )
    filtering = ResourceFilter(MetadataFilter(), lambda _: FilterOptions())
    assert not (await filtering.apply(rows, replace(request, observation=view))).rows
