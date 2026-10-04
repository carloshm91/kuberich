"""A bounded, disposable real terminal with explicit process and descriptor ownership."""

import errno
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path
from types import TracebackType

ROOT = Path(__file__).resolve().parents[2]


class TerminalSession:
    def __init__(
        self, command: list[str], directory: Path, *, size: tuple[int, int] = (100, 30)
    ) -> None:
        self.master, self.slave = pty.openpty()
        self.original_mode = termios.tcgetattr(self.slave)
        self.transcript = bytearray()
        self.sizes = [size]
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[1], size[0], 0, 0))
        preferences = directory / "preferences.yaml"
        if not preferences.exists():
            preferences.write_text("schema_version: 1\n", encoding="utf-8")
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("KUBETROL_", "TEXTUAL"))
        }
        environment.pop("PYTHONPATH", None)
        environment.pop("NO_COLOR", None)
        environment.pop("COLUMNS", None)
        environment.pop("LINES", None)
        environment["TERM"] = "xterm-256color"
        environment["KUBETROL_CONFIG"] = str(preferences)
        environment["KUBETROL_LOG_FILE"] = str(directory / "kubetrol.log")
        environment["KUBETROL_LOG_LEVEL"] = "DEBUG"
        environment["KUBECONFIG"] = str(directory / "never-use-a-real-cluster")

        def terminal_owner() -> None:
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        try:
            self.process = subprocess.Popen(
                command,
                cwd=directory,
                env=environment,
                stdin=self.slave,
                stdout=self.slave,
                stderr=self.slave,
                preexec_fn=terminal_owner,
            )
        except BaseException:
            os.close(self.master)
            os.close(self.slave)
            raise

    def __enter__(self) -> "TerminalSession":
        return self

    def _read(self, timeout: float = 0.1) -> None:
        ready, _, _ = select.select([self.master], [], [], timeout)
        if ready:
            try:
                self.transcript.extend(os.read(self.master, 65536))
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

    def resize(self, width: int, height: int) -> int:
        marker = len(self.transcript)
        self.sizes.append((width, height))
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
        self.process.send_signal(signal.SIGWINCH)
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
        assert self.process.returncode == expected, self.transcript[-3000:].decode(errors="replace")
        assert termios.tcgetattr(self.slave) == self.original_mode, (
            "TTY attributes were not restored"
        )
        assert b"\x1b[?1049h" in self.transcript
        assert self.mode_restored(1049), "Alternate screen was not closed"
        assert self.mode_restored(25, enabled=True), "Cursor was not restored"
        for mode in (1000, 1003, 1004, 1006, 2004):
            assert self.mode_restored(mode), f"Terminal reporting mode {mode} was not disabled"

    def mode_restored(self, mode: int, *, enabled: bool = False) -> bool:
        restored = f"\x1b[?{mode}{'h' if enabled else 'l'}".encode()
        changed = f"\x1b[?{mode}{'l' if enabled else 'h'}".encode()
        return self.transcript.rfind(restored) > self.transcript.rfind(changed)

    def save_evidence(self, name: str) -> None:
        output = ROOT / "artifacts" / "terminal"
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{name}.ansi").write_bytes(self.transcript)
        (output / f"{name}.json").write_text(
            json.dumps(
                {
                    "exit": self.process.returncode,
                    "sizes": self.sizes,
                    "terminal_mode_restored": termios.tcgetattr(self.slave) == self.original_mode,
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
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            os.close(self.master)
            os.close(self.slave)
