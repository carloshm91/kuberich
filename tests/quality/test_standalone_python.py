"""Full interpreter ingestion binds original bytes and rejects unsafe enrollment."""

import hashlib
import io
import json
import struct
import tarfile
from pathlib import Path

import pytest
import zstandard

from scripts import standalone_python
from scripts.standalone import TARGETS


def full_archive(tmp_path, *, extra=None, missing_notice=False, triple="x86_64-unknown-linux-gnu"):
    metadata = {
        "version": "8",
        "python_version": "3.12.12",
        "target_triple": triple,
        "python_exe": "install/bin/python3.12",
        "licenses": ["Python-2.0"],
        "license_path": "licenses/LICENSE.cpython.txt",
        "build_info": {
            "core": {"shared_lib": "install/lib/libpython3.12.so.1.0"},
            "extensions": {
                "_ctypes": [
                    {
                        "variant": "default",
                        "in_core": False,
                        "licenses": ["MIT"],
                        "license_paths": ["licenses/LICENSE.libffi.txt"],
                        "links": [{"name": "ffi", "path_static": "build/lib/libffi.a"}],
                    }
                ]
            },
        },
    }
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 62)
    members = [
        ("python/PYTHON.json", json.dumps(metadata).encode()),
        ("python/install/bin/python3.12", bytes(header)),
        ("python/install/lib/libpython3.12.so.1.0", bytes(header)),
        ("python/licenses/LICENSE.cpython.txt", b"original CPython text"),
    ]
    if not missing_notice:
        members.append(("python/licenses/LICENSE.libffi.txt", b"original libffi text"))
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode="w") as output:
        for name, content in members:
            entry = tarfile.TarInfo(name)
            entry.mode = 0o755 if name.endswith("python3.12") else 0o644
            entry.size = len(content)
            output.addfile(entry, io.BytesIO(content))
        if extra:
            output.addfile(extra)
    archive = tmp_path / "original.tar.zst"
    archive.write_bytes(zstandard.ZstdCompressor().compress(plain.getvalue()))
    pin = {
        "version": "3.12.12",
        "triple": "x86_64-unknown-linux-gnu",
        "bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "supplemental_notices": {},
    }
    return archive, pin


def test_all_native_interpreters_have_distinct_immutable_full_archive_pins():
    pins = [standalone_python.pin_for(target) for target in TARGETS]
    assert len({pin["sha256"] for pin in pins}) == 4
    assert all(
        pin["version"] == "3.12.15" and pin["name"].endswith("-full.tar.zst") for pin in pins
    )
    assert all(
        pin["url"].startswith(
            "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/"
        )
        for pin in pins
    )
    with pytest.raises(ValueError):
        standalone_python.pin_for("windows-x86_64")


def test_original_component_licenses_and_metadata_stay_with_actual_interpreter(tmp_path):
    archive, pin = full_archive(tmp_path)
    destination = tmp_path / "prepared"
    result = standalone_python.extract_original(archive, destination, pin, "linux-x86_64")
    assert result["full_archive"]["sha256"] == pin["sha256"]
    assert (
        result["licensing"]["notices"]["licenses/LICENSE.libffi.txt"]
        == hashlib.sha256(b"original libffi text").hexdigest()
    )
    assert result["licensing"]["components"]["_ctypes:default"]["links"] == [
        {"name": "ffi", "path_static": "build/lib/libffi.a"}
    ]
    interpreter = Path(result["python"])
    assert interpreter.is_relative_to(destination)
    assert interpreter.stat().st_mode & 0o111
    assert result["python_sha256"] == hashlib.sha256(interpreter.read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["size", "digest", "symlink"])
def test_forged_original_cannot_create_an_extraction(tmp_path, change):
    archive, pin = full_archive(tmp_path)
    if change == "size":
        pin["bytes"] += 1
    elif change == "digest":
        pin["sha256"] = "0" * 64
    else:
        link = tmp_path / "alias.tar.zst"
        link.symlink_to(archive)
        archive = link
    output = tmp_path / "prepared"
    with pytest.raises(ValueError):
        standalone_python.extract_original(archive, output, pin, "linux-x86_64")
    assert not output.exists()


def test_missing_original_notice_is_not_silently_inferred_or_waived(tmp_path):
    archive, pin = full_archive(tmp_path, missing_notice=True)
    with pytest.raises(ValueError, match="Missing unpinned original component notice"):
        standalone_python.extract_original(archive, tmp_path / "prepared", pin, "linux-x86_64")


@pytest.mark.parametrize(
    "name,target",
    [
        ("python/install/bin/escape", "../../../outside"),
        ("python/install/bin/escape", "/etc/passwd"),
        ("../outside", "anything"),
    ],
)
def test_original_interpreter_links_cannot_escape_the_owned_installation(tmp_path, name, target):
    extra = tarfile.TarInfo(name)
    extra.type = tarfile.SYMTYPE
    extra.linkname = target
    archive, pin = full_archive(tmp_path, extra=extra)
    with pytest.raises(ValueError):
        standalone_python.extract_original(archive, tmp_path / "prepared", pin, "linux-x86_64")
    assert not (tmp_path / "outside").exists()


def test_original_interpreter_cannot_relabel_its_platform(tmp_path):
    archive, pin = full_archive(tmp_path, triple="aarch64-unknown-linux-gnu")
    with pytest.raises(ValueError, match="pinned target"):
        standalone_python.extract_original(archive, tmp_path / "prepared", pin, "linux-x86_64")


def test_retained_bytes_and_entry_counts_are_bounded(tmp_path, monkeypatch):
    archive, pin = full_archive(tmp_path)
    monkeypatch.setattr(standalone_python, "MAX_FILES", 1)
    with pytest.raises(ValueError, match="excessive"):
        standalone_python.extract_original(archive, tmp_path / "members", pin, "linux-x86_64")
    monkeypatch.setattr(standalone_python, "MAX_FILES", 100)
    with tarfile.open(
        fileobj=io.BytesIO(zstandard.ZstdDecompressor().decompress(archive.read_bytes()))
    ) as original:
        budget = original.getmember("python/PYTHON.json").size + 32
    monkeypatch.setattr(standalone_python, "MAX_RETAINED_BYTES", budget)
    with pytest.raises(ValueError, match="byte limit"):
        standalone_python.extract_original(archive, tmp_path / "bytes", pin, "linux-x86_64")
