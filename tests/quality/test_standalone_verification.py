"""Tampered provenance, native bytes, floors and retained assets must fail closed."""

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from scripts.build_standalone import source_inputs
from scripts.check_standalone import inspect_bundle, inspect_candidate
from scripts.standalone import create_archive
from scripts.standalone_python import pin_for

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def candidate(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for relative in source_inputs(ROOT):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Owned Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Owned native source fixture",
        ],
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    output = tmp_path / "candidate"
    output.mkdir()
    bundle = output / "kuberich"
    bundle.mkdir()
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 62)
    executable = bundle / "kuberich"
    executable.write_bytes(header + b"GLIBC_2.35\x00")
    executable.chmod(0o755)
    notice = b"Owned original notice\n"
    full = {
        "full_archive": pin_for("linux-x86_64"),
        "licensing": {
            "notices": {"licenses/LICENSE.owned.txt": hashlib.sha256(notice).hexdigest()}
        },
    }
    assets = {
        "THIRD-PARTY-NOTICES/python-full-distribution.json": json.dumps(full).encode(),
        "THIRD-PARTY-NOTICES/python-runtime/LICENSE.owned.txt": notice,
        "THIRD-PARTY-NOTICES/CPYTHON-LICENSE.txt": b"Owned CPython notice",
        "THIRD-PARTY-NOTICES/LICENSE": b"Owned project license",
        "THIRD-PARTY-NOTICES/NOTICE": b"Owned project notice",
        "REPLACING-PYTE.md": b"Owned source replacement instructions",
        "_internal/pyte/__init__.py": b"# Owned replaceable source fixture",
        "_internal/certifi/cacert.pem": b"Owned certificate data fixture",
        "_internal/kuberich/ui/kuberich.tcss": b"Screen { background: black; }",
        "_internal/textual/css/styles.py": b"# Owned inline stylesheet fixture",
    }
    for name, content in assets.items():
        path = bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    archive = output / "kuberich-0.0.1.dev0-linux-x86_64.tar.gz"
    members = create_archive(bundle, archive, "linux-x86_64", 1)
    manifest = {
        "schema_version": 1,
        "source_commit": commit,
        "source_clean": True,
        "diagnostic_only": False,
        "source_inputs": source_inputs(source),
        "version": "0.0.1.dev0",
        "target": "linux-x86_64",
        "archive": {
            "name": archive.name,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "members": members,
        },
        "native": {
            "files": {"kuberich": {"sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}}
        },
        "full_python_distribution": full,
        "compatible_glibc_floor": True,
    }
    (output / "build-manifest.json").write_text(json.dumps(manifest))
    return source, output, bundle, manifest


def test_original_git_archive_native_files_and_assets_are_measured(candidate):
    source, output, bundle, manifest = candidate
    assert inspect_candidate(source, output) == manifest
    result = inspect_bundle(bundle, manifest)
    assert result["highest_glibc_symbols"] == [2, 35]
    assert result["original_interpreter_notice_texts"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("source_commit", "0" * 40),
        ("source_clean", False),
        ("source_clean", 1),
        ("diagnostic_only", True),
        ("diagnostic_only", 0),
        ("source_inputs", {}),
    ],
)
def test_wrong_source_diagnostic_or_incomplete_inputs_cannot_qualify(candidate, field, value):
    source, output, _, manifest = candidate
    manifest[field] = value
    (output / "build-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="clean committed source"):
        inspect_candidate(source, output)


def test_dirty_working_files_cannot_impersonate_original_git_blobs(candidate):
    source, output, _, manifest = candidate
    path = source / "scripts/standalone.py"
    path.write_text("# changed after original commit\n")
    manifest["source_inputs"] = source_inputs(source)
    (output / "build-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Git blobs"):
        inspect_candidate(source, output)


@pytest.mark.parametrize("corruption", ["name", "checksum", "members", "bytes"])
def test_changed_archive_identity_or_member_inventory_cannot_qualify(candidate, corruption):
    source, output, _, manifest = candidate
    if corruption == "bytes":
        archive = output / manifest["archive"]["name"]
        archive.write_bytes(archive.read_bytes() + b"unexpected trailing bytes")
    elif corruption == "members":
        manifest["archive"]["members"] = {}
    else:
        manifest["archive"]["name" if corruption == "name" else "sha256"] = "changed"
    (output / "build-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="archive"):
        inspect_candidate(source, output)


@pytest.mark.parametrize(
    "corruption", ["wrong-architecture", "newer-glibc", "no-glibc", "missing-native"]
)
def test_actual_native_bytes_override_optimistic_compatibility_flags(candidate, corruption):
    _, _, bundle, manifest = candidate
    path = bundle / "kuberich"
    content = bytearray(path.read_bytes())
    if corruption == "wrong-architecture":
        struct.pack_into("<H", content, 18, 183)
    elif corruption == "newer-glibc":
        content.extend(b"GLIBC_2.38\x00")
    elif corruption == "no-glibc":
        content = content[:64]
    else:
        manifest["native"]["files"] = {}
    path.write_bytes(content)
    if corruption != "missing-native":
        manifest["native"]["files"]["kuberich"]["sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError):
        inspect_bundle(bundle, manifest)


@pytest.mark.parametrize(
    "asset",
    [
        "_internal/certifi/cacert.pem",
        "_internal/pyte/__init__.py",
        "_internal/kuberich/ui/kuberich.tcss",
        "_internal/textual/css/styles.py",
        "REPLACING-PYTE.md",
        "THIRD-PARTY-NOTICES/CPYTHON-LICENSE.txt",
    ],
)
def test_missing_or_empty_runtime_assets_are_rejected(candidate, asset):
    _, _, bundle, manifest = candidate
    (bundle / asset).write_bytes(b"")
    with pytest.raises(ValueError, match="asset"):
        inspect_bundle(bundle, manifest)


def test_changed_original_interpreter_pin_or_license_cannot_qualify(candidate):
    _, _, bundle, manifest = candidate
    manifest["full_python_distribution"]["full_archive"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="immutable pin"):
        inspect_bundle(bundle, manifest)
    manifest["full_python_distribution"]["full_archive"] = pin_for("linux-x86_64")
    (bundle / "THIRD-PARTY-NOTICES/python-runtime/LICENSE.owned.txt").write_bytes(b"changed notice")
    with pytest.raises(ValueError, match="notice bytes"):
        inspect_bundle(bundle, manifest)
