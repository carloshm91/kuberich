"""Literal, scrollable selectors for context and namespace names."""

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from kuberich.security.presentation import safe_text


class ScopeScreen(ModalScreen[str]):
    AUTO_FOCUS = "#scope-options"
    DEFAULT_CSS = """
    ScopeScreen { align: center middle; }
    #scope-dialog { width: 80%; max-width: 90; height: 80%; border: round $accent; padding: 1; background: $surface; }
    #scope-title { height: 1; }
    #scope-options { height: 1fr; }
    #scope-close { height: 1; }
    """

    def __init__(self, title: str, values: tuple[str, ...]) -> None:
        super().__init__()
        self.heading = title
        self.values = values

    def compose(self) -> ComposeResult:
        with Vertical(id="scope-dialog"):
            yield Static(self.heading, id="scope-title", markup=False)
            yield OptionList(
                *(
                    Option(safe_text(value), id=f"scope-{index}")
                    for index, value in enumerate(self.values)
                ),
                id="scope-options",
            )
            yield Button("Back", id="scope-close", compact=True)

    @on(OptionList.OptionSelected, "#scope-options")
    def select_scope(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.values[event.option_index])

    @on(Button.Pressed, "#scope-close")
    def close_scope(self) -> None:
        self.dismiss()


class ConnectionScreen(ModalScreen[None]):
    """Make the complete owned connection message readable in narrow terminals."""

    AUTO_FOCUS = "#help-scroll"

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("Connection status", id="help-title", markup=False)
            with VerticalScroll(id="help-scroll"):
                yield Static(safe_text(self.message), id="connection-details")
            yield Button("Back", id="connection-close", compact=True)

    @on(Button.Pressed, "#connection-close")
    def close_details(self) -> None:
        self.dismiss()
