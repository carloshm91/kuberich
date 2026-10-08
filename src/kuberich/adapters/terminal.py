"""POSIX foreground process-group and terminal-attribute lease."""

import errno
import os
import signal
import termios
from contextlib import suppress
from types import TracebackType
from typing import Any

from kuberich.errors import AppError


def current_terminal_size() -> tuple[int, int] | None:
    """Read the live native TTY instead of trusting a queued resize snapshot."""
    try:
        size = os.get_terminal_size(0)
    except OSError:
        return None
    return (size.columns, size.lines) if size.columns > 0 and size.lines > 0 else None


def _revoked(descriptor: int) -> bool:
    try:
        termios.tcgetattr(descriptor)
    except termios.error as error:
        if error.args[0] in (errno.EIO, errno.ENXIO, errno.ENOTTY):
            return True
        raise
    return False


def _revoked_output(descriptor: int) -> bool:
    if _revoked(descriptor):
        return True
    # Darwin can still return attributes after hangup while rejecting writes.
    # Probe the captured output without emitting bytes or stopping a background
    # process group with SIGTTOU; unexpected driver errors remain visible.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
    try:
        os.write(descriptor, b"")
    except OSError as error:
        if error.errno in (errno.EIO, errno.ENXIO, errno.ENOTTY):
            return True
        raise
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
    return False


class RevokedTerminalOutput:
    """Discard shutdown writes only to the same, demonstrably revoked TTY.

    A disconnected SSH PTY cannot receive restoration bytes. Leaving buffered
    output attached to it also makes CPython replace the requested exit code
    with 120 during interpreter finalization. Live terminals and non-TTY
    streams must keep their original descriptors.
    """

    def __init__(self, descriptors: tuple[int, ...] = (1, 2)) -> None:
        self.terminals = {
            descriptor: os.fstat(descriptor) for descriptor in descriptors if os.isatty(descriptor)
        }

    def discard_revoked(self) -> None:
        for descriptor, original in self.terminals.items():
            try:
                current = os.fstat(descriptor)
            except OSError as error:
                if error.errno == errno.EBADF:
                    continue
                raise
            if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                continue
            if _revoked_output(descriptor):
                sink = os.open(os.devnull, os.O_WRONLY)
                try:
                    os.dup2(sink, descriptor)
                finally:
                    os.close(sink)


def _foreground(descriptor: int, group: int) -> None:
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
    try:
        os.tcsetpgrp(descriptor, group)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class TerminalLease:
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor
        self.group = 0
        self.attributes: list[Any] = []

    def __enter__(self) -> "TerminalLease":
        if not os.isatty(self.descriptor):
            raise AppError("Terminal handoff requires a real interactive terminal.")
        self.group = os.tcgetpgrp(self.descriptor)
        if self.group != os.getpgrp():
            raise AppError("KubeRich must own the foreground terminal before handoff.")
        self.attributes = termios.tcgetattr(self.descriptor)
        return self

    def claim(self, group: int) -> None:
        _foreground(self.descriptor, group)
        # A child can read before tcsetpgrp and be stopped by SIGTTIN.
        with suppress(ProcessLookupError):
            os.killpg(group, signal.SIGCONT)

    def present(self, heading: str) -> None:
        """Clear the visible screen and introduce a native handoff, preserving scrollback."""
        data = ("\x1b[H\x1b[2J" + heading).encode("utf-8")
        try:
            while data:
                count = os.write(self.descriptor, data)
                if count == 0:
                    raise OSError("Terminal write made no progress.")
                data = data[count:]
        except OSError:
            raise AppError(
                "Cannot prepare the container shell screen. Check the terminal."
            ) from None

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        try:
            try:
                _foreground(self.descriptor, self.group)
            finally:
                termios.tcsetattr(self.descriptor, termios.TCSANOW, self.attributes)
        except (OSError, termios.error):
            # A lost SSH terminal has no attributes or foreground group left
            # to restore. Preserve cancellation after reaping the child, while
            # still surfacing restoration failures on a live terminal.
            if not _revoked(self.descriptor):
                raise
