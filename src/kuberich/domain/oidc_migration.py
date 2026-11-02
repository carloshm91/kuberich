"""Generate a reviewable OIDC exec fragment without copying tokens or doing I/O."""

import base64
import binascii
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

CLIENT_SECRET_PLACEHOLDER = "REPLACE_WITH_CLIENT_SECRET_IN_PRIVATE_CONFIG"


def _text(config: dict[str, Any], field: str, *, required: bool = False) -> str | None:
    value = config.get(field)
    if value is None or value == "":
        if required:
            raise AppError(f"users.user.auth-provider.config.{field} is required for migration.")
        return None
    try:
        return validate_argument(value)
    except AppError:
        raise AppError(
            f"users.user.auth-provider.config.{field} must be bounded text without controls."
        ) from None


def oidc_exec_fragment(provider: object, directory: Path) -> dict[str, Any]:
    """Return only reviewed metadata and a fixed placeholder for a required secret."""
    if not isinstance(provider, dict) or provider.get("name") != "oidc":
        raise AppError("users.user.auth-provider.name must be oidc for this migration command.")
    config = provider.get("config")
    if (
        not isinstance(config, dict)
        or len(config) > 32
        or any(
            not isinstance(key, str) or (value is not None and not isinstance(value, str))
            for key, value in config.items()
        )
    ):
        raise AppError("users.user.auth-provider.config must contain at most 32 string values.")
    issuer = _text(config, "idp-issuer-url", required=True)
    client_id = _text(config, "client-id", required=True)
    assert issuer is not None and client_id is not None
    try:
        parsed = urlsplit(issuer)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.port != 0
        )
    except ValueError:
        valid = False
    if not valid:
        raise AppError(
            "users.user.auth-provider.config.idp-issuer-url must be HTTPS without credentials, query or fragment."
        )
    arguments = [
        "get-token",
        "--oidc-issuer-url=" + issuer,
        "--oidc-client-id=" + client_id,
    ]
    if config.get("client-secret"):
        arguments.append("--oidc-client-secret=" + CLIENT_SECRET_PLACEHOLDER)
    inline = _text(config, "idp-certificate-authority-data")
    filename = _text(config, "idp-certificate-authority")
    if inline is not None:
        try:
            material = base64.b64decode(inline, validate=True)
            valid_ca = (
                material.lstrip().startswith(b"-----BEGIN CERTIFICATE-----")
                and b"-----END CERTIFICATE-----" in material
                and b"PRIVATE KEY" not in material
            )
        except (ValueError, binascii.Error):
            valid_ca = False
        if not valid_ca:
            raise AppError(
                "users.user.auth-provider.config.idp-certificate-authority-data must be bounded base64 PEM certificates."
            )
        arguments.append("--certificate-authority-data=" + inline)
    elif filename is not None:
        if not directory.is_absolute():
            raise AppError("OIDC migration requires the original absolute kubeconfig directory.")
        arguments.append("--certificate-authority=" + str(directory / filename))
    try:
        for argument in arguments:
            validate_argument(argument)
    except AppError:
        raise AppError(
            "Generated users.user.exec.args exceed the supported argument limit."
        ) from None
    return {
        "exec": {
            "apiVersion": "client.authentication.k8s.io/v1",
            "command": "kubelogin",
            "args": arguments,
            "interactiveMode": "IfAvailable",
            "provideClusterInfo": False,
        }
    }
