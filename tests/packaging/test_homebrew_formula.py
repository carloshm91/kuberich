"""Consume a real audited canonical RC, then test update publication guards."""

import json
from pathlib import Path

import pytest

from scripts import homebrew
from scripts.homebrew import FORMULA, TapGitHub, formula, prepare, publish, resources
from scripts.release import GitHub, request
from scripts.release_policy import REPOSITORY
from tests.support.release_server import release_server
from tests.support.tap_server import TapServer


def test_real_rc_formula_has_exact_audited_sources_and_is_exclusive(canonical_release, tmp_path):
    source, bundle, sha = canonical_release
    output = tmp_path / "tap"
    report = prepare(bundle, source, output)
    text = (output / FORMULA).read_text()
    assert report["candidate"] and report["resources"] == 27
    assert f"# Source commit: {sha}" in text
    assert "system_site_packages: false" in text
    for item in resources(bundle, source):
        assert f'resource "{item["name"]}"' in text
        assert f'sha256 "{item["sha256"]}"' in text
        assert f'url "{item["url"]}"' in text
    assert (output / ".github/workflows/verify.yml").is_file()
    with pytest.raises(FileExistsError):
        prepare(bundle, source, output)
    assert (output / FORMULA).read_text() == text
    with pytest.raises(ValueError, match="verified local"):
        formula(bundle, source, "file:///unrelated/sdist.tar.gz", candidate=True)


@pytest.mark.parametrize(
    "fault", [None, "private", "draft", "tag", "hash", "yanked", "github_asset"]
)
def test_real_rc_owned_http_publication_guards(canonical_release, tmp_path, monkeypatch, fault):
    source, bundle, sha = canonical_release
    manifest = json.loads((bundle / "release.json").read_text())
    version = manifest["version"]
    for key, value in {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": sha,
        "GITHUB_ACTOR": "carloshm91",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    with (
        release_server(tmp_path / "source") as upstream,
        release_server(tmp_path / "tap", factory=TapServer) as tap,
    ):
        prefix = "/repos/" + REPOSITORY
        dist = {
            Path(name).name: value
            for name, value in manifest["files"].items()
            if name.startswith("dist/")
        }
        assets = [{"name": name, "digest": "sha256:" + value} for name, value in dist.items()]
        upstream.reads[prefix] = {"full_name": REPOSITORY, "private": fault == "private"}
        upstream.reads[prefix + f"/releases/tags/v{version.replace('rc', '-rc.')}"] = {
            "draft": fault == "draft",
            "assets": assets,
        }
        upstream.reads[prefix + f"/git/ref/tags/v{version.replace('rc', '-rc.')}"] = {
            "object": {"type": "tag", "sha": "b" * 40}
        }
        upstream.reads[prefix + "/git/tags/" + "b" * 40] = {
            "tag": f"v{version.replace('rc', '-rc.')}",
            "object": {"type": "commit", "sha": "c" * 40 if fault == "tag" else sha},
        }
        urls = [
            {
                "filename": name,
                "digests": {"sha256": value},
                "yanked": False,
                "url": f"https://files.pythonhosted.org/packages/owned/{name}",
            }
            for name, value in dist.items()
        ]
        if fault == "hash":
            urls[0]["digests"]["sha256"] = "f" * 64
        if fault == "yanked":
            urls[0]["yanked"] = True
        if fault == "github_asset":
            assets[0]["digest"] = "sha256:" + "f" * 64
        upstream.reads[f"/pypi/kuberich/{version}/json"] = {
            "info": {"name": "kuberich", "version": version},
            "urls": urls,
        }

        def local_index(url, *arguments, **keywords):
            if url == f"https://pypi.org/pypi/kuberich/{version}/json":
                return request(upstream.url + f"pypi/kuberich/{version}/json")
            assert url.startswith(tap.url)
            return request(url, *arguments, **keywords)

        monkeypatch.setattr(homebrew, "request", local_index)
        api = GitHub("synthetic-source-token", upstream.url)
        target = TapGitHub("synthetic-tap-token", tap.url)
        if fault:
            with pytest.raises(ValueError):
                publish(bundle, source, api, target)
            assert not tap.posts
        else:
            assert publish(bundle, source, api, target).endswith("/pull/1")
            branch = f"release/kuberich-{version}-{sha[:12]}"
            installed_text = tap.command("show", branch + ":" + FORMULA)
            assert f"# Source commit: {sha}" in installed_text and "file://" not in installed_text
            assert "Signed-off-by: Carlos Herrera <carloshm91@gmail.com>" in tap.command(
                "show", "--format=%B", "--no-patch", branch
            )
            assert all(
                "workflows" not in json.dumps(json.loads(body))
                for path, body in tap.posts
                if path.endswith("/git/trees")
            )
        assert not upstream.posts
