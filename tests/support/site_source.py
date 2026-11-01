"""Owned site source copies with a chosen version, independent of the checkout's version."""

import hashlib
import json
import re
import shutil
from pathlib import Path

from packaging.version import Version

from scripts.build_site import MARKER, ROOT


def refresh(output: Path, path: Path) -> None:
    """Rehash a deliberately altered output so a semantic negative control runs."""
    manifest = json.loads((output / MARKER).read_text())
    manifest["files"][path.relative_to(output).as_posix()] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (output / MARKER).write_text(json.dumps(manifest))


def latest_published() -> str:
    """The newest version in the checked-in published-release inventory."""
    releases = json.loads((ROOT / "docs/published-releases.json").read_text())["releases"]
    return str(max(map(Version, releases)))


def unpublished_version() -> str:
    """A later minor version that the checked-in inventory never lists."""
    latest = Version(latest_published())
    return f"{latest.major}.{latest.minor + 1}.0"


def set_version(source: Path, version: str) -> None:
    project = source / "pyproject.toml"
    text = project.read_text()
    project.write_text(
        re.sub(r'^version = "[^"]+"', f'version = "{version}"', text, count=1, flags=re.M)
    )


def copy_source(destination: Path, version: str | None = None) -> Path:
    for relative in ("website", "docs", "src"):
        shutil.copytree(ROOT / relative, destination / relative)
    (destination / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/build_site.py", destination / "scripts/build_site.py")
    shutil.copyfile(ROOT / "scripts/site_reference.py", destination / "scripts/site_reference.py")
    shutil.copyfile(ROOT / "scripts/documentation.py", destination / "scripts/documentation.py")
    shutil.copyfile(ROOT / "pyproject.toml", destination / "pyproject.toml")
    if version is not None:
        set_version(destination, version)
    return destination


def published_source(destination: Path) -> Path:
    """Public indexing needs a published version; a prepared candidate is not one yet."""
    return copy_source(destination, latest_published())
