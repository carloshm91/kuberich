"""Action availability rules for each workspace view."""

import pytest

from kuberich.domain.view_actions import TABLE_ACTIONS, ViewState, action_available
from kuberich.services.access import Action
from kuberich.services.command_catalog import COMMAND_SPECS


@pytest.mark.parametrize(
    "action,view,expected",
    [
        ("review_delete", ViewState("contexts"), True),
        ("review_delete", ViewState("namespaces"), False),
        ("review_delete", ViewState("widgets", generic=True), False),
        ("configuration_data", ViewState("secrets"), True),
        ("configuration_data", ViewState("pods"), False),
        ("configuration_data", ViewState("configmaps", generic=True), False),
        ("logs_all", ViewState("deployments"), True),
        ("logs_all", ViewState("services"), False),
        ("logs_all", ViewState("pods", generic=True), False),
        ("edit", ViewState("deployments"), True),
        ("edit", ViewState("widgets", generic=True), False),
        ("port_forward", ViewState("services"), True),
        ("port_forward", ViewState("deployments"), False),
        ("shell", ViewState("pods"), True),
        ("shell", ViewState("deployments"), False),
        ("quit", ViewState("pods", modal=True, typing=True), True),
        ("metric_history", ViewState("pods"), True),
        ("metric_history", ViewState("nodes"), True),
        ("metric_history", ViewState("deployments", generic=True), True),
        ("metric_history", ViewState("pulse"), True),
        ("metric_history", ViewState("pods", typing=True), False),
        ("metric_history", ViewState("nodes", modal=True), False),
        ("metric_history", ViewState("services"), False),
    ],
)
def test_actions_follow_the_current_view(action, view, expected):
    assert action_available(action, view) is expected


@pytest.mark.parametrize(
    "action", sorted(TABLE_ACTIONS - {"configuration_data", "port_forward", "open_relationship"})
)
def test_table_actions_pause_while_a_modal_or_input_has_focus(action):
    assert action_available(action, ViewState("pods"))
    assert not action_available(action, ViewState("pods", modal=True))
    assert not action_available(action, ViewState("pods", typing=True))


@pytest.mark.parametrize("action", sorted(TABLE_ACTIONS | {"views", "retry"}))
def test_pulse_exposes_navigation_without_resource_operations(action):
    allowed = action in {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "retry",
    }
    assert action_available(action, ViewState("pulse")) is allowed


@pytest.mark.parametrize("action", sorted(TABLE_ACTIONS | {"views", "retry"}))
def test_relationships_expose_explicit_open_and_graph_navigation_without_resource_operations(
    action,
):
    allowed = action in {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "xray",
        "usedby",
        "open_relationship",
        "retry",
    }
    assert action_available(action, ViewState("relationships")) is allowed


@pytest.mark.parametrize("resource", ["relationships", "pulse", "authorization"])
def test_every_declared_mutation_ui_action_is_unavailable_for_aggregate_rows(resource):
    actions = {
        spec.ui_action
        for spec in COMMAND_SPECS
        if spec.policy is Action.MUTATE and spec.ui_action is not None
    }
    assert {"annotate", "edit", "review_delete", "cleanup_pods"} <= actions
    for action in actions:
        assert not action_available(action, ViewState(resource))


@pytest.mark.parametrize("action", ["xray", "usedby", "open_relationship"])
def test_graph_actions_respect_modal_and_input_focus(action):
    assert action_available(action, ViewState("relationships"))
    assert not action_available(action, ViewState("relationships", modal=True))
    assert not action_available(action, ViewState("relationships", typing=True))


@pytest.mark.parametrize("resource", ["contexts", "pulse", "authorization"])
@pytest.mark.parametrize("action", ["xray", "usedby", "open_relationship"])
def test_graph_commands_do_not_capture_non_resource_source_views(resource, action):
    assert action_available(action, ViewState(resource)) is (
        resource == "authorization" and action == "open_relationship"
    )


@pytest.mark.parametrize("action", sorted(TABLE_ACTIONS | {"views", "retry"}))
def test_authorization_keeps_navigation_and_explicit_object_open_without_resource_effects(action):
    allowed = action in {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "open_relationship",
        "retry",
    }
    assert action_available(action, ViewState("authorization")) is allowed
    if action in TABLE_ACTIONS:
        assert not action_available(action, ViewState("authorization", modal=True))
        assert not action_available(action, ViewState("authorization", typing=True))
