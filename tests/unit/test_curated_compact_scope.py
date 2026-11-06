"""Compact transport preserves the named read-only view rather than printer ownership."""

import pytest

from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.views import ResourceSelection
from kuberich.errors import AppError


@pytest.mark.parametrize(
    "group,name",
    [("autoscaling", "horizontalpodautoscalers"), ("", "events"), ("events.k8s.io", "events")],
)
def test_compact_curated_selection_keeps_application_owned_columns(group, name):
    scope = ResourceSelection(name, group, "v1", query=ResourceQuery(compact=True))
    assert scope.query.compact and not scope.server_columns


@pytest.mark.parametrize(
    "group,name",
    [
        ("other.example", "horizontalpodautoscalers"),
        ("apps", "deployments"),
        ("", "pods"),
        ("", "services"),
    ],
)
def test_compact_does_not_widen_full_object_views_or_same_plural_in_another_group(group, name):
    with pytest.raises(AppError, match="Compact"):
        ResourceSelection(name, group, query=ResourceQuery(compact=True))


def test_generic_compact_metadata_keeps_its_existing_transport_contract():
    query = ResourceQuery(compact=True)
    assert (
        ResourceSelection("widgets", "owned.example", server_columns=True, query=query).query
        == query
    )
    with pytest.raises(AppError, match="Compact"):
        ResourceSelection("pods", server_columns=True, query=query)
