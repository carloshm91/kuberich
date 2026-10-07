"""Build artifact-linked locked/fresh runtime evidence; never publish packages.

Run as ``uv run python -m scripts.check_supply_chain`` after ``uv build``.
"""

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import tomllib
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.supply_chain import (
    check_actions,
    check_audit,
    check_policy,
    digest,
    license_inventory,
    runtime_packages,
    validate_sbom,
)

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("locked", "fresh")
INPUT_FILES = (
    "pyproject.toml",
    "uv.lock",
    "scripts/supply_chain_policy.json",
    "scripts/check_supply_chain.py",
    "scripts/supply_chain.py",
    "scripts/dependency_inventory.py",
    ".github/workflows/quality.yml",
    ".github/workflows/repository.yml",
)


def run(command: list[str], work: Path, log: Path, *, allowed: tuple[int, ...] = (0,)) -> int:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "PIP_", "PYTHON", "KUBETROL_", "TEXTUAL", "PIP_AUDIT_"))
        and key != "VIRTUAL_ENV"
    }
    environment.update(
        {
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_CACHE_DIR": str(work / "cache"),
            "PIP_CONFIG_FILE": os.devnull,
        }
    )
    with log.open("a", encoding="utf-8") as output:
        output.write(json.dumps(command) + "\n")
        output.flush()
        process = subprocess.Popen(
            command, cwd=work, env=environment, stdout=output, stderr=output, start_new_session=True
        )
        try:
            code = process.wait(timeout=240)
        except BaseException:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    if code not in allowed:
        raise ValueError(f"Supply-chain subprocess failed (exit {code}); see {log.name}")
    return code


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    digest(path)
    return json.loads(path.read_text(encoding="utf-8"))


def selected_requirements(text: str, python: str) -> dict[str, str]:
    environment = {key: str(value) for key, value in default_environment().items()}
    environment["python_full_version"] = python
    environment["python_version"] = ".".join(python.split(".")[:2])
    result: dict[str, str] = {}
    for line in text.replace("\\\n", " ").splitlines():
        value = line.split(" --hash=", 1)[0].strip()
        if not value:
            continue
        requirement = Requirement(value)
        pins = list(requirement.specifier)
        if requirement.url or len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
            raise ValueError("Runtime export must contain exact registry pins")
        if requirement.marker is None or requirement.marker.evaluate(environment):
            name = str(canonicalize_name(requirement.name))
            if name in result:
                raise ValueError("Duplicate active runtime lock entry")
            result[name] = pins[0].version
    if not result:
        raise ValueError("Empty locked runtime export")
    return result


def notices_text(licenses: dict[str, Any]) -> str:
    sections = [
        "Kubetrol third-party runtime notices\n",
        "These dependencies are separately installed, not relicensed by Kubetrol.\n",
        "Pyte 0.8.2 is unmodified, dynamically imported LGPL-3.0-only code.\n",
        "Preserve its license and corresponding source/replacement rights in standalone delivery.\n",
    ]
    for name, item in sorted(licenses.items()):
        sections.append(f"\n===== {name} {item['version']} ({item['expression']}) =====\n")
        for notice in item["notices"]:
            content = base64.b64decode(notice["content_base64"], validate=True)
            sections.append(f"\n--- {notice['file']} SHA256 {notice['sha256']} ---\n")
            sections.append(content.decode("utf-8") + "\n")
    return "".join(sections)


def attach_artifacts(
    bom: dict[str, Any], artifacts: dict[str, str], lock_digest: str, scope: str
) -> None:
    root = bom["metadata"]["component"]
    wheel = next(value for name, value in artifacts.items() if name.endswith(".whl"))
    root["hashes"] = [{"alg": "SHA-256", "content": wheel}]
    root.setdefault("properties", []).extend(
        [
            {"name": f"kubetrol:artifact:{name}:sha256", "value": value}
            for name, value in sorted(artifacts.items())
        ]
        + [
            {"name": "kubetrol:uv-lock:sha256", "value": lock_digest},
            {"name": "kubetrol:runtime-selection", "value": scope},
        ]
    )


def check_attachment(
    bom: dict[str, Any],
    artifacts: dict[str, str],
    lock_digest: str,
    scope: str,
    project: dict[str, Any],
) -> None:
    root = bom["metadata"]["component"]
    if (
        root.get("name") != "kubetrol"
        or root.get("version") != project["version"]
        or root.get("type") != "application"
    ):
        raise ValueError("SBOM application identity mismatch")
    wheel = next(value for name, value in artifacts.items() if name.endswith(".whl"))
    if root.get("hashes") != [{"alg": "SHA-256", "content": wheel}]:
        raise ValueError("SBOM wheel digest mismatch")
    expected = {f"kubetrol:artifact:{name}:sha256": value for name, value in artifacts.items()}
    expected.update({"kubetrol:uv-lock:sha256": lock_digest, "kubetrol:runtime-selection": scope})
    properties = {item["name"]: item["value"] for item in root.get("properties", [])}
    if any(properties.get(key) != value for key, value in expected.items()):
        raise ValueError("SBOM artifact/lock linkage mismatch")


def artifact_inventory(directory: Path) -> dict[str, str]:
    files = sorted(directory.glob("*.whl")) + sorted(directory.glob("*.tar.gz"))
    if len(files) != 2 or sum(path.suffix == ".whl" for path in files) != 1:
        raise ValueError("Supply exactly one built wheel and one source archive")
    return {path.name: digest(path) for path in files}


def verify(output: Path, dist: Path, root: Path = ROOT) -> dict[str, Any]:
    manifest = read_json(output / "provenance.json")
    if manifest.get("schema_version") != 1 or manifest.get("scopes") != list(SCOPES):
        raise ValueError("Complete locked/fresh evidence required")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")):
        raise ValueError("Exact source commit is required")
    generated = datetime.fromisoformat(manifest["generated_at"])
    if (
        generated.tzinfo is None
        or not 0 <= (datetime.now(UTC) - generated).total_seconds() <= 86400
    ):
        raise ValueError("Audit evidence must be refreshed within 24 hours")
    artifacts = artifact_inventory(dist)
    if manifest.get("artifacts") != artifacts:
        raise ValueError("Candidate artifact digest mismatch")
    inputs = {name: digest(root / name) for name in INPUT_FILES}
    if manifest.get("inputs") != inputs:
        raise ValueError("Source policy/lock digest mismatch")
    expected_files = {"runtime.txt"} | {
        f"{scope}-{name}"
        for scope in SCOPES
        for name in ("inventory.json", "audit.json", "sbom.json", "NOTICES.txt")
    }
    if manifest.get("reports", {}).keys() != expected_files:
        raise ValueError("Complete security report inventory required")
    for name, value in manifest["reports"].items():
        if digest(output / name) != value:
            raise ValueError("Security report digest mismatch")
    policy = read_json(root / "scripts/supply_chain_policy.json")
    today = datetime.now(UTC).date()
    lock = tomllib.loads((root / "uv.lock").read_text())
    pyte = next(package for package in lock["package"] if package["name"] == "pyte")
    if (
        manifest.get("pyte_corresponding_source") != pyte["sdist"]
        or manifest.get("attested") is not False
    ):
        raise ValueError("Invalid dependency source/attestation evidence")
    check_policy(policy, today)
    check_actions(root / ".github/workflows")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    results = {}
    for scope in SCOPES:
        inventory = read_json(output / f"{scope}-inventory.json")
        expected = runtime_packages(inventory, project)
        if scope == "locked" and expected != selected_requirements(
            (output / "runtime.txt").read_text(), inventory["python"]
        ):
            raise ValueError("Installed runtime differs from selected lock")
        audit = read_json(output / f"{scope}-audit.json")
        accepted = check_audit(audit, expected, policy, today)
        findings = sum(len(item["vulns"]) for item in audit["dependencies"])
        if manifest.get("audit_exit_codes", {}).get(scope) != int(findings > 0):
            raise ValueError("Audit exit status contradicts its complete findings")
        bom = read_json(output / f"{scope}-sbom.json")
        validate_sbom(bom)
        check_attachment(bom, artifacts, inputs["uv.lock"], scope, project)
        licenses = license_inventory(inventory, bom, policy)
        if (output / f"{scope}-NOTICES.txt").read_text() != notices_text(licenses):
            raise ValueError("Original license notice composition mismatch")
        results[scope] = {
            "dependencies": len(expected),
            "accepted_exceptions": accepted,
            "python": inventory["python"],
        }
    return results


def generate(output: Path, dist: Path, root: Path = ROOT) -> dict[str, Any]:
    output = output.resolve()
    dist = dist.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = artifact_inventory(dist)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    policy = read_json(root / "scripts/supply_chain_policy.json")
    check_policy(policy, datetime.now(UTC).date())
    check_actions(root / ".github/workflows")
    inputs = {name: digest(root / name) for name in INPUT_FILES}
    wheel = dist / next(name for name in artifacts if name.endswith(".whl"))
    log = output / "commands.log"
    audit_codes = {}
    with tempfile.TemporaryDirectory(prefix="kubetrol-supply-chain-") as temporary:
        work = Path(temporary)
        run(
            [
                "uv",
                "export",
                "--project",
                str(root),
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--no-annotate",
                "--no-header",
                "--quiet",
                "--output-file",
                str(output / "runtime.txt"),
            ],
            work,
            log,
        )
        for scope in SCOPES:
            python = work / scope / "bin/python"
            run(["uv", "venv", "--python", sys.executable, str(python.parent.parent)], work, log)
            if scope == "locked":
                run(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str(python),
                        "--require-hashes",
                        "--only-binary",
                        ":all:",
                        "-r",
                        str(output / "runtime.txt"),
                    ],
                    work,
                    log,
                )
            command = ["uv", "pip", "install", "--python", str(python), "--only-binary", ":all:"]
            if scope == "locked":
                command.append("--no-deps")
            run([*command, str(wheel)], work, log)
            run(["uv", "pip", "check", "--python", str(python)], work, log)
            run([str(python), "-I", "-m", "kubetrol", "--version"], work, log)
            inventory_file = output / f"{scope}-inventory.json"
            run(
                [
                    str(python),
                    "-I",
                    str(root / "scripts/dependency_inventory.py"),
                    str(inventory_file),
                ],
                work,
                log,
            )
            inventory = read_json(inventory_file)
            expected = runtime_packages(inventory, project)
            if scope == "locked" and expected != selected_requirements(
                (output / "runtime.txt").read_text(), inventory["python"]
            ):
                raise ValueError("Installed runtime differs from selected lock")
            # Audit exact versions without resolving/importing them in the dev environment.
            requirements = work / f"{scope}.txt"
            requirements.write_text(
                "".join(f"{name}=={version}\n" for name, version in sorted(expected.items()))
            )
            audit_file = output / f"{scope}-audit.json"
            code = run(
                [
                    sys.executable,
                    "-m",
                    "pip_audit",
                    "--strict",
                    "--no-deps",
                    "--disable-pip",
                    "-r",
                    str(requirements),
                    "--format",
                    "json",
                    "--progress-spinner",
                    "off",
                    "--timeout",
                    "15",
                    "--cache-dir",
                    str(work / "advisory-cache"),
                    "--output",
                    str(audit_file),
                ],
                work,
                log,
                allowed=(0, 1),
            )
            audit = read_json(audit_file)
            check_audit(audit, expected, policy, datetime.now(UTC).date())
            findings = sum(len(item["vulns"]) for item in audit["dependencies"])
            if code != int(findings > 0):
                raise ValueError("Audit exit status contradicts its complete findings")
            audit_codes[scope] = code
            bom_file = output / f"{scope}-sbom.json"
            run(
                [
                    sys.executable,
                    "-m",
                    "cyclonedx_py",
                    "environment",
                    str(python),
                    "--pyproject",
                    str(root / "pyproject.toml"),
                    "--gather-license-texts",
                    "--output-reproducible",
                    "--spec-version",
                    "1.6",
                    "--validate",
                    "--output-file",
                    str(bom_file),
                ],
                work,
                log,
            )
            bom = read_json(bom_file)
            attach_artifacts(bom, artifacts, inputs["uv.lock"], scope)
            validate_sbom(bom)
            licenses = license_inventory(inventory, bom, policy)
            write_json(bom_file, bom)
            (output / f"{scope}-NOTICES.txt").write_text(notices_text(licenses), encoding="utf-8")
    # These are unsigned, locally measured provenance sidecars; D02 owns attestation.
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()
    lock = tomllib.loads((root / "uv.lock").read_text())
    pyte = next(package for package in lock["package"] if package["name"] == "pyte")
    report_files = ["runtime.txt"] + [
        f"{scope}-{name}"
        for scope in SCOPES
        for name in ("inventory.json", "audit.json", "sbom.json", "NOTICES.txt")
    ]
    write_json(
        output / "provenance.json",
        {
            "schema_version": 1,
            "source_commit": commit,
            "generated_at": datetime.now(UTC).isoformat(),
            "scopes": list(SCOPES),
            "inputs": inputs,
            "artifacts": artifacts,
            "reports": {name: digest(output / name) for name in report_files},
            "audit_exit_codes": audit_codes,
            "tools": {
                name: version(name)
                for name in ("pip-audit", "cyclonedx-bom", "cyclonedx-python-lib")
            },
            "pyte_corresponding_source": pyte["sdist"],
            "attested": False,
        },
    )
    return verify(output, dist, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/security")
    parser.add_argument(
        "--verify", action="store_true", help="Recheck retained evidence without network access"
    )
    arguments = parser.parse_args()
    try:
        results = (
            verify(arguments.output, arguments.dist)
            if arguments.verify
            else generate(arguments.output, arguments.dist)
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Supply-chain gate failed: {error}", file=sys.stderr)
        return 1
    print("Supply-chain gate passed: " + json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
