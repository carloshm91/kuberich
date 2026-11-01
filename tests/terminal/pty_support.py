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
import signal
import subprocess
import sys
import termios
import time

def encode_mode(mode):
    return [*mode[:6], [value.hex() if isinstance(value, bytes) else value for value in mode[6]]]

fcntl.ioctl(0, termios.TIOCSCTTY, 0)
before = termios.tcgetattr(0)
stopped_at = None
def stopping(*_):
    global stopped_at
    if stopped_at is None:
        stopped_at = time.monotonic()
signal.signal(signal.SIGTERM, stopping)
process = subprocess.Popen(sys.argv[3:])
while True:
    try:
        result = process.wait(timeout=0.1)
        break
    except subprocess.TimeoutExpired:
        if stopped_at is not None and time.monotonic() - stopped_at >= 2:
            process.kill()
after = termios.tcgetattr(0)
record = {'exit': result, 'before': encode_mode(before), 'after': encode_mode(after)}
os.write(int(sys.argv[1]), json.dumps(record).encode() + b'\\n')
# Keep the session identity reserved until the parent has checked its group.
# The application has exited and its actual terminal modes are already recorded.
os.read(int(sys.argv[2]), 1)
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
        read_size: int = 65536,
    ) -> None:
        assert type(read_size) is int and 1 <= read_size <= 65536
        self.read_size = read_size
        self._closed_descriptors: set[int] = set()
        self._attempted_descriptors: set[int] = set()
        self._acknowledged = False
        self._acknowledgement_attempted = False
        self._cleanup_master_eof = False
        self._cleanup_completion_eof = False
        self._cleanup_discarded_bytes = 0
        self._cleanup_poll_failures = 0
        self._cleanup_errors: list[BaseException] = []
        self.cleanup: dict[str, object] | None = None
        self._descriptors: list[int] = []
        try:
            self.master, self.slave = pty.openpty()
            self._descriptors.extend((self.master, self.slave))
            self.original_mode = termios.tcgetattr(self.slave)
            self.completion_read, completion_write = os.pipe()
            self._descriptors.extend((self.completion_read, completion_write))
            acknowledgement_read, self.acknowledgement_write = os.pipe()
            self._descriptors.extend((acknowledgement_read, self.acknowledgement_write))
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
            # Ordinary PTY trials must never replace a developer's host clipboard.
            environment["KUBERICH_CLIPBOARD"] = "osc52"
            environment["KUBECONFIG"] = str(directory / "never-use-a-real-cluster")
            environment.update(overrides)

            if transport is not None:
                command, environment = transport.wrap(command, directory, environment)
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _SESSION_OWNER,
                    str(completion_write),
                    str(acknowledgement_read),
                    *command,
                ],
                cwd=directory,
                env=environment,
                stdin=self.slave,
                stdout=self.slave,
                stderr=self.slave,
                start_new_session=True,
                pass_fds=(completion_write, acknowledgement_read),
            )
            self._owner_pid = self.process.pid
            self._owner_process = self.process
            close_errors = []
            for descriptor in (completion_write, acknowledgement_read):
                try:
                    self._close_descriptor(descriptor)
                except BaseException as error:
                    close_errors.append(error)
            if close_errors:
                raise BaseExceptionGroup("Terminal setup descriptor cleanup failed", close_errors)
        except BaseException as first:
            if hasattr(self, "process"):
                self._owner_pid = self.process.pid
                self._owner_process = self.process
                try:
                    self.__exit__(type(first), first, first.__traceback__)
                except BaseException as cleanup_error:
                    first.add_note(f"Terminal setup cleanup failed: {cleanup_error!r}")
            for descriptor in self._descriptors:
                try:
                    self._close_descriptor(descriptor)
                except BaseException as close_error:
                    first.add_note(f"Terminal descriptor cleanup failed: {close_error!r}")
            raise

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
                data = os.read(self.master, self.read_size)
                self.transcript.extend(data)
                # The owned disconnect flag is set before terminating SSH.
                # Late output may contain truncated/interleaved terminal frames;
                # retain it for exit/restoration evidence without inventing a
                # visible screen after the transport has ceased to be observable.
                if self.transport is None or not self.transport.disconnected:
                    self.screen_stream.feed(self.screen_decoder.decode(data))
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
            assert len(self.transcript) <= 2 * 1024 * 1024, "Unexpected unbounded terminal output"

    def wait_for(self, text: bytes, *, since: int = 0, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while text not in self.transcript[since:]:
            self._read()
            if self.completion is not None or self.process.poll() is not None:
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
            assert self.completion is None, f"Application exited before visible {text!r}"
            self._read()
            # Preserve real fragmented reads/UTF-8/ANSI decoding without rebuilding
            # the entire screen for each tiny fragment. Bound ready-only work so
            # the unchanged deadline and process checks remain observable.
            for _ in range(min(63, 65536 // self.read_size - 1)):
                if not select.select([self.master], [], [], 0)[0]:
                    break
                self._read(0)
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
            self._acknowledge_completion(deadline)
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

    def _verify_owner(self) -> None:
        # An unreaped direct child reserves its PID. Its new session also pins
        # the only group to which this harness may send a real group signal.
        pid = self._owner_pid
        if (
            self.process.returncode is not None
            or self.process is not self._owner_process
            or self.process.pid != pid
            or pid <= 1
            or pid in {os.getpid(), os.getpgrp()}
            or os.getpgid(pid) != pid
            or os.getsid(pid) != pid
        ):
            raise RuntimeError("Cannot verify the live owned terminal session/group.")

    def _close_descriptor(self, descriptor: int) -> None:
        if descriptor in self._attempted_descriptors:
            return
        # Do not repeat close after an interrupted/failed syscall: the integer
        # may already have been released and reused for another resource.
        self._attempted_descriptors.add(descriptor)
        try:
            os.close(descriptor)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise
        self._closed_descriptors.add(descriptor)

    def _group_members(self, deadline: float) -> set[int]:
        self._verify_owner()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Terminal group observation exceeded its cleanup deadline.")
        # No command lines or credentials are collected. The live session
        # leader prevents its PGID from becoming an unrelated signal target.
        rows = subprocess.run(
            ["ps", "-axo", "pid=,pgid="],
            capture_output=True,
            check=True,
            timeout=min(0.5, remaining),
        ).stdout
        if len(rows) > 1024 * 1024:
            raise RuntimeError("Terminal group observation exceeded its size limit.")
        members = set()
        for row in rows.splitlines():
            pid, group = map(int, row.split())
            if group == self._owner_pid:
                members.add(pid)
        self._verify_owner()
        return members

    def _acknowledge_completion(self, deadline: float) -> None:
        if self._acknowledgement_attempted or self.completion is None:
            return
        if self.acknowledgement_write in self._attempted_descriptors:
            raise RuntimeError("Terminal acknowledgement pipe closed before acknowledgement.")
        if self._group_members(deadline) != {self._owner_pid}:
            return  # Other group members must finish before the guard is released.
        self._acknowledgement_attempted = True
        try:
            if os.write(self.acknowledgement_write, b"x") != 1:
                raise OSError("Terminal completion acknowledgement made no progress.")
        finally:
            self._close_descriptor(self.acknowledgement_write)
        self._acknowledged = True

    def _probe_group(self) -> str:
        # Signal zero never delivers a signal. After reaping, a reused number
        # can only produce a conservative live/denied result, never a new kill.
        try:
            os.killpg(self._owner_pid, 0)
        except ProcessLookupError:
            return "gone"
        except PermissionError:
            return "denied"
        return "live"

    def _signal_group(self, value: signal.Signals, deadline: float) -> str:
        self._verify_owner()
        try:
            os.killpg(self._owner_pid, value)
        except ProcessLookupError:
            return "gone"
        except PermissionError:
            if sys.platform == "darwin":
                for _ in range(5):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.01, remaining))
                    state = self._probe_group()
                    if state == "gone":
                        return state
                    if state == "live":
                        break
            raise  # A live group or persistent denial remains an actual failure.
        return "sent"

    def _read_cleanup(self, timeout: float) -> None:
        descriptors = []
        if not self._cleanup_master_eof:
            descriptors.append(self.master)
        if self.completion is None and not self._cleanup_completion_eof:
            descriptors.append(self.completion_read)
        if not descriptors:
            time.sleep(timeout)
            return
        ready, _, _ = select.select(descriptors, [], [], timeout)
        for descriptor in ready:
            try:
                data = os.read(descriptor, self.read_size if descriptor == self.master else 4096)
            except BlockingIOError:
                continue
            except OSError as error:
                if descriptor != self.master or error.errno != errno.EIO:
                    raise
                data = b""
            if descriptor == self.master:
                if not data:
                    self._cleanup_master_eof = True
                else:
                    remaining = max(0, 2 * 1024 * 1024 - len(self.transcript))
                    self.transcript.extend(data[:remaining])
                    if len(data) > remaining:
                        if not self._cleanup_discarded_bytes:
                            self._cleanup_errors.append(
                                RuntimeError("Terminal cleanup output exceeded its size limit.")
                            )
                        self._cleanup_discarded_bytes += len(data) - remaining
                continue
            if not data:
                self._cleanup_completion_eof = True
                continue
            self.completion_bytes.extend(data)
            if len(self.completion_bytes) > 4096:
                raise RuntimeError("Terminal restoration evidence exceeded its size limit.")
            if b"\n" in self.completion_bytes:
                completion = json.loads(self.completion_bytes)
                if not isinstance(completion, dict):
                    raise RuntimeError("Invalid terminal restoration evidence.")
                self.completion = completion

    def _wait_cleanup(self, deadline: float) -> bool:
        while True:
            remaining = deadline - time.monotonic()
            try:
                if self.process.poll() is not None:
                    return True
            except BaseException as error:
                if not self._cleanup_poll_failures:
                    self._cleanup_errors.append(error)
                self._cleanup_poll_failures += 1
                if remaining <= 0:
                    return False
                time.sleep(min(0.01, remaining))
                continue
            if remaining <= 0:
                return False
            try:
                self._read_cleanup(min(0.05, remaining))
            except BaseException as error:
                self._cleanup_errors.append(error)
                self._cleanup_master_eof = self._cleanup_completion_eof = True
            if time.monotonic() >= deadline:
                return False
            try:
                self._acknowledge_completion(deadline)
            except BaseException as error:
                if (
                    isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
                    and time.monotonic() >= deadline
                ):
                    # Expiry advances to the existing escalation phase; it is
                    # never interpreted as an empty or disappeared group.
                    return False
                self._cleanup_errors.append(error)
                self._acknowledgement_attempted = True
                # An acknowledgement failure must not strand the owner on read.
                try:
                    self._close_descriptor(self.acknowledgement_write)
                except BaseException as close_error:
                    self._cleanup_errors.append(close_error)

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
        if self.cleanup is not None:
            if self._cleanup_errors and value is None:
                raise BaseExceptionGroup("Terminal cleanup failed", self._cleanup_errors)
            return
        before = self.completion
        first_screen: list[str] | None = None
        try:
            first_screen = list(self.screen.display)
        except BaseException as error:
            self._cleanup_errors.append(error)
        stages: list[dict[str, object]] = []
        descriptors = tuple(self._descriptors)
        group = "unknown"
        deadline = time.monotonic() + 3
        try:
            # Parent copies must not keep the PTY alive while its owner exits.
            try:
                self._close_descriptor(self.slave)
            except BaseException as error:
                self._cleanup_errors.append(error)
            for descriptor in (self.master, self.completion_read):
                try:
                    os.set_blocking(descriptor, False)
                except BaseException as error:
                    self._cleanup_errors.append(error)
            for termination in (signal.SIGTERM, signal.SIGKILL):
                if self.process.returncode is not None:
                    break
                deadline = time.monotonic() + 3
                if termination is signal.SIGKILL:
                    # Successful escalation also kills the guard: its pipe can
                    # no longer acknowledge completion, even before poll reaps
                    # it. Preserve any real completion already received.
                    self._acknowledgement_attempted = True
                try:
                    outcome = self._signal_group(termination, deadline)
                    stages.append({"signal": termination.name, "outcome": outcome})
                except BaseException as error:
                    self._cleanup_errors.append(error)
                    stages.append({"signal": termination.name, "outcome": type(error).__name__})
                    # A denied group must remain a failure, but the known Popen
                    # child can still be reaped without an unchecked PGID kill.
                    if self.process is self._owner_process and self.process.pid == self._owner_pid:
                        try:
                            if termination is signal.SIGTERM:
                                self.process.terminate()
                            else:
                                self.process.kill()
                        except BaseException as owner_error:
                            self._cleanup_errors.append(owner_error)
                if termination is signal.SIGKILL:
                    try:
                        self._close_descriptor(self.acknowledgement_write)
                    except BaseException as close_error:
                        self._cleanup_errors.append(close_error)
                if self._wait_cleanup(deadline):
                    break
                stages.append({"wait_seconds": 3, "outcome": "timeout"})
            if self.process.poll() is None:
                self._cleanup_errors.append(
                    TimeoutError("The owned terminal session did not exit during cleanup.")
                )
            try:
                group = self._probe_group()
                for _ in range(5):
                    remaining = deadline - time.monotonic()
                    if group == "gone" or remaining <= 0:
                        break
                    time.sleep(min(0.01, remaining))
                    group = self._probe_group()
                if group != "gone":
                    self._cleanup_errors.append(
                        RuntimeError(
                            f"Terminal process-group disappearance is unverified: {group}."
                        )
                    )
            except BaseException as error:
                self._cleanup_errors.append(error)
        except BaseException as error:
            self._cleanup_errors.append(error)
        finally:
            for descriptor in descriptors:
                try:
                    self._close_descriptor(descriptor)
                except BaseException as error:
                    self._cleanup_errors.append(error)
        if any(descriptor not in self._closed_descriptors for descriptor in descriptors):
            self._cleanup_errors.append(
                RuntimeError("Closure of every owned terminal descriptor could not be confirmed.")
            )
        self.cleanup = {
            "status": "failed" if self._cleanup_errors else "complete",
            "owner_pid": self._owner_pid,
            "owner_reaped": self.process.returncode is not None,
            "owner_returncode": self.process.returncode,
            "group": group,
            "stages": stages,
            "acknowledged": self._acknowledged,
            "completion_observed": self.completion is not None,
            "descriptors_closed": all(
                descriptor in self._closed_descriptors for descriptor in descriptors
            ),
            "discarded_cleanup_bytes": self._cleanup_discarded_bytes,
            "poll_failures": self._cleanup_poll_failures,
            "errors": [
                {"type": type(error).__name__, "message": str(error)}
                for error in self._cleanup_errors
            ],
        }
        evidence: Path | None = None
        if kind is not None or self._cleanup_errors:
            try:
                output = ROOT / "artifacts/terminal"
                output.mkdir(parents=True, exist_ok=True)
                name = f"failure-{time.time_ns()}"
                (output / f"{name}.ansi").write_bytes(self.transcript)
                evidence = output / f"{name}.json"
                evidence.write_text(
                    json.dumps(
                        {
                            "result": "failed",
                            "error_type": kind.__name__ if kind is not None else None,
                            "body_error": str(value) if value is not None else None,
                            "sizes": self.sizes,
                            "screen": first_screen,
                            "terminal_completion_before_cleanup": before,
                            "terminal_completion": self.completion,
                            "cleanup": self.cleanup,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            except BaseException as error:
                self._cleanup_errors.append(error)
                self.cleanup["status"] = "failed"
                self.cleanup["evidence_error"] = str(error)
                evidence = None
        if value is not None:
            summary = (
                ", ".join(type(error).__name__ for error in self._cleanup_errors) or "complete"
            )
            value.add_note(f"Terminal cleanup: {summary}; evidence: {evidence or 'unavailable'}.")
        elif self._cleanup_errors:
            raise BaseExceptionGroup("Terminal cleanup failed", self._cleanup_errors)
