"""Native archives retain bytes and reject unsafe paths without extraction."""

import hashlib
import io
import os
import struct
import tarfile
from pathlib import Path

import pytest

from scripts import standalone


def header(target: str) -> bytes:
    value = bytearray(64)
    if target.startswith("linux-"):
        value[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", value, 18, 62 if target.endswith("x86_64") else 183)
    else:
        value[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", value, 4, 0x01000007 if target.endswith("x86_64") else 0x0100000C)
    return bytes(value)


def member(
    name: str, kind: bytes = tarfile.REGTYPE, *, mode: int = 0o644, link: str = ""
) -> tarfile.TarInfo:
    entry = tarfile.TarInfo(name)
    entry.type = kind
    entry.mode = mode
    entry.linkname = link
    return entry


def archive(
    path: Path,
    extras: list[tuple[tarfile.TarInfo, bytes]],
    *,
    cli_mode: int = 0o755,
    target: str = "linux-x86_64",
) -> Path:
    entries = [
        (member("kuberich", tarfile.DIRTYPE, mode=0o755), b""),
        (member("kuberich/kuberich", mode=cli_mode), header(target)),
        *extras,
    ]
    with tarfile.open(path, "w:gz") as output:
        for entry, content in entries:
            if entry.isfile():
                entry.size = len(content)
                output.addfile(entry, io.BytesIO(content))
            else:
                output.addfile(entry)
    return path


@pytest.mark.parametrize("target", standalone.TARGETS)
def test_native_headers_bind_actual_architecture(target):
    standalone.check_executable(header(target), target)
    for other in standalone.TARGETS:
        if other != target:
            with pytest.raises(ValueError):
                standalone.check_executable(header(target), other)
    with pytest.raises(ValueError):
        standalone.check_executable(b"#!/bin/sh\n", target)


@pytest.mark.parametrize(
    "system,machine,target",
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "AMD64", "macos-x86_64"),
    ],
)
def test_only_native_supported_targets(system, machine, target):
    assert standalone.native_target(system, machine) == target


@pytest.mark.parametrize("system,machine", [("Windows", "AMD64"), ("Linux", "s390x")])
def test_unsupported_targets_fail(system, machine):
    with pytest.raises(ValueError):
        standalone.native_target(system, machine)


def test_asset_names_require_canonical_version_and_target():
    assert (
        standalone.asset_name("0.1.0rc1", "linux-arm64") == "kuberich-0.1.0rc1-linux-arm64.tar.gz"
    )
    for version, target in [("v0.1.0", "linux-arm64"), ("0.1.0", "windows-x86_64")]:
        with pytest.raises(ValueError):
            standalone.asset_name(version, target)


def test_archive_is_deterministic_and_preserves_relative_symlinks_and_hardlinked_bytes(tmp_path):
    bundle = tmp_path / "owned"
    bundle.mkdir()
    cli = bundle / "kuberich"
    cli.write_bytes(header("linux-x86_64"))
    cli.chmod(0o755)
    library = bundle / "library"
    library.write_bytes(b"original native library")
    os.link(library, bundle / "copy")
    (bundle / "alias").symlink_to("library")
    first, second = tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"
    inventory = standalone.create_archive(bundle, first, "linux-x86_64", 123)
    assert inventory == standalone.create_archive(bundle, second, "linux-x86_64", 123)
    assert first.read_bytes() == second.read_bytes()
    assert inventory["kuberich/alias"] == {"kind": "symlink", "target": "library"}
    assert inventory["kuberich/library"] == inventory["kuberich/copy"]
    assert (
        inventory["kuberich/library"]["sha256"] == hashlib.sha256(library.read_bytes()).hexdigest()
    )
    with pytest.raises(FileExistsError):
        standalone.create_archive(bundle, first, "linux-x86_64", 123)


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "kuberich/../outside",
        "outside",
        "kuberich//alias",
        "kuberich/./alias",
        "kuberich\\file",
        "kuberich/\x1bfile",
    ],
)
def test_traversal_and_ambiguous_paths_are_rejected_without_writing(tmp_path, name):
    path = archive(tmp_path / "input.tar.gz", [(member(name), b"untrusted")])
    with pytest.raises(ValueError, match="canonical bundle"):
        standalone.archive_inventory(path, "linux-x86_64")
    assert sorted(item.name for item in tmp_path.iterdir()) == ["input.tar.gz"]


@pytest.mark.parametrize("link", ["/etc/passwd", "../../outside", "\\outside", "\x1bescape", ""])
def test_escaping_symlinks_fail(tmp_path, link):
    path = archive(
        tmp_path / "input.tar.gz", [(member("kuberich/link", tarfile.SYMTYPE, link=link), b"")]
    )
    with pytest.raises(ValueError):
        standalone.archive_inventory(path, "linux-x86_64")


@pytest.mark.parametrize(
    "extras,message",
    [
        ([(member("kuberich/kuberich"), b"duplicate")], "duplicate"),
        ([(member("kuberich/bad", mode=0o666), b"writable")], "permissions"),
        ([(member("kuberich/bad", mode=0o4755), b"setuid")], "permissions"),
        ([(member("kuberich/device", tarfile.CHRTYPE), b"")], "special device"),
        ([(member("kuberich/hard", tarfile.LNKTYPE, link="kuberich/kuberich"), b"")], "hard link"),
        (
            [
                (member("kuberich/a", tarfile.SYMTYPE, link="b"), b""),
                (member("kuberich/b", tarfile.SYMTYPE, link="a"), b""),
            ],
            "cycle",
        ),
        ([(member("kuberich/a", tarfile.SYMTYPE, link="missing"), b"")], "dangling"),
        ([(member("kuberich/nested/file"), b"payload")], "ancestors"),
        (
            [
                (member("kuberich/alias", tarfile.SYMTYPE, link="."), b""),
                (member("kuberich/alias/file"), b"payload"),
            ],
            "ancestors",
        ),
    ],
)
def test_invalid_members_cannot_be_qualified(tmp_path, extras, message):
    path = archive(tmp_path / "input.tar.gz", extras)
    with pytest.raises(ValueError, match=message):
        standalone.archive_inventory(path, "linux-x86_64")


def test_bounds_and_executable_mode_are_enforced(tmp_path, monkeypatch):
    path = archive(tmp_path / "input.tar.gz", [])
    monkeypatch.setattr(standalone, "MAX_FILES", 1)
    with pytest.raises(ValueError, match="excessive"):
        standalone.archive_inventory(path, "linux-x86_64")
    monkeypatch.setattr(standalone, "MAX_FILES", 100)
    monkeypatch.setattr(standalone, "MAX_BYTES", 63)
    with pytest.raises(ValueError, match="byte limit"):
        standalone.archive_inventory(path, "linux-x86_64")
    monkeypatch.setattr(standalone, "MAX_BYTES", 100)
    invalid = archive(tmp_path / "mode.tar.gz", [], cli_mode=0o644)
    with pytest.raises(ValueError, match="not executable"):
        standalone.archive_inventory(invalid, "linux-x86_64")


def test_declared_glibc_floor_is_observed_from_actual_symbol_versions():
    assert standalone.glibc_versions(b"GLIBC_2.3\0GLIBC_2.35\0GLIBC_2.3 GLIBC_PRIVATE") == [
        (2, 3),
        (2, 35),
    ]
