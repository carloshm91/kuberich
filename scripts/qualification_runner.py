"""Run or collect existing phase verification without publishing anything."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from packaging.version import Version

from scripts.ci_policy import LINUX_RUNNER
from scripts.qualification import (
    REAP_GRACE_SECONDS,
    SIGNAL_GRACE_SECONDS,
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

ARCHIVE_TREES = (
    "ui",
    "backend",
    "terminal",
    "security",
    "cluster",
    "quickstart",
    "distribution",
    "releases",
    "container-inspection",
    "helm",
    "manifests",
    "ephemeral-debug",
    "packaging",
    "startup",
    "pulse",
    "relationships",
    "authorization",
    "diagnostics",
    "metric-history",
    "curated-resources",
    "node-shell",
    "node-maintenance",
    "benchmarks",
    "resource-creation",
)
RETENTION_MAX_FILES = 32768
RETENTION_MAX_BYTES = 1024 * 1024 * 1024


def regular_files(path: Path, boundary: Path) -> list[Path]:
    """Bound all traversal entries, including empty directories, before sorting."""
    entries = 1

    def visit(current: Path) -> list[Path]:
        nonlocal entries
        try:
            physical = current.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"Unsafe retention path: {current}") from error
        if not current.is_relative_to(boundary) or physical != current.absolute():
            raise ValueError(f"Unsafe retention path: {current}")
        if len(current.relative_to(boundary).parts) > 64:
            raise ValueError("Retention directory-depth bound exceeded.")
        if not current.exists():
            return []
        if current.is_file():
            return [current]
        if not current.is_dir():
            raise ValueError(f"Retention requires regular files/directories: {current}")
        children = []
        with os.scandir(current) as iterator:
            for child in iterator:
                entries += 1
                if entries > RETENTION_MAX_FILES:
                    raise ValueError("Retention traversal-entry bound exceeded.")
                children.append(current / child.name)
        return [file for child in sorted(children) for file in visit(child)]

    return visit(path)


def retention_hash(path: Path) -> str:
    """Read a finite declared size, rejecting evidence that grows or shrinks."""
    size = path.stat().st_size
    if size > RETENTION_MAX_BYTES:
        raise ValueError("Retention byte bound exceeded.")
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = size
        while remaining:
            block = stream.read(min(remaining, 1024 * 1024))
            if not block:
                raise ValueError("Retained evidence shrank while hashing.")
            checksum.update(block)
            remaining -= len(block)
        if stream.read(1):
            raise ValueError("Retained evidence grew while hashing.")
    return checksum.hexdigest()


def retained_inventory(directory: Path) -> dict[str, dict[str, Any]]:
    """Hash exact retained bytes with a finite file/byte inventory."""
    inventory = {}
    total = 0
    for path in regular_files(directory, directory):
        size = path.stat().st_size
        total += size
        if total > RETENTION_MAX_BYTES:
            raise ValueError("Retention byte bound exceeded.")
        inventory[path.relative_to(directory).as_posix()] = {
            "size": size,
            "sha256": retention_hash(path),
        }
    return inventory


def runtime_originals(
    directory: Path, source: dict[str, Any], initial_backend_receipt: str | None = None
) -> dict[str, Any]:
    """Check referenced originals without changing or replacing producer receipts."""
    from scripts.merge_runtime_coverage import ARTIFACTS, RUNTIME_ARTIFACTS, digest, document

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    def identity(value: Any) -> None:
        require(
            isinstance(value, dict)
            and value.get("tested_checkout_commit") == source["commit"]
            and value.get("tested_checkout_tree") == source["tree"]
            and isinstance(value.get("files"), dict)
            and bool(value["files"])
            and all(
                source["files"].get(name) == checksum for name, checksum in value["files"].items()
            ),
            "Retained runtime source identity differs from the frozen candidate.",
        )

    identities = {}
    producer_nonces: set[str] = set()
    for family, receipt_name, child_tree, modes in (
        ("backend", "runtime-receipt.json", "runtime", ("positive", "negative")),
        (
            "ui",
            "aggregate-runtime-receipt.json",
            "aggregate-runtime",
            ("positive", "negative", "coverage"),
        ),
    ):
        parent = directory / "artifacts" / family
        receipt = document(parent / receipt_name)
        expected = receipt.get("source")
        identity(expected)
        require(
            isinstance(receipt.get("children"), dict) and set(receipt["children"]) == set(modes),
            "Missing retained runtime child receipt.",
        )
        nonces = set()
        for mode in modes:
            result = receipt["children"][mode]
            nonce = result.get("nonce")
            require(
                isinstance(nonce, str)
                and re.fullmatch("[0-9a-f]{32}", nonce) is not None
                and nonce not in producer_nonces,
                "Invalid retained runtime nonce.",
            )
            nonces.add(nonce)
            producer_nonces.add(nonce)
            child = parent / child_tree / mode
            artifacts = result.get("artifacts")
            require(
                isinstance(artifacts, dict)
                and set(artifacts) == (ARTIFACTS if mode == "coverage" else RUNTIME_ARTIFACTS),
                "Incomplete retained runtime child inventory.",
            )
            for name, checksum in artifacts.items():
                require(
                    Path(name).name == name and digest(child / name) == checksum,
                    "Missing or changed retained runtime child bytes.",
                )
            request, observed = (
                document(child / name) for name in ("request.json", "source-receipt.json")
            )
            require(
                request.get("nonce") == observed.get("nonce") == nonce
                and request.get("mode") == observed.get("mode") == mode
                and request.get("source")
                == observed.get("source_before")
                == observed.get("source_after")
                == expected,
                "Retained child source/nonce identity mismatch.",
            )
        identities[family] = {
            "source": expected,
            "nonces": sorted(nonces),
            "receipt_sha256": digest(parent / receipt_name),
        }
    for path in (
        "artifacts/backend/aggregate-tiny-lines-heartbeat.json",
        "artifacts/ui/aggregate-heartbeat.json",
    ):
        require((directory / path).is_file(), "Missing retained runtime parent observation.")
    merge = document(directory / "artifacts/ui/coverage-merge-receipt.json")
    identity(merge.get("source"))
    require(
        isinstance(merge.get("parent_before"), dict)
        and isinstance(merge.get("merged"), dict)
        and set(merge["parent_before"])
        == set(merge["merged"])
        == {"coverage.data", "coverage.json", "coverage.xml"},
        "Incomplete retained coverage merge inventory.",
    )
    before = Path(merge["before_directory"])
    require(
        not before.is_absolute() and ".." not in before.parts,
        "Unsafe runtime parent-before-merge path.",
    )
    for name, checksum in merge["parent_before"].items():
        require(
            Path(name).name == name
            and digest(directory / "artifacts/ui" / before / name) == checksum,
            "Missing retained parent-before-merge original.",
        )
    for name, checksum in merge["merged"].items():
        original = directory / (".coverage" if name == "coverage.data" else name)
        require(
            Path(name).name == name and digest(original) == checksum,
            "Retained merged coverage differs from its producer receipt.",
        )
    require(
        digest(directory / "artifacts/ui/merged-coverage.data") == merge["merged"]["coverage.data"],
        "Missing retained merged coverage data.",
    )
    require(
        merge.get("outer_receipt_sha256")
        == digest(directory / "artifacts/ui/aggregate-runtime-receipt.json")
        and merge.get("replay_coverage_data_sha256")
        == digest(directory / "artifacts/ui/aggregate-runtime/coverage/coverage.data")
        and merge.get("backend_runtime_receipt_sha256")
        == (initial_backend_receipt or identities["backend"]["receipt_sha256"]),
        "Retained merge receipt does not identify the original runtime inputs.",
    )
    return identities


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
    sources = (root / "dist", *(root / "artifacts" / name for name in ARCHIVE_TREES))
    if any(destination.is_relative_to(source) for source in sources):
        raise ValueError("Retention cannot recursively collect the qualification output.")
    destination.mkdir(parents=True, exist_ok=False)
    for name in (".coverage", "coverage.json", "coverage.xml", "diff-coverage.json"):
        if (root / name).is_file():
            shutil.copy2(root / name, destination / name)
    if (root / "dist").is_dir():
        shutil.copytree(root / "dist", destination / "dist", symlinks=True)
    for name in ARCHIVE_TREES:
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

    def __init__(
        self,
        root: Path,
        output: Path,
        report: dict[str, Any],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root, self.output, self.report = root, output, report
        self.clock = clock
        self.current: subprocess.Popen[bytes] | None = None
        self.cancelled: int | None = None
        self.interrupted = False
        self.cleanup_timeout = 30.0

    def save(self) -> None:
        temporary = self.output / "report.tmp"
        temporary.write_text(json.dumps(self.report, indent=2) + "\n")
        temporary.replace(self.output / "report.json")
        (self.output / "summary.md").write_text(summary(self.report))

    def signal_group(self, value: int) -> bool:
        process = self.current
        if process is None:
            return False
        if process.pid <= 1 or process.pid == os.getpgrp():
            raise ValueError("Refuse to signal an ambient or invalid process group.")
        try:
            os.killpg(process.pid, value)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            if sys.platform != "darwin":
                raise
            # Match runtime.signal_process_group: only confirmed ESRCH can
            # explain XNU's exiting-group EPERM; a live/denied group is failure.
            for _ in range(5):
                time.sleep(0.01)
                # Reap this owned leader; only the group probe establishes absence.
                process.poll()
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    continue
                raise
            raise

    def stop(self, signum: int, frame: FrameType | None) -> None:
        if self.cancelled is not None:
            return
        self.cancelled = signum
        self.report["cancel_signal"] = signum
        if self.current is not None:
            self.signal_group(signal.SIGCONT)
            self.interrupted = self.signal_group(signal.SIGINT)

    def unchanged(self) -> None:
        if snapshot(self.root) != self.report["source"]:
            raise ValueError("Tracked candidate inputs changed during qualification.")

    def verify_retained(self) -> None:
        for retained in self.report.get("runtime_snapshots", []):
            directory = self.output / retained["directory"]
            inventory = retained_inventory(directory)
            if inventory != retained["inventory"]:
                raise ValueError("Previously retained runtime snapshot is missing or changed.")

    def retain_runtime(self, stage: Stage, gate: dict[str, Any]) -> None:
        """Exclusive snapshots are taken only after every owned writer drained."""
        name = "runtime-controls-1" if stage.name == "runtime-controls" else stage.name
        directory = self.output / "retained" / name
        if "pid" in gate and gate.get("group_drained") is not True:
            raise ValueError("Runtime evidence writers have not drained; retention failed.")
        regular_files(directory, self.output)
        directory.mkdir(parents=True, exist_ok=False)
        originals = directory / "originals"
        originals.mkdir()
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "stage": stage.name,
            "status": gate["status"],
            "gate": dict(gate),
            "source": self.report["source"],
            "bounds": {
                "files": RETENTION_MAX_FILES,
                "traversal_entries": RETENTION_MAX_FILES,
                "bytes": RETENTION_MAX_BYTES,
            },
            "complete": False,
            "files": {},
        }
        failure: Exception | None = None
        try:
            sources = [
                (path, path.relative_to(self.root))
                for name in (
                    ".coverage",
                    "coverage.json",
                    "coverage.xml",
                    "diff-coverage.json",
                    "artifacts/backend",
                    "artifacts/ui",
                    "artifacts/resource-creation",
                )
                for path in regular_files(self.root / name, self.root)
            ]
            campaign_paths = {
                self.output / "cases.xml",
                *(
                    self.output / (gate["name"] + suffix)
                    for gate in self.report["gates"]
                    for suffix in (".log", ".xml")
                ),
            }
            sources.extend(
                (file, Path("campaign") / file.name)
                for path in sorted(campaign_paths)
                for file in regular_files(path, self.output)
            )
            if (
                len(sources) > RETENTION_MAX_FILES
                or sum(path.stat().st_size for path, _ in sources) > RETENTION_MAX_BYTES
            ):
                raise ValueError("Runtime snapshot exceeds its retention bounds.")
            copied_bytes = 0
            for path, relative in sources:
                regular_files(path, self.root if path.is_relative_to(self.root) else self.output)
                size = path.stat().st_size
                copied_bytes += size
                if copied_bytes > RETENTION_MAX_BYTES:
                    raise ValueError("Original runtime evidence exceeded its byte bound.")
                copied = originals / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                with path.open("rb") as source, copied.open("xb") as target:
                    remaining = size
                    while remaining:
                        block = source.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise ValueError("Original runtime evidence shrank during retention.")
                        target.write(block)
                        remaining -= len(block)
                    if source.read(1):
                        raise ValueError("Original runtime evidence grew during retention.")
                checksum = retention_hash(copied)
                if checksum != retention_hash(path):
                    raise ValueError("Original runtime evidence changed while retaining it.")
                manifest["files"][relative.as_posix()] = {
                    "original_path": str(path),
                    "size": copied.stat().st_size,
                    "sha256": checksum,
                    "status": "retained_original",
                }
            earlier = self.report.get("runtime_snapshots", [])
            initial_backend_receipt = None
            if stage.name.startswith("contracts-"):
                if (
                    not earlier
                    or earlier[0]["stage"] != "runtime-controls"
                    or not earlier[0]["complete"]
                ):
                    raise ValueError("Repeated contracts require the retained initial controls.")
                initial_backend_receipt = earlier[0]["runtime_identities"]["backend"][
                    "receipt_sha256"
                ]
            manifest["runtime_identities"] = runtime_originals(
                originals, self.report["source"], initial_backend_receipt
            )
            if stage.name.startswith("contracts-"):
                old = {
                    nonce
                    for record in earlier
                    for family in ("backend", "ui")
                    for nonce in record.get("runtime_identities", {})
                    .get(family, {})
                    .get("nonces", [])
                }
                new = manifest["runtime_identities"]["backend"]["nonces"]
                if old & set(new):
                    raise ValueError("Repeated contracts did not produce fresh backend controls.")
            required_junit = (
                "cases.xml" if stage.name == "runtime-controls" else stage.name + ".xml"
            )
            if not (originals / "campaign" / required_junit).is_file():
                raise ValueError("Missing original stage JUnit evidence.")
            manifest["complete"] = True
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            failure = error
            manifest["retention_error"] = f"{type(error).__name__}: {error}"
        finally:
            (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            self.report.setdefault("runtime_snapshots", []).append(
                {
                    "stage": stage.name,
                    "directory": directory.relative_to(self.output).as_posix(),
                    "complete": manifest["complete"],
                    "status": gate["status"],
                    "runtime_identities": manifest.get("runtime_identities", {}),
                    "inventory": retained_inventory(directory),
                }
            )
        if failure is not None:
            raise ValueError(f"Runtime originals retention failed: {failure}") from failure

    def drain(self, gate: dict[str, Any]) -> None:
        process = self.current
        if process is None:
            return
        gate.update(
            group_cleanup_attempted=True,
            group_drained=False,
            cleanup_timeout_seconds=self.cleanup_timeout,
        )
        if not self.interrupted and self.signal_group(0):
            self.signal_group(signal.SIGCONT)
            self.interrupted = self.signal_group(signal.SIGINT)
        deadline = self.clock() + self.cleanup_timeout
        leader_exited: float | None = None
        while self.signal_group(0):
            now = self.clock()
            if process.poll() is not None:
                leader_exited = now if leader_exited is None else leader_exited
                if now - leader_exited >= SIGNAL_GRACE_SECONDS:
                    break
            if now >= deadline:
                break
            time.sleep(0.02)
        if self.signal_group(0):
            gate["forced_group_kill"] = self.signal_group(signal.SIGKILL)
            deadline = self.clock() + REAP_GRACE_SECONDS
            while self.signal_group(0) and self.clock() < deadline:
                process.poll()
                time.sleep(0.02)
        process.wait(timeout=REAP_GRACE_SECONDS)
        gate.update(process_reaped=True, group_drained=not self.signal_group(0))
        if not gate["group_drained"]:
            raise RuntimeError(
                "Owned process group remains after bounded cleanup; qualification failed."
            )

    def wait(self, timeout: int, gate: dict[str, Any]) -> int:
        assert self.current is not None
        deadline = self.clock() + timeout
        while True:
            try:
                code = self.current.wait(timeout=0.1)
                self.drain(gate)
                return code
            except subprocess.TimeoutExpired:
                if self.cancelled is not None or self.clock() >= deadline:
                    gate["timed_out"] = self.cancelled is None
                    gate["reason"] = (
                        "Command deadline exceeded; original retained."
                        if self.cancelled is None
                        else "Cancelled; owned group cleanup required."
                    )
                    self.drain(gate)
                    assert self.current.returncode is not None
                    return self.current.returncode

    def run(self, stage: Stage) -> None:
        self.unchanged()
        if self.cancelled is not None:
            raise InterruptedError("Qualification cancelled before the next command.")
        gate = next(item for item in self.report["gates"] if item["name"] == stage.name)
        gate.update(
            status="running",
            reason="Local command started.",
            command=list(stage.command),
            started=time.time(),
        )
        self.save()
        started = time.monotonic()
        self.interrupted = False
        self.cleanup_timeout = stage.cleanup_timeout
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
                if code == 0
                and self.cancelled is None
                and not gate.get("timed_out")
                and not gate.get("forced_group_kill")
                else "failed"
            )
        except BaseException:
            gate["status"] = "failed"
            if not gate.get("group_cleanup_attempted"):
                self.drain(gate)
            if self.current is not None:
                gate["process_reaped"] = self.current.poll() is not None
            raise
        finally:
            self.current = None
            gate.update(elapsed_seconds=time.monotonic() - started, log=path.name)
            if gate["reason"] == "Local command started.":
                gate["reason"] = f"Local command {gate['status']}; see its retained log."
            try:
                if stage.name == "runtime-controls" or re.fullmatch(r"contracts-[23]", stage.name):
                    self.retain_runtime(stage, gate)
                self.verify_retained()
            except (OSError, ValueError) as error:
                gate.update(status="failed", retention_error=f"{type(error).__name__}: {error}")
                self.report["retention_error"] = gate["retention_error"]
                raise
            finally:
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
        "private-access",
        "types",
        "startup",
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
        if (
            runner is not None
            and runner.cancelled is not None
            and "retention_error" not in runner.report
        ):
            assert report is not None
            report["status"] = "cancelled"
            code = 128 + runner.cancelled
    finally:
        try:
            if report is not None and runner is not None:
                try:
                    if not args.collect_only:
                        archive(root, output / "after")
                    runner.verify_retained()
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
                if runner.cancelled is not None and "retention_error" not in report:
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
