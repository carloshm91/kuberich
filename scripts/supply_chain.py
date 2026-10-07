"""Fail-closed dependency, license, audit and artifact-evidence decisions.

These are development/release gates, outside the installed application's code.
"""

import base64
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator
from license_expression import get_spdx_licensing
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Evidence must be a regular, non-symlink file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_map(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(inventory.get("packages"), list) or not inventory["packages"]:
        raise ValueError("Missing installed dependency inventory")
    for package in inventory["packages"]:
        name = str(canonicalize_name(package["name"]))
        if name in result or not package.get("version"):
            raise ValueError("Duplicate or incomplete installed dependency")
        result[name] = package
    return result


def runtime_packages(inventory: dict[str, Any], project: dict[str, Any]) -> dict[str, str]:
    packages = package_map(inventory)
    root = packages.pop("kubetrol", None)
    if root is None or root["version"] != project["version"]:
        raise ValueError("The built application must be installed")
    environment = {key: str(value) for key, value in default_environment().items()}
    environment["python_full_version"] = inventory["python"]
    environment["python_version"] = ".".join(inventory["python"].split(".")[:2])
    requirements = [Requirement(value) for value in root["requires"]]
    declared = {str(Requirement(value)) for value in project["dependencies"]}
    if declared != {str(value) for value in requirements}:
        raise ValueError("Installed root requirements differ from project metadata")
    pending = [
        value
        for value in requirements
        if value.marker is None or value.marker.evaluate(environment)
    ]
    visited: set[tuple[str, tuple[str, ...]]] = set()
    reached = set()
    while pending:
        requirement = pending.pop()
        name = str(canonicalize_name(requirement.name))
        if requirement.url or name not in packages:
            raise ValueError("Runtime inventory has an unavailable or direct-URL dependency")
        package = packages[name]
        if not requirement.specifier.contains(package["version"], prereleases=True):
            raise ValueError("Installed dependency violates its requirement")
        key = name, tuple(sorted(requirement.extras))
        reached.add(name)
        if key in visited:
            continue
        visited.add(key)
        for value in package["requires"]:
            child = Requirement(value)
            if child.marker is None or any(
                child.marker.evaluate({**environment, "extra": extra})
                for extra in {"", *requirement.extras}
            ):
                pending.append(child)
    if reached != packages.keys():
        raise ValueError("Runtime inventory includes unrelated or missing components")
    return {name: package["version"] for name, package in packages.items()}


def check_policy(policy: dict[str, Any], today: date) -> list[dict[str, str]]:
    if policy.get("schema_version") != 1:
        raise ValueError("Unsupported supply-chain policy")
    expressions = policy.get("approved_license_expressions")
    if (
        not isinstance(expressions, list)
        or not expressions
        or len(set(expressions)) != len(expressions)
    ):
        raise ValueError("Explicit reviewed license expressions are required")
    licensing = get_spdx_licensing()
    for expression in expressions:
        if licensing.validate(expression, strict=True).errors:
            raise ValueError("Invalid SPDX license policy")
    exceptions = policy.get("vulnerability_exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("Explicit vulnerability exception inventory is required")
    seen = set()
    for exception in exceptions:
        required = {"package", "version", "vulnerability", "issue", "owner", "rationale", "expires"}
        if not isinstance(exception, dict) or exception.keys() != required:
            raise ValueError("Incomplete vulnerability exception")
        if any(not isinstance(value, str) or not value.strip() for value in exception.values()):
            raise ValueError("Empty vulnerability exception field")
        if not re.fullmatch(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", exception["package"]):
            raise ValueError("Exceptions require one exact normalized package")
        if any(character in exception["version"] for character in "*<>=!, "):
            raise ValueError("Exceptions require one exact version")
        Version(exception["version"])
        if not re.fullmatch(
            r"(?:CVE-\d{4}-\d+|GHSA-[a-z0-9-]+|PYSEC-\d{4}-\d+)", exception["vulnerability"]
        ):
            raise ValueError("Exceptions require one specific vulnerability")
        if not re.fullmatch(
            r"https://github.com/carloshm91/kubetrol/issues/[1-9]\d*", exception["issue"]
        ):
            raise ValueError("Exception needs its tracked repository issue")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", exception["owner"]):
            raise ValueError("Exception needs an accountable GitHub owner")
        if len(exception["rationale"].strip()) < 20:
            raise ValueError("Exception requires a mitigation rationale")
        expiry = date.fromisoformat(exception["expires"])
        if not 0 < (expiry - today).days <= 90:
            raise ValueError("Vulnerability exception expired or exceeds 90 days")
        key = exception["package"], exception["version"], exception["vulnerability"]
        if key in seen:
            raise ValueError("Duplicate vulnerability exception")
        seen.add(key)
    return exceptions


def check_audit(
    report: dict[str, Any], expected: dict[str, str], policy: dict[str, Any], today: date
) -> list[dict[str, str]]:
    exceptions = check_policy(policy, today)
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("Missing audit dependency evidence")
    found = {}
    accepted = []
    for dependency in dependencies:
        name = str(canonicalize_name(dependency["name"]))
        if (
            name in found
            or dependency.get("skip_reason")
            or not isinstance(dependency.get("vulns"), list)
        ):
            raise ValueError("Incomplete, skipped or duplicate audit dependency")
        found[name] = dependency.get("version")
        for vulnerability in dependency["vulns"]:
            identifier = vulnerability.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("Malformed vulnerability finding")
            aliases = vulnerability.get("aliases", [])
            if not isinstance(aliases, list) or not all(
                isinstance(value, str) for value in aliases
            ):
                raise ValueError("Malformed vulnerability aliases")
            matches = [
                exception
                for exception in exceptions
                if exception["package"] == name
                and exception["version"] == found[name]
                and exception["vulnerability"] in {identifier, *aliases}
            ]
            if len(matches) != 1:
                raise ValueError(f"Unresolved vulnerability: {name} {found[name]} {identifier}")
            accepted.append(matches[0])
    if found != expected:
        raise ValueError("Audit does not cover the exact runtime inventory")
    return accepted


def validate_sbom(bom: dict[str, Any]) -> None:
    if bom.get("specVersion") != "1.6" or bom.get("bomFormat") != "CycloneDX":
        raise ValueError("CycloneDX 1.6 SBOM required")
    error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(json.dumps(bom))
    if error is not None:
        raise ValueError("SBOM schema validation failed")


def license_inventory(
    inventory: dict[str, Any], bom: dict[str, Any], policy: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    packages = package_map(inventory)
    packages.pop("kubetrol")
    components = {}
    for component in bom.get("components", []):
        name = str(canonicalize_name(component["name"]))
        if name in components:
            raise ValueError("Duplicate SBOM component")
        components[name] = component
    if components.keys() != packages.keys():
        raise ValueError("SBOM does not match installed runtime components")
    output: dict[str, dict[str, Any]] = {}
    for name, package in packages.items():
        component = components[name]
        if component.get("version") != package["version"]:
            raise ValueError("SBOM component version mismatch")
        licenses = component.get("licenses", [])
        expression = package.get("license_expression")
        if not expression:
            identifiers = sorted(
                {value["license"]["id"] for value in licenses if value.get("license", {}).get("id")}
            )
            expressions = [value["expression"] for value in licenses if value.get("expression")]
            expression = expressions[0] if len(expressions) == 1 else " AND ".join(identifiers)
        if not expression:
            legacy = policy["legacy_licenses"].get(name, {})
            if legacy.get("version") != package["version"] or legacy.get("declared") != package.get(
                "license"
            ):
                raise ValueError(f"Unreviewed legacy license: {name}")
            expression = legacy.get("expression")
        if expression not in policy["approved_license_expressions"]:
            raise ValueError(f"Unapproved dependency license: {name}")
        notices = package.get("notices")
        if not isinstance(notices, list) or not notices:
            raise ValueError(f"Missing original dependency notices: {name}")
        for notice in notices:
            content = base64.b64decode(notice["content_base64"], validate=True)
            if not content or hashlib.sha256(content).hexdigest() != notice["sha256"]:
                raise ValueError("Dependency notice digest mismatch")
        output[name] = {"version": package["version"], "expression": expression, "notices": notices}
    if (
        output.get("pyte", {}).get("expression") != "LGPL-3.0-only"
        or output["pyte"]["version"] != "0.8.2"
    ):
        raise ValueError("Pinned Pyte LGPL inventory requires explicit review")
    if "wcwidth" not in output:
        raise ValueError("Pyte width dependency must be inventoried")
    return output


def check_actions(directory: Path) -> None:
    workflows = list(directory.glob("*.yml")) + list(directory.glob("*.yaml"))
    if not workflows:
        raise ValueError("Missing required workflow inventory")
    for path in workflows:
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            uses = [job["uses"]] if "uses" in job else []
            uses += [step["uses"] for step in job.get("steps", []) if "uses" in step]
            for action in uses:
                if not isinstance(action, str) or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}", action
                ):
                    raise ValueError("Every external Action/workflow must be pinned by commit")
