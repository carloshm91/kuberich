"""Public Input events implement deliberate completion without async stale results."""

from collections.abc import Callable
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.events import Blur, Focus
from textual.message import Message
from textual.widgets import Input


class NavigationInput(Input):
    """Finish focus/value ownership in the key handler before the next queued key."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "submit", "Submit", show=False, priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]

    def __init__(
        self,
        focus_table: Callable[[], None],
        *,
        placeholder: str,
        id: str,
        clear_on_submit: bool = False,
    ) -> None:
        self.focus_table = focus_table
        self.clear_on_submit = clear_on_submit
        super().__init__(placeholder=placeholder, id=id, compact=True, max_length=256)

    async def action_submit(self) -> None:
        await super().action_submit()
        if self.clear_on_submit:
            self.value = ""
        self.focus_table()


class CommandInput(NavigationInput):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "complete", "Complete", show=False, priority=True),
        Binding("up", "previous_choice", "Previous suggestion", show=False, priority=True),
        Binding("down", "next_choice", "Next suggestion", show=False, priority=True),
    ]

    class ChoicesChanged(Message):
        pass

    def __init__(
        self, provider: Callable[[str], tuple[str, ...]], focus_table: Callable[[], None]
    ) -> None:
        self.provider = provider
        self.choices: tuple[str, ...] = ()
        self.selected = 0
        self._accepted: str | None = None
        self._query = ""
        self._cycled = False
        super().__init__(
            focus_table,
            placeholder="po / ctx / ns · Tab completes",
            id="command",
            clear_on_submit=True,
        )

    def watch_selection(self) -> None:
        self.refresh_choices()

    def refresh_choices(self) -> None:
        choices = (
            self.provider(self.value)
            if self.has_focus and self.cursor_at_end and self.value != self._accepted
            else ()
        )
        if choices != self.choices or self.value != self._query:
            self._query = self.value
            self.choices = choices
            self.selected = 0
            self._cycled = False
            self.post_message(self.ChoicesChanged())

    def reset_choice(self) -> None:
        """A new workspace generation must not inherit an arrow selection."""
        self._cycled = False
        self.selected = 0
        self.refresh_choices()

    async def action_submit(self) -> None:
        self.refresh_choices()
        if self._cycled and self.choices:
            # Capture before assigning value: reactive input watchers reset choices.
            self.value = self.choices[self.selected]
            self.cursor_position = len(self.value)
        await super().action_submit()

    def on_focus(self, event: Focus) -> None:
        self.refresh_choices()

    def on_blur(self, event: Blur) -> None:
        self.refresh_choices()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"complete", "previous_choice", "next_choice"}:
            self.refresh_choices()
            return self.has_focus if action == "complete" else bool(self.choices)
        return True

    def action_complete(self) -> None:
        # Binding actions run before the next queued key, unlike a bubbled Key message.
        self.refresh_choices()
        if self.choices:
            self.value = self.choices[self.selected]
            self.cursor_position = len(self.value)
            self._accepted = self.value
            self.choices = ()
            self.selected = 0
            self.post_message(self.ChoicesChanged())
        else:
            self.screen.focus_next()

    def _cycle(self, delta: int) -> None:
        self.refresh_choices()
        if self.choices:
            self.selected = (self.selected + delta) % len(self.choices)
            self._cycled = True
            self.post_message(self.ChoicesChanged())

    def action_previous_choice(self) -> None:
        self._cycle(-1)

    def action_next_choice(self) -> None:
        self._cycle(1)
