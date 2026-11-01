"""Dispatch resolved commands through declared handlers and narrow typed routes."""

from collections.abc import Callable

from kuberich.domain.interactions import InteractionCommand
from kuberich.services.command_catalog import BoundCommands
from kuberich.services.commands import (
    GenericResourceCommand,
    PluginCommand,
    ResolvedCommand,
    ResourceCommand,
    ScopedCommand,
)


class CommandRouter:
    def __init__(
        self,
        bound: BoundCommands,
        interaction: Callable[[InteractionCommand], None],
        plugin: Callable[[str], None],
        resource: Callable[[ResourceCommand], None],
        generic: Callable[[GenericResourceCommand], None],
        generic_mode: Callable[[], bool],
        refused: Callable[[str], None],
    ) -> None:
        self.bound, self.interaction, self.plugin = bound, interaction, plugin
        self.resource, self.generic = resource, generic
        self.generic_mode, self.refused = generic_mode, refused

    def apply(self, command: ResolvedCommand) -> None:
        # These variants retain their own canonical parsing and capture owners.
        # In particular, a named plugin is classified from its manifest before
        # any preparation; it is not reduced to the unsafe bare plugin verb.
        if isinstance(command, InteractionCommand):
            self.interaction(command)
        elif isinstance(command, PluginCommand):
            self.plugin(command.name)
        elif isinstance(command, GenericResourceCommand):
            self.generic(command)
        elif isinstance(command, ResourceCommand):
            self.resource(command)
        else:
            action = command.command if isinstance(command, ScopedCommand) else command
            spec = self.bound.catalog.by_command[action]
            if self.generic_mode() and not spec.generic_allowed:
                self.refused("Generic resources are read-only in this checkpoint.")
                return
            self.bound.dispatch(
                action, command.argument if isinstance(command, ScopedCommand) else None
            )
