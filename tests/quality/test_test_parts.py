"""Parallel test parts cover every file once and combine fail-closed."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import combine_test_parts, part_timings
from scripts.combine_test_parts import DATA, collect, combine
from tests.support.parts import MAX_PARTS, UNKNOWN_SECONDS, assign, load_timings, parse_part

ROOT = Path(__file__).resolve().parents[2]
FILES = [f"tests/unit/test_{index}.py" for index in range(9)]


@pytest.mark.parametrize("value", ["", "2", "0/4", "5/4", "1/17", "a/4", "2/b", "-1/4", "1/4/2"])
def test_part_values_outside_the_supported_range_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="INDEX/COUNT"):
        parse_part(value)


def test_part_values_inside_the_supported_range_are_read() -> None:
    assert parse_part("2/4") == (2, 4)
    assert parse_part(f"{MAX_PARTS}/{MAX_PARTS}") == (MAX_PARTS, MAX_PARTS)


@pytest.mark.parametrize("value", [[], {"a.py": -1}, {"a.py": "1"}, {"a.py": True}, {"a.py": None}])
def test_invalid_timing_tables_are_rejected(tmp_path: Path, value: object) -> None:
    path = tmp_path / "timings.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="non-negative seconds"):
        load_timings(path)


def test_the_checked_in_timing_table_names_existing_test_files() -> None:
    timings = load_timings()
    assert timings and all((ROOT / name).is_file() for name in timings)
    assert all(name.startswith("tests/") and name.endswith(".py") for name in timings)


def test_every_file_lands_in_exactly_one_part_and_the_result_is_stable() -> None:
    timings = {name: float(index) for index, name in enumerate(FILES)}
    parts = assign(reversed(FILES), 4, timings)
    assert parts == assign([*FILES, *FILES], 4, timings)
    assert sorted(parts) == sorted(FILES) and set(parts.values()) == {1, 2, 3, 4}
    loads = [sum(timings[name] for name in FILES if parts[name] == part) for part in (1, 2, 3, 4)]
    assert max(loads) - min(loads) <= max(timings.values())


def test_unknown_files_get_a_default_duration_and_a_part() -> None:
    parts = assign(["tests/new.py", "tests/slow.py"], 2, {"tests/slow.py": UNKNOWN_SECONDS + 1})
    assert parts == {"tests/slow.py": 1, "tests/new.py": 2}
    assert assign(["tests/new.py"], 1, {}) == {"tests/new.py": 1}


def test_the_collection_hook_keeps_only_the_files_of_one_part() -> None:
    selected = []
    for part in (1, 2):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/quality"],
            cwd=ROOT,
            env={**_environment(), "KUBERICH_TEST_PART": f"{part}/2"},
            capture_output=True,
            text=True,
            check=True,
        )
        selected.append(
            {line.split("::")[0] for line in result.stdout.splitlines() if "::" in line}
        )
    assert selected[0] and selected[1] and not selected[0] & selected[1]
    assert "deselected" in result.stdout


def test_an_invalid_part_value_stops_collection() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/quality"],
        cwd=ROOT,
        env={**_environment(), "KUBERICH_TEST_PART": "3/2"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "INDEX/COUNT" in result.stdout + result.stderr


def _environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != "KUBERICH_TEST_PART"}


def _part(parts: Path, name: str, evidence: dict[str, bytes] | None = None) -> Path:
    part = parts / name
    part.mkdir(parents=True)
    (part / DATA).write_bytes(b"")
    for relative, content in (evidence or {}).items():
        target = part / "artifacts" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return part


def test_evidence_from_every_part_is_copied_and_identical_copies_are_accepted(
    tmp_path: Path,
) -> None:
    parts, root = tmp_path / "parts", tmp_path / "root"
    _part(parts, "p-1", {"ui/receipt.json": b"ui", "shared.txt": b"same"})
    _part(parts, "p-2", {"backend/receipt.json": b"backend", "shared.txt": b"same"})
    root.mkdir()
    data = collect(parts, "p-", 2, root)
    assert data == [parts / "p-1" / DATA, parts / "p-2" / DATA]
    assert (root / "artifacts/ui/receipt.json").read_bytes() == b"ui"
    assert (root / "artifacts/backend/receipt.json").read_bytes() == b"backend"
    assert (root / "artifacts/shared.txt").read_bytes() == b"same"


@pytest.mark.parametrize("names", [[], ["p-1"], ["p-1", "p-2", "p-3"], ["p-1", "q-2"]])
def test_a_missing_or_unexpected_part_fails(tmp_path: Path, names: list[str]) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    for name in names:
        _part(parts, name)
    with pytest.raises(ValueError, match="Expected test parts p-1, p-2"):
        collect(parts, "p-", 2, tmp_path)


def test_a_missing_parts_directory_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="found none"):
        collect(tmp_path / "absent", "p-", 1, tmp_path)


def test_a_part_without_coverage_data_fails(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    (_part(parts, "p-1") / DATA).unlink()
    with pytest.raises(ValueError, match="p-1 has no coverage data"):
        collect(parts, "p-", 1, tmp_path)


def test_conflicting_evidence_fails(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    _part(parts, "p-1", {"ui/receipt.json": b"one"})
    _part(parts, "p-2", {"ui/receipt.json": b"two"})
    with pytest.raises(ValueError, match=r"disagree about artifacts/ui/receipt\.json"):
        collect(parts, "p-", 2, tmp_path)


def test_symbolic_links_in_evidence_fail(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    part = _part(parts, "p-1", {"ui/receipt.json": b"one"})
    (part / "artifacts/ui/link").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symbolic link: artifacts/ui/link"):
        collect(parts, "p-", 1, tmp_path / "root")


def _measure(root: Path, name: str, flag: str) -> Path:
    """Record branch coverage of one tiny program into a part data file."""
    path = root / f"{name}.data"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            f"--data-file={path}",
            "sample.py",
            flag,
        ],
        cwd=root,
        env={key: value for key, value in os.environ.items() if not key.startswith("COV")},
        check=True,
    )
    return path


def test_parts_combine_into_one_report_with_every_branch(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("import sys\nif sys.argv[1]:\n    print(1)\nprint(2)\n")
    (tmp_path / "pyproject.toml").write_text("[tool.coverage.run]\nbranch = true\n")
    data = [_measure(tmp_path, "one", "yes"), _measure(tmp_path, "two", "")]
    (tmp_path / ".coverage").write_text("stale")
    combine(data, tmp_path)
    report = json.loads((tmp_path / "coverage.json").read_text())
    assert report["totals"]["percent_covered"] == 100.0
    assert report["meta"]["branch_coverage"] is True
    assert (tmp_path / "coverage.xml").is_file() and all(path.is_file() for path in data)


def test_the_command_reports_failures_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = tmp_path / "parts"
    arguments = ["combine", "--parts", str(parts), "--prefix", "p-", "--count", "1"]
    monkeypatch.setattr(sys, "argv", [*arguments, "--root", str(tmp_path)])
    assert combine_test_parts.main() == 1
    assert "Combining test parts failed: Expected test parts p-1" in capsys.readouterr().err
    _part(parts, "p-1")
    calls = []
    monkeypatch.setattr(combine_test_parts, "combine", lambda data, root: calls.append(data))
    assert combine_test_parts.main() == 0
    assert calls == [[parts / "p-1" / DATA]]
    assert "Combined coverage and evidence from 1 test parts." in capsys.readouterr().out


def test_timings_are_summed_per_file_from_a_junit_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="tests.unit.test_a" name="one" time="1.25"/>'
        '<testcase classname="tests.unit.test_a.TestGroup" name="two" time="2"/>'
        '<testcase classname="tests.ui.test_b" name="three"/>'
        '<testcase classname="conftest" name="setup" time="9"/>'
        "</testsuite></testsuites>"
    )
    assert part_timings.timings(report) == {"tests/ui/test_b.py": 0.0, "tests/unit/test_a.py": 3.2}
    output = tmp_path / "timings.json"
    monkeypatch.setattr(sys, "argv", ["timings", str(report), "--output", str(output)])
    assert part_timings.main() == 0
    assert load_timings(output) == {"tests/ui/test_b.py": 0.0, "tests/unit/test_a.py": 3.2}
    assert "Wrote timings for 2 test files (3 s)." in capsys.readouterr().out
    report.write_text("<testsuites/>")
    assert part_timings.main() == 1
    assert "no test cases" in capsys.readouterr().err
