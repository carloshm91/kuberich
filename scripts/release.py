"""Prepare, validate and deliver an already-qualified immutable release bundle."""

import argparse
import base64
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from packaging.version import Version

from scripts.check_supply_chain import (
    INPUT_FILES,
    ROOT,
    artifact_inventory,
    read_json,
    verify,
    write_json,
)
from scripts.release_notes import freeze, frozen_body, parse_preview
from scripts.release_policy import (
    OWNER,
    RELEASE_WORKFLOW,
    REPOSITORY,
    milestone_readiness,
    missing_files,
    publication_tag,
    release_preflight,
    release_tag,
    require_sha,
    reuse_artifact,
)
from scripts.supply_chain import digest


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    token: str = "",
    content_type: str = "application/json",
) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "kuberich-release/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            content = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise ValueError(f"Release API refused {method} (HTTP {error.code})") from None
    except urllib.error.URLError:
        raise ValueError("Release API unavailable") from None
    if len(content) > 4 * 1024 * 1024:
        raise ValueError("Release API response exceeds its bound")
    return json.loads(content)


class GitHub:
    def __init__(
        self,
        token: str,
        base: str = "https://api.github.com/",
        uploads: str = "https://uploads.github.com/",
    ) -> None:
        self.token = token
        self.base = base.rstrip("/") + "/"
        self.uploads = uploads.rstrip("/") + "/"

    def __call__(self, path: str, method: str = "GET", value: Any = None) -> Any:
        prefix = f"repos/{REPOSITORY}"
        segments = urllib.parse.unquote(path.split("?", 1)[0]).split("/")
        if (path != prefix and not path.startswith(prefix + "/")) or any(
            segment in {".", ".."} for segment in segments
        ):
            raise ValueError("Unexpected release API scope")
        return request(
            self.base + path,
            method,
            None if value is None else json.dumps(value).encode(),
            self.token,
        )

    def upload(self, release: int, path: Path) -> Any:
        url = f"{self.uploads}repos/{REPOSITORY}/releases/{release}/assets?name="
        return request(
            url + urllib.parse.quote(path.name, safe=""),
            "POST",
            path.read_bytes(),
            self.token,
            "application/octet-stream",
        )


def metadata(distribution: Path, version: str) -> None:
    if set(artifact_inventory(distribution)) != {
        f"kuberich-{version}-py3-none-any.whl",
        f"kuberich-{version}.tar.gz",
    }:
        raise ValueError("Distribution filenames must match the canonical version")
    for path in (distribution / name for name in artifact_inventory(distribution)):
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                names = [
                    name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
                ]
                if len(names) != 1:
                    raise ValueError("One wheel metadata record is required")
                content = archive.read(names[0])
        else:
            with tarfile.open(path) as archive:
                entries = [
                    item
                    for item in archive.getmembers()
                    if item.name.count("/") == 1 and item.name.endswith("/PKG-INFO")
                ]
                if len(entries) != 1 or not entries[0].isfile():
                    raise ValueError("One regular source metadata record is required")
                file = archive.extractfile(entries[0])
                if file is None:
                    raise ValueError("Source metadata is missing")
                content = file.read()
        parsed = BytesParser().parsebytes(content)
        if parsed["Name"] != "kuberich" or parsed["Version"] != version:
            raise ValueError("Distribution name/version does not match the release request")


def bundle_files(directory: Path) -> dict[str, str]:
    files = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Release bundles cannot contain symlinks")
        if path.is_file() and path.name not in {"release.json", "SHA256SUMS"}:
            files[path.relative_to(directory).as_posix()] = digest(path)
    return files


def require_source(root: Path, sha: str) -> None:
    current = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()
    paths = [
        "src",
        "scripts",
        "packaging",
        ".github/workflows",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "CHANGELOG.md",
        "docs/release-notes",
        "LICENSE",
        "NOTICE",
        ".gitignore",
        *INPUT_FILES,
    ]
    changed = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--", *paths],
        text=True,
        timeout=10,
    )
    if current != sha or changed:
        raise ValueError("Release requires the exact clean committed source and policy inputs")


def prepare(
    source: Path,
    output: Path,
    sha: str,
    version: str,
    *,
    candidate: bool = False,
    root: Path = ROOT,
    notes_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_sha(sha)
    if candidate:
        if str(Version(version)) != version:
            raise ValueError("Candidate version must be normalized")
        tag = None
    else:
        tag = release_tag(version)
        require_source(root, sha)
    distribution, security = source / "dist", source / "artifacts/security"
    verify(security, distribution, root)
    provenance = read_json(security / "provenance.json")
    if provenance["source_commit"] != sha:
        raise ValueError("Security evidence does not belong to the requested commit")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    if project["version"] != version:
        raise ValueError("Source version differs from requested release")
    metadata(distribution, version)
    notes = None if candidate else freeze(root, sha, version, notes_preview)
    if candidate and notes_preview is not None:
        raise ValueError("Local development bundles cannot use a public notes preview")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / "dist").mkdir()
    (output / "artifacts/security").mkdir(parents=True)
    for name in artifact_inventory(distribution):
        shutil.copyfile(distribution / name, output / "dist" / name)
    for name in {"provenance.json", *provenance["reports"]}:
        shutil.copyfile(security / name, output / "artifacts/security" / name)
    if notes is not None:
        (output / "release-notes.md").write_text(notes["body"], encoding="utf-8", newline="")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "commit": sha,
        "version": version,
        "tag": tag,
        "candidate_only": candidate,
        "notes": notes,
        "files": bundle_files(output),
    }
    write_json(output / "release.json", manifest)
    hashes = {**manifest["files"], "release.json": digest(output / "release.json")}
    (output / "SHA256SUMS").write_text(
        "".join(f"{value}  {name}\n" for name, value in sorted(hashes.items()))
    )
    verify_bundle(output, sha, version, root=root, candidate=candidate)
    return manifest


def verify_bundle(
    directory: Path,
    sha: str,
    version: str,
    *,
    root: Path = ROOT,
    candidate: bool = False,
    notes_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_sha(sha)
    if not candidate:
        require_source(root, sha)
    manifest: dict[str, Any] = read_json(directory / "release.json")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("repository") != REPOSITORY
        or manifest.get("commit") != sha
        or manifest.get("version") != version
        or manifest.get("candidate_only") is not candidate
        or manifest.get("tag") != (None if candidate else release_tag(version))
        or manifest.get("files") != bundle_files(directory)
    ):
        raise ValueError("Release bundle identity/content mismatch")
    expected = {**manifest["files"], "release.json": digest(directory / "release.json")}
    content = "".join(f"{value}  {name}\n" for name, value in sorted(expected.items()))
    digest(directory / "SHA256SUMS")
    if (directory / "SHA256SUMS").read_text() != content:
        raise ValueError("Release checksums do not match every supplied byte")
    verify(directory / "artifacts/security", directory / "dist", root)
    if read_json(directory / "artifacts/security/provenance.json")["source_commit"] != sha:
        raise ValueError("Release evidence source identity mismatch")
    metadata(directory / "dist", version)
    if candidate:
        if manifest.get("notes") is not None or notes_preview is not None:
            raise ValueError("Local development bundles cannot carry public release notes")
    else:
        frozen_body(directory, sha, version)
        notes = manifest["notes"]
        if notes != freeze(root, sha, version, notes["generated_preview"]):
            raise ValueError("Authored release notes differ from committed source bytes")
        if notes_preview is not None and notes_preview != notes["generated_preview"]:
            raise ValueError("Retry preview differs from the frozen original release notes")
    return manifest


def published_files(version: str, index: str) -> dict[str, str]:
    release_tag(version)
    if index not in {"pypi", "testpypi"}:
        raise ValueError("Unsupported publication index")
    host = "pypi.org" if index == "pypi" else "test.pypi.org"
    result = request(f"https://{host}/pypi/kuberich/{version}/json")
    existing = {}
    if result is not None:
        if result["info"]["name"] != "kuberich" or result["info"]["version"] != version:
            raise ValueError("PyPI release identity mismatch")
        for item in result["urls"]:
            if item["filename"] in existing or item.get("yanked") is not False:
                raise ValueError("PyPI release is duplicate or yanked")
            existing[item["filename"]] = item["digests"]["sha256"]
    return existing


def pypi_remaining(directory: Path, version: str, index: str, output: Path) -> list[str]:
    missing = missing_files(artifact_inventory(directory / "dist"), published_files(version, index))
    output.mkdir(exist_ok=False)
    for name in missing:
        shutil.copyfile(directory / "dist" / name, output / name)
    return missing


def immutable_tag(api: GitHub, sha: str, version: str) -> None:
    require_sha(sha)
    tag = publication_tag(version)
    prefix = f"repos/{REPOSITORY}"
    existing = api(f"{prefix}/git/ref/tags/{tag}")
    if existing is not None:
        if existing["object"]["type"] != "tag":
            raise ValueError("Existing release tag must be annotated")
        target = api(f"{prefix}/git/tags/{existing['object']['sha']}")
        if (
            target["tag"] != tag
            or target["object"]["type"] != "commit"
            or target["object"]["sha"] != sha
        ):
            raise ValueError("Existing release tag differs; it will never be moved")
        return
    annotated = api(
        f"{prefix}/git/tags",
        "POST",
        {
            "tag": tag,
            "message": f"KubeRich {version}\n",
            "object": sha,
            "type": "commit",
        },
    )
    require_sha(annotated["sha"])
    api(f"{prefix}/git/refs", "POST", {"ref": f"refs/tags/{tag}", "sha": annotated["sha"]})


def github_assets(api: GitHub, directory: Path, sha: str, version: str) -> list[str]:
    tag = publication_tag(version)
    body = frozen_body(directory, sha, version)
    prefix = f"repos/{REPOSITORY}"
    release = api(f"{prefix}/releases/tags/{tag}")
    if release is None:
        release = api(
            f"{prefix}/releases",
            "POST",
            {
                "tag_name": tag,
                "target_commitish": sha,
                "name": f"KubeRich {version}",
                "draft": True,
                "prerelease": Version(version).is_prerelease,
                "body": body,
                "generate_release_notes": False,
            },
        )
    if (
        release.get("tag_name") != tag
        or release.get("prerelease") is not Version(version).is_prerelease
        or release.get("target_commitish") != sha
        or release.get("name") != f"KubeRich {version}"
        or release.get("body") != body
    ):
        raise ValueError("Existing GitHub release identity differs")
    expected = {path.name: digest(path) for path in directory.rglob("*") if path.is_file()}
    if len(expected) != sum(path.is_file() for path in directory.rglob("*")):
        raise ValueError("Release attachment basenames must be unique")
    assets = api(f"{prefix}/releases/{int(release['id'])}/assets?per_page=100")
    existing = {}
    for asset in assets:
        name = asset["name"]
        value = asset.get("digest")
        if name in existing or not isinstance(value, str) or not value.startswith("sha256:"):
            raise ValueError("Existing GitHub assets lack unique SHA-256 identities")
        existing[name] = value[7:]
    missing = missing_files(expected, existing)
    files = {path.name: path for path in directory.rglob("*") if path.is_file()}
    if not release.get("draft") and missing:
        raise ValueError("Completed GitHub releases cannot receive replacement content")
    for name in missing:
        uploaded = api.upload(int(release["id"]), files[name])
        if uploaded.get("digest") != f"sha256:{expected[name]}":
            raise ValueError("Uploaded asset digest differs from the tested artifact")
    assets = api(f"{prefix}/releases/{int(release['id'])}/assets?per_page=100")
    final = {asset["name"]: asset.get("digest", "")[7:] for asset in assets}
    if len(final) != len(assets) or missing_files(expected, final):
        raise ValueError("GitHub release upload is incomplete")
    if release.get("draft"):
        completed = api(f"{prefix}/releases/{int(release['id'])}", "PATCH", {"draft": False})
        if completed.get("body") != body or completed.get("draft") is not False:
            raise ValueError("Published release body differs from the reviewed notes")
    return missing


def dispatch_identity(sha: str) -> None:
    expected = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": OWNER,
        "GITHUB_SHA": sha,
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ValueError("Publishing checks require a maintainer dispatch from main")
    if not os.environ.get("GITHUB_WORKFLOW_REF", "").startswith(
        f"{REPOSITORY}/{RELEASE_WORKFLOW}@"
    ):
        raise ValueError("Unexpected release workflow identity")


def preflight(api: GitHub, sha: str, version: str, index: str) -> dict[str, Any]:
    result = release_preflight(api, sha, version, index)
    contents = api(f"repos/{REPOSITORY}/contents/pyproject.toml?ref={sha}")
    project = tomllib.loads(base64.b64decode(contents["content"]).decode())["project"]
    if project.get("name") != "kuberich" or project.get("version") != version:
        raise ValueError("Requested source metadata version differs")
    values = {}
    for filename in ("backlog.json", "github-issues.json"):
        contents = api(f"repos/{REPOSITORY}/contents/docs/{filename}?ref={sha}")
        values[filename] = json.loads(base64.b64decode(contents["content"]))
    result["release_gate"] = milestone_readiness(
        api, version, values["backlog.json"], values["github-issues.json"]
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "preflight",
            "prepare",
            "verify",
            "tag",
            "pypi-missing",
            "pypi-verify",
            "github-assets",
        ),
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--index", choices=("pypi", "testpypi"), default="testpypi")
    parser.add_argument("--source", type=Path, default=Path("qualified"))
    parser.add_argument("--bundle", type=Path, default=Path("release-candidate"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--notes-preview",
        type=Path,
        help="owner-reviewed source/version-bound generated notes JSON",
    )
    parser.add_argument(
        "--notes-preview-env",
        action="store_true",
        help="read optional KUBERICH_RELEASE_NOTES_PREVIEW JSON from the dispatch environment",
    )
    parser.add_argument("--reuse-run", type=int, default=0)
    parser.add_argument(
        "--candidate", action="store_true", help="local-only preview; cannot publish"
    )
    args = parser.parse_args()
    try:
        if args.candidate and args.operation not in {"prepare", "verify"}:
            raise ValueError("Local candidates cannot publish or create tags")
        api = GitHub(os.environ.get("GH_TOKEN", ""))
        if args.notes_preview and args.notes_preview_env:
            raise ValueError("Choose a preview file or dispatch environment, not both")
        preview = (
            parse_preview(args.notes_preview.read_text(encoding="utf-8"))
            if args.notes_preview
            else parse_preview(os.environ.get("KUBERICH_RELEASE_NOTES_PREVIEW", ""))
            if args.notes_preview_env
            else None
        )
        if args.operation == "preflight":
            dispatch_identity(args.commit)
            result = preflight(api, args.commit, args.version, args.index)
            result["download_run_id"] = result["quality_run_id"]
            if args.reuse_run:
                result["artifact_id"] = reuse_artifact(
                    api, args.commit, args.version, args.reuse_run
                )
                result["download_run_id"] = args.reuse_run
            if args.output:
                write_json(args.output, result)
            if os.environ.get("GITHUB_OUTPUT"):
                with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                    output.write("".join(f"{key}={value}\n" for key, value in result.items()))
        elif args.operation == "prepare":
            result = prepare(
                args.source,
                args.bundle,
                args.commit,
                args.version,
                candidate=args.candidate,
                notes_preview=preview,
            )
        else:
            verify_bundle(
                args.bundle,
                args.commit,
                args.version,
                candidate=args.candidate,
                notes_preview=preview,
            )
            if args.operation == "verify":
                result = {"verified": True, "candidate_only": args.candidate}
            else:
                dispatch_identity(args.commit)
                preflight(api, args.commit, args.version, args.index)
                if args.operation == "tag":
                    if args.index != "pypi":
                        raise ValueError("TestPyPI does not create production tags")
                    immutable_tag(api, args.commit, args.version)
                    result = {"tag": release_tag(args.version)}
                elif args.operation == "pypi-missing":
                    if args.output is None:
                        raise ValueError("Missing-file staging requires --output")
                    missing = pypi_remaining(args.bundle, args.version, args.index, args.output)
                    result = {"missing": missing}
                    if os.environ.get("GITHUB_OUTPUT"):
                        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                            output.write(f"count={len(missing)}\n")
                elif args.operation == "pypi-verify":
                    if missing_files(
                        artifact_inventory(args.bundle / "dist"),
                        published_files(args.version, args.index),
                    ):
                        raise ValueError("Published index does not contain every tested artifact")
                    result = {"publication_verified": True, "index": args.index}
                else:
                    if args.index != "pypi" or missing_files(
                        artifact_inventory(args.bundle / "dist"),
                        published_files(args.version, "pypi"),
                    ):
                        raise ValueError(
                            "GitHub production delivery requires complete matching PyPI files"
                        )
                    immutable_tag(api, args.commit, args.version)
                    result = {"missing": github_assets(api, args.bundle, args.commit, args.version)}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        tarfile.TarError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as error:
        parser.exit(1, f"Release validation failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
