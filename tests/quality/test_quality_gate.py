"""The aggregate status must reject every nonsuccess dependency result."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_policy import matrix, native_matrix

ROOT = Path(__file__).resolve().parents[2]


def run_gate(
    results: str | None, event: str = "pull_request", ref: str = "refs/pull/143/merge"
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(GITHUB_EVENT_NAME=event, GITHUB_REF=ref)
    environment.pop("KUBERICH_JOB_RESULTS", None)
    if results is not None:
        environment["KUBERICH_JOB_RESULTS"] = results
    return subprocess.run(
        [sys.executable, "-m", "scripts.check_quality_gate"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def successful_results() -> dict:
    return {
        "application": {"result": "success"},
        "standalone": {"result": "success"},
        "plan": {
            "result": "success",
            "outputs": {
                "matrix": json.dumps(matrix("pull_request", "refs/pull/143/merge")),
                "native_matrix": json.dumps(native_matrix("pull_request", "refs/pull/143/merge")),
            },
        },
    }


def test_successful_complete_matrix_passes() -> None:
    result = run_gate(json.dumps(successful_results()))
    assert result.returncode == 0
    assert "complete application matrix succeeded" in result.stdout


@pytest.mark.parametrize("job", ["plan", "application", "standalone"])
@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", None])
def test_unsuccessful_matrix_cannot_pass(job: str, state: str | None) -> None:
    results = successful_results()
    results[job]["result"] = state
    result = run_gate(json.dumps(results))
    assert result.returncode == 1
    assert "required job did not succeed" in result.stderr


@pytest.mark.parametrize(
    "results",
    [None, "{invalid", "[]", "{}", '{"other": {"result": "success"}}', '{"application": null}'],
)
def test_missing_or_invalid_dependencies_fail_closed(results: str | None) -> None:
    result = run_gate(results)
    assert result.returncode == 1
    assert "Quality gate failed" in result.stderr


@pytest.mark.parametrize(
    "planned",
    [
        None,
        "{invalid",
        "{}",
        "null",
        '{"include": []}',
        json.dumps(matrix("push", "refs/heads/main")),
        json.dumps(matrix("workflow_dispatch", "refs/heads/main")),
    ],
)
def test_missing_corrupted_or_incomplete_plan_cannot_pass(planned) -> None:
    results = successful_results()
    results["plan"]["outputs"]["matrix"] = planned
    result = run_gate(json.dumps(results))
    assert result.returncode == 1
    assert "Quality gate failed" in result.stderr


@pytest.mark.parametrize(
    "event,ref",
    [
        ("pull_request", "refs/pull/143/merge"),
        ("push", "refs/heads/main"),
        ("workflow_dispatch", "refs/heads/main"),
    ],
)
@pytest.mark.parametrize("runner", ["ubuntu-latest", "ubuntu-26.04", "macos-latest"])
def test_complete_plan_with_wrong_linux_runner_cannot_pass(event, ref, runner) -> None:
    results = successful_results()
    planned = matrix(event, ref)
    results["plan"]["outputs"]["matrix"] = json.dumps(planned)
    assert run_gate(json.dumps(results), event, ref).returncode == 0
    planned["include"][0]["os"] = runner
    results["plan"]["outputs"]["matrix"] = json.dumps(planned)
    refused = run_gate(json.dumps(results), event, ref)
    assert refused.returncode == 1 and "complete matrix" in refused.stderr


@pytest.mark.parametrize(
    "corruption", ["missing", "invalid", "empty", "duplicate", "wrong-runner", "missing-target"]
)
def test_a_successful_native_job_cannot_hide_an_incomplete_native_plan(corruption):
    results = successful_results()
    planned = native_matrix("pull_request", "refs/pull/143/merge")
    if corruption == "missing":
        results["plan"]["outputs"].pop("native_matrix")
    elif corruption == "invalid":
        results["plan"]["outputs"]["native_matrix"] = "{invalid"
    else:
        if corruption == "empty":
            planned["include"] = []
        elif corruption == "duplicate":
            planned["include"][1] = dict(planned["include"][0])
        elif corruption == "wrong-runner":
            planned["include"][0]["os"] = "ubuntu-latest"
        else:
            planned["include"].pop()
        results["plan"]["outputs"]["native_matrix"] = json.dumps(planned)
    result = run_gate(json.dumps(results))
    assert result.returncode == 1 and "Quality gate failed" in result.stderr
