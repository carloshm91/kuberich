"""POSIX foreground process-group and terminal-attribute lease."""

import os
import signal
import termios
from contextlib import suppress
from types import TracebackType
from typing import Any

from kubetrol.errors import AppError


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
            raise AppError("Kubetrol must own the foreground terminal before handoff.")
        self.attributes = termios.tcgetattr(self.descriptor)
        return self

    def claim(self, group: int) -> None:
        _foreground(self.descriptor, group)
        # A child can read before tcsetpgrp and be stopped by SIGTTIN.
        with suppress(ProcessLookupError):
            os.killpg(group, signal.SIGCONT)

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        try:
            _foreground(self.descriptor, self.group)
        finally:
            termios.tcsetattr(self.descriptor, termios.TCSANOW, self.attributes)
