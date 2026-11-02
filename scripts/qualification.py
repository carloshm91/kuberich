"""Existing phase gates and commands for one local run or exact-source collection."""

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from packaging.version import Version

from scripts.release_policy import (
    APPLICATION_JOBS,
    PHASE_GATES,
    QUALITY_WORKFLOW,
    REPOSITORY,
    qualified_run,
    reviewed_issue_numbers,
    successful_jobs,
)

# owned_kind finally: two inspections (ps + inspect, 30 s each), deletion
# (90 s), and one command's existing two 2 s signal waits plus 5 s reap.
OWNED_KIND_CLEANUP_SECONDS = 2 * 2 * 30 + 90 + 2 * 2 + 5
SIGNAL_GRACE_SECONDS = 2
REAP_GRACE_SECONDS = 5

KIND_SCENARIOS = (
    ("contexts", "verify_contexts_kind", False),
    ("lifecycle", "verify_kind_lifecycle", False),
    ("shell", "verify_shell_kind", True),
    ("port-forwards", "verify_port_forwards_kind", True),
    ("credentials", "verify_credential_interop_kind", True),
    ("mutations", "verify_mutations_kind", False),
    ("editing", "verify_editing_kind", False),
    ("workloads", "verify_workloads_kind", False),
    ("operations", "verify_operations_kind", False),
    ("cleanup", "verify_cleanup_kind", False),
    ("transfers", "verify_transfers_kind", True),
    ("custom-resources", "verify_custom_resources_kind", False),
    ("aggregate-logs", "verify_aggregate_logs_kind", False),
)


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...]
    timeout: int = 2700
    cleanup_timeout: float = 30


def phase(value: str) -> tuple[str, int]:
    """Use the same reviewed phase mapping as publication, without publishing."""
    version = Version(value)
    key = f"{version.major}.{version.minor}.0"
    if value != key or key not in PHASE_GATES:
        raise ValueError("Choose a reviewed phase such as 0.3.0, not an unmapped release line.")
    return key, reviewed_issue_numbers()[PHASE_GATES[key]]


def type_command(root: Path) -> tuple[str, ...]:
    """Keep the actual workflow's strict target list rather than a second copy."""
    workflow = yaml.safe_load((root / QUALITY_WORKFLOW).read_text())
    commands = [
        tuple(shlex.split(line))
        for step in workflow["jobs"]["application"]["steps"]
        for line in str(step.get("run", "")).splitlines()
        if line.strip().startswith("uv run mypy --strict ")
    ]
    targets = tuple(dict.fromkeys(target for command in commands for target in command[4:]))
    if (
        not commands
        or "src/kuberich" not in targets
        or any(target.startswith("-") for target in targets)
    ):
        raise ValueError("Expected complete strict workflow target lists with shared options.")
    return ("uv", "run", "mypy", "--strict", *targets)


def local_stages(root: Path, output: Path, temporary: Path, workers: int, base: str) -> list[Stage]:
    if workers < 0 or workers > 64:
        raise ValueError("Workers must be between 0 and 64.")
    return [
        Stage("plan", ("uv", "run", "python", "scripts/validate_plan.py")),
        Stage(
            "source-import",
            (
                "uv",
                "run",
                "python",
                "-c",
                "from pathlib import Path; import kuberich; assert Path(kuberich.__file__).resolve() == Path.cwd() / 'src/kuberich/__init__.py'",
            ),
        ),
        Stage("lint", ("uv", "run", "ruff", "check", ".")),
        Stage("format", ("uv", "run", "ruff", "format", "--check", ".")),
        Stage("private-access", ("uv", "run", "python", "scripts/check_private_access.py")),
        Stage("types", type_command(root)),
        Stage(
            "startup",
            (
                "uv",
                "run",
                "python",
                "-m",
                "scripts.check_startup",
                "--output",
                str(output / "startup"),
            ),
        ),
        Stage(
            "tests",
            (
                "uv",
                "run",
                "pytest",
                "-n",
                str(workers),
                "--cov=kuberich",
                "--cov-branch",
                "--cov-report=json",
                "--cov-report=xml",
                "--tb=short",
                f"--basetemp={temporary / 'tests-pytest'}",
                f"--junitxml={output / 'cases.xml'}",
            ),
        ),
        Stage("runtime-controls", ("uv", "run", "python", "-m", "scripts.merge_runtime_coverage")),
        Stage("coverage", ("uv", "run", "python", "scripts/check_coverage.py", "coverage.json")),
        Stage(
            "changed-coverage",
            (
                "uv",
                "run",
                "diff-cover",
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
            ),
        ),
        Stage("build", ("uv", "build")),
        # Enumerate built artifacts after the build, without a shell glob.
        Stage("metadata", ("uv", "run", "twine", "check")),
        Stage(
            "supply-chain", ("uv", "run", "python", "-m", "scripts.check_supply_chain", "--verify")
        ),
    ]


def cluster_stages(
    output: Path, kind: Path, kubectl: Path, wheel: Path, repetition: int
) -> list[Stage]:
    stages = [
        Stage(
            f"kind-{repetition}-{name}",
            (
                "uv",
                "run",
                "python",
                "-m",
                f"scripts.{module}",
                "--kind",
                str(kind),
                *(("--kubectl", str(kubectl)) if needs_kubectl else ()),
                "--evidence",
                str(output / f"kind-{repetition}-{name}.json"),
            ),
            cleanup_timeout=OWNED_KIND_CLEANUP_SECONDS,
        )
        for name, module, needs_kubectl in KIND_SCENARIOS
    ]
    # Quickstart is the installed-wheel rehearsal in addition to the API trials.
    stages.append(
        Stage(
            f"kind-{repetition}-quickstart",
            (
                "uv",
                "run",
                "python",
                "-m",
                "scripts.verify_quickstart",
                "--kind",
                str(kind),
                "--kubectl",
                str(kubectl),
                "--wheel",
                str(wheel),
                "--evidence",
                str(output / f"kind-{repetition}-quickstart.json"),
            ),
            cleanup_timeout=OWNED_KIND_CLEANUP_SECONDS,
        )
    )
    return stages


def validate_hosted(run: dict[str, Any], jobs: dict[str, Any], commit: str) -> str:
    """Collect current exact-source full verification; never reuse CI execution."""
    if not isinstance(run.get("head_repository"), dict) or type(run.get("id")) is not int:
        raise ValueError("Missing workflow identity.")
    qualified_run(run, commit, QUALITY_WORKFLOW)
    entries = jobs.get("jobs")
    if (
        not isinstance(entries, list)
        or type(jobs.get("total_count")) is not int
        or jobs["total_count"] != len(entries)
    ):
        raise ValueError("The full current job inventory is required, without truncated pages.")
    successful_jobs(entries, APPLICATION_JOBS)
    return f"https://github.com/{REPOSITORY}/actions/runs/{int(run['id'])}"


def waiting(run: dict[str, Any], commit: str, path: str) -> bool:
    """Report queued work as pending; completed work still uses strict validators."""
    if run.get("status") == "completed":
        return False
    event = "workflow_dispatch" if path == QUALITY_WORKFLOW else "push"
    if (
        run.get("status") not in {"queued", "in_progress", "waiting", "pending", "requested"}
        or run.get("head_sha") != commit
        or run.get("path") != path
        or run.get("head_branch") != "main"
        or run.get("event") != event
        or not isinstance(run.get("head_repository"), dict)
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("Pending workflow must still belong to the exact source/repository.")
    return True


def latest_run(runs: dict[str, Any], chosen: int, commit: str) -> None:
    """As in release preflight, a later failed attempt blocks an older success."""
    matching = [run for run in runs.get("workflow_runs", []) if run.get("head_sha") == commit]
    if not matching:
        raise ValueError("Missing current exact-source workflow run.")
    latest = max(matching, key=lambda run: (run["run_number"], run["run_attempt"]))
    if latest.get("id") != chosen:
        raise ValueError("Collect the latest exact-source workflow run, including failures.")


def summary(report: dict[str, Any]) -> str:
    lines = [
        f"# Phase {report['phase']} verification",
        "",
        f"Source: `{report['source']['commit']}`. Gate: #{report['phase_gate']}.",
        "",
        f"Actual source version: **{report.get('source_version', 'unknown')}**. Target phase: **{report['phase']}**.",
        *(
            [
                "",
                "Engineering preview report for the target phase; the actual source version differs.",
            ]
            if report.get("source_version") not in {None, report["phase"]}
            and Version(str(report["source_version"])).major == 0
            else []
        ),
        "",
        f"Result: **{report['status']}**. Publication is not authorized by this report.",
        "",
    ]
    for gate in report["gates"]:
        lines.append(f"- **{gate['status']}**: {gate['name']}. {gate.get('reason', '')}".rstrip())
    lines.extend(("", "See report.json for commands, original logs, skips and source audit.", ""))
    return "\n".join(lines)
