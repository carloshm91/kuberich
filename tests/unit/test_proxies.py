"""Kubeconfig/environment precedence and private proxy URL boundaries."""

import ssl

import pytest

from kuberich.domain.proxies import effective_proxy, proxy_url, tls_failure
from kuberich.errors import AppError

SERVER = "https://api.example.test:6443"
PROXY = "http://user:private@127.0.0.1:3128"


def test_wrapped_tls_failure_keeps_diagnostic_without_reading_private_error_text():
    tls = ssl.SSLCertVerificationError("private-certificate")
    wrapped = OSError("private-proxy")
    outer = ConnectionError("private-address")
    wrapped.__cause__ = tls
    outer.__context__ = wrapped
    assert tls_failure(tls) and tls_failure(outer)
    assert not tls_failure(OSError("private"))
    wrapped.__cause__ = outer
    assert not tls_failure(outer)  # A malformed cyclic exception chain terminates.


@pytest.mark.parametrize(
    "value",
    [
        PROXY,
        "https://proxy.example:444/",
        "socks5://user:private@127.0.0.1:1080",
        "http://proxy.example",
    ],
)
def test_explicit_supported_proxy_urls_preserve_authentication_and_normalize_only_trailing_slash(
    value,
):
    assert proxy_url(value) == value.rstrip("/")


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        12,
        "",
        "x" * 4097,
        "file:///private",
        "http:///private",
        "http://host/private",
        "http://host?private",
        "http://host#private",
        "http://host:0",
        "http://user:private@host:private",
        "http://[private",
        "http://user:%0Aprivate@host",
        "http://host\x7f",
    ],
)
def test_invalid_proxy_urls_refuse_without_exposing_credentials(value):
    with pytest.raises(AppError) as error:
        proxy_url(value)
    assert "user:private" not in str(error.value)


def test_explicit_proxy_wins_over_environment_and_bypass_including_loopback():
    assert (
        effective_proxy(
            "https://127.0.0.1:6443", PROXY, {"NO_PROXY": "*", "HTTPS_PROXY": "http://other"}
        )
        == PROXY
    )
    with pytest.raises(AppError):
        effective_proxy(SERVER, {}, {})


@pytest.mark.parametrize("declared", [None, ""])
def test_environment_proxy_uses_selected_scheme_and_uppercase_precedence(declared):
    environment = {
        "HTTPS_PROXY": PROXY,
        "https_proxy": "http://other",
        "HTTP_PROXY": "proxy-http:3128",
    }
    assert effective_proxy(SERVER, declared, environment) == PROXY
    assert (
        effective_proxy("http://api.example.test", declared, environment)
        == "http://proxy-http:3128"
    )
    assert effective_proxy(SERVER, declared, {"https_proxy": PROXY}) == PROXY
    assert effective_proxy(SERVER, declared, {}) is None


@pytest.mark.parametrize(
    "server,bypass",
    [
        (SERVER, "*"),
        (SERVER, "example.test"),
        (SERVER, ".example.test"),
        (SERVER, "*.example.test"),
        (SERVER, "api.example.test:6443"),
        (SERVER, "missing.test, ,example.test"),
        ("https://localhost:6443", ""),
        ("https://127.0.0.2:6443", ""),
        ("https://[::1]:6443", ""),
        ("https://10.12.1.5:443", "10.0.0.0/8"),
        ("https://10.12.1.5:443", "10.12.1.5"),
        ("https://[fd00::1]:6443", "fd00::1"),
        ("https://[fd00::1]:6443", "fd00::/8"),
    ],
)
def test_no_proxy_cidr_ip_domain_port_and_loopback_bypass(server, bypass):
    assert effective_proxy(server, None, {"NO_PROXY": bypass, "HTTPS_PROXY": PROXY}) is None


@pytest.mark.parametrize(
    "server,bypass",
    [
        (SERVER, "other.test"),
        (SERVER, "example.test:443"),
        (SERVER, "10.0.0.0/8"),
        (SERVER, "bad/cidr"),
        (SERVER, "bad:port"),
        (SERVER, ":443"),
        (SERVER, ":6443"),
        ("https://10.0.0.1", "bad/cidr"),
        ("https://10.0.0.1", "not-an-ip.test"),
        (SERVER, "[bad"),
        ("https://example.test", ".example.test"),
        ("https://example.test", "*.example.test"),
        ("https://10.0.0.1", "172.16.0.0/16"),
        ("https://[fd00::2]", "fd00::1"),
    ],
)
def test_nonmatching_or_invalid_bypass_entries_do_not_change_proxy_identity(server, bypass):
    assert effective_proxy(server, None, {"no_proxy": bypass, "HTTPS_PROXY": PROXY}) == PROXY


def test_cgi_http_proxy_refuses_ambiguous_environment_but_explicit_config_works():
    environment = {"REQUEST_METHOD": "GET", "HTTP_PROXY": PROXY}
    with pytest.raises(AppError, match="CGI"):
        effective_proxy("http://api.example.test", None, environment)
    assert effective_proxy("http://api.example.test", PROXY, environment) == PROXY
