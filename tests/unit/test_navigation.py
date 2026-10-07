"""Actual command grammar, local completions and bounded reversible history."""

import pytest

from kubetrol.domain.navigation import (
    MAX_HISTORY,
    ContextRow,
    NamespaceChoice,
    NavigationHistory,
    NavigationState,
)
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.commands import ALIASES, Command, CommandService, ScopedCommand, suggestions


@pytest.mark.parametrize("current, marker", [(False, ""), (True, "*")])
def test_local_context_row_is_exact_case_preserving_configuration(current, marker):
    row = ContextRow("Team Production", "Cluster", "auth", "team", current)
    assert row.cells() == (marker, "Team Production", "Cluster", "auth", "team")


@pytest.mark.parametrize("alias,command", ALIASES.items())
def test_aliases_share_one_readonly_initial_and_interactive_parser(alias, command):
    text = " :" + alias.upper() + " "
    assert CommandService(AccessPolicy(False)).resolve(text) is command
    service = CommandService(AccessPolicy(True))
    if command is Command.SHELL:
        with pytest.raises(AppError, match="Read-only"):
            service.resolve(text)
    else:
        assert service.resolve(text) is command


@pytest.mark.parametrize("alias", ["po", "pod", "pods", "ns", "namespace", "namespaces"])
@pytest.mark.parametrize("argument", ["team", "*"])
def test_resource_scope_arguments_are_validated_and_preserved(alias, argument):
    resolved = CommandService(AccessPolicy(True)).resolve(alias + " " + argument)
    assert isinstance(resolved, ScopedCommand)
    assert resolved.argument == argument and resolved.command is ALIASES[alias]


def test_context_case_and_spaces_are_preserved_and_invalid_arguments_are_rejected():
    service = CommandService(AccessPolicy(False))
    assert service.resolve("CTX Production Team") == ScopedCommand(
        Command.CONTEXTS, "Production Team"
    )
    for value in ["ns Upper", "po -team", "ctx bad\x1bvalue"]:
        with pytest.raises(AppError):
            service.resolve(value)
    assert service.resolve("unknown extra") is Command.UNAVAILABLE


def test_completions_are_literal_bounded_case_preserving_and_deduplicated():
    assert suggestions("c", (), ()) == ("context", "contexts", "ctx")
    assert suggestions("ct", (), ()) == ("ctx",)
    assert suggestions(":ctx p", ("Production", "prod[red]", "Production"), ()) == (
        "ctx prod[red]",
        "ctx Production",
    )
    assert suggestions("CTX p", ("Production Team",), ()) == ("CTX Production Team",)
    assert suggestions("ctx Production Team", ("Production Team",), ()) == ()
    assert suggestions("ns t", (), ("team", "team-blue")) == ("ns team", "ns team-blue")
    assert suggestions("po *", (), ("*",)) == ()
    assert suggestions("ns ", (), ()) == ()
    assert suggestions("help ", (), ()) == ()
    assert suggestions("not-real", (), ()) == ()
    assert len(suggestions("", (), ())) == 8
    assert len(suggestions("ctx ", tuple(f"team-{i:02}" for i in range(30)), ())) == 8
    assert suggestions("ctx ", ("x" * 300,), ()) == ()


def test_navigation_restores_full_immutable_state_and_drops_forward_on_new_visit():
    history = NavigationHistory()
    a, b, c = (NavigationState(name, "team", query=name, selected="uid" + name) for name in "abc")
    assert history.move(a) is None and history.move(a, forward=True) is None
    history.visit(a)
    history.visit(a)
    assert history.previous == [a]
    history.visit(b)
    assert history.move(c) == b
    assert history.move(b) == a
    assert history.move(a, forward=True) == b
    assert history.move(b, forward=True) == c
    assert history.move(c, forward=True) is None
    history.move(c)
    history.visit(c)
    assert not history.following


def test_history_memory_is_bounded_in_both_directions_and_scope_validates():
    history = NavigationHistory()
    for i in range(MAX_HISTORY * 3):
        history.visit(NavigationState(str(i), None))
    assert len(history.previous) == MAX_HISTORY
    for _i in range(MAX_HISTORY):
        assert history.move(NavigationState("now", "team")) is not None
    assert len(history.following) == MAX_HISTORY
    assert NamespaceChoice(None).namespace is None
    assert NamespaceChoice("team").namespace == "team"
    with pytest.raises(AppError):
        NamespaceChoice("Uppercase")
