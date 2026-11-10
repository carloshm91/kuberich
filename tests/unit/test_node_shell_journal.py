"""Metadata schema and conservative selected-connection recovery evidence."""

import json
from dataclasses import replace
from typing import Any

import pytest

from kuberich.domain.node_shell_journal import (
    JournalRecord,
    JournalState,
    connection_fingerprint,
    parse_record,
    recovery_matches,
)
from kuberich.errors import AppError


def sample_record() -> JournalRecord:
    return JournalRecord(
        "a" * 32,
        JournalState.PREPARED,
        "fixture",
        "b" * 64,
        "diagnostics",
        "namespace-uid",
        "worker-1",
        "node-uid",
        "kuberich-node-shell-" + "a" * 32,
        None,
        "c" * 64,
        1,
        2,
    )


def test_metadata_only_record_round_trip_and_known_uid_recovery_matching() -> None:
    record = sample_record()
    assert parse_record(record.to_bytes()) == record
    assert record.to_mapping()["schema_version"] == 1
    assert not recovery_matches(
        record, connection_fingerprint="b" * 64, namespace_uid="namespace-uid"
    )
    known = replace(record, state=JournalState.OWNED, pod_uid="created-uid", result_code="created")
    assert recovery_matches(known, connection_fingerprint="b" * 64, namespace_uid="namespace-uid")
    assert not recovery_matches(
        known, connection_fingerprint="d" * 64, namespace_uid="namespace-uid"
    )
    assert not recovery_matches(known, connection_fingerprint="b" * 64, namespace_uid="replacement")
    assert (
        parse_record(replace(known, state=JournalState.CLEANUP_PENDING).to_bytes()).pod_uid
        == "created-uid"
    )
    assert (
        parse_record(replace(record, state=JournalState.CREATE_UNCERTAIN).to_bytes()).pod_uid
        is None
    )
    assert set(record.to_mapping()) == {
        "schema_version",
        "operation_id",
        "state",
        "context",
        "connection_fingerprint",
        "namespace",
        "namespace_uid",
        "node_name",
        "node_uid",
        "pod_name",
        "pod_uid",
        "image_digest",
        "created_at",
        "updated_at",
        "result_code",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_id", "../escape"),
        ("operation_id", 7),
        ("state", "owned"),
        ("context", "private\x1b[2J"),
        ("context", "a" * 254),
        ("connection_fingerprint", "a" * 63),
        ("connection_fingerprint", 7),
        ("namespace", 7),
        ("namespace", "not.a.namespace"),
        ("namespace_uid", ""),
        ("node_uid", "a" * 254),
        ("node_name", "../bad"),
        ("pod_name", "foreign"),
        ("pod_uid", "created-uid"),
        ("state", JournalState.OWNED),
        ("image_digest", "sha256:" + "a" * 64),
        ("image_digest", None),
        ("created_at", True),
        ("updated_at", True),
        ("created_at", -1),
        ("created_at", 3),
        ("updated_at", 253402300800),
        ("result_code", "server token private"),
        ("result_code", "opaque_token_abc"),
        ("result_code", 7),
    ],
)
def test_record_constructor_rejects_unsafe_or_inconsistent_metadata(field: str, value: Any) -> None:
    with pytest.raises(AppError):
        replace(sample_record(), **{field: value})


def test_known_uid_must_be_valid_bounded_text() -> None:
    for uid in ("", "a" * 254, "uid\n"):
        with pytest.raises(AppError):
            replace(sample_record(), state=JournalState.OWNED, pod_uid=uid)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"x" * 16385,
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b"{}",
        b'{"schema_version":true}',
        b'{"schema_version":2}',
        b'{"schema_version":1,"state":"foreign"}',
        b'{"schema_version":1,"schema_version":1}',
        "text",
    ],
)
def test_malformed_record_is_never_used_for_recovery(raw: Any) -> None:
    with pytest.raises(AppError):
        parse_record(raw)


def test_unknown_json_fields_and_invalid_metadata_do_not_escape_validation() -> None:
    data = sample_record().to_mapping()
    data["token"] = "must-not-be-retained"
    with pytest.raises(AppError):
        parse_record(json.dumps(data).encode())
    del data["token"]
    data["namespace"] = True
    with pytest.raises(AppError):
        parse_record(json.dumps(data).encode())


def fingerprint(**changes: Any) -> str:
    values: dict[str, Any] = {
        "endpoint": "https://API.EXAMPLE.test:443/base/",
        "verify_ssl": True,
        "tls_server_name": "api.example.test",
        "trust": b"captured CA bytes",
        "proxy": None,
        "identity_scope": (("user", "operator"),),
    }
    values.update(changes)
    return connection_fingerprint(**values)


def test_fingerprint_normalizes_routes_and_binds_tls_proxy_and_identity() -> None:
    original = fingerprint()
    assert len(original) == 64
    assert original == fingerprint(endpoint="https://api.example.test/base")
    assert original != fingerprint(endpoint="https://api.example.test/other")
    assert original != fingerprint(endpoint="https://api.example.test:8443/base")
    assert original != fingerprint(trust=b"replacement CA")
    assert original != fingerprint(verify_ssl=False)
    assert original != fingerprint(tls_server_name=None)
    assert original != fingerprint(identity_scope=(("user", "other"),))
    assert original != fingerprint(proxy="http://proxy.test:80")
    proxy = fingerprint(proxy="https://user:secret@proxy.test:8443/base/")
    assert proxy == fingerprint(proxy="https://user:rotated@proxy.test:8443/base")
    assert proxy != fingerprint(proxy="https://other:secret@proxy.test:8443/base")
    assert fingerprint(
        endpoint="http://[::1]:80/base/", verify_ssl=False, trust=b""
    ) == fingerprint(endpoint="http://[::1]/base", verify_ssl=False, trust=b"")
    assert fingerprint(proxy="socks5h://proxy.test:1080") != original
    assert fingerprint(identity_scope=(("b", "two"), ("a", "one"))) == fingerprint(
        identity_scope=(("a", "one"), ("b", "two"))
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"verify_ssl": 1},
        {"trust": "path"},
        {"trust": b"x" * (4 * 1024 * 1024 + 1)},
        {"trust": b""},
        {"endpoint": "file:///tmp/socket"},
        {"endpoint": "https:///missing"},
        {"endpoint": "https://host/path?token=secret"},
        {"endpoint": "https://host/#fragment"},
        {"endpoint": "https://host:bad"},
        {"endpoint": "https://[invalid"},
        {"tls_server_name": "x\n"},
        {"identity_scope": (("user", "private\n"),)},
    ],
)
def test_ambiguous_or_unavailable_fingerprint_material_fails_closed(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(AppError):
        fingerprint(**changes)
