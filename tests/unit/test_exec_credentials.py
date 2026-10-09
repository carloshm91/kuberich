"""Validate private exec responses independently of network/process adapters."""

import json
from datetime import UTC, datetime

import pytest

from kuberich.domain.exec_credentials import encrypted_key, parse_credentials
from kuberich.errors import AppError

VERSION = "client.authentication.k8s.io/v1"
NOW = datetime(2026, 10, 8, tzinfo=UTC)
CERT = "-----BEGIN CERTIFICATE-----\nowned-private-material\n-----END CERTIFICATE-----\n"
KEY = "-----BEGIN PRIVATE KEY-----\nowned-private-material\n-----END PRIVATE KEY-----\n"


@pytest.mark.parametrize(
    "material,expected",
    [
        (b"-----BEGIN ENCRYPTED PRIVATE KEY-----\nopaque", True),
        (b"-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nopaque", True),
        (KEY.encode(), False),
        (b"", False),
        (b"Proc-Type: unencrypted\nENCRYPTED is body text", False),
    ],
)
def test_encrypted_private_keys_are_detected_before_any_password_callback(material, expected):
    assert encrypted_key(material) is expected


def payload(status):
    return json.dumps({"apiVersion": VERSION, "kind": "ExecCredential", "status": status}).encode()


@pytest.mark.parametrize("expiration", [None, "2027-01-01T00:00:00Z", "2027-01-01T00:00:00+00:00"])
def test_private_token_result_has_optional_aware_expiry_and_no_repr_leak(expiration):
    status = {"token": "private-token"}
    if expiration is not None:
        status["expirationTimestamp"] = expiration
    result = parse_credentials(payload(status), VERSION, NOW)
    assert result.token == "private-token" and result.certificate is None
    assert result.expiration == (datetime(2027, 1, 1, tzinfo=UTC) if expiration else None)
    assert "private" not in repr(result)


@pytest.mark.parametrize("header", ["PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY"])
def test_certificate_auth_requires_paired_unencrypted_pem_and_hides_values(header):
    key = KEY.replace("PRIVATE KEY", header)
    result = parse_credentials(
        payload({"clientCertificateData": CERT, "clientKeyData": key}), VERSION, NOW
    )
    assert result.token is None and result.certificate == (CERT, key)
    assert "private" not in repr(result)


@pytest.mark.parametrize(
    "root",
    [
        None,
        [],
        {},
        {"kind": "wrong", "apiVersion": VERSION},
        {"kind": "ExecCredential", "apiVersion": "wrong"},
        {"kind": "ExecCredential", "apiVersion": VERSION, "status": []},
    ],
)
def test_missing_or_mismatched_protocol_does_not_accept_a_credential(root):
    with pytest.raises((AppError, ValueError)):
        parse_credentials(json.dumps(root).encode(), VERSION, NOW)


@pytest.mark.parametrize(
    "status",
    [
        {},
        {"token": ""},
        {"token": "private\nheader"},
        {"token": 12},
        {"token": "private", "clientCertificateData": CERT},
        {"token": "private", "clientKeyData": KEY},
        {"clientCertificateData": CERT},
        {"clientKeyData": KEY},
        {"clientCertificateData": 1, "clientKeyData": KEY},
        {"clientCertificateData": "private", "clientKeyData": KEY},
        {
            "clientCertificateData": "-----BEGIN WRONG-----\nprivate\n-----END WRONG-----",
            "clientKeyData": KEY,
        },
        {"clientCertificateData": "-----BEGIN CERTIFICATE-----\nprivate", "clientKeyData": KEY},
        {"clientCertificateData": CERT + "\x1b", "clientKeyData": KEY},
        {
            "clientCertificateData": CERT,
            "clientKeyData": KEY.replace("PRIVATE KEY", "ENCRYPTED PRIVATE KEY"),
        },
        {"clientCertificateData": CERT + "a" * (256 * 1024), "clientKeyData": KEY},
        {"token": "private", "expirationTimestamp": "2020-01-01T00:00:00Z"},
        {"token": "private", "expirationTimestamp": "2027-01-01T00:00:00"},
        {"token": "private", "expirationTimestamp": "invalid"},
        {"token": "private", "expirationTimestamp": 42},
    ],
)
def test_invalid_or_ambiguous_credentials_are_rejected_without_disclosing_private_material(status):
    with pytest.raises((AppError, ValueError)) as error:
        parse_credentials(payload(status), VERSION, NOW)
    assert "owned-private-material" not in str(error.value)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_extra_fields_are_invalid_json_credentials(constant):
    output = payload({"token": "private"})[:-1] + b', "extra": ' + constant.encode() + b"}"
    with pytest.raises(AppError, match="Nonfinite"):
        parse_credentials(output, VERSION, NOW)


def test_entire_response_is_bounded_before_json_decoding():
    with pytest.raises(AppError, match="size limit"):
        parse_credentials(b"x" * (1024 * 1024 + 1), VERSION, NOW)
