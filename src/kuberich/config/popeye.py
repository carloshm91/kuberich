"""Offline validation for an explicitly selected, trusted local Popeye program."""

from dataclasses import dataclass
from pathlib import Path

from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

# Canonical linter names from the pinned v0.22.1 internal/glossary.go.
POPEYE_SECTIONS = frozenset(
    {
        "cluster",
        "configmaps",
        "endpoints",
        "namespaces",
        "nodes",
        "persistentvolumes",
        "persistentvolumeclaims",
        "pods",
        "secrets",
        "serviceaccounts",
        "services",
        "deployments",
        "daemonsets",
        "replicasets",
        "statefulsets",
        "clusterroles",
        "clusterrolebindings",
        "roles",
        "rolebindings",
        "ingresses",
        "networkpolicies",
        "poddisruptionbudgets",
        "horizontalpodautoscalers",
        "podmetrics",
        "nodemetrics",
        "cronjobs",
        "jobs",
        "gateways",
        "gatewayclasses",
        "httproutes",
    }
)


@dataclass(frozen=True, slots=True)
class PopeyeSettings:
    executable: Path
    sections: tuple[str, ...] = ("pods",)
    timeout_seconds: int = 60
    trusted_read_only: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.executable, Path)
            or not self.executable.is_absolute()
            or len(str(self.executable)) > 4096
        ):
            raise AppError("Popeye executable must be an absolute path of at most 4096 characters.")
        validate_argument(str(self.executable))
        if (
            not isinstance(self.sections, tuple)
            or not 1 <= len(self.sections) <= 16
            or any(
                not isinstance(item, str) or item not in POPEYE_SECTIONS for item in self.sections
            )
            or len(set(self.sections)) != len(self.sections)
        ):
            raise AppError(
                "Popeye sections require 1 to 16 unique supported canonical linter names."
            )
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 120:
            raise AppError("Popeye timeout_seconds must be an integer between 1 and 120.")
        if type(self.trusted_read_only) is not bool:
            raise AppError("Popeye trusted_read_only must be true or false.")


def parse_popeye_settings(value: object) -> PopeyeSettings | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.keys() - {
        "executable",
        "sections",
        "timeout_seconds",
        "trusted_read_only",
    }:
        raise AppError(
            "observability.popeye accepts executable, sections, timeout_seconds and trusted_read_only."
        )
    executable, sections = value.get("executable"), value.get("sections", ["pods"])
    if not isinstance(executable, str) or not isinstance(sections, list):
        raise AppError("Popeye requires an executable path string and a list of sections.")
    return PopeyeSettings(
        Path(executable),
        tuple(sections),
        value.get("timeout_seconds", 60),
        value.get("trusted_read_only", False),
    )


def serialize_popeye_settings(settings: PopeyeSettings | None) -> dict[str, object] | None:
    if settings is None:
        return None
    return {
        "executable": str(settings.executable),
        "sections": list(settings.sections),
        "timeout_seconds": settings.timeout_seconds,
        "trusted_read_only": settings.trusted_read_only,
    }
