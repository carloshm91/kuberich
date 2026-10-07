"""Real gate decisions reject incomplete audits, broad waivers and floating Actions."""

import copy
import json
from datetime import date, timedelta

import pytest

from scripts.check_supply_chain import check_attachment, selected_requirements
from scripts.supply_chain import (
    check_actions,
    check_audit,
    check_policy,
    runtime_packages,
    validate_sbom,
)
from tests.support.distribution import ROOT

TODAY = date(2026, 10, 7)
POLICY = json.loads((ROOT / "scripts/supply_chain_policy.json").read_text())
VULNERABLE = {
    "dependencies": [
        {
            "name": "requests",
            "version": "2.19.1",
            "vulns": [
                {
                    "id": "PYSEC-2018-28",
                    "aliases": ["CVE-2018-18074", "GHSA-x84v-xcm2-53pg"],
                    "fix_versions": ["2.20.0"],
                }
            ],
        }
    ]
}


def exception(**changes):
    value = {
        "package": "requests",
        "version": "2.19.1",
        "vulnerability": "CVE-2018-18074",
        "issue": "https://github.com/carloshm91/kubetrol/issues/35",
        "owner": "carloshm91",
        "rationale": "Synthetic fixture only; production does not use this vulnerable version.",
        "expires": (TODAY + timedelta(days=7)).isoformat(),
    }
    value.update(changes)
    return value


def with_exception(**changes):
    return {**copy.deepcopy(POLICY), "vulnerability_exceptions": [exception(**changes)]}


def test_known_requests_credential_disclosure_fixture_is_rejected():
    # Source: https://github.com/advisories/GHSA-x84v-xcm2-53pg
    with pytest.raises(ValueError, match=r"Unresolved vulnerability: requests 2\.19\.1"):
        check_audit(VULNERABLE, {"requests": "2.19.1"}, POLICY, TODAY)
    assert check_audit(VULNERABLE, {"requests": "2.19.1"}, with_exception(), TODAY) == [exception()]


@pytest.mark.parametrize(
    "changes",
    [
        {"package": "*"},
        {"package": "requests_*"},
        {"version": "*"},
        {"version": ">=2"},
        {"vulnerability": "*"},
        {"vulnerability": "all"},
        {"issue": "https://example.invalid/1"},
        {"issue": "https://github.com/carloshm91/kubetrol/issues/0"},
        {"owner": ""},
        {"owner": "someone@example.invalid"},
        {"rationale": "ignore"},
        {"rationale": ""},
        {"expires": "2026-10-06"},
        {"expires": "2026-10-07"},
        {"expires": "2027-10-07"},
        {"expires": "never"},
        {"version": None},
    ],
)
def test_broad_incomplete_or_expired_exception_cannot_pass(changes):
    with pytest.raises(ValueError):
        check_policy(with_exception(**changes), TODAY)


@pytest.mark.parametrize("field", list(exception()))
def test_every_exception_field_is_required(field):
    policy = with_exception()
    del policy["vulnerability_exceptions"][0][field]
    with pytest.raises(ValueError, match="Incomplete"):
        check_policy(policy, TODAY)


def test_exception_is_version_and_package_specific_and_duplicate_aliases_are_rejected():
    for changes in ({"package": "other"}, {"version": "2.19.0"}, {"vulnerability": "CVE-2000-1"}):
        with pytest.raises(ValueError, match="Unresolved"):
            check_audit(VULNERABLE, {"requests": "2.19.1"}, with_exception(**changes), TODAY)
    duplicate = with_exception()
    duplicate["vulnerability_exceptions"].append(exception())
    with pytest.raises(ValueError, match="Duplicate"):
        check_policy(duplicate, TODAY)
    ambiguous = with_exception()
    ambiguous["vulnerability_exceptions"].append(exception(vulnerability="PYSEC-2018-28"))
    with pytest.raises(ValueError, match="Unresolved"):
        check_audit(VULNERABLE, {"requests": "2.19.1"}, ambiguous, TODAY)


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"dependencies": None},
        {"dependencies": []},
        {
            "dependencies": [
                {"name": "requests", "version": "2.19.1", "skip_reason": "missing", "vulns": []}
            ]
        },
        {"dependencies": [{"name": "requests", "version": "2.19.1"}]},
        {"dependencies": [{"name": "requests", "version": "2.20.0", "vulns": []}]},
        {"dependencies": [{"name": "requests", "version": "2.19.1", "vulns": []}] * 2},
    ],
)
def test_audit_must_cover_each_exact_dependency_without_skips(report):
    with pytest.raises(ValueError):
        check_audit(report, {"requests": "2.19.1"}, POLICY, TODAY)


@pytest.mark.parametrize(
    "finding",
    [
        {},
        {"id": ""},
        {"id": "CVE-2018-18074", "aliases": None},
        {"id": "CVE-2018-18074", "aliases": [1]},
    ],
)
def test_malformed_findings_do_not_pass(finding):
    report = copy.deepcopy(VULNERABLE)
    report["dependencies"][0]["vulns"] = [finding]
    with pytest.raises(ValueError):
        check_audit(report, {"requests": "2.19.1"}, with_exception(), TODAY)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"approved_license_expressions": []},
        {"approved_license_expressions": ["MIT", "MIT"]},
        {"approved_license_expressions": ["anything"]},
        {"vulnerability_exceptions": None},
    ],
)
def test_license_and_exception_policies_are_explicit(changes):
    with pytest.raises(ValueError):
        check_policy({**POLICY, **changes}, TODAY)


def test_locked_selection_honors_markers_and_rejects_unpinned_requirements():
    text = 'a==1 \\\n --hash=sha256:abc\nb==2; python_version < "3.13"\nb==3; python_version >= "3.13"\n'
    assert selected_requirements(text, "3.12.12") == {"a": "1", "b": "2"}
    assert selected_requirements(text, "3.14.3") == {"a": "1", "b": "3"}
    for value in ("", "a>=1", "a==1.*", "a @ https://example.invalid/a.whl", "a==1\na==1"):
        with pytest.raises(ValueError):
            selected_requirements(value, "3.12.12")


def test_runtime_closure_includes_extras_cycles_and_only_active_markers():
    project = {"version": "0.1", "dependencies": ["a[x]>=1"]}
    inventory = {
        "python": "3.12.12",
        "packages": [
            {"name": "kubetrol", "version": "0.1", "requires": ["a[x]>=1"]},
            {
                "name": "a",
                "version": "1",
                "requires": ['b==2; extra == "x"', 'absent; python_version < "3.11"'],
            },
            {"name": "b", "version": "2", "requires": ["a[x]>=1"]},
        ],
    }
    assert runtime_packages(inventory, project) == {"a": "1", "b": "2"}
    for change in ("missing", "extra", "root", "requirement", "version", "duplicate", "url"):
        candidate = copy.deepcopy(inventory)
        if change == "missing":
            candidate["packages"].pop()
        if change == "extra":
            candidate["packages"].append({"name": "extra", "version": "1", "requires": []})
        if change == "root":
            candidate["packages"][0]["version"] = "0.2"
        if change == "requirement":
            candidate["packages"][0]["requires"] = []
        if change == "version":
            candidate["packages"][1]["version"] = "0"
        if change == "duplicate":
            candidate["packages"].append(candidate["packages"][1])
        if change == "url":
            candidate["packages"][1]["requires"] = ["b @ https://example.invalid/x.whl"]
        with pytest.raises(ValueError):
            runtime_packages(candidate, project)


@pytest.mark.parametrize(
    "uses",
    [
        "actions/checkout@main",
        "actions/checkout@v7",
        "a/b@" + "a" * 39,
        "a/b@" + "a" * 41,
        "docker://image:latest",
        "a/b@${{ secrets.REF }}",
    ],
)
def test_floating_actions_and_reusable_workflows_fail(tmp_path, uses):
    for job in (f"steps:\n      - uses: '{uses}'", f"uses: '{uses}'"):
        (tmp_path / "workflow.yml").write_text(f"jobs:\n  gate:\n    {job}\n")
        with pytest.raises(ValueError, match="pinned"):
            check_actions(tmp_path)


def test_current_actions_are_pinned_and_missing_inventory_is_rejected(tmp_path):
    check_actions(ROOT / ".github/workflows")
    with pytest.raises(ValueError, match="Missing"):
        check_actions(tmp_path)


def test_cyclonedx_schema_and_digest_linkage_are_independently_required():
    artifacts = {"kubetrol.whl": "a" * 64, "kubetrol.tar.gz": "b" * 64}
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "kubetrol", "version": "0.1"}},
    }
    validate_sbom(bom)
    from scripts.check_supply_chain import attach_artifacts

    attach_artifacts(bom, artifacts, "c" * 64, "locked")
    validate_sbom(bom)
    check_attachment(bom, artifacts, "c" * 64, "locked", {"version": "0.1"})
    for change in ("schema", "hash", "source", "version", "lock", "scope"):
        candidate = copy.deepcopy(bom)
        component = candidate["metadata"]["component"]
        if change == "schema":
            candidate["version"] = "invalid"
        if change == "hash":
            component["hashes"][0]["content"] = "d" * 64
        if change == "source":
            component["properties"][0]["value"] = "d" * 64
        if change == "version":
            component["version"] = "0.2"
        if change == "lock":
            component["properties"][-2]["value"] = "d" * 64
        if change == "scope":
            component["properties"][-1]["value"] = "other"
        with pytest.raises(ValueError):
            validate_sbom(candidate)
            check_attachment(candidate, artifacts, "c" * 64, "locked", {"version": "0.1"})
