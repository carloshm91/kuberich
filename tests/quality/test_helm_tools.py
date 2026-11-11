"""Pinned Helm acquisition and mandatory gate enrollment without network or execution."""

import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import yaml

from scripts import helm_tools as tools
from scripts.qualification import cluster_stages, phase, type_command
from scripts.qualification_runner import archive

ROOT = Path(__file__).resolve().parents[2]
BINARY = b"original synthetic Helm bytes; this file is never executed"


def tar_bytes(binary: bytes, fault: str = "") -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as contents:
        names = ["linux-amd64/helm"] * (2 if fault == "duplicate" else 1)
        if fault == "missing":
            names = ["other/helm"]
        if fault == "traversal":
            names.append("../../outside")
        for name in names:
            member = tarfile.TarInfo(name)
            member.size = len(binary)
            if fault == "symlink":
                member.type, member.linkname, member.size = tarfile.SYMTYPE, "../../outside", 0
                contents.addfile(member)
            else:
                contents.addfile(member, io.BytesIO(binary))
    return stream.getvalue()


def asset_pin(version: str, *, fault: str = "") -> tuple[tools.HelmPin, dict[str, bytes]]:
    payload = tar_bytes(BINARY, fault)
    archive_name = f"helm-{version}-linux-amd64.tar.gz"
    archive_hash = hashlib.sha256(payload).hexdigest()
    checksum = f"{archive_hash}  {archive_name}\n".encode()
    pin = tools.HelmPin(
        version,
        "a" * 40,
        hashlib.sha256(checksum).hexdigest(),
        archive_hash,
        hashlib.sha256(BINARY).hexdigest(),
        len(BINARY),
    )
    return pin, {archive_name: payload, archive_name + ".sha256sum": checksum}


@dataclass
class SyntheticTools:
    pins: tuple[tools.HelmPin, ...]
    assets: dict[str, bytes]
    urls: list[tuple[str, int]]


@pytest.fixture
def synthetic(monkeypatch: pytest.MonkeyPatch) -> SyntheticTools:
    pairs = [asset_pin(version) for version in ("v3.22.1", "v4.3.1")]
    fixture = SyntheticTools(tuple(pin for pin, _ in pairs), {}, [])
    for _, assets in pairs:
        fixture.assets.update(assets)
    monkeypatch.setattr(tools, "HELM_PINS", fixture.pins)

    def response(url: str, timeout: int) -> io.BytesIO:
        fixture.urls.append((url, timeout))
        return io.BytesIO(fixture.assets[url.removeprefix(tools.BASE_URL)])

    monkeypatch.setattr(tools, "urlopen", response)
    return fixture


def test_official_pins_bind_exact_versions_sources_archives_and_binary_bytes() -> None:
    expected = {
        "v3.22.1": (
            "d6c1a0e4027caa6abc7892e7ea9f0cda7447baa3",
            "46aeab5e043f62d01f7c168823b392cabc1cea3807b67906296290483791be43",
            61_702_306,
        ),
        "v4.3.1": (
            "c0d08d0d6d9424d4a14febb5e8a3e51b0dd00dff",
            "b66cb19f2b31f9d427632ea6c4b4a1ff89b74ecaeaee323cd166da41a7af53bd",
            66_314_400,
        ),
    }
    assert tools.BASE_URL == "https://get.helm.sh/"
    assert {pin.version for pin in tools.HELM_PINS} == set(expected)
    for pin in tools.HELM_PINS:
        assert (pin.source_commit, pin.binary_sha256, pin.binary_bytes) == expected[pin.version]
        assert pin.archive == f"helm-{pin.version}-linux-amd64.tar.gz"
        for digest in (pin.checksum_sha256, pin.archive_sha256, pin.binary_sha256):
            assert len(digest) == 64 and bytes.fromhex(digest)


def test_acquisition_validates_actual_extraction_and_rechecks_cache_without_execution(
    tmp_path: Path,
    synthetic: SyntheticTools,
) -> None:
    directory = tmp_path / "tools"
    paths = tools.prepare_helm_tools(directory)
    assert paths == (directory / "3.22.1/helm", directory / "4.3.1/helm")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for pin, path in zip(synthetic.pins, paths, strict=True):
        assert path.read_bytes() == BINARY and stat.S_IMODE(path.stat().st_mode) == 0o500
        assert tools.verify_helm_binary(path, pin) == pin.binary_sha256
        receipt = json.loads((path.parent / "prepared-provenance.json").read_text())
        assert receipt["version"] == pin.version and receipt["binary_sha256"] == pin.binary_sha256
        assert receipt["host_executed"] is False and "no signature claim" in receipt["verification"]
    assert synthetic.urls == [
        (tools.BASE_URL + name, 30)
        for pin in synthetic.pins
        for name in (pin.archive + ".sha256sum", pin.archive)
    ]
    before = list(synthetic.urls)
    assert tools.prepare_helm_tools(directory) == paths and synthetic.urls == before


@pytest.mark.parametrize("field", ["checksum", "archive", "binary", "receipt"])
def test_corrupt_cached_inputs_are_preserved_and_never_redownloaded(
    tmp_path: Path,
    synthetic: SyntheticTools,
    field: str,
) -> None:
    directory = tmp_path / "tools"
    paths = tools.prepare_helm_tools(directory)
    pin, path = synthetic.pins[0], paths[0]
    target = {
        "checksum": path.parent / (pin.archive + ".sha256sum"),
        "archive": path.parent / pin.archive,
        "binary": path,
        "receipt": path.parent / "prepared-provenance.json",
    }[field]
    target.chmod(0o600)
    target.write_bytes(b"original corrupt input")
    before = list(synthetic.urls)
    with pytest.raises(ValueError):
        tools.prepare_helm_tools(directory)
    assert target.read_bytes() == b"original corrupt input" and synthetic.urls == before


@pytest.mark.parametrize("field", ["checksum", "archive", "binary", "receipt"])
@pytest.mark.parametrize("broken", [False, True])
def test_cached_links_never_read_or_write_an_external_destination(
    tmp_path: Path,
    synthetic: SyntheticTools,
    field: str,
    broken: bool,
) -> None:
    directory = tmp_path / "tools"
    path = tools.prepare_helm_tools(directory)[0]
    pin = synthetic.pins[0]
    target = {
        "checksum": path.parent / (pin.archive + ".sha256sum"),
        "archive": path.parent / pin.archive,
        "binary": path,
        "receipt": path.parent / "prepared-provenance.json",
    }[field]
    original = target.read_bytes()
    target.unlink()
    external = tmp_path / "external"
    if not broken:
        external.write_bytes(original)
    target.symlink_to(external)
    before = list(synthetic.urls)
    with pytest.raises((ValueError, FileExistsError, FileNotFoundError)):
        tools.prepare_helm_tools(directory)
    assert target.is_symlink() and synthetic.urls == before
    assert not external.exists() if broken else external.read_bytes() == original


def test_explicit_directory_and_version_subdirectories_refuse_symbolic_links(
    tmp_path: Path,
    synthetic: SyntheticTools,
) -> None:
    with pytest.raises(ValueError, match="absolute"):
        tools.prepare_helm_tools(Path("relative"))
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="absolute"):
        tools.prepare_helm_tools(link)
    directory = tmp_path / "tools"
    directory.mkdir()
    (directory / "3.22.1").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        tools.prepare_helm_tools(directory)
    assert not synthetic.urls


@pytest.mark.parametrize("fault", ["missing", "duplicate", "symlink", "size", "binary-hash"])
def test_archive_member_is_unique_regular_bounded_and_matches_the_pinned_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic: SyntheticTools,
    fault: str,
) -> None:
    pin, assets = asset_pin("v3.22.1", fault=fault)
    if fault == "size":
        pin = replace(pin, binary_bytes=pin.binary_bytes + 1)
    if fault == "binary-hash":
        pin = replace(pin, binary_sha256="0" * 64)
    monkeypatch.setattr(tools, "HELM_PINS", (pin,))
    synthetic.assets.update(assets)
    directory = tmp_path / "tools"
    with pytest.raises(ValueError, match=r"member|binary"):
        tools.prepare_helm_tools(directory)
    assert (directory / "3.22.1" / pin.archive).exists()
    assert not (directory / "3.22.1/helm").exists()
    assert not (tmp_path / "outside").exists()


def test_nonselected_archive_paths_are_never_extracted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic: SyntheticTools,
) -> None:
    pin, assets = asset_pin("v3.22.1", fault="traversal")
    monkeypatch.setattr(tools, "HELM_PINS", (pin,))
    synthetic.assets.update(assets)
    path = tools.prepare_helm_tools(tmp_path / "tools")[0]
    assert path.read_bytes() == BINARY and not (tmp_path / "outside").exists()


def test_pinned_checksum_content_must_name_the_exact_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic: SyntheticTools,
) -> None:
    pin = synthetic.pins[0]
    malformed = f"{pin.archive_sha256} another-archive.tar.gz\n".encode()
    synthetic.assets[pin.archive + ".sha256sum"] = malformed
    monkeypatch.setattr(
        tools, "HELM_PINS", (replace(pin, checksum_sha256=hashlib.sha256(malformed).hexdigest()),)
    )
    with pytest.raises(ValueError, match="archive"):
        tools.prepare_helm_tools(tmp_path / "tools")


@pytest.mark.parametrize("change", ["size", "mode", "bytes", "pin", "relative", "directory"])
def test_binary_verification_rejects_drift_and_unreviewed_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic: SyntheticTools,
    change: str,
) -> None:
    pin = synthetic.pins[0]
    path = tools.prepare_helm_tools(tmp_path / "tools")[0]
    if change == "size":
        pin = replace(pin, binary_bytes=pin.binary_bytes + 1)
        monkeypatch.setattr(tools, "HELM_PINS", (pin,))
    elif change == "mode":
        path.chmod(0o600)
    elif change == "bytes":
        path.chmod(0o700)
        path.write_bytes(b"tampered")
    elif change == "pin":
        pin = replace(pin, version="v5.0.0")
    elif change == "relative":
        path = Path("relative")
    else:
        path = tmp_path
    with pytest.raises(ValueError):
        tools.verify_helm_binary(path, pin)


def test_partial_download_is_retained_and_cannot_be_repaired_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic: SyntheticTools,
) -> None:
    class Interrupted(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if self.tell():
                raise OSError("Synthetic interruption")
            return super().read(size)

    pin = synthetic.pins[0]
    requested: list[str] = []

    def response(url: str, timeout: int) -> io.BytesIO:
        requested.append(url)
        if url.endswith(".sha256sum"):
            return io.BytesIO(synthetic.assets[pin.archive + ".sha256sum"])
        return Interrupted(b"partial archive")

    monkeypatch.setattr(tools, "urlopen", response)
    directory = tmp_path / "tools"
    with pytest.raises(OSError, match="interruption"):
        tools.prepare_helm_tools(directory)
    original = directory / "3.22.1" / pin.archive
    assert original.read_bytes() == b"partial archive"
    with pytest.raises(ValueError, match="archive"):
        tools.prepare_helm_tools(directory)
    assert len(requested) == 2 and original.read_bytes() == b"partial archive"


def test_downloader_requires_fixed_assets_and_exclusive_destination(
    tmp_path: Path,
    synthetic: SyntheticTools,
) -> None:
    pin = synthetic.pins[0]
    target = tmp_path / "download"
    tools.download_asset(pin, pin.archive + ".sha256sum", target)
    original = target.read_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        tools.download_asset(pin, pin.archive + ".sha256sum", target)
    for candidate, name in (
        (pin, "../../unreviewed"),
        (replace(pin, version="v5.0.0"), pin.archive),
    ):
        with pytest.raises(ValueError, match="reviewed"):
            tools.download_asset(candidate, name, tmp_path / "never")
    assert not (tmp_path / "never").exists() and target.read_bytes() == original


@pytest.mark.parametrize("archive_payload", [False, True])
def test_failed_download_limits_preserve_the_written_bounded_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic: SyntheticTools,
    archive_payload: bool,
) -> None:
    class Overflow(io.BytesIO):
        def __init__(self) -> None:
            super().__init__()
            self.count = 0

        def read(self, size: int | None = -1) -> bytes:
            self.count += 1
            return b"x" * (1024 * 1024) if self.count <= 41 else b""

    pin = synthetic.pins[0]
    name = pin.archive if archive_payload else pin.archive + ".sha256sum"
    monkeypatch.setattr(
        tools,
        "urlopen",
        lambda url, timeout: Overflow() if archive_payload else io.BytesIO(b"x" * 1025),
    )
    target = tmp_path / "overflow"
    with pytest.raises(ValueError, match="bound"):
        tools.download_asset(pin, name, target)
    assert target.stat().st_size == (40 * 1024 * 1024 if archive_payload else 0)


def test_helper_cli_reports_verified_paths_without_claiming_execution(
    tmp_path: Path,
    synthetic: SyntheticTools,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["helm_tools", "--directory", str(tmp_path / "tools")])
    tools.main()
    assert json.loads(capsys.readouterr().out) == {
        "binaries": [
            str(tmp_path / "tools" / pin.version.removeprefix("v") / "helm")
            for pin in synthetic.pins
        ]
    }


def test_workflow_and_current_qualifier_require_helm_without_changing_phase_policy(
    tmp_path: Path,
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    application = workflow["jobs"]["application"]
    step = next(
        step
        for step in application["steps"]
        if "python -m scripts.verify_helm_kind" in step.get("run", "")
    )
    assert step["if"] == "${{ matrix.os == 'ubuntu-24.04' && matrix.python == '3.12' }}"
    assert "continue-on-error" not in step and "continue-on-error" not in application
    assert 'scripts.helm_tools --directory "$RUNNER_TEMP/kuberich-helm-tools"' in step["run"]
    assert '--helm3 "$RUNNER_TEMP/kuberich-helm-tools/3.22.1/helm"' in step["run"]
    assert '--helm4 "$RUNNER_TEMP/kuberich-helm-tools/4.3.1/helm"' in step["run"]
    assert "--docker /usr/bin/docker --evidence artifacts/helm/evidence.json" in step["run"]
    assert (
        "trap retain_helm_receipts EXIT" in step["run"]
        and "prepared-provenance.json" in step["run"]
    )
    assert {
        "scripts/helm_tools.py",
        "scripts/verify_helm_kind.py",
        "scripts/helm_lifecycle_cases.py",
        "scripts/helm_lifecycle_catalog_cases.py",
        "scripts/helm_lifecycle_fault_cases.py",
        "scripts/helm_registry.py",
        "scripts/verify_helm_registry.py",
    } <= set(type_command(ROOT))
    assert phase("0.4.0") == ("0.4.0", 75) and phase("0.5.0") == ("0.5.0", 82)
    first = cluster_stages(
        tmp_path, Path("/owned/kind"), Path("/owned/kubectl"), Path("/owned/app.whl"), 1
    )
    second = cluster_stages(
        tmp_path, Path("/owned/kind"), Path("/owned/kubectl"), Path("/owned/app.whl"), 2
    )
    preparation = next(stage for stage in first if stage.name == "kind-1-helm-tools")
    verification = next(stage for stage in first if stage.name == "kind-1-helm")
    assert first.index(preparation) < first.index(verification)
    assert preparation.command[4:] == (
        "scripts.helm_tools",
        "--directory",
        str(tmp_path / "helm-tools"),
    )
    for flag, value in (
        ("--helm3", tmp_path / "helm-tools/3.22.1/helm"),
        ("--helm4", tmp_path / "helm-tools/4.3.1/helm"),
        ("--kind", Path("/owned/kind")),
        ("--docker", Path("/usr/bin/docker")),
        ("--evidence", tmp_path / "kind-1-helm/evidence.json"),
    ):
        assert verification.command[verification.command.index(flag) + 1] == str(value)
    repeated = next(stage for stage in second if stage.name == "kind-2-helm")
    assert repeated.command[-1] == str(tmp_path / "kind-2-helm/evidence.json")


def test_lifecycle_proof_hashes_every_owned_helper_and_fixture_input():
    from scripts.verify_helm_kind import input_hashes

    inventory = input_hashes(ROOT)
    assert {
        "scripts/helm_lifecycle_cases.py",
        "scripts/helm_lifecycle_catalog_cases.py",
        "scripts/helm_lifecycle_fault_cases.py",
        "scripts/helm_registry.py",
        "scripts/verify_helm_registry.py",
        "tests/support/helm_catalog.py",
        "tests/support/helm_oci.py",
        "scripts/owned_kind.py",
        "scripts/diagnostics_tools.py",
    } <= inventory.keys()
    assert {
        str(path.relative_to(ROOT)) for path in (ROOT / "src/kuberich").rglob("*.py")
    } <= inventory.keys()


def test_canonical_helm_evidence_and_sibling_receipts_survive_archiving(tmp_path: Path) -> None:
    source = tmp_path / "source"
    evidence = source / "artifacts/helm"
    receipt = evidence / "tool-provenance/3.22.1-prepared-provenance.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"version":"v3.22.1"}\n')
    (evidence / "evidence.json").write_text('{"status":"failed"}\n')
    destination = tmp_path / "retained"
    archive(source, destination)
    receipt.write_text('{"version":"changed"}\n')
    assert (
        destination / "helm/tool-provenance/3.22.1-prepared-provenance.json"
    ).read_text() == '{"version":"v3.22.1"}\n'
    assert (destination / "helm/evidence.json").read_text() == '{"status":"failed"}\n'


@pytest.mark.parametrize("fault", ["acquisition", "verification", ""])
def test_actual_workflow_shell_retains_available_receipts_without_masking_failure(
    tmp_path: Path,
    fault: str,
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["application"]["steps"]
        if "python -m scripts.verify_helm_kind" in step.get("run", "")
    )
    # Replace only the external uv commands. Execute the actual workflow shell and EXIT trap.
    prefix = """
uv() {
  if [ "$4" = "scripts.helm_tools" ]; then
    mkdir -p "$RUNNER_TEMP/kuberich-helm-tools/3.22.1" "$RUNNER_TEMP/kuberich-helm-tools/4.3.1"
    printf '{"version":"v3.22.1"}\n' > "$RUNNER_TEMP/kuberich-helm-tools/3.22.1/prepared-provenance.json"
    printf 'tool binary' > "$RUNNER_TEMP/kuberich-helm-tools/3.22.1/helm"
    printf 'tool archive' > "$RUNNER_TEMP/kuberich-helm-tools/3.22.1/archive.tar.gz"
    if [ "$HELM_FAULT" = "acquisition" ]; then return 23; fi
    printf '{"version":"v4.3.1"}\n' > "$RUNNER_TEMP/kuberich-helm-tools/4.3.1/prepared-provenance.json"
  elif [ "$4" = "scripts.verify_helm_kind" ]; then
    mkdir -p artifacts/helm
    printf '{"status":"observed"}\n' > artifacts/helm/evidence.json
    if [ "$HELM_FAULT" = "verification" ]; then return 23; fi
  else
    return 99
  fi
}
"""
    result = subprocess.run(
        ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", prefix + step["run"]),
        cwd=tmp_path,
        env={"PATH": os.defpath, "RUNNER_TEMP": str(tmp_path / "runner"), "HELM_FAULT": fault},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == (23 if fault else 0), result.stderr
    retained = tmp_path / "artifacts/helm"
    receipts = retained / "tool-provenance"
    assert json.loads((receipts / "3.22.1-prepared-provenance.json").read_text()) == {
        "version": "v3.22.1"
    }
    assert (receipts / "4.3.1-prepared-provenance.json").exists() == (fault != "acquisition")
    assert (retained / "evidence.json").exists() == (fault != "acquisition")
    assert not list(retained.rglob("*.tar.gz")) and not list(retained.rglob("helm"))
