"""Literal command aliases; no shell parsing, interpolation or execution."""

import re
from collections.abc import Collection

from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

type Aliases = tuple[tuple[str, str], ...]
MAX_ALIAS_DEPTH = 8


def expand_alias(text: str, aliases: Aliases, blocked: Collection[str] = ()) -> str:
    lookup = dict(aliases)
    current = text.strip()
    seen: set[str] = set()
    while current:
        parts = current.split(maxsplit=1)
        name = parts[0].lower()
        if name not in lookup:
            return current
        if name in blocked:
            raise AppError(
                "Configured alias conflicts with a discovered resource; rename it or use :resource explicitly."
            )
        if name in seen:
            raise AppError("Recursive command aliases are not allowed.")
        if len(seen) >= MAX_ALIAS_DEPTH:
            raise AppError("Alias expansion exceeds eight steps.")
        seen.add(name)
        target = lookup[name]
        if len(parts) == 2:
            if len(target.split(maxsplit=1)) == 2:
                raise AppError(
                    "This alias already supplies arguments; omit the additional argument."
                )
            if len(parts[1]) > 256:
                raise AppError("Alias arguments must be at most 256 characters.")
            target += " " + parts[1]
        current = target
    return current


def parse_aliases(value: object, reserved: Collection[str] = ()) -> Aliases:
    if not isinstance(value, dict) or len(value) > 64:
        raise AppError("aliases must be a mapping with at most 64 entries.")
    parsed = []
    for name, target in value.items():
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name) is None:
            raise AppError(
                "Alias names use 1-32 lowercase ASCII letters, digits, underscores or hyphens, starting with a letter."
            )
        if name in reserved:
            raise AppError(
                "Aliases cannot replace built-in commands, resource names or reserved actions."
            )
        if not isinstance(target, str) or not 1 <= len(target) <= 256:
            raise AppError("Alias targets must be 1-256 characters.")
        validate_argument(target)
        target = target.strip().removeprefix(":").strip()
        parts = target.split(maxsplit=1)
        if (
            not parts
            or re.fullmatch(r"(?:[a-z][a-z0-9_.-]*(?:/[a-z0-9.-]+)?|\?)", parts[0], re.IGNORECASE)
            is None
        ):
            raise AppError(
                "Alias targets must begin with a command or Kubernetes resource reference."
            )
        parsed.append((name, parts[0].lower() + (" " + parts[1] if len(parts) == 2 else "")))
    result = tuple(sorted(parsed))
    for name, _ in result:
        expand_alias(name, result)
    return result
