"""A bounded, disposable real terminal with explicit process and descriptor ownership."""

import codecs
import errno
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import pyte

from tests.support.terminal_modes import restored_modes

if TYPE_CHECKING:
    from tests.support.transports import TerminalTransport

ROOT = Path(__file__).resolve().parents[2]

# Keep a shell-like session owner alive while the actual CLI exits. Darwin revokes
# slave descriptors when that owner exits, so record both modes before then.
_SESSION_OWNER = """
import fcntl
import json
import os
import subprocess
import sys
import termios

def encode_mode(mode):
    return [*mode[:6], [value.hex() if isinstance(value, bytes) else value for value in mode[6]]]

fcntl.ioctl(0, termios.TIOCSCTTY, 0)
before = termios.tcgetattr(0)
result = subprocess.run(sys.argv[2:], check=False)
after = termios.tcgetattr(0)
record = {'exit': result.returncode, 'before': encode_mode(before), 'after': encode_mode(after)}
os.write(int(sys.argv[1]), json.dumps(record).encode() + b'\\n')
"""


def encode_mode(mode: list[object]) -> list[object]:
    controls = mode[6]
    assert isinstance(controls, list)
    return [*mode[:6], [value.hex() if isinstance(value, bytes) else value for value in controls]]


class ObserverScreen(pyte.Screen):
    """Observe output without injecting query responses into application input."""

    def report_device_status(self, mode: int, *, private: bool = False) -> None:
        if not private:
            super().report_device_status(mode)


class TerminalSession:
    def __init__(
        self,
        command: list[str],
        directory: Path,
        *,
        size: tuple[int, int] = (100, 30),
        transport: "TerminalTransport | None" = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.master, self.slave = pty.openpty()
        self.original_mode = termios.tcgetattr(self.slave)
        self.completion_read, completion_write = os.pipe()
        self.completion_bytes = bytearray()
        self.completion: dict[str, object] | None = None
        self.transcript = bytearray()
        self.sizes = [size]
        self.screen = ObserverScreen(*size)
        self.screen_stream = pyte.Stream(self.screen)
        self.screen_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[1], size[0], 0, 0))
        preferences = directory / "preferences.yaml"
        if not preferences.exists():
            preferences.write_text("schema_version: 1\n", encoding="utf-8")
        self.transport = transport
        overrides = environment or {}
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("KUBERICH_", "KUBETROL_", "TEXTUAL"))
        }
        environment.pop("PYTHONPATH", None)
        environment.pop("NO_COLOR", None)
        environment.pop("COLUMNS", None)
        environment.pop("LINES", None)
        environment["TERM"] = "xterm-256color"
        environment["KUBERICH_CONFIG"] = str(preferences)
        environment["KUBERICH_LOG_FILE"] = str(directory / "kuberich.log")
        environment["KUBERICH_LOG_LEVEL"] = "DEBUG"
        environment["KUBECONFIG"] = str(directory / "never-use-a-real-cluster")
        environment.update(overrides)

        try:
            if transport is not None:
                command, environment = transport.wrap(command, directory, environment)
            self.process = subprocess.Popen(
                [sys.executable, "-c", _SESSION_OWNER, str(completion_write), *command],
                cwd=directory,
                env=environment,
                stdin=self.slave,
                stdout=self.slave,
                stderr=self.slave,
                start_new_session=True,
                pass_fds=(completion_write,),
            )
        except BaseException:
            os.close(self.master)
            os.close(self.slave)
            os.close(self.completion_read)
            raise
        finally:
            os.close(completion_write)

    def __enter__(self) -> "TerminalSession":
        return self

    def _read(self, timeout: float = 0.1) -> None:
        descriptors = [self.master]
        if self.completion is None:
            descriptors.append(self.completion_read)
        ready, _, _ = select.select(descriptors, [], [], timeout)
        if self.completion_read in ready:
            chunk = os.read(self.completion_read, 4096)
            assert chunk, f"Session owner exited without restoration evidence: {self.transcript!r}"
            self.completion_bytes.extend(chunk)
            assert len(self.completion_bytes) <= 4096, "Unbounded restoration evidence"
            if b"\n" in self.completion_bytes:
                self.completion = json.loads(self.completion_bytes)
        if self.master in ready:
            try:
                data = os.read(self.master, 65536)
                self.transcript.extend(data)
                self.screen_stream.feed(self.screen_decoder.decode(data))
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
            assert len(self.transcript) <= 2 * 1024 * 1024, "Unexpected unbounded terminal output"

    def wait_for(self, text: bytes, *, since: int = 0, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while text not in self.transcript[since:]:
            self._read()
            if self.process.poll() is not None:
                self._read(0)
                assert text in self.transcript[since:], (
                    f"Process exited before {text!r}: {self.transcript[-3000:]!r}"
                )
            assert time.monotonic() < deadline, (
                f"Timed out waiting for {text!r}: {self.transcript[-3000:]!r}"
            )

    def send(self, data: bytes) -> int:
        marker = len(self.transcript)
        os.write(self.master, data)
        return marker

    def wait_for_screen(
        self,
        text: str,
        *,
        row: int | None = None,
        timeout: float = 15,
        since: int = -1,
        absent: tuple[str, ...] = (),
    ) -> None:
        deadline = time.monotonic() + timeout
        while True:
            display = "\n".join(self.screen.display)
            selected = display if row is None else "\n".join(self.screen.display[row : row + 1])
            if (
                text in selected
                and len(self.transcript) > since
                and all(value not in display for value in absent)
            ):
                return
            self._read()
            assert self.process.poll() is None, f"Exited before visible {text!r}"
            assert time.monotonic() < deadline, f"Missing visible {text!r}: {self.screen.display!r}"

    def resize(self, width: int, height: int) -> int:
        # Consume bytes already emitted for the old geometry before changing
        # the observer's screen. Otherwise delayed PTY/SSH output is replayed
        # against dimensions it was never rendered for.
        for _ in range(16):
            if not select.select([self.master], [], [], 0)[0]:
                break
            self._read(0)
        marker = len(self.transcript)
        self.sizes.append((width, height))
        self.screen.resize(lines=height, columns=width)
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
        os.killpg(self.process.pid, signal.SIGWINCH)
        return marker

    def finish(self, *, expected: int = 0, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while self.process.poll() is None:
            self._read()
            assert time.monotonic() < deadline, (
                f"Terminal process did not exit: {self.transcript[-3000:]!r}"
            )
        for _ in range(5):
            self._read(0)
        assert self.process.returncode == 0, self.transcript[-3000:].decode(errors="replace")
        assert self.completion is not None, "Missing actual application exit/restoration evidence"
        disconnected = self.transport is not None and self.transport.disconnected
        outer_expected = (
            255
            if disconnected
            else 0
            if self.transport is not None and self.transport.tmux
            else expected
        )
        assert self.completion["exit"] == outer_expected, self.transcript[-3000:].decode(
            errors="replace"
        )
        assert self.completion["before"] == encode_mode(self.original_mode)
        assert restored_modes(self.completion["before"], self.completion["after"]), (
            "TTY attributes not restored"
        )
        assert b"\x1b[?1049h" in self.transcript
        if not disconnected:
            assert self.mode_restored(1049), "Alternate screen was not closed"
            assert self.mode_restored(25, enabled=True), "Cursor was not restored"
            for mode in (1000, 1003, 1004, 1006, 2004):
                assert self.mode_restored(mode), f"Terminal reporting mode {mode} was not disabled"
        if self.transport is not None:
            self.transport.verify(expected)

    def mode_restored(self, mode: int, *, enabled: bool = False) -> bool:
        restored = f"\x1b[?{mode}{'h' if enabled else 'l'}".encode()
        changed = f"\x1b[?{mode}{'l' if enabled else 'h'}".encode()
        return self.transcript.rfind(restored) > self.transcript.rfind(changed)

    def save_evidence(self, name: str) -> None:
        assert self.completion is not None
        output = ROOT / "artifacts" / "terminal"
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{name}.ansi").write_bytes(self.transcript)
        (output / f"{name}.json").write_text(
            json.dumps(
                {
                    "exit": self.completion["exit"],
                    "sizes": self.sizes,
                    "terminal_mode_restored": restored_modes(
                        self.completion["before"], self.completion["after"]
                    ),
                    "kernel_flag_normalization": "Darwin PENDIN"
                    if sys.platform == "darwin"
                    else None,
                    "terminal_modes": self.completion,
                    "transport": self.transport.record if self.transport else None,
                    "alternate_screen_closed": self.mode_restored(1049),
                    "cursor_restored": self.mode_restored(25, enabled=True),
                    "reporting_modes_disabled": {
                        str(mode): self.mode_restored(mode)
                        for mode in (1000, 1003, 1004, 1006, 2004)
                    },
                },
                indent=2,
            )
            + "\n"
        )

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        try:
            if kind is not None:
                output = ROOT / "artifacts/terminal"
                output.mkdir(parents=True, exist_ok=True)
                name = f"failure-{time.time_ns()}"
                (output / f"{name}.ansi").write_bytes(self.transcript)
                (output / f"{name}.json").write_text(
                    json.dumps(
                        {
                            "result": "failed",
                            "error_type": kind.__name__,
                            "sizes": self.sizes,
                            "screen": self.screen.display,
                            "terminal_completion": self.completion,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
        finally:
            os.close(self.master)
            os.close(self.slave)
            os.close(self.completion_read)
