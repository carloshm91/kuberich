"""Current architecture, active decision links, and an exact historical source."""

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from scripts.build_site import ROOT, heading_ids
from scripts.documentation import load_navigation, validate_documentation_plan
from scripts.documentation_links import (
    git_bytes,
    original_contexts,
    relocated_source,
    validate_repository_links,
)


class Identifiers(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attributes):
        identifier = dict(attributes).get("id")
        if identifier:
            assert identifier not in self.ids, identifier
            self.ids.add(identifier)


def rendered(source):
    parser = MarkdownIt("commonmark", {"html": True}).enable("table")
    tokens = parser.parse(source)
    heading_ids(tokens)
    identifiers = Identifiers()
    identifiers.feed(parser.renderer.render(tokens, parser.options, {}))
    return tokens, identifiers.ids


def history():
    folder = ROOT / "docs/internal/architecture-history"
    record = json.loads((folder / "source-map.json").read_text())
    record["archive"] = relocated_source(ROOT, record["archive"])
    return record, json.loads((folder / "decision-catalog.json").read_text())


def test_short_overview_explains_the_actual_layers_data_flow_and_boundaries():
    text = (ROOT / "docs/architecture.md").read_text()
    assert len(text.splitlines()) <= 300
    tokens, _ = rendered(text)
    headings = {
        tokens[index + 1].content
        for index, token in enumerate(tokens)
        if token.type == "heading_open"
    }
    assert {
        "Domain",
        "Services",
        "Adapters",
        "UI",
        "Dependency direction",
        "Cluster sessions and watches",
        "Resource data flow",
        "Concurrency and cleanup",
        "Security boundaries",
        "Terminal behavior",
    } <= headings
    diagrams = [
        token.content for token in tokens if token.type == "fence" and token.info == "mermaid"
    ]
    assert len(diagrams) == 3
    assert any(
        "WatchState / ViewStore" in diagram and "projection / filter" in diagram
        for diagram in diagrams
    )
    assert any(
        "Cancel and await" in diagram and "Replace connection?" in diagram for diagram in diagrams
    )
    assert "still contains substantial" in text
    assert "smaller-App target remain stable-release goals" in text
    assert "WorkspacePresenter" in text and "WorkspaceCommands" in text
    assert "Target invalidation, capture, retirement, and cleanup failures remain" in text
    assert "no hosted backend or Textual Web" in text


def test_the_previous_log_is_byte_exact_and_each_section_has_an_active_destination():
    record, catalog = history()
    archive = (ROOT / record["archive"]).read_bytes()
    assert record["source_commit"] == "625086db1a75aab10ec28fe4d6440f7fb1d32849"
    assert hashlib.sha256(archive).hexdigest() == record["sha256"]
    plan = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    previous = next(item for item in plan["documents"] if item["source"] == "docs/architecture.md")
    assert previous["baseline_sha256"] == record["sha256"]
    assert record["archive"] in previous["destinations"]
    assert record["preamble"]["byte_start"] == 0
    cursor = record["preamble"]["byte_end"]
    accepted = {item["source"] for item in catalog["decisions"]}
    for section in record["sections"]:
        assert section["byte_start"] == cursor
        content = archive[section["byte_start"] : section["byte_end"]]
        assert content.startswith(("## " + section["heading"]).encode())
        assert hashlib.sha256(content).hexdigest() == section["sha256"]
        assert section["destinations"] and set(section["destinations"]) <= accepted
        for destination in section["destinations"]:
            assert (ROOT / destination).is_file()
        cursor = section["byte_end"]
    assert cursor == len(archive)


def test_every_previous_heading_still_resolves_to_current_overview_guidance():
    record, _ = history()
    archived = (ROOT / record["archive"]).read_text()
    old_tokens, old_ids = rendered(archived)
    old_headings = {token.attrGet("id") for token in old_tokens if token.type == "heading_open"}
    assert old_headings == {item["identifier"] for item in record["headings"]}
    _, active_ids = rendered((ROOT / "docs/architecture.md").read_text())
    assert old_headings <= old_ids
    assert old_headings <= active_ids


def test_numbered_records_are_real_decisions_with_sources_and_a_template():
    _, catalog = history()
    paths = set()
    index = (ROOT / "docs/adr/README.md").read_text()
    for item in catalog["decisions"]:
        path = ROOT / item["source"]
        assert re.fullmatch(r"[0-9]{4}-[a-z0-9-]+\.md", path.name)
        assert item["number"] not in paths
        paths.add(item["number"])
        text = path.read_text()
        assert text.startswith("# " + item["title"] + "\n")
        assert "Status: Accepted" in text
        assert all(
            "## " + title in text
            for title in ("Context", "Decision", "Consequences", "Source and related decisions")
        )
        assert f"]({path.name})" in index
        for module in item["modules"]:
            assert (ROOT / module).is_file(), module
            assert f"](../../{module})" in text
    template = (ROOT / "docs/adr/0000-template.md").read_text()
    assert "Status: Proposed" in template and "## Consequences" in template
    contribution = (ROOT / "CONTRIBUTING.md").read_text()
    assert "](docs/architecture.md)" in contribution
    assert "](docs/adr/README.md)" in contribution


def test_architecture_and_decision_links_resolve_without_publishing_history():
    _, catalog = history()
    paths = [ROOT / "docs/architecture.md", ROOT / "docs/adr/README.md"]
    paths += [ROOT / item["source"] for item in catalog["decisions"]]
    paths += [
        ROOT / "docs/adr/app-composition.md",
        ROOT / "docs/adr/0032-kubeconfig-loader-contract.md",
    ]
    for path in paths:
        tokens, _ = rendered(path.read_text())
        for token in tokens:
            for child in token.children or []:
                if child.type != "link_open":
                    continue
                href = str(child.attrGet("href"))
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    assert parsed.scheme == "https"
                    continue
                target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
                assert target.is_relative_to(ROOT) and target.is_file(), href
                if parsed.fragment:
                    _, identifiers = rendered(target.read_text())
                    assert unquote(parsed.fragment) in identifiers, href
    navigation = load_navigation(ROOT)
    assert navigation.user_page_count == 20
    assert not any(
        "architecture" in page.source or "adr/" in page.source for page in navigation.pages
    )


def test_every_new_architecture_document_has_an_explicit_disposition():
    record, catalog = history()
    names = [item["source"] for item in catalog["decisions"]]
    names += [
        record["archive"],
        "docs/internal/architecture-history/README.md",
        "docs/adr/README.md",
        "docs/adr/0000-template.md",
    ]
    validate_documentation_plan(ROOT, names)


def test_archived_architecture_links_use_the_byte_verified_original_source_context():
    record, _ = history()
    archive = ROOT / record["archive"]
    contexts = original_contexts(ROOT)
    plan = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    proof = next(item for item in plan["preserved_sources"] if item["path"] == record["archive"])
    assert contexts[archive].source == "docs/architecture.md"
    assert contexts[archive].commit == proof["commit"]
    # The outer transfer can use a byte-identical protected predecessor while
    # the unchanged inner map records its original migration source.
    assert archive.read_bytes() == git_bytes(
        ROOT, "cat-file", "blob", f"{proof['commit']}:{proof['source']}"
    )
    assert not (archive.parent / "acceptance/plugin-execution.md").exists()
    assert validate_repository_links(ROOT) > 0


def test_current_composition_and_kubeconfig_decisions_remain_in_the_active_index():
    index = (ROOT / "docs/adr/README.md").read_text()
    overview = (ROOT / "docs/architecture.md").read_text()
    for name in ("app-composition.md", "0032-kubeconfig-loader-contract.md"):
        assert f"]({name})" in index
        assert f"](adr/{name})" in overview
    assert "current view and scope" in overview and "inline Retry" in overview
    assert "**INCOMPLETE**" in overview and "PartialObjectMetadata" in overview
    assert "Basic authentication" in overview and "OIDC migration" in overview
    assert "latency targets are advisory" in overview and "for 0.x" in overview
    assert "strict opt-ins and actual source major 1" in overview
    assert "RSS/import boundaries" in overview and "ownership/cleanup remain mandatory" in overview
