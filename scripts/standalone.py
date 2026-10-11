"""Validate native archive identity and retained bytes; never publish or rebuild."""

import gzip
import hashlib
import os
import platform
import posixpath
import re
import struct
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.version import Version

TARGETS = ("linux-x86_64", "linux-arm64", "macos-x86_64", "macos-arm64")
MAX_FILES = 10000
MAX_BYTES = 512 * 1024 * 1024


def native_target(system: str | None = None, machine: str | None = None) -> str:
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    operating_system = {"Linux": "linux", "Darwin": "macos"}.get(system)
    architecture = {
        "x86_64": "x86_64",
        "AMD64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if operating_system is None or architecture is None:
        raise ValueError("Standalone builds require a declared native Linux/macOS architecture")
    return operating_system + "-" + architecture


def asset_name(version: str, target: str) -> str:
    if target not in TARGETS or str(Version(version)) != version:
        raise ValueError("Standalone assets require a normalized version and declared target")
    return f"kuberich-{version}-{target}.tar.gz"


def check_executable(content: bytes, target: str) -> None:
    if target not in TARGETS or len(content) < 32:
        raise ValueError("Missing declared native executable header")
    if target.startswith("linux-"):
        if content[:6] != b"\x7fELF\x02\x01":
            raise ValueError("Standalone Linux executable must be little-endian ELF64")
        architecture = struct.unpack_from("<H", content, 18)[0]
        expected = 62 if target.endswith("x86_64") else 183
    else:
        if content[:4] != b"\xcf\xfa\xed\xfe":
            raise ValueError("Standalone macOS executable must be a native Mach-O64 slice")
        architecture = struct.unpack_from("<I", content, 4)[0]
        expected = 0x01000007 if target.endswith("x86_64") else 0x0100000C
    if architecture != expected:
        raise ValueError("Executable architecture differs from the declared archive target")


def safe_name(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or path.is_absolute()
        or ".." in path.parts
        or path.parts[0] != "kuberich"
        or path.as_posix() != value.rstrip("/")
    ):
        raise ValueError("Standalone archive path leaves its canonical bundle")
    return path


def safe_link(name: str, target: str) -> str:
    if not target or "\\" in target or any(ord(character) < 32 for character in target):
        raise ValueError("Invalid native archive symlink target")
    if PurePosixPath(target).is_absolute():
        raise ValueError("Native symlinks must be relative")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    safe_name(resolved)
    return resolved


def archive_inventory(archive: Path, target: str) -> dict[str, dict[str, Any]]:
    """Inspect without extraction; reject aliases, traversal, special files and growth."""
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("Native archive must be a regular file")
    inventory: dict[str, dict[str, Any]] = {}
    size = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in bundle:
            name = safe_name(entry.name).as_posix()
            if name in inventory or len(inventory) >= MAX_FILES:
                raise ValueError("Native archive has duplicate or excessive entries")
            if (entry.mode & 0o7000 or entry.mode & 0o022) and not entry.issym():
                raise ValueError("Native archive has unsafe file permissions")
            if entry.isdir():
                inventory[name] = {"kind": "directory", "mode": entry.mode}
            elif entry.issym():
                safe_link(name, entry.linkname)
                inventory[name] = {"kind": "symlink", "target": entry.linkname}
            elif entry.isfile():
                if entry.size < 0:
                    raise ValueError("Native archive contains a negative file size")
                size += entry.size
                if size > MAX_BYTES:
                    raise ValueError("Native archive exceeds its expanded byte limit")
                stream = bundle.extractfile(entry)
                if stream is None:
                    raise ValueError("Native archive file is missing")
                digest = hashlib.sha256()
                header = stream.read(64)
                digest.update(header)
                if name == "kuberich/kuberich":
                    check_executable(header, target)
                    if not entry.mode & 0o111:
                        raise ValueError("Native CLI is not executable")
                while chunk := stream.read(65536):
                    digest.update(chunk)
                inventory[name] = {
                    "kind": "file",
                    "mode": entry.mode,
                    "bytes": entry.size,
                    "sha256": digest.hexdigest(),
                }
            else:
                raise ValueError("Native archive contains a hard link or special device")
    if inventory.get("kuberich", {}).get("kind") != "directory":
        raise ValueError("Missing canonical native bundle directory")
    if inventory.get("kuberich/kuberich", {}).get("kind") != "file":
        raise ValueError("Missing native CLI")
    for name, metadata in inventory.items():
        if metadata["kind"] == "symlink":
            destination = safe_link(name, metadata["target"])
            visited = {name}
            while inventory.get(destination, {}).get("kind") == "symlink":
                if destination in visited:
                    raise ValueError("Native archive contains a symlink cycle")
                visited.add(destination)
                destination = safe_link(destination, inventory[destination]["target"])
            if destination not in inventory:
                raise ValueError("Native archive contains a dangling symlink")
        for parent in PurePosixPath(name).parents:
            if str(parent) == ".":
                break
            if inventory.get(str(parent), {}).get("kind") != "directory":
                raise ValueError("Native members must have real directory ancestors")
    return inventory


def create_archive(directory: Path, output: Path, target: str, timestamp: int) -> dict[str, Any]:
    """Normalize archive metadata while preserving contained relative symlinks."""
    if directory.is_symlink() or not directory.is_dir() or timestamp < 0:
        raise ValueError("Native archive requires an owned bundle and source timestamp")
    with (
        output.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle,
    ):
        for path in [directory, *sorted(directory.rglob("*"))]:
            name = "kuberich" + (
                "/" + path.relative_to(directory).as_posix() if path != directory else ""
            )
            entry = bundle.gettarinfo(str(path), arcname=name)
            if entry.islnk():
                # Duplicate source inodes become independent portable files.
                entry.type = tarfile.REGTYPE
                entry.linkname = ""
                entry.size = path.stat().st_size
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            entry.mtime = timestamp
            entry.mode = (
                0o777
                if entry.issym()
                else 0o755
                if (entry.isdir() or os.stat(path).st_mode & 0o111)
                else 0o644
            )
            if entry.isfile():
                with path.open("rb") as stream:
                    bundle.addfile(entry, stream)
            else:
                bundle.addfile(entry)
    return archive_inventory(output, target)


def glibc_versions(content: bytes) -> list[tuple[int, int]]:
    """Observe linked GLIBC symbol versions, independent of the builder's claim."""
    return sorted(
        {
            (int(major), int(minor))
            for major, minor in re.findall(rb"GLIBC_([0-9]+)\.([0-9]+)", content)
        }
    )


def macos_minimum(content: bytes) -> tuple[int, int, int]:
    """Read the actual Mach-O deployment command, rejecting truncation/other platforms."""
    if len(content) < 32 or content[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Missing native Mach-O deployment header")
    count, size = struct.unpack_from("<II", content, 16)
    if not 0 < count <= 4096 or size > 1024 * 1024 or len(content) < 32 + size:
        raise ValueError("Mach-O deployment commands are missing, truncated or excessive")
    offset = 32
    minimum = None
    for _ in range(count):
        if offset + 8 > 32 + size:
            raise ValueError("Truncated Mach-O load command")
        command, length = struct.unpack_from("<II", content, offset)
        if length < 8 or length % 8 or offset + length > 32 + size:
            raise ValueError("Invalid Mach-O load command length")
        if command in {0x24, 0x32}:
            required = 16 if command == 0x24 else 24
            if length < required or minimum is not None:
                raise ValueError("Invalid or duplicate macOS deployment command")
            if command == 0x32 and struct.unpack_from("<I", content, offset + 8)[0] != 1:
                raise ValueError("Standalone Mach-O target must be macOS")
            if command == 0x32:
                tools = struct.unpack_from("<I", content, offset + 20)[0]
                if length != 24 + 8 * tools:
                    raise ValueError(
                        "Mach-O build tool declarations differ from their command length"
                    )
            value = struct.unpack_from("<I", content, offset + (8 if command == 0x24 else 12))[0]
            minimum = value >> 16, value >> 8 & 0xFF, value & 0xFF
        offset += length
    if offset != 32 + size or minimum is None or minimum[0] == 0:
        raise ValueError("Missing complete native macOS deployment evidence")
    return minimum
