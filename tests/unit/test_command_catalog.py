"""Declared handlers and documentation retain the existing parser/access boundary."""

from dataclasses import replace

import pytest

from kuberich.domain.commands import Command as DomainCommand
from kuberich.domain.view_actions import ViewState
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.command_catalog import (
    COMMAND_CATALOG,
    COMMAND_SPECS,
    BoundCommands,
    Capability,
    CommandCatalog,
)
from kuberich.services.commands import ALIASES, Command, CommandService, PluginCommand, suggestions


def test_catalog_drives_existing_aliases_help_and_binding_policy_without_advertising_stubs():
    assert DomainCommand is Command
    assert dict(COMMAND_CATALOG.aliases) == ALIASES
    assert set(COMMAND_CATALOG.by_command) == set(Command)
    rows = COMMAND_CATALOG.help_rows()
    assert ("shell / exec", "Choose a pod container and open its shell.") in rows
    assert {alias for names, _ in rows for alias in names.split(" / ")} == set(ALIASES)
    assert not {"ssh", "apply", "patch", "plugin"} & set(ALIASES)
    assert "context" in suggestions(":c", (), ())
    assert not COMMAND_CATALOG.available("shell", ViewState("services"))
    assert COMMAND_CATALOG.available("shell", ViewState("pods"))
    assert not COMMAND_CATALOG.available("edit", ViewState("widgets.example.test", generic=True))
    assert COMMAND_CATALOG.by_command[Command.SHELL].capabilities == frozenset({Capability.POD})
    assert not COMMAND_CATALOG.by_command[Command.DOWNLOAD].generic_allowed


@pytest.mark.parametrize(
    "verb", ["ssh", "apply", "patch", "plugin", "shell", "exec", "upload", "rename", "cleanup"]
)
def test_reserved_or_implemented_unsafe_commands_still_refuse_before_parsing_or_dispatch(verb):
    with pytest.raises(AppError, match="Read-only mode blocks"):
        CommandService(AccessPolicy(True)).resolve(verb)
    with pytest.raises(AppError, match="Read-only mode blocks"):
        AccessPolicy(True).require(COMMAND_CATALOG.policy_for(verb.upper()))


def test_read_only_plugin_manifest_classification_remains_after_parsing_and_before_execution():
    service = CommandService(AccessPolicy(True))
    assert service.resolve("plugin owned") == PluginCommand("owned")
    assert service.resolve("download") is Command.DOWNLOAD
    assert COMMAND_CATALOG.by_command[Command.DOWNLOAD].read_only_allowed
    assert not COMMAND_CATALOG.by_command[Command.UPLOAD].read_only_allowed


def test_bound_handlers_preserve_scoped_argument_and_refuse_before_handler_lookup():
    captured = []
    handlers = {"scale": lambda argument: captured.append(argument)}
    bound = BoundCommands(AccessPolicy(False), handlers)
    handlers.clear()
    resolved = CommandService(bound.policy).resolve("scale 3")
    bound.dispatch(resolved.command, resolved.argument)
    assert captured == ["3"]
    readonly = BoundCommands(AccessPolicy(True), {})
    with pytest.raises(AppError, match="Read-only mode blocks"):
        readonly.dispatch(Command.SCALE, "4")
    assert captured == ["3"]


@pytest.mark.parametrize(
    "problem", ["missing", "duplicate", "alias", "reserved", "handler", "help"]
)
def test_catalog_refuses_a_declaration_that_could_desynchronize_policy_help_or_dispatch(problem):
    specs = list(COMMAND_SPECS)
    if problem == "missing":
        specs.pop()
    elif problem == "duplicate":
        specs[-1] = specs[0]
    elif problem == "alias":
        specs[0] = replace(specs[0], aliases=("delete",))
    elif problem == "reserved":
        specs[0] = replace(specs[0], aliases=("apply",))
    else:
        specs[0] = replace(specs[0], **{problem: ""})
    with pytest.raises(AppError):
        CommandCatalog(tuple(specs))
