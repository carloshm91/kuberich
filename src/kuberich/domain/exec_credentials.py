"""Private, deterministic ExecCredential response validation."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

from kuberich.domain.credential_helpers import bearer_token
from kuberich.errors import AppError


@dataclass(frozen=True, repr=False)
class CredentialResult:
    token: str | None
    certificate: tuple[str, str] | None
    expiration: datetime | None


def encrypted_key(material: bytes) -> bool:
    """Refuse OpenSSL's implicit terminal passphrase callback before TLS loading."""
    return b"-----BEGIN ENCRYPTED PRIVATE KEY-----" in material or any(
        line.strip().startswith(b"Proc-Type:") and b"ENCRYPTED" in line
        for line in material.splitlines()
    )


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError("ExecCredential fields must be objects.")
    return value


def _pem(value: Any, marker: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 256 * 1024
        or not value.startswith("-----BEGIN ")
        or marker not in value
        or "-----END " not in value
        or "ENCRYPTED" in value
        or any(ord(character) < 32 and character not in "\n\r\t" for character in value)
    ):
        raise AppError("Exec certificate credentials must contain bounded PEM material.")
    return value


def _constant(value: str) -> NoReturn:
    raise AppError("Nonfinite JSON constants are invalid credentials.")


def parse_credentials(output: bytes, version: str, now: datetime) -> CredentialResult:
    """Validate one response without exposing private values in errors/repr."""
    if len(output) > 1024 * 1024:
        raise AppError("ExecCredential response exceeds its size limit.")
    response = _object(json.loads(output, parse_constant=_constant))
    if response.get("kind") != "ExecCredential" or response.get("apiVersion") != version:
        raise AppError("Credential helper returned a mismatched ExecCredential kind/version.")
    status = _object(response.get("status"))
    token = status.get("token")
    certificate = status.get("clientCertificateData")
    key = status.get("clientKeyData")
    if token is not None and (certificate is not None or key is not None):
        raise AppError("ExecCredential must return a token or a certificate/key pair.")
    pair = None
    if certificate is not None or key is not None:
        pair = (_pem(certificate, "CERTIFICATE"), _pem(key, "PRIVATE KEY"))
        token = None
    else:
        token = bearer_token(token)
    expiration = status.get("expirationTimestamp")
    expires = None
    if expiration is not None:
        if not isinstance(expiration, str):
            raise AppError("Credential expiration must be an RFC3339 timestamp.")
        expires = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= now:
            raise AppError("Credential helper returned expired or timezone-less credentials.")
    return CredentialResult(token, pair, expires)
