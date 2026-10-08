"""Enforce separate coverage floors over the complete production package."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast


class GateError(ValueError):
    """The evidence or configuration cannot establish the required coverage."""


def mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise GateError(f"{label} must be an object")
    return cast(dict[str, object], value)


def count(summary: Mapping[str, object], key: str) -> int:
    value = summary.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GateError(f"{key} must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class Counts:
    lines: int
    statements: int
    branches: int
    total_branches: int

    @classmethod
    def from_summary(cls, value: object) -> Counts:
        summary = mapping(value, "coverage summary")
        result = cls(
            count(summary, "covered_lines"),
            count(summary, "num_statements"),
            count(summary, "covered_branches"),
            count(summary, "num_branches"),
        )
        if result.lines + count(summary, "missing_lines") != result.statements:
            raise GateError("inconsistent line counts")
        if result.branches + count(summary, "missing_branches") != result.total_branches:
            raise GateError("inconsistent branch counts")
        if count(summary, "excluded_lines"):
            raise GateError("excluded production lines are not permitted")
        return result

    def describe(self, label: str, minimum: int) -> list[str]:
        failures = []
        for metric, covered, total in (
            ("lines", self.lines, self.statements),
            ("branches", self.branches, self.total_branches),
        ):
            if total == 0:
                print(f"{label} {metric}: N/A (no executable {metric})")
            else:
                print(f"{label} {metric}: {covered}/{total} ({100 * covered / total:.4f}%)")
                # Compare integer counts, never a rounded display percentage.
                if 100 * covered < minimum * total:
                    failures.append(f"{label} {metric} below {minimum}%")
        return failures


def read_policy(root: Path) -> list[str]:
    configuration = tomllib.loads((root / "pyproject.toml").read_text())
    tools = configuration["tool"]
    coverage = tools["coverage"]
    run = coverage["run"]
    report = coverage["report"]
    if run.get("branch") is not True or run.get("source") != ["kuberich"]:
        raise GateError("measure branches over the entire kuberich package")
    if report.get("include_namespace_packages") is not True:
        raise GateError("include unimported namespace-package modules")
    for section in (run, report):
        if section.get("omit") or section.get("include"):
            raise GateError("production coverage include/omit filters are not permitted")
    for key in ("exclude_lines", "partial_branches"):
        if report.get(key) != []:
            raise GateError(f"{key} must be explicitly empty")
    for key in ("exclude_also", "partial_also", "ignore_errors", "skip_empty", "skip_covered"):
        if report.get(key):
            raise GateError(f"{key} would hide production evidence")
    critical = tools["kuberich"]["coverage"]["critical_modules"]
    if (
        not isinstance(critical, list)
        or not critical
        or any(not isinstance(path, str) for path in critical)
        or len(set(critical)) != len(critical)
    ):
        raise GateError("critical_modules must be a nonempty list of unique source paths")
    return cast(list[str], critical)


def evaluate(root: Path, report_path: Path) -> list[str]:
    critical = read_policy(root)
    report = mapping(json.loads(report_path.read_text()), "coverage report")
    if mapping(report.get("meta"), "coverage metadata").get("branch_coverage") is not True:
        raise GateError("coverage evidence must include branches")
    expected = {
        path.relative_to(root).as_posix()
        for path in (root / "src/kuberich").rglob("*.py")
        if path.is_file()
    }
    if not expected:
        raise GateError("no production Python modules found")
    files = mapping(report.get("files"), "coverage files")
    measured = {}
    for name, value in files.items():
        normalized = (root / name).resolve().relative_to(root).as_posix()
        if normalized in measured:
            raise GateError(f"duplicate coverage path: {normalized}")
        measured[normalized] = Counts.from_summary(mapping(value, name).get("summary"))
    if measured.keys() != expected:
        missing = sorted(expected - measured.keys())
        extra = sorted(measured.keys() - expected)
        raise GateError(f"production inventory mismatch; missing={missing}, extra={extra}")
    if any(path not in expected for path in critical):
        raise GateError("every critical module must name an existing production Python file")
    totals = Counts.from_summary(report.get("totals"))
    summed = Counts(
        sum(item.lines for item in measured.values()),
        sum(item.statements for item in measured.values()),
        sum(item.branches for item in measured.values()),
        sum(item.total_branches for item in measured.values()),
    )
    if totals != summed:
        raise GateError("coverage totals do not match the production files")
    if totals.statements == 0:
        raise GateError("empty production code does not establish coverage")
    failures = totals.describe("Production", 90)
    for path in critical:
        if measured[path].statements == 0:
            raise GateError(f"critical module has no executable statements: {path}")
        failures.extend(measured[path].describe(f"Critical {path}", 100))
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", type=Path, default=Path("coverage.json"))
    arguments = parser.parse_args(argv)
    try:
        failures = evaluate(Path.cwd().resolve(), arguments.report)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Coverage gate failed: {error}", file=sys.stderr)
        return 1
    for failure in failures:
        print(f"Coverage gate failed: {failure}", file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
