"""An embedded interactive terminal; Textual retains ownership of the host screen."""

import asyncio
from collections.abc import Sequence
from functools import lru_cache

from pyte.screens import Char
from rich.segment import Segment
from rich.style import Style
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click, Key, MouseScrollDown, MouseScrollUp, Paste, Resize
from textual.message import Message
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Button, Static

from kuberich.adapters.emulator import TerminalModel
from kuberich.adapters.pty import PtyEndpoint
from kuberich.domain.attach import attach_result
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.processes import ProcessPurpose
from kuberich.domain.shell import shell_result
from kuberich.domain.terminal import terminal_key, terminal_paste
from kuberich.domain.terminal_history import SEARCH_CHARACTERS, TerminalCell, TerminalReview
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.security.controls import escape_controls
from kuberich.security.presentation import safe_text
from kuberich.services.attach import AttachService
from kuberich.services.processes import ProcessRunner
from kuberich.services.shell import ShellRequest, ShellService


@lru_cache(maxsize=256)
def _color(value: str) -> str | None:
    if value in {"black", "red", "green", "brown", "blue", "magenta", "cyan", "white"}:
        return "yellow" if value == "brown" else value
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        return "#" + value
    return None


class TerminalWidget(Widget):
    can_focus = True

    class ReviewChanged(Message):
        pass

    def __init__(self) -> None:
        super().__init__(id="shell-terminal")
        self.endpoint: PtyEndpoint | None = None
        self.pending = bytearray()
        self.model = TerminalModel(80, 24, self.write)
        self.review: TerminalReview | None = None

    def begin_review(self) -> None:
        self.review = TerminalReview(self.model.review_rows())
        self.review.move(-max(1, self.size.height), self.size.height)
        self.post_message(self.ReviewChanged())
        self.refresh()

    def end_review(self) -> None:
        self.review = None
        self.post_message(self.ReviewChanged())
        self.refresh()

    def clear_history(self) -> None:
        self.review = None
        self.model.clear_history()

    def on_click(self, event: Click) -> None:
        if self.review is not None:
            if event.shift:
                if self.review.mark is None:
                    self.review.toggle_mark()
            else:
                self.review.mark = None
            self.review.move(self.review.top + event.y - self.review.cursor, self.size.height)
            self.post_message(self.ReviewChanged())
            self.refresh()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if self.review is not None:
            self.review.move(-3, self.size.height)
            self.post_message(self.ReviewChanged())
            self.refresh()
            event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if self.review is not None:
            self.review.move(3, self.size.height)
            self.post_message(self.ReviewChanged())
            self.refresh()
            event.stop()

    def write(self, data: bytes) -> None:
        if self.endpoint is not None:
            self.endpoint.write(data)
        elif len(self.pending) + len(data) <= 65536:
            self.pending.extend(data)
        else:
            raise AppError("Terminal input is busy; wait for the shell to open.")

    def attach(self, endpoint: PtyEndpoint) -> None:
        self.endpoint = endpoint
        self.model.resize(self.size.width, self.size.height)
        endpoint.resize(self.size.width, self.size.height)
        endpoint.write(bytes(self.pending))
        self.pending.clear()

    def on_resize(self, event: Resize) -> None:
        self.model.resize(event.size.width, event.size.height)
        if self.endpoint is not None:
            self.endpoint.resize(event.size.width, event.size.height)
        if self.review is not None:
            self.review.fit(event.size.height)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        screen = self.model.screen
        segments: list[Segment] = []
        row = self.review.top + y if self.review is not None else y
        cells: Sequence[TerminalCell | Char]
        if self.review is not None:
            cells = self.review.rows[row].cells if row < len(self.review.rows) else ()
        else:
            cells = (
                tuple(screen.buffer[y][x] for x in range(screen.columns))
                if y < screen.lines
                else ()
            )
        for x, char in enumerate(cells):
            if not char.data:
                continue
            cursor = (
                not screen.cursor.hidden
                and self.review is None
                and self.has_focus
                and (x, y) == (screen.cursor.x, screen.cursor.y)
            )
            style = Style(
                color=_color(char.fg),
                bgcolor=_color(char.bg),
                bold=char.bold,
                italic=char.italics,
                underline=char.underscore,
                strike=char.strikethrough,
                reverse=char.reverse
                != (cursor or (self.review is not None and self.review.selected(row))),
            )
            segments.append(Segment(escape_controls(char.data), style))
        return (
            Strip(segments)
            .apply_style(self.rich_style)
            .extend_cell_length(self.size.width, self.rich_style)
            .crop(0, self.size.width)
            .simplify()
        )


class ShellScreen(ModalScreen[str]):
    AUTO_FOCUS = "#shell-terminal"
    DEFAULT_CSS = """
    ShellScreen { background: $background; }
    #shell-frame { width: 100%; height: 100%; border: round $primary; }
    #shell-heading { height: 1; color: $accent; text-overflow: ellipsis; }
    #shell-context, #shell-target, #shell-controls { height: 1; text-overflow: ellipsis; }
    #shell-terminal { height: 1fr; width: 1fr; background: $background; }
    #shell-toolbar { height: 1; }
    #shell-controls { width: 1fr; }
    #shell-history { width: 9; min-width: 0; height: 1; min-height: 1; border: none; padding: 0; }
    #shell-controls { color: $text-muted; }
    """

    def __init__(
        self, shell: ShellService | AttachService, runner: ProcessRunner, request: ShellRequest
    ) -> None:
        super().__init__()
        self.shell, self.runner, self.request = shell, runner, request
        self.attach_mode = request.command.purpose is ProcessPurpose.ATTACH
        self.detach_pending = False
        self.terminal = TerminalWidget()
        self._session_task: asyncio.Task[None] | None = None
        self.message: str | None = None
        self._shell_unmounting = False
        self._shell_closing = False
        self.searching = False
        self.search_query = ""
        self.review_message = ""
        self.history_button = Button("History", id="shell-history")
        self.controls = Static(self.live_controls(), id="shell-controls", markup=False)

    def compose(self) -> ComposeResult:
        target = self.request.command.target
        assert target is not None
        with Vertical(id="shell-frame"):
            yield Static(
                "KubeRich · Attach to existing process"
                if self.attach_mode
                else "KubeRich · Container shell",
                id="shell-heading",
                markup=False,
            )
            yield Static(safe_text(f"Context: {target.session.context}"), id="shell-context")
            yield Static(
                safe_text(f"Pod: {target.namespace}/{target.name} · Container: {target.container}"),
                id="shell-target",
            )
            yield self.terminal
            with Horizontal(id="shell-toolbar"):
                yield self.controls
                yield self.history_button

    def live_controls(self) -> str:
        return (
            "Ctrl+P, Ctrl+Q detach · Ctrl+] close · Alt+PgUp history · Ctrl+Q quit"
            if self.attach_mode
            else "exit / Ctrl+D return · Ctrl+] close · Alt+PgUp history · Ctrl+Q quit"
        )

    def on_terminal_widget_review_changed(self, event: TerminalWidget.ReviewChanged) -> None:
        if self.is_mounted and not self._shell_closing:
            self.update_review_controls()

    def update_review_controls(self) -> None:
        # Textual removes children before dispatching the screen's Unmount.
        # The owned PTY can still deliver output during that interval.
        if not self.controls.is_attached or not self.history_button.is_attached:
            return
        review = self.terminal.review
        self.history_button.label = "Live" if review is not None else "History"
        if review is None:
            text = self.live_controls()
        elif self.searching:
            text = f"Search: {self.search_query} · Enter find · Esc cancel"
        else:
            text = (
                f"Review {review.cursor + 1}/{len(review.rows)} · dropped {self.terminal.model.history.dropped}"
                " · / search · v select · y copy · Enter live"
            )
            if self.review_message:
                text = self.review_message + " · " + text
        self.controls.update(safe_text(text))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "shell-history" and not self._shell_closing:
            self.detach_pending = False
            if self.terminal.review is None:
                self.terminal.begin_review()
            else:
                self.return_live()
            self.terminal.focus()

    def return_live(self) -> None:
        self.searching = False
        self.search_query = ""
        self.review_message = ""
        self.terminal.end_review()

    def review_key(self, event: Key) -> None:
        review = self.terminal.review
        assert review is not None
        height = max(1, self.terminal.size.height)
        self.review_message = ""
        if self.searching:
            if event.key == "escape":
                self.searching = False
            elif event.key == "enter":
                self.searching = False
                self.review_message = (
                    "Match" if review.find(self.search_query, height=height) else "No match"
                )
            elif event.key == "backspace":
                self.search_query = self.search_query[:-1]
            elif (
                event.character is not None
                and event.character.isprintable()
                and len(self.search_query) < SEARCH_CHARACTERS
            ):
                self.search_query += event.character
        elif event.key in {"escape", "enter", "q"}:
            self.return_live()
        elif event.key in {"slash", "ctrl+f"}:
            self.searching = True
            self.search_query = ""
        elif event.key in {"g", "home", "G", "end"}:
            review.edge(event.key in {"G", "end"}, height)
        elif event.key in {"v", "space"}:
            review.toggle_mark()
        elif event.key in {"y", "ctrl+y"}:
            self.shell.require_current()
            self.app.copy_to_clipboard(review.copy())
            self.review_message = "Redacted selection copied; clipboard write requested"
        elif event.key in {"n", "N"}:
            self.review_message = (
                "Match"
                if review.find(review.query, backwards=event.key == "N", height=height)
                else "No match"
            )
        else:
            delta = {
                "up": -1,
                "k": -1,
                "down": 1,
                "j": 1,
                "pageup": -height,
                "shift+pageup": -height,
                "alt+pageup": -height,
                "pagedown": height,
                "shift+pagedown": height,
                "alt+pagedown": height,
            }.get(event.key, 0)
            review.move(delta, height)
        self.update_review_controls()
        self.terminal.refresh()

    def on_mount(self) -> None:
        self._session_task = asyncio.create_task(self._run())
        self._session_task.add_done_callback(self._finished)
        if self._shell_closing:
            self._session_task.cancel()

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._session_task = None
        if self.is_mounted and not self._shell_unmounting:
            self.dismiss(
                self.message
                or (
                    "Attach closed locally · Container selection retained."
                    if self.attach_mode
                    else "Shell closed · Container selection retained."
                )
            )

    @property
    def stop_requested(self) -> bool:
        """Whether terminal input has stopped and its owned session needs draining."""
        return self._shell_closing

    def validate_target(self) -> None:
        try:
            self.shell.require_current()
        except AppError as error:
            self.message = str(error)
            self.close_shell()

    def close_shell(self) -> None:
        self._shell_closing = True
        self.terminal.endpoint = None
        self.terminal.pending.clear()
        self.terminal.clear_history()
        if self._session_task is not None and not self._session_task.cancelling():
            self._session_task.cancel()

    def key(self, event: Key) -> None:
        if self._shell_closing:
            return
        self.detach_pending = (
            self.attach_mode and self.terminal.review is None and event.key == "ctrl+p"
        )
        if event.key == "ctrl+right_square_bracket":
            self.close_shell()
            return
        try:
            if self.terminal.review is not None:
                self.review_key(event)
                return
            if event.key in {"shift+pageup", "alt+pageup"}:
                self.detach_pending = False
                self.terminal.begin_review()
                return
            self.terminal.write(
                terminal_key(
                    event.key,
                    event.character,
                    application_cursor=self.terminal.model.application_cursor,
                )
            )
        except AppError as error:
            self.query_one("#shell-controls", Static).update(safe_text(str(error)))

    def paste(self, event: Paste) -> None:
        if self._shell_closing:
            return
        self.detach_pending = False
        try:
            if self.terminal.review is not None:
                if self.searching:
                    literal = "".join(
                        char for char in event.text[:SEARCH_CHARACTERS] if char.isprintable()
                    )
                    self.search_query = (self.search_query + literal)[:SEARCH_CHARACTERS]
                self.update_review_controls()
                return
            self.terminal.write(
                terminal_paste(event.text, bracketed=self.terminal.model.bracketed_paste)
            )
        except AppError as error:
            self.query_one("#shell-controls", Static).update(safe_text(str(error)))

    async def _run(self) -> None:
        try:
            async with self.shell.stage(self.request) as command:
                size = self.terminal.size
                async with self.runner.terminal(
                    command, width=size.width, height=size.height, guard=self.shell.require_current
                ) as (endpoint, process):
                    self.terminal.attach(endpoint)
                    while data := await endpoint.read():
                        self.terminal.model.feed(data)
                        self.terminal.refresh()
                        if self.terminal.review is not None:
                            self.update_review_controls()
                        await asyncio.sleep(0)
                    result = await process.wait()
                    self.message = (
                        attach_result(result) if self.attach_mode else shell_result(result)
                    )
        except asyncio.CancelledError:
            pass
        except ExecutableUnavailable:
            self.message = (
                "kubectl is unavailable. Install kubectl on PATH, then press a to retry attach."
                if self.attach_mode
                else "kubectl is unavailable. Install kubectl on PATH, then press s to retry."
            )
        except (AppError, ConnectionProblem) as error:
            self.message = str(error)
        except Exception as error:
            self.app._handle_exception(error)
        finally:
            self.terminal.endpoint = None
            self.terminal.clear_history()

    async def stop_owned(self) -> None:
        self.close_shell()
        if self._session_task is not None:
            await asyncio.gather(self._session_task, return_exceptions=True)

    async def on_unmount(self) -> None:
        self._shell_unmounting = True
        await self.stop_owned()
