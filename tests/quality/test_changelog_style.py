"""Concise user changes preserve the published history and frozen-note contract."""

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import date

import pytest
from markdown_it import MarkdownIt
from packaging.version import Version

from scripts.build_site import ROOT
from scripts.documentation_links import git_bytes
from scripts.release_notes import SECTIONS, freeze

PARSER = MarkdownIt("commonmark")
GROUPS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}


def visible_words(markdown):
    inline = PARSER.parseInline(markdown)[0]
    text = "".join(
        token.content for token in inline.children or [] if token.type in {"text", "code_inline"}
    )
    return text.split()


def change_entries(text):
    lines = text.splitlines()
    version, category = "Unreleased", ""
    tokens = PARSER.parse(text)
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            content = tokens[index + 1].content
            if token.tag == "h2":
                match = re.fullmatch(
                    r"\[(Unreleased|[0-9][^\]]*)\](?: - (\d{4}-\d{2}-\d{2}))?", content
                )
                assert match, content
                version = match[1]
                if version != "Unreleased":
                    Version(version)
                    assert match[2]
                    date.fromisoformat(match[2])
            elif token.tag == "h3":
                assert content in GROUPS
                category = content
        if token.type != "list_item_open":
            continue
        assert token.map is not None
        start, end = token.map
        source = "\n".join(lines[start:end]).strip()
        assert source.startswith("- ") and "\n" not in source
        yield version, category, source


def source_start_lines(path, original):
    tokens = PARSER.parse(original)
    if path == "CHANGELOG.md":
        current = "Unreleased"
        starts = set()
        for index, token in enumerate(tokens):
            if token.type == "heading_open" and token.tag == "h2":
                current = tokens[index + 1].content
            if token.type == "list_item_open" and "Unreleased" not in current:
                starts.add(token.map[0] + 1)
        return starts
    return {token.map[0] + 1 for token in tokens if token.type in {"paragraph_open", "fence"}}


def test_keep_a_changelog_groups_and_every_change_entry_is_one_short_line():
    text = (ROOT / "CHANGELOG.md").read_text()
    entries = list(change_entries(text))
    assert entries and text.startswith("# Changelog\n")
    assert "https://keepachangelog.com/en/1.1.0/" in text
    versions = [match[1] for match in re.finditer(r"^## \[([^]]+)\]", text, re.M)]
    assert versions[0] == "Unreleased"
    assert list(map(Version, versions[1:])) == sorted(map(Version, versions[1:]), reverse=True)
    published = json.loads((ROOT / "docs/published-releases.json").read_text())["releases"]
    assert set(published) <= set(versions)
    for version, category, entry in entries:
        assert category in GROUPS
        assert 1 <= len(visible_words(entry[2:])) <= 25, (version, entry)
    for path in (ROOT / "docs/release-notes").glob("*.md"):
        if path.name == "README.md":
            continue
        for token in PARSER.parse(path.read_text()):
            if token.type != "list_item_open":
                continue
            lines = path.read_text().splitlines()[token.map[0] : token.map[1]]
            entry = "\n".join(lines).strip()
            assert "\n" not in entry and len(visible_words(entry[2:])) <= 25, (path, entry)


def test_published_user_change_map_is_complete_and_uses_actual_stable_git_sources():
    mapping = json.loads((ROOT / "docs/internal/release-note-mapping.json").read_text())
    assert mapping["schema_version"] == 1
    sources = {}
    expected_starts = {}
    for source in mapping["sources"]:
        assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
        # A protected-main ancestor remains reachable when short-lived PR branches go away.
        assert (
            subprocess.run(
                [
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    source["commit"],
                    "refs/remotes/origin/main",
                ],
                cwd=ROOT,
                check=False,
            ).returncode
            == 0
        )
        original = git_bytes(ROOT, "show", f"{source['commit']}:{source['path']}")
        assert hashlib.sha256(original).hexdigest() == source["sha256"]
        sources[source["path"]] = original.decode().splitlines(keepends=True)
        expected_starts[source["path"]] = source_start_lines(source["path"], original.decode())
    current = {
        (version, hashlib.sha256(entry.encode()).hexdigest())
        for version, _, entry in change_entries((ROOT / "CHANGELOG.md").read_text())
    }
    entries = {entry["id"]: entry for entry in mapping["entries"]}
    assert len(entries) == len(mapping["entries"])
    for entry in entries.values():
        assert entry["version"] != "Unreleased"
        assert (entry["version"], entry["markdown_sha256"]) in current
    actual_starts = defaultdict(set)
    targets = set()
    identifiers = set()
    for block in mapping["source_blocks"]:
        assert block["id"] not in identifiers
        identifiers.add(block["id"])
        source = sources[block["source"]]
        start, end = block["line_start"], block["line_end"]
        assert 0 < start <= end <= len(source)
        original = "".join(source[start - 1 : end])
        assert hashlib.sha256(original.encode()).hexdigest() == block["sha256"]
        actual_starts[block["source"]].add(start)
        if block["disposition"] == "internal_process":
            assert block["reason"] and not block.get("targets") and not block.get("destinations")
            continue
        assert block["disposition"] == "user_change"
        assert block["targets"] or block["destinations"]
        for target in block["targets"]:
            assert target in entries
            if block["source"] == "CHANGELOG.md":
                assert entries[target]["version"] == block["version"]
            targets.add(target)
        for destination in block["destinations"]:
            assert f"\n## {destination['section']}\n" in (ROOT / destination["path"]).read_text()
    assert dict(actual_starts) == expected_starts
    assert targets == entries.keys()


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0"])
def test_rewritten_actual_notes_still_freeze_exactly_under_the_existing_contract(tmp_path, version):
    path = tmp_path / f"docs/release-notes/{version}.md"
    path.parent.mkdir(parents=True)
    content = (ROOT / f"docs/release-notes/{version}.md").read_bytes()
    path.write_bytes(content)
    for arguments in [
        ("init", "--quiet"),
        ("add", "."),
        (
            "-c",
            "user.name=Owned Notes Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Record actual rewritten note bytes",
        ),
    ]:
        subprocess.run(
            ["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True, timeout=10
        )
    sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    result = freeze(tmp_path, sha, version)
    assert result["body"] == content.decode()
    assert result["authored_sha256"] == hashlib.sha256(content).hexdigest()
    template = (ROOT / "docs/release-notes/TEMPLATE.md").read_text()
    assert all(f"\n## {section}\n" in template for section in SECTIONS)
