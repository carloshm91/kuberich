"""Development cost reductions must preserve required checks and release gates."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci_policy import MACOS_RUNNER, TEST_PARTS, main, matrix, native_matrix, part_matrix

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "event,ref,mac_versions",
    [
        ("pull_request", "refs/pull/143/merge", ["3.12"]),
        ("push", "refs/heads/main", []),
        ("workflow_dispatch", "refs/heads/main", ["3.12", "3.13", "3.14"]),
    ],
)
def test_event_preserves_every_linux_minor_and_declared_mac_coverage(event, ref, mac_versions):
    jobs = matrix(event, ref)["include"]
    assert [job["python"] for job in jobs if job["os"] == "ubuntu-24.04"] == [
        "3.12",
        "3.13",
        "3.14",
    ]
    assert [job["python"] for job in jobs if job["os"] == "macos-15"] == mac_versions
    assert {job["os"] for job in jobs} <= {"ubuntu-24.04", "macos-15"}
    assert len({(job["os"], job["python"]) for job in jobs}) == len(jobs)
    parts = part_matrix(event, ref)["include"]
    assert parts == [
        {**job, "part": str(part), "parts": str(TEST_PARTS)}
        for job in jobs
        for part in range(1, TEST_PARTS + 1)
    ]


@pytest.mark.parametrize(
    "event,ref",
    [
        ("schedule", "refs/heads/main"),
        ("pull_request_target", "refs/heads/main"),
        ("push", "refs/heads/feature"),
        ("workflow_dispatch", "refs/heads/feature"),
        ("pull_request", "refs/heads/main"),
        ("pull_request", "refs/pull/143/head"),
    ],
)
def test_unknown_events_and_wrong_refs_fail_closed(event, ref):
    with pytest.raises(ValueError):
        matrix(event, ref)


def test_macos_transport_and_clipboard_steps_follow_the_selected_source_runner():
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    expected = "${{ matrix.os == '" + MACOS_RUNNER + "' }}"
    for job_name in ("tests", "application"):
        steps = workflow["jobs"][job_name]["steps"]
        transport = next(
            step
            for step in steps
            if step.get("name") == "Install real terminal transport test tools on macOS"
        )
        assert transport["if"] == expected
        if job_name == "application":
            clipboard = next(
                step
                for step in steps
                if step.get("name")
                == "Verify plaintext clipboard on the owned ephemeral macOS runner"
            )
            assert clipboard["if"] == expected


def test_retained_test_parts_preserve_clean_source_before_debug_preflight(tmp_path):
    from scripts.verify_ephemeral_debug_kind import source_identity

    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    application = workflow["jobs"]["application"]
    download = next(
        step
        for step in application["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    )

    def git(*arguments):
        return subprocess.run(
            ["git", *arguments], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    source = tmp_path / "src/kuberich/fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    git("init", "--quiet")
    git("add", ".gitignore", "src")
    git(
        "-c",
        "user.name=Owned fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Owned source fixture",
    )
    commit = git("rev-parse", "HEAD")
    assert source_identity(tmp_path) == commit
    part = tmp_path / download["with"]["path"] / "test-part-fixture-1/coverage-part.data"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"retained original coverage part")
    assert source_identity(tmp_path) == commit
    assert part.read_bytes() == b"retained original coverage part"

    untracked = source.with_name("untracked.py")
    untracked.write_text("value = 2\n")
    with pytest.raises(ValueError, match="freeze clean tracked source"):
        source_identity(tmp_path)
    untracked.unlink()
    source.write_text("value = 3\n")
    with pytest.raises(ValueError, match="freeze clean tracked source"):
        source_identity(tmp_path)
    source.write_text("value = 1\n")
    assert source_identity(tmp_path) == commit and part.is_file()


@pytest.mark.parametrize("missing", ["GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_OUTPUT"])
def test_cli_refuses_missing_github_inputs(monkeypatch, tmp_path, capsys, missing):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.delenv(missing)
    assert main() == 1
    assert "Quality planning failed" in capsys.readouterr().err
    assert not (tmp_path / "output").exists()


def test_cli_refuses_unknown_event_and_unwritable_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path))
    assert main() == 1
    assert "Unsupported quality event" in capsys.readouterr().err
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert main() == 1
    assert "Quality planning failed" in capsys.readouterr().err


def test_plan_cli_and_aggregate_use_the_same_actual_event(tmp_path):
    output = tmp_path / "output"
    environment = dict(os.environ, GITHUB_OUTPUT=str(output), GITHUB_REF="refs/heads/main")
    environment["GITHUB_EVENT_NAME"] = "workflow_dispatch"
    process = subprocess.run(
        [sys.executable, "-m", "scripts.ci_policy"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert set(outputs) == {"matrix", "test_matrix", "native_matrix"}
    assert json.loads(outputs["matrix"]) == matrix("workflow_dispatch", "refs/heads/main")
    assert json.loads(outputs["test_matrix"]) == part_matrix("workflow_dispatch", "refs/heads/main")
    assert json.loads(outputs["native_matrix"]) == native_matrix(
        "workflow_dispatch", "refs/heads/main"
    )
    environment["KUBERICH_JOB_RESULTS"] = json.dumps(
        {
            "plan": {"result": "success", "outputs": outputs},
            "fast": {"result": "success"},
            "tests": {"result": "success"},
            "application": {"result": "success"},
            "standalone": {"result": "success"},
        }
    )
    passed = subprocess.run(
        [sys.executable, "-m", "scripts.check_quality_gate"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert passed.returncode == 0, passed.stderr
    environment["GITHUB_EVENT_NAME"] = "push"
    refused = subprocess.run(
        [sys.executable, "-m", "scripts.check_quality_gate"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert refused.returncode == 1 and "complete matrix" in refused.stderr


def test_workflow_keeps_required_event_checks_full_behavior_and_independent_gates():
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["on"]["pull_request"] is None
    assert workflow["permissions"] == {"contents": "read"}
    assert "github.event_name" in workflow["concurrency"]["group"]
    plan, fast, tests, application, gate = (
        workflow["jobs"][name] for name in ("plan", "fast", "tests", "application", "quality-gate")
    )
    assert plan["steps"][-1]["run"] == "python3 -m scripts.ci_policy"
    assert fast["needs"] == "plan"
    assert "uv run python scripts/check_private_access.py" in [
        step.get("run") for step in fast["steps"]
    ]
    fast_command = next(step["run"] for step in fast["steps"] if "pytest" in step.get("run", ""))
    for option in ("-m fast", "--dist loadgroup", "--max-worker-restart=0", "--maxfail=1"):
        assert option in fast_command
    assert tests["needs"] == ["plan", "fast"]
    assert workflow["jobs"]["standalone"]["needs"] == ["plan", "fast"]
    assert tests["strategy"] == {
        "fail-fast": False,
        "matrix": "${{ fromJSON(needs.plan.outputs.test_matrix) }}",
    }
    part = "\n".join(step.get("run", "") for step in tests["steps"])
    assert "pytest --cov=kuberich --cov-branch" in part
    assert "-n 2 --dist loadgroup --max-worker-restart=0" in part
    assert next(step for step in tests["steps"] if "pytest" in step.get("run", ""))["env"] == {
        "KUBERICH_TEST_PART": "${{ matrix.part }}/${{ matrix.parts }}"
    }
    kept = next(
        step
        for step in tests["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert kept["with"]["name"] == (
        "test-part-${{ matrix.os }}-python-${{ matrix.python }}-${{ matrix.part }}"
    )
    assert kept["with"]["if-no-files-found"] == "error"
    assert application["needs"] == ["plan", "tests"]
    assert application["strategy"] == {
        "fail-fast": False,
        "matrix": "${{ fromJSON(needs.plan.outputs.matrix) }}",
    }
    for job in (tests, application):
        assert "if" not in job and "continue-on-error" not in job
        assert all("continue-on-error" not in step for step in job["steps"])
    commands = "\n".join(step.get("run", "") for step in application["steps"])
    for required in (
        "scripts.combine_test_parts --parts artifacts/test-parts",
        "scripts.merge_runtime_coverage",
        "scripts/check_coverage.py coverage.json",
        "diff-cover coverage.xml",
        "--fail-under 90",
        "scripts.check_supply_chain --verify",
        "scripts.verify_contexts_kind",
        "scripts.verify_kind_lifecycle",
        "scripts.verify_shell_kind",
        "scripts.verify_port_forwards_kind",
        "scripts.verify_mutations_kind",
        "scripts.verify_editing_kind",
        "scripts.verify_workloads_kind",
        "scripts.verify_operations_kind",
        "scripts.verify_cleanup_kind",
        "scripts.verify_credential_interop_kind",
        "scripts.verify_transfers_kind",
        "scripts.verify_custom_resources_kind",
        "scripts.verify_aggregate_logs_kind",
        "scripts.verify_pulse_kind",
        "scripts.verify_relationships_kind",
        "scripts.verify_authorization_kind",
        "scripts.diagnostics_tools --directory",
        "scripts.verify_diagnostics_kind",
        "scripts.verify_container_inspection_kind",
        "scripts.verify_history_kind",
        "scripts.verify_curated_resources_kind",
        "scripts.helm_tools --directory",
        "scripts.verify_helm_kind",
        "scripts.verify_manifests_kind",
        "scripts.verify_node_shell_kind",
        "scripts.verify_node_maintenance_kind",
        "scripts.verify_ephemeral_debug_kind",
        "scripts.benchmark_tools --directory",
        "scripts.verify_benchmarks_kind",
        "scripts.verify_quickstart",
        "uv build",
        "twine check",
    ):
        assert required in commands
    assert (
        commands.index("scripts.combine_test_parts")
        < commands.index("python -m scripts.merge_runtime_coverage")
        < commands.index("scripts/check_coverage.py coverage.json")
    )
    assert "scripts/merge_runtime_coverage.py" in commands
    assert "git rev-parse HEAD^" in commands
    assert gate["name"] == "Quality gate" and gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == {"plan", "fast", "tests", "application", "standalone"}
    assert gate["steps"][-1]["run"] == "python3 -m scripts.check_quality_gate"
    linux_tools = next(
        step
        for step in application["steps"]
        if "scripts.ci_apt" in step.get("run", "") and "mypy" not in step["run"]
    )
    assert linux_tools["if"] == "${{ matrix.os == 'ubuntu-24.04' }}"
    assert "openssh-server tmux" in linux_tools["run"]
    assert linux_tools["timeout-minutes"] == 6
    cluster_steps = [
        step for step in application["steps"] if "python -m scripts.verify" in step.get("run", "")
    ]
    assert len(cluster_steps) == 27
    for step in cluster_steps:
        assert step["if"] == "${{ matrix.os == 'ubuntu-24.04' && matrix.python == '3.12' }}"
    upload = next(
        step
        for step in application["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["name"] == "quality-${{ matrix.os }}-python-${{ matrix.python }}"
    assert upload["if"] == "${{ always() }}"
    assert not any(
        path.startswith("artifacts/test-parts") or path == "artifacts/**"
        for path in upload["with"]["path"].splitlines()
    )
    assert "artifacts/backend/*" in upload["with"]["path"].splitlines()
    assert "artifacts/authorization/**" in upload["with"]["path"].splitlines()
    assert "artifacts/container-inspection/**" in upload["with"]["path"].splitlines()
    assert "artifacts/metric-history/**" in upload["with"]["path"].splitlines()
    assert "artifacts/curated-resources/**" in upload["with"]["path"].splitlines()
    assert "artifacts/helm/**" in upload["with"]["path"].splitlines()
    assert "artifacts/manifests/**" in upload["with"]["path"].splitlines()
    assert "uv run mypy --strict scripts/verify_manifests_kind.py" in commands
    assert "artifacts/node-shell/**" in upload["with"]["path"].splitlines()
    assert "uv run mypy --strict scripts/verify_node_shell_kind.py" in commands
    assert "artifacts/node-maintenance/**" in upload["with"]["path"].splitlines()
    assert "uv run mypy --strict scripts/verify_node_maintenance_kind.py" in commands
    assert "artifacts/ephemeral-debug/**" in upload["with"]["path"].splitlines()
    assert "uv run mypy --strict scripts/verify_ephemeral_debug_kind.py" in commands
    ephemeral_debug = next(
        step
        for step in cluster_steps
        if "python -m scripts.verify_ephemeral_debug_kind" in step["run"]
    )
    assert '--kind "$RUNNER_TEMP/kuberich-kind"' in ephemeral_debug["run"]
    assert '--kubectl "$RUNNER_TEMP/kuberich-shell/bin/kubectl"' in ephemeral_debug["run"]
    assert "--docker /usr/bin/docker" in ephemeral_debug["run"]
    assert "--evidence artifacts/ephemeral-debug/evidence.json" in ephemeral_debug["run"]
    assert "artifacts/benchmarks/**" in upload["with"]["path"].splitlines()
    assert (
        "uv run mypy --strict scripts/benchmark_tools.py scripts/benchmark_native.py scripts/verify_benchmarks_kind.py"
        in commands
    )
    benchmarks = next(
        step for step in cluster_steps if "python -m scripts.verify_benchmarks_kind" in step["run"]
    )
    assert '--kind "$RUNNER_TEMP/kuberich-kind"' in benchmarks["run"]
    assert '--kubectl "$RUNNER_TEMP/kuberich-shell/bin/kubectl"' in benchmarks["run"]
    assert '--vegeta "$RUNNER_TEMP/kuberich-benchmark-tools/vegeta"' in benchmarks["run"]
    assert "--docker /usr/bin/docker" in benchmarks["run"]
    assert "--evidence artifacts/benchmarks/evidence.json" in benchmarks["run"]
    assert benchmarks["run"].index("scripts.benchmark_tools") < benchmarks["run"].index(
        "scripts.verify_benchmarks_kind"
    )
    assert "trap retain_benchmark_receipt EXIT" in benchmarks["run"]
    assert "uv run mypy --strict scripts/ci_apt.py" in commands
    assert (
        "uv run mypy --strict scripts/curated_kind.py scripts/verify_curated_resources_kind.py"
        in commands
    )
    curated = next(
        step
        for step in cluster_steps
        if "python -m scripts.verify_curated_resources_kind" in step["run"]
    )
    assert '--kind "$RUNNER_TEMP/kuberich-kind"' in curated["run"]
    assert "--docker /usr/bin/docker" in curated["run"]
    assert "--evidence artifacts/curated-resources/evidence.json" in curated["run"]
    manifests = next(
        step for step in cluster_steps if "python -m scripts.verify_manifests_kind" in step["run"]
    )
    assert '--kind "$RUNNER_TEMP/kuberich-kind"' in manifests["run"]
    assert '--kubectl "$RUNNER_TEMP/kuberich-shell/bin/kubectl"' in manifests["run"]
    assert "--docker /usr/bin/docker" in manifests["run"]
    assert "--evidence artifacts/manifests/evidence.json" in manifests["run"]
    node_shell = next(
        step for step in cluster_steps if "python -m scripts.verify_node_shell_kind" in step["run"]
    )
    assert '--kind "$RUNNER_TEMP/kuberich-kind"' in node_shell["run"]
    assert '--kubectl "$RUNNER_TEMP/kuberich-shell/bin/kubectl"' in node_shell["run"]
    assert "--docker /usr/bin/docker" in node_shell["run"]
    assert "--evidence artifacts/node-shell/evidence.json" in node_shell["run"]
    maintenance = next(
        step
        for step in cluster_steps
        if "python -m scripts.verify_node_maintenance_kind" in step["run"]
    )
    assert '--kind "$RUNNER_TEMP/kuberich-kind"' in maintenance["run"]
    assert '--kubectl "$RUNNER_TEMP/kuberich-shell/bin/kubectl"' in maintenance["run"]
    assert "--docker /usr/bin/docker" in maintenance["run"]
    assert "--evidence artifacts/node-maintenance/evidence.json" in maintenance["run"]


@pytest.mark.parametrize("job_name", ["fast", "tests", "standalone"])
@pytest.mark.parametrize("failed", [False, True])
def test_benchmark_tool_preparation_is_explicit_fatal_and_preserves_original_receipt(
    tmp_path, job_name, failed
):
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    job = workflow["jobs"][job_name]
    steps = job["steps"]
    prepared = next(
        step
        for step in steps
        if step.get("name") == "Prepare the pinned optional HTTP benchmark test tool"
    )
    assert "if" not in prepared and "continue-on-error" not in prepared
    executed = next(
        step
        for step in steps
        if ("uv run pytest" if job_name != "standalone" else "scripts.verify_standalone")
        in step.get("run", "")
    )
    assert steps.index(prepared) < steps.index(executed)
    runner = tmp_path / "runner"
    runner.mkdir()
    environment_file = tmp_path / "github-environment"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    helper = binaries / "uv"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import os,sys\nfrom pathlib import Path\n"
        "assert sys.argv[1:6] == ['run','python','-m','scripts.benchmark_tools','--directory']\n"
        "assert len(sys.argv) == 7\n"
        "directory=Path(sys.argv[6])\n"
        "assert directory.is_absolute()\n"
        "directory.mkdir()\n"
        "(directory/'prepared-provenance.json').write_bytes(b'{\"owned_fixture\":true}\\n')\n"
        "sys.exit(3 if os.environ['KUBERICH_ENROLLMENT_FAIL'] == '1' else 0)\n"
    )
    helper.chmod(0o700)
    native = Path("artifacts/standalone/owned-platform")
    environment = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ.get("PATH", ""),
        RUNNER_TEMP=str(runner),
        GITHUB_ENV=str(environment_file),
        KUBERICH_NATIVE_DIR=str(native),
        KUBERICH_ENROLLMENT_FAIL="1" if failed else "0",
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", prepared["run"]],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == (3 if failed else 0), result.stderr
    saved = (
        tmp_path / native / "benchmark-tool-provenance/prepared-provenance.json"
        if job_name == "standalone"
        else tmp_path / "artifacts/benchmarks/tool-provenance/prepared-provenance.json"
    )
    assert (
        saved.read_bytes()
        == (runner / "kuberich-benchmark-tools/prepared-provenance.json").read_bytes()
    )
    if failed:
        assert not environment_file.exists()
    else:
        assert environment_file.read_text().splitlines() == [
            "KUBERICH_TEST_VEGETA=" + str(runner / "kuberich-benchmark-tools/vegeta")
        ]
    # The native verifier owns a fresh output directory; provisioning must not claim it.
    assert not (tmp_path / native / "runtime").exists()
    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    if job_name == "standalone":
        assert "artifacts/standalone/${{ matrix.target }}/benchmark-tool-provenance/*" in (
            upload["with"]["path"].splitlines()
        )


def test_linux_package_setup_keeps_every_tool_and_a_finite_step_deadline():
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    expected = {
        "fast": "xclip xvfb",
        "tests": "openssh-server tmux xclip xvfb",
        "application": "openssh-server tmux xclip xvfb",
        "standalone": "gcc libc6-dev binutils",
    }
    for name, packages in expected.items():
        steps = [
            step
            for step in workflow["jobs"][name]["steps"]
            if "python -m scripts.ci_apt" in step.get("run", "")
        ]
        assert len(steps) == 1
        step = steps[0]
        assert step["timeout-minutes"] == 6
        assert step["run"].splitlines()[0] == "uv run python -m scripts.ci_apt " + packages
        assert "continue-on-error" not in step
    assert "sudo install -d -m 0755 /run/sshd" in (
        next(
            step["run"]
            for step in workflow["jobs"]["tests"]["steps"]
            if "python -m scripts.ci_apt" in step.get("run", "")
        )
    )
    assert "docker version" in (
        next(
            step["run"]
            for step in workflow["jobs"]["standalone"]["steps"]
            if "python -m scripts.ci_apt" in step.get("run", "")
        )
    )


@pytest.mark.parametrize(
    "filename,hosts",
    [
        (
            "quality.yml",
            {
                "plan": "ubuntu-24.04",
                "fast": "ubuntu-24.04",
                "tests": "${{ matrix.os }}",
                "application": "${{ matrix.os }}",
                "standalone": "${{ matrix.os }}",
                "quality-gate": "ubuntu-24.04",
            },
        ),
        ("repository.yml", {"repository": "ubuntu-24.04"}),
        ("release.yml", {"validate": "ubuntu-24.04", "publish": "ubuntu-24.04"}),
        ("pages.yml", {"prepare": "ubuntu-24.04", "publish": "ubuntu-24.04"}),
    ],
)
def test_workflows_pin_every_linux_job_and_preserve_matrix_selection(filename, hosts):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    assert {name: job["runs-on"] for name, job in workflow["jobs"].items()} == hosts


@pytest.mark.parametrize(
    "event,ref",
    [
        ("pull_request", "refs/pull/49/merge"),
        ("push", "refs/heads/main"),
        ("workflow_dispatch", "refs/heads/main"),
    ],
)
def test_native_verification_always_covers_four_real_os_architectures(event, ref):
    selected = native_matrix(event, ref)["include"]
    assert {(job["os"], job["target"]) for job in selected} == {
        ("ubuntu-22.04", "linux-x86_64"),
        ("ubuntu-22.04-arm", "linux-arm64"),
        ("macos-15-intel", "macos-x86_64"),
        ("macos-15", "macos-arm64"),
    }
    assert len(selected) == 4
    for job in selected:
        if job["target"].startswith("linux-"):
            assert len(job["kind_sha256"]) == 64 and len(job["kubectl_sha256"]) == 64


def test_native_matrix_is_required_and_cannot_skip_archive_or_runtime_failures():
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
    native = workflow["jobs"]["standalone"]
    assert native["needs"] == ["plan", "fast"]
    assert "if" not in native and "continue-on-error" not in native
    assert native["strategy"] == {
        "fail-fast": False,
        "matrix": "${{ fromJSON(needs.plan.outputs.native_matrix) }}",
    }
    for step in native["steps"]:
        assert "continue-on-error" not in step
    commands = "\n".join(step.get("run", "") for step in native["steps"])
    for required in (
        "scripts.build_standalone",
        "scripts.verify_standalone",
        "scripts.check_standalone",
        "scripts.verify_shell_kind",
        "--executable",
        "sha256sum --check",
    ):
        assert required in commands
    upload = next(
        step
        for step in native["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["if"] == "${{ always() }}"
