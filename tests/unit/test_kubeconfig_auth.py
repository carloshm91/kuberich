"""Basic credentials preserve literal bytes and never enter error messages."""

import base64

import pytest

from kuberich.domain.connections import ConnectionProblem, ConnectionState
from kuberich.domain.kubeconfig_auth import basic_credentials, basic_header


@pytest.mark.parametrize("user", [{}, {"username": ""}, {"password": ""}, {"username": None}])
def test_empty_basic_fields_do_not_invent_an_identity(user):
    assert basic_credentials(user) is None


@pytest.mark.parametrize(
    "username,password",
    [("demo", "private"), ("demo", ""), ("", "private"), ("démo", "🔑:private")],
)
def test_basic_header_preserves_utf8_and_empty_half_without_prompting(username, password):
    credentials = basic_credentials({"username": username, "password": password})
    assert credentials == (username, password)
    header = basic_header(credentials)
    assert header.startswith("Basic ")
    assert base64.b64decode(header[6:]) == (username + ":" + password).encode("utf-8")


@pytest.mark.parametrize(
    "user,field",
    [
        ({"username": 1}, "username"),
        ({"password": []}, "password"),
        ({"username": "private:ambiguous"}, "username"),
        ({"password": "private" * 10000}, "username/password"),
        ({"password": "private\ud800"}, "password"),
        ({"password": "private\n"}, "password"),
        ({"username": "private\x1b"}, "username"),
    ],
)
def test_invalid_basic_fields_have_safe_actionable_errors(user, field):
    with pytest.raises(ConnectionProblem) as caught:
        basic_credentials(user)
    assert caught.value.state is ConnectionState.AUTH_ERROR
    assert "users.user." + field in str(caught.value)
    assert "private" not in str(caught.value)


def test_basic_utf8_limit_counts_encoded_bytes():
    assert basic_credentials({"username": "a", "password": "é" * 32767}) is not None
    with pytest.raises(ConnectionProblem, match="64 KiB"):
        basic_credentials({"username": "a", "password": "é" * 32768})
