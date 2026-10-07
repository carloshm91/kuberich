"""Own POSIX shutdown requests while the native workspace is mounted."""

import signal
from types import FrameType
from typing import Any

from textual.app import App

from kubetrol.adapters.terminal import RevokedTerminalOutput
from kubetrol.errors import ExitCode

TERMINAL_SIGNALS = (signal.SIGHUP, signal.SIGTERM)


def terminal_exit_code(signum: int) -> ExitCode:
    return ExitCode.HANGUP if signum == signal.SIGHUP else ExitCode.TERMINATED


class TerminalSignals:
    def __init__(self, app: App[Any]) -> None:
        self.app = app
        self.previous: dict[int, signal._HANDLER] = {}
        self.requested: ExitCode | None = None
        self.output = RevokedTerminalOutput()

    def install(self) -> None:
        self.previous = {signum: signal.getsignal(signum) for signum in TERMINAL_SIGNALS}
        try:
            for signum in TERMINAL_SIGNALS:
                signal.signal(signum, self.request)
        except BaseException:
            self.restore()
            raise

    def request(self, signum: int, frame: FrameType | None) -> None:
        if signum == signal.SIGHUP:
            self.output.discard_revoked()
        if self.requested is None:
            self.requested = terminal_exit_code(signum)
            self.app.exit(return_code=self.requested)

    def restore(self) -> None:
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)
        self.previous.clear()
