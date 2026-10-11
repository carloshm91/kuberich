"""Build a native locked-wheel bundle and preserve its exact archive and notices."""

import argparse
import ast
import base64
import hashlib
import json
import platform
import shutil
import struct
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from scripts.check_supply_chain import ROOT, run, selected_requirements, write_json
from scripts.standalone import (
    asset_name,
    check_executable,
    create_archive,
    glibc_versions,
    macos_minimum,
    native_target,
)
from scripts.standalone_python import original_digest, prepare
from scripts.supply_chain import digest, runtime_packages


def source_inputs(root: Path) -> dict[str, str]:
    paths = [
        *sorted((root / "src/kuberich").rglob("*.py")),
        *sorted((root / "src/kuberich").rglob("*.tcss")),
        root / "src/kuberich/py.typed",
        *sorted((root / "packaging/standalone").rglob("*.py")),
        *sorted((root / "packaging/standalone").rglob("*.json")),
        root / "packaging/standalone/REPLACING-PYTE.md",
        root / "pyproject.toml",
        root / "uv.lock",
        root / "LICENSE",
        root / "NOTICE",
        root / "scripts/build_standalone.py",
        root / "scripts/standalone.py",
        root / "scripts/standalone_python.py",
        root / "scripts/check_standalone.py",
        root / "scripts/standalone_release.py",
        root / "scripts/release.py",
        root / "scripts/release_policy.py",
        root / ".github/workflows/release.yml",
        root / "scripts/verify_standalone.py",
        root / "scripts/verify_shell_kind.py",
        root / "scripts/verify_eks_auth.py",
        root / "scripts/owned_kind.py",
        root / ".github/workflows/quality.yml",
        root / "tests/terminal/pty_support.py",
        *sorted((root / "tests/support").rglob("*.py")),
        *sorted((root / "tests/support").rglob("*.pyi")),
        root / "tests/support/native_helper.c",
        root / "scripts/check_supply_chain.py",
        root / "scripts/dependency_inventory.py",
        root / "scripts/supply_chain.py",
        root / "scripts/supply_chain_policy.json",
    ]
    return {str(path.relative_to(root)): digest(path) for path in paths}


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, timeout=10
    ).strip()


def retain_notices(inventory: dict[str, Any], directory: Path, root: Path) -> None:
    directory.mkdir()
    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(root / name, directory / name)
    stdlib = Path(inventory["stdlib_license"])
    if not stdlib.is_file():
        raise ValueError("The build interpreter must retain its original CPython license")
    shutil.copyfile(stdlib, directory / "CPYTHON-LICENSE.txt")
    extras = Path(inventory["base_prefix"]) / "licenses"
    full_python = inventory.get("full_python_distribution")
    if full_python is not None:
        extras = Path(full_python["python"]).parents[2] / "licenses"
        write_json(directory / "python-full-distribution.json", full_python)
    if extras.is_dir():
        shutil.copytree(extras, directory / "python-runtime", symlinks=False)
    for package in inventory["packages"]:
        name = package["name"].lower().replace("_", "-")
        notices = package["notices"]
        if not notices:
            raise ValueError(f"Missing original dependency/build-tool notice: {name}")
        for index, notice in enumerate(notices):
            content = base64.b64decode(notice["content_base64"], validate=True)
            if hashlib.sha256(content).hexdigest() != notice["sha256"]:
                raise ValueError("Original dependency notice digest differs")
            destination = directory / name
            destination.mkdir(exist_ok=True)
            (destination / f"{index:03d}-{Path(notice['file']).name}").write_bytes(content)
    write_json(directory / "dependency-inventory.json", inventory)


def analysis_binaries(path: Path) -> dict[str, str]:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("PyInstaller analysis exceeds its bounded format")
    value = ast.literal_eval(path.read_text())
    result = {}
    for item in value:
        if isinstance(item, list):
            for row in item:
                if isinstance(row, tuple) and len(row) == 3 and row[2] in {"BINARY", "EXTENSION"}:
                    if not isinstance(row[0], str) or not isinstance(row[1], str):
                        raise ValueError("Invalid frozen binary source identity")
                    result[row[0]] = row[1]
    if not result:
        raise ValueError("Missing original PyInstaller binary analysis")
    return result


def system_package(source: Path) -> str:
    """Use dpkg's original path identity on merged-/usr Linux hosts."""
    resolved = source.resolve()
    candidates = [source, resolved]
    if resolved.is_relative_to(Path("/usr/lib")):
        alias = Path("/lib") / resolved.relative_to("/usr/lib")
        if alias.resolve() == resolved:
            candidates.append(alias)
    for candidate in dict.fromkeys(candidates):
        owned = subprocess.run(
            ["dpkg-query", "-S", str(candidate)], capture_output=True, text=True, timeout=10
        )
        if owned.returncode == 0:
            lines = owned.stdout.splitlines()
            if len(lines) != 1 or ": " not in lines[0]:
                raise ValueError("Ambiguous original system-library package ownership")
            return lines[0].split(": ", 1)[0]
        if owned.returncode != 1:
            owned.check_returncode()
    raise ValueError("No original package owns the copied system library")


def native_evidence(bundle: Path, analysis: Path, notices: Path, target: str) -> dict[str, Any]:
    sources = analysis_binaries(analysis)
    evidence: dict[str, Any] = {}
    highest = (0, 0)
    highest_macos = (0, 0, 0)
    signatures = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(64)
        if header[:4] not in {b"\x7fELF", b"\xcf\xfa\xed\xfe"}:
            continue
        check_executable(header, target)
        relative = path.relative_to(bundle).as_posix()
        source = sources.get(relative.removeprefix("_internal/"))
        entry: dict[str, Any] = {"sha256": digest(path), "original_build_source": source}
        if target.startswith("macos-"):
            load_size = struct.unpack_from("<I", header, 20)[0]
            if load_size > 1024 * 1024:
                raise ValueError("Native macOS load commands exceed their bounded format")
            with path.open("rb") as commands:
                minimum = macos_minimum(commands.read(32 + load_size))
            highest_macos = max(highest_macos, minimum)
            entry["minimum_macos"] = list(minimum)
            verified = subprocess.run(
                ["codesign", "--verify", "--strict", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            verified.check_returncode()
            inspected = subprocess.run(
                ["codesign", "--display", "--verbose=4", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            description = inspected.stdout + inspected.stderr
            signatures[relative] = {
                "valid": True,
                "ad_hoc": "Signature=adhoc" in description,
                "developer_id": "Authority=Developer ID Application:" in description,
            }
        if target.startswith("linux-"):
            content = path.read_bytes()
            versions = glibc_versions(content)
            if b"GLIBC_ABI_" in content:
                raise ValueError("Unqualified special GLIBC ABI requirement")
            if versions:
                highest = max(highest, versions[-1])
            entry["glibc_symbol_versions"] = [list(value) for value in versions]
            if source and Path(source).resolve().is_relative_to(Path("/usr/lib")):
                package = system_package(Path(source))
                copyright = Path("/usr/share/doc") / package.split(":", 1)[0] / "copyright"
                if not copyright.is_file():
                    raise ValueError("Missing original copied system-library copyright")
                name = package.replace(":", "-") + "-copyright.txt"
                shutil.copyfile(copyright, notices / name)
                entry["system_package"] = package
                entry["system_notice_sha256"] = digest(notices / name)
        evidence[relative] = entry
    if "kuberich" not in evidence:
        raise ValueError("Missing original native executable evidence")
    return {
        "files": evidence,
        "highest_glibc_symbols": list(highest),
        "highest_macos_minimum": list(highest_macos),
        "macos_signing": {
            "verification_performed": bool(signatures),
            "files": signatures,
            "developer_id": bool(signatures)
            and all(entry["developer_id"] for entry in signatures.values()),
            "notarization_performed": False,
        },
    }


def build(
    root: Path,
    output: Path,
    *,
    target: str | None = None,
    diagnostic: bool = False,
    interpreter_archive: Path | None = None,
) -> dict[str, Any]:
    target = native_target() if target is None else target
    if target != native_target():
        raise ValueError("Builds must run on their declared native OS/architecture")
    before = source_inputs(root)
    commit = git(root, "rev-parse", "HEAD")
    clean = not git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "src",
        "scripts",
        "packaging",
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "NOTICE",
    )
    if not clean and not diagnostic:
        raise ValueError("Native qualification requires committed clean source inputs")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    asset = asset_name(version, target)
    output.mkdir(parents=True, exist_ok=False)
    work = output / "build"
    work.mkdir()
    log = output / "build-original.log"
    prepared = prepare(work / "python-runtime", target, archive=interpreter_archive)
    selected_python = prepared["python"]

    def command(argv: list[str]) -> None:
        run(argv, work, log)

    command(
        [
            "uv",
            "build",
            str(root),
            "--python",
            selected_python,
            "--wheel",
            "--out-dir",
            str(work / "wheel"),
        ]
    )
    command(
        [
            "uv",
            "export",
            "--project",
            str(root),
            "--python",
            selected_python,
            "--locked",
            "--no-default-groups",
            "--group",
            "standalone",
            "--no-emit-project",
            "--output-file",
            str(work / "build-requirements.txt"),
        ]
    )
    command(
        [
            "uv",
            "export",
            "--project",
            str(root),
            "--python",
            selected_python,
            "--locked",
            "--no-default-groups",
            "--no-emit-project",
            "--no-annotate",
            "--no-header",
            "--no-hashes",
            "--output-file",
            str(work / "runtime-requirements.txt"),
        ]
    )
    environment = work / "environment"
    command(["uv", "venv", "--python", selected_python, str(environment)])
    python = str(environment / "bin/python")
    command(
        [
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--require-hashes",
            "-r",
            str(work / "build-requirements.txt"),
        ]
    )
    wheels = list((work / "wheel").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("One immutable build wheel is required")
    command(["uv", "pip", "install", "--python", python, "--no-deps", str(wheels[0])])
    command(
        [
            python,
            "-I",
            str(root / "packaging/standalone/runtime_inventory.py"),
            str(root),
            str(output / "build-environment.json"),
        ]
    )
    inventory = json.loads((output / "build-environment.json").read_text())
    if Path(inventory["base_prefix"]).resolve() != Path(selected_python).parents[1].resolve():
        raise ValueError("The build environment must use the prepared full interpreter")
    inventory["full_python_distribution"] = prepared
    pins = selected_requirements(
        (work / "runtime-requirements.txt").read_text(), inventory["python"]
    )
    runtime = {
        **inventory,
        "packages": [
            item
            for item in inventory["packages"]
            if item["name"].lower().replace("_", "-") in {"kuberich", *pins}
        ],
    }
    if runtime_packages(runtime, project) != pins:
        raise ValueError("The native runtime must match every locked production dependency")
    command(
        [
            python,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--onedir",
            "--noupx",
            "--name",
            "kuberich",
            "--distpath",
            str(work / "native"),
            "--workpath",
            str(work / "analysis"),
            "--specpath",
            str(work / "spec"),
            "--recursive-copy-metadata",
            "kuberich",
            "--collect-all",
            "textual",
            "--collect-data",
            "kuberich",
            "--collect-data",
            "certifi",
            "--additional-hooks-dir",
            str(root / "packaging/standalone/hooks"),
            "--exclude-module",
            "readline",
            str(root / "packaging/standalone/entry.py"),
        ]
    )
    bundle = work / "native/kuberich"
    notices = bundle / "THIRD-PARTY-NOTICES"
    retain_notices(inventory, notices, root)
    native = native_evidence(bundle, work / "analysis/kuberich/Analysis-00.toc", notices, target)
    compatible_floor = not target.startswith("linux-") or tuple(
        native["highest_glibc_symbols"]
    ) <= (2, 35)
    if not compatible_floor and not diagnostic:
        raise ValueError("The built native libraries exceed the declared glibc 2.35 floor")
    macos_floor = tuple(native["highest_macos_minimum"]) <= (14, 0, 0)
    if target.startswith("macos-") and not macos_floor and not diagnostic:
        raise ValueError("The native load commands exceed the declared macOS 14 floor")
    if not (bundle / "_internal/pyte/__init__.py").is_file():
        raise ValueError("The original LGPL Pyte sources must be external and replaceable")
    shutil.copyfile(root / "packaging/standalone/REPLACING-PYTE.md", bundle / "REPLACING-PYTE.md")
    timestamp = int(git(root, "show", "-s", "--format=%ct", "HEAD"))
    archive = output / asset
    members = create_archive(bundle, archive, target, timestamp)
    if before != source_inputs(root) or commit != git(root, "rev-parse", "HEAD"):
        raise ValueError("Source inputs changed during the native build")
    for field in ("python", "shared_library"):
        if original_digest(Path(prepared[field])) != prepared[field + "_sha256"]:
            raise ValueError("The original interpreter executable/library changed during freezing")
    original_root = work / "python-runtime/python"
    if digest(original_root / "PYTHON.json") != prepared["metadata_sha256"]:
        raise ValueError("Original interpreter metadata changed during freezing")
    for relative, expected in prepared["licensing"]["notices"].items():
        if digest(original_root / relative) != expected:
            raise ValueError("Original interpreter notice changed during freezing")
    manifest = {
        "schema_version": 1,
        "source_commit": commit,
        "source_clean": clean,
        "diagnostic_only": diagnostic,
        "version": version,
        "target": target,
        "source_inputs": before,
        "python": inventory["python"],
        "full_python_distribution": prepared,
        "builder": platform.platform(),
        "wheel": {"name": wheels[0].name, "sha256": digest(wheels[0])},
        "archive": {"name": asset, "sha256": digest(archive), "members": members},
        "runtime_dependencies": pins,
        "native": native,
        "declared_minimum": "glibc 2.35" if target.startswith("linux-") else "macOS 14",
        "compatible_glibc_floor": compatible_floor,
        "compatible_macos_floor": macos_floor,
        "build_log_sha256": digest(log),
        "runtime_qualified": False,
    }
    write_json(output / "build-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target")
    parser.add_argument(
        "--interpreter-archive",
        type=Path,
        help="reuse the exact hash-pinned full interpreter archive; never accepts a different build",
    )
    parser.add_argument(
        "--diagnostic", action="store_true", help="local exploration; never qualifies a release"
    )
    args = parser.parse_args()
    try:
        manifest = build(
            ROOT,
            args.output.absolute(),
            target=args.target,
            diagnostic=args.diagnostic,
            interpreter_archive=args.interpreter_archive.absolute()
            if args.interpreter_archive
            else None,
        )
        print(
            json.dumps(
                {
                    "asset": manifest["archive"]["name"],
                    "sha256": manifest["archive"]["sha256"],
                    "runtime_qualified": False,
                    "diagnostic_only": args.diagnostic,
                }
            )
        )
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        SyntaxError,
    ) as error:
        parser.exit(1, f"Native build failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
