"""Action availability rules for each workspace view."""

import pytest

from kuberich.domain.view_actions import TABLE_ACTIONS, ViewState, action_available


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
    ],
)
def test_actions_follow_the_current_view(action, view, expected):
    assert action_available(action, view) is expected


@pytest.mark.parametrize("action", sorted(TABLE_ACTIONS - {"configuration_data", "port_forward"}))
def test_table_actions_pause_while_a_modal_or_input_has_focus(action):
    assert action_available(action, ViewState("pods"))
    assert not action_available(action, ViewState("pods", modal=True))
    assert not action_available(action, ViewState("pods", typing=True))
