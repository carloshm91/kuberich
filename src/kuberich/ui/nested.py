"""Shared command bar for captured workspaces through an explicit command port."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.domain.interactions import CommandHistory
from kuberich.ui.commands import CommandInput


@dataclass(frozen=True)
class NestedCommands:
    suggestions: Callable[[str], tuple[str, ...]]
    history: CommandHistory
    route: Callable[[CommandWorkspace, str], None]


class CommandWorkspace(ModalScreen[None]):
    command_input: CommandInput | None = None

    def command_bar(self) -> ComposeResult:
        # Standalone screens can omit the root workspace's command capabilities.
        commands = getattr(self.app, "nested_commands", None)
        if not isinstance(commands, NestedCommands):
            return
        previous = self.AUTO_FOCUS

        def focus_view() -> None:
            if isinstance(previous, str):
                self.set_focus(self.query_one(previous))

        self.command_input = CommandInput(
            commands.suggestions,
            focus_view,
            lambda value: commands.route(self, value),
            id="view-command",
            history=commands.history,
        )
        with Horizontal(classes="input-bar nested-command-bar"):
            yield Static(":", classes="input-label", markup=False)
            yield self.command_input

    def focus_command(self) -> None:
        if self.command_input is not None:
            self.set_focus(self.command_input)

    def leave_command(self) -> bool:
        if self.command_input is not None and self.focused is self.command_input:
            self.command_input.value = ""
            self.command_input.focus_table()
            return True
        return False
