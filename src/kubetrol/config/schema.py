"""Versioned, typed preferences with strict validation and unknown-field retention."""

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from kubetrol.errors import AppError
from kubetrol.security.arguments import freeze_arguments

SCHEMA_VERSION = 1
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
FIELDS = frozenset({"theme", "refresh_seconds", "read_only", "log_level", "log_file", "shell"})


def shell_arguments(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 32:
        raise AppError("shell must be an argument list with 1-32 strings.")
    if not all(isinstance(item, str) for item in value):
        raise AppError("shell arguments must be strings.")
    try:
        arguments = freeze_arguments(value)
    except AppError:
        raise AppError("shell arguments must be bounded nonempty text without controls.") from None
    if arguments[0].startswith("-"):
        raise AppError("shell executable cannot be a command option.")
    return arguments


@dataclass(frozen=True)
class Settings:
    theme: str = "textual-dark"
    refresh_seconds: float = 2.0
    read_only: bool = False
    log_level: str = "WARNING"
    log_file: str | None = None
    shell: tuple[str, ...] = ("sh",)

    def __post_init__(self) -> None:
        object.__setattr__(self, "shell", shell_arguments(self.shell))
        if not isinstance(self.theme, str) or not re.fullmatch(
            r"[a-zA-Z][\w-]{0,63}", self.theme, re.ASCII
        ):
            raise AppError("theme must be a theme identifier (1-64 ASCII characters).")
        if (
            type(self.refresh_seconds) not in {int, float}
            or not 0.1 <= self.refresh_seconds <= 3600
        ):
            raise AppError("refresh_seconds must be a finite number between 0.1 and 3600.")
        if type(self.read_only) is not bool:
            raise AppError("read_only must be true or false.")
        if not isinstance(self.log_level, str) or self.log_level not in LOG_LEVELS:
            raise AppError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
        if self.log_file is not None and (
            not isinstance(self.log_file, str)
            or not self.log_file.strip()
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in self.log_file)
        ):
            raise AppError("log_file must be null or a nonempty path without control characters.")

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


def settings_from(values: Mapping[str, object]) -> Settings:
    """Validate input types before constructing an annotated dataclass."""
    defaults = Settings()
    theme = values.get("theme", defaults.theme)
    refresh = values.get("refresh_seconds", defaults.refresh_seconds)
    read_only = values.get("read_only", defaults.read_only)
    level = values.get("log_level", defaults.log_level)
    log_file = values.get("log_file", defaults.log_file)
    if not isinstance(theme, str):
        raise AppError("theme must be a string.")
    if not isinstance(refresh, (int, float)) or isinstance(refresh, bool):
        raise AppError("refresh_seconds must be a number.")
    if not isinstance(read_only, bool):
        raise AppError("read_only must be true or false.")
    if not isinstance(level, str):
        raise AppError("log_level must be a string.")
    if log_file is not None and not isinstance(log_file, str):
        raise AppError("log_file must be null or a path string.")
    try:
        seconds = float(refresh)
    except OverflowError:
        raise AppError("refresh_seconds must be a finite number between 0.1 and 3600.") from None
    return Settings(
        theme,
        seconds,
        read_only,
        level.upper(),
        log_file,
        shell_arguments(values.get("shell", defaults.shell)),
    )


@dataclass(frozen=True)
class ConfigDocument:
    settings: Settings = field(default_factory=Settings)
    unknown: dict[str, object] = field(default_factory=dict)
    migrated: bool = False

    def to_mapping(self) -> dict[str, object]:
        return {**self.unknown, "schema_version": SCHEMA_VERSION, **self.settings.to_mapping()}


def parse_document(values: Mapping[str, object]) -> ConfigDocument:
    """Migrate versionless/v0 preferences in memory; never rewrite on load."""
    data = dict(values)
    if {"current-context", "clusters", "contexts", "users"} & data.keys() or data.get(
        "kind"
    ) == "Config":
        raise AppError("This is a kubeconfig; --config accepts Kubetrol preferences only.")
    schema = data.pop("schema_version", 0)
    if type(schema) is not int or schema not in {0, SCHEMA_VERSION}:
        raise AppError("Unsupported schema_version; this build accepts versions 0 and 1.")
    if schema == 0:
        for old, new in (("refresh", "refresh_seconds"), ("readonly", "read_only")):
            if old in data:
                if new in data:
                    raise AppError("Legacy and current preference names cannot be combined.")
                data[new] = data.pop(old)
    settings = settings_from(data)
    unknown = {key: value for key, value in data.items() if key not in FIELDS}
    return ConfigDocument(settings, unknown, migrated=schema == 0)


ENV_FIELDS = {
    "KUBETROL_THEME": "theme",
    "KUBETROL_REFRESH": "refresh_seconds",
    "KUBETROL_READONLY": "read_only",
    "KUBETROL_LOG_LEVEL": "log_level",
    "KUBETROL_LOG_FILE": "log_file",
}


def resolve_settings(
    document: ConfigDocument,
    environment: Mapping[str, str],
    overrides: Mapping[str, object],
) -> Settings:
    """CLI > application environment > file > defaults; validate every layer."""
    data = document.settings.to_mapping()
    for variable, name in ENV_FIELDS.items():
        if variable not in environment:
            continue
        value: object = environment[variable]
        if name == "refresh_seconds":
            try:
                value = float(environment[variable])
            except ValueError:
                raise AppError("KUBETROL_REFRESH must be a number.") from None
        elif name == "read_only":
            text = environment[variable].lower()
            if text not in {"true", "false"}:
                raise AppError("KUBETROL_READONLY must be true or false.")
            value = text == "true"
        data[name] = value
    settings_from(data)
    if not overrides.keys() <= FIELDS:
        raise AppError("Unknown preference override.")
    data.update(overrides)
    return settings_from(data)
