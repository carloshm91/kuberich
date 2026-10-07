"""Actual installed-runtime audits and offline, artifact-linked negative controls."""

import json
import shutil
import sys

import pytest

from scripts.check_supply_chain import verify, write_json
from scripts.supply_chain import digest, license_inventory
from tests.support.distribution import ROOT, run


def test_locked_and_fresh_installed_runtime_reports_have_valid_complete_sboms(security_evidence):
    output, distribution = security_evidence
    results = verify(output, distribution)
    assert results.keys() == {"locked", "fresh"}
    assert all(
        value["dependencies"] >= 27 and value["accepted_exceptions"] == []
        for value in results.values()
    )
    for scope in results:
        notices = (output / f"{scope}-NOTICES.txt").read_text()
        assert "LGPL-3.0-only" in notices and "GNU LESSER GENERAL PUBLIC LICENSE" in notices
        assert "wcwidth" in notices and "MIT License" in notices
    result = run(
        [
            sys.executable,
            "-m",
            "scripts.check_supply_chain",
            "--verify",
            "--output",
            str(output),
            "--dist",
            str(distribution),
        ],
        ROOT,
        environment={"PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "finding",
        "audit_missing",
        "audit_skip",
        "audit_version",
        "audit_exit",
        "sbom_schema",
        "sbom_missing",
        "sbom_version",
        "sbom_hash",
        "notice_missing",
        "notice_digest",
        "notice_rewrite",
        "inventory_extra",
        "inventory_duplicate",
        "lock_rewrite",
        "report_digest",
        "source_link",
        "attested",
        "scopes",
        "reports",
        "artifact_bytes",
        "report_symlink",
    ],
)
def test_altered_evidence_is_rejected_even_when_outer_report_hash_is_recomputed(
    security_evidence, tmp_path, mutation
):
    original, original_dist = security_evidence
    output, distribution = tmp_path / "reports", tmp_path / "dist"
    shutil.copytree(original, output)
    shutil.copytree(original_dist, distribution)
    manifest = json.loads((output / "provenance.json").read_text())
    report = None
    if mutation.startswith("audit") or mutation == "finding":
        report = "locked-audit.json"
        value = json.loads((output / report).read_text())
        dependency = value["dependencies"][0]
        if mutation == "finding":
            dependency["vulns"] = [{"id": "CVE-2000-1234", "aliases": []}]
        if mutation == "audit_missing":
            value["dependencies"].pop()
        if mutation == "audit_skip":
            dependency["skip_reason"] = "unavailable"
        if mutation == "audit_version":
            dependency["version"] = "0"
        if mutation == "audit_exit":
            manifest["audit_exit_codes"]["locked"] = 1
        write_json(output / report, value)
    if mutation.startswith("sbom"):
        report = "locked-sbom.json"
        value = json.loads((output / report).read_text())
        if mutation == "sbom_schema":
            value["version"] = "broken"
        if mutation == "sbom_missing":
            value["components"].pop()
        if mutation == "sbom_version":
            value["components"][0]["version"] = "0"
        if mutation == "sbom_hash":
            value["metadata"]["component"]["hashes"][0]["content"] = "a" * 64
        write_json(output / report, value)
    if mutation in {"notice_missing", "notice_digest", "inventory_extra", "inventory_duplicate"}:
        report = "locked-inventory.json"
        value = json.loads((output / report).read_text())
        package = next(package for package in value["packages"] if package["name"] == "pyte")
        if mutation == "notice_missing":
            package["notices"] = []
        if mutation == "notice_digest":
            package["notices"][0]["sha256"] = "a" * 64
        if mutation == "inventory_duplicate":
            value["packages"].append(package)
        if mutation == "inventory_extra":
            value["packages"].append({**package, "name": "unrelated"})
        write_json(output / report, value)
    if mutation == "notice_rewrite":
        report = "locked-NOTICES.txt"
        (output / report).write_text("All licenses erased")
    if mutation == "lock_rewrite":
        report = "runtime.txt"
        (output / report).write_text("pyte==0.8.2\n")
    if report:
        manifest["reports"][report] = digest(output / report)
    if mutation == "report_digest":
        manifest["reports"]["runtime.txt"] = "a" * 64
    if mutation == "source_link":
        manifest["pyte_corresponding_source"]["hash"] = "sha256:" + "a" * 64
    if mutation == "attested":
        manifest["attested"] = True
    if mutation == "scopes":
        manifest["scopes"] = ["locked"]
    if mutation == "reports":
        del manifest["reports"]["fresh-audit.json"]
    if mutation == "artifact_bytes":
        next(distribution.glob("*.whl")).write_bytes(b"replaced")
    if mutation == "report_symlink":
        path = output / "runtime.txt"
        path.unlink()
        path.symlink_to(original / "runtime.txt")
    write_json(output / "provenance.json", manifest)
    with pytest.raises(ValueError):
        verify(output, distribution)


@pytest.mark.parametrize(
    "change", ["legacy_version", "legacy_declared", "unapproved", "missing_pyte", "missing_width"]
)
def test_license_reviews_are_specific_and_original_files_are_required(security_evidence, change):
    output, _ = security_evidence
    inventory = json.loads((output / "locked-inventory.json").read_text())
    bom = json.loads((output / "locked-sbom.json").read_text())
    policy = json.loads((ROOT / "scripts/supply_chain_policy.json").read_text())
    package = next(item for item in inventory["packages"] if item["name"] == "aiosignal")
    if change == "legacy_version":
        package["version"] = "0.0.0"
        next(item for item in bom["components"] if item["name"] == "aiosignal")["version"] = "0.0.0"
    if change == "legacy_declared":
        package["license"] = "Different License"
    if change == "unapproved":
        package["license_expression"] = "AGPL-3.0-only"
    if change in {"missing_pyte", "missing_width"}:
        name = "pyte" if change == "missing_pyte" else "wcwidth"
        inventory["packages"] = [item for item in inventory["packages"] if item["name"] != name]
        bom["components"] = [item for item in bom["components"] if item["name"] != name]
    with pytest.raises(ValueError):
        license_inventory(inventory, bom, policy)
