"""Generate checked source formulas and propose immutable Homebrew updates."""

import argparse
import base64
import json
import os
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from packaging.version import Version

from scripts.check_supply_chain import ROOT, read_json, selected_requirements
from scripts.release import GitHub, dispatch_identity, request, verify_bundle
from scripts.release_policy import HASH, REPOSITORY, release_tag, require_sha
from scripts.supply_chain import digest

TAP = "carloshm91/homebrew-tap"
FORMULA = "Formula/kuberich.rb"
SCAFFOLD = ROOT / "packaging/homebrew"


def source_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "files.pythonhosted.org"
        or not parsed.path.startswith("/packages/")
        or not parsed.path.endswith(".tar.gz")
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[A-Za-z0-9/_.%-]+", parsed.path)
        or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))
    ):
        raise ValueError("Require an immutable Python-hosted sdist URL")
    return value


def ruby(value: str) -> str:
    # JSON escaping alone does not prevent Ruby interpolation.
    if "#" in value or any(ord(character) < 32 for character in value):
        raise ValueError("Unsafe Ruby string")
    return json.dumps(value)


def resources(bundle: Path, root: Path) -> list[dict[str, str]]:
    inventory = read_json(bundle / "artifacts/security/locked-inventory.json")
    expected = selected_requirements(
        (bundle / "artifacts/security/runtime.txt").read_text(), inventory["python"]
    )
    packages = tomllib.loads((root / "uv.lock").read_text())["package"]
    result = []
    for name, version in sorted(expected.items()):
        matches = [p for p in packages if p["name"] == name and p["version"] == version]
        if len(matches) != 1 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("Ambiguous or unsafe locked resource")
        source = matches[0].get("sdist", {})
        checksum = source.get("hash", "").removeprefix("sha256:")
        if not HASH.fullmatch(checksum):
            raise ValueError("Each runtime resource needs a source SHA-256")
        result.append({"name": name, "url": source_url(source["url"]), "sha256": checksum})
    return result


def formula(bundle: Path, root: Path, url: str, *, candidate: bool = False) -> str:
    manifest = read_json(bundle / "release.json")
    version, sha = manifest["version"], manifest["commit"]
    release_tag(version)
    verify_bundle(bundle, sha, version, root=root, candidate=manifest["candidate_only"])
    if manifest["candidate_only"]:
        raise ValueError("Homebrew requires a canonical RC or stable source")
    archives = [name for name in manifest["files"] if name.endswith(".tar.gz")]
    if len(archives) != 1:
        raise ValueError("Require exactly one source distribution")
    archive = bundle / archives[0]
    if candidate:
        if url != archive.resolve().as_uri():
            raise ValueError("A candidate URL must name the verified local sdist")
    else:
        source_url(url)
    blocks = "\n\n".join(
        f"  resource {ruby(item['name'])} do\n"
        f"    url {ruby(item['url'])}\n"
        f"    sha256 {ruby(item['sha256'])}\n  end"
        for item in resources(bundle, root)
    )
    return f"""# Source version: {version}
# Source commit: {sha}
class Kuberich < Formula
  include Language::Python::Virtualenv

  desc "Kubernetes terminal workspace built with Python and Textual"
  homepage "https://github.com/{REPOSITORY}"
  url {ruby(url)}
  sha256 {ruby(digest(archive))}
  license "MIT"

  depends_on "kubernetes-cli"
  depends_on "libyaml"
  depends_on "python@3.14"

{blocks}

  def install
    virtualenv_install_with_resources system_site_packages: false
  end

  test do
    ENV["XDG_CONFIG_HOME"] = testpath/"config"
    ENV["XDG_STATE_HOME"] = testpath/"state"
    assert_equal "kuberich #{{version}}\\n", shell_output("#{{bin}}/kuberich --version")
    assert_match "--context", shell_output("#{{bin}}/kuberich --help")
    assert_match "KubeRich preferences are valid", shell_output("#{{bin}}/kuberich config check")
    info = JSON.parse(shell_output("#{{bin}}/kuberich info"))
    assert_equal false, info.fetch("cluster_connected")
    assert_equal true, info.fetch("terminal_ui_available")
    site = libexec/"lib/python3.14/site-packages/kuberich"
    assert_path_exists site/"py.typed"
    assert_path_exists site/"ui/kuberich.tcss"
    system formula_opt_bin("python@3.14")/"python3.14", "-m", "pip",
           "--python", libexec/"bin/python", "check"
  end
end
"""


def prepare(bundle: Path, root: Path, output: Path) -> dict[str, Any]:
    archive = next((bundle / "dist").glob("*.tar.gz"))
    text = formula(bundle, root, archive.resolve().as_uri(), candidate=True)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(SCAFFOLD, output, dirs_exist_ok=True)
    path = output / FORMULA
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return {"candidate": True, "formula": str(path), "resources": len(resources(bundle, root))}


class TapGitHub:
    def __init__(self, token: str, base: str = "https://api.github.com/") -> None:
        self.token = token
        self.base = base.rstrip("/") + "/"

    def __call__(self, path: str, method: str = "GET", value: Any = None) -> Any:
        prefix = f"repos/{TAP}"
        if (path != prefix and not path.startswith(prefix + "/")) or any(
            part in {".", ".."} for part in unquote(urlsplit(path).path).split("/")
        ):
            raise ValueError("Tap API outside its scope")
        return request(
            self.base + path,
            method,
            None if value is None else json.dumps(value).encode(),
            self.token,
        )


def propose(api: TapGitHub, text: str, sha: str, version: str) -> str:
    """Create an immutable update branch/PR; never merge or replace a ref."""
    require_sha(sha)
    release_tag(version)
    declared = re.search(r"^# Source version: ([^\n]+)$", text, re.M)
    if declared is None or declared[1] != version:
        raise ValueError("Formula source version differs from the update request")
    prefix = f"repos/{TAP}"
    repo = api(prefix)
    if (
        repo.get("full_name") != TAP
        or repo.get("private") is not False
        or repo.get("default_branch") != "main"
    ):
        raise ValueError("Require the owner-approved public tap with main")
    current = api(f"{prefix}/contents/{FORMULA}?ref=main")
    if current is not None:
        old = base64.b64decode("".join(current["content"].splitlines()), validate=True).decode()
        match = re.search(r"^# Source version: ([^\n]+)$", old, re.M)
        if match is None or Version(version) <= Version(match[1]):
            if old != text:
                raise ValueError("Homebrew update cannot downgrade or replace an existing version")
            return "unchanged"
    branch = f"release/kuberich-{version}-{sha[:12]}"
    files = {FORMULA: text}
    # Initial CI belongs to the maintainer-owned scaffold; the update token
    # only changes the formula and needs no workflow-write permission.
    ref = api(f"{prefix}/git/ref/heads/{branch}")
    if ref is None:
        main = api(f"{prefix}/git/ref/heads/main")["object"]["sha"]
        require_sha(main)
        base = api(f"{prefix}/git/commits/{main}")["tree"]["sha"]
        entries = []
        for name, content in sorted(files.items()):
            blob = api(f"{prefix}/git/blobs", "POST", {"content": content, "encoding": "utf-8"})[
                "sha"
            ]
            require_sha(blob)
            entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob})
        tree = api(f"{prefix}/git/trees", "POST", {"base_tree": base, "tree": entries})["sha"]
        require_sha(tree)
        commit = api(
            f"{prefix}/git/commits",
            "POST",
            {
                "tree": tree,
                "parents": [main],
                "message": f"build(homebrew): update kuberich to {version}\n\nSource: {sha}\n\nSigned-off-by: Carlos Herrera <carloshm91@gmail.com>",
                "author": {"name": "Carlos Herrera", "email": "carloshm91@gmail.com"},
            },
        )["sha"]
        require_sha(commit)
        api(f"{prefix}/git/refs", "POST", {"ref": "refs/heads/" + branch, "sha": commit})
    for name, content in files.items():
        existing = api(f"{prefix}/contents/{name}?ref={quote(branch, safe='')}")
        if (
            existing is None
            or base64.b64decode("".join(existing["content"].splitlines()), validate=True).decode()
            != content
        ):
            raise ValueError("Existing update branch differs; it cannot be overwritten")
    pulls = api(f"{prefix}/pulls?state=open&base=main&head=carloshm91:{quote(branch, safe='')}")
    if len(pulls) > 1:
        raise ValueError("Ambiguous update pull request")
    if pulls:
        return str(pulls[0]["html_url"])
    pull = api(
        f"{prefix}/pulls",
        "POST",
        {
            "title": f"build(homebrew): update kuberich to {version}",
            "head": branch,
            "base": "main",
            "body": f"Install the published immutable {version} sdist and audited hashed runtime resources.\n\nSource: `{sha}`. Run Linux/macOS tap checks before maintainer review and squash merge.\n\nGenerated by KubeRich's approved release job; no automatic merge.",
        },
    )
    return str(pull["html_url"])


def publish(bundle: Path, root: Path, source_api: GitHub, tap_api: TapGitHub) -> str:
    manifest = read_json(bundle / "release.json")
    sha, version = manifest["commit"], manifest["version"]
    dispatch_identity(sha)
    verify_bundle(bundle, sha, version, root=root)
    repo = source_api(f"repos/{REPOSITORY}")
    release = source_api(f"repos/{REPOSITORY}/releases/tags/{release_tag(version)}")
    if (
        repo.get("full_name") != REPOSITORY
        or repo.get("private") is not False
        or release is None
        or release.get("draft") is not False
    ):
        raise ValueError("Require a completed approved public release")
    ref = source_api(f"repos/{REPOSITORY}/git/ref/tags/{release_tag(version)}")
    if ref is None or ref["object"].get("type") != "tag":
        raise ValueError("Require the annotated published source tag")
    tag = source_api(f"repos/{REPOSITORY}/git/tags/{ref['object']['sha']}")
    if (
        tag.get("tag") != release_tag(version)
        or tag["object"].get("type") != "commit"
        or tag["object"].get("sha") != sha
    ):
        raise ValueError("Published tag differs from source commit")
    expected = {
        Path(name).name: value
        for name, value in manifest["files"].items()
        if name.startswith("dist/")
    }
    data = request(f"https://pypi.org/pypi/kuberich/{version}/json")
    if data is None or data["info"].get("name") != "kuberich" or data["info"]["version"] != version:
        raise ValueError("Require complete published PyPI artifacts")
    actual = {
        item["filename"]: item["digests"]["sha256"] for item in data["urls"] if not item["yanked"]
    }
    if len(data["urls"]) != len(expected) or actual != expected:
        raise ValueError("Published PyPI bytes differ from the tested candidate")
    assets = [item for item in release["assets"] if item["name"] in expected]
    if (
        len(assets) != len(expected)
        or {item["name"]: item.get("digest", "")[7:] for item in assets} != expected
    ):
        raise ValueError("Published GitHub distribution bytes differ")
    archive = next(item for item in data["urls"] if item["filename"].endswith(".tar.gz"))
    return propose(tap_api, formula(bundle, root, archive["url"]), sha, version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "publish"))
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/homebrew-candidate"))
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            result: Any = prepare(args.bundle, args.source, args.output)
        else:
            if not os.environ.get("HOMEBREW_TAP_TOKEN"):
                raise ValueError("Configure a token limited to the approved tap repository")
            result = {
                "pull_request": publish(
                    args.bundle,
                    args.source,
                    GitHub(os.environ.get("GH_TOKEN", "")),
                    TapGitHub(os.environ["HOMEBREW_TAP_TOKEN"]),
                )
            }
        print(json.dumps(result))
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
        print(f"Homebrew preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
