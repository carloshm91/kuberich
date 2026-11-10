"""Bounded metadata-only recovery records; records never confer ownership."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from kuberich.domain.connections import namespace_name
from kuberich.domain.resources import api_segment
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_RECORDS = 100
MAX_JOURNAL_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024
RESULT_CODES = frozenset(
    {
        "prepared",
        "created",
        "create_uncertain",
        "create_rejected",
        "running",
        "ready",
        "completed",
        "interrupted",
        "cancelled",
        "timeout",
        "startup_timeout",
        "session_timeout",
        "admission_drift",
        "denied",
        "auth_error",
        "not_found",
        "conflict",
        "unreachable",
        "cleanup_pending",
        "delete_denied",
        "delete_uncertain",
        "deletion_timeout",
        "persistence_failed",
        "stale",
        "failed",
        "recovered",
        "deleted",
        "absent",
        "replaced",
    }
)


class JournalState(StrEnum):
    PREPARED = "prepared"
    CREATE_UNCERTAIN = "create_uncertain"
    OWNED = "owned"
    CLEANUP_PENDING = "cleanup_pending"


def _text(value: str, limit: int) -> None:
    validate_argument(value)
    if len(value) > limit:
        raise AppError("Node-shell recovery metadata exceeds its bounded field size.")


def _digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise AppError("Node-shell recovery digest must be SHA-256 hex.")


@dataclass(frozen=True, slots=True)
class JournalRecord:
    operation_id: str
    state: JournalState
    context: str
    connection_fingerprint: str
    namespace: str
    namespace_uid: str
    node_name: str
    node_uid: str
    pod_name: str
    pod_uid: str | None
    image_digest: str
    created_at: int
    updated_at: int
    result_code: str = "prepared"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation_id, str)
            or re.fullmatch(r"[a-f0-9]{32}", self.operation_id) is None
        ):
            raise AppError("Node-shell recovery operation identity must be UUID hex.")
        if not isinstance(self.state, JournalState):
            raise AppError("Node-shell recovery state is invalid.")
        _text(self.context, 253)
        _digest(self.connection_fingerprint)
        if not isinstance(self.namespace, str):
            raise AppError("Node-shell recovery namespace must be text.")
        namespace_name(self.namespace)
        for value in (self.namespace_uid, self.node_uid):
            _text(value, 253)
        api_segment(self.node_name)
        if self.pod_name != "kuberich-node-shell-" + self.operation_id:
            raise AppError("Node-shell recovery Pod name differs from the operation.")
        if self.pod_uid is not None:
            _text(self.pod_uid, 253)
        if (self.state in {JournalState.OWNED, JournalState.CLEANUP_PENDING}) != (
            self.pod_uid is not None
        ):
            raise AppError("Node-shell recovery state and known UID disagree.")
        _digest(self.image_digest)
        if (
            type(self.created_at) is not int
            or type(self.updated_at) is not int
            or not 0 <= self.created_at <= self.updated_at <= 253402300799
        ):
            raise AppError("Node-shell recovery timestamps are invalid.")
        if not isinstance(self.result_code, str) or self.result_code not in RESULT_CODES:
            raise AppError("Node-shell recovery result requires a bounded application code.")

    def to_mapping(self) -> dict[str, Any]:
        return {"schema_version": 1, **asdict(self)}

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":")).encode()


def parse_record(raw: bytes) -> JournalRecord:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_RECORD_BYTES:
        raise AppError("Node-shell recovery record exceeds 16 KiB or is empty.")
    try:

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        data = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(data, dict):
            raise ValueError
        version = data.pop("schema_version")
        if type(version) is not int or version != 1:
            raise ValueError
        data["state"] = JournalState(data["state"])
        return JournalRecord(**data)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise AppError("Node-shell recovery record is malformed or unsupported.") from None


def recovery_matches(
    record: JournalRecord, *, connection_fingerprint: str, namespace_uid: str
) -> bool:
    """A match permits review, never an implicit connection or DELETE."""
    return (
        record.pod_uid is not None
        and record.connection_fingerprint == connection_fingerprint
        and record.namespace_uid == namespace_uid
    )


def _route(value: str) -> str:
    validate_argument(value)
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https", "socks5", "socks5h"}
            or not parts.hostname
            or parts.query
            or parts.fragment
        ):
            raise ValueError
        host = parts.hostname.lower()
        if ":" in host:
            host = "[" + host + "]"
        port = parts.port
        if port is not None and (parts.scheme, port) not in {("https", 443), ("http", 80)}:
            host += ":" + str(port)
        # Passwords are excluded; configured identity is bound separately below.
        if parts.username is not None:
            host = parts.username + "@" + host
        return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    except ValueError:
        raise AppError(
            "Node-shell recovery requires an unambiguous captured connection route."
        ) from None


def connection_fingerprint(
    *,
    endpoint: str,
    verify_ssl: bool,
    tls_server_name: str | None,
    trust: bytes,
    proxy: str | None = None,
    identity_scope: tuple[tuple[str, str], ...] = (),
) -> str:
    """Hash prepared routing/trust/identity evidence, excluding expiring tokens.

    The adapter reads captured trust files off the event loop. Empty trust is
    valid only for explicit insecure/plain-HTTP connections; TLS verification
    requires the effective trust bytes (including default trust when selected).
    """
    if type(verify_ssl) is not bool or not isinstance(trust, bytes) or len(trust) > 4 * 1024 * 1024:
        raise AppError("Node-shell fingerprint requires bounded captured TLS material.")
    endpoint_route = _route(endpoint)
    if verify_ssl and endpoint_route.startswith("https:") and not trust:
        raise AppError("Node-shell recovery cannot match unavailable TLS trust material.")
    if tls_server_name is not None:
        _text(tls_server_name, 253)
    for key, value in identity_scope:
        _text(key, 253)
        _text(value, 4096)
    material = {
        "endpoint": endpoint_route,
        "verify_ssl": verify_ssl,
        "tls_server_name": tls_server_name,
        "trust": hashlib.sha256(trust).hexdigest(),
        "proxy": _route(proxy) if proxy is not None else None,
        "identity_scope": sorted(identity_scope),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
