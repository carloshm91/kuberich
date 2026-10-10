"""Read an exact native candidate and its original source; never rebuild or publish."""

import argparse
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from scripts.build_standalone import source_inputs
from scripts.standalone import (
    archive_inventory,
    asset_name,
    check_executable,
    glibc_versions,
    macos_minimum,
)
from scripts.standalone_python import pin_for
from scripts.supply_chain import digest

ROOT = Path(__file__).resolve().parents[1]


def inspect_candidate(source: Path, candidate: Path) -> dict[str, Any]:
    manifest_path = candidate / "build-manifest.json"
    digest(manifest_path)
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True, timeout=15
    ).strip()
    if (
        manifest["schema_version"] != 1
        or manifest["source_commit"] != commit
        or manifest["source_clean"] is not True
        or manifest["diagnostic_only"] is not False
        or manifest["source_inputs"] != source_inputs(source)
    ):
        raise ValueError("Native candidate must match the complete clean committed source")
    # Compare original Git blobs as well as working files; a dirty tree cannot impersonate HEAD.
    for name, expected in manifest["source_inputs"].items():
        original = subprocess.check_output(
            ["git", "-C", str(source), "show", commit + ":" + name], timeout=15
        )
        if hashlib.sha256(original).hexdigest() != expected:
            raise ValueError("Native inputs differ from their original Git blobs")
    target = manifest["target"]
    name = asset_name(manifest["version"], target)
    archive = candidate / name
    if manifest["archive"]["name"] != name or digest(archive) != manifest["archive"]["sha256"]:
        raise ValueError("Native archive name or original checksum differs")
    inventory = archive_inventory(archive, target)
    if inventory != manifest["archive"]["members"]:
        raise ValueError("Native archive members differ from original construction evidence")
    return manifest


def inspect_bundle(bundle: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Measure extracted bytes independently of producer compatibility/signature flags."""
    target = manifest["target"]
    native = {}
    highest_glibc = (0, 0)
    highest_macos = (0, 0, 0)
    signatures = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(64)
        if header[:4] not in {b"\x7fELF", b"\xcf\xfa\xed\xfe"}:
            continue
        relative = path.relative_to(bundle).as_posix()
        check_executable(header, target)
        native[relative] = digest(path)
        if target.startswith("linux-"):
            versions = glibc_versions(path.read_bytes())
            highest_glibc = max(highest_glibc, max(versions, default=(0, 0)))
        else:
            with path.open("rb") as stream:
                floor = macos_minimum(stream.read(1024 * 1024 + 32))
            highest_macos = max(highest_macos, floor)
            subprocess.run(
                ["codesign", "--verify", "--strict", str(path)],
                capture_output=True,
                timeout=30,
                check=True,
            )
            signature = subprocess.run(
                ["codesign", "--display", "--verbose=4", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            text = signature.stdout + signature.stderr
            signatures[relative] = {
                "valid": True,
                "ad_hoc": "Signature=adhoc" in text,
                "developer_id": "Authority=Developer ID Application:" in text,
            }
    expected = {name: item["sha256"] for name, item in manifest["native"]["files"].items()}
    if not native or native != expected:
        raise ValueError("Extracted native file identity differs from the complete inventory")
    if target.startswith("linux-") and (highest_glibc == (0, 0) or highest_glibc > (2, 35)):
        raise ValueError("Measured native GLIBC symbols exceed the promised 2.35 floor")
    if target.startswith("macos-") and (highest_macos == (0, 0, 0) or highest_macos > (14, 0, 0)):
        raise ValueError("Measured native load commands exceed the promised macOS 14 floor")
    full = manifest["full_python_distribution"]
    if full["full_archive"] != pin_for(target):
        raise ValueError("Interpreter evidence differs from the reviewed immutable pin")
    original = json.loads(
        (bundle / "THIRD-PARTY-NOTICES/python-full-distribution.json").read_text()
    )
    if original != full or not full["licensing"]["notices"]:
        raise ValueError("Bundled original interpreter provenance is missing or different")
    for relative, expected_notice in full["licensing"]["notices"].items():
        relative_path = Path(relative)
        if ".." in relative_path.parts or relative_path.is_absolute():
            raise ValueError("Original notice path leaves its retained directory")
        notice = (
            bundle / "THIRD-PARTY-NOTICES/python-runtime" / relative_path.relative_to("licenses")
        )
        if digest(notice) != expected_notice:
            raise ValueError("Bundled original interpreter notice bytes differ")
    for required in (
        "THIRD-PARTY-NOTICES/CPYTHON-LICENSE.txt",
        "THIRD-PARTY-NOTICES/LICENSE",
        "THIRD-PARTY-NOTICES/NOTICE",
        "REPLACING-PYTE.md",
        "_internal/pyte/__init__.py",
        "_internal/certifi/cacert.pem",
        "_internal/kuberich/ui/kuberich.tcss",
        "_internal/textual/css/styles.py",
    ):
        path = bundle / required
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Missing retained runtime certificate, source or notice asset")
    return {
        "native_files": native,
        "highest_glibc_symbols": list(highest_glibc),
        "highest_macos_minimum": list(highest_macos),
        "macos_signatures": signatures,
        "notarization_performed": False,
        "original_interpreter_notice_texts": len(full["licensing"]["notices"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--extract", type=Path, help="extract the inspected archive to a new owned directory"
    )
    args = parser.parse_args()
    manifest = inspect_candidate(args.source.absolute(), args.candidate.absolute())
    if args.extract is not None:
        destination = args.extract.absolute()
        destination.mkdir(parents=True, exist_ok=False)
        with tarfile.open(args.candidate / manifest["archive"]["name"], "r:gz") as archive:
            archive.extractall(destination, filter="data")
        inspect_bundle(destination / "kuberich", manifest)
    print(json.dumps({"source_commit": manifest["source_commit"], "target": manifest["target"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
