"""Per-context settings; a context may make a session stricter, never looser."""

from collections.abc import Collection
from dataclasses import dataclass

from kuberich.config.schema import ConfigDocument, Settings
from kuberich.errors import AppError

FIELDS = frozenset({"read_only", "refresh_seconds"})


@dataclass(frozen=True)
class ContextOverride:
    read_only: bool = False
    refresh_seconds: float | None = None


@dataclass(frozen=True)
class ContextSettings:
    contexts: tuple[tuple[str, ContextOverride], ...] = ()

    def effective(
        self, settings: Settings, pinned: Collection[str], context: str | None
    ) -> tuple[bool, float]:
        """Command line and environment > context > preference file > defaults."""
        override = dict(self.contexts).get(context or "", ContextOverride())
        refresh = (
            settings.refresh_seconds
            if "refresh_seconds" in pinned or override.refresh_seconds is None
            else override.refresh_seconds
        )
        return override.read_only, refresh


def parse_context_settings(value: object) -> ContextSettings:
    if not isinstance(value, dict) or value.keys() - {"schema_version", "contexts"}:
        raise AppError("context_settings must contain only schema_version and contexts.")
    version = value.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise AppError("Unsupported context_settings.schema_version; use version 1.")
    contexts = value.get("contexts", {})
    if not isinstance(contexts, dict) or len(contexts) > 128:
        raise AppError("context_settings.contexts allows at most 128 contexts.")
    parsed = []
    for name, fields in contexts.items():
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 253
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)
        ):
            raise AppError("Context names must be bounded text without controls.")
        if not isinstance(fields, dict) or not fields or fields.keys() - FIELDS:
            raise AppError("Each context accepts only read_only and refresh_seconds.")
        if "read_only" in fields and fields["read_only"] is not True:
            raise AppError("A context can set read_only: true; it cannot turn read-only off.")
        value = fields.get("refresh_seconds")
        refresh = None
        if value is not None:
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0.1 <= value <= 3600
            ):
                raise AppError("Context refresh_seconds must be a number between 0.1 and 3600.")
            refresh = float(value)
        parsed.append((name, ContextOverride("read_only" in fields, refresh)))
    return ContextSettings(tuple(sorted(parsed, key=lambda item: item[0])))


def context_settings_from(document: ConfigDocument) -> ContextSettings:
    return parse_context_settings(document.extensions.get("context_settings", {}))
