"""An embedded interactive terminal; Textual retains ownership of the host screen."""

import asyncio
from functools import lru_cache

from rich.segment import Segment
from rich.style import Style
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key, Paste, Resize
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from kuberich.adapters.emulator import TerminalModel
from kuberich.adapters.pty import PtyEndpoint
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.shell import shell_result
from kuberich.domain.terminal import terminal_key, terminal_paste
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.security.controls import escape_controls
from kuberich.security.presentation import safe_text
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

    def __init__(self) -> None:
        super().__init__(id="shell-terminal")
        self.endpoint: PtyEndpoint | None = None
        self.pending = bytearray()
        self.model = TerminalModel(80, 24, self.write)

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
        self.refresh()

    def render_line(self, y: int) -> Strip:
        screen = self.model.screen
        segments: list[Segment] = []
        if y < screen.lines:
            for x in range(screen.columns):
                char = screen.buffer[y][x]
                if not char.data:
                    continue
                cursor = (
                    not screen.cursor.hidden
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
                    reverse=char.reverse != cursor,
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
    #shell-controls { color: $text-muted; }
    """

    def __init__(self, shell: ShellService, runner: ProcessRunner, request: ShellRequest) -> None:
        super().__init__()
        self.shell, self.runner, self.request = shell, runner, request
        self.terminal = TerminalWidget()
        self._session_task: asyncio.Task[None] | None = None
        self.message: str | None = None
        self._shell_unmounting = False
        self._shell_closing = False

    def compose(self) -> ComposeResult:
        target = self.request.command.target
        assert target is not None
        with Vertical(id="shell-frame"):
            yield Static("KubeRich · Container shell", id="shell-heading", markup=False)
            yield Static(safe_text(f"Context: {target.session.context}"), id="shell-context")
            yield Static(
                safe_text(f"Pod: {target.namespace}/{target.name} · Container: {target.container}"),
                id="shell-target",
            )
            yield self.terminal
            yield Static(
                "exit / Ctrl+D return · Ctrl+] close · Ctrl+C interrupt · Ctrl+Q quit",
                id="shell-controls",
                markup=False,
            )

    def on_mount(self) -> None:
        self._session_task = asyncio.create_task(self._run())
        self._session_task.add_done_callback(self._finished)
        if self._shell_closing:
            self._session_task.cancel()

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._session_task = None
        if self.is_mounted and not self._shell_unmounting:
            self.dismiss(self.message or "Shell closed · Container selection retained.")

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
        if self._session_task is not None:
            self._session_task.cancel()

    def key(self, event: Key) -> None:
        if self._shell_closing:
            return
        if event.key == "ctrl+right_square_bracket":
            self.close_shell()
            return
        try:
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
        try:
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
                        await asyncio.sleep(0)
                    self.message = shell_result(await process.wait())
        except asyncio.CancelledError:
            pass
        except ExecutableUnavailable:
            self.message = "kubectl is unavailable. Install kubectl on PATH, then press s to retry."
        except (AppError, ConnectionProblem) as error:
            self.message = str(error)
        except Exception as error:
            self.app._handle_exception(error)
        finally:
            self.terminal.endpoint = None

    async def on_unmount(self) -> None:
        self._shell_unmounting = True
        self.close_shell()
        if self._session_task is not None:
            await asyncio.gather(self._session_task, return_exceptions=True)
