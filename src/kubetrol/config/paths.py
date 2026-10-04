"""Platform paths without creating directories or reading kubeconfig."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_log_path

from kubetrol.config.schema import Settings
from kubetrol.errors import AppError


def preference_path(value: str) -> Path:
    if not value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise AppError("Preference paths must be nonempty and contain no control characters.")
    try:
        return Path(value).expanduser().absolute()
    except (OSError, RuntimeError):
        raise AppError("Cannot resolve preference path.") from None


@dataclass(frozen=True)
class ConfigLocation:
    path: Path
    explicit: bool


def config_location(argument: str | None, environment: Mapping[str, str]) -> ConfigLocation:
    if argument is not None:
        return ConfigLocation(preference_path(argument), True)
    if "KUBETROL_CONFIG" in environment:
        return ConfigLocation(preference_path(environment["KUBETROL_CONFIG"]), True)
    return ConfigLocation(user_config_path("kubetrol", appauthor=False) / "config.yaml", False)


def log_location(settings: Settings, config_file: Path, *, from_file: bool) -> Path:
    if settings.log_file is None:
        return user_log_path("kubetrol", appauthor=False) / "kubetrol.log"
    path = preference_path(settings.log_file)
    if from_file and not Path(settings.log_file).expanduser().is_absolute():
        path = config_file.parent / Path(settings.log_file).expanduser()
    return path
