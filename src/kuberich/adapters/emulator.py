"""Pinned Pyte adapter; remote terminal protocol never reaches the host driver."""

import codecs
import re
import unicodedata
from collections.abc import Callable
from typing import cast

import pyte
from pyte.modes import DECOM
from pyte.screens import Screen

from kuberich.domain.terminal import terminal_size

# Controls has already bounded/framed every escape. Dispatch each frame separately
# so a rejected Pyte parameter list cannot discard the later text in that read.
_FRAMES = re.compile(r"\x1b(?:\[[0-9;? >]*[@-~]|[()%#].|.)|[^\x1b]+", re.DOTALL)


class _Controls:
    """Frame bounded escape sequences and discard all control strings, including OSC52."""

    def __init__(self) -> None:
        self.state = "text"
        self.sequence = ""

    def feed(self, text: str) -> str:
        output: list[str] = []
        for char in text:
            if self.state == "string":
                if char in "\x07\x9c":
                    self.state = "text"
                elif char == "\x1b":
                    self.state = "string_escape"
            elif self.state == "string_escape":
                self.state = "text" if char == "\\" else "string"
            elif char == "\x1b":
                self.sequence, self.state = char, "escape"
            elif self.state == "escape":
                if char in "]PX^_":
                    self.sequence, self.state = "", "string"
                elif char == "[":
                    self.sequence += char
                    self.state = "csi"
                elif char in "()%#":
                    self.sequence += char
                    self.state = "charset"
                else:
                    output.append(self.sequence + char)
                    self.sequence, self.state = "", "text"
            elif self.state == "charset":
                output.append(self.sequence + char)
                self.sequence, self.state = "", "text"
            elif self.state in {"csi", "discard_csi"}:
                if "@" <= char <= "~":
                    if self.state == "csi":
                        output.append(self.sequence + char)
                    self.sequence, self.state = "", "text"
                elif char in "0123456789;? >" and len(self.sequence) < 128:
                    self.sequence += char
                else:
                    self.sequence, self.state = "", "discard_csi"
            elif char in "\x90\x98\x9d\x9e\x9f":
                self.state = "string"
            elif char == "\x9b":
                self.sequence, self.state = "\x1b[", "csi"
            elif char in "\x07\b\t\n\v\f\r" or char.isprintable():
                output.append(char)
        return "".join(output)


class _Screen(Screen):
    def __init__(self, width: int, height: int, reply: Callable[[bytes], None]) -> None:
        super().__init__(width, height)
        self.reply = reply

    def write_process_input(self, data: str) -> None:
        self.reply(data.encode("ascii"))

    def report_device_status(self, mode: int, *, private: bool = False) -> None:
        if mode == 6:
            row = self.cursor.y + 1
            if DECOM in self.mode and self.margins is not None:
                row -= self.margins.top
            prefix = "\x1b[?" if private else "\x1b["
            self.write_process_input(f"{prefix}{row};{self.cursor.x + 1}R")
        elif not private:
            super().report_device_status(mode)

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        height = lines or self.lines
        width = columns or self.columns
        if height < self.lines:
            # Trim the bottom first. Scroll only far enough to retain the live
            # cursor when it would fall below the new viewport.
            shift = max(0, self.cursor.y - height + 1)
            retained = {
                row - shift: cells
                for row, cells in self.buffer.items()
                if shift <= row < shift + height
            }
            self.buffer.clear()
            self.buffer.update(retained)
            self.cursor.y -= shift
            self.lines = height
            self.set_margins()
            self.dirty.update(range(height))
        super().resize(lines=height, columns=width)

    def save_cursor(self) -> None:
        # DEC defines one saved cursor; an unbounded stack is unnecessary here.
        self.savepoints.clear()
        super().save_cursor()

    def draw(self, data: str) -> None:
        if not any(unicodedata.combining(char) for char in data):
            super().draw(data)
            return
        for char in data:
            if unicodedata.combining(char):
                x, y = self.cursor.x - 1, self.cursor.y
                if x < 0:
                    x, y = self.columns - 1, y - 1
                if y >= 0 and len(self.buffer[y][x].data) >= 32:
                    continue
            super().draw(char)


class _Router:
    """Pyte's documented duck-typed event listener, routing cached callbacks dynamically."""

    def __init__(self, model: "TerminalModel") -> None:
        self.model = model

    def __getattr__(self, event: str) -> Callable[..., None]:
        if event not in pyte.Stream.events:
            raise AttributeError(event)

        def dispatch(*args: object, **kwargs: object) -> None:
            callback: Callable[..., None] = getattr(self.model.screen, event)
            callback(*args, **kwargs)

        return dispatch

    def set_mode(self, *modes: int, **kwargs: bool) -> None:
        self._mode(True, modes, kwargs.get("private", False))

    def reset_mode(self, *modes: int, **kwargs: bool) -> None:
        self._mode(False, modes, kwargs.get("private", False))

    def reset(self) -> None:
        self.model.normal.reset()
        self.model.secondary.reset()
        self.model.screen = self.model.normal
        self.model.application_cursor = False
        self.model.bracketed_paste = False

    def _mode(self, enabled: bool, modes: tuple[int, ...], private: bool) -> None:
        for mode in modes:
            if private and mode in {47, 1047, 1049}:
                self.model.alternate(enabled, clear=mode != 47)
            elif private and mode == 2004:
                self.model.bracketed_paste = enabled
            elif private and mode == 1:
                self.model.application_cursor = enabled
            elif (private and mode in {6, 7, 25}) or (not private and mode in {4, 20}):
                callback = self.model.screen.set_mode if enabled else self.model.screen.reset_mode
                callback(mode, private=private)


class TerminalModel:
    def __init__(self, width: int, height: int, reply: Callable[[bytes], None]) -> None:
        width, height = terminal_size(width, height)
        self.normal = _Screen(width, height, reply)
        self.secondary = _Screen(width, height, reply)
        self.screen = self.normal
        self.application_cursor = False
        self.bracketed_paste = False
        self.controls = _Controls()
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        # Stream checks every documented event; the adapter supplies them through routing.
        self.stream = pyte.Stream(cast(Screen, _Router(self)))

    def alternate(self, enabled: bool, *, clear: bool) -> None:
        if enabled and self.screen is self.normal:
            if clear:
                self.secondary.reset()
            self.screen = self.secondary
        elif not enabled:
            self.screen = self.normal

    def resize(self, width: int, height: int) -> None:
        width, height = terminal_size(width, height)
        for screen in (self.normal, self.secondary):
            screen.resize(lines=height, columns=width)
            screen.ensure_hbounds()
            screen.ensure_vbounds()

    def feed(self, data: bytes) -> None:
        value = self.controls.feed(self.decoder.decode(data))
        for frame in _FRAMES.finditer(value):
            try:
                self.stream.feed(frame.group())
            except (ValueError, IndexError, TypeError):
                # Pyte resets its parser after a dispatch error. Continue with
                # the next frame instead of losing the rest of this PTY read.
                continue
