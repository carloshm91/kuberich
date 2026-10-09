"""Discovered resource grammar preserves qualification and advertised scope."""

from dataclasses import replace

import pytest

from kuberich.domain.resources import Discovery
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import (
    Command,
    CommandService,
    GenericResourceCommand,
    ScopedCommand,
    generic_command,
    resource_candidates,
    suggestions,
)
from tests.support.tables import custom_resource


def catalogue(*, ambiguous=False):
    preferred = custom_resource()
    return Discovery(
        (
            preferred,
            replace(preferred, version="v1beta1"),
            replace(custom_resource(name="gadgets", namespaced=False), aliases=("gdt",)),
            *((replace(preferred, group="other.example.test"),) if ambiguous else ()),
        )
    )


def test_aliases_versions_qualified_names_and_scope_preserve_requested_identity():
    service = CommandService(AccessPolicy(True))
    discovery = catalogue()
    assert service.resolve("wdg team", discovery) == GenericResourceCommand(
        "widgets", "owned.example.test", None, "team"
    )
    assert service.resolve(
        "widgets.owned.example.test/v1beta1 *", discovery
    ) == GenericResourceCommand("widgets", "owned.example.test", "v1beta1", "*")
    assert service.resolve(
        "resource widgets.owned.example.test/v1beta1 *"
    ) == GenericResourceCommand("widgets", "owned.example.test", "v1beta1", "*")
    assert service.resolve("widgets.owned.example.test") == GenericResourceCommand(
        "widgets", "owned.example.test"
    )
    assert generic_command("widgets/v1") == GenericResourceCommand("widgets", version="v1")
    assert generic_command("pods.core/v1") == GenericResourceCommand("pods", "", "v1")
    assert service.resolve("resource widgets", discovery).group == "owned.example.test"
    assert service.resolve("gadgets", discovery).name == "gadgets"
    assert service.resolve("columns c2 c3") == ScopedCommand(Command.COLUMNS, "c2 c3")


@pytest.mark.parametrize(
    "text",
    [
        "resource",
        "resource a b c",
        "widgets.bad/",
        "widgets./v1",
        "widgets/v1/x",
        "resource Bad",
        "resource widgets Upper",
    ],
)
def test_invalid_generic_syntax_is_rejected_before_transport(text):
    with pytest.raises(AppError):
        CommandService(AccessPolicy(True)).resolve(text)


def test_unknown_ambiguous_cluster_scope_and_explicit_missing_version_do_not_guess():
    service = CommandService(AccessPolicy(False))
    for text, match in (
        ("wdg", "ambiguous"),
        ("widgets", "ambiguous"),
        ("widgets.owned.example.test/v9", "not discovered"),
        ("gadgets team", "cluster-scoped"),
        ("unknown", "not discovered"),
    ):
        with pytest.raises(AppError, match=match):
            service.resolve(text, catalogue(ambiguous=True))
    assert service.resolve("unknown") is Command.UNAVAILABLE


def test_completions_hide_ambiguous_aliases_show_qualified_versions_and_scope():
    assert resource_candidates(None) == ()
    values = resource_candidates(catalogue(ambiguous=True))
    assert "wdg" not in values and "widgets" not in values
    assert "widgets.owned.example.test/v1beta1" in values
    assert suggestions("widgets.owned", (), (), catalogue()) == (
        "widgets.owned.example.test",
        "widgets.owned.example.test/v1",
        "widgets.owned.example.test/v1beta1",
    )
    assert suggestions("resource wid", (), (), catalogue())
    assert suggestions("widgets.owned.example.test t", (), ("team",), catalogue()) == (
        "widgets.owned.example.test team",
    )
    assert suggestions("gadgets t", (), ("team",), catalogue()) == ()
    assert suggestions("missing t", (), ("team",), catalogue()) == ()


def test_builtin_aliases_win_and_explicit_resource_accesses_a_colliding_alias():
    discovery = Discovery((replace(custom_resource(), aliases=("help", "po", "svc")),))
    service = CommandService(AccessPolicy(True))
    assert service.resolve("help", discovery) is Command.HELP
    assert service.resolve("po", discovery) is Command.PODS
    assert service.resolve("svc", discovery).definition.name == "services"
    assert service.resolve("resource svc", discovery) == GenericResourceCommand(
        "widgets", "owned.example.test"
    )
