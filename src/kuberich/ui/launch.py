"""Terminal ownership boundary for the ordinary CLI invocation."""

import logging
import os
import sys

from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import DEFAULT_CONNECTION, ConnectionRequest
from kuberich.errors import AppError, ExitCode
from kuberich.services.commands import Command, ResolvedCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.presentation import DEFAULT_PRESENTATION, Presentation


def run_terminal(
    settings: Settings,
    logger: logging.Logger,
    *,
    presentation: Presentation = DEFAULT_PRESENTATION,
    initial_command: ResolvedCommand = Command.EMPTY,
    connection: ConnectionRequest = DEFAULT_CONNECTION,
) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AppError(
            "The terminal UI requires an interactive terminal; use kuberich info for local diagnostics."
        )
    catalog = load_catalog(connection, os.environ)
    app = KubeRichApp(
        settings,
        logger,
        presentation=presentation,
        initial_command=initial_command,
        catalog=catalog,
        connection=connection,
    )
    app.run()
    if app.return_code == ExitCode.HANGUP:
        raise AppError("Terminal disconnected.", ExitCode.HANGUP)
    if app.return_code == ExitCode.TERMINATED:
        raise AppError("Terminal session terminated; terminal restored.", ExitCode.TERMINATED)
    if app.return_code:
        raise AppError(
            "Terminal interface failed; check the local diagnostic log.", ExitCode.FAILURE
        )
