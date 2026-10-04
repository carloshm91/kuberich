"""Capture explicit process arguments without shell parsing or silent normalization."""

from collections.abc import Sequence

from kubetrol.errors import AppError
from kubetrol.security.controls import escape_controls

MAX_ARGUMENT_CHARACTERS = 8192


def validate_argument(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ARGUMENT_CHARACTERS:
        raise AppError("Command arguments must be nonempty, bounded text.")
    if escape_controls(value) != value:
        raise AppError("Command arguments contain unsupported control characters.")
    return value


def freeze_arguments(values: Sequence[str]) -> tuple[str, ...]:
    """Snapshot an argv, never a shell command; builders still own option semantics."""
    if isinstance(values, (str, bytes)) or not values:
        raise AppError("Commands require an explicit argument sequence.")
    return tuple(validate_argument(value) for value in values)
