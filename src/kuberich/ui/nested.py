"""Shared command bar for captured read-only workspaces, without shell interception."""

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.ui.commands import CommandInput

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp


class CommandWorkspace(ModalScreen[None]):
    command_input: CommandInput | None = None

    def command_bar(self) -> ComposeResult:
        # Standalone widget harnesses do not own the application's command service.
        if not hasattr(self.app, "_suggestions"):
            return
        app = cast("KubeRichApp", self.app)
        previous = self.AUTO_FOCUS

        def focus_view() -> None:
            if isinstance(previous, str):
                self.set_focus(self.query_one(previous))

        self.command_input = CommandInput(
            app._suggestions,
            focus_view,
            lambda value: app.route_nested(self, value),
            id="view-command",
            history=app.interactions.history,
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
