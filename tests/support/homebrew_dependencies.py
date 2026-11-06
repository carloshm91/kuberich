"""Separately bounded core-dependency setup on an owned ephemeral Actions runner."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from scripts.homebrew import RUNTIME_FORMULAE
from tests.support.distribution import ROOT, clean_environment, run

RECEIPT = ROOT / "artifacts/installation/dependencies.json"
DEPENDENCY_TIMEOUT = 75 * 60
IDENTITY_KEYS = (
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_JOB",
    "GITHUB_SHA",
    "RUNNER_NAME",
    "RUNNER_OS",
    "RUNNER_ARCH",
)
INPUTS = ("pyproject.toml", "uv.lock", "scripts/homebrew.py", __file__)


def owned_identity() -> dict[str, str]:
    """Refuse personal Homebrew before inspecting or modifying its installation."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("RUNNER_TEMP"):
        raise ValueError("Homebrew dependency preparation requires an owned Actions runner")
    identity = {name: os.environ.get(name, "") for name in IDENTITY_KEYS}
    if not all(identity.values()):
        raise ValueError("Missing exact workflow job identity")
    if re.fullmatch(r"[0-9a-f]{40}", identity["GITHUB_SHA"]) is None:
        raise ValueError("Missing valid workflow source commit")
    return identity


def source_identity() -> dict[str, object]:
    if run(["git", "status", "--porcelain", "--untracked-files=no"], ROOT).stdout.strip():
        raise ValueError("Homebrew qualification requires clean committed source")
    return {
        "commit": run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip(),
        "inputs": {
            str(Path(name).resolve().relative_to(ROOT)): hashlib.sha256(
                (ROOT / name).read_bytes()
            ).hexdigest()
            for name in INPUTS
        },
    }


def installed_formulae(output: str) -> set[str]:
    return {line.split()[0] for line in output.splitlines() if line.split()}


def prepare_dependencies(brew: str, output: Path = RECEIPT) -> dict[str, object]:
    """Record preinstalled state, real setup time and failures without a cold claim."""
    identity = owned_identity()
    source = source_identity()
    if source["commit"] != identity["GITHUB_SHA"]:
        raise ValueError("Checked-out source differs from the workflow commit")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Dependency evidence must use a fresh output path")
    outside = Path(os.environ["RUNNER_TEMP"])
    environment = clean_environment(outside)
    environment.update(
        HOMEBREW_NO_ANALYTICS="1",
        HOMEBREW_NO_AUTO_UPDATE="1",
        HOMEBREW_NO_INSTALL_CLEANUP="1",
        HOMEBREW_NO_AUTOREMOVE="1",
    )
    commands = []
    receipt: dict[str, object] = {
        "result": "failed",
        "runner": identity,
        "source": source,
        "brew": str(Path(brew).absolute()),
        "required_formulae": list(RUNTIME_FORMULAE),
        "dependency_timeout_seconds": DEPENDENCY_TIMEOUT,
        "application_install_included": False,
        "end_to_end_cold_install": False,
        "commands": commands,
    }

    def write() -> None:
        output.write_text(json.dumps(receipt, indent=2) + "\n")

    def execute(arguments: list[str], timeout: int = 60) -> str:
        command = [brew, *arguments]
        record: dict[str, object] = {"command": command, "timeout_seconds": timeout}
        commands.append(record)
        started = time.monotonic()
        try:
            result = run(command, outside, timeout, check=False, environment=environment)
            record.update(exit=result.returncode, stdout=result.stdout, stderr=result.stderr)
            if result.returncode:
                raise subprocess.CalledProcessError(
                    result.returncode, command, result.stdout, result.stderr
                )
            return result.stdout
        except BaseException as error:
            record["error"] = type(error).__name__
            if isinstance(error, subprocess.TimeoutExpired):
                for name in ("stdout", "stderr"):
                    value = getattr(error, name)
                    record[name] = (
                        value.decode(errors="replace") if isinstance(value, bytes) else value
                    )
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            write()

    started = time.monotonic()
    try:
        receipt["prefix"] = execute(["--prefix"]).strip()
        receipt["brew_version"] = execute(["--version"])
        before = execute(["list", "--versions", "--formula"])
        receipt["installed_before"] = before
        receipt["missing_before"] = sorted(set(RUNTIME_FORMULAE) - installed_formulae(before))
        # Core formulae come from the same declaration used to render the candidate.
        # A preinstalled runner remains explicitly preinstalled; no cache is purged.
        execute(["install", "--formula", *RUNTIME_FORMULAE], DEPENDENCY_TIMEOUT)
        after = execute(["list", "--versions", "--formula"])
        receipt["installed_after"] = after
        if not set(RUNTIME_FORMULAE) <= installed_formulae(after):
            raise ValueError("Required Homebrew dependencies are missing after preparation")
        if source_identity() != source:
            raise ValueError("Source changed during Homebrew dependency preparation")
        receipt["result"] = "passed"
        return receipt
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write()


def prepared_dependencies(brew: str, receipt_path: Path = RECEIPT) -> dict[str, object]:
    """Bind application tests to successful preparation on this exact source/job."""
    identity = owned_identity()
    source = source_identity()
    if source["commit"] != identity["GITHUB_SHA"]:
        raise ValueError("Checked-out source differs from the workflow commit")
    receipt = json.loads(receipt_path.read_text())
    prefix = run([brew, "--prefix"], Path(os.environ["RUNNER_TEMP"])).stdout.strip()
    if (
        receipt.get("result") != "passed"
        or receipt.get("runner") != identity
        or receipt.get("source") != source
        or receipt.get("brew") != str(Path(brew).absolute())
        or receipt.get("prefix") != prefix
        or receipt.get("required_formulae") != list(RUNTIME_FORMULAE)
        or not set(RUNTIME_FORMULAE) <= installed_formulae(receipt.get("installed_after", ""))
        or receipt.get("application_install_included") is not False
        or receipt.get("end_to_end_cold_install") is not False
    ):
        raise ValueError("Homebrew dependency evidence does not match this source and runner")
    return receipt


def main() -> None:
    owned_identity()
    brew = shutil.which("brew")
    if brew is None:
        raise ValueError("Homebrew is required on the owned runner")
    prepare_dependencies(brew)


if __name__ == "__main__":
    main()
