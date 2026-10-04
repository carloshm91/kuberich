"""Use real Git commits and coverage XML to qualify changed-line enforcement."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def run(command: list[str], directory: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        GIT_AUTHOR_NAME="Coverage fixture",
        GIT_AUTHOR_EMAIL="fixture@example.invalid",
        GIT_COMMITTER_NAME="Coverage fixture",
        GIT_COMMITTER_EMAIL="fixture@example.invalid",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    return subprocess.run(
        command,
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    run(["git", "init", "-b", "main"], tmp_path)
    run(["git", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "Base"], tmp_path)
    base = run(["git", "rev-parse", "HEAD"], tmp_path).stdout.strip()
    run(["git", "switch", "-c", "feature"], tmp_path)
    return tmp_path, base


def candidate(directory: Path, covered: int, lines: int, change_code: bool = True) -> None:
    if change_code:
        source = directory / "src/kubetrol/new.py"
        source.parent.mkdir(parents=True)
        source.write_text("".join(f"VALUE_{line} = {line}\n" for line in range(1, lines + 1)))
        run(["git", "add", "src"], directory)
    else:
        (directory / "README.md").write_text("Documentation change\n")
        run(["git", "add", "README.md"], directory)
    run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "Candidate"], directory)
    entries = "".join(
        f'<line number="{line}" hits="{int(line <= covered)}"/>' for line in range(1, lines + 1)
    )
    (directory / "coverage.xml").write_text(
        "<coverage><sources><source>src/kubetrol</source></sources><packages>"
        '<package name="kubetrol"><classes><class filename="new.py"><lines>'
        f"{entries}</lines></class></classes></package></packages></coverage>"
    )


def diff_coverage(directory: Path, base: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("diff-cover")
    assert executable is not None
    return subprocess.run(
        [
            executable,
            "coverage.xml",
            "--compare-branch",
            base,
            "--fail-under",
            "90",
            "--ignore-staged",
            "--ignore-unstaged",
            "--total-percent-float",
            "--format",
            "json:diff-coverage.json",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


@pytest.mark.parametrize(("covered", "expected"), [(0, 1), (8, 1), (9, 0), (10, 0)])
def test_changed_line_floor_rejects_new_untested_code(
    repository: tuple[Path, str], covered: int, expected: int
) -> None:
    directory, base = repository
    candidate(directory, covered, 10)
    result = diff_coverage(directory, base)
    assert result.returncode == expected, result.stdout + result.stderr
    report = json.loads((directory / "diff-coverage.json").read_text())
    assert report["total_num_lines"] == 10
    assert report["total_num_violations"] == 10 - covered


def test_documentation_only_diff_has_no_executable_line_claim(
    repository: tuple[Path, str],
) -> None:
    directory, base = repository
    candidate(directory, 0, 0, change_code=False)
    result = diff_coverage(directory, base)
    assert result.returncode == 0
    report = json.loads((directory / "diff-coverage.json").read_text())
    assert report["total_num_lines"] == 0


def test_unknown_comparison_base_fails(repository: tuple[Path, str]) -> None:
    directory, _ = repository
    candidate(directory, 10, 10)
    assert diff_coverage(directory, "missing-base").returncode != 0
