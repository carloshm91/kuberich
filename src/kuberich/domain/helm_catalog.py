"""Bounded catalog identities and immutable, inspected Helm chart inputs."""

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_CATALOG_ENTRIES = 10_000
MAX_REPOSITORIES = 64
MAX_CATALOG_PAGES = 20
MAX_CHART_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_CHART_FILES = 2_000
MAX_CHART_DEPTH = 8
MAX_VALUES_BYTES = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OCI_PATH = re.compile(
    r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*"
)
_OCI_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


def catalog_text(value: str, *, limit: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or escape_controls(value) != value
    ):
        raise AppError("Helm catalog metadata must be bounded text without controls.")
    return value


def catalog_name(value: str) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise AppError("Helm catalog names must be bounded lowercase identifiers.")
    return value


def chart_version(value: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or _VERSION.fullmatch(value) is None:
        raise AppError("Helm charts require an exact supported semantic version.")
    return value


def chart_version_key(
    value: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...], str]:
    chart_version(value)
    match = _VERSION.fullmatch(value)
    assert match is not None
    prerelease = match[4]
    return (
        int(match[1]),
        int(match[2]),
        int(match[3]),
        int(prerelease is None),
        tuple((0, int(part)) if part.isdecimal() else (1, part) for part in prerelease.split("."))
        if prerelease
        else (),
        value,
    )


def digest(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AppError("Helm catalog content requires a SHA-256 digest.")
    return value


def oci_digest(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise AppError("Only SHA-256 OCI content digests are supported.")
    digest(value[7:])
    return value


def oci_chart_path(value: str) -> tuple[str, str | None]:
    if not isinstance(value, str):
        raise AppError("Register an explicit bounded OCI chart repository path.")
    path, separator, pinned = value.partition("@")
    if not 1 <= len(path) <= 255 or _OCI_PATH.fullmatch(path) is None:
        raise AppError("Register an explicit bounded OCI chart repository path.")
    return path, oci_digest(pinned) if separator else None


def oci_tag(value: str) -> str:
    if not isinstance(value, str) or _OCI_TAG.fullmatch(value) is None:
        raise AppError("OCI tags must be bounded registry tag identifiers.")
    return value


def oci_chart_version(tag: str) -> str | None:
    oci_tag(tag)
    try:
        return chart_version(tag.replace("_", "+"))
    except AppError:
        return None


def loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def catalog_url(value: str, *, allow_loopback_http: bool = False, oci: bool = False) -> str:
    catalog_text(value)
    if type(allow_loopback_http) is not bool:
        raise AppError("Helm plaintext loopback use must be explicit.")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise AppError("Invalid Helm catalog URL.") from None
    schemes = {"oci"} if oci else {"https", "http"}
    if (
        parsed.scheme not in schemes
        or host is None
        or not host.isascii()
        or "*" in host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or (port is not None and not 1 <= port <= 65535)
        or (parsed.scheme == "http" and not (allow_loopback_http and loopback_host(host)))
        or (allow_loopback_http and not loopback_host(host))
    ):
        raise AppError(
            "Helm URLs require verified HTTPS or explicitly enabled loopback HTTP, without credentials or queries."
        )
    path = unquote(parsed.path)
    if escape_controls(path) != path or any(part in {".", ".."} for part in path.split("/")):
        raise AppError("Helm URLs contain an unsafe path.")
    if oci and (not path.strip("/") or any(not part for part in path.strip("/").split("/"))):
        raise AppError("Register an explicit OCI chart repository path.")
    if oci:
        oci_chart_path(path.strip("/"))
        if path != parsed.path or path.rstrip("/") != "/" + path.strip("/"):
            raise AppError("OCI chart paths require literal canonical registry identifiers.")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def url_origin(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class HelmRepositoryKind(StrEnum):
    HTTP = "http"
    OCI = "oci"


@dataclass(frozen=True, slots=True, repr=False)
class RepositoryCredentials:
    username: str | None = None
    password: str | None = None
    token: str | None = None

    def __post_init__(self) -> None:
        if (self.username is None) != (self.password is None) or (
            self.token is not None and self.username is not None
        ):
            raise AppError("Choose separate Basic or bearer Helm repository credentials.")
        for value in (self.username, self.password, self.token):
            if value is not None:
                catalog_text(value)
        if self.username is not None and ":" in self.username:
            raise AppError("Basic repository usernames cannot contain a colon.")
        if self.token is not None and any(
            ord(char) <= 32 or ord(char) >= 127 for char in self.token
        ):
            raise AppError("Repository bearer tokens require bounded ASCII without whitespace.")


@dataclass(frozen=True, slots=True)
class HelmRepository:
    name: str
    url: str
    kind: HelmRepositoryKind
    revision: str
    allow_loopback_http: bool = False
    ca_file: Path | None = None
    token_origins: tuple[str, ...] = ()
    download_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        catalog_name(self.name)
        if not isinstance(self.kind, HelmRepositoryKind):
            raise AppError("Unknown Helm repository kind.")
        if (
            catalog_url(
                self.url,
                allow_loopback_http=self.allow_loopback_http,
                oci=self.kind is HelmRepositoryKind.OCI,
            )
            != self.url
        ):
            raise AppError("Helm repository URL must be canonical.")
        digest(self.revision)
        if self.ca_file is not None and (
            not isinstance(self.ca_file, Path) or not self.ca_file.is_absolute()
        ):
            raise AppError("Helm repository CA paths must be explicit and absolute.")
        if not isinstance(self.token_origins, tuple) or len(self.token_origins) > 8:
            raise AppError("Helm token origins exceed their configured bound.")
        for origin in self.token_origins:
            if (
                catalog_url(origin, allow_loopback_http=self.allow_loopback_http) != origin
                or url_origin(origin) != origin
            ):
                raise AppError("Helm token origins must be exact canonical origins.")
        if not isinstance(self.download_origins, tuple) or len(self.download_origins) > 8:
            raise AppError("Helm download origins exceed their configured bound.")
        for origin in self.download_origins:
            if (
                catalog_url(origin, allow_loopback_http=self.allow_loopback_http) != origin
                or url_origin(origin) != origin
                or (self.origin.startswith("https:") and not origin.startswith("https:"))
            ):
                raise AppError(
                    "Helm download origins require exact canonical origins without HTTPS downgrades."
                )

    @property
    def origin(self) -> str:
        if self.kind is HelmRepositoryKind.HTTP:
            return url_origin(self.url)
        scheme = "http" if self.allow_loopback_http else "https"
        parsed = urlsplit(self.url)
        return urlunsplit((scheme, parsed.netloc, "", "", ""))

    @property
    def oci_path(self) -> str:
        return urlsplit(self.url).path.strip("/").partition("@")[0]

    @property
    def pinned_digest(self) -> str | None:
        _, separator, value = urlsplit(self.url).path.partition("@")
        return value if separator else None


@dataclass(frozen=True, slots=True)
class ChartVersion:
    repository: str
    name: str
    version: str
    url: str
    sha256: str
    catalog_revision: str
    manifest_digest: str | None = None

    def __post_init__(self) -> None:
        catalog_name(self.repository)
        catalog_name(self.name)
        chart_version(self.version)
        catalog_text(self.url)
        digest(self.sha256)
        digest(self.catalog_revision)
        if self.manifest_digest is not None:
            oci_digest(self.manifest_digest)


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    generation: int = 0
    repositories: tuple[HelmRepository, ...] = ()
    charts: tuple[ChartVersion, ...] = ()

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 0:
            raise AppError("Helm catalog generations must be nonnegative integers.")
        if (
            not isinstance(self.repositories, tuple)
            or len(self.repositories) > MAX_REPOSITORIES
            or any(not isinstance(item, HelmRepository) for item in self.repositories)
        ):
            raise AppError("Helm catalog repositories exceed their typed inventory bound.")
        if (
            not isinstance(self.charts, tuple)
            or len(self.charts) > MAX_CATALOG_ENTRIES
            or any(not isinstance(item, ChartVersion) for item in self.charts)
        ):
            raise AppError("Helm chart versions exceed their typed inventory bound.")
        names = {item.name for item in self.repositories}
        revisions = {item.name: item.revision for item in self.repositories}
        keys = {(item.repository, item.name, item.version) for item in self.charts}
        if (
            len(names) != len(self.repositories)
            or len(keys) != len(self.charts)
            or any(revisions.get(item.repository) != item.catalog_revision for item in self.charts)
        ):
            raise AppError("Helm catalog contains duplicate or stale identities.")


@dataclass(frozen=True, slots=True, repr=False)
class ChartSnapshot:
    name: str
    version: str
    source: str
    sha256: str
    package: bytes
    default_values: bytes
    catalog_generation: int = 0
    manifest_digest: str | None = None
    layer_digest: str | None = None
    catalog_revision: str | None = None

    def __post_init__(self) -> None:
        validate_chart_snapshot(self)


def validate_chart_snapshot(snapshot: ChartSnapshot) -> None:
    from kuberich.domain.helm_archive import inspect_chart_package

    catalog_name(snapshot.name)
    chart_version(snapshot.version)
    catalog_text(snapshot.source)
    digest(snapshot.sha256)
    if (
        not isinstance(snapshot.package, bytes)
        or not 1 <= len(snapshot.package) <= MAX_CHART_BYTES
        or hashlib.sha256(snapshot.package).hexdigest() != snapshot.sha256
    ):
        raise AppError("Helm chart package content differs from its frozen digest or byte bound.")
    if type(snapshot.catalog_generation) is not int or snapshot.catalog_generation < 0:
        raise AppError("Helm chart catalog generation is invalid.")
    for value in (snapshot.manifest_digest, snapshot.layer_digest):
        if value is not None:
            oci_digest(value)
    if snapshot.layer_digest is not None and snapshot.layer_digest != "sha256:" + snapshot.sha256:
        raise AppError("OCI chart layer digest differs from the frozen package.")
    if snapshot.catalog_revision is not None:
        digest(snapshot.catalog_revision)
    defaults = inspect_chart_package(
        snapshot.package, expected_name=snapshot.name, expected_version=snapshot.version
    )
    if snapshot.default_values != defaults:
        raise AppError("Helm chart defaults differ from the frozen package.")
