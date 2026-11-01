"""Own root/nested command transitions through parser and declared handlers."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from textual.app import App

from kuberich.domain.aliases import Aliases
from kuberich.domain.interactions import InteractionCommand
from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.view_routes import ViewKind
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.command_catalog import COMMAND_CATALOG, BoundCommands
from kuberich.services.commands import (
    Command,
    GenericResourceCommand,
    ResolvedCommand,
    ResourceCommand,
    ScopedCommand,
    suggestions,
)
from kuberich.services.ownership import finish_owned
from kuberich.services.workspace import WorkspaceService
from kuberich.ui.command_routing import CommandRouter
from kuberich.ui.interactions import Interactions
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.root_views import RootViews
from kuberich.ui.workspace_navigation import WorkspaceNavigation


@dataclass(frozen=True)
class CompletionSources:
    contexts: tuple[str, ...]
    aliases: Aliases
    plugins: tuple[str, ...]
    jumps: tuple[str, ...]


def bind_commands(
    policy: AccessPolicy,
    no_arguments: Mapping[Command, Callable[[], None]],
    arguments: Mapping[Command, Callable[[str | None], None]],
) -> BoundCommands:
    """Require one explicit implementation for each declared semantic command."""
    if no_arguments.keys() & arguments.keys() or no_arguments.keys() | arguments.keys() != set(
        Command
    ):
        raise AppError("Every local command must have exactly one bound implementation.")

    def ignore_argument(callback: Callable[[], None]) -> Callable[[str | None], None]:
        def invoke(argument: str | None) -> None:
            callback()

        return invoke

    handlers = {
        COMMAND_CATALOG.by_command[command].handler: ignore_argument(callback)
        for command, callback in no_arguments.items()
    }
    handlers.update(
        {
            COMMAND_CATALOG.by_command[command].handler: callback
            for command, callback in arguments.items()
        }
    )
    return BoundCommands(policy, handlers)


class WorkspaceCommands:
    def __init__(
        self,
        host: App[None],
        resolve: Callable[[str], ResolvedCommand],
        workspace: WorkspaceService,
        navigator: WorkspaceNavigation,
        views: RootViews,
        interactions: Interactions,
        bound: BoundCommands,
        plugin: Callable[[str], None],
        sources: Callable[[], CompletionSources],
    ) -> None:
        self.host, self.resolve, self.workspace = host, resolve, workspace
        self.navigator, self.views, self.interactions = navigator, views, interactions
        self.sources = sources
        self.router = CommandRouter(
            bound,
            interactions.apply,
            plugin,
            self.resource,
            navigator.generic,
            lambda: views.route.kind is ViewKind.CUSTOM,
            navigator.command_error,
        )
        self._transition: asyncio.Task[None] | None = None

    def apply(self, command: ResolvedCommand) -> None:
        try:
            self.router.apply(command)
        except AppError as error:
            self.navigator.command_error(str(error))

    def resource(self, command: ResourceCommand) -> None:
        scope = (
            NamespaceChoice(None if command.scope == "*" else command.scope)
            if command.scope is not None
            else None
        )
        self.navigator.select_resource(command.definition.name, scope=scope)

    def suggestions(self, value: str) -> tuple[str, ...]:
        sources = self.sources()
        return suggestions(
            value,
            sources.contexts,
            self.navigator.namespace_choices(),
            self.workspace.discovery,
            sources.aliases,
            sources.plugins,
            sources.jumps,
        )

    async def close(self) -> None:
        if self._transition is not None:
            if not self._transition.done() and not self._transition.cancelling():
                self._transition.cancel()
            await finish_owned(asyncio.gather(self._transition, return_exceptions=True))

    def submit(self, value: str, *, repeat: bool = False) -> None:
        self.navigator.clear_column_notice()
        try:
            command = self.resolve(value)
        except AppError as error:
            self.navigator.command_error(str(error))
            return
        if (
            not repeat
            and command is not Command.UNAVAILABLE
            and not (isinstance(command, InteractionCommand) and command.verb == "!!")
        ):
            self.interactions.history.record(value)
        self.apply(command)

    def route(self, origin: CommandWorkspace, value: str) -> None:
        from kuberich.ui.containers import ContainerScreen
        from kuberich.ui.inspection import InspectionScreen
        from kuberich.ui.logs import LogScreen

        if self._transition is not None and not self._transition.done():
            self.host.notify("A workspace transition is already in progress.")
            return
        try:
            command = self.resolve(value)
            if isinstance(command, InteractionCommand) and command.verb == "!!":
                value = self.interactions.history.repeat()
                command = self.resolve(value)
            if command is Command.EMPTY or command is Command.UNAVAILABLE:
                if command is Command.UNAVAILABLE:
                    self.host.notify("Command is unavailable; the current view is retained.")
                return
        except AppError as error:
            self.host.notify(str(error), severity="error")
            return
        if isinstance(command, InteractionCommand) and command.verb in {
            "headless",
            "crumbsless",
            "fullscreen",
            "favorite",
        }:
            self.interactions.apply(command)
            self.interactions.history.record(value)
            return
        if isinstance(command, InteractionCommand) and command.verb in {
            "copy",
            "copyns",
            "copytext",
        }:
            try:
                source = (
                    origin.service
                    if isinstance(origin, InspectionScreen)
                    else origin.stream
                    if isinstance(origin, (ContainerScreen, LogScreen))
                    else None
                )
                if source is None:
                    raise AppError("This view has no captured resource to copy.")
                source.require_current()
                if command.verb == "copytext" and isinstance(origin, (InspectionScreen, LogScreen)):
                    origin.action_copy()
                else:
                    self.host.copy_to_clipboard(
                        (source.target.namespace or "")
                        if command.verb == "copyns"
                        else source.target.name
                    )
                self.interactions.history.record(value)
            except AppError as error:
                self.host.notify(str(error), severity="error")
            return
        self._transition = asyncio.create_task(self._navigate(origin, command, value))

    async def _navigate(
        self, origin: CommandWorkspace, command: ResolvedCommand, value: str
    ) -> None:
        from kuberich.ui.containers import ContainerScreen
        from kuberich.ui.inspection import InspectionScreen
        from kuberich.ui.logs import LogScreen

        source = (
            origin.service
            if isinstance(origin, InspectionScreen)
            else origin.stream
            if isinstance(origin, (ContainerScreen, LogScreen))
            else None
        )
        local = {
            Command.HELP,
            Command.THEMES,
            Command.ABOUT,
            Command.VIEWS,
            Command.PLUGINS,
            Command.PLUGIN_JOBS,
            Command.STATUS,
            Command.PORT_FORWARDS,
            Command.WRITES,
        }
        navigation = {
            Command.CONTEXTS,
            Command.NAMESPACES,
            Command.PODS,
            Command.BACK,
            Command.FORWARD,
            Command.QUIT,
            Command.RETRY,
            Command.LOGIN,
            Command.REFRESH,
        }
        action = command.command if isinstance(command, ScopedCommand) else command
        requires_target = (
            not isinstance(command, (ResourceCommand, GenericResourceCommand, InteractionCommand))
            and action not in local | navigation
        )
        try:
            if requires_target:
                if source is None:
                    raise AppError("This command requires a captured resource view.")
                source.require_current()
            if command is Command.BACK:
                await origin.dismiss()
                self.interactions.history.record(value)
                return
            # Drain covered owners before changing namespace/context or targeting a root action.
            for screen in reversed(tuple(self.host.screen_stack[1:])):
                if not isinstance(screen, CommandWorkspace):
                    raise AppError(
                        "Close the current review before navigating to another workspace."
                    )
                if isinstance(screen, (ContainerScreen, LogScreen, InspectionScreen)):
                    await screen.stop_owned()
            if requires_target and source is not None:
                source.require_current()
            for screen in reversed(tuple(self.host.screen_stack[1:])):
                await screen.dismiss()
            if requires_target and source is not None:
                table = self.views.table
                if source.target.uid not in table.rows:
                    raise AppError("The captured resource is no longer visible; select it again.")
                table.move_cursor(row=table.get_row_index(source.target.uid), scroll=False)
            self.interactions.history.record(value)
            self.apply(command)
        except AppError as error:
            self.host.notify(str(error), severity="error")
