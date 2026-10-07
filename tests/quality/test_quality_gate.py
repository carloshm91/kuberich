"""The aggregate status must reject every nonsuccess dependency result."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_policy import matrix

ROOT = Path(__file__).resolve().parents[2]


def run_gate(results: str | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/143/merge")
    environment.pop("KUBETROL_JOB_RESULTS", None)
    if results is not None:
        environment["KUBETROL_JOB_RESULTS"] = results
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
        "plan": {
            "result": "success",
            "outputs": {"matrix": json.dumps(matrix("pull_request", "refs/pull/143/merge"))},
        },
    }


def test_successful_complete_matrix_passes() -> None:
    result = run_gate(json.dumps(successful_results()))
    assert result.returncode == 0
    assert "complete application matrix succeeded" in result.stdout


@pytest.mark.parametrize("job", ["plan", "application"])
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
