"""Conservative request reviews, private targets and literal external commands."""

import base64
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kuberich.domain.benchmarks import (
    LoadOptions,
    RequestOptions,
    attack_argv,
    minimal_environment,
    parse_vegeta_version,
    report_argv,
    review_request,
    targets_json,
)
from kuberich.errors import AppError


@pytest.mark.parametrize(
    "field,maximum",
    [("rate", 50), ("concurrency", 8), ("duration_seconds", 30), ("timeout_seconds", 5)],
)
def test_load_limits_are_strict_integers(field, maximum):
    assert getattr(LoadOptions(**{field: maximum}), field) == maximum
    for value in (False, True, 0, -1, maximum + 1, 1.0, float("inf"), "1", None):
        with pytest.raises(AppError):
            LoadOptions(**{field: value})


def test_options_are_immutable_and_review_never_retains_private_values():
    request = RequestOptions(
        "POST",
        "/health?token=secret",
        (("Authorization", "private"), ("X-Key", "hidden")),
        b"sensitive",
    )
    review = review_request(request)
    assert review.route == "/health" and review.query_present and review.auth_present
    assert review.method == "POST" and review.header_names == ("Authorization", "X-Key")
    assert review.body_bytes == 9
    assert all(
        secret not in repr(request) + repr(review)
        for secret in ("secret", "private", "hidden", "sensitive")
    )
    assert review_request(RequestOptions()).query_present is False
    assert review_request(RequestOptions()).auth_present is False
    assert LoadOptions().nominal_requests == 5
    with pytest.raises(FrozenInstanceError):
        request.target = "/changed"


@pytest.mark.parametrize(
    "fields",
    [
        {"method": "TRACE"},
        {"method": False},
        {"target": False},
        {"target": ""},
        {"target": "https://elsewhere/"},
        {"target": "//elsewhere/"},
        {"target": "/\\elsewhere"},
        {"target": "/x\n"},
        {"target": "/#fragment"},
        {"target": "/x#"},
        {"target": "/%0d%0a"},
        {"target": "/%5c"},
        {"target": "/" + "x" * 2048},
        {"headers": []},
        {"headers": tuple((f"X-{i}", "v") for i in range(17))},
        {"headers": (["X", "v"],)},
        {"headers": (("X",),)},
        {"headers": (("X", 1),)},
        {"headers": (("X", "a"), ("x", "b"))},
        {"headers": (("Host", "elsewhere"),)},
        {"headers": (("Transfer-Encoding", "chunked"),)},
        {"headers": (("X:", "bad"),)},
        {"headers": (("X", "bad\r\nvalue"),)},
        {"headers": (("X", "a" * 8192),)},
        {"body": bytearray(b"bad")},
        {"body": b"a" * 16385},
    ],
)
def test_unsafe_or_unbounded_requests_refused(fields):
    with pytest.raises(AppError):
        RequestOptions(**fields)


def test_private_json_targets_are_one_loopback_origin_and_base64_body():
    request = RequestOptions(
        "PATCH", "/ready?a=private", (("Authorization", "Bearer secret"),), b"\x00\xff"
    )
    target = json.loads(targets_json(request, 43210))
    assert target == {
        "method": "PATCH",
        "url": "http://127.0.0.1:43210/ready?a=private",
        "header": {"Authorization": ["Bearer secret"]},
        "body": "AP8=",
    }
    assert base64.b64decode(target["body"]) == request.body
    for port in (True, 0, 65536, "80"):
        with pytest.raises(AppError):
            targets_json(request, port)
    # JSON's ASCII escapes can be larger than the admitted UTF-8 header inputs.
    assert (
        len(
            targets_json(
                RequestOptions(
                    target="/" + "é" * 1023, headers=(("X", "é" * 4095),), body=b"x" * 16384
                ),
                80,
            )
        )
        < 64 * 1024
    )


def test_literal_argv_fixed_network_controls_and_minimal_environment(monkeypatch):
    exe, target = Path("/opt/program with spaces;safe"), Path("/private/request.json")
    args = attack_argv(exe, target, LoadOptions(50, 8, 30, 5))
    assert args == (
        str(exe),
        "-cpus=1",
        "attack",
        "-format=json",
        "-targets=/private/request.json",
        "-rate=50/1s",
        "-duration=30s",
        "-timeout=5s",
        "-workers=8",
        "-max-workers=8",
        "-connections=8",
        "-max-connections=8",
        "-redirects=-1",
        "-max-body=0",
        "-keepalive=false",
        "-http2=false",
        "-h2c=false",
        "-prometheus-addr=",
    )
    assert report_argv(exe, target) == (str(exe), "-cpus=1", "report", "-type=json", str(target))
    monkeypatch.setenv("HTTPS_PROXY", "https://private.example")
    monkeypatch.setenv("KUBECONFIG", "/private/kubeconfig")
    assert minimal_environment() == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
    for path in (
        "/wrongtype",
        Path("relative"),
        Path("/a/../b"),
        Path("/bad\n"),
        Path("/" + "a" * 4097),
    ):
        with pytest.raises(AppError):
            report_argv(path, target)
        with pytest.raises(AppError):
            attack_argv(exe, path, LoadOptions())


@pytest.mark.parametrize("version", ["12.13.0", "v12.13.0"])
def test_exact_pinned_version_contract(version):
    data = f"Version: {version}\nCommit: 507c4f0\nRuntime: go1.22.12 linux/amd64\nDate: 2025-01-01\n".encode()
    assert parse_vegeta_version(data) == "12.13.0"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x" * 16385,
        b"\xff",
        b"Version: 12.13.0\n",
        b"Version: 12.14.0\nCommit: abc\nRuntime: go1 linux/amd64\nDate: today\n",
        b"Version: 12.13.0\nCommit: \nRuntime: go1 linux/amd64\nDate: today\n",
        b"Version: 12.13.0\nCommit: abc\nRuntime: go1 linux/amd64\nDate: today\x1b[0m\n",
        b"Version: 12.13.0\nCommit: abc\nRuntime: go1 linux/amd64\nOther: today\n",
    ],
)
def test_unknown_or_unsafe_version_output_refused(data):
    with pytest.raises(AppError):
        parse_vegeta_version(data)
