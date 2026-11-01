"""Actual semantic bindings reject omissions before a user can dispatch input."""

import pytest

from kuberich.domain.commands import Command
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.ui.workspace_commands import bind_commands


@pytest.mark.parametrize("invalid", ["missing", "overlapping"])
def test_workspace_bindings_require_one_explicit_owner_per_command(invalid):
    no_arguments = {command: lambda: None for command in Command}
    arguments = {}
    if invalid == "missing":
        no_arguments.pop(Command.SCALE)
    else:
        arguments[Command.SCALE] = lambda value: None
    with pytest.raises(AppError, match="exactly one"):
        bind_commands(AccessPolicy(False), no_arguments, arguments)


def test_complete_bindings_preserve_scoped_values_and_refuse_before_the_callback():
    calls = []
    no_arguments = {command: lambda: calls.append("local") for command in Command}
    no_arguments.pop(Command.SCALE)
    arguments = {Command.SCALE: lambda value: calls.append(value)}
    bound = bind_commands(AccessPolicy(False), no_arguments, arguments)
    bound.dispatch(Command.HELP)
    bound.dispatch(Command.SCALE, "3")
    readonly = bind_commands(AccessPolicy(True), no_arguments, arguments)
    with pytest.raises(AppError, match="Read-only"):
        readonly.dispatch(Command.SCALE, "4")
    assert calls == ["local", "3"]
