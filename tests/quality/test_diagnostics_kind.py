"""Owned diagnostics acquisition/containment decisions; real trials remain separate."""

import hashlib
import io
import json
import stat
import tarfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from kuberich.domain.cluster_diagnostics import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticIdentity,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSeverity,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
)
from kuberich.domain.targets import SessionIdentity
from scripts import diagnostics_kind_runtime as runtime
from scripts import diagnostics_tools as tools
from scripts import verify_diagnostics_kind as verifier
from scripts.owned_kind import OwnedCluster


def synthetic_assets(monkeypatch):
    binary = b"owned synthetic executable bytes; never executed"
    archive_stream = io.BytesIO()
    with tarfile.open(fileobj=archive_stream, mode="w:gz") as archive:
        member = tarfile.TarInfo("popeye")
        member.size = len(binary)
        archive.addfile(member, io.BytesIO(binary))
    archive = archive_stream.getvalue()
    archive_hash = hashlib.sha256(archive).hexdigest()
    checksum = f"{archive_hash}  {tools.POPEYE_ARCHIVE}\n".encode()
    monkeypatch.setattr(tools, "POPEYE_BINARY_BYTES", len(binary))
    monkeypatch.setattr(tools, "POPEYE_BINARY_SHA256", hashlib.sha256(binary).hexdigest())
    monkeypatch.setattr(tools, "POPEYE_ARCHIVE_SHA256", archive_hash)
    monkeypatch.setattr(tools, "POPEYE_CHECKSUM_SHA256", hashlib.sha256(checksum).hexdigest())
    return {"checksums.sha256": checksum, tools.POPEYE_ARCHIVE: archive}


def test_official_pin_metadata_and_the_only_supported_source_are_traceable():
    path = Path(__file__).parents[1] / "fixtures/popeye/0.22.1/official-provenance.json"
    assert json.loads(path.read_text()) == tools.tool_provenance()
    assert tools.POPEYE_COMMIT == "35b554961dcdabfa7aba6bd070673c6c24c70884"
    assert (
        tools.POPEYE_BINARY_SHA256
        == "a9af3fd43bffbf3b4099e68a18e9b1c6a8c1ec735d33390d5fe61ddbb0ffab11"
    )
    assert tools.tool_provenance()["host_executed"] is False


def test_measured_source_inventory_includes_every_production_module_and_tool_pin():
    root = Path(__file__).resolve().parents[2]
    inventory = verifier.input_hashes(root)
    assert (
        set(str(path.relative_to(root)) for path in (root / "src/kuberich").rglob("*.py"))
        <= inventory.keys()
    )
    assert {
        "src/kuberich/services/workspace.py",
        "pyproject.toml",
        "uv.lock",
        "scripts/owned_kind.py",
        "scripts/diagnostics_tools.py",
        "scripts/diagnostics_kind_runtime.py",
        "scripts/verify_diagnostics_kind.py",
        "tests/fixtures/popeye/0.22.1/official-provenance.json",
    } <= inventory.keys()


def test_acquisition_returns_exact_executable_path_and_revalidates_cache_without_execution(
    tmp_path, monkeypatch
):
    assets = synthetic_assets(monkeypatch)
    downloads = []

    def download(name, destination, limit):
        downloads.append((name, limit))
        destination.write_bytes(assets[name])

    monkeypatch.setattr(tools, "download_asset", download)
    directory = tmp_path / "tools"
    path = tools.prepare_diagnostics_tool(directory)
    assert path == directory / "popeye" and path.is_absolute()
    assert stat.S_IMODE(path.stat().st_mode) == 0o500
    assert downloads == [("checksums.sha256", 16384), (tools.POPEYE_ARCHIVE, 32 * 1024 * 1024)]
    assert tools.prepare_diagnostics_tool(directory) == path and len(downloads) == 2
    path.chmod(0o700)
    path.write_bytes(b"tampered owned synthetic bytes")
    with pytest.raises(ValueError, match="checksum-verified"):
        tools.prepare_diagnostics_tool(directory)
    assert path.read_bytes() == b"tampered owned synthetic bytes" and len(downloads) == 2


def test_invalid_or_partial_acquisition_never_overwrites_existing_inputs(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="absolute"):
        tools.prepare_diagnostics_tool(Path("relative"))
    link = tmp_path / "linked"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="absolute"):
        tools.prepare_diagnostics_tool(link)
    directory = tmp_path / "partial"
    directory.mkdir()
    (directory / "checksums.sha256").write_text("original invalid receipt")
    with pytest.raises(ValueError, match="checksum file"):
        tools.prepare_diagnostics_tool(directory)
    assert (directory / "checksums.sha256").read_text() == "original invalid receipt"
    with pytest.raises(ValueError, match="regular"):
        tools.sha256_file(link)


def test_downloader_has_fixed_urls_and_retains_a_bounded_failed_download(tmp_path, monkeypatch):
    urls = []

    def response(url, timeout):
        urls.append((url, timeout))
        return io.BytesIO(b"owned response")

    monkeypatch.setattr(tools, "urlopen", response)
    target = tmp_path / "checksum"
    tools.download_asset("checksums.sha256", target, 100)
    assert target.read_bytes() == b"owned response"
    assert urls == [(tools.POPEYE_RELEASE_URL + "checksums.sha256", 30)]
    with pytest.raises(ValueError, match="fixed"):
        tools.download_asset("not-a-release-asset", tmp_path / "never", 100)
    assert not (tmp_path / "never").exists()
    with pytest.raises(ValueError, match="bound"):
        tools.download_asset(tools.POPEYE_ARCHIVE, tmp_path / "overflow", 1)
    assert (tmp_path / "overflow").exists()
    with pytest.raises(FileExistsError):
        tools.download_asset("checksums.sha256", target, 100)


def test_helper_cli_reports_the_verified_absolute_binary_path(tmp_path, monkeypatch, capsys):
    path = tmp_path / "popeye"
    captured = []

    def prepare(directory):
        captured.append(directory)
        return path

    monkeypatch.setattr(tools, "prepare_diagnostics_tool", prepare)
    monkeypatch.setattr("sys.argv", ["diagnostics_tools", "--directory", str(tmp_path)])
    tools.main()
    assert captured == [tmp_path]
    assert json.loads(capsys.readouterr().out) == {
        "popeye": str(path),
        "binary_sha256": tools.POPEYE_BINARY_SHA256,
    }


def test_required_binary_and_kind_identity_fail_before_any_owned_cluster_creation(
    tmp_path, monkeypatch
):
    kind = tmp_path / "kind"
    kind.write_bytes(b"owned kind bytes")
    monkeypatch.setattr(verifier, "KIND_SHA256", hashlib.sha256(kind.read_bytes()).hexdigest())
    monkeypatch.setattr(verifier, "sys", SimpleNamespace(version_info=(3, 12), platform="linux"))
    monkeypatch.setattr(verifier.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="required qualification prerequisite"):
        verifier.prerequisites(kind, None)
    kind.write_bytes(b"tampered kind bytes")
    with pytest.raises(ValueError, match=r"kind0\.33\.0"):
        verifier.prerequisites(kind, tmp_path / "popeye")


def test_container_vector_only_mounts_owned_inputs_with_its_own_account_home(tmp_path):
    cluster = OwnedCluster(
        "owned-name",
        tmp_path / "private-kubeconfig",
        tmp_path,
        "kind-kuberich-test-owned",
        ("node-id",),
    )
    argv = verifier.container_argv(
        "docker",
        cluster,
        tmp_path / "source",
        tmp_path / "sites",
        tmp_path / "popeye",
        tmp_path / "evidence",
        tmp_path / "passwd",
        "nonce",
        1001,
        1002,
    )
    assert "--read-only" in argv and "--network=host" in argv and "--cap-drop=ALL" in argv
    assert "1001:1002" in argv and "--env=HOME=/owned/home" in argv
    assert "--env=KUBECONFIG=/fixture/kubeconfig" in argv
    assert verifier.RUNTIME_IMAGE in argv
    mounts = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--mount"]
    assert len(mounts) == 7 and sum(item.endswith(",readonly") for item in mounts) == 6
    assert any("target=/etc/passwd,readonly" in item for item in mounts)
    assert not any(
        "/home/develop" in item or "/.kube" in item or "docker.sock" in item for item in mounts
    )
    assert argv[-8:] == [
        "--kubeconfig",
        "/fixture/kubeconfig",
        "--context",
        cluster.context,
        "--evidence",
        "/evidence",
        "--popeye",
        "/owned/popeye",
    ]


@pytest.mark.parametrize("body_failure", [False, True])
def test_labelled_runtime_cleanup_is_bound_and_precedes_borrowed_material_teardown(
    tmp_path, monkeypatch, body_failure
):
    calls, current = [], []
    identifier = "a" * 64

    def run(argv, environment, timeout=30):
        calls.append((argv, timeout))
        if argv[1] == "create":
            current.append(identifier)
            return identifier
        if argv[1] == "inspect":
            return json.dumps(
                [
                    {
                        "Id": identifier,
                        "Config": {
                            "Labels": {verifier.OWNER_LABEL: "nonce"},
                            "Image": verifier.RUNTIME_IMAGE,
                        },
                        "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "host"},
                    }
                ]
            )
        if argv[1] == "rm":
            current.clear()
            return identifier
        return "\n".join(current)

    monkeypatch.setattr(verifier, "run_owned", run)
    receipt = {}

    def execute():
        with verifier.contained_runtime(
            ["docker", "create"], "docker", {}, "nonce", receipt
        ) as actual:
            assert actual == identifier and current == [identifier]
            if body_failure:
                raise RuntimeError("owned injected body failure")

    if body_failure:
        with pytest.raises(RuntimeError, match="injected"):
            execute()
    else:
        execute()
    assert receipt["container_deleted"] and not current
    assert [timeout for _, timeout in calls[-3:]] == [5, 5, 5]
    assert calls[-2][0] == ["docker", "rm", "--force", identifier]


def test_replaced_container_is_never_deleted_even_if_its_label_still_matches(monkeypatch):
    identifier, replacement = "a" * 64, "b" * 64
    current, removed = [], []

    def run(argv, environment, timeout=30):
        if argv[1] == "create":
            current.append(identifier)
            return identifier
        if argv[1] == "inspect":
            return json.dumps(
                [
                    {
                        "Id": identifier,
                        "Config": {
                            "Labels": {verifier.OWNER_LABEL: "nonce"},
                            "Image": verifier.RUNTIME_IMAGE,
                        },
                        "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "host"},
                    }
                ]
            )
        if argv[1] == "rm":
            removed.append(argv)
        return "\n".join(current)

    monkeypatch.setattr(verifier, "run_owned", run)
    with (
        pytest.raises(ValueError, match="membership changed"),
        verifier.contained_runtime(["docker", "create"], "docker", {}, "nonce"),
    ):
        current[:] = [replacement]
    assert not removed


def test_native_fixtures_are_synthetic_and_cover_real_controller_triggers():
    values = runtime.fixtures()
    assert {item["metadata"]["name"] for item in values if item["kind"] == "Namespace"} == {
        runtime.NAMESPACE,
        runtime.OTHER_NAMESPACE,
    }
    pods = {
        item["metadata"]["name"]: item
        for item in values
        if item["kind"] == "Pod" and item["metadata"]["namespace"] == runtime.NAMESPACE
    }
    assert pods[runtime.IMAGE_POD]["spec"]["containers"][0]["image"].startswith("registry.invalid/")
    assert pods[runtime.CRASH_POD]["spec"]["containers"][0]["command"][-1].endswith("exit 23")
    assert "readinessProbe" in pods[runtime.READY_POD]["spec"]["containers"][0]
    assert "configMap" in pods[runtime.VOLUME_POD]["spec"]["volumes"][0]
    assert all(item["spec"]["automountServiceAccountToken"] is False for item in pods.values())
    assert not any(item["kind"] == "Secret" for item in values)
    assert {"Deployment", "Job", "CronJob", "PersistentVolumeClaim", "Role", "RoleBinding"} <= {
        item["kind"] for item in values
    }


def test_runtime_failure_preserves_original_and_verified_cleanup_without_extra_processes(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "evidence.json"
    kind, binary = tmp_path / "kind", tmp_path / "popeye"
    private = tmp_path / "cluster"
    private.mkdir()
    configuration = private / "config"
    configuration.write_text("owned synthetic caller sentinel")
    cluster = OwnedCluster(
        "owned-name", configuration, private, "kind-kuberich-test-owned", ("owned-node-id",)
    )
    commands = []
    completed = []

    @contextmanager
    def owned(*args, **kwargs):
        try:
            yield cluster
        finally:
            configuration.unlink()
            private.rmdir()
            completed.append("cluster")

    @contextmanager
    def container(argv, docker, environment, nonce, receipt):
        try:
            yield "owned-container"
        finally:
            receipt["container_deleted"] = True
            completed.append("container")

    async def failing_attach(*args):
        (tmp_path / "diagnostics-runtime.json").write_text(
            json.dumps({"status": "failed", "failure_type": "OwnedRuntimeFailure"})
        )
        raise RuntimeError("retained original owned body failure")

    def run(argv, environment, timeout=30):
        commands.append(argv)
        return "owned-preexisting-id\n" if argv[1] == "ps" else ""

    monkeypatch.setattr(verifier, "prerequisites", lambda *args: None)
    monkeypatch.setattr(
        verifier, "input_hashes", lambda *args: {"owned": "stable synthetic source"}
    )
    monkeypatch.setattr(
        verifier, "capture_docker", lambda *args: {"DOCKER_HOST": "unix:///owned/socket"}
    )
    monkeypatch.setattr(verifier, "run_owned", run)
    monkeypatch.setattr(verifier, "owned_cluster", owned)
    monkeypatch.setattr(verifier, "contained_runtime", container)
    monkeypatch.setattr(verifier, "attach", failing_attach)
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_diagnostics_kind",
            "--kind",
            str(kind),
            "--popeye",
            str(binary),
            "--evidence",
            str(evidence),
        ],
    )
    with pytest.raises(RuntimeError, match="retained original"):
        verifier.main()
    receipt = json.loads(evidence.read_text())
    assert receipt["status"] == "failed" and receipt["failure_type"] == "RuntimeError"
    assert receipt["runtime"]["failure_type"] == "OwnedRuntimeFailure"
    assert (
        receipt["container_deleted"]
        and receipt["cluster_deleted"]
        and receipt["private_directory_deleted"]
    )
    assert (
        receipt["caller_kubeconfig_unchanged"]
        and receipt["inputs_unchanged"]
        and receipt["environment_unchanged"]
    )
    assert completed == ["container", "cluster"]
    assert (
        sum(argv[1] == "ps" for argv in commands) == 1
    )  # No new process after signal/body cleanup.


def native_snapshot(categories, *, revision=1, collecting=False):
    now = datetime(2026, 11, 5, tzinfo=UTC)
    request = DiagnosticRequest(
        DiagnosticScope(SessionIdentity("owned-fixture", 1), "team"), revision
    )
    findings = tuple(
        DiagnosticFinding(
            str(category),
            DiagnosticSeverity.ERROR,
            category,
            None,
            None,
            "Synthetic observed category",
            "Synthetic fixture only",
            (),
            frozenset(),
            DiagnosticSourceKind.CONDITION,
            None,
            None,
            DiagnosticIdentity.UNRESOLVED,
        )
        for category in categories
    )
    source = DiagnosticSource(
        "owned-source",
        DiagnosticSourceKind.CONDITION,
        None,
        "team",
        DiagnosticStatus.READY,
        None,
        None,
        now,
        "Synthetic completed source",
    )
    return DiagnosticSnapshot(request, findings, (source,), collecting, 2, now)


@pytest.mark.asyncio
async def test_readiness_uses_one_completed_native_snapshot_and_retains_the_failed_observation():
    missing = native_snapshot(runtime.CANONICAL - {DiagnosticCategory.CRASH_LOOP})
    only_crash = native_snapshot({DiagnosticCategory.CRASH_LOOP}, revision=2)
    complete = native_snapshot(runtime.CANONICAL, revision=3)
    retained = []

    # Negative control for the original post-readiness single-collection assert:
    # raw Pod readiness cannot establish what a later native observation contains.
    async def legacy_single_collection():
        value = missing
        assert {item.category for item in value.findings} >= runtime.CANONICAL
        retained.append(value)
        return value

    with pytest.raises(AssertionError):
        await legacy_single_collection()
    assert not retained  # This was the original loss of normalized failure evidence.

    values = iter((missing, only_crash, complete))

    async def collect():
        return next(values)

    observed = await runtime.wait_for_canonical_snapshot(collect, retained.append, seconds=2)
    assert observed is complete
    assert retained == [
        missing,
        only_crash,
        complete,
    ]  # No union of the first two snapshots can pass.
    assert retained[0].sources[0].status is DiagnosticStatus.READY


@pytest.mark.asyncio
async def test_readiness_keeps_exact_requirement_deadline_and_incomplete_source_evidence():
    incomplete = native_snapshot(runtime.CANONICAL - {DiagnosticCategory.CRASH_LOOP})
    retained = []

    async def collect():
        return incomplete

    with pytest.raises(TimeoutError):
        await runtime.wait_for_canonical_snapshot(collect, retained.append, seconds=0.01)
    assert retained == [incomplete]


@pytest.mark.asyncio
async def test_readiness_does_not_accept_an_in_progress_snapshot_even_with_all_categories():
    pending = native_snapshot(runtime.CANONICAL, collecting=True)
    complete = native_snapshot(runtime.CANONICAL, revision=2)
    values, retained = iter((pending, complete)), []

    async def collect():
        return next(values)

    observed = await runtime.wait_for_canonical_snapshot(collect, retained.append, seconds=2)
    assert observed is complete and retained == [pending, complete]
