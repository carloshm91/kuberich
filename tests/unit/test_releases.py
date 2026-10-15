"""PEP 440 ordering and strict public-release/cache validation."""

import pytest

from kuberich.domain.releases import (
    CACHE_SECONDS,
    RELEASES,
    cached_release,
    installed_version,
    is_newer,
    release_record,
)
from kuberich.errors import AppError


def release(tag="v0.2.0", **changes):
    return {
        "tag_name": tag,
        "html_url": RELEASES + tag,
        "draft": False,
        "prerelease": False,
        **changes,
    }


def test_stable_record_roundtrip_cache_boundary_and_prerelease_installed_ordering():
    record = release_record(release())
    assert record.mapping() == release()
    for current, expected in [
        ("0.1.0", True),
        ("0.2.0rc1", True),
        ("0.2.0.dev0", True),
        ("0.2.0", False),
        ("0.3.0", False),
        ("0.2.0+local", False),
    ]:
        assert is_newer(record, current) is expected
    assert cached_release({"checked_at": 1, "release": release()}, 1 + CACHE_SECONDS) == record
    assert installed_version("0.1.0").release == (0, 1, 0)


@pytest.mark.parametrize("value", ["x" * 65, "invalid"])
def test_invalid_local_version_does_not_echo_untrusted_text(value):
    with pytest.raises(AppError) as error:
        installed_version(value)
    assert value not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        release(draft=True),
        release(draft=0),
        release(prerelease=True),
        release(tag_name=None),
        release(tag_name=""),
        release("v" + "1" * 65),
        release("v1..0"),
        release("v0.2.0rc1"),
        release("v0.2.0.dev0"),
        release("v0.2.0+private"),
        release(html_url="https://evil.invalid/v0.2.0"),
        release(html_url=RELEASES + "v0.3.0"),
    ],
)
def test_unverified_or_nonstable_records_never_become_notices(value):
    with pytest.raises(AppError):
        release_record(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"checked_at": True},
        {"checked_at": "1"},
        {"checked_at": float("nan")},
        {"checked_at": float("inf")},
        {"checked_at": 10**1000},
        {"checked_at": -100000},
        {"checked_at": 2},
        {"checked_at": 0, "release": None},
    ],
)
def test_expired_future_corrupt_and_invalid_cache_is_refused(value):
    with pytest.raises(AppError):
        cached_release(value, 1)
