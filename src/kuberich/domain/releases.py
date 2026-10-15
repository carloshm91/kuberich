"""Stable release validation; remote titles, bodies and arbitrary URLs are never used."""

import re
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

from kuberich.errors import AppError

RELEASES = "https://github.com/carloshm91/kuberich/releases/tag/"
CACHE_SECONDS = 86400


def installed_version(text: str) -> Version:
    if len(text) > 64:
        raise AppError("Installed version is unavailable; version check skipped.")
    try:
        return Version(text)
    except InvalidVersion:
        raise AppError("Installed version is unavailable; version check skipped.") from None


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    url: str

    def mapping(self) -> dict[str, object]:
        return {"tag_name": self.tag, "html_url": self.url, "draft": False, "prerelease": False}


def release_record(value: object) -> Release:
    if (
        not isinstance(value, dict)
        or value.get("draft") is not False
        or value.get("prerelease") is not False
    ):
        raise AppError("No verified stable public release was returned.")
    tag = value.get("tag_name")
    if not isinstance(tag, str) or re.fullmatch(r"v?[0-9][0-9A-Za-z.\-]{0,63}", tag) is None:
        raise AppError("Release version is invalid; no update announced.")
    try:
        parsed = Version(tag)
    except InvalidVersion:
        raise AppError("Release version is invalid; no update announced.") from None
    if (
        parsed.is_prerelease
        or parsed.is_devrelease
        or parsed.local is not None
        or value.get("html_url") != RELEASES + tag
    ):
        raise AppError("No verified stable public release was returned.")
    return Release(str(parsed), tag, RELEASES + tag)


def is_newer(release: Release, current: str) -> bool:
    return Version(release.version) > installed_version(current)


def cached_release(value: object, now: float) -> Release:
    if not isinstance(value, dict):
        raise AppError("Version cache is invalid.")
    stamp = value.get("checked_at")
    if (
        not isinstance(stamp, (int, float))
        or isinstance(stamp, bool)
        or not 0 <= stamp <= now
        or now - stamp > CACHE_SECONDS
    ):
        raise AppError("Version cache expired or has an invalid clock.")
    return release_record(value.get("release"))
