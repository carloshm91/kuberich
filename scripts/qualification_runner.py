"""Run or collect existing phase verification without publishing anything."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from packaging.version import Version

from scripts.ci_policy import LINUX_RUNNER
from scripts.qualification import (
    Stage,
    cluster_stages,
    latest_run,
    local_stages,
    phase,
    summary,
    validate_hosted,
    waiting,
)
from scripts.release_policy import REPOSITORY, qualified_run, successful_jobs


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=root, text=True).strip()


def snapshot(root: Path) -> dict[str, Any]:
    paths = git(root, "ls-files", "-z").split("\0")
    return {
        "commit": git(root, "rev-parse", "HEAD"),
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "status": git(root, "status", "--porcelain"),
        "files": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths if name
        },
    }


def archive(root: Path, destination: Path) -> None:
    """Preserve canonical originals before another command can overwrite them."""
    destination.mkdir(parents=True, exist_ok=False)
    for name in (".coverage", "coverage.json", "coverage.xml", "diff-coverage.json"):
        if (root / name).is_file():
            shutil.copy2(root / name, destination / name)
    if (root / "dist").is_dir():
        shutil.copytree(root / "dist", destination / "dist", symlinks=True)
    for name in ("ui", "backend", "terminal", "security", "cluster", "quickstart", "distribution"):
        source = root / "artifacts" / name
        if source.is_dir():
            shutil.copytree(source, destination / name, symlinks=True)


def skips(path: Path) -> list[dict[str, str]]:
    return [
        {
            "case": case.get("classname", "") + "::" + case.get("name", ""),
            "reason": skipped.get("message", ""),
        }
        for case in ElementTree.parse(path).getroot().findall(".//testcase")
        for skipped in case.findall("skipped")
    ]


class Runner:
    """One owned process group at a time; originals survive failure and signals."""

    def __init__(self, root: Path, output: Path, report: dict[str, Any]) -> None:
        self.root, self.output, self.report = root, output, report
        self.current: subprocess.Popen[bytes] | None = None
        self.cancelled: int | None = None
        self.interrupted = False

    def save(self) -> None:
        temporary = self.output / "report.tmp"
        temporary.write_text(json.dumps(self.report, indent=2) + "\n")
        temporary.replace(self.output / "report.json")
        (self.output / "summary.md").write_text(summary(self.report))

    def stop(self, signum: int, frame: FrameType | None) -> None:
        if self.cancelled is not None:
            return
        self.cancelled = signum
        self.report["cancel_signal"] = signum
        if self.current is not None and self.current.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(self.current.pid, signal.SIGINT)
                self.interrupted = True

    def unchanged(self) -> None:
        if snapshot(self.root) != self.report["source"]:
            raise ValueError("Tracked candidate inputs changed during qualification.")

    def drain(self) -> None:
        process = self.current
        if process is None or process.poll() is not None:
            return
        if not self.interrupted:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGINT)
                self.interrupted = True
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

    def wait(self, timeout: int, gate: dict[str, Any]) -> int:
        assert self.current is not None
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.current.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                if self.cancelled is not None or time.monotonic() >= deadline:
                    gate["timed_out"] = self.cancelled is None
                    gate["reason"] = (
                        "Command deadline exceeded; original retained."
                        if self.cancelled is None
                        else "Cancelled; owned group drained."
                    )
                    self.drain()
                    assert self.current.returncode is not None
                    return self.current.returncode

    def run(self, stage: Stage) -> None:
        self.unchanged()
        if self.cancelled is not None:
            raise InterruptedError("Qualification cancelled before the next command.")
        gate = next(item for item in self.report["gates"] if item["name"] == stage.name)
        gate.update(status="running", command=list(stage.command), started=time.time())
        self.save()
        started = time.monotonic()
        self.interrupted = False
        environment = dict(os.environ)
        environment["PYTEST_ADDOPTS"] = ""
        environment["PYTEST_DEBUG_TEMPROOT"] = self.report["external_temp_owner"]["physical_parent"]
        for key in (
            "KUBERICH_TEST_PART",
            "KUBERICH_TEST_AGGREGATE_RUNTIME",
            "KUBERICH_TEST_AGGREGATE_REQUEST",
            "KUBERICH_TEST_BACKEND_RUNTIME",
            "KUBERICH_TEST_BACKEND_REQUEST",
        ):
            environment.pop(key, None)
        path = self.output / f"{stage.name}.log"
        try:
            with path.open("wb") as log:
                self.current = subprocess.Popen(
                    stage.command,
                    cwd=self.root,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                gate["pid"] = self.current.pid
                self.save()
                code = self.wait(stage.timeout, gate)
                gate.update(returncode=code, process_reaped=True)
            if code == 0 and "--evidence" in stage.command:
                evidence = Path(stage.command[stage.command.index("--evidence") + 1])
                if not evidence.is_file() or not isinstance(json.loads(evidence.read_text()), dict):
                    raise ValueError("Owned verifier must retain its actual JSON receipt.")
                gate["evidence"] = str(evidence)
            gate["status"] = (
                "passed"
                if code == 0 and self.cancelled is None and not gate.get("timed_out")
                else "failed"
            )
        except BaseException:
            gate["status"] = "failed"
            self.drain()
            if self.current is not None:
                gate["process_reaped"] = self.current.poll() is not None
            raise
        finally:
            self.current = None
            gate.update(elapsed_seconds=time.monotonic() - started, log=path.name)
            self.save()
        try:
            self.unchanged()
        except ValueError:
            gate.update(status="failed", reason="Tracked candidate inputs changed during command.")
            self.save()
            raise
        if gate["status"] != "passed":
            raise RuntimeError(f"Stopped at {stage.name}; retain its original log.")


def api(route: str) -> dict[str, Any]:
    result = subprocess.run(
        ("gh", "api", f"repos/{REPOSITORY}/{route}"), capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise ValueError("Read-only GitHub qualification lookup failed; check gh authentication.")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("Expected a GitHub response object.")
    return value


def pending(name: str, reason: str = "Not run or collected.") -> dict[str, Any]:
    return {"name": name, "status": "pending", "reason": reason}


def collect(report: dict[str, Any], quality_run: int | None, repository_run: int | None) -> None:
    sha = report["source"]["commit"]
    quality_gates = {
        "source-import",
        "lint",
        "format",
        "types",
        "tests",
        "runtime-controls",
        "coverage",
        "changed-coverage",
        "build",
        "metadata",
        "supply-chain",
        "owned-kind",
        "native-platforms",
        "local-skips",
    }
    for label, identifier, path in (
        ("quality", quality_run, ".github/workflows/quality.yml"),
        ("repository", repository_run, ".github/workflows/repository.yml"),
    ):
        if identifier is None:
            continue
        event = "workflow_dispatch" if label == "quality" else "push"
        latest_run(
            api(f"actions/workflows/{label}.yml/runs?head_sha={sha}&event={event}&per_page=100"),
            identifier,
            sha,
        )
        run = api(f"actions/runs/{identifier}")
        report.setdefault("hosted", {})[label] = {"id": identifier, "status": run.get("status")}
        if waiting(run, sha, path):
            continue
        jobs = api(f"actions/runs/{identifier}/jobs?filter=latest&per_page=100")
        if label == "quality":
            link = validate_hosted(run, jobs, sha)
            covered = quality_gates
        else:
            qualified_run(run, sha, path)
            if jobs.get("total_count") != len(jobs.get("jobs", [])):
                raise ValueError("Incomplete repository job inventory.")
            successful_jobs(jobs["jobs"], {"Repository checks": LINUX_RUNNER})
            link = f"https://github.com/{REPOSITORY}/actions/runs/{identifier}"
            covered = {"repository", "plan"}
        for gate in report["gates"]:
            if gate["name"] in covered and gate["status"] == "pending":
                gate.update(status="passed", reason=f"Collected exact-source verification: {link}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", help="Reviewed phase, for example 0.3.0")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--base", help="Full changed-coverage comparison commit; default merge base or HEAD^"
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--repetitions", type=int, choices=(1, 3), default=1)
    parser.add_argument("--kind", type=Path, help="Explicit verified kind v0.33.0 executable")
    parser.add_argument("--kubectl", type=Path, help="Explicit verified kubectl executable")
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Collect actual hosted results without local execution",
    )
    parser.add_argument("--quality-run", type=int)
    parser.add_argument("--repository-run", type=int)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    output = (args.output or root / "artifacts/qualification" / uuid4().hex).resolve()
    report: dict[str, Any] | None = None
    runner: Runner | None = None
    previous: dict[signal.Signals, Any] = {}
    code = 1
    try:
        target, issue = phase(args.phase)
        source = snapshot(root)
        if source["status"]:
            raise ValueError("Commit and freeze the candidate before qualification.")
        source_version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
        if Version(target).major >= 1 and Version(source_version).major < 1:
            raise ValueError(
                "Stable phase qualification requires a major-version 1 source candidate."
            )
        base = args.base
        if base is None:
            base = git(root, "merge-base", "HEAD", "origin/main")
            if base == source["commit"]:
                base = "HEAD^"
        base = git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
        if (
            base == source["commit"]
            or subprocess.run(
                ("git", "merge-base", "--is-ancestor", base, source["commit"]), cwd=root
            ).returncode
            != 0
        ):
            raise ValueError("Changed coverage needs a distinct ancestor comparison commit.")
        if any(
            identifier is not None and identifier <= 0
            for identifier in (args.quality_run, args.repository_run)
        ):
            raise ValueError("Hosted run IDs must be positive integers.")
        if (
            output.is_relative_to(root)
            and subprocess.run(("git", "check-ignore", "--quiet", str(output)), cwd=root).returncode
            != 0
        ):
            raise ValueError("An in-checkout report must be in an ignored artifact directory.")
        if (args.kind is None) != (args.kubectl is None):
            raise ValueError(
                "Provide both explicit kind and kubectl paths, or leave real-cluster gates pending."
            )
        tools = tuple(path.resolve(strict=True) for path in (args.kind, args.kubectl) if path)
        if any(not path.is_file() or not os.access(path, os.X_OK) for path in tools):
            raise ValueError("Owned cluster tool paths must be executable files.")
        output.mkdir(parents=True, exist_ok=False)
        temporary = Path(tempfile.mkdtemp(prefix="kuberich-qualify-", dir="/tmp")).resolve()
        temporary.chmod(0o700)
        if temporary.resolve().is_relative_to(root):
            raise ValueError(
                "Installation qualification requires an external physical temporary directory."
            )
        owner = {
            "workspace": str(root),
            "candidate": source["commit"],
            "physical_parent": str(temporary.resolve()),
            "pid": os.getpid(),
        }
        (temporary / "owner.json").write_text(json.dumps(owner, indent=2) + "\n")
        stages = local_stages(root, output, temporary, args.workers, base)
        report = {
            "schema_version": 1,
            "phase": target,
            "phase_gate": issue,
            "source": source,
            "source_version": source_version,
            "platform": {"system": platform.system(), "python": platform.python_version()},
            "comparison_base": base,
            "external_temp_owner": owner,
            "status": "running",
            "publication_authorized": False,
            "gates": [pending(stage.name) for stage in stages],
        }
        report["gates"].extend(
            (
                pending(
                    "owned-kind",
                    "Provide explicit verified tool paths or collect the full hosted run.",
                ),
                pending(
                    "native-platforms", "A local run does not establish the full native matrix."
                ),
                pending("repository", "Collect the exact-source repository validation run."),
                pending(
                    "repetitions",
                    "Publication still requires three contract/owned-cluster repetitions.",
                ),
            )
        )
        runner = Runner(root, output, report)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, runner.stop)
        runner.save()
        if not args.collect_only:
            archive(root, output / "before")
            for stage in stages:
                if stage.name == "metadata":
                    version = report["source_version"]
                    artifacts = (
                        *sorted(root.glob(f"dist/kuberich-{version}-*.whl")),
                        root / f"dist/kuberich-{version}.tar.gz",
                    )
                    if len(artifacts) != 2 or not all(path.is_file() for path in artifacts):
                        raise ValueError("Require the actual source version's wheel and sdist.")
                    stage = Stage(stage.name, (*stage.command, *(str(path) for path in artifacts)))
                runner.run(stage)
            report["skips"] = skips(output / "cases.xml")
            for repetition in range(1, args.repetitions + 1):
                if repetition > 1:
                    stage = Stage(
                        f"contracts-{repetition}",
                        (
                            "uv",
                            "run",
                            "pytest",
                            "tests/contract",
                            "--no-cov",
                            "-n",
                            str(args.workers),
                            f"--basetemp={temporary / f'contracts-{repetition}-pytest'}",
                            f"--junitxml={output / f'contracts-{repetition}.xml'}",
                        ),
                    )
                    report["gates"].append(pending(stage.name))
                    runner.run(stage)
                    report["skips"].extend(skips(output / f"contracts-{repetition}.xml"))
                if tools:
                    wheels = tuple(root.glob(f"dist/kuberich-{report['source_version']}-*.whl"))
                    if len(wheels) != 1:
                        raise ValueError(
                            "Require one exact candidate wheel for installed quickstart."
                        )
                    for stage in cluster_stages(output, tools[0], tools[1], wheels[0], repetition):
                        report["gates"].append(pending(stage.name))
                        runner.run(stage)
            if tools:
                next(g for g in report["gates"] if g["name"] == "owned-kind").update(
                    status="passed"
                )
            if tools and args.repetitions == 3:
                next(g for g in report["gates"] if g["name"] == "repetitions").update(
                    status="passed"
                )
            if report["skips"]:
                report["gates"].append(
                    pending(
                        "local-skips",
                        "See every explicit skip in report.json; native results remain required.",
                    )
                )
        collect(report, args.quality_run, args.repository_run)
        runner.unchanged()
        report["source_unchanged"] = True
        report["status"] = (
            "pending" if any(g["status"] == "pending" for g in report["gates"]) else "passed"
        )
        report["limits"] = [
            "Publication approval/readiness and separately required sustained-performance/provider reviews are not established by this command."
        ]
        code = 2 if report["status"] == "pending" else 0
    except Exception as error:
        if report is not None:
            report.update(status="failed", error=f"{type(error).__name__}: {error}")
        else:
            print(f"Qualification failed before execution: {error}", file=sys.stderr)
        code = 1
        if runner is not None and runner.cancelled is not None:
            assert report is not None
            report["status"] = "cancelled"
            code = 128 + runner.cancelled
    finally:
        try:
            if report is not None and runner is not None:
                try:
                    if not args.collect_only:
                        archive(root, output / "after")
                    report["source_unchanged"] = snapshot(root) == report["source"]
                    if not report["source_unchanged"]:
                        report.update(
                            status="failed",
                            error="Tracked candidate inputs changed before the final audit.",
                        )
                        code = 1
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    report.update(
                        status="failed", retention_error=f"{type(error).__name__}: {error}"
                    )
                    code = 1
                if runner.cancelled is not None:
                    report["status"] = "cancelled"
                    code = 128 + runner.cancelled
                report["finished"] = time.time()
                runner.save()
                print(f"{report['status']}: {output / 'report.json'}")
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
