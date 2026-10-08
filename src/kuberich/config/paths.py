"""Platform paths without creating directories or reading kubeconfig."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_log_path

from kuberich.config.schema import Settings
from kuberich.errors import AppError


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
    migration_target: Path | None = None


def config_location(argument: str | None, environment: Mapping[str, str]) -> ConfigLocation:
    if argument is not None:
        return ConfigLocation(preference_path(argument), True)
    if "KUBERICH_CONFIG" in environment:
        return ConfigLocation(preference_path(environment["KUBERICH_CONFIG"]), True)
    if "KUBETROL_CONFIG" in environment:
        return ConfigLocation(preference_path(environment["KUBETROL_CONFIG"]), True)
    current = user_config_path("kuberich", appauthor=False) / "config.yaml"
    if current.exists() or current.is_symlink():
        return ConfigLocation(current, False)
    legacy = user_config_path("kubetrol", appauthor=False) / "config.yaml"
    if legacy.exists() or legacy.is_symlink():
        return ConfigLocation(legacy, False, current)
    return ConfigLocation(current, False)


def log_location(settings: Settings, config_file: Path, *, from_file: bool) -> Path:
    if settings.log_file is None:
        return user_log_path("kuberich", appauthor=False) / "kuberich.log"
    path = preference_path(settings.log_file)
    if from_file and not Path(settings.log_file).expanduser().is_absolute():
        path = config_file.parent / Path(settings.log_file).expanduser()
    return path
