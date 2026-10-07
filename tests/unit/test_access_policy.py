"""Service-level guards cannot be bypassed by avoiding a UI shortcut."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy, Action
from kubetrol.services.commands import Command, CommandService


@pytest.mark.parametrize("action", list(Action))
def test_readonly_guard_allows_inspection_and_refuses_every_other_action(action: Action) -> None:
    policy = AccessPolicy(True)
    if action is Action.READ:
        policy.require(action)
    else:
        with pytest.raises(AppError, match="Read-only mode blocks"):
            policy.require(action)


@pytest.mark.parametrize("action", list(Action))
def test_write_preference_does_not_block_actions_or_grant_api_permissions(action: Action) -> None:
    AccessPolicy(False).require(action)


@pytest.mark.parametrize("value", [None, "true", 1])
def test_policy_rejects_unvalidated_values(value: Any) -> None:
    with pytest.raises(AppError, match="must be true or false"):
        AccessPolicy(value)


@pytest.mark.parametrize("value", [None, "READ", 1])
def test_unknown_action_is_fail_closed_even_in_write_mode(value: Any) -> None:
    with pytest.raises(AppError, match="operation refused"):
        AccessPolicy(False).require(value)


def test_readonly_cannot_be_changed_mid_action() -> None:
    policy = AccessPolicy(True)
    with pytest.raises(FrozenInstanceError):
        policy.read_only = False  # type: ignore[misc]


@pytest.mark.parametrize(
    "text",
    [
        "exec pod",
        "shell",
        "ssh",
        "attach pod",
        "plugin local",
        "delete pod",
        "edit pod",
        "scale deploy",
        "rollout deploy",
        "apply file",
        "patch pod",
    ],
)
def test_command_service_guard_is_independent_of_widgets(text: str) -> None:
    with pytest.raises(AppError, match="Read-only mode blocks"):
        CommandService(AccessPolicy(True)).resolve(text)
    expected = Command.SHELL if text == "shell" else Command.UNAVAILABLE
    assert CommandService(AccessPolicy(False)).resolve(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", Command.EMPTY),
        (" ", Command.EMPTY),
        ("help", Command.HELP),
        (":HELP", Command.HELP),
        ("?", Command.HELP),
        ("quit", Command.QUIT),
        ("q", Command.QUIT),
        ("exit", Command.QUIT),
        ("help extra", Command.UNAVAILABLE),
        ("pods", Command.PODS),
        (":login", Command.LOGIN),
    ],
)
def test_available_commands_work_in_readonly_mode(text: str, expected: Command) -> None:
    assert CommandService(AccessPolicy(True)).resolve(text) is expected
