"""Prepare a hash-pinned full interpreter with original component license texts."""

import argparse
import hashlib
import json
import os
import posixpath
import shutil
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

import zstandard

from scripts.standalone import TARGETS, check_executable, native_target

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "packaging/standalone/python-runtime.json"
MAX_FILES = 30000
MAX_RETAINED_BYTES = 1024 * 1024 * 1024


def pin_for(target: str, pins: Path = PINS) -> dict[str, Any]:
    data = json.loads(pins.read_text())
    if data["schema_version"] != 1 or set(data["targets"]) != set(TARGETS) or target not in TARGETS:
        raise ValueError("The interpreter pin inventory must cover every native target")
    item = data["targets"][target]
    name = (
        f"cpython-{data['python_version']}+{data['release']}-{item['triple']}-pgo+lto-full.tar.zst"
    )
    url = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        + data["release"]
        + "/"
        + urllib.parse.quote(name)
    )
    return {
        **item,
        "version": data["python_version"],
        "release": data["release"],
        "name": name,
        "url": url,
        "supplemental_notices": data["supplemental_notices"],
    }


def original_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_name(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or path.parts[0] != "python"
        or path.as_posix() != value.rstrip("/")
    ):
        raise ValueError("Original interpreter archive leaves its canonical root")
    return path


def download_original(url: str, path: Path, size: int, expected: str) -> None:
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("Original interpreter sources require HTTPS")
    deadline = time.monotonic() + 240
    with urllib.request.urlopen(url, timeout=30) as remote, path.open("xb") as output:
        total = 0
        while chunk := remote.read(65536):
            total += len(chunk)
            if time.monotonic() > deadline:
                raise ValueError("Original interpreter download exceeded its total deadline")
            if total > size:
                raise ValueError("Downloaded original exceeds its pinned size")
            output.write(chunk)
    if total != size or original_digest(path) != expected:
        raise ValueError("Downloaded original differs from its pinned size/digest")


def supplemental_notices(
    directory: Path, metadata: dict[str, Any], pin: dict[str, Any]
) -> dict[str, Any]:
    referenced = {metadata["license_path"]}
    for variants in metadata["build_info"]["extensions"].values():
        for variant in variants:
            referenced.update(variant.get("license_paths", []))
    supplemented = {}
    for relative in sorted(referenced):
        path = canonical_name("python/" + relative)
        if path.parts[1:2] != ("licenses",):
            raise ValueError("Original component notice must stay in its license directory")
        destination = directory / path
        if destination.is_file():
            continue
        original = pin["supplemental_notices"].get(relative)
        if original is None:
            raise ValueError(f"Missing unpinned original component notice: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        download_original(original["url"], destination, original["bytes"], original["sha256"])
        supplemented[relative] = original
    return supplemented


def notice_inventory(directory: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    notices = {}
    components = {
        "cpython": {"licenses": metadata["licenses"], "license_paths": [metadata["license_path"]]}
    }
    for name, variants in metadata["build_info"]["extensions"].items():
        for variant in variants:
            if variant.get("license_paths"):
                components[name + ":" + variant["variant"]] = {
                    "licenses": variant["licenses"],
                    "license_paths": variant["license_paths"],
                    "in_core": variant["in_core"],
                    "links": variant["links"],
                }
    for component in components.values():
        for relative in component["license_paths"]:
            path = canonical_name("python/" + relative)
            if path.parts[1] != "licenses":
                raise ValueError(
                    "Interpreter component notice must use the original license directory"
                )
            original = directory / path
            if original.is_symlink() or not original.is_file():
                raise ValueError(f"Missing original interpreter component notice: {relative}")
            notices[relative] = original_digest(original)
    # Preserve every original notice, including build/core dependencies, not just selected extensions.
    for original in sorted((directory / "python/licenses").rglob("*")):
        if original.is_symlink():
            raise ValueError("Original interpreter notices cannot be symlinks")
        if original.is_file():
            notices[original.relative_to(directory / "python").as_posix()] = original_digest(
                original
            )
    if not notices or not components:
        raise ValueError("Original interpreter licensing inventory is empty")
    return {"components": components, "notices": notices}


def extract_original(
    archive: Path, directory: Path, pin: dict[str, Any], target: str
) -> dict[str, Any]:
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size != pin["bytes"]:
        raise ValueError("Interpreter archive must match the pinned regular file size")
    if original_digest(archive) != pin["sha256"]:
        raise ValueError("Interpreter archive differs from its immutable release digest")
    directory.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    retained_bytes = 0
    links = []
    with (
        archive.open("rb") as source,
        zstandard.ZstdDecompressor().stream_reader(source) as stream,
        tarfile.open(fileobj=stream, mode="r|") as bundle,
    ):
        for entry in bundle:
            path = canonical_name(entry.name)
            if len(seen) >= MAX_FILES or str(path) in seen:
                raise ValueError("Original interpreter has duplicate or excessive members")
            seen.add(str(path))
            if path != PurePosixPath("python/PYTHON.json") and path.parts[1:2] not in {
                ("install",),
                ("licenses",),
            }:
                continue
            destination = directory / path
            if any(
                parent.is_symlink()
                for parent in destination.parents
                if parent.is_relative_to(directory)
            ):
                raise ValueError("Interpreter extraction cannot traverse symlink directories")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if entry.isdir():
                destination.mkdir(exist_ok=True)
            elif entry.issym():
                if PurePosixPath(entry.linkname).is_absolute() or "\\" in entry.linkname:
                    raise ValueError("Interpreter symlinks must be contained and relative")
                resolved = canonical_name(
                    posixpath.normpath(posixpath.join(str(path.parent), entry.linkname))
                )
                if resolved.parts[1:2] != ("install",):
                    raise ValueError("Interpreter symlink leaves its installation")
                destination.symlink_to(entry.linkname)
                links.append(destination)
            elif entry.isfile() and 0 <= entry.size <= MAX_RETAINED_BYTES:
                retained_bytes += entry.size
                if retained_bytes > MAX_RETAINED_BYTES:
                    raise ValueError("Original interpreter exceeds its retained byte limit")
                content = bundle.extractfile(entry)
                if content is None:
                    raise ValueError("Original interpreter is missing a regular payload")
                with destination.open("xb") as output:
                    shutil.copyfileobj(content, output)
                destination.chmod(0o755 if entry.mode & 0o111 else 0o644)
                os.utime(destination, (entry.mtime, entry.mtime))
            else:
                raise ValueError("Original interpreter contains an unsupported selected member")
    for link in links:
        if not link.resolve(strict=True).is_relative_to(directory / "python/install"):
            raise ValueError("Interpreter symlink resolves outside its installation")
    metadata_path = directory / "python/PYTHON.json"
    metadata = json.loads(metadata_path.read_text())
    if (
        metadata["version"] != "8"
        or metadata["python_version"] != pin["version"]
        or metadata["target_triple"] != pin["triple"]
    ):
        raise ValueError("Original full interpreter metadata differs from its pinned target")
    interpreter = directory / canonical_name("python/" + metadata["python_exe"])
    if not interpreter.is_file() or not interpreter.resolve().is_relative_to(
        directory / "python/install"
    ):
        raise ValueError("Original native interpreter leaves its installation")
    with interpreter.open("rb") as executable:
        check_executable(executable.read(64), target)
    shared = directory / canonical_name("python/" + metadata["build_info"]["core"]["shared_lib"])
    if shared.is_symlink() or not shared.is_file():
        raise ValueError("Original interpreter shared library must be a regular payload")
    with shared.open("rb") as executable:
        check_executable(executable.read(64), target)
    supplemented = supplemental_notices(directory, metadata, pin)
    licensing = {**notice_inventory(directory, metadata), "supplemental_sources": supplemented}
    receipt = {
        "schema_version": 1,
        "target": target,
        "full_archive": pin,
        "python": str(interpreter),
        "python_sha256": original_digest(interpreter),
        "shared_library": str(shared),
        "shared_library_sha256": original_digest(shared),
        "metadata_sha256": original_digest(metadata_path),
        "licensing": licensing,
        "members_observed": len(seen),
        "retained_bytes": retained_bytes,
    }
    (directory / "python-runtime.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    return receipt


def prepare(directory: Path, target: str, *, archive: Path | None = None) -> dict[str, Any]:
    pin = pin_for(target)
    if archive is None:
        directory.parent.mkdir(parents=True, exist_ok=True)
        archive = directory.parent / pin["name"]
        download_original(pin["url"], archive, pin["bytes"], pin["sha256"])
    return extract_original(archive, directory, pin, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", default=native_target(), choices=TARGETS)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.output.absolute(), args.target, archive=args.archive)
        print(
            json.dumps(
                {
                    "python": result["python"],
                    "original_notices": len(result["licensing"]["notices"]),
                    "target": args.target,
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError) as error:
        parser.exit(1, f"Native interpreter preparation failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
