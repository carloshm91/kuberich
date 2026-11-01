"""Lightweight CLI-to-TUI launch seam keeping Textual imports out of offline commands."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

    from kuberich.config.schema import ConfigDocument, Settings
    from kuberich.domain.connections import ConnectionRequest
    from kuberich.services.appearance import PreferenceSource
    from kuberich.services.commands import ResolvedCommand
    from kuberich.ui.presentation import Presentation


def version(distribution: str) -> str:
    from importlib.metadata import version as installed_version

    return installed_version(distribution)


def read_config(path: Path, *, missing_ok: bool = True) -> ConfigDocument:
    from kuberich.config.store import read_config as read

    return read(path, missing_ok=missing_ok)


def diagnostic_logging(path: Path, level: str) -> AbstractContextManager[Logger]:
    from kuberich.diagnostics.logging import diagnostic_logging as logging_context

    return logging_context(path, level)


def run_terminal(
    settings: Settings,
    logger: Logger,
    *,
    presentation: Presentation | None = None,
    initial_command: ResolvedCommand | None = None,
    connection: ConnectionRequest | None = None,
    preferences: PreferenceSource | None = None,
) -> None:
    from kuberich.domain.connections import DEFAULT_CONNECTION
    from kuberich.services.commands import Command
    from kuberich.ui import launch
    from kuberich.ui.presentation import DEFAULT_PRESENTATION

    launch.run_terminal(
        settings,
        logger,
        presentation=DEFAULT_PRESENTATION if presentation is None else presentation,
        initial_command=Command.EMPTY if initial_command is None else initial_command,
        connection=DEFAULT_CONNECTION if connection is None else connection,
        preferences=preferences,
    )
