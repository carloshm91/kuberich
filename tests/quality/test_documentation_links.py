"""Active Markdown links and exact historical contexts retain real failure checks."""

import hashlib
import json
import subprocess

import pytest
import yaml

from scripts.build_site import ROOT
from scripts.documentation_links import (
    original_contexts,
    repository_path,
    validate_markdown,
    validate_repository_links,
)
from scripts.site_reference import check_reference_files, reference_files


def git(root, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], stderr=subprocess.PIPE, text=True, timeout=10
    ).strip()


def history_source(tmp_path, text="[Original sibling](sibling.md)\n"):
    root = tmp_path / "source"
    (root / "docs").mkdir(parents=True)
    (root / "docs/old.md").write_text(text)
    (root / "docs/sibling.md").write_text("# Sibling\n")
    (root / "docs/documentation-plan.json").write_text("{}\n")
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Owned Documentation Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Record original documentation",
    )
    commit = git(root, "rev-parse", "HEAD")
    archive = root / "engineering/history/old.md"
    archive.parent.mkdir(parents=True)
    archive.write_bytes((root / "docs/old.md").read_bytes())
    (root / "docs/old.md").unlink()
    (root / "docs/sibling.md").unlink()
    record = {
        "path": "engineering/history/old.md",
        "source": "docs/old.md",
        "commit": commit,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    save_records(root, [record])
    git(root, "add", "--all")
    return root, archive, record


def save_records(root, records):
    (root / "docs/documentation-plan.json").write_text(
        json.dumps({"preserved_sources": records}) + "\n"
    )


def test_generated_references_exist_at_their_real_canonical_markdown_paths():
    generated = reference_files(ROOT)
    assert len(generated) == 4
    for name, text in generated.items():
        assert (ROOT / "docs" / name).read_text() == text
        assert not (ROOT / "docs/generated" / name).exists()
    check_reference_files(ROOT)
    # This is the original CI regression, also a GitHub-source reader contract.
    assert validate_markdown(ROOT, ROOT / "docs/configuration.md") > 0


def test_repository_workflow_installs_locked_parser_before_validation():
    data = yaml.safe_load((ROOT / ".github/workflows/repository.yml").read_text())
    steps = data["jobs"]["repository"]["steps"]
    setup = next(i for i, step in enumerate(steps) if "astral-sh/setup-uv@" in step.get("uses", ""))
    sync = next(
        i for i, step in enumerate(steps) if step.get("run") == "uv sync --locked --group dev"
    )
    validate = next(
        i
        for i, step in enumerate(steps)
        if step.get("run") == "uv run python -m scripts.validate_plan"
    )
    assert setup < sync < validate
    assert all("continue-on-error" not in step for step in steps)


def test_actual_markdown_ignores_fenced_inline_and_indented_code(tmp_path):
    page = tmp_path / "example.md"
    (tmp_path / "real.md").write_text("# Target\n")
    page.write_text(
        "[Visible][target]\n\n[target]: real.md#heading\n\n"
        "![Image](real.md)\n\n[External](https://example.invalid/page)\n\n"
        "[Query](real.md?raw=true)\n\n[Local](#heading)\n\n"
        "`[Inline](missing.md)`\n\n```markdown\n[Fenced](missing.md)\n```\n\n"
        "    [Indented](missing.md)\n"
    )
    assert validate_markdown(tmp_path, page) == 3


@pytest.mark.parametrize(
    "text", ["[Broken](missing.md)", "![Broken](missing.png)", "[Broken][ref]\n\n[ref]: missing.md"]
)
def test_active_broken_links_still_fail(tmp_path, text):
    path = tmp_path / "page.md"
    path.write_text(text)
    with pytest.raises(ValueError, match="Broken link"):
        validate_markdown(tmp_path, path)


@pytest.mark.parametrize(
    "target",
    ["../outside.md", "%2e%2e/outside.md", "/absolute.md", "bad%5cpath.md", "bad%00path.md"],
)
def test_encoded_or_literal_unsafe_links_are_rejected(tmp_path, target):
    path = tmp_path / "page.md"
    path.write_text(f"[Unsafe]({target})\n")
    with pytest.raises(ValueError, match=r"Unsafe|escapes"):
        validate_markdown(tmp_path, path)


def test_links_cannot_escape_through_an_owned_symlink(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    (root / "linked.md").symlink_to(outside)
    page = root / "page.md"
    page.write_text("[Outside](linked.md)\n")
    with pytest.raises(ValueError, match="Broken link"):
        validate_markdown(root, page)


def test_exact_original_record_resolves_links_in_its_real_original_tree(tmp_path):
    root, archive, record = history_source(tmp_path)
    assert not (archive.parent / "sibling.md").exists()
    assert not (root / "docs/sibling.md").exists()
    contexts = original_contexts(root)
    assert contexts[archive].source == record["source"]
    assert validate_repository_links(root) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "bytes",
        "source",
        "commit",
        "checksum",
        "duplicate",
        "symlink",
        "source_escape",
        "path_escape",
        "non_list",
        "non_object",
        "non_markdown",
    ],
)
def test_history_context_is_exact_and_cannot_be_a_broad_archive_exemption(tmp_path, fault):
    root, archive, record = history_source(tmp_path)
    records = [record]
    if fault == "bytes":
        archive.write_text("[Changed](missing.md)\n")
    elif fault == "source":
        record["source"] = "docs/sibling.md"
    elif fault == "commit":
        record["commit"] = "HEAD"
    elif fault == "checksum":
        record["sha256"] = "not-a-hash"
    elif fault == "duplicate":
        records.append(dict(record))
    elif fault == "symlink":
        target = root / "other.md"
        archive.rename(target)
        archive.symlink_to(target)
    elif fault == "source_escape":
        record["source"] = "../old.md"
    elif fault == "path_escape":
        record["path"] = "../old.md"
    elif fault == "non_list":
        records = {}
    elif fault == "non_object":
        records = ["engineering/history"]
    else:
        record["source"] = "docs/data.json"
    save_records(root, records)
    with pytest.raises(ValueError):
        original_contexts(root)


def test_even_byte_exact_history_must_have_valid_links_at_the_original_source(tmp_path):
    root, _, _ = history_source(tmp_path, "[Broken original](absent.md)\n")
    with pytest.raises(ValueError, match="Broken link"):
        validate_repository_links(root)


def test_unregistered_neighbor_history_has_no_special_link_context(tmp_path):
    root, archive, _ = history_source(tmp_path)
    other = archive.parent / "other.md"
    other.write_text("[Broken neighbor](sibling.md)\n")
    git(root, "add", ".")
    with pytest.raises(ValueError, match=r"Broken link.*other.md"):
        validate_repository_links(root)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../out.md",
        "/absolute.md",
        "docs//old.md",
        "docs/./old.md",
        "docs/old\\name.md",
        "docs/old\nname.md",
    ],
)
def test_registered_paths_are_plain_repository_paths(path):
    with pytest.raises(ValueError):
        repository_path(path)
