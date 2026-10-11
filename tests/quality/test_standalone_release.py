"""Release readers reject incomplete or altered original native qualification records."""

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.build_standalone import source_inputs
from scripts.standalone import TARGETS, asset_name
from scripts.standalone_release import check_records, enroll, verify
from tests.support.native_release import candidates

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.0.1.dev0"


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-release-source")
    for name in source_inputs(ROOT):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Owned Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test: native release parser fixture",
        ],
        check=True,
    )
    sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return root, sha


@pytest.fixture
def original(source, tmp_path):
    root, sha = source
    candidates(root, sha, VERSION, tmp_path)
    return root, sha, tmp_path


def records_for(directory, target):
    source = directory / "standalone" / target
    records = {
        "candidate/build-manifest.json": (source / "candidate/build-manifest.json").read_bytes()
    }
    records.update(
        {"runtime/" + path.name: path.read_bytes() for path in (source / "runtime").glob("*.json")}
    )
    if target.startswith("linux-"):
        records["owned-kind-shell.json"] = (source / "owned-kind-shell.json").read_bytes()
    return source / "candidate" / asset_name(VERSION, target), records


def test_enrollment_preserves_four_exact_archives_and_every_original_json(original, tmp_path):
    root, sha, directory = original
    output = tmp_path / "enrolled"
    enroll(directory, output, root, sha, VERSION)
    verify(output, root, sha, VERSION)
    assert len(list(output.iterdir())) == 8
    for target in TARGETS:
        archive, records = records_for(directory, target)
        assert (output / archive.name).read_bytes() == archive.read_bytes()
        receipt = json.loads(
            (output / (archive.name.removesuffix(".tar.gz") + ".provenance.json")).read_bytes()
        )
        assert {
            name: base64.b64decode(value, validate=True)
            for name, value in receipt["records"].items()
        } == records


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "archive",
        "native",
        "helper",
        "qualified",
        "publication",
        "cli_failure",
        "cli_version",
        "cli_cluster",
        "terminal_digest",
        "terminal_mode",
        "terminal_modes_missing",
        "kubeconfig",
    ],
)
def test_changed_native_execution_and_terminal_records_cannot_qualify(original, target, mutation):
    root, sha, directory = original
    archive, records = records_for(directory, target)
    host = json.loads(records["runtime/host-runtime.json"])
    if mutation == "source":
        host["source_commit"] = "0" * 40
    elif mutation == "archive":
        host["archive_sha256"] = "0" * 64
    elif mutation == "native":
        host["native"]["native_files"]["kuberich"] = "0" * 64
    elif mutation == "helper":
        host["owned_helper_source_sha256"] = "0" * 64
    elif mutation in {"qualified", "publication"}:
        host["runtime_qualified" if mutation == "qualified" else "publication_performed"] = True
    elif mutation == "terminal_digest":
        host["auth_and_shell"]["sha256"] = "0" * 64
    elif mutation in {"terminal_mode", "terminal_modes_missing"}:
        terminal = json.loads(records["runtime/terminal.json"])
        if mutation == "terminal_mode":
            terminal["terminal_mode_restored"] = False
        else:
            terminal["reporting_modes_disabled"] = {}
        records["runtime/terminal.json"] = json.dumps(terminal).encode()
        for reference in ("missing_optional_tool", "auth_and_shell"):
            host[reference]["sha256"] = hashlib.sha256(records["runtime/terminal.json"]).hexdigest()
    elif mutation == "kubeconfig":
        host["auth_and_shell"]["caller_kubeconfig_unchanged"] = 1
    elif mutation in {"cli_failure", "cli_version"}:
        control = json.loads(records["runtime/version.json"])
        control["exit" if mutation == "cli_failure" else "stdout"] = (
            1 if mutation == "cli_failure" else "kuberich wrong-version"
        )
        records["runtime/version.json"] = json.dumps(control).encode()
    else:
        control = json.loads(records["runtime/info.json"])
        control["stdout"] = json.dumps({"version": VERSION, "cluster_connected": True})
        records["runtime/info.json"] = json.dumps(control).encode()
    records["runtime/host-runtime.json"] = json.dumps(host).encode()
    with pytest.raises(ValueError):
        check_records(root, archive, records, sha, VERSION, target)


@pytest.mark.parametrize("target", ["linux-x86_64", "linux-arm64"])
@pytest.mark.parametrize(
    "mutation", ["python", "glibc", "kind_source", "kind_digest", "kind_failure", "control_failure"]
)
def test_linux_requires_python_free_controls_and_this_executables_real_kind_report(
    original, target, mutation
):
    root, sha, directory = original
    archive, records = records_for(directory, target)
    if mutation in {"python", "glibc", "control_failure"}:
        name = "actual-glibc" if mutation == "glibc" else "installed-packages"
        value = json.loads(records[f"runtime/{name}.json"])
        value["stdout"] = "python3 3.12" if mutation == "python" else "ldd 2.38"
        if mutation == "control_failure":
            value["exit"] = 1
        records[f"runtime/{name}.json"] = json.dumps(value).encode()
    else:
        value = json.loads(records["owned-kind-shell.json"])
        field, replacement = {
            "kind_source": ("application_entry", "source"),
            "kind_digest": ("native_executable_sha256", "0" * 64),
            "kind_failure": ("real_rbac_exec_denial", False),
        }[mutation]
        value[field] = replacement
        records["owned-kind-shell.json"] = json.dumps(value).encode()
    with pytest.raises(ValueError):
        check_records(root, archive, records, sha, VERSION, target)


@pytest.mark.parametrize("target", ["macos-x86_64", "macos-arm64"])
@pytest.mark.parametrize(
    "mutation",
    [
        "python_allowed",
        "shell_failed",
        "shell_output",
        "shell_python_allowed",
        "shell_python_wrong_failure",
        "missing_signatures",
        "invalid_signature",
        "notarization",
        "physical_absence",
    ],
)
def test_macos_requires_actual_signature_and_isolation_records_without_overstating_them(
    original, target, mutation
):
    root, sha, directory = original
    archive, records = records_for(directory, target)
    host = json.loads(records["runtime/host-runtime.json"])
    if mutation == "python_allowed":
        control = json.loads(records["runtime/external-python-denied.json"])
        control["exit"] = 0
        records["runtime/external-python-denied.json"] = json.dumps(control).encode()
    elif mutation in {"shell_failed", "shell_output"}:
        control = json.loads(records["runtime/system-shell.json"])
        control["exit" if mutation == "shell_failed" else "stdout"] = (
            1 if mutation == "shell_failed" else ""
        )
        records["runtime/system-shell.json"] = json.dumps(control).encode()
    elif mutation in {"shell_python_allowed", "shell_python_wrong_failure"}:
        control = json.loads(records["runtime/shell-python-denied.json"])
        control["exit" if mutation == "shell_python_allowed" else "stderr"] = (
            0 if mutation == "shell_python_allowed" else "unrelated failure"
        )
        records["runtime/shell-python-denied.json"] = json.dumps(control).encode()
    elif mutation == "missing_signatures":
        host["native"]["macos_signatures"] = {}
    elif mutation == "invalid_signature":
        host["native"]["macos_signatures"]["kuberich"]["valid"] = False
    elif mutation == "notarization":
        host["native"]["notarization_performed"] = True
    else:
        host["system_python_absent"] = True
    records["runtime/host-runtime.json"] = json.dumps(host).encode()
    with pytest.raises(ValueError):
        check_records(root, archive, records, sha, VERSION, target)
