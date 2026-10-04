"""Stable, application-owned errors; messages must never contain raw input."""

from enum import IntEnum


class ExitCode(IntEnum):
    FAILURE = 1
    INVALID_INPUT = 2
    LOCAL_IO = 3
    INTERRUPTED = 130


class AppError(Exception):
    """A safe user message and a stable process result."""

    def __init__(self, message: str, code: ExitCode = ExitCode.INVALID_INPUT) -> None:
        super().__init__(message)
        self.code = code
