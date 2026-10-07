"""Homebrew source decisions and real owned HTTP/Git update transactions."""

import json

import pytest

from scripts.homebrew import FORMULA, TAP, TapGitHub, propose, resources, ruby, source_url
from tests.support.release_server import release_server
from tests.support.tap_server import TapServer

SHA = "a" * 40
TEXT = '# Source version: 0.0.1\nclass Kubetrol < Formula\n  url "file:///owned/kubetrol-0.0.1.tar.gz"\nend\n'


@pytest.mark.parametrize(
    "url",
    [
        "http://files.pythonhosted.org/packages/a/x.tar.gz",
        "https://evil.invalid/packages/a/x.tar.gz",
        "https://files.pythonhosted.org.evil/packages/a/x.tar.gz",
        "file:///tmp/x.tar.gz",
        "https://user@files.pythonhosted.org/packages/a/x.tar.gz",
        "https://files.pythonhosted.org:443/packages/a/x.tar.gz",
        "https://files.pythonhosted.org/packages/a/x.whl",
        "https://files.pythonhosted.org/packages/a/x.tar.gz?token=synthetic",
        "https://files.pythonhosted.org/packages/a/x.tar.gz#fragment",
        "https://files.pythonhosted.org/packages/%2e%2e/x.tar.gz",
        "https://files.pythonhosted.org/packages/#{bad}.tar.gz",
    ],
)
def test_source_urls_cannot_change_host_or_inject_ruby(url):
    with pytest.raises(ValueError):
        source_url(url)


@pytest.mark.parametrize("value", ["#{system('bad')}", "bad\nvalue", "bad\x1bvalue"])
def test_ruby_rejects_interpolation_and_controls(value):
    with pytest.raises(ValueError):
        ruby(value)


def test_source_resource_is_bound_to_exact_locked_version_and_sha(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    security = tmp_path / "bundle/artifacts/security"
    security.mkdir(parents=True)
    (security / "locked-inventory.json").write_text(json.dumps({"python": "3.14.8"}))
    (security / "runtime.txt").write_text("attrs==26.1.0\n")
    lock = root / "uv.lock"
    text = (
        '[[package]]\nname = "attrs"\nversion = "26.1.0"\n[package.sdist]\nurl = "https://files.pythonhosted.org/packages/a/attrs.tar.gz"\nhash = "sha256:'
        + "a" * 64
        + '"\n'
    )
    lock.write_text(text)
    assert resources(tmp_path / "bundle", root) == [
        {
            "name": "attrs",
            "url": "https://files.pythonhosted.org/packages/a/attrs.tar.gz",
            "sha256": "a" * 64,
        }
    ]
    for changed in (
        text + text,
        text.replace("26.1.0", "26.2.0"),
        text.replace("sha256:", "unknown:"),
        text.replace("files.pythonhosted.org", "evil.invalid"),
    ):
        lock.write_text(changed)
        with pytest.raises(ValueError):
            resources(tmp_path / "bundle", root)


def test_actual_update_git_objects_and_retry_never_change_main_or_duplicate_pr(tmp_path):
    with release_server(tmp_path, factory=TapServer) as server:
        api = TapGitHub("synthetic-tap-token", server.url)
        server.fail_pull = True
        with pytest.raises(ValueError, match="HTTP 503"):
            propose(api, TEXT, SHA, "0.0.1")
        assert server.command("rev-parse", "refs/heads/main").strip() == server.sha
        branch = "refs/heads/release/kubetrol-0.0.1-" + SHA[:12]
        original = server.command("rev-parse", branch).strip()
        assert server.command("show", branch + ":" + FORMULA) == TEXT
        before = len(server.posts)
        server.fail_pull = False
        assert propose(api, TEXT, SHA, "0.0.1").endswith("/pull/1")
        assert [path for path, _ in server.posts[before:]] == [f"/repos/{TAP}/pulls"]
        before = len(server.posts)
        assert propose(api, TEXT, SHA, "0.0.1").endswith("/pull/1")
        assert len(server.posts) == before and len(server.pulls) == 1
        with pytest.raises(ValueError, match="cannot be overwritten"):
            propose(api, TEXT + "# changed\n", SHA, "0.0.1")
        assert server.command("rev-parse", branch).strip() == original
        assert all(method != "PATCH" for method, _, _ in server.requests)
        assert all(token == "Bearer synthetic-tap-token" for _, _, token in server.requests)


def test_private_tap_and_api_scope_are_refused_before_writes(tmp_path):
    with release_server(tmp_path, factory=TapServer) as server:
        api = TapGitHub("synthetic-tap-token", server.url)
        server.private = True
        with pytest.raises(ValueError, match="owner-approved public"):
            propose(api, TEXT, SHA, "0.0.1")
        assert not server.posts
        for path in (
            "repos/evil/tap",
            f"repos/{TAP}-evil",
            f"repos/{TAP}/../secrets",
            f"repos/{TAP}/%2e%2e/secrets",
        ):
            with pytest.raises(ValueError):
                api(path)


def test_published_formula_cannot_be_downgraded_or_changed_at_same_version(tmp_path):
    with release_server(tmp_path, factory=TapServer) as server:
        api = TapGitHub("synthetic-tap-token", server.url)
        propose(api, TEXT, SHA, "0.0.1")
        branch = "refs/heads/release/kubetrol-0.0.1-" + SHA[:12]
        server.command("update-ref", "refs/heads/main", server.command("rev-parse", branch).strip())
        before = len(server.posts)
        assert propose(api, TEXT, SHA, "0.0.1") == "unchanged"
        for version, text in (
            ("0.0.0", TEXT.replace("0.0.1", "0.0.0")),
            ("0.0.1", TEXT + "# changed\n"),
        ):
            with pytest.raises(ValueError, match="cannot downgrade"):
                propose(api, text, SHA, version)
        assert len(server.posts) == before
