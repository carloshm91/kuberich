"""Resolved variants retain literal scoped arguments and explicit plugin trust flow."""

import pytest

from kuberich.domain.interactions import InteractionCommand
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.command_catalog import BoundCommands
from kuberich.services.commands import CommandService, GenericResourceCommand, ResourceCommand
from kuberich.ui.command_routing import CommandRouter


class Routes:
    def __init__(self, *, readonly=False):
        self.calls, self.refused = [], []
        self.generic_mode = False
        self.policy = AccessPolicy(readonly)
        self.commands = CommandService(self.policy)
        self.router = CommandRouter(
            BoundCommands(
                self.policy,
                {
                    "scale": lambda value: self.calls.append(("scale", value)),
                    "contexts": lambda value: self.calls.append(("contexts", value)),
                    "pods": lambda value: self.calls.append(("pods", value)),
                    "download": lambda value: self.calls.append(("download", value)),
                    "status": lambda value: self.calls.append(("status", value)),
                },
            ),
            lambda command: self.calls.append(("interaction", command)),
            lambda name: self.calls.append(("classify-plugin", name)),
            lambda command: self.calls.append(("resource", command)),
            lambda command: self.calls.append(("generic", command)),
            lambda: self.generic_mode,
            self.refused.append,
        )

    def run(self, text):
        self.router.apply(self.commands.resolve(text))


def test_root_router_preserves_all_canonical_variants_and_scoped_handler_arguments():
    routes = Routes()
    for text in (
        "wide",
        "plugin owned",
        "deploy team",
        "resource widgets.owned.example.test/v2 *",
        "scale 3",
        "ctx owned",
        "status",
    ):
        routes.run(text)
    assert routes.calls == [
        ("interaction", InteractionCommand("wide")),
        ("classify-plugin", "owned"),
        ("resource", ResourceCommand(RESOURCE_ALIASES["deploy"], "team")),
        ("generic", GenericResourceCommand("widgets", "owned.example.test", "v2", "*")),
        ("scale", "3"),
        ("contexts", "owned"),
        ("status", None),
    ]
    assert routes.refused == []


def test_generic_refusal_uses_the_same_catalog_and_does_not_block_navigation_or_classification():
    routes = Routes()
    routes.generic_mode = True
    routes.run("download")
    routes.run("scale 3")
    assert routes.calls == []
    assert routes.refused == ["Generic resources are read-only in this checkpoint."] * 2
    routes.run("ctx owned")
    routes.run("pods team")
    routes.run("plugin owned")
    assert routes.calls[0] == ("contexts", "owned")
    assert routes.calls[1] == ("pods", "team")
    assert routes.calls[-1] == ("classify-plugin", "owned")
    routes.generic_mode = False
    routes.run("download")
    assert routes.calls[-1] == ("download", None)


def test_parser_and_dispatch_keep_read_only_refusal_before_a_handler_and_plugin_preparation():
    routes = Routes(readonly=True)
    with pytest.raises(AppError, match="Read-only mode blocks"):
        routes.run("scale 3")
    assert routes.calls == []
    routes.run("download")
    routes.run("plugin trusted-review")
    assert routes.calls == [("download", None), ("classify-plugin", "trusted-review")]
    # Classification is the only callback. This router never grants trust,
    # launches a process, or substitutes an argv value into shell syntax.
