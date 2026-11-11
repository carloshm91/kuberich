"""Pure catalog authority and immutable package inputs reject ambiguous identities."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.domain.helm_catalog import (
    CatalogSnapshot,
    ChartSnapshot,
    ChartVersion,
    HelmRepository,
    HelmRepositoryKind,
    RepositoryCredentials,
    catalog_name,
    catalog_text,
    catalog_url,
    chart_version,
    chart_version_key,
    digest,
    loopback_host,
    oci_digest,
    url_origin,
    validate_chart_snapshot,
)
from kuberich.errors import AppError
from tests.support.helm_catalog import chart_package


@pytest.mark.parametrize(
    "function,value",
    [
        (catalog_text, ""),
        (catalog_text, "x\x1b[2J"),
        (catalog_text, None),
        (catalog_name, "UPPER"),
        (catalog_name, "-option"),
        (catalog_name, "x" * 129),
        (catalog_name, None),
        (chart_version, "1.2"),
        (chart_version, "1.2.3-01"),
        (chart_version, "x" * 129),
        (chart_version, None),
        (digest, "a" * 63),
        (digest, None),
        (oci_digest, "sha512:" + "a" * 64),
        (oci_digest, None),
        (oci_digest, "sha256:invalid"),
    ],
)
def test_invalid_metadata_cannot_enter_catalog_records(function, value):
    with pytest.raises(AppError):
        function(value)


def test_exact_semver_order_and_safe_digest_metadata():
    assert catalog_text("safe") == "safe"
    assert catalog_name("a") == "a"
    assert digest("a" * 64) == "a" * 64
    assert oci_digest("sha256:" + "a" * 64) == "sha256:" + "a" * 64
    versions = ["1.0.0", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-alpha", "2.0.0+build"]
    assert sorted(versions, key=chart_version_key) == [
        "1.0.0-alpha",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0",
        "2.0.0+build",
    ]
    assert loopback_host("localhost") and loopback_host("127.0.0.2") and loopback_host("::1")
    assert not loopback_host("example.invalid") and not loopback_host("192.0.2.1")
    assert url_origin("https://example.invalid/charts") == "https://example.invalid"


@pytest.mark.parametrize(
    "value,options",
    [
        ("https://example.invalid:bad/charts", {}),
        ("https://example.invalid:0/charts", {}),
        ("ftp://example.invalid/charts", {}),
        ("https:///charts", {}),
        ("https://user:secret@example.invalid/charts", {}),
        ("https://example.invalid/charts?token=secret", {}),
        ("https://example.invalid/charts#fragment", {}),
        ("https://example.invalid/\\private", {}),
        ("https://é.invalid/charts", {}),
        ("http://example.invalid/charts", {}),
        ("http://127.0.0.1/charts", {}),
        ("https://example.invalid/charts", {"allow_loopback_http": True}),
        ("https://example.invalid/charts/%2e%2e/private", {}),
        ("https://example.invalid/%0a", {}),
        ("oci://example.invalid", {"oci": True}),
        ("oci://example.invalid/charts//item", {"oci": True}),
        ("https://example.invalid", {"allow_loopback_http": "yes"}),
    ],
)
def test_url_configuration_never_silently_inherits_credentials_or_plaintext(value, options):
    with pytest.raises(AppError):
        catalog_url(value, **options)


def test_repository_origins_and_explicit_loopback_are_separate_from_kubernetes():
    assert catalog_url("https://EXAMPLE.invalid/charts/") == "https://example.invalid/charts"
    assert catalog_url("http://127.0.0.1:123/charts", allow_loopback_http=True).startswith("http:")
    repository = HelmRepository(
        "owned",
        "https://example.invalid/charts",
        HelmRepositoryKind.HTTP,
        "a" * 64,
        ca_file=Path("/private/ca.pem"),
        token_origins=("https://auth.invalid",),
    )
    assert repository.origin == "https://example.invalid"
    oci = replace(repository, url="oci://example.invalid/charts/item", kind=HelmRepositoryKind.OCI)
    assert oci.origin == "https://example.invalid" and oci.oci_path == "charts/item"
    local = HelmRepository(
        "owned", "oci://127.0.0.1:123/charts/item", HelmRepositoryKind.OCI, "b" * 64, True
    )
    assert local.origin == "http://127.0.0.1:123"
    for changes in (
        {"kind": "http"},
        {"url": "https://EXAMPLE.invalid/charts"},
        {"ca_file": Path("relative")},
        {"ca_file": "bad"},
        {"token_origins": []},
        {"token_origins": ("https://auth.invalid/path",)},
        {"token_origins": ("https://auth.invalid/",)},
        {"token_origins": ("https://auth.invalid",) * 9},
    ):
        with pytest.raises(AppError):
            replace(repository, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "user"},
        {"password": "secret"},
        {"username": "user", "password": "secret", "token": "token"},
        {"username": "user:name", "password": "secret"},
        {"token": "white space"},
        {"token": "é"},
        {"token": "line\nbreak"},
    ],
)
def test_credential_modes_are_explicit_private_and_nonambiguous(changes):
    with pytest.raises(AppError):
        RepositoryCredentials(**changes)


def test_typed_catalog_rejects_duplicate_stale_or_unbounded_inventory():
    repository = HelmRepository(
        "owned", "https://example.invalid", HelmRepositoryKind.HTTP, "a" * 64
    )
    chart = ChartVersion(
        "owned",
        "item",
        "1.0.0",
        "https://example.invalid/item.tgz",
        "b" * 64,
        repository.revision,
        "sha256:" + "c" * 64,
    )
    snapshot = CatalogSnapshot(1, (repository,), (chart,))
    assert snapshot.repositories == (repository,)
    for changes in (
        {"generation": -1},
        {"generation": True},
        {"repositories": []},
        {"repositories": ("bad",)},
        {"repositories": (repository,) * 65},
        {"charts": []},
        {"charts": ("bad",)},
        {"charts": (chart,) * 10_001},
        {"repositories": (repository, repository)},
        {"charts": (chart, chart)},
        {"charts": (replace(chart, catalog_revision="d" * 64),)},
    ):
        with pytest.raises(AppError):
            replace(snapshot, **changes)
    assert "secret" not in repr(RepositoryCredentials(username="user", password="secret"))


def test_package_record_is_content_bound_and_not_an_archive_policy_bypass():
    package = chart_package()
    defaults = b"message: synthetic-first\npassword: synthetic-private\n"
    snapshot = ChartSnapshot(
        "owned-chart",
        "1.0.0",
        "owned/owned-chart",
        hashlib.sha256(package).hexdigest(),
        package,
        defaults,
        manifest_digest="sha256:" + "a" * 64,
        layer_digest="sha256:" + hashlib.sha256(package).hexdigest(),
        catalog_revision="d" * 64,
    )
    validate_chart_snapshot(snapshot)
    assert snapshot.package == package and "synthetic-private" not in repr(snapshot)
    for changes in (
        {"package": b""},
        {"package": "invalid"},
        {"sha256": "a" * 64},
        {"default_values": b"message: changed\n"},
        {"catalog_generation": -1},
        {"catalog_generation": True},
        {"layer_digest": "sha512:bad"},
        {"name": "other"},
        {"version": "2.0.0"},
    ):
        with pytest.raises(AppError):
            replace(snapshot, **changes)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "Upper/name",
        "owned/../name",
        "owned/" + "a" * 256,
        "owned/name@sha256:invalid",
        "owned/name@sha256:" + "a" * 64 + "@extra",
    ],
)
def test_explicit_oci_paths_never_guess_unregistered_or_ambiguous_repositories(value):
    from kuberich.domain.helm_catalog import oci_chart_path

    with pytest.raises(AppError):
        oci_chart_path(value)


def test_oci_tag_build_translation_and_frozen_revision_are_validated():
    from kuberich.domain.helm_catalog import oci_chart_path, oci_chart_version, oci_tag

    assert oci_chart_path("owned/chart") == ("owned/chart", None)
    assert oci_chart_path("owned/chart@sha256:" + "a" * 64) == ("owned/chart", "sha256:" + "a" * 64)
    assert oci_chart_version("1.2.3_build.4") == "1.2.3+build.4"
    assert oci_chart_version("latest") is None
    for tag in (None, "/unsafe", "a" * 129):
        with pytest.raises(AppError):
            oci_tag(tag)
    for url in ("oci://example.invalid/%6fwned/chart", "oci://example.invalid//owned/chart"):
        with pytest.raises(AppError):
            catalog_url(url, oci=True)
    package = chart_package()
    snapshot = ChartSnapshot(
        "owned-chart",
        "1.0.0",
        "owned",
        hashlib.sha256(package).hexdigest(),
        package,
        b"message: synthetic-first\npassword: synthetic-private\n",
    )
    for changes in ({"layer_digest": "sha256:" + "b" * 64}, {"catalog_revision": "invalid"}):
        with pytest.raises(AppError):
            replace(snapshot, **changes)


def test_download_origins_are_explicit_bounded_and_independent_of_token_origins():
    base = HelmRepository("owned", "https://example.invalid", HelmRepositoryKind.HTTP, "a" * 64)
    configured = replace(base, download_origins=("https://cdn.invalid",))
    assert (
        configured.download_origins == ("https://cdn.invalid",) and configured.token_origins == ()
    )
    for changes in (
        {"download_origins": []},
        {"download_origins": ("https://cdn.invalid",) * 9},
        {"download_origins": ("https://cdn.invalid/path",)},
        {"download_origins": ("https://cdn.invalid/",)},
    ):
        with pytest.raises(AppError):
            replace(base, **changes)
    loopback_tls = replace(base, url="https://127.0.0.1", allow_loopback_http=True)
    with pytest.raises(AppError):
        replace(loopback_tls, download_origins=("http://127.0.0.1:5000",))


def test_catalog_and_approved_origins_reject_literal_wildcard_hosts():
    with pytest.raises(AppError):
        catalog_url("https://*.example.invalid/charts")
    repository = HelmRepository(
        "owned", "https://example.invalid", HelmRepositoryKind.HTTP, "a" * 64
    )
    for changes in (
        {"token_origins": ("https://*.example.invalid",)},
        {"download_origins": ("https://*.example.invalid",)},
    ):
        with pytest.raises(AppError):
            replace(repository, **changes)
