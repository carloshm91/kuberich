"""Service-level guards cannot be bypassed by avoiding a UI shortcut."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.commands import Command, CommandService, ScopedCommand


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
        "scale 3",
        "restart",
        "rollback 1",
        "apply file",
        "patch pod",
    ],
)
def test_command_service_guard_is_independent_of_widgets(text: str) -> None:
    with pytest.raises(AppError, match="Read-only mode blocks"):
        CommandService(AccessPolicy(True)).resolve(text)
    expected = {
        "shell": Command.SHELL,
        "restart": Command.RESTART,
        "scale 3": ScopedCommand(Command.SCALE, "3"),
        "rollback 1": ScopedCommand(Command.ROLLBACK, "1"),
    }.get(text, Command.UNAVAILABLE)
    assert CommandService(AccessPolicy(False)).resolve(text) == expected


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
        ("rollout", Command.ROLLOUT),
        (":ROLLOUT", Command.ROLLOUT),
        ("rollout deploy", Command.UNAVAILABLE),
    ],
)
def test_available_commands_work_in_readonly_mode(text: str, expected: Command) -> None:
    assert CommandService(AccessPolicy(True)).resolve(text) is expected


@pytest.mark.parametrize("argument", ["deploy", "-1", "1.5"])
def test_scale_invalid_input_is_rejected_before_any_widget_or_request(argument: str) -> None:
    with pytest.raises(AppError, match="Read-only mode blocks"):
        CommandService(AccessPolicy(True)).resolve("scale " + argument)
    with pytest.raises(AppError, match="ASCII integer"):
        CommandService(AccessPolicy(False)).resolve("scale " + argument)
