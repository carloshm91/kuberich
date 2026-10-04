"""The aggregate status must reject every nonsuccess dependency result."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[2] / "scripts/check_quality_gate.py"


def run_gate(results: str | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("KUBETROL_JOB_RESULTS", None)
    if results is not None:
        environment["KUBETROL_JOB_RESULTS"] = results
    return subprocess.run(
        [sys.executable, str(GATE)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_successful_complete_matrix_passes() -> None:
    result = run_gate(json.dumps({"application": {"result": "success"}}))
    assert result.returncode == 0
    assert "complete application matrix succeeded" in result.stdout


@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", None])
def test_unsuccessful_matrix_cannot_pass(state: str | None) -> None:
    result = run_gate(json.dumps({"application": {"result": state}}))
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
