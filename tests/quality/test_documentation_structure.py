"""Canonical documentation keeps guidance, old routes and exact source receipts."""

import json
import shutil
import subprocess

import pytest

from scripts.build_site import ROOT, build
from scripts.check_site import verify
from scripts.documentation import load_navigation, validate_documentation_plan
from tests.support.site_source import published_source, refresh


def navigation_data(source):
    return json.loads((source / "docs/navigation.json").read_text())


def save_navigation(source, data):
    (source / "docs/navigation.json").write_text(json.dumps(data))


def docs_source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "docs", source / "docs")
    return source


def insert_after_title(path, text):
    first, remaining = path.read_text().split("\n", 1)
    path.write_text(first + "\n\n" + text + "\n" + remaining)


def test_navigation_is_complete_diataxis_and_maps_the_baseline_documents():
    catalog = load_navigation(ROOT)
    assert catalog.user_page_count == 20
    assert {page.kind for page in catalog.pages} == {
        "tutorial",
        "how-to",
        "reference",
        "explanation",
    }
    fragments = {name for page in catalog.guides for name in page.sources}
    plan = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    baseline_guides = {
        item["source"].removeprefix("docs/")
        for item in plan["documents"]
        if item["audience"] == "user"
    }
    retired = {name for page in catalog.guides for name in page.retired}
    assert fragments | retired == baseline_guides and len(fragments | retired) == 30
    assert len(fragments) == 15
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT, text=True).split("\0")
    paths += ["docs/STYLE.md", "docs/navigation.json", "docs/documentation-plan.json"]
    assert validate_documentation_plan(ROOT, paths) == len(plan["documents"])
    assert len((ROOT / "docs/STYLE.md").read_text().splitlines()) <= 250
    assert plan["migration_state"] == "user_guides_architecture_and_internal_history_consolidated"


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "budget_override",
        "missing_type",
        "duplicate_type",
        "duplicate_page",
        "duplicate_fragment",
        "unsafe_source",
        "missing_source",
        "missing_reference",
        "fake_reference",
        "empty_sources",
        "missing_route",
        "wrong_route",
        "unsafe_anchor",
        "canonical_route",
        "too_many_pages",
        "symlink_source",
        "symlink_navigation",
    ],
)
def test_navigation_rejects_missing_ambiguous_or_unsafe_structure(tmp_path, fault):
    source = docs_source(tmp_path)
    data = navigation_data(source)
    page = data["sections"][0]["pages"][0]
    if fault == "version":
        data["schema_version"] = True
    elif fault == "budget_override":
        data["page_budget"] = 100
    elif fault == "missing_type":
        data["sections"].pop(0)
    elif fault == "duplicate_type":
        data["sections"][1]["kind"] = "tutorial"
    elif fault == "duplicate_page":
        data["sections"][0]["pages"].append(page.copy())
    elif fault == "duplicate_fragment":
        page["sources"].append("installation.md")
    elif fault == "unsafe_source":
        page["sources"].append("../outside.md")
    elif fault == "missing_source":
        (source / "docs/quickstart.md").unlink()
    elif fault == "missing_reference":
        data["sections"][-1]["pages"].pop()
    elif fault == "fake_reference":
        data["sections"][-1]["pages"][0]["source"] = "invented-reference.md"
    elif fault == "empty_sources":
        page["sources"] = []
    elif fault == "missing_route":
        data["legacy_routes"].pop(0)
    elif fault == "wrong_route":
        data["legacy_routes"][0]["target"] = "quickstart.md"
    elif fault == "unsafe_anchor":
        data["legacy_routes"][0]["anchor"] = "a fragment with spaces"
    elif fault == "canonical_route":
        data["legacy_routes"][0]["source"] = "quickstart.md"
    elif fault == "too_many_pages":
        for number in range(2):
            name = f"extra-{number}.md"
            (source / "docs" / name).write_text("# Extra guide\n")
            data["sections"][0]["pages"].append(
                {"source": name, "title": "Extra guide", "sources": [name], "generated": False}
            )
    elif fault == "symlink_source":
        original = source / "docs/quickstart.md"
        other = tmp_path / "external-guide.md"
        original.rename(other)
        original.symlink_to(other)
    save_navigation(source, data)
    if fault == "symlink_navigation":
        original = source / "docs/navigation.json"
        other = tmp_path / "external-navigation.json"
        original.rename(other)
        original.symlink_to(other)
    with pytest.raises(ValueError):
        load_navigation(source)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "action", "destination", "checksum"])
def test_document_dispositions_reject_unmapped_or_invalid_records(tmp_path, fault):
    source = docs_source(tmp_path)
    path = source / "docs/documentation-plan.json"
    data = json.loads(path.read_text())
    entry = data["documents"][0]
    paths = [entry["source"]]
    if fault == "missing":
        paths.append("docs/new-unmapped-guide.md")
    elif fault == "duplicate":
        data["documents"].append(entry.copy())
    elif fault == "action":
        entry["action"] = "discard"
    elif fault == "destination":
        entry["destinations"] = ["../../outside.md"]
    else:
        entry["baseline_sha256"] = "not-a-checksum"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        validate_documentation_plan(source, paths)


@pytest.mark.parametrize("public", [False, True])
def test_canonical_pages_preserve_every_fragment_and_real_deep_links(tmp_path, public):
    source = published_source(tmp_path / "source")
    catalog = load_navigation(source)
    for guide in catalog.guides:
        for fragment in guide.sources:
            insert_after_title(source / "docs" / fragment, f"Fragment receipt: {fragment}.")
    insert_after_title(
        source / "docs/quickstart.md",
        "## Primary stable anchor\n\n[Primary link](#primary-stable-anchor)\n\n"
        "[Merged link](eks-authentication.md#supported-local-contracts)",
    )
    output = tmp_path / "output"
    manifest = build(output, source, public_launch=public)
    assert manifest["documentation_pages"] == 20 and manifest["publication_performed"] is False
    assert "docs/navigation.json" in manifest["sources"]
    assert "scripts/documentation.py" in manifest["sources"]
    surfaces = [output / "docs"] + ([] if public else [output / "www/docs"])
    for surface in surfaces:
        assert len(list(surface.glob("*.html"))) - int((surface / "404.html").exists()) == 20
        for guide in catalog.guides:
            html = (surface / guide.filename).read_text()
            for fragment in guide.sources:
                assert html.count(f"Fragment receipt: {fragment}.") == 1
                assert "docs/" + fragment in manifest["sources"]
        quickstart = (surface / "quickstart.html").read_text()
        contexts = (surface / "context-sessions.html").read_text()
        assert 'href="quickstart.html#primary-stable-anchor"' in quickstart
        assert 'href="context-sessions.html#eks"' in quickstart
        assert 'id="first-installation-and-trial"' in quickstart
        assert 'id="eks-authentication--supported-local-contracts"' in contexts
        assert 'id="legacy-eks-authentication"' in contexts
    redirects = (output / "docs/_redirects").read_text()
    assert "/eks-authentication.html /context-sessions.html 301\n" in redirects
    assert "/themes /configuration.html 301\n" in redirects
    assert "/standard-resources /resource-workspace.html 301\n" in redirects
    verify(output, source)


def test_legacy_routes_survive_later_source_consolidation(tmp_path):
    source = published_source(tmp_path / "source")
    data = navigation_data(source)
    page = next(
        page
        for section in data["sections"]
        for page in section["pages"]
        if page["source"] == "context-sessions.md"
    )
    assert "eks-authentication.md" in page["retired_sources"]
    route = next(
        route for route in data["legacy_routes"] if route["source"] == "eks-authentication.md"
    )
    route["heading"] = "retained-aws-help"
    route["anchor"] = "relocated-aws-help"
    existing = source / "docs/eks-authentication.md"
    body = existing.read_text().split("\n", 1)[1]
    insert_after_title(source / "docs/context-sessions.md", "## Retained AWS help\n" + body)
    existing.unlink()
    save_navigation(source, data)
    output = tmp_path / "output"
    build(output, source)
    html = (output / "docs/context-sessions.html").read_text()
    assert 'id="relocated-aws-help"' in html
    assert 'id="retained-aws-help"' in html
    verify(output, source)


@pytest.mark.parametrize("fault", ["redirect", "anchor", "extra_page"])
def test_checker_rejects_rehashed_but_invalid_documentation_routes(tmp_path, fault):
    source = published_source(tmp_path / "source")
    output = tmp_path / "output"
    build(output, source)
    if fault == "redirect":
        path = output / "docs/_redirects"
        path.write_text(
            path.read_text().replace("/themes /configuration.html", "/themes /wrong.html")
        )
        refresh(output, path)
    elif fault == "anchor":
        path = output / "docs/context-sessions.html"
        path.write_text(
            path.read_text().replace('id="legacy-eks-authentication"', 'id="wrong-anchor"')
        )
        refresh(output, path)
    else:
        path = output / "docs/unlisted.html"
        shutil.copyfile(output / "docs/quickstart.html", path)
        refresh(output, path)
    with pytest.raises(ValueError, match=r"redirect|canonical"):
        verify(output, source)


def test_generated_reference_snapshots_remain_part_of_the_source_receipt(tmp_path):
    source = published_source(tmp_path / "source")
    output = tmp_path / "output"
    build(output, source)
    path = source / "docs/config-reference.md"
    path.write_text(path.read_text() + "\nA changed generated snapshot.\n")
    with pytest.raises(ValueError, match="source drift"):
        verify(output, source)
