"""Audited launch options whose owning product behavior has not shipped yet."""

from collections.abc import Mapping
from dataclasses import dataclass

from kuberich.errors import AppError, ExitCode


@dataclass(frozen=True)
class PendingOption:
    flags: tuple[str, ...]
    destination: str
    owner: str
    boolean: bool = False
    repeated: bool = False


PENDING_OPTIONS = (
    PendingOption(("--splashless",), "splashless", "startup splash", boolean=True),
    PendingOption(("--invert",), "invert", "theme inversion", boolean=True),
    PendingOption(("--screen-dump-dir",), "screen_dump_dir", "screen exports"),
)

CONNECTION_OPTIONS = (
    PendingOption(("--cluster",), "cluster", "connection overrides"),
    PendingOption(("--user",), "user", "connection overrides"),
    PendingOption(("--as",), "as_user", "impersonation transport"),
    PendingOption(("--as-group",), "as_group", "impersonation transport", repeated=True),
    PendingOption(
        ("--insecure-skip-tls-verify",),
        "insecure",
        "TLS transport",
        boolean=True,
    ),
    PendingOption(("--certificate-authority",), "certificate_authority", "TLS transport"),
    PendingOption(("--client-key",), "client_key", "TLS transport"),
    PendingOption(("--client-certificate",), "client_certificate", "TLS transport"),
    PendingOption(("--token",), "token", "credential overrides"),
)


def require_available(values: Mapping[str, object]) -> None:
    """Reject before reading files, running helpers or creating diagnostic logs."""
    if values["read_only"] is not None and values["write"] is not None:
        raise AppError("--readonly and --write are mutually exclusive.")
    if values["namespace"] is not None and values["all_namespaces"] is not None:
        raise AppError("--namespace and --all-namespaces are mutually exclusive.")
    if values["as_group"] is not None and values["as_user"] is None:
        raise AppError("--as-group requires --as.")
    if (values["client_key"] is None) != (values["client_certificate"] is None):
        raise AppError("--client-key and --client-certificate must be supplied together.")
    for option in PENDING_OPTIONS:
        if values[option.destination] is not None:
            raise AppError(
                f"{option.flags[0]} is unavailable in this development build; "
                f"requires {option.owner}.",
                ExitCode.UNAVAILABLE,
            )
