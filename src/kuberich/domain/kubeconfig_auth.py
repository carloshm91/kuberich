"""Bounded Basic credentials without prompting or exposing source material."""

import base64
from collections.abc import Mapping
from typing import Any

from kuberich.domain.connections import ConnectionProblem, ConnectionState
from kuberich.security.controls import escape_controls


def basic_credentials(user: Mapping[str, Any]) -> tuple[str, str] | None:
    """Empty optional strings mean no identity; one populated field is sufficient."""
    values = []
    for field in ("username", "password"):
        value = user.get(field)
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ConnectionProblem(
                ConnectionState.AUTH_ERROR, f"users.user.{field} must be a string."
            )
        if escape_controls(value) != value:
            raise ConnectionProblem(
                ConnectionState.AUTH_ERROR,
                f"users.user.{field} cannot contain control characters.",
            )
        values.append(value)
    username, password = values
    if not username and not password:
        return None
    if ":" in username:
        raise ConnectionProblem(
            ConnectionState.AUTH_ERROR, "users.user.username cannot contain a colon."
        )
    size = len((username + ":" + password).encode("utf-8"))
    if size > 65536:
        raise ConnectionProblem(
            ConnectionState.AUTH_ERROR,
            "users.user.username/password must contain at most 64 KiB of valid UTF-8.",
        )
    return username, password


def basic_header(credentials: tuple[str, str]) -> str:
    """Encode the already validated identity using the same UTF-8 bytes as client-go."""
    return "Basic " + base64.b64encode(":".join(credentials).encode("utf-8")).decode("ascii")
