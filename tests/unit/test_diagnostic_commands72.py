"""Strict diagnostics grammar, local completion and declared read-only handler policy."""

import pytest

from kuberich.domain.aliases import parse_aliases
from kuberich.domain.commands import Command
from kuberich.domain.resources import Discovery
from kuberich.domain.view_actions import ViewState
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.command_catalog import COMMAND_CATALOG, BoundCommands, Capability
from kuberich.services.commands import (
    RESERVED_COMMANDS,
    CommandService,
    GenericResourceCommand,
    ScopedCommand,
    suggestions,
)
from tests.support.tables import custom_resource


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize(
    "text,expected",
    [
        ("diagnostics", Command.DIAGNOSTICS),
        (":diagnostics", Command.DIAGNOSTICS),
        (" :DIAGNOSTICS ", Command.DIAGNOSTICS),
        ("diagnose", Command.DIAGNOSE),
        (":DIAGNOSE", Command.DIAGNOSE),
        ("popeye", Command.POPEYE),
        (":POPEYE", Command.POPEYE),
        (":diagnostics cancel", ScopedCommand(Command.DIAGNOSTICS, "cancel")),
        (":DIAGNOSTICS cancel", ScopedCommand(Command.DIAGNOSTICS, "cancel")),
        ("diagnostics   cancel", ScopedCommand(Command.DIAGNOSTICS, "cancel")),
    ],
)
def test_exact_readonly_commands_capture_only_the_requested_diagnostic_operation(
    text, expected, read_only
):
    assert CommandService(AccessPolicy(read_only)).resolve(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "diagnostics CANCEL",
        "diagnostics stop",
        "diagnostics cancel extra",
        "diagnostics *",
        "diagnostics team",
        "diagnostics --namespace=team",
        "diagnostics cancel;popeye",
        "diagnostics cancel\x1b",
        "diagnose one",
        "diagnose team/one",
        "diagnose --namespace team",
        "popeye team",
        "popeye --all-namespaces",
        "popeye run",
        "popeye ;",
    ],
)
def test_extra_arguments_are_usage_errors_before_any_transport_or_tool(text):
    with pytest.raises(AppError, match="Use :"):
        CommandService(AccessPolicy(True)).resolve(text)


@pytest.mark.parametrize(
    "text", ["diagnostic", "diagnostics-cancel", "diagnoses", "popey", "diag", "diagnose;popeye"]
)
def test_undeclared_spellings_or_shell_like_input_do_not_become_diagnostic_aliases(text):
    assert CommandService(AccessPolicy(True)).resolve(text) is Command.UNAVAILABLE


@pytest.mark.parametrize(
    "text,expected",
    [
        ("diagnostics ", ("diagnostics cancel",)),
        (":diagnostics c", ("diagnostics cancel",)),
        ("DIAGNOSTICS C", ("DIAGNOSTICS cancel",)),
        ("diagnostics cancel", ()),
        ("diagnostics cancel ", ()),
        ("diagnostics c extra", ()),
        ("diagnose ", ()),
        ("popeye ", ()),
    ],
)
def test_cancel_completion_is_literal_local_and_has_no_scope_or_tool_options(text, expected):
    assert suggestions(text, ("Owned Context",), ("team", "*")) == expected


def test_aliases_preserve_command_grammar_and_cannot_replace_new_builtin_names():
    aliases = parse_aliases(
        {
            "inspect-failures": "diagnostics",
            "stop-scan": "diagnostics cancel",
            "external-report": "popeye",
        },
        RESERVED_COMMANDS,
    )
    parser = CommandService(AccessPolicy(True), aliases)
    assert parser.resolve("inspect-failures cancel") == ScopedCommand(Command.DIAGNOSTICS, "cancel")
    assert parser.resolve("stop-scan") == ScopedCommand(Command.DIAGNOSTICS, "cancel")
    assert parser.resolve("external-report") is Command.POPEYE
    with pytest.raises(AppError, match="already supplies arguments"):
        parser.resolve("stop-scan cancel")
    assert suggestions("inspect-failures c", (), (), aliases=aliases) == (
        "inspect-failures cancel",
    )
    assert suggestions("stop-scan c", (), (), aliases=aliases) == ()
    for name in ["diagnostics", "diagnose", "popeye"]:
        with pytest.raises(AppError, match="cannot replace"):
            parse_aliases({name: "help"}, RESERVED_COMMANDS)


def test_builtin_diagnostics_wins_over_discovered_alias_but_explicit_resource_remains_available():
    resource = custom_resource()
    from dataclasses import replace

    discovery = Discovery((replace(resource, aliases=("diagnostics", "diagnose", "popeye")),))
    parser = CommandService(AccessPolicy(True))
    for alias, command in [
        ("diagnostics", Command.DIAGNOSTICS),
        ("diagnose", Command.DIAGNOSE),
        ("popeye", Command.POPEYE),
    ]:
        assert parser.resolve(alias, discovery) is command
        assert parser.resolve("resource " + alias, discovery) == GenericResourceCommand(
            resource.name, resource.group
        )


def test_catalog_enrolls_help_policy_capability_and_declared_handlers_for_each_operation():
    captured = []
    handlers = {
        name: lambda argument, name=name: captured.append((name, argument))
        for name in ["diagnostics", "diagnose", "popeye"]
    }
    bound = BoundCommands(AccessPolicy(True), handlers)
    for command in [Command.DIAGNOSTICS, Command.DIAGNOSE, Command.POPEYE]:
        spec = COMMAND_CATALOG.by_command[command]
        assert spec.handler == command.name.lower()
        assert spec.policy is Action.READ and spec.read_only_allowed
        assert spec.aliases == (spec.handler,)
        assert any(
            names == spec.handler and help_text == spec.help
            for names, help_text in COMMAND_CATALOG.help_rows()
        )
        assert COMMAND_CATALOG.policy_for(spec.handler.upper()) is Action.READ
        bound.dispatch(command, "cancel" if command is Command.DIAGNOSTICS else None)
    assert captured == [("diagnostics", "cancel"), ("diagnose", None), ("popeye", None)]
    diagnose = COMMAND_CATALOG.by_command[Command.DIAGNOSE]
    assert diagnose.capabilities == frozenset({Capability.WORKLOAD})
    assert diagnose.ui_action == "diagnose" and not diagnose.generic_allowed
    assert COMMAND_CATALOG.available("diagnose", ViewState("pods"))
    assert not COMMAND_CATALOG.available("diagnose", ViewState("diagnostics"))
    assert not COMMAND_CATALOG.available("diagnose", ViewState("widgets", generic=True))
