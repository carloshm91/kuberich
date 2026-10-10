"""Committed authored notes and optional reviewed previews remain immutable."""

import json
import shutil
import subprocess

import pytest

from scripts.release import GitHub, github_assets
from scripts.release_notes import MAX_NOTES_BYTES, freeze, frozen_body, parse_preview
from tests.support.release_notes import authored, commit_notes, note_bundle
from tests.support.release_server import release_server


def preview(sha, version="0.1.0"):
    return {
        "schema_version": 1,
        "commit": sha,
        "version": version,
        "tag": "v" + version,
        "body": "## Reviewed pull requests\n\nOwned transport fixture.\n",
    }


@pytest.mark.parametrize("combined", [False, True])
def test_http_publishes_exact_reviewed_body_and_identical_retry_is_readonly(tmp_path, combined):
    root, bundle = tmp_path / "source", tmp_path / "bundle"
    sha = commit_notes(root, "0.1.0")
    bundle.mkdir()
    (bundle / "wheel.whl").write_bytes(b"immutable fixture wheel")
    generated = preview(sha) if combined else None
    body = note_bundle(bundle, root, sha, "0.1.0", generated)
    assert body == authored("0.1.0") + ("\n\n" + generated["body"] if combined else "")
    assert frozen_body(bundle, sha, "0.1.0") == body
    with release_server(tmp_path / "http") as server:
        api = GitHub("synthetic-token", server.url, server.url)
        assert set(github_assets(api, bundle, sha, "0.1.0")) == {
            "wheel.whl",
            "release.json",
            "release-notes.md",
        }
        assert server.release["body"] == body and server.release["draft"] is False
        creation = next(
            json.loads(data) for path, data in server.posts if path.endswith("/releases")
        )
        assert creation["generate_release_notes"] is False
        assert not any("generate-notes" in path for _, path, _ in server.requests)
        before = len(server.posts)
        assert github_assets(api, bundle, sha, "0.1.0") == []
        assert len(server.posts) == before
        server.release["body"] += "\nEdited remotely"
        with pytest.raises(ValueError, match="identity differs"):
            github_assets(api, bundle, sha, "0.1.0")
        assert len(server.posts) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "file_changed",
        "manifest_changed",
        "wrong_source",
        "wrong_tag",
        "wrong_version",
        "invalid_preview",
        "control",
        "oversized",
    ],
)
def test_malformed_or_tampered_frozen_body_makes_zero_http_requests(tmp_path, mutation):
    root, bundle = tmp_path / "source", tmp_path / "bundle"
    sha = commit_notes(root, "0.1.0")
    bundle.mkdir()
    note_bundle(bundle, root, sha, "0.1.0", preview(sha))
    manifest = json.loads((bundle / "release.json").read_text())
    if mutation == "missing":
        (bundle / "release-notes.md").unlink()
    elif mutation == "file_changed":
        (bundle / "release-notes.md").write_text("unreviewed text")
    elif mutation == "manifest_changed":
        manifest["notes"]["body"] += "changed"
    elif mutation in {"wrong_source", "wrong_tag", "wrong_version"}:
        key = {"wrong_source": "commit", "wrong_tag": "tag", "wrong_version": "version"}[mutation]
        manifest[key] = "invalid identity"
    elif mutation == "invalid_preview":
        manifest["notes"]["generated_preview"]["tag"] = "v0.2.0"
    elif mutation == "control":
        manifest["notes"]["body"] += "\x1b[31m"
    else:
        manifest["notes"]["body"] = "x" * (MAX_NOTES_BYTES * 2 + 3)
    (bundle / "release.json").write_text(json.dumps(manifest))
    with release_server(tmp_path / "http") as server:
        with pytest.raises(ValueError):
            github_assets(GitHub("synthetic-token", server.url), bundle, sha, "0.1.0")
        assert server.requests == [] and server.posts == []


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "boolean_schema",
        "commit",
        "version",
        "tag",
        "extra",
        "empty",
        "control",
        "oversized",
    ],
)
def test_reviewed_preview_requires_exact_bounded_identity(tmp_path, mutation):
    sha = commit_notes(tmp_path, "0.1.0")
    generated = preview(sha)
    if mutation in {"schema", "boolean_schema"}:
        generated["schema_version"] = True if mutation == "boolean_schema" else 2
    elif mutation in {"commit", "version", "tag"}:
        generated[mutation] = "different"
    elif mutation == "extra":
        generated["unreviewed"] = True
    else:
        generated["body"] = {
            "empty": " ",
            "control": "unsafe\x7f",
            "oversized": "ü" * MAX_NOTES_BYTES,
        }[mutation]
    with pytest.raises(ValueError):
        freeze(tmp_path, sha, "0.1.0", generated)


@pytest.mark.parametrize("value", ["[]", "null", "{invalid}", "x" * (MAX_NOTES_BYTES + 1025)])
def test_cli_preview_parser_refuses_malformed_or_unbounded_json(value):
    with pytest.raises(ValueError):
        parse_preview(value)


def test_authored_notes_require_committed_exact_version_and_all_useful_sections(tmp_path):
    sha = commit_notes(tmp_path, "0.1.0")
    path = tmp_path / "docs/release-notes/0.1.0.md"
    assert parse_preview("") is None
    assert freeze(tmp_path, sha, "0.1.0")["body"] == path.read_text()
    path.write_text(authored("0.1.0") + "uncommitted body\n")
    with pytest.raises(ValueError, match="committed source bytes"):
        freeze(tmp_path, sha, "0.1.0")
    with pytest.raises(ValueError, match="committed per-version"):
        freeze(tmp_path, sha, "0.1.1")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=10).strip()


@pytest.mark.parametrize("mutation", ["ignored", "ancestor", "git_symlink", "oversized_blob"])
def test_real_git_notes_cannot_be_untracked_linked_or_an_unbounded_blob(tmp_path, mutation):
    root = tmp_path / "source"
    sha = commit_notes(root, "0.1.0")
    path = root / "docs/release-notes/0.1.0.md"
    if mutation == "ignored":
        git(root, "rm", "--cached", "docs/release-notes/0.1.0.md")
        (root / ".gitignore").write_text("docs/release-notes/\n")
        git(root, "add", ".gitignore")
    elif mutation == "ancestor":
        shutil.move(path.parent, tmp_path / "external-notes")
        path.parent.symlink_to(tmp_path / "external-notes", target_is_directory=True)
    elif mutation == "git_symlink":
        outside = tmp_path / "outside.md"
        outside.write_text(path.read_text())
        path.unlink()
        path.symlink_to(outside)
        git(root, "add", "docs/release-notes/0.1.0.md")
    else:
        path.write_text("x" * (MAX_NOTES_BYTES + 1))
        git(root, "add", "docs/release-notes/0.1.0.md")
    if mutation != "ancestor":
        git(
            root,
            "-c",
            "user.name=Release Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Owned invalid note source",
        )
        sha = git(root, "rev-parse", "HEAD")
        # Supply valid-looking regular filesystem bytes despite the committed bad object.
        if mutation == "git_symlink":
            path.unlink()
        if mutation in {"git_symlink", "oversized_blob"}:
            path.write_text(authored("0.1.0"))
    with pytest.raises(ValueError, match=r"committed|source commit"):
        freeze(root, sha, "0.1.0")
