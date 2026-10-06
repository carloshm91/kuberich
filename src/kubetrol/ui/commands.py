"""Public Input events implement deliberate completion without async stale results."""

from collections.abc import Callable
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.events import Blur, Focus
from textual.strip import Strip
from textual.widgets import Input

from kubetrol.security.presentation import safe_text


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

    def __init__(
        self,
        provider: Callable[[str], tuple[str, ...]],
        focus_table: Callable[[], None],
        submit: Callable[[str], None] | None = None,
    ) -> None:
        self.submit = submit
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

    @property
    def inline_completion(self) -> str:
        """A display projection, never submitted text until deliberate acceptance."""
        if self.value and self.choices and self.has_focus and self.cursor_at_end:
            candidate = safe_text(self.choices[self.selected]).plain
            # The provider matches case-insensitively. Preserve the literal typed
            # prefix, including an optional leading colon, in the display only.
            prefix = self.value.removeprefix(":").casefold()
            if not candidate.casefold().startswith(prefix):
                return ""  # Redaction may replace part of the typed prefix.
            boundary, folded = 0, ""
            while len(folded) < len(prefix):
                folded += candidate[boundary].casefold()
                boundary += 1
            return self.value + folded[len(prefix) :] + candidate[boundary:]
        return ""

    def render_line(self, y: int) -> Strip:
        self.refresh_choices()
        # Pinned Textual 8.2 Input renders this literal styled suffix with native
        # cursor/selection/Unicode scrolling. A synchronous local projection
        # avoids asynchronous suggester messages outliving a context revision.
        self._suggestion = self.inline_completion
        return super().render_line(y)

    def action_cursor_right(self, select: bool = False) -> None:
        # Native Input also accepts its suggestion on Right. Keep Right for
        # editing and reserve acceptance for Tab or deliberate arrow+Enter.
        self._suggestion = ""
        super().action_cursor_right(select)

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
            self.refresh()

    def reset_choice(self) -> None:
        """A new workspace generation must not inherit an arrow selection."""
        self._cycled = False
        self.selected = 0
        self.refresh_choices()
        self.refresh()

    async def action_submit(self) -> None:
        self.refresh_choices()
        if self._cycled and self.choices:
            # Capture before assigning value: reactive input watchers reset choices.
            self.value = self.choices[self.selected]
            self.cursor_position = len(self.value)
        if self.submit is None:
            await super().action_submit()
        else:
            # Complete the command's synchronous navigation decision before the
            # next queued app key. Posting Input.Submitted can lag typeahead.
            value = self.value
            self.value = ""
            self.focus_table()
            self.submit(value)

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
            self.refresh()
        else:
            self.screen.focus_next()

    def _cycle(self, delta: int) -> None:
        self.refresh_choices()
        if self.choices:
            self.selected = (self.selected + delta) % len(self.choices)
            self._cycled = True
            self.refresh()

    def action_previous_choice(self) -> None:
        self._cycle(-1)

    def action_next_choice(self) -> None:
        self._cycle(1)
