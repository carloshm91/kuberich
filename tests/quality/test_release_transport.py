"""Actual owned HTTP uploads, Git tags and failure/retry cleanup."""

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.release import (
    GitHub,
    dispatch_identity,
    github_assets,
    immutable_tag,
    preflight,
    request,
)
from scripts.release_policy import REPOSITORY, release_preflight
from tests.quality.test_release_policy import SHA, trusted_api
from tests.support.release_server import release_server


def test_actual_http_main_qualification_is_readonly_and_source_version_matches(tmp_path):
    with release_server(tmp_path) as server:
        server.reads = {"/" + path: value for path, value in trusted_api().items()}
        server.reads[f"/repos/{REPOSITORY}/contents/pyproject.toml?ref={SHA}"] = {
            "content": base64.b64encode(
                b'[project]\nname="kubetrol"\nversion="0.0.1rc1"\n'
            ).decode()
        }
        files = {
            "backlog.json": {
                "milestones": [{"title": "v0.0.1"}],
                "tasks": [{"id": "D04", "milestone": "v0.0.1", "requires": ["F01"]}],
            },
            "github-issues.json": {"issues": {"F01": {"number": 14}, "D04": {"number": 40}}},
        }
        for name, content in files.items():
            server.reads[f"/repos/{REPOSITORY}/contents/docs/{name}?ref={SHA}"] = {
                "content": base64.b64encode(json.dumps(content).encode()).decode()
            }
        server.reads[f"/repos/{REPOSITORY}/issues/14"] = {"number": 14, "state": "closed"}
        api = GitHub("synthetic-token", server.url)
        assert preflight(api, SHA, "0.0.1rc1", "pypi")["artifact_id"] == 18
        assert all(
            method == "GET" and auth == "Bearer synthetic-token"
            for method, _, auth in server.requests
        )
        assert server.posts == []
        with pytest.raises(ValueError, match="metadata version"):
            preflight(api, SHA, "0.0.1", "pypi")
        server.reads[f"/repos/{REPOSITORY}"]["private"] = True
        with pytest.raises(ValueError, match="Public launch"):
            release_preflight(api, SHA, "0.0.1", "pypi")
        assert server.posts == []


def test_real_annotated_git_tag_is_immutable_and_identical_retry_does_not_write(tmp_path):
    with release_server(tmp_path) as server:
        api = GitHub("synthetic-token", server.url)
        immutable_tag(api, server.sha, "0.0.1rc1")
        ref = server.command("rev-parse", "refs/tags/v0.0.1-rc.1").strip()
        assert server.command("cat-file", "-t", ref).strip() == "tag"
        assert server.command("rev-parse", "refs/tags/v0.0.1-rc.1^{}").strip() == server.sha
        posts = len(server.posts)
        immutable_tag(api, server.sha, "0.0.1rc1")
        assert len(server.posts) == posts
        with pytest.raises(ValueError, match="never be moved"):
            immutable_tag(api, "a" * 40, "0.0.1rc1")
        assert server.command("rev-parse", "refs/tags/v0.0.1-rc.1").strip() == ref
        assert len(server.posts) == posts


def test_lightweight_existing_tag_is_not_replaced(tmp_path):
    with release_server(tmp_path) as server:
        server.command("update-ref", "refs/tags/v0.0.1", server.sha)
        with pytest.raises(ValueError, match="annotated"):
            immutable_tag(GitHub("synthetic-token", server.url), server.sha, "0.0.1")
        assert server.posts == []


def test_racing_real_git_tag_creations_cannot_overwrite_the_first_reference(tmp_path):
    with release_server(tmp_path) as server:
        server.ref_barrier = threading.Barrier(2)
        api = GitHub("synthetic-token", server.url)

        def create():
            try:
                immutable_tag(api, server.sha, "0.0.1")
                return "created"
            except ValueError as error:
                assert "HTTP 422" in str(error)
                return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        assert sorted(results) == ["created", "refused"]
        assert server.command("rev-parse", "refs/tags/v0.0.1^{}").strip() == server.sha


def test_actual_partial_asset_upload_retries_only_missing_original_bytes(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "wheel.whl").write_bytes(b"exact tested wheel")
    (bundle / "z-source.tar.gz").write_bytes(b"exact tested source")
    with release_server(tmp_path / "service") as server:
        api = GitHub("synthetic-token", server.url, server.url)
        server.fail_upload = "z-source.tar.gz"
        with pytest.raises(ValueError, match="HTTP 503"):
            github_assets(api, bundle, server.sha, "0.0.1")
        assert server.assets == {"wheel.whl": b"exact tested wheel"}
        assert server.release["draft"] is True
        server.fail_upload = None
        assert github_assets(api, bundle, server.sha, "0.0.1") == ["z-source.tar.gz"]
        assert server.assets == {
            "wheel.whl": b"exact tested wheel",
            "z-source.tar.gz": b"exact tested source",
        }
        assert server.release["draft"] is False
        posts = len(server.posts)
        assert github_assets(api, bundle, server.sha, "0.0.1") == []
        assert len(server.posts) == posts
        (bundle / "wheel.whl").write_bytes(b"changed bytes")
        with pytest.raises(ValueError, match="never replace"):
            github_assets(api, bundle, server.sha, "0.0.1")
        assert server.assets["wheel.whl"] == b"exact tested wheel"
        assert len(server.posts) == posts


def test_wrong_uploaded_hash_never_publishes_draft(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "wheel.whl").write_bytes(b"candidate")
    with release_server(tmp_path / "service") as server:
        server.corrupt_upload = True
        with pytest.raises(ValueError, match="digest differs"):
            github_assets(
                GitHub("synthetic-token", server.url, server.url), bundle, server.sha, "0.0.1"
            )
        assert server.release["draft"] is True


def test_bounded_api_refuses_redirects_and_does_not_disclose_error_body(tmp_path):
    with release_server(tmp_path) as server:
        for path, message in (("denied", "HTTP 403"), ("redirect", "HTTP 302"), ("large", "bound")):
            with pytest.raises(ValueError, match=message) as error:
                request(server.url + path, token="synthetic-token")
            assert "synthetic-token" not in str(error.value) and "must not be printed" not in str(
                error.value
            )
        assert not any(path == "/target" for _, path, _ in server.requests)


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_ACTOR", "contributor"),
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_REPOSITORY", "fork/kubetrol"),
        ("GITHUB_SHA", "b" * 40),
        ("GITHUB_WORKFLOW_REF", "carloshm91/kubetrol/.github/workflows/other.yml@refs/heads/main"),
    ],
)
def test_only_owner_main_dispatch_can_reach_publication_checks(monkeypatch, key, value):
    variables = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "carloshm91",
        "GITHUB_SHA": SHA,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
    }
    for name, content in variables.items():
        monkeypatch.setenv(name, content)
    dispatch_identity(SHA)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        dispatch_identity(SHA)
