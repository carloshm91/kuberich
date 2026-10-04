"""Terminal ownership boundary for the ordinary CLI invocation."""

import logging
import sys

from kubetrol.config.schema import Settings
from kubetrol.errors import AppError, ExitCode
from kubetrol.services.commands import Command
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.presentation import DEFAULT_PRESENTATION, Presentation


def run_terminal(
    settings: Settings,
    logger: logging.Logger,
    *,
    presentation: Presentation = DEFAULT_PRESENTATION,
    initial_command: Command = Command.EMPTY,
) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AppError(
            "The terminal UI requires an interactive terminal; use kubetrol info for local diagnostics."
        )
    app = KubetrolApp(settings, logger, presentation=presentation, initial_command=initial_command)
    app.run()
    if app.return_code:
        raise AppError(
            "Terminal interface failed; check the local diagnostic log.", ExitCode.FAILURE
        )
