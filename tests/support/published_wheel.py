"""Immutable public Python upgrade inputs; no candidate can stand in for them."""

import hashlib
import re
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

from tests.support.source_candidate import published_baseline

PUBLISHED_WHEELS = {
    "0.2.0": {
        "url": "https://files.pythonhosted.org/packages/c1/3c/061a88bd7d498cd186305d5872cc755fb578684c2ea963772935c0f82901/kuberich-0.2.0-py3-none-any.whl",
        "sha256": "5d03bdb259d5b54b77d8100017ce4d59b71c37dde1d49ff8d539a231fe0d272c",
    }
}
MAX_WHEEL_BYTES = 10 * 1024 * 1024


def wheel_metadata(path: Path):
    name, version, _, _ = parse_wheel_filename(path.name)
    with zipfile.ZipFile(path) as archive:
        metadata = archive.getinfo(f"{name}-{version}.dist-info/METADATA")
        assert metadata.file_size <= 65536
        return BytesParser().parsebytes(archive.read(metadata))


def reviewed_wheel_name(version: str, pin: dict[str, str]) -> str:
    expected = f"kuberich-{version}-py3-none-any.whl"
    url = urlsplit(pin["url"])
    if (
        url.scheme != "https"
        or url.hostname != "files.pythonhosted.org"
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path.rsplit("/", 1)[-1] != expected
        or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    ):
        raise ValueError("Require the reviewed canonical public wheel pin")
    return expected


def verify_published_wheel(path: Path, version: str, pin: dict[str, str]) -> dict[str, str]:
    if path.name != reviewed_wheel_name(version, pin):
        raise ValueError("Published wheel filename differs from the pinned version")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.stat().st_size > MAX_WHEEL_BYTES or actual != pin["sha256"]:
        raise ValueError("Published wheel bytes differ from the reviewed digest")
    try:
        metadata = wheel_metadata(path)
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as error:
        raise ValueError("Malformed published wheel metadata") from error
    if metadata["Name"] != "kuberich" or metadata["Version"] != version:
        raise ValueError("Published wheel metadata differs from the pinned version")
    return {"filename": path.name, "version": version, "url": pin["url"], "sha256": actual}


def published_upgrade_wheel(directory: Path, candidate: str) -> tuple[Path, dict]:
    baseline = published_baseline(candidate)
    pin = PUBLISHED_WHEELS.get(baseline["version"])
    if pin is None:
        raise ValueError("Selected predecessor needs a reviewed immutable public wheel pin")
    directory.mkdir(parents=True)
    path = directory / reviewed_wheel_name(baseline["version"], pin)
    with urlopen(pin["url"], timeout=30) as response, path.open("xb") as output:
        data = response.read(MAX_WHEEL_BYTES + 1)
        output.write(data)
    return path, {**baseline, **verify_published_wheel(path, baseline["version"], pin)}


def require_wheelhouse(wheel: Path, directory: Path) -> None:
    """Fail before installation if locked wheels cannot meet the actual metadata."""
    available = {}
    for path in directory.glob("*.whl"):
        name, version, _, _ = parse_wheel_filename(path.name)
        available.setdefault(name, []).append(version)
    for value in wheel_metadata(wheel).get_all("Requires-Dist", []):
        requirement = Requirement(value)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        assert any(
            version in requirement.specifier
            for version in available.get(canonicalize_name(requirement.name), [])
        ), f"Locked wheelhouse cannot satisfy {requirement}"
