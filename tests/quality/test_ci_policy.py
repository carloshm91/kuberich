"""Development cost reductions must preserve required checks and release gates."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci_policy import main, matrix

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
    assert [job["python"] for job in jobs if job["os"] == "ubuntu-latest"] == [
        "3.12",
        "3.13",
        "3.14",
    ]
    assert [job["python"] for job in jobs if job["os"] == "macos-latest"] == mac_versions
    assert len({(job["os"], job["python"]) for job in jobs}) == len(jobs)


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
    key, value = output.read_text().strip().split("=", 1)
    assert key == "matrix" and json.loads(value) == matrix("workflow_dispatch", "refs/heads/main")
    environment["KUBERICH_JOB_RESULTS"] = json.dumps(
        {
            "plan": {"result": "success", "outputs": {"matrix": value}},
            "application": {"result": "success"},
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
    plan, application, gate = (
        workflow["jobs"][name] for name in ("plan", "application", "quality-gate")
    )
    assert plan["steps"][-1]["run"] == "python3 -m scripts.ci_policy"
    assert application["needs"] == "plan"
    assert application["strategy"] == {
        "fail-fast": False,
        "matrix": "${{ fromJSON(needs.plan.outputs.matrix) }}",
    }
    assert "if" not in application and "continue-on-error" not in application
    commands = "\n".join(step.get("run", "") for step in application["steps"])
    for required in (
        "pytest --cov=kuberich --cov-branch",
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
        "scripts.verify_credential_interop_kind",
        "scripts.verify_transfers_kind",
        "scripts.verify_custom_resources_kind",
        "scripts.verify_quickstart",
        "uv build",
        "twine check",
    ):
        assert required in commands
    assert "git rev-parse HEAD^" in commands
    assert gate["name"] == "Quality gate" and gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == {"plan", "application"}
    assert gate["steps"][-1]["run"] == "python3 -m scripts.check_quality_gate"
