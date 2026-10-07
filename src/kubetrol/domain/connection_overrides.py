"""Bounded, immutable invocation overrides and explicit impersonation headers."""

import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote

from kubetrol.errors import AppError
from kubetrol.security.arguments import validate_argument

AUTH_FIELDS = (
    "token",
    "tokenFile",
    "exec",
    "auth-provider",
    "username",
    "password",
    "client-key",
    "client-key-data",
    "client-certificate",
    "client-certificate-data",
)
IMPERSONATION_FIELDS = ("as", "as-groups", "as-uid", "as-user-extra")
PATH_FIELDS = ("certificate_authority", "client_certificate", "client_key")


@dataclass(frozen=True, repr=False)
class ConnectionOverrides:
    cluster: str | None = None
    user: str | None = None
    token: str | None = None
    certificate_authority: str | None = None
    client_certificate: str | None = None
    client_key: str | None = None
    insecure: bool | None = None
    as_user: str | None = None
    as_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.cluster,
            self.user,
            self.token,
            self.certificate_authority,
            self.client_certificate,
            self.client_key,
            self.as_user,
        ):
            if value is not None:
                validate_argument(value)
        if self.insecure is not None and type(self.insecure) is not bool:
            raise AppError("TLS verification override must be true or false.")
        if not isinstance(self.as_groups, tuple) or len(self.as_groups) > 64:
            raise AppError(
                "Impersonation groups must be an immutable sequence of at most 64 values."
            )
        for group in self.as_groups:
            validate_argument(group)
        if self.as_groups and self.as_user is None:
            raise AppError("--as-group requires --as.")
        if (self.client_key is None) != (self.client_certificate is None):
            raise AppError("--client-key and --client-certificate must be supplied together.")
        if self.token is not None and self.client_certificate is not None:
            raise AppError("Token and client-certificate overrides are mutually exclusive.")
        if self.insecure is True and self.certificate_authority is not None:
            raise AppError("An explicit CA and insecure TLS override are mutually exclusive.")

    def capture_paths(self, directory: Path) -> "ConnectionOverrides":
        """Capture relative CLI paths before the UI, without reading credential files."""
        if not directory.is_absolute():
            raise AppError("Connection overrides require an absolute captured directory.")
        values = {}
        for name in PATH_FIELDS:
            value = getattr(self, name)
            if value is not None:
                path = Path(value).expanduser()
                values[name] = str(path if path.is_absolute() else directory / path)
        return replace(
            self,
            certificate_authority=values.get("certificate_authority"),
            client_certificate=values.get("client_certificate"),
            client_key=values.get("client_key"),
        )

    def apply(
        self, cluster: dict[str, Any], user: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Derive owned effective dictionaries; the loaded catalogue stays intact."""
        cluster, user = copy.deepcopy(cluster), copy.deepcopy(user)
        if self.insecure is True or self.certificate_authority is not None:
            cluster.pop("certificate-authority", None)
            cluster.pop("certificate-authority-data", None)
            cluster["insecure-skip-tls-verify"] = self.insecure is True
        elif self.insecure is False:
            cluster["insecure-skip-tls-verify"] = False
        if self.certificate_authority is not None:
            cluster["certificate-authority"] = self.certificate_authority
        if self.token is not None or self.client_certificate is not None:
            for name in AUTH_FIELDS:
                user.pop(name, None)
            if self.token is not None:
                user["token"] = self.token
            else:
                user["client-certificate"] = self.client_certificate
                user["client-key"] = self.client_key
        if self.as_user is not None:
            # An explicit subject owns its complete identity, including groups.
            for name in IMPERSONATION_FIELDS:
                user.pop(name, None)
            user["as"] = self.as_user
            user["as-groups"] = list(self.as_groups)
        return cluster, user


def _values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 64:
        raise AppError("Impersonation values must be a list of at most 64 strings.")
    return tuple(validate_argument(item) for item in value)


def impersonation_headers(user: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Retain repeated groups/extras; validate before any authentication or request."""
    subject, uid = user.get("as"), user.get("as-uid")
    groups = _values(user.get("as-groups", []))
    extras = user.get("as-user-extra", {})
    if not isinstance(extras, dict) or len(extras) > 16:
        raise AppError("Impersonation extras must be a bounded string/list mapping.")
    if subject is None:
        if groups or uid is not None or extras:
            raise AppError("Impersonation attributes require an explicit subject.")
        return ()
    headers = [("Impersonate-User", validate_argument(subject))]
    headers.extend(("Impersonate-Group", group) for group in groups)
    if uid is not None:
        headers.append(("Impersonate-Uid", validate_argument(uid)))
    for key, values in extras.items():
        name = "Impersonate-Extra-" + quote(validate_argument(key).lower(), safe="")
        headers.extend((name, value) for value in _values(values))
    if sum(len(name.encode()) + len(value.encode()) for name, value in headers) > 65536:
        raise AppError("Impersonation headers exceed the bounded 64 KiB budget.")
    return tuple(headers)
