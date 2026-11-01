"""Internal evidence stays exact, while readers and release tools use current paths."""

import json
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from scripts.build_site import ROOT, build
from scripts.check_site import verify
from scripts.check_supply_chain import INPUT_FILES
from scripts.documentation import load_navigation, validate_documentation_plan
from scripts.documentation_links import links, original_contexts, relocated_source
from scripts.site_reference import reference_files


def test_history_moves_to_one_internal_area_with_exact_original_git_evidence():
    plan = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    assert len(plan["relocations"]) == 98
    assert len(plan["preserved_sources"]) == 95
    assert len(plan["operational_sources"]) == 3
    assert len(original_contexts(ROOT)) == 95
    mapped = {item["source"]: item for item in plan["documents"]}
    for old, new in plan["relocations"].items():
        assert new.startswith("docs/internal/") and (ROOT / new).is_file()
        assert new in mapped[old]["destinations"]
        assert mapped[new]["action"] == "keep"
        if old != "docs/first-preview.md":
            assert not (ROOT / old).is_file()
    for record in plan["preserved_sources"] + plan["operational_sources"]:
        assert mapped[record["path"]]["baseline_sha256"] == record["sha256"]
    assert len(mapped) == 313
    assert validate_documentation_plan(ROOT, list(mapped)) == 313
    assert not (ROOT / "docs/status.md").exists()


def test_status_is_short_and_every_user_page_avoids_evidence_links():
    status = (ROOT / "docs/first-preview.md").read_text()
    assert status.startswith("# Status\n") and len(status.splitlines()) <= 50
    assert "0.2.0" in status and "It is not a published release" in status
    assert "coverage" not in status.lower() and "actions/runs" not in status
    assert "kuberich --version" in status
    navigation = load_navigation(ROOT)
    generated = reference_files(ROOT)
    pages = {"first-preview.md": status, "README.md": (ROOT / "README.md").read_text()}
    for page in navigation.pages:
        pages[page.source] = (
            generated[page.source] if page.generated else (ROOT / "docs" / page.source).read_text()
        )
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    for name, content in pages.items():
        for target in links(parser.parse(content)):
            parsed = urlsplit(target)
            path = unquote(parsed.path)
            assert not any(
                segment in path
                for segment in (
                    "/internal/",
                    "acceptance/",
                    "preview-history",
                    "guide-history",
                    "architecture-history",
                )
            ), (name, target)
    assert navigation.user_page_count == 20


def test_public_surfaces_and_search_never_include_internal_records(tmp_path):
    output = tmp_path / "site"
    manifest = build(output, ROOT)
    verify(output, ROOT)
    assert manifest["documentation_pages"] == 20
    for path in output.rglob("*"):
        assert "internal" not in path.relative_to(output).parts
        if path.is_file() and (path.suffix == ".html" or path.name.startswith("search")):
            text = path.read_text()
            assert "/internal/" not in text
            assert "first-preview-before-status" not in text
            assert "user-guides-before-consolidation" not in text


def test_source_guard_keeps_current_operational_inputs_in_exact_release_inventory():
    for filename in ("backlog.json", "github-issues.json"):
        assert f"docs/internal/{filename}" in INPUT_FILES
        assert f"docs/{filename}" not in INPUT_FILES
        assert relocated_source(ROOT, f"docs/{filename}") == f"docs/internal/{filename}"
    plan = json.loads((ROOT / "docs/internal/backlog.json").read_text())
    issues = json.loads((ROOT / "docs/internal/github-issues.json").read_text())
    assert plan["repository"] == issues["repository"] == "carloshm91/kuberich"
