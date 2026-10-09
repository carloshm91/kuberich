"""Publish checked development site bytes; credentials stay in the protected job."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from scripts.build_site import HEADERS, MARKER
from scripts.check_site import verify

API = "https://api.cloudflare.com/client/v4"
PROJECTS = {"www": "kuberich-site", "docs": "kuberich-docs"}
REPOSITORY = "carloshm91/kuberich"


class PagesError(Exception):
    """A bounded publication error containing no provider response or credentials."""


class NoApiRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise PagesError("Authenticated API redirects are forbidden")


def dispatch_identity(environment: dict[str, str], checkout: Path) -> str:
    expected = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/pages.yml@refs/heads/main",
    }
    if any(environment.get(key) != value for key, value in expected.items()):
        raise PagesError("Publication requires the canonical main-only manual workflow")
    sha = environment.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PagesError("Missing exact source commit")
    actual = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, timeout=15
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
        text=True,
        timeout=15,
    )
    if actual != sha or dirty:
        raise PagesError("Publication requires the clean exact committed source")
    return sha


def api_request(
    account: str, token: str, method: str, suffix: str, body: dict[str, str] | None = None
) -> dict[str, Any]:
    request = Request(
        f"{API}/accounts/{account}/pages/projects{suffix}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    with build_opener(NoApiRedirect()).open(request, timeout=30) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise PagesError("Provider response exceeds the bounded limit")
    document = json.loads(payload)
    if not isinstance(document, dict) or document.get("success") is not True:
        raise PagesError("Cloudflare API did not report success")
    result = document.get("result")
    if not isinstance(result, dict):
        raise PagesError("Cloudflare API returned an unexpected project response")
    return result


def pages_url(value: object) -> str:
    if not isinstance(value, str):
        raise PagesError("Missing provider Pages URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)?\.pages\.dev", parsed.netloc)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise PagesError("Unexpected provider Pages URL")
    return value.rstrip("/")


def ensure_project(account: str, token: str, name: str) -> dict[str, Any]:
    if name not in PROJECTS.values():
        raise PagesError("Project is outside the approved website scope")
    try:
        project = api_request(account, token, "GET", f"/{name}")
    except HTTPError as error:
        if error.code != 404:
            raise
        project = api_request(
            account, token, "POST", "", {"name": name, "production_branch": "main"}
        )
    if (
        project.get("name") != name
        or project.get("production_branch") != "main"
        or project.get("source") is not None
    ):
        raise PagesError("Existing project conflicts with the approved Direct Upload configuration")
    pages_url("https://" + str(project.get("subdomain", "")))
    return project


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    request = Request(
        url, headers={"Accept-Encoding": "identity", "User-Agent": "KubeRich-site-verifier"}
    )
    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        if error.code != 404:
            raise
        response = error
    with response:
        final = urlsplit(response.geturl())
        original = urlsplit(url)
        if final.netloc != original.netloc or final.scheme != original.scheme:
            raise PagesError("Unexpected cross-host response redirect")
        content = response.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024:
            raise PagesError("Public response exceeds the bounded limit")
        return response.status, {k.lower(): v for k, v in response.headers.items()}, content


def verify_surface(output: Path, surface: str, url: str) -> dict[str, object]:
    origin = pages_url(url)
    manifest = json.loads((output / MARKER).read_text())
    required_headers = dict(
        line.strip().split(": ", 1) for line in HEADERS.splitlines() if line.startswith("  ")
    )
    checked = 0
    for relative, expected in manifest["files"].items():
        if not relative.startswith(surface + "/"):
            continue
        name = relative.removeprefix(surface + "/")
        if name == "_headers":
            continue  # Pages consumes this routing configuration; it is not a served asset.
        status, headers, content = fetch(origin + "/" + quote(name, safe="/"))
        if status not in ({200, 404} if name == "404.html" else {200}):
            raise PagesError(f"Unexpected public status for {surface}/{name}")
        if hashlib.sha256(content).hexdigest() != expected:
            raise PagesError(f"Public content digest mismatch for {surface}/{name}")
        if any(headers.get(key.lower()) != value for key, value in required_headers.items()):
            raise PagesError(f"Missing or changed public headers for {surface}/{name}")
        checked += 1
    if checked == 0:
        raise PagesError("No public files were verified")
    status, _, content = fetch(origin + "/__kuberich_missing_page_check__")
    expected_404 = manifest["files"][surface + "/404.html"]
    if status != 404 or hashlib.sha256(content).hexdigest() != expected_404:
        raise PagesError("Public 404 routing differs from the checked page")
    return {
        "url": origin,
        "files_verified": checked,
        "headers_verified": True,
        "not_found_verified": True,
    }


def wait_verified(output: Path, surface: str, url: str) -> dict[str, object]:
    # Bound DNS/CDN propagation without allowing a successful upload to hide failed verification.
    for attempt in range(12):
        try:
            return verify_surface(output, surface, url)
        except (OSError, ValueError, PagesError):
            if attempt == 11:
                raise
            time.sleep(5)
    raise AssertionError("Unreachable verification retry")


def publish(output: Path, receipt: Path, wrangler: Path, checkout: Path) -> dict[str, Any]:
    sha = dispatch_identity(dict(os.environ), checkout)
    verify(output, checkout)
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not re.fullmatch(r"[0-9a-f]{32}", account) or not token or token != token.strip():
        raise PagesError("Missing or invalid protected Cloudflare credentials")
    if not wrangler.is_file():
        raise PagesError("Pinned Wrangler executable is missing")
    result: dict[str, Any] = {
        "source_commit": sha,
        "build_manifest_sha256": hashlib.sha256((output / MARKER).read_bytes()).hexdigest(),
        "status": "preparing",
        "publication_performed": False,
        "upload_attempted": False,
        "surfaces": {},
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    try:
        # Resolve both first; do not start uploads if the second project conflicts.
        projects = {
            surface: ensure_project(account, token, name) for surface, name in PROJECTS.items()
        }
        for surface, name in PROJECTS.items():
            project = projects[surface]
            entry: dict[str, Any] = {
                "project": name,
                "project_id": project["id"],
                "previous_deployment_id": (project.get("canonical_deployment") or {}).get("id"),
                "status": "uploading",
            }
            result["surfaces"][surface] = entry
            # The provider may accept bytes before the CLI fails; record that possibility first.
            result["status"] = "publication_started"
            result["upload_attempted"] = True
            save()
            completed = subprocess.run(
                [
                    "node",
                    str(wrangler),
                    "pages",
                    "deploy",
                    str(output / surface),
                    "--project-name",
                    name,
                    "--branch",
                    "main",
                    "--commit-hash",
                    sha,
                    "--commit-dirty=false",
                ],
                capture_output=True,
                timeout=240,
                check=False,
            )
            if completed.returncode != 0:
                raise PagesError(
                    f"Wrangler upload failed for {surface}; inspect the project before retrying"
                )
            deployed = api_request(account, token, "GET", f"/{name}")
            deployment = deployed.get("canonical_deployment") or {}
            metadata = (deployment.get("deployment_trigger") or {}).get("metadata") or {}
            if (
                metadata.get("commit_hash") != sha
                or deployment.get("environment") != "production"
                or (deployment.get("latest_stage") or {}).get("status") != "success"
            ):
                raise PagesError(
                    "Cloudflare production deployment does not match this source commit"
                )
            entry.update(
                {
                    "deployment_id": deployment["id"],
                    "deployment_url": pages_url(deployment.get("url")),
                    "status": "uploaded",
                }
            )
            result["publication_performed"] = True
            save()
            entry["deployment_verification"] = wait_verified(
                output, surface, entry["deployment_url"]
            )
            origin = pages_url("https://" + str(deployed["subdomain"]))
            entry["production_verification"] = wait_verified(output, surface, origin)
            entry["status"] = "verified"
            save()
        result["status"] = "verified"
        save()
        return result
    except Exception:
        result["status"] = "failed_or_partial"
        save()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/site"))
    parser.add_argument("--receipt", type=Path, default=Path("artifacts/pages/publication.json"))
    parser.add_argument(
        "--wrangler",
        type=Path,
        default=Path("artifacts/pages-tools/node_modules/wrangler/bin/wrangler.js"),
    )
    args = parser.parse_args()
    try:
        result = publish(args.output.resolve(), args.receipt, args.wrangler.resolve(), Path.cwd())
    except PagesError as error:
        print(f"Pages publication failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Do not print raw provider/HTTP/subprocess errors, which can contain sensitive material.
        print(
            "Pages publication failed; inspect the retained receipt and Cloudflare project status",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
