"""Controlled coverage evidence must reject false passes and missing modules."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/check_coverage.py"
CRITICAL = "src/kubetrol/critical.py"
FEATURE = "src/kubetrol/feature.py"
POLICY = """
[tool.coverage.run]
branch = true
source = ["kubetrol"]
[tool.coverage.report]
include_namespace_packages = true
exclude_lines = []
partial_branches = []
[tool.kubetrol.coverage]
critical_modules = ["src/kubetrol/critical.py"]
"""


def summary(lines: int, statements: int, branches: int = 0, total_branches: int = 0) -> dict:
    return {
        "covered_lines": lines,
        "num_statements": statements,
        "missing_lines": statements - lines,
        "excluded_lines": 0,
        "covered_branches": branches,
        "num_branches": total_branches,
        "missing_branches": total_branches - branches,
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(POLICY)
    for name in (CRITICAL, FEATURE):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n")
    return tmp_path


def write_report(project: Path, critical: dict, feature: dict) -> dict:
    report = {
        "meta": {"branch_coverage": True},
        "files": {CRITICAL: {"summary": critical}, FEATURE: {"summary": feature}},
        "totals": {key: critical[key] + feature[key] for key in critical},
    }
    (project / "coverage.json").write_text(json.dumps(report))
    return report


def run_gate(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_complete_evidence_and_exact_ninety_percent_pass(project: Path) -> None:
    write_report(project, summary(10, 10), summary(80, 90, 9, 10))
    result = run_gate(project)
    assert result.returncode == 0, result.stderr
    assert "Production lines: 90/100 (90.0000%)" in result.stdout
    assert "Production branches: 9/10 (90.0000%)" in result.stdout


def test_low_branches_fail_even_with_high_combined_coverage(project: Path) -> None:
    write_report(project, summary(10, 10), summary(100, 100, 1, 2))
    result = run_gate(project)
    assert result.returncode == 1
    assert "Production lines: 110/110 (100.0000%)" in result.stdout
    assert "Production branches below 90%" in result.stderr


def test_low_lines_fail_independently_of_complete_branches(project: Path) -> None:
    write_report(project, summary(10, 10), summary(79, 90, 2, 2))
    result = run_gate(project)
    assert result.returncode == 1
    assert "Production lines below 90%" in result.stderr
    assert "Production branches: 2/2 (100.0000%)" in result.stdout


def test_rounding_cannot_turn_a_subthreshold_result_into_a_pass(project: Path) -> None:
    write_report(project, summary(10, 10), summary(17989, 19990))
    result = run_gate(project)
    assert result.returncode == 1
    assert "89.9950%" in result.stdout


@pytest.mark.parametrize("critical", [summary(9, 10), summary(10, 10, 1, 2)])
def test_critical_gaps_fail_when_global_floors_pass(project: Path, critical: dict) -> None:
    write_report(project, critical, summary(100, 100, 100, 100))
    result = run_gate(project)
    assert result.returncode == 1
    assert f"Critical {CRITICAL}" in result.stderr
    assert "below 100%" in result.stderr
    assert "Production" not in result.stderr


def test_no_branches_are_reported_as_not_applicable(project: Path) -> None:
    write_report(project, summary(10, 10), summary(10, 10))
    result = run_gate(project)
    assert result.returncode == 0
    assert "Production branches: N/A" in result.stdout
    assert "branches: 0/0 (100" not in result.stdout


def test_omitted_unimported_namespace_module_fails_inventory(project: Path) -> None:
    write_report(project, summary(10, 10), summary(10, 10))
    missing = project / "src/kubetrol/domain/unimported.py"
    missing.parent.mkdir()
    missing.write_text("VALUE = 1\n")
    result = run_gate(project)
    assert result.returncode == 1
    assert "src/kubetrol/domain/unimported.py" in result.stderr
    assert "inventory mismatch" in result.stderr


def test_test_code_cannot_inflate_the_denominator(project: Path) -> None:
    report = write_report(project, summary(10, 10), summary(10, 10))
    report["files"]["tests/test_feature.py"] = {"summary": summary(1000, 1000)}
    (project / "coverage.json").write_text(json.dumps(report))
    result = run_gate(project)
    assert result.returncode == 1
    assert "extra=['tests/test_feature.py']" in result.stderr


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('source = ["kubetrol"]', 'source = ["kubetrol.cli"]'),
        ("branch = true", "branch = false"),
        ("include_namespace_packages = true", "include_namespace_packages = false"),
        ('source = ["kubetrol"]', 'source = ["kubetrol"]\nomit = ["*/domain/*"]'),
        ("exclude_lines = []", 'exclude_lines = [".*"]'),
        ("partial_branches = []", 'partial_branches = [".*"]'),
        ("exclude_lines = []", 'exclude_lines = []\nexclude_also = [".*"]'),
        ("partial_branches = []", "partial_branches = []\nskip_covered = true"),
        ('critical_modules = ["src/kubetrol/critical.py"]', "critical_modules = []"),
        (
            'critical_modules = ["src/kubetrol/critical.py"]',
            'critical_modules = ["src/kubetrol/deleted.py"]',
        ),
    ],
)
def test_configuration_cannot_hide_required_evidence(
    project: Path, original: str, replacement: str
) -> None:
    write_report(project, summary(10, 10), summary(10, 10))
    (project / "pyproject.toml").write_text(POLICY.replace(original, replacement))
    assert run_gate(project).returncode == 1


@pytest.mark.parametrize("problem", ["malformed", "missing", "no-branches", "totals", "excluded"])
def test_invalid_evidence_fails_closed(project: Path, problem: str) -> None:
    report = write_report(project, summary(10, 10), summary(10, 10))
    path = project / "coverage.json"
    if problem == "malformed":
        path.write_text("{bad json")
    elif problem == "missing":
        path.unlink()
    else:
        if problem == "no-branches":
            report["meta"]["branch_coverage"] = False
        elif problem == "totals":
            report["totals"] = summary(999, 999)
        elif problem == "excluded":
            report["files"][FEATURE]["summary"]["excluded_lines"] = 100
        path.write_text(json.dumps(report))
    result = run_gate(project)
    assert result.returncode == 1
    assert "Coverage gate failed" in result.stderr


def test_empty_production_code_is_not_a_coverage_claim(project: Path) -> None:
    write_report(project, summary(0, 0), summary(0, 0))
    result = run_gate(project)
    assert result.returncode == 1
    assert "empty production code" in result.stderr


def test_real_coverage_includes_an_unimported_namespace_module(tmp_path: Path) -> None:
    # Exercise coverage.py itself, not just a hand-written summary fixture.
    (tmp_path / "pyproject.toml").write_text(POLICY)
    package = tmp_path / "src/kubetrol"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "critical.py").write_text("VALUE = 1\n")
    nested = package / "domain"
    nested.mkdir()
    (nested / "unimported.py").write_text("UNTESTED = 1\n")
    (tmp_path / "runner.py").write_text("import kubetrol.critical\n")
    environment = os.environ.copy()
    environment.pop("COVERAGE_RCFILE", None)
    environment.pop("COVERAGE_PROCESS_START", None)
    environment["PYTHONPATH"] = str(tmp_path / "src")
    environment["COVERAGE_FILE"] = str(tmp_path / ".coverage")
    for command in (
        [sys.executable, "-m", "coverage", "run", "runner.py"],
        [sys.executable, "-m", "coverage", "json"],
    ):
        subprocess.run(
            command,
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    result = run_gate(tmp_path)
    assert result.returncode == 1
    assert "Production lines: 1/2 (50.0000%)" in result.stdout
    assert "inventory mismatch" not in result.stderr
