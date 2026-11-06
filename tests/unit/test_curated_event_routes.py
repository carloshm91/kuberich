"""Dedicated Event routes and metadata fallback retain their actual API identity."""

from dataclasses import replace

import pytest

from kuberich.domain.registry import definition_for_resource, resource_row
from kuberich.domain.resources import resource_record
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ResourceSelection
from kuberich.errors import AppError
from tests.support.events import EVENT_CANARY, event_manifest, event_resource


@pytest.mark.parametrize("modern", [False, True])
def test_events_route_keeps_exact_group_and_version_without_server_column_ownership(modern):
    resource = event_resource(modern=modern)
    selection = ResourceSelection(resource.name, resource.group, resource.version)
    route = ViewRoute.events(selection)
    assert route.kind is ViewKind.EVENTS and route.selection is selection
    assert route.display_key == "events" and route.resource_name == "events"


@pytest.mark.parametrize(
    "selection", [ResourceSelection("pods"), ResourceSelection("events", "other.example")]
)
def test_dedicated_events_route_cannot_masquerade_as_another_resource(selection):
    with pytest.raises(AppError, match="Event API"):
        ViewRoute.events(selection)


@pytest.mark.parametrize("modern", [False, True])
def test_unsupported_served_event_versions_only_expose_metadata_and_explicit_limit(modern):
    resource = replace(event_resource(modern=modern), version="v99")
    body = event_manifest(modern=modern)
    body["apiVersion"] = resource.api_version
    definition = definition_for_resource(resource)
    assert definition.name == "events" and definition.group == resource.group
    assert tuple(column.key for column in definition.columns) == (
        "namespace",
        "name",
        "info",
        "age",
    )
    row = resource_row(resource_record(resource, body), definition, resource=resource)
    assert row.uid == body["metadata"]["uid"] and row.name == body["metadata"]["name"]
    assert row.values[2].text == "Unsupported API version or schema"
    assert EVENT_CANARY not in repr(row)
