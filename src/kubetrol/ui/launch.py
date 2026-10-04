"""Terminal ownership boundary for the ordinary CLI invocation."""

import logging
import sys

from kubetrol.config.schema import Settings
from kubetrol.errors import AppError, ExitCode
from kubetrol.ui.app import KubetrolApp


def run_terminal(settings: Settings, logger: logging.Logger) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AppError(
            "The terminal UI requires an interactive terminal; use kubetrol info for local diagnostics."
        )
    app = KubetrolApp(settings, logger)
    app.run()
    if app.return_code:
        raise AppError(
            "Terminal interface failed; check the local diagnostic log.", ExitCode.FAILURE
        )
