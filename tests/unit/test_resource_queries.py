"""Explicit server selectors cannot silently change local filtering or native payloads."""

from dataclasses import FrozenInstanceError, replace

import pytest

from kuberich.domain.navigation import NavigationState
from kuberich.domain.resource_queries import ResourceQuery, query_command
from kuberich.domain.resources import CollectionState, metadata_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ResourceSelection
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService, ScopedCommand, suggestions
from tests.support.resources import item, pod_resource
from tests.support.tables import custom_item, custom_resource


def test_query_is_immutable_and_encodes_only_explicit_server_selectors():
    empty = ResourceQuery()
    assert empty.empty and empty.parameters == {}
    query = ResourceQuery("app in (api,worker),!disabled", "metadata.name!=retired", True)
    assert not query.empty
    assert query.parameters == {
        "labelSelector": "app in (api,worker),!disabled",
        "fieldSelector": "metadata.name!=retired",
    }
    with pytest.raises(FrozenInstanceError):
        query.compact = False
    values = query.parameters
    values["labelSelector"] = "changed=true"
    assert query.label_selector == "app in (api,worker),!disabled"


@pytest.mark.parametrize("field", ["label_selector", "field_selector"])
@pytest.mark.parametrize("value", [False, 4, [], "", "x" * 257, "name=bad\nvalue", "x=one|two"])
def test_selector_boundaries_refuse_invalid_input_without_echoing_it(field, value):
    with pytest.raises(AppError) as error:
        ResourceQuery(**{field: value})
    assert "bad\nvalue" not in str(error.value)


@pytest.mark.parametrize("value", [None, 0, 1, "true", []])
def test_compact_mode_requires_an_explicit_boolean(value):
    with pytest.raises(AppError, match="explicitly"):
        ResourceQuery(compact=value)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("label app=api", ResourceQuery("app=api", "metadata.name=one")),
        ("field status.phase=Running", ResourceQuery("old=yes", "status.phase=Running")),
        ("clear", ResourceQuery()),
        ("compact", ResourceQuery("old=yes", "metadata.name=one", True)),
        ("full", ResourceQuery("old=yes", "metadata.name=one")),
    ],
)
def test_explicit_query_commands_preserve_the_other_selector_and_mode(text, expected):
    current = ResourceQuery("old=yes", "metadata.name=one")
    assert query_command(current, text) == expected
    command = CommandService(AccessPolicy(True)).resolve(":server " + text)
    assert command == ScopedCommand(Command.SERVER, text)
    assert current == ResourceQuery("old=yes", "metadata.name=one")
    assert query_command(replace(current, compact=True), "clear") == ResourceQuery(compact=True)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "label",
        "field",
        "clear extra",
        "full extra",
        "compact extra",
        "other",
        "field spec.private=x",
    ],
)
def test_unknown_or_incomplete_server_operations_fail_before_network(text):
    with pytest.raises(AppError):
        query_command(ResourceQuery(), text)
    if text:
        with pytest.raises(AppError):
            CommandService(AccessPolicy(True)).resolve("server " + text)


def test_server_help_and_suboperation_completion_do_not_need_a_cluster():
    assert CommandService(AccessPolicy(True)).resolve(":server") is Command.SERVER
    assert set(suggestions("server ", (), ())) == {
        "server label ",
        "server field ",
        "server clear",
        "server compact",
        "server full",
    }
    assert suggestions("server co", (), ()) == ("server compact",)


def test_query_identity_and_history_are_separate_from_the_local_query():
    query = ResourceQuery("app=api")
    first = ResourceScope(SessionIdentity("owned", 1), pod_resource(), "team")
    assert replace(first, query=query) != first
    selection = ResourceSelection(query=query)
    state = NavigationState("owned", "team", query="local needle", server_query=query)
    assert state.query == "local needle" and state.server_query == selection.query
    with pytest.raises(AppError, match="validated"):
        replace(first, query="raw")
    with pytest.raises(AppError, match="validated"):
        ResourceSelection(query={})


@pytest.mark.parametrize(
    "name,group,server",
    [("pods", "", True), ("services", "", True), ("deployments", "apps", False)],
)
def test_native_and_core_payloads_cannot_be_replaced_by_compact_metadata(name, group, server):
    with pytest.raises(AppError, match="full objects"):
        ResourceSelection(name, group, server_columns=server, query=ResourceQuery(compact=True))
    assert ResourceSelection(
        "widgets", "owned.example.test", server_columns=True, query=ResourceQuery(compact=True)
    ).query.compact


@pytest.mark.parametrize(
    "kwargs",
    [
        {"complete": 1},
        {"limited": 0},
        {"limited": True},
        {"pages": -1},
        {"pages": False},
        {"retained_bytes": -1},
        {"retained_bytes": 1.2},
    ],
)
def test_collection_state_requires_honest_complete_and_bounded_counts(kwargs):
    with pytest.raises(AppError):
        CollectionState(**kwargs)
    assert CollectionState() == CollectionState(True, False, 0, 0)
    assert CollectionState(False, True, 3, 100).limited


def test_partial_metadata_keeps_real_type_identity_and_independent_bytes():
    source = custom_item()
    partial = {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "PartialObjectMetadata",
        "metadata": source["metadata"],
    }
    record = metadata_record(custom_resource(), partial, "team")
    assert record.metadata_only and record.uid == "owned-one"
    assert record.manifest == partial and "spec" not in record.manifest
    partial["metadata"]["name"] = "changed"
    assert record.manifest["metadata"]["name"] == "one"


@pytest.mark.parametrize("change", ["version", "kind", "extra", "scope", "identity"])
def test_partial_metadata_never_masquerades_as_a_full_or_different_target(change):
    partial = {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "PartialObjectMetadata",
        "metadata": item()["metadata"],
    }
    if change == "version":
        partial["apiVersion"] = "meta.k8s.io/v1beta1"
    elif change == "kind":
        partial["kind"] = "Widget"
    elif change == "extra":
        partial["spec"] = {}
    elif change == "scope":
        partial["metadata"]["namespace"] = "other"
    else:
        partial["metadata"]["name"] = "bad/name"
    with pytest.raises(AppError):
        metadata_record(custom_resource(), partial, "team")
