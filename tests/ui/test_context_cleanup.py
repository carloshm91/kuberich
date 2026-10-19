"""Context rename/delete and finished-pod cleanup through the real UI (public behavior only)."""

import copy
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from textual.widgets import Input, SelectionList, Static

from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.ui.app import KubeRichApp
from kuberich.ui.context_admin import ContextEditScreen
from kuberich.ui.operations import ResourceOperationScreen
from tests.support.connections import namespaces
from tests.support.pods import pod
from tests.support.resources import collection, legacy_roots
from tests.support.workspace import stable_watch, wait_for


def write_kubeconfig(directory: Path, server: str, current: str = "owned-one") -> Path:
    data = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": current,
        "contexts": [
            {"name": name, "context": {"cluster": "owned", "user": "owned", "namespace": "team"}}
            for name in ("owned-one", "owned-two")
        ],
        "clusters": [{"name": "owned", "cluster": {"server": server}}],
        "users": [{"name": "owned", "user": {"token": "synthetic-token"}}],
    }
    path = directory / "config"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    path.chmod(0o600)
    return path


def make_app(path: Path, *, context: str | None = None, readonly: bool = False) -> KubeRichApp:
    request = ConnectionRequest(kubeconfig=str(path), context=context)
    return KubeRichApp(
        Settings(read_only=readonly),
        logging.getLogger("owned-context-cleanup"),
        catalog=load_catalog(request, {}),
        connection=request,
    )


def status(app: KubeRichApp) -> str:
    return str(app.status.content)


def table_names(app: KubeRichApp) -> list[str]:
    return [str(row.key.value) for row in app.context_table.ordered_rows]


async def command(pilot, text: str) -> None:
    await pilot.press("colon")
    await pilot.press(*text)
    await pilot.press("enter")
    await pilot.pause()


class PodApi:
    """Pods in namespace team with UID/version DELETE preconditions."""

    def __init__(self, *pods: dict) -> None:
        self.pods = {value["metadata"]["name"]: value for value in pods}
        self.deletes: list[tuple[str, dict]] = []

    async def handle(self, request: web.Request) -> web.StreamResponse:
        roots = legacy_roots()
        roots["/api/v1"]["resources"][0]["verbs"] = ["get", "list", "watch", "delete"]
        if request.path in roots:
            return web.json_response(roots[request.path])
        if request.path == "/api/v1/namespaces":
            return namespaces("team")
        if "watch" in request.query:
            return await stable_watch(request)
        name = request.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            body = await request.json()
            self.deletes.append((name, body))
            value = self.pods.get(name)
            if value is None:
                return web.Response(status=404)
            metadata = value["metadata"]
            expected = {"uid": metadata["uid"], "resourceVersion": metadata["resourceVersion"]}
            if body["preconditions"] != expected:
                return web.Response(status=409)
            del self.pods[name]
            return web.json_response(value)
        if request.path.startswith("/api/v1/namespaces/team/pods/"):
            value = self.pods.get(name)
            return web.json_response(value) if value else web.Response(status=404)
        return web.json_response(collection(*copy.deepcopy(list(self.pods.values()))))


@asynccontextmanager
async def pod_api(*pods: dict):
    fixture = PodApi(*pods)
    application = web.Application()
    application.router.add_route("*", "/{path:.*}", fixture.handle)
    runner = web.AppRunner(application, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}", fixture
    finally:
        await runner.cleanup()


def finished(name: str, phase: str, reason: str | None = None) -> dict:
    value = pod(name)
    value["status"]["phase"] = phase
    if reason:
        value["status"]["reason"] = reason
    return value


@pytest.mark.asyncio
async def test_rename_reviews_the_owning_file_then_saves_with_backup(tmp_path):
    path = write_kubeconfig(tmp_path, "http://127.0.0.1:9")
    app = make_app(path)
    async with app.run_test(size=(110, 30)) as pilot:
        await command(pilot, "ctx")
        await wait_for(lambda: table_names(app) == ["owned-one", "owned-two"])
        await pilot.press("down")
        await command(pilot, "rename short-two")
        await wait_for(lambda: isinstance(app.screen, ContextEditScreen))
        screen = app.screen
        await pilot.click("#context-edit-confirm")
        assert "owned-two" in path.read_text()  # Confirm stays disabled before Review
        await pilot.click("#context-edit-review")
        preview = screen.query_one("#context-edit-preview", Static)
        await wait_for(lambda: "short-two" in str(preview.content))
        assert f"File: {path}" in str(preview.content)
        assert "synthetic-token" not in str(preview.content)
        await pilot.click("#context-edit-confirm")
        await wait_for(lambda: not isinstance(app.screen, ContextEditScreen))
        await wait_for(lambda: "short-two" in table_names(app))
        assert table_names(app) == ["owned-one", "short-two"]
        assert "Renamed owned-two" in status(app) and ".kuberich-" in status(app)
    saved = yaml.safe_load(path.read_text())
    assert [entry["name"] for entry in saved["contexts"]] == ["owned-one", "short-two"]
    assert saved["users"][0]["user"]["token"] == "synthetic-token"
    assert len(list(tmp_path.glob("config.kuberich-*.bak"))) == 1


@pytest.mark.asyncio
async def test_deleting_the_current_context_needs_the_stronger_confirmation(tmp_path):
    path = write_kubeconfig(tmp_path, "http://127.0.0.1:9")
    app = make_app(path, context="owned-two")
    async with app.run_test(size=(110, 30)) as pilot:
        await command(pilot, "ctx")
        await wait_for(lambda: table_names(app) == ["owned-one", "owned-two"])
        await pilot.press("ctrl+d")
        await wait_for(lambda: isinstance(app.screen, ContextEditScreen))
        screen = app.screen
        await pilot.click("#context-edit-review")
        prompt = screen.query_one("#context-edit-prompt", Static)
        await wait_for(lambda: "DELETE CURRENT" in str(prompt.content))
        confirmation = screen.query_one("#context-edit-confirmation", Input)
        confirmation.value = "DELETE"
        await pilot.click("#context-edit-confirm")
        feedback = screen.query_one("#context-edit-feedback", Static)
        await wait_for(lambda: "exactly" in str(feedback.content))
        assert "owned-one" in path.read_text()
        confirmation.value = "DELETE CURRENT"
        await pilot.click("#context-edit-confirm")
        await wait_for(lambda: table_names(app) == ["owned-two"])
    saved = yaml.safe_load(path.read_text())
    assert "current-context" not in saved
    assert [entry["name"] for entry in saved["contexts"]] == ["owned-two"]


@pytest.mark.asyncio
async def test_the_connected_context_cannot_be_deleted_and_cancel_keeps_the_file(tmp_path):
    path = write_kubeconfig(tmp_path, "http://127.0.0.1:9")
    original = path.read_bytes()
    app = make_app(path, context="owned-two")
    async with app.run_test(size=(110, 30)) as pilot:
        await wait_for(lambda: app.sessions.client is not None)
        await command(pilot, "ctx")
        await wait_for(lambda: table_names(app) == ["owned-one", "owned-two"])
        await pilot.press("down")
        await command(pilot, "delete")
        await wait_for(lambda: isinstance(app.screen, ContextEditScreen))
        screen = app.screen
        await pilot.click("#context-edit-review")
        feedback = screen.query_one("#context-edit-feedback", Static)
        await wait_for(lambda: "Switch to another context" in str(feedback.content))
        await pilot.click("#context-edit-cancel")
        await wait_for(lambda: not isinstance(app.screen, ContextEditScreen))
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("config.kuberich-*.bak"))


@pytest.mark.asyncio
async def test_read_only_mode_blocks_context_edits_and_pod_cleanup(tmp_path):
    path = write_kubeconfig(tmp_path, "http://127.0.0.1:9")
    original = path.read_bytes()
    app = make_app(path, readonly=True)
    async with app.run_test(size=(110, 30)) as pilot:
        await command(pilot, "ctx")
        await wait_for(lambda: bool(table_names(app)))
        await command(pilot, "rename other")
        assert not isinstance(app.screen, ContextEditScreen)
        assert "read-only" in status(app).lower()
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert not isinstance(app.screen, ContextEditScreen)
        await command(pilot, "cleanup")
        assert not isinstance(app.screen, ResourceOperationScreen)
        assert "read-only" in status(app).lower()
    assert path.read_bytes() == original


@pytest.mark.asyncio
async def test_cleanup_preselects_finished_pods_and_reports_a_lost_race(tmp_path):
    pods = (
        pod("web"),
        finished("job-done", "Succeeded"),
        finished("job-evicted", "Failed", "Evicted"),
        finished("job-raced", "Succeeded"),
    )
    async with pod_api(*pods) as (url, api):
        app = make_app(write_kubeconfig(tmp_path, url))
        async with app.run_test(size=(120, 36)) as pilot:
            await wait_for(lambda: app.resources.row_count == 4)
            await command(pilot, "cleanup")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            targets = screen.query_one(SelectionList)
            labels = [str(targets.get_option_at_index(i).prompt) for i in range(targets.option_count)]
            assert len(labels) == 3 and not any("web" in label for label in labels)
            assert any("job-evicted · Failed (Evicted)" in label for label in labels)
            assert len(targets.selected) == 3
            await pilot.click("#operation-review")
            await wait_for(lambda: screen.intent is not None)
            assert not api.deletes
            api.pods["job-raced"]["metadata"]["resourceVersion"] = "changed-after-review"
            screen.query_one("#operation-count", Input).value = "DELETE 3"
            await pilot.click("#operation-confirm")
            feedback = screen.query_one("#operation-feedback", Static)
            await wait_for(lambda: len(api.deletes) == 3 and ":" in str(feedback.content))
            preview = str(screen.query_one("#operation-preview", Static).content)
            assert "job-raced" in preview
    assert sorted(name for name, _ in api.deletes) == ["job-done", "job-evicted", "job-raced"]
    assert set(api.pods) == {"web", "job-raced"}


@pytest.mark.asyncio
async def test_cleanup_without_finished_pods_explains_and_opens_nothing(tmp_path):
    async with pod_api(pod("web")) as (url, api):
        app = make_app(write_kubeconfig(tmp_path, url))
        async with app.run_test(size=(110, 30)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await command(pilot, "cleanup")
            assert "No completed or failed pods" in status(app)
            assert not isinstance(app.screen, ResourceOperationScreen)
            await command(pilot, "ctx")
            await command(pilot, "cleanup")
            assert "Open a connected :pods view" in status(app)
    assert not api.deletes
