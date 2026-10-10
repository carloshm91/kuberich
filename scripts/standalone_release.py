"""Enroll exact native archives and original execution evidence without rebuilding."""

import base64
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.check_standalone import inspect_original
from scripts.standalone import TARGETS, asset_name, check_executable, glibc_versions, macos_minimum
from scripts.standalone_python import pin_for
from scripts.supply_chain import digest

REQUIRED_ASSETS = (
    "THIRD-PARTY-NOTICES/CPYTHON-LICENSE.txt",
    "THIRD-PARTY-NOTICES/LICENSE",
    "THIRD-PARTY-NOTICES/NOTICE",
    "REPLACING-PYTE.md",
    "_internal/pyte/__init__.py",
    "_internal/certifi/cacert.pem",
    "_internal/kuberich/ui/kuberich.tcss",
    "_internal/textual/css/styles.py",
)
RESTORATION = ("terminal_mode_restored", "alternate_screen_closed", "cursor_restored")
REPORTING_MODES = {"1000", "1003", "1004", "1006", "2004"}
KIND_CONTROLS = (
    "prewrite_owned_endpoint_verified",
    "real_two_container_selection",
    "embedded_shell_and_persistent_captured_heading",
    "configured_shell",
    "changed_source_config_does_not_retarget",
    "real_keyboard_resize_ctrl_c",
    "real_fullscreen_vi",
    "repeated_shell_return",
    "missing_shell_actionable",
    "real_rbac_exec_denial",
    "terminal_restored",
    "explicit_cluster_user_tls_overrides",
    "explicit_token_replaces_client_certificates",
    "impersonated_shell_and_actual_rbac_denial",
    "synthetic_eks_real_kubectl_exec_denial",
    "synthetic_aks_real_kubectl_exec_denial",
)


def payload(archive: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Read actual native headers, load commands, notices and assets on any release host."""
    target = manifest["target"]
    native: dict[str, str] = {}
    retained: dict[str, bytes] = {}
    glibc = (0, 0)
    macos = (0, 0, 0)
    full = manifest["full_python_distribution"]
    if full["full_archive"] != pin_for(target) or not full["licensing"]["notices"]:
        raise ValueError("Native interpreter must match the complete reviewed original pin")
    notices = {}
    for name, expected in full["licensing"]["notices"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "licenses":
            raise ValueError("Native notice path leaves its retained directory")
        notices["THIRD-PARTY-NOTICES/python-runtime/" + path.relative_to("licenses").as_posix()] = (
            expected
        )
    wanted = {*REQUIRED_ASSETS, *notices, "THIRD-PARTY-NOTICES/python-full-distribution.json"}
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in bundle:
            if not entry.isfile():
                continue
            stream = bundle.extractfile(entry)
            if stream is None:
                raise ValueError("Missing original native archive member")
            name = PurePosixPath(entry.name).relative_to("kuberich").as_posix()
            header = stream.read(64)
            is_native = header[:4] in {b"\x7fELF", b"\xcf\xfa\xed\xfe"}
            if is_native or name in wanted:
                content = header + stream.read()
                if name in wanted:
                    retained[name] = content
                if is_native:
                    check_executable(header, target)
                    native[name] = hashlib.sha256(content).hexdigest()
                    if target.startswith("linux-"):
                        glibc = max(glibc, max(glibc_versions(content), default=(0, 0)))
                    else:
                        macos = max(macos, macos_minimum(content[: 1024 * 1024 + 32]))
    if not native or native != {
        name: item["sha256"] for name, item in manifest["native"]["files"].items()
    }:
        raise ValueError("Original native file inventory differs from actual archive bytes")
    if target.startswith("linux-") and (glibc == (0, 0) or glibc > (2, 35)):
        raise ValueError("Original native archive exceeds the GLIBC 2.35 floor")
    if target.startswith("macos-") and (macos == (0, 0, 0) or macos > (14, 0, 0)):
        raise ValueError("Original native archive exceeds the macOS 14 floor")
    if any(not retained.get(name) for name in wanted):
        raise ValueError(
            "Original native certificate, stylesheet, source or notice asset is missing"
        )
    if json.loads(retained["THIRD-PARTY-NOTICES/python-full-distribution.json"]) != full:
        raise ValueError("Bundled original interpreter metadata differs")
    if any(
        hashlib.sha256(retained[name]).hexdigest() != expected for name, expected in notices.items()
    ):
        raise ValueError("Original interpreter notice bytes differ")
    return {
        "native_files": native,
        "highest_glibc_symbols": list(glibc),
        "highest_macos_minimum": list(macos),
    }


def json_record(records: dict[str, bytes], name: str) -> dict[str, Any]:
    value = json.loads(records[name])
    if not isinstance(value, dict):
        raise ValueError("Native evidence must contain a JSON object")
    return value


def check_records(
    root: Path, archive: Path, records: dict[str, bytes], sha: str, version: str, target: str
) -> None:
    if not 1 <= len(records) <= 32 or any(
        not isinstance(name, str)
        or not isinstance(content, bytes)
        or not content
        or len(content) > 1024 * 1024
        or (
            name not in {"candidate/build-manifest.json", "owned-kind-shell.json"}
            and not (
                PurePosixPath(name).parent == PurePosixPath("runtime")
                and PurePosixPath(name).suffix == ".json"
                and PurePosixPath(name).as_posix() == name
            )
        )
        for name, content in records.items()
    ):
        raise ValueError("Native original records must be bounded canonical JSON files")
    manifest = json_record(records, "candidate/build-manifest.json")
    if (
        manifest.get("source_commit") != sha
        or manifest.get("version") != version
        or manifest.get("target") != target
    ):
        raise ValueError("Native archive source, version or target differs from the release")
    inspect_original(root, manifest, archive)
    measured = payload(archive, manifest)
    host = json_record(records, "runtime/host-runtime.json")
    if (
        host.get("schema_version") != 1
        or host.get("source_commit") != sha
        or host.get("target") != target
        or host.get("archive") != archive.name
        or host.get("archive_sha256") != digest(archive)
        or host.get("runtime_qualified") is not False
        or host.get("publication_performed") is not False
        or host.get("owned_helper_source_sha256") != digest(root / "tests/support/native_helper.c")
        or any(host.get("native", {}).get(name) != value for name, value in measured.items())
    ):
        raise ValueError(
            "Native execution evidence is not bound to the original archive and source"
        )
    for scenario in ("missing_optional_tool", "auth_and_shell"):
        reference = host[scenario]
        name = reference["receipt"]
        if (
            PurePosixPath(name).name != name
            or reference.get("caller_kubeconfig_unchanged") is not True
        ):
            raise ValueError("Native terminal evidence must preserve the caller's kubeconfig")
        original = records["runtime/" + name]
        terminal = json.loads(original)
        modes = terminal.get("reporting_modes_disabled", {})
        if (
            hashlib.sha256(original).hexdigest() != reference["sha256"]
            or type(terminal.get("exit")) is not int
            or terminal["exit"] != 0
            or any(terminal.get(key) is not True for key in RESTORATION)
            or set(modes) != REPORTING_MODES
            or any(value is not True for value in modes.values())
        ):
            raise ValueError("Original native PTY receipt does not prove terminal restoration")
    controls = {
        name: json_record(records, f"runtime/{name}.json") for name in ("version", "help", "info")
    }
    if any(type(item.get("exit")) is not int or item["exit"] != 0 for item in controls.values()):
        raise ValueError("Native CLI execution did not succeed")
    info = json.loads(controls["info"]["stdout"])
    if (
        controls["version"]["stdout"].strip() != "kuberich " + version
        or info.get("version") != version
        or info.get("cluster_connected") is not False
    ):
        raise ValueError("Native CLI execution differs from release metadata")
    if target.startswith("linux-"):
        if (
            host.get("system_python_absent") is not True
            or host.get("external_python_execution_denied") is not False
        ):
            raise ValueError("Linux evidence must use a Python-free native runtime")
        for name in ("installed-packages", "missing-system-tools", "actual-glibc"):
            control = json_record(records, f"runtime/{name}.json")
            if type(control.get("exit")) is not int or control["exit"] != 0:
                raise ValueError("Linux clean-host controls did not succeed")
            if name == "installed-packages" and any(
                "python" in line.split()[0].lower()
                for line in control["stdout"].splitlines()
                if line.split()
            ):
                raise ValueError("Native Linux runtime contained a Python package")
            if name == "actual-glibc" and "2.35" not in control["stdout"]:
                raise ValueError("Native runtime did not use GLIBC 2.35")
        kind = json_record(records, "owned-kind-shell.json")
        if (
            kind.get("result") != "passed"
            or kind.get("application_entry") != "native"
            or kind.get("native_executable_sha256") != measured["native_files"]["kuberich"]
            or any(kind.get(name) is not True for name in KIND_CONTROLS)
        ):
            raise ValueError("Owned-kind execution does not qualify this exact native executable")
    else:
        if (
            host.get("system_python_absent") is not False
            or host.get("external_python_execution_denied") is not True
        ):
            raise ValueError("macOS must retain its explicit external-Python isolation limits")
        for name in ("external-python-denied", "system-python-denied"):
            control = json_record(records, f"runtime/{name}.json")
            if (
                type(control.get("exit")) is not int
                or control["exit"] == 0
                or "Operation not permitted" not in control.get("stderr", "")
            ):
                raise ValueError("macOS outside Python was not denied by the native sandbox")
        signatures = host["native"].get("macos_signatures", {})
        if (
            set(signatures) != set(measured["native_files"])
            or any(signature.get("valid") is not True for signature in signatures.values())
            or host["native"].get("notarization_performed") is not False
        ):
            raise ValueError("macOS original native signature evidence is missing or overstated")


def enroll(source: Path, output: Path, root: Path, sha: str, version: str) -> None:
    """Retain four archives and uniquely named provenance assets; PyPI remains source-only."""
    output.mkdir(mode=0o700, exist_ok=False)
    for target in TARGETS:
        directory = source / "standalone" / target
        archive = directory / "candidate" / asset_name(version, target)
        digest(directory / "candidate/build-manifest.json")
        records = {
            "candidate/build-manifest.json": (
                directory / "candidate/build-manifest.json"
            ).read_bytes()
        }
        for path in sorted((directory / "runtime").glob("*.json")):
            digest(path)
            records["runtime/" + path.name] = path.read_bytes()
        if target.startswith("linux-"):
            digest(directory / "owned-kind-shell.json")
            records["owned-kind-shell.json"] = (directory / "owned-kind-shell.json").read_bytes()
        check_records(root, archive, records, sha, version, target)
        shutil.copyfile(archive, output / archive.name)
        sidecar = {
            "schema_version": 1,
            "target": target,
            "records": {
                name: base64.b64encode(content).decode("ascii") for name, content in records.items()
            },
        }
        (output / (archive.name.removesuffix(".tar.gz") + ".provenance.json")).write_text(
            json.dumps(sidecar, sort_keys=True) + "\n", encoding="utf-8"
        )


def verify(directory: Path, root: Path, sha: str, version: str) -> None:
    expected: set[str] = set()
    for target in TARGETS:
        archive = directory / asset_name(version, target)
        sidecar = archive.name.removesuffix(".tar.gz") + ".provenance.json"
        expected.update((archive.name, sidecar))
        digest(directory / sidecar)
        if (directory / sidecar).stat().st_size > 48 * 1024 * 1024:
            raise ValueError("Native provenance exceeds its retained record limit")
        evidence = json.loads((directory / sidecar).read_bytes())
        if evidence.get("schema_version") != 1 or evidence.get("target") != target:
            raise ValueError("Native provenance schema or target differs")
        records = {
            name: base64.b64decode(value, validate=True)
            for name, value in evidence["records"].items()
        }
        check_records(root, archive, records, sha, version, target)
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError(
            "Native release assets must contain exactly the four targets and their provenance"
        )
