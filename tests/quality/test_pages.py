"""Publication trust boundaries, real owned HTTP checks and partial-upload receipts."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError

import pytest
import yaml

from scripts import pages
from scripts.build_site import HEADERS, ROOT, build
from tests.support.release_server import release_server

SHA = "a" * 40
ACCOUNT = "b" * 32
TOKEN = "owned-fixture-token-not-a-credential"
ORIGIN = "https://kuberich-site.pages.dev"


def project(name="kuberich-site", **changes):
    return {
        "name": name,
        "id": "owned-project",
        "production_branch": "main",
        "source": None,
        "subdomain": name + ".pages.dev",
        "canonical_deployment": {"id": "previous"},
        **changes,
    }


def deployed(name):
    return project(
        name,
        canonical_deployment={
            "id": "owned-new-deployment",
            "environment": "production",
            "url": "https://owned." + name + ".pages.dev",
            "latest_stage": {"status": "success"},
            "deployment_trigger": {"metadata": {"commit_hash": SHA}},
        },
    )


@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://kuberich-site.pages.dev",
        "https://pages.dev",
        "https://evil.example",
        "https://kuberich-site.pages.dev.evil.example",
        "https://token@kuberich-site.pages.dev",
        "https://kuberich-site.pages.dev:443",
        ORIGIN + "/unreviewed",
        ORIGIN + "?token=private",
        ORIGIN + "#fragment",
    ],
)
def test_only_https_provider_pages_origins_are_accepted(url):
    with pytest.raises(pages.PagesError):
        pages.pages_url(url)
    assert pages.pages_url(ORIGIN + "/") == ORIGIN
    assert pages.pages_url("https://owned.kuberich-docs.pages.dev")


def test_actual_api_requests_are_authenticated_and_redirects_cannot_forward_tokens(
    tmp_path, monkeypatch
):
    with release_server(tmp_path) as server:
        monkeypatch.setattr(pages, "API", server.url.rstrip("/"))
        path = f"/accounts/{ACCOUNT}/pages/projects/kuberich-site"
        server.reads[path] = {"success": True, "result": project()}
        assert pages.api_request(ACCOUNT, TOKEN, "GET", "/kuberich-site")["id"] == "owned-project"
        assert server.requests == [("GET", path, "Bearer " + TOKEN)]
        server.requests.clear()
        # /redirect uses the real server's 302 response. No second authenticated GET is sent.
        monkeypatch.setattr(pages, "API", server.url.rstrip("/") + "/redirect/../../..")
        request = pages.Request(
            server.url + "redirect", headers={"Authorization": "Bearer " + TOKEN}
        )
        with pytest.raises(pages.PagesError, match="redirects"):
            pages.build_opener(pages.NoApiRedirect()).open(request, timeout=5)
        assert server.requests == [("GET", "/redirect", "Bearer " + TOKEN)]


@pytest.mark.parametrize(
    "payload",
    [{"success": False, "errors": [{"message": TOKEN}]}, {"success": True, "result": []}, [TOKEN]],
)
def test_actual_api_rejects_unexpected_responses_without_echoing_private_body(
    tmp_path, monkeypatch, payload
):
    with release_server(tmp_path) as server:
        monkeypatch.setattr(pages, "API", server.url.rstrip("/"))
        server.reads[f"/accounts/{ACCOUNT}/pages/projects/kuberich-site"] = payload
        with pytest.raises(pages.PagesError) as raised:
            pages.api_request(ACCOUNT, TOKEN, "GET", "/kuberich-site")
        assert TOKEN not in str(raised.value)


def test_only_missing_approved_projects_are_created_and_existing_configuration_is_preserved(
    monkeypatch,
):
    calls = []

    def request(account, token, method, suffix, body=None):
        calls.append((method, suffix, body))
        if method == "GET":
            raise HTTPError("https://owned.invalid", 404, "missing", {}, None)
        return project()

    monkeypatch.setattr(pages, "api_request", request)
    assert pages.ensure_project(ACCOUNT, TOKEN, "kuberich-site")["id"] == "owned-project"
    assert calls == [
        ("GET", "/kuberich-site", None),
        ("POST", "", {"name": "kuberich-site", "production_branch": "main"}),
    ]
    calls.clear()
    with pytest.raises(pages.PagesError, match="scope"):
        pages.ensure_project(ACCOUNT, TOKEN, "unrelated-project")
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"name": "unrelated"},
        {"production_branch": "production"},
        {"source": {"type": "github"}},
        {"subdomain": "unrelated.example"},
    ],
)
def test_conflicting_projects_fail_without_reconfiguration(monkeypatch, change):
    calls = []
    monkeypatch.setattr(pages, "api_request", lambda *args: calls.append(args) or project(**change))
    with pytest.raises(pages.PagesError):
        pages.ensure_project(ACCOUNT, TOKEN, "kuberich-site")
    assert len(calls) == 1 and calls[0][2] == "GET"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_do_not_trigger_project_creation(monkeypatch, status):
    calls = []

    def denied(*args):
        calls.append(args)
        raise HTTPError("https://owned.invalid", status, "denied", {}, None)

    monkeypatch.setattr(pages, "api_request", denied)
    with pytest.raises(HTTPError):
        pages.ensure_project(ACCOUNT, TOKEN, "kuberich-site")
    assert len(calls) == 1


def owned_checkout(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "--quiet")
    (tmp_path / "owned.txt").write_text("owned")
    git("add", "owned.txt")
    git(
        "-c",
        "user.name=Owned Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Owned fixture",
    )
    return {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": pages.REPOSITORY,
        "GITHUB_WORKFLOW_REF": pages.REPOSITORY + "/.github/workflows/pages.yml@refs/heads/main",
        "GITHUB_SHA": git("rev-parse", "HEAD"),
    }


def test_dispatch_requires_canonical_manual_main_and_clean_exact_checkout(tmp_path):
    environment = owned_checkout(tmp_path)
    assert pages.dispatch_identity(environment, tmp_path) == environment["GITHUB_SHA"]
    for key, value in [
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_REPOSITORY", "fork/kuberich"),
        ("GITHUB_WORKFLOW_REF", "wrong-workflow"),
        ("GITHUB_SHA", "invalid"),
        ("GITHUB_SHA", SHA),
    ]:
        with pytest.raises(pages.PagesError):
            pages.dispatch_identity({**environment, key: value}, tmp_path)
    (tmp_path / "owned.txt").write_text("dirty")
    with pytest.raises(pages.PagesError, match="clean"):
        pages.dispatch_identity(environment, tmp_path)


@pytest.mark.parametrize("fault", [None, "bytes", "headers", "notfound"])
def test_live_verification_reads_real_owned_http_and_detects_drift_without_credentials(
    tmp_path, monkeypatch, fault
):
    output = tmp_path / "site"
    build(output)
    requests = []
    required = dict(
        line.strip().split(": ", 1) for line in HEADERS.splitlines() if line.startswith("  ")
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            file = output / "www" / self.path.lstrip("/")
            missing = not file.is_file()
            content = (output / "www/404.html" if missing else file).read_bytes()
            if fault == "bytes" and self.path == "/index.html":
                content += b"changed"
            self.send_response(200 if not missing or fault == "notfound" else 404)
            for key, value in required.items():
                if fault != "headers" or key != "Content-Security-Policy":
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    fetch = pages.fetch
    monkeypatch.setattr(
        pages,
        "fetch",
        lambda url: fetch(url.replace(ORIGIN, f"http://127.0.0.1:{server.server_port}")),
    )
    try:
        if fault:
            with pytest.raises(
                pages.PagesError,
                match={"bytes": "digest", "headers": "headers", "notfound": "404"}[fault],
            ):
                pages.verify_surface(output, "www", ORIGIN)
        else:
            result = pages.verify_surface(output, "www", ORIGIN)
            assert result["files_verified"] > 25 and result["not_found_verified"] is True
        assert requests and all(auth is None for _, auth in requests)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def publication_fixture(tmp_path, monkeypatch, script="process.exit(0);"):
    output, receipt, wrangler = (
        tmp_path / "site",
        tmp_path / "receipt.json",
        tmp_path / "wrangler.js",
    )
    build(output)
    wrangler.write_text(script)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    monkeypatch.setattr(pages, "dispatch_identity", lambda *args: SHA)
    monkeypatch.setattr(pages, "ensure_project", lambda account, token, name: project(name))
    monkeypatch.setattr(
        pages, "api_request", lambda account, token, method, path: deployed(path[1:])
    )
    monkeypatch.setattr(
        pages, "wait_verified", lambda output, surface, url: {"url": url, "files_verified": 31}
    )
    return output, receipt, wrangler


def test_both_actual_node_uploads_receive_scoped_argv_and_receipt_matches_checked_manifest(
    tmp_path, monkeypatch
):
    argument_file = tmp_path / "arguments.jsonl"
    script = (
        "require('node:fs').appendFileSync("
        + json.dumps(str(argument_file))
        + ", JSON.stringify(process.argv.slice(2))+'\\n');"
    )
    output, receipt, wrangler = publication_fixture(tmp_path, monkeypatch, script)
    result = pages.publish(output, receipt, wrangler, ROOT)
    assert result["status"] == "verified" and result["publication_performed"] is True
    assert json.loads(receipt.read_text()) == result
    arguments = [json.loads(line) for line in argument_file.read_text().splitlines()]
    assert len(arguments) == 2
    for args, surface in zip(arguments, ("www", "docs"), strict=True):
        assert args[:3] == ["pages", "deploy", str(output / surface)]
        assert args[3:] == [
            "--project-name",
            pages.PROJECTS[surface],
            "--branch",
            "main",
            "--commit-hash",
            SHA,
            "--commit-dirty=false",
        ]
    assert TOKEN not in receipt.read_text() and TOKEN not in argument_file.read_text()


@pytest.mark.parametrize("failure", ["first-upload", "second-upload", "identity", "verification"])
def test_failed_or_partial_publication_keeps_earlier_receipts_and_never_claims_success(
    tmp_path, monkeypatch, failure
):
    script = (
        "process.exit(1);"
        if failure == "first-upload"
        else (
            "process.exit(process.argv.includes('kuberich-docs') ? 1 : 0);"
            if failure == "second-upload"
            else "process.exit(0);"
        )
    )
    output, receipt, wrangler = publication_fixture(tmp_path, monkeypatch, script)
    if failure == "identity":
        wrong = deployed("kuberich-site")
        wrong["canonical_deployment"]["deployment_trigger"]["metadata"]["commit_hash"] = "c" * 40
        monkeypatch.setattr(pages, "api_request", lambda *args: wrong)
    if failure == "verification":

        def fail(*args):
            raise pages.PagesError("Public content mismatch")

        monkeypatch.setattr(pages, "wait_verified", fail)
    with pytest.raises(pages.PagesError):
        pages.publish(output, receipt, wrangler, ROOT)
    result = json.loads(receipt.read_text())
    assert result["status"] == "failed_or_partial" and result["upload_attempted"] is True
    if failure == "second-upload":
        assert result["surfaces"]["www"]["status"] == "verified"
    assert TOKEN not in receipt.read_text()


def test_invalid_credentials_and_second_project_conflict_do_not_upload(tmp_path, monkeypatch):
    output, receipt, wrangler = publication_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
    with pytest.raises(pages.PagesError, match="credentials"):
        pages.publish(output, receipt, wrangler, ROOT)
    assert not receipt.exists()
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    calls = []

    def ensure(account, token, name):
        calls.append(name)
        if name == "kuberich-docs":
            raise pages.PagesError("Existing project conflicts")
        return project()

    monkeypatch.setattr(pages, "ensure_project", ensure)
    with pytest.raises(pages.PagesError, match="conflicts"):
        pages.publish(output, receipt, wrangler, ROOT)
    assert calls == ["kuberich-site", "kuberich-docs"]
    assert json.loads(receipt.read_text())["upload_attempted"] is False


def test_verification_retry_is_bounded_and_a_failure_remains_failure(monkeypatch):
    attempts, sleeps = [], []

    def fail(*args):
        attempts.append(args)
        raise pages.PagesError("Not yet available")

    monkeypatch.setattr(pages, "verify_surface", fail)
    monkeypatch.setattr(pages.time, "sleep", sleeps.append)
    with pytest.raises(pages.PagesError, match="available"):
        pages.wait_verified(ROOT, "www", ORIGIN)
    assert len(attempts) == 12 and sleeps == [5] * 11


def test_workflow_never_publishes_from_pr_and_secrets_are_only_available_to_the_upload_step():
    workflow = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text())
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    prepare, publish = workflow["jobs"]["prepare"], workflow["jobs"]["publish"]
    assert "refs/heads/main" in prepare["if"] and pages.REPOSITORY in prepare["if"]
    assert "environment" not in prepare and "secrets." not in json.dumps(prepare)
    assert publish["needs"] == "prepare" and publish["environment"] == "release"
    credential_steps = [step for step in publish["steps"] if "secrets." in json.dumps(step)]
    assert (
        len(credential_steps) == 1
        and credential_steps[0]["run"] == "uv run python -m scripts.pages"
    )
    assert not any(
        "pip" in step.get("run", "") or "npm" in step.get("run", "") for step in credential_steps
    )
