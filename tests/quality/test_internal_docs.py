"""Internal evidence stays exact, while readers and release tools use current paths."""

import json
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from scripts.build_site import ROOT, build
from scripts.check_site import verify
from scripts.check_supply_chain import INPUT_FILES
from scripts.documentation import load_navigation, validate_documentation_plan
from scripts.documentation_links import git_bytes, links, original_contexts, relocated_source
from scripts.site_reference import reference_files
from tests.support.site_source import latest_published


def test_history_moves_to_one_internal_area_with_exact_original_git_evidence():
    plan = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    assert len(plan["relocations"]) == 100
    assert len(plan["preserved_sources"]) == 105
    assert len(plan["operational_sources"]) == 3
    assert len(original_contexts(ROOT)) == 105
    mapped = {item["source"]: item for item in plan["documents"]}
    for old, new in plan["relocations"].items():
        assert new.startswith("docs/internal/") and (ROOT / new).is_file()
        assert new in mapped[old]["destinations"]
        assert mapped[new]["action"] == "keep"
        if old != "docs/first-preview.md":
            assert not (ROOT / old).is_file()
    for record in plan["preserved_sources"] + plan["operational_sources"]:
        assert mapped[record["path"]]["baseline_sha256"] == record["sha256"]
    assert len(mapped) == 370
    assert validate_documentation_plan(ROOT, list(mapped)) == 370
    assert not (ROOT / "docs/status.md").exists()


def test_status_is_short_and_every_user_page_avoids_evidence_links():
    status = (ROOT / "docs/first-preview.md").read_text()
    assert status.startswith("# Status\n")
    assert f"KubeRich {latest_published()} is published" in status
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
    assert navigation.user_page_count == 25


def test_public_surfaces_and_search_never_include_internal_records(tmp_path):
    output = tmp_path / "site"
    manifest = build(output, ROOT)
    verify(output, ROOT)
    assert manifest["documentation_pages"] == 25
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


def test_current_engineering_phase_snapshots_do_not_overwrite_earlier_history():
    plan = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    versions = {
        "docs/acceptance/editing.md": "docs/internal/acceptance/editing.md",
        "docs/acceptance/startup-budget.md": "docs/internal/acceptance/startup-budget.md",
        "docs/acceptance/terminal-navigation.md": "docs/internal/acceptance/terminal-navigation.md",
        "docs/acceptance/forward-presets.md": "docs/internal/acceptance/forward-presets.md",
        "docs/acceptance/plugin-execution.md": "docs/internal/acceptance/plugin-execution.md",
        "docs/acceptance/resource-workspace.md": "docs/internal/acceptance/resource-workspace.md",
        "engineering/guide-history/source-map.json": "docs/internal/guide-history/source-map.json",
        "docs/first-preview.md": "docs/internal/first-preview-before-status.md",
    }
    contexts = original_contexts(ROOT)
    mapped = {item["source"]: item for item in plan["documents"]}
    for source, earlier in versions.items():
        current = relocated_source(ROOT, source)
        assert current != earlier and "0.3" in current
        assert (ROOT / current).read_bytes() != (ROOT / earlier).read_bytes()
        assert {current, earlier} <= set(mapped[source]["destinations"])
        assert contexts[ROOT / current].source == contexts[ROOT / earlier].source == source
    for name in (
        "kubeconfig-compatibility.md",
        "large-collections.md",
        "property-mutation-tests.md",
        "property-mutation-survivors.json",
        "startup-budget.md",
        "wayland-clipboard.md",
    ):
        path = "docs/internal/acceptance/" + name
        assert (ROOT / path).is_file() and mapped[path]["action"] == "keep"


def test_current_checkpoint_and_acceptance_use_normal_links_without_history_exemptions():
    contexts = original_contexts(ROOT)
    current = (
        "docs/internal/first-preview-current.md",
        "docs/internal/acceptance/task-guides.md",
        "docs/internal/acceptance/architecture-overview.md",
    )
    for name in current:
        assert (ROOT / name).is_file() and ROOT / name not in contexts
    checkpoint = (ROOT / current[0]).read_text()
    assert "857f9ad0216688853142d9b463d5d41cc955114f" in checkpoint
    assert "41444530467" in checkpoint and "125274306280" in checkpoint
    assert "Commands and keys" in checkpoint
    acceptance = (ROOT / current[1]).read_text()
    assert "41425930497" in acceptance and "79.77" in acceptance


def test_authorization_docs_append_only_exact_enrollment_without_rewriting_history():
    baseline = json.loads(
        git_bytes(
            ROOT, "show", "64817677c20aad876489f81427a7636f0c56cc6c:docs/documentation-plan.json"
        )
    )
    current = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    assert len(baseline["documents"]) == 348
    assert current["documents"][:348] == baseline["documents"]
    authorization = json.loads(
        git_bytes(
            ROOT, "show", "a3f8118e6b7bf8a55948564c80e8bdeec405c1ff:docs/documentation-plan.json"
        )
    )
    assert len(authorization["documents"]) == 351
    assert authorization["documents"][:348] == baseline["documents"]
    assert current["documents"][:351] == authorization["documents"]
    assert [item["source"] for item in current["documents"][348:351]] == [
        "docs/authorization.md",
        "docs/adr/0035-authorization-evidence-and-reviews.md",
        "docs/internal/acceptance/authorization.md",
    ]
    diagnostics = json.loads(
        git_bytes(
            ROOT, "show", "f4c34931dcf49df68f122888d028069af310c29d:docs/documentation-plan.json"
        )
    )
    assert len(diagnostics["documents"]) == 354
    assert diagnostics["documents"][:351] == authorization["documents"]
    assert current["documents"][:354] == diagnostics["documents"]
    assert [item["source"] for item in current["documents"][351:354]] == [
        "docs/cluster-diagnostics.md",
        "docs/adr/0036-native-and-external-diagnostics.md",
        "docs/internal/acceptance/cluster-diagnostics.md",
    ]
    exports = json.loads(
        git_bytes(
            ROOT, "show", "b781c793cbb7834d2dfe2c1bbe55c2caef1f7005:docs/documentation-plan.json"
        )
    )
    assert len(exports["documents"]) == 357
    assert exports["documents"][:354] == diagnostics["documents"]
    assert current["documents"][:357] == exports["documents"]
    assert [item["source"] for item in current["documents"][354:357]] == [
        "docs/exports.md",
        "docs/adr/0037-reviewed-local-artifacts.md",
        "docs/internal/acceptance/local-exports.md",
    ]
    assert [item["source"] for item in current["documents"][357:359]] == [
        "docs/adr/0038-container-configuration-provenance.md",
        "docs/internal/acceptance/container-inspection.md",
    ]
    inspection = json.loads(
        git_bytes(
            ROOT, "show", "5444b7d9c357d389243147a978cc20b248293edb:docs/documentation-plan.json"
        )
    )
    assert len(inspection["documents"]) == 359
    assert current["documents"][:359] == inspection["documents"]
    history = json.loads(
        git_bytes(
            ROOT, "show", "5060b4dcd35968e3b990bd833eba731539938cff:docs/documentation-plan.json"
        )
    )
    assert len(history["documents"]) == 361
    assert history["documents"][:359] == inspection["documents"]
    assert current["documents"][:361] == history["documents"]
    assert [item["source"] for item in history["documents"][359:361]] == [
        "docs/adr/0039-context-owned-metric-history.md",
        "docs/internal/acceptance/metric-history.md",
    ]
    curated = json.loads(
        git_bytes(
            ROOT, "show", "389babca15ab15e0ef8317a815afbeda1e8e9f73:docs/documentation-plan.json"
        )
    )
    assert len(curated["documents"]) == 364
    assert current["documents"][:364] == curated["documents"]
    assert [item["source"] for item in current["documents"][361:364]] == [
        "docs/adr/0040-curated-resource-observations.md",
        "docs/internal/acceptance/curated-resources.md",
        "docs/internal/curated-resource-inventory.json",
    ]
    observability = json.loads(
        git_bytes(
            ROOT, "show", "eee30e4d1a595fa15f54449d6b0c5026e74869ce:docs/documentation-plan.json"
        )
    )
    assert len(observability["documents"]) == 366
    assert observability["documents"][:364] == curated["documents"]
    assert current["documents"][:366] == observability["documents"]
    assert [item["source"] for item in observability["documents"][364:366]] == [
        "docs/release-notes/0.4.0.md",
        "docs/internal/acceptance/observability-qualification.md",
    ]
    assert len(current["documents"]) == 370
    assert current["documents"][366:] == [
        {
            "source": "docs/adr/0041-helm-release-identity.md",
            "audience": "development",
            "action": "keep",
            "destinations": ["docs/adr/0041-helm-release-identity.md"],
            "reason": "Record actual Helm storage identity, optional CLI ownership, default disclosure policy and non-atomic rollback outcomes.",
            "baseline_sha256": None,
        },
        {
            "source": "docs/internal/acceptance/helm-releases.md",
            "audience": "contributor acceptance evidence",
            "action": "keep",
            "destinations": ["docs/internal/acceptance/helm-releases.md"],
            "reason": "Retain Helm implementation boundaries and measured verification outside public user navigation.",
            "baseline_sha256": None,
        },
        {
            "source": "tests/fixtures/helm/README.md",
            "audience": "contributor test fixture provenance",
            "action": "keep",
            "destinations": ["tests/fixtures/helm/README.md"],
            "reason": "Retain upstream Helm fixture attribution, pinned source hashes and synthetic parser-shape provenance outside user navigation.",
            "baseline_sha256": None,
        },
        {
            "source": "tests/fixtures/helm/tiny-chart/README.md",
            "audience": "contributor test fixture provenance",
            "action": "keep",
            "destinations": ["tests/fixtures/helm/tiny-chart/README.md"],
            "reason": "Document the original synthetic chart, owned-cluster fixture behavior and rollback verification scope outside user navigation.",
            "baseline_sha256": None,
        },
    ]
    assert all(item["baseline_sha256"] is None for item in current["documents"][348:])
    assert authorization["canonical_user_pages"] == 23
    assert diagnostics["canonical_user_pages"] == 24
    assert exports["canonical_user_pages"] == 25
    assert current["canonical_user_pages"] == 25
    assert {
        key: value
        for key, value in current.items()
        if key not in {"documents", "canonical_user_pages"}
    } == {
        key: value
        for key, value in baseline.items()
        if key not in {"documents", "canonical_user_pages"}
    }
