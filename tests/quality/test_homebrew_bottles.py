"""Bottle records, formula blocks and immutable tap storage behind an owned loopback API."""

import base64
import hashlib
import json
import sys

import pytest

from scripts import homebrew
from scripts.homebrew import (
    BOTTLE_BLOCK,
    BOTTLE_TAGS,
    FORMULA,
    TAP,
    TapGitHub,
    bottle_block,
    bottle_records,
    bottle_root,
    propose,
    publish_bottles,
    with_bottles,
)
from scripts.release_policy import REPOSITORY
from tests.support.release_server import release_server
from tests.support.tap_server import TapServer

SHA = "b" * 40
VERSION = "1.0.1"
ROOT_URL = bottle_root(VERSION)
TEXT = (
    f"# Source version: {VERSION}\n# Source commit: {SHA}\nclass Kuberich < Formula\n"
    '  url "https://files.pythonhosted.org/packages/a/kuberich-1.0.1.tar.gz"\n'
    '  license "Apache-2.0"\n\n  depends_on "python@3.14"\nend\n'
)
CELLARS = {"arm64_sequoia": ":any", "sequoia": "/usr/local/Cellar", "x86_64_linux": ":any"}


def commit_formula(server, text, parent, message):
    """Commit `Formula/kuberich.rb` on the owned tap and make it main."""
    blob = server.command("hash-object", "-w", "--stdin", input=text).strip()
    folder, name = FORMULA.split("/")
    inner = server.command("mktree", input=f"100644 blob {blob}\t{name}\n").strip()
    tree = server.command("mktree", input=f"040000 tree {inner}\t{folder}\n").strip()
    sha = server.command(
        "-c", "user.name=Tap", "-c", "user.email=tap@example.invalid", "commit-tree", tree,
        "-p", parent, "-m", message,
    ).strip()  # fmt: skip
    server.command("update-ref", "refs/heads/main", sha)
    return sha


def write_bottles(directory, revision="c" * 40, tags=BOTTLE_TAGS, **changes):
    directory.mkdir(exist_ok=True)
    for tag in tags:
        name = f"kuberich-{VERSION}.{tag}.bottle.tar.gz"
        (directory / name).write_bytes(tag.encode())
        item = {
            "filename": name,
            "local_filename": name.replace("-", "--", 1),
            "sha256": hashlib.sha256(tag.encode()).hexdigest(),
        }
        # Homebrew writes the cellar once per record, without the Ruby colon.
        cellar = CELLARS.get(tag, ":any").removeprefix(":")
        record = {
            "formula": {"pkg_version": VERSION, "tap_git_revision": revision},
            "bottle": {"root_url": ROOT_URL, "cellar": cellar, "rebuild": 0, "tags": {tag: item}},
        }
        change = changes.get(tag)
        if change is not None:
            change(record)
        (directory / f"kuberich--{VERSION}.{tag}.bottle.json").write_text(
            json.dumps({"kuberich/tap/kuberich": record})
        )
    return directory


def test_complete_bottle_records_are_read_with_their_archive_digests(tmp_path):
    records = bottle_records(write_bottles(tmp_path), VERSION, ROOT_URL)
    assert sorted(records) == sorted(BOTTLE_TAGS)
    assert records["sequoia"] == {
        "filename": f"kuberich-{VERSION}.sequoia.bottle.tar.gz",
        "sha256": hashlib.sha256(b"sequoia").hexdigest(),
        "cellar": "/usr/local/Cellar",
        "revision": "c" * 40,
    }


def test_published_sonoma_metadata_stays_readable_without_becoming_a_new_build(tmp_path):
    tags = ("arm64_sonoma", "sequoia", "x86_64_linux")
    directory = write_bottles(tmp_path, tags=tags)
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    records = bottle_records(directory, VERSION, ROOT_URL, tags)
    assert records["arm64_sonoma"]["filename"] == (f"kuberich-{VERSION}.arm64_sonoma.bottle.tar.gz")
    block = bottle_block(records, ROOT_URL)
    assert "arm64_sonoma:" in block and "arm64_sequoia:" not in block
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == original
    with pytest.raises(ValueError, match="Require exactly one bottle"):
        bottle_records(directory, VERSION, ROOT_URL)


def _set(path, value):
    def change(record):
        *parents, key = path
        target = record
        for name in parents:
            target = target[name]
        target[key] = value

    return change


def _tag(record):
    return next(iter(record["bottle"]["tags"].values()))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_set(("formula", "pkg_version"), "1.0.0"), "first 1.0.1 bottle"),
        (_set(("bottle", "root_url"), "https://evil.invalid"), "first 1.0.1 bottle"),
        (_set(("bottle", "rebuild"), 1), "first 1.0.1 bottle"),
        (lambda record: record["bottle"]["tags"].update(extra={}), "first 1.0.1 bottle"),
        (_set(("bottle", "cellar"), "/tmp/Cellar"), "verified archive"),
        (lambda record: _tag(record).update(cellar="/tmp/Cellar"), "verified archive"),
        (lambda record: _tag(record).update(sha256="0" * 64), "verified archive"),
        (lambda record: _tag(record).update(sha256="not-a-digest"), "verified archive"),
        (lambda record: _tag(record).update(filename="other.tar.gz"), "verified archive"),
    ],
)
def test_bottle_records_must_match_the_version_storage_and_archive(tmp_path, change, message):
    write_bottles(tmp_path, arm64_sequoia=change)
    with pytest.raises(ValueError, match=message):
        bottle_records(tmp_path, VERSION, ROOT_URL)


def test_bottle_records_refuse_missing_unsupported_or_untrusted_archives(tmp_path):
    with pytest.raises(ValueError, match="exactly one bottle for each"):
        bottle_records(write_bottles(tmp_path / "missing", tags=BOTTLE_TAGS[:2]), VERSION, ROOT_URL)
    single = write_bottles(tmp_path / "single", tags=["sequoia"])
    assert list(bottle_records(single, VERSION, ROOT_URL, ("sequoia",))) == ["sequoia"]
    with pytest.raises(ValueError, match="verified archive"):
        bottle_records(write_bottles(tmp_path / "other", tags=["monterey"]), VERSION, ROOT_URL)
    linked = write_bottles(tmp_path / "linked")
    archive = linked / f"kuberich-{VERSION}.sequoia.bottle.tar.gz"
    archive.rename(tmp_path / "outside.tar.gz")
    archive.symlink_to(tmp_path / "outside.tar.gz")
    with pytest.raises(ValueError, match="sequoia does not match"):
        bottle_records(linked, VERSION, ROOT_URL)
    duplicate = write_bottles(tmp_path / "duplicate")
    (duplicate / "copy.bottle.json").write_text(
        (duplicate / f"kuberich--{VERSION}.sequoia.bottle.json").read_text()
    )
    with pytest.raises(ValueError, match="sequoia does not match"):
        bottle_records(duplicate, VERSION, ROOT_URL)
    (tmp_path / "foreign").mkdir()
    (tmp_path / "foreign/a.bottle.json").write_text(json.dumps({"other/tap/other": {}}))
    with pytest.raises(ValueError, match="not a kuberich bottle record"):
        bottle_records(tmp_path / "foreign", VERSION, ROOT_URL)


def test_the_bottle_block_is_aligned_and_removes_cleanly():
    records = {
        tag: {"cellar": CELLARS[tag], "sha256": str(index) * 64}
        for index, tag in enumerate(BOTTLE_TAGS)
    }
    assert bottle_block(records, ROOT_URL) == (
        "  bottle do\n"
        f'    root_url "{ROOT_URL}"\n'
        f'    sha256 cellar: :any,                arm64_sequoia: "{"0" * 64}"\n'
        f'    sha256 cellar: "/usr/local/Cellar", sequoia:       "{"1" * 64}"\n'
        f'    sha256 cellar: :any,                x86_64_linux:  "{"2" * 64}"\n'
        "  end\n"
    )
    text = with_bottles(TEXT, records, ROOT_URL)
    assert '  license "Apache-2.0"\n\n  bottle do\n' in text
    assert BOTTLE_BLOCK.sub("", text, count=1) == TEXT
    with pytest.raises(ValueError, match="Add bottles once"):
        with_bottles(text, records, ROOT_URL)
    with pytest.raises(ValueError, match="Add bottles once"):
        with_bottles(TEXT.replace("  license", "  # license"), records, ROOT_URL)


@pytest.mark.parametrize(
    "records",
    [
        {},
        {"monterey": {"cellar": ":any", "sha256": "a" * 64}},
        {"sequoia": {"cellar": "/tmp/Cellar", "sha256": "a" * 64}},
        {"sequoia": {"cellar": ":any", "sha256": "#{bad}"}},
    ],
)
def test_the_bottle_block_refuses_unknown_tags_cellars_and_digests(records):
    with pytest.raises(ValueError, match="Bottle"):
        bottle_block(records, ROOT_URL)


@pytest.fixture
def tap(tmp_path, monkeypatch):
    for key, value in {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "carloshm91",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/bottles.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    with release_server(tmp_path / "server", factory=TapServer) as server:
        sha = commit_formula(server, TEXT, server.sha, "build(homebrew): update kuberich to 1.0.1")
        yield server, TapGitHub("synthetic-tap-token", server.url, server.url), sha


def test_bottles_are_stored_once_then_proposed_as_a_formula_only_change(tap, tmp_path):
    server, api, main = tap
    directory = write_bottles(tmp_path / "bottles", main)
    result = publish_bottles(directory, api)
    assert result == {
        "release": "https://github.com/owned/r/1",
        "pull_request": "https://github.com/owned-fixture/pull/1",
    }
    assert server.releases[0]["tag_name"] == f"kuberich-v{VERSION}"
    assert server.releases[0]["draft"] is False
    assert sorted(server.assets) == sorted(
        f"kuberich-{VERSION}.{tag}.bottle.tar.gz" for tag in BOTTLE_TAGS
    )
    branch = f"refs/heads/bottles/kuberich-{VERSION}-{SHA[:12]}"
    text = server.command("show", f"{branch}:{FORMULA}")
    assert BOTTLE_BLOCK.sub("", text, count=1) == TEXT and f'root_url "{ROOT_URL}"' in text
    assert server.pulls[0]["title"] == f"build(homebrew): add kuberich {VERSION} bottles"
    assert server.command("rev-parse", "refs/heads/main").strip() == main
    before = len(server.posts)
    assert publish_bottles(directory, api) == result
    assert len(server.posts) == before, "a retry neither uploads nor proposes again"


def test_a_partial_upload_resumes_the_same_draft(tap, tmp_path):
    server, api, main = tap
    directory = write_bottles(tmp_path / "bottles", main)
    server.fail_upload = f"kuberich-{VERSION}.sequoia.bottle.tar.gz"
    with pytest.raises(ValueError, match="HTTP 503"):
        publish_bottles(directory, api)
    assert server.releases[0]["draft"] is True and len(server.assets) == 1
    server.fail_upload = None
    publish_bottles(directory, api)
    assert len(server.releases) == 1 and len(server.assets) == 3


def test_bottle_storage_is_never_replaced_or_extended_after_publication(tap, tmp_path):
    server, api, main = tap
    directory = write_bottles(tmp_path / "bottles", main)
    server.corrupt_upload = True
    with pytest.raises(ValueError, match="Uploaded bottle digest differs"):
        publish_bottles(directory, api)
    server.corrupt_upload = False
    server.assets[f"kuberich-{VERSION}.arm64_sequoia.bottle.tar.gz"] = b"other bytes"
    with pytest.raises(ValueError, match="cannot be replaced"):
        publish_bottles(directory, api)
    server.assets.clear()
    server.releases[0]["draft"] = False
    with pytest.raises(ValueError, match="cannot receive new content"):
        publish_bottles(directory, api)
    server.releases.append(dict(server.releases[0]))
    with pytest.raises(ValueError, match="Ambiguous bottle release"):
        publish_bottles(directory, api)
    assert not server.pulls


def test_bottles_must_come_from_the_current_tap_formula_and_a_main_dispatch(
    tap, tmp_path, monkeypatch
):
    server, api, main = tap
    with pytest.raises(ValueError, match="current tap formula"):
        publish_bottles(write_bottles(tmp_path / "old", "d" * 40), api)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{REPOSITORY}/.github/workflows/other.yml@main")
    with pytest.raises(ValueError, match="maintainer dispatch from main"):
        publish_bottles(write_bottles(tmp_path / "new", main), api)
    assert not server.posts and not server.releases


def test_a_formula_without_source_identity_is_refused(tap, tmp_path):
    server, api, main = tap
    sha = commit_formula(server, "class Kuberich\nend\n", main, "unidentified")
    with pytest.raises(ValueError, match="source version and commit"):
        publish_bottles(write_bottles(tmp_path / "bottles", sha), api)


def test_only_adding_bottles_to_the_same_published_version_is_accepted(tap):
    _server, api, _main = tap
    records = {tag: {"cellar": ":any", "sha256": "a" * 64} for tag in BOTTLE_TAGS}
    bottled = with_bottles(TEXT, records, ROOT_URL)
    for text in (
        TEXT + "# changed\n",
        BOTTLE_BLOCK.sub("", bottled, count=1).replace("python@3.14", "python@3.13")
        + bottle_block(records, ROOT_URL),
    ):
        with pytest.raises(ValueError, match="cannot downgrade or replace"):
            propose(api, text, SHA, VERSION)
    assert propose(api, bottled, SHA, VERSION).endswith("/pull/1")


def test_the_command_requires_a_bundle_or_a_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HOMEBREW_TAP_TOKEN", raising=False)
    for arguments in (["prepare"], ["bottles"]):
        monkeypatch.setattr(sys, "argv", ["homebrew", *arguments])
        assert homebrew.main() == 1
    error = capsys.readouterr().err
    assert "--bundle is required" in error and "Configure a token" in error
    calls = []
    monkeypatch.setenv("HOMEBREW_TAP_TOKEN", "synthetic-tap-token")
    monkeypatch.setattr(
        homebrew, "publish_bottles", lambda path, api: calls.append((path, api.token)) or {}
    )
    monkeypatch.setattr(sys, "argv", ["homebrew", "bottles", "--bottles", str(tmp_path)])
    assert homebrew.main() == 0
    assert calls == [(tmp_path, "synthetic-tap-token")]


def test_uploads_go_to_the_tap_release_only(tap, tmp_path):
    server, api, _main = tap
    archive = tmp_path / "a b.tar.gz"
    archive.write_bytes(b"bytes")
    server.releases.append({"id": 1})
    uploaded = api.upload(1, archive)
    assert uploaded["digest"] == "sha256:" + hashlib.sha256(b"bytes").hexdigest()
    method, path, token = server.requests[-1]
    assert (method, path) == ("POST", f"/repos/{TAP}/releases/1/assets?name=a%20b.tar.gz")
    assert token == "Bearer synthetic-tap-token"
    assert base64.b64encode(server.assets["a b.tar.gz"]) == base64.b64encode(b"bytes")
