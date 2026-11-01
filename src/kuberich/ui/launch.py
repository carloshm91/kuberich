"""Terminal ownership boundary for the ordinary CLI invocation."""

import logging
import os
import sys
from pathlib import Path

from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import DEFAULT_CONNECTION, ConnectionRequest
from kuberich.errors import AppError, ExitCode
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command, ResolvedCommand
from kuberich.ui.app import KubeRichApp as KubeRichApp
from kuberich.ui.presentation import DEFAULT_PRESENTATION, Presentation


def _fatal_error(logger: logging.Logger, error: Exception | None = None) -> AppError:
    from kuberich.diagnostics.reports import write_report

    log_path = next(
        (
            Path(handler.baseFilename)
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler)
        ),
        None,
    )
    try:
        path = write_report(config_status="unavailable", log_path=log_path, error=error)
    except Exception:
        message = "Terminal interface failed; terminal restored. A diagnostic report could not be created."
    else:
        message = f"Terminal interface failed; terminal restored. Redacted crash report: {path}"
    return AppError(message, ExitCode.FAILURE)


def run_terminal(
    settings: Settings,
    logger: logging.Logger,
    *,
    presentation: Presentation = DEFAULT_PRESENTATION,
    initial_command: ResolvedCommand = Command.EMPTY,
    connection: ConnectionRequest = DEFAULT_CONNECTION,
    preferences: PreferenceSource | None = None,
) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AppError(
            "The terminal UI requires an interactive terminal; use kuberich info for local diagnostics."
        )
    catalog = load_catalog(connection, os.environ)
    try:
        app = KubeRichApp(
            settings,
            logger,
            presentation=presentation,
            initial_command=initial_command,
            catalog=catalog,
            connection=connection,
            preferences=preferences,
        )
        app.run(mouse=app.navigation.mouse)
    except Exception as error:
        # Textual restores its terminal context before run returns or raises.
        raise _fatal_error(logger, error) from None
    if app.return_code == ExitCode.HANGUP:
        raise AppError("Terminal disconnected.", ExitCode.HANGUP)
    if app.return_code == ExitCode.TERMINATED:
        raise AppError("Terminal session terminated; terminal restored.", ExitCode.TERMINATED)
    if app.return_code:
        raise _fatal_error(logger)
