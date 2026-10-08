"""Effective invocation identities cannot mutate catalogues or leak in repr."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kuberich.domain.connection_overrides import ConnectionOverrides, impersonation_headers
from kuberich.errors import AppError


@pytest.mark.parametrize("field", ["cluster", "user", "token", "certificate_authority", "as_user"])
@pytest.mark.parametrize("value", ["", "injected\nheader", "x" * 8193, 1])
def test_invalid_override_strings_never_reach_transport(field, value):
    with pytest.raises(AppError):
        ConnectionOverrides(**{field: value})


@pytest.mark.parametrize(
    "values",
    [
        {"insecure": 1},
        {"as_groups": ["a"]},
        {"as_groups": ("a",) * 65},
        {"as_user": "reader", "as_groups": ("a\r",)},
        {"as_groups": ("a",)},
        {"client_key": "/key"},
        {"client_certificate": "/cert"},
        {"token": "private", "client_certificate": "/cert", "client_key": "/key"},
        {"insecure": True, "certificate_authority": "/ca"},
    ],
)
def test_invalid_identity_combinations_fail_before_files_or_helpers(values):
    with pytest.raises(AppError):
        ConnectionOverrides(**values)


def test_secret_repr_and_immutable_capture():
    overrides = ConnectionOverrides(token="unstructured-private-token")
    assert "unstructured-private-token" not in repr(overrides)
    with pytest.raises(FrozenInstanceError):
        overrides.token = "replacement"


def test_file_overrides_capture_relative_paths_and_tilde_without_reading(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    original = ConnectionOverrides(
        certificate_authority="~/missing-ca", client_certificate="cert", client_key="/absolute-key"
    )
    captured = original.capture_paths(tmp_path)
    assert captured.certificate_authority == str(tmp_path / "missing-ca")
    assert captured.client_certificate == str(tmp_path / "cert")
    assert captured.client_key == "/absolute-key" and original.client_certificate == "cert"
    assert list(tmp_path.iterdir()) == []
    assert ConnectionOverrides().capture_paths(tmp_path) == ConnectionOverrides()
    with pytest.raises(AppError):
        original.capture_paths(Path("relative"))


def test_default_override_deep_copies_catalogue_values():
    cluster, user = {"extensions": [{"nested": ["initial"]}]}, {"exec": {"args": ["initial"]}}
    selected_cluster, selected_user = ConnectionOverrides().apply(cluster, user)
    selected_cluster["extensions"][0]["nested"].append("later")
    selected_user["exec"]["args"].append("later")
    assert cluster["extensions"][0]["nested"] == ["initial"]
    assert user["exec"]["args"] == ["initial"]


@pytest.mark.parametrize("insecure", [True, False, None])
def test_explicit_ca_and_verification_precedence(insecure):
    cluster = {
        "certificate-authority-data": "old-inline",
        "certificate-authority": "old-file",
        "insecure-skip-tls-verify": True,
    }
    override = ConnectionOverrides(insecure=insecure)
    selected, _ = override.apply(cluster, {})
    if insecure is True:
        assert selected == {"insecure-skip-tls-verify": True}
    elif insecure is False:
        assert (
            selected["insecure-skip-tls-verify"] is False
            and selected["certificate-authority-data"] == "old-inline"
        )
    else:
        assert selected == cluster
    selected, _ = ConnectionOverrides(certificate_authority="/new-ca").apply(cluster, {})
    assert selected == {"certificate-authority": "/new-ca", "insecure-skip-tls-verify": False}
    assert cluster["certificate-authority-data"] == "old-inline"


@pytest.mark.parametrize(
    "override,expected",
    [
        (ConnectionOverrides(token="chosen"), {"token": "chosen"}),
        (
            ConnectionOverrides(client_key="/key", client_certificate="/cert"),
            {"client-key": "/key", "client-certificate": "/cert"},
        ),
    ],
)
def test_explicit_credentials_replace_legacy_helpers_and_inline_credentials(override, expected):
    user = {
        "token": "old",
        "tokenFile": "missing",
        "exec": {"command": "must-not-run"},
        "auth-provider": {},
        "username": "old",
        "password": "old",
        "client-key": "old",
        "client-key-data": "old",
        "client-certificate": "old",
        "client-certificate-data": "old",
        "extra": {"nested": [1]},
    }
    _, selected = override.apply({}, user)
    assert selected == {**expected, "extra": {"nested": [1]}}
    assert "exec" in user and user["token"] == "old"


def test_explicit_impersonation_captures_exact_subject_and_group_order():
    original = {
        "as": "old",
        "as-uid": "old-uid",
        "as-user-extra": {"scope": ["old"]},
        "as-groups": ["old"],
        "token": "owner",
    }
    _, selected = ConnectionOverrides(
        as_user="system:serviceaccount:team:reader", as_groups=("one", "two", "one")
    ).apply({}, original)
    assert selected == {
        "as": "system:serviceaccount:team:reader",
        "as-groups": ["one", "two", "one"],
        "token": "owner",
    }
    assert original["as"] == "old"
    assert impersonation_headers(selected) == (
        ("Impersonate-User", "system:serviceaccount:team:reader"),
        ("Impersonate-Group", "one"),
        ("Impersonate-Group", "two"),
        ("Impersonate-Group", "one"),
    )
    assert impersonation_headers({}) == ()
    assert impersonation_headers({"as": "reader"}) == (("Impersonate-User", "reader"),)


def test_kubeconfig_uid_and_repeated_extra_headers_use_safe_percent_encoded_names():
    assert impersonation_headers(
        {"as": "reader", "as-uid": "uid", "as-user-extra": {"Example.com/Scope": ["one", "two"]}}
    ) == (
        ("Impersonate-User", "reader"),
        ("Impersonate-Uid", "uid"),
        ("Impersonate-Extra-example.com%2Fscope", "one"),
        ("Impersonate-Extra-example.com%2Fscope", "two"),
    )


@pytest.mark.parametrize(
    "user",
    [
        {"as": "bad\n"},
        {"as-groups": "bad"},
        {"as-groups": ["a"] * 65},
        {"as": "reader", "as-groups": ["bad\r"]},
        {"as-groups": ["reader"]},
        {"as-uid": "orphan"},
        {"as-user-extra": {"scope": ["orphan"]}},
        {"as-user-extra": []},
        {"as": "reader", "as-user-extra": {str(i): [] for i in range(17)}},
        {"as": "reader", "as-uid": "bad\r"},
        {"as": "reader", "as-user-extra": {"bad\n": []}},
        {"as": "reader", "as-user-extra": {"scope": "scalar"}},
        {"as": "reader", "as-groups": ["x" * 8192] * 9},
    ],
)
def test_malformed_or_oversized_impersonation_cannot_be_sent(user):
    with pytest.raises(AppError):
        impersonation_headers(user)
