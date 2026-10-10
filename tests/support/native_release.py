"""Owned parser fixtures, never executable or evidence of native runtime qualification."""

import json
import struct
from pathlib import Path

from scripts.build_standalone import source_inputs
from scripts.standalone import TARGETS, asset_name, create_archive
from scripts.standalone_python import pin_for
from scripts.standalone_release import KIND_CONTROLS, REPORTING_MODES, REQUIRED_ASSETS, RESTORATION
from scripts.supply_chain import digest


def candidates(root: Path, commit: str, version: str, destination: Path) -> None:
    """Construct tiny ELF/Mach-O data and controlled reports for reader failure tests."""
    inputs = source_inputs(root)
    for target in TARGETS:
        directory = destination / "standalone" / target
        output = directory / "candidate"
        bundle = output / "kuberich"
        bundle.mkdir(parents=True)
        header = bytearray(64)
        linux = target.startswith("linux-")
        if linux:
            header[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<H", header, 18, 62 if target.endswith("x86_64") else 183)
            header.extend(b"GLIBC_2.35\x00")
        else:
            header[:4] = b"\xcf\xfa\xed\xfe"
            struct.pack_into(
                "<I", header, 4, 0x01000007 if target.endswith("x86_64") else 0x0100000C
            )
            struct.pack_into("<II", header, 16, 1, 24)
            struct.pack_into("<IIIIII", header, 32, 0x32, 24, 1, 14 << 16, 14 << 16, 0)
        executable = bundle / "kuberich"
        executable.write_bytes(header)
        executable.chmod(0o755)
        for name in REQUIRED_ASSETS:
            path = bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Owned parser fixture; not an executable or runtime certificate.\n")
        notice = bundle / "THIRD-PARTY-NOTICES/python-runtime/LICENSE.fixture"
        notice.parent.mkdir(parents=True)
        notice.write_bytes(b"Owned notice fixture\n")
        full = {
            "full_archive": pin_for(target),
            "licensing": {"notices": {"licenses/LICENSE.fixture": digest(notice)}},
        }
        (bundle / "THIRD-PARTY-NOTICES/python-full-distribution.json").write_text(json.dumps(full))
        archive = output / asset_name(version, target)
        members = create_archive(bundle, archive, target, 1)
        manifest = {
            "schema_version": 1,
            "source_commit": commit,
            "source_clean": True,
            "diagnostic_only": False,
            "source_inputs": inputs,
            "version": version,
            "target": target,
            "archive": {"name": archive.name, "sha256": digest(archive), "members": members},
            "native": {"files": {"kuberich": {"sha256": digest(executable)}}},
            "full_python_distribution": full,
        }
        (output / "build-manifest.json").write_text(json.dumps(manifest))
        runtime = directory / "runtime"
        runtime.mkdir()
        terminal = {
            "exit": 0,
            **dict.fromkeys(RESTORATION, True),
            "reporting_modes_disabled": dict.fromkeys(REPORTING_MODES, True),
        }
        receipt = runtime / "terminal.json"
        receipt.write_text(json.dumps(terminal))
        reference = {
            "receipt": receipt.name,
            "sha256": digest(receipt),
            "caller_kubeconfig_unchanged": True,
        }
        host = {
            "schema_version": 1,
            "source_commit": commit,
            "target": target,
            "archive": archive.name,
            "archive_sha256": digest(archive),
            "runtime_qualified": False,
            "publication_performed": False,
            "owned_helper_source_sha256": digest(root / "tests/support/native_helper.c"),
            "native": {
                "native_files": {"kuberich": digest(executable)},
                "highest_glibc_symbols": [2, 35] if linux else [0, 0],
                "highest_macos_minimum": [0, 0, 0] if linux else [14, 0, 0],
                "macos_signatures": {}
                if linux
                else {"kuberich": {"valid": True, "ad_hoc": True, "developer_id": False}},
                "notarization_performed": False,
            },
            "missing_optional_tool": reference,
            "auth_and_shell": reference,
            "system_python_absent": linux,
            "external_python_execution_denied": not linux,
        }
        (runtime / "host-runtime.json").write_text(json.dumps(host))
        controls = {
            "version": {"exit": 0, "stdout": "kuberich " + version + "\n"},
            "help": {"exit": 0, "stdout": "Owned help fixture"},
            "info": {
                "exit": 0,
                "stdout": json.dumps({"version": version, "cluster_connected": False}),
            },
        }
        if linux:
            controls.update(
                {
                    "installed-packages": {"exit": 0, "stdout": "libc6 2.35"},
                    "missing-system-tools": {"exit": 0, "stdout": ""},
                    "actual-glibc": {"exit": 0, "stdout": "ldd 2.35"},
                }
            )
            (directory / "owned-kind-shell.json").write_text(
                json.dumps(
                    {
                        "result": "passed",
                        "application_entry": "native",
                        "native_executable_sha256": digest(executable),
                        **dict.fromkeys(KIND_CONTROLS, True),
                    }
                )
            )
        else:
            controls.update(
                {
                    name: {"exit": 71, "stderr": "sandbox-exec: Operation not permitted"}
                    for name in ("external-python-denied", "system-python-denied")
                }
            )
        for name, value in controls.items():
            (runtime / (name + ".json")).write_text(json.dumps(value))
