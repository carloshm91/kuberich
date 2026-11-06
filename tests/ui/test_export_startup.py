"""The installed command's browser route stays local through mount, refresh and Back."""

import asyncio
import json
import logging

import pytest
from aiohttp import web
from textual.events import ScreenResume, ScreenSuspend
from textual.messages import InvokeLater
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import parse_document
from kuberich.config.store import write_config
from kuberich.domain.connections import ConnectionRequest
from kuberich.errors import AppError
from kuberich.services import sessions as session_module
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command
from kuberich.services.sessions import SessionService
from kuberich.services.updates import UpdateService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.appearance_controller import AppearanceController
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.artifact_viewer import ArtifactViewerScreen
from kuberich.ui.export_review import ArtifactConfirmation
from kuberich.ui.workspace_screen import WorkspaceScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_artifact_viewer import viewer_ready
from tests.ui.test_export_review import sensitive_ref, service_for


def startup_trace(app, lifecycle, api_requests):
    view = app.workspace.store.observation
    frame = app.presenter.export_frame
    return {
        "lifecycle": lifecycle,
        "current_screen": type(app.screen).__name__,
        "root_current": app.screen_stack[0].is_current,
        "root_foreground": app.screen_stack[-1] is app.screen_stack[0],
        "foreground_active": app.views.foreground.active,
        "foreground_closed": app.views.foreground.closed,
        "session_state": app.sessions.observation.state.name,
        "session_namespace": app.sessions.observation.namespace,
        "view_status": view.status.name,
        "view_revision": view.revision,
        "snapshot_items": len(view.snapshot.items) if view.snapshot is not None else None,
        "table_rows": app.resources.row_count,
        "table_display": app.resources.display,
        "export_frame": None
        if frame is None
        else {"route": frame[0].display_key, "query": frame[1], "revision": frame[2]},
        "api_requests": api_requests,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_exports_initial_route_skips_client_auth_and_opted_in_updates_until_explicit_retry(
    tmp_path, monkeypatch, size
):
    api_requests, connections, clients, updates = [], [], [], []
    lifecycle = []
    original_resume = WorkspaceScreen.on_screen_resume
    original_suspend = WorkspaceScreen.on_screen_suspend

    def observed(operation, name):
        def handle(screen, event):
            state = {
                "event": name,
                "current": screen.is_current,
                "active_before": screen.foreground.active,
                "stack": [type(item).__name__ for item in screen.app.screen_stack],
            }
            operation(screen, event)
            state["active_after"] = screen.foreground.active
            lifecycle.append(state)

        return handle

    monkeypatch.setattr(WorkspaceScreen, "on_screen_resume", observed(original_resume, "resume"))
    monkeypatch.setattr(WorkspaceScreen, "on_screen_suspend", observed(original_suspend, "suspend"))
    permitted = False
    original_connect, original_client = SessionService.connect, session_module.KubernetesSession

    async def connect(self, context, **kwargs):
        connections.append(context)
        assert permitted, "Local browser startup attempted a Kubernetes connection"
        return await original_connect(self, context, **kwargs)

    def client(*args, **kwargs):
        clients.append(True)
        assert permitted, "Local browser startup constructed a transport/authentication owner"
        return original_client(*args, **kwargs)

    def start_updates(self):
        updates.append("scheduled")

    async def check_updates(self):
        updates.append("requested")
        raise AssertionError("Offline startup must not request a public version")

    monkeypatch.setattr(SessionService, "connect", connect)
    monkeypatch.setattr(session_module, "KubernetesSession", client)
    monkeypatch.setattr(AppearanceController, "start_updates", start_updates)
    monkeypatch.setattr(UpdateService, "check", check_updates)

    async def ns(request):
        api_requests.append(request.path)
        return namespaces("team")

    async def resources(request):
        api_requests.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("owned-api")))

    document = parse_document({"schema_version": 1, "appearance": {"check_updates": True}})
    config = tmp_path / "preferences.yaml"
    write_config(config, document)
    source = PreferenceSource(ConfigLocation(config, True), document)
    service = service_for(tmp_path)
    async with workspace_api(ns, resources) as url:
        app = KubeRichApp(
            document.settings,
            logging.Logger("offline-exports", level=100),
            catalog=catalog_fixture(tmp_path, url),
            connection=ConnectionRequest(context="kuberich-test-one"),
            preferences=source,
            updates=UpdateService("0.3.0", tmp_path / "update-cache"),
            initial_command=Command.EXPORTS,
            export_service=service,
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
            browser = app.screen
            await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
            assert app.appearance.check_updates
            assert not api_requests and not clients and not connections and not updates
            assert app.sessions.client is None and app.sessions.observation.identity is None
            assert not service.default_root.exists()
            assert not (tmp_path / "update-cache").exists()
            browser.action_refresh()
            await wait_for(lambda: browser.operation_count == 0)
            await app.live_preferences.check()
            assert not api_requests and not clients and not connections and not updates
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert app.sessions.client is None and app.resources.row_count == 0
            assert not service.default_root.exists()
            assert not api_requests and not clients and not connections and not updates
            permitted = True
            await app.run_command(":retry")
            try:
                await wait_for(lambda: app.resources.row_count == 1)
            except TimeoutError:
                trace = startup_trace(app, lifecycle, api_requests)
                (tmp_path / "retry-timeout-trace.json").write_text(json.dumps(trace, indent=2))
                print(json.dumps(trace, indent=2))
                raise
            assert connections == ["kuberich-test-one"] and len(clients) == 1
            assert api_requests and not updates
        assert app.exports.operation_count == 0


class ExportCover(ModalScreen[None]):
    def compose(self):
        yield Static("A safe overlay over the retained viewer")


@pytest.mark.asyncio
async def test_sensitive_export_screenshot_guard_survives_overlay_and_clears_after_hide(tmp_path):
    service = service_for(tmp_path)
    ref = await sensitive_ref(service)
    app = KubeRichApp(
        parse_document({"schema_version": 1}).settings,
        logging.Logger("screenshot-export", level=100),
        export_service=service,
        updates=UpdateService("0.3.0", tmp_path / "update-cache"),
    )
    viewer = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=lambda _: None)
    async with app.run_test() as pilot:
        app.push_screen(viewer)
        await viewer_ready(viewer)
        assert not viewer.sensitive and "ui-secret-value" not in viewer.viewer.text
        assert "<svg" in app.export_screenshot()
        await pilot.click("#artifact-sensitive")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: viewer.sensitive and viewer.operation_count == 0)
        assert "ui-secret-value" in viewer.viewer.text
        cover = ExportCover()
        app.push_screen(cover)
        await wait_for(lambda: cover.is_mounted)
        with pytest.raises(AppError, match="Close sensitive views"):
            app.export_screenshot()
        assert app.deliver_screenshot("refused.svg", str(tmp_path)) is None
        assert not (tmp_path / "refused.svg").exists()
        await cover.dismiss()
        await pilot.click("#artifact-sensitive")
        await wait_for(lambda: not viewer.sensitive and viewer.operation_count == 0)
        assert "ui-secret-value" not in viewer.viewer.text
        assert "<svg" in app.export_screenshot()
        await pilot.press("escape")
    assert not viewer.viewer.text and app.exports.operation_count == 0


@pytest.mark.asyncio
async def test_delayed_root_suspend_cannot_block_explicit_retry_after_browser_back(
    tmp_path, monkeypatch
):
    delayed, lifecycle, api_requests = [], [], []
    original_post = WorkspaceScreen.post_message
    original_suspend = WorkspaceScreen.on_screen_suspend

    def post(screen, message):
        if isinstance(message, ScreenSuspend) and not delayed:
            # Retain the real event produced by pushing the startup browser;
            # deliver it after the same browser has completed Back.
            delayed.append((screen, message))
            return True
        return original_post(screen, message)

    def suspend(screen, event):
        before = screen.foreground.active
        original_suspend(screen, event)
        lifecycle.append(
            {
                "event": "delayed-suspend",
                "current": screen.is_current,
                "active_before": before,
                "active_after": screen.foreground.active,
            }
        )

    monkeypatch.setattr(WorkspaceScreen, "post_message", post)
    monkeypatch.setattr(WorkspaceScreen, "on_screen_suspend", suspend)

    async def ns(request):
        api_requests.append(request.path)
        return namespaces("team")

    async def resources(request):
        api_requests.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("owned-api")))

    service = service_for(tmp_path)
    async with workspace_api(ns, resources) as url:
        app = KubeRichApp(
            parse_document({"schema_version": 1}).settings,
            logging.Logger("delayed-root-export", level=100),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=Command.EXPORTS,
            export_service=service,
            updates=UpdateService("0.3.0", tmp_path / "update-cache"),
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
            browser = app.screen
            await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
            assert not api_requests and app.sessions.client is None
            assert len(delayed) == 1
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1 and app.views.foreground.active)
            root, event = delayed[0]
            assert root is app.screen and root.is_current
            assert original_post(root, event)
            await wait_for(lambda: len(lifecycle) == 1)
            await app.run_command(":retry")
            try:
                await wait_for(lambda: app.resources.row_count == 1)
            except TimeoutError:
                trace = startup_trace(app, lifecycle, api_requests)
                (tmp_path / "delayed-suspend-trace.json").write_text(json.dumps(trace, indent=2))
                print(json.dumps(trace, indent=2))
                raise
            assert lifecycle[0]["current"] and lifecycle[0]["active_after"]
            assert app.views.foreground.active and not app.views.foreground.closed
            assert app.sessions.client is not None and api_requests
        assert app.exports.operation_count == 0


@pytest.mark.asyncio
async def test_delayed_root_resume_does_not_activate_rendering_under_startup_browser(
    tmp_path, monkeypatch
):
    delayed, lifecycle = [], []
    original_post = WorkspaceScreen.post_message
    original_resume = WorkspaceScreen.on_screen_resume

    def post(screen, message):
        if isinstance(message, ScreenResume) and not delayed:
            delayed.append((screen, message))
            return True
        return original_post(screen, message)

    def resume(screen, event):
        before = screen.foreground.active
        original_resume(screen, event)
        lifecycle.append(
            {
                "foreground": screen.app.screen is screen,
                "visible": screen.is_current,
                "active_before": before,
                "active_after": screen.foreground.active,
            }
        )

    monkeypatch.setattr(WorkspaceScreen, "post_message", post)
    monkeypatch.setattr(WorkspaceScreen, "on_screen_resume", resume)
    app = KubeRichApp(
        parse_document({"schema_version": 1}).settings,
        logging.Logger("delayed-root-resume", level=100),
        initial_command=Command.EXPORTS,
        export_service=service_for(tmp_path),
        updates=UpdateService("0.3.0", tmp_path / "update-cache"),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
        browser = app.screen
        await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
        assert len(delayed) == 1 and not app.views.foreground.active
        root, event = delayed[0]
        assert root is not app.screen and original_post(root, event)
        await wait_for(lambda: len(lifecycle) == 1)
        assert lifecycle == [
            {"foreground": False, "visible": True, "active_before": False, "active_after": False}
        ]
        assert not app.views.foreground.active and not app.views.foreground.closed
        assert app.sessions.client is None
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1 and app.views.foreground.active)
        assert root.is_current and app.sessions.client is None
    assert app.views.foreground.closed and app.exports.operation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_callbacks", [1, 2])
async def test_discarded_browser_refresh_callback_rearms_after_actual_root_refresh(
    tmp_path, monkeypatch, lost_callbacks
):
    held, api_requests, clients, phases = [], [], [], []
    entered, returned, root_refreshed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_post = KubeRichApp.post_message
    original_connect, original_client = SessionService.connect, session_module.KubernetesSession

    def post(app, message):
        callback = message.callback if isinstance(message, InvokeLater) else None
        owner = getattr(getattr(callback, "func", None), "__self__", None)
        if (
            isinstance(owner, asyncio.Event)
            and (not held or owner is held[0][1])
            and len(held) < lost_callbacks
        ):
            held.append((message, owner))
            return True
        return original_post(app, message)

    async def connect(service, context, **kwargs):
        before = service.before_connect
        assert before is not None

        async def before_connect():
            entered.set()
            await before()
            returned.set()

        service.before_connect = before_connect
        return await original_connect(service, context, **kwargs)

    def client(*args, **kwargs):
        assert root_refreshed.is_set(), "Transport started before the observed root refresh"
        clients.append(True)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(KubeRichApp, "post_message", post)
    monkeypatch.setattr(SessionService, "connect", connect)
    monkeypatch.setattr(session_module, "KubernetesSession", client)

    async def ns(request):
        api_requests.append(request.path)
        return namespaces("team")

    async def resources(request):
        api_requests.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("owned-api")))

    service = service_for(tmp_path)
    async with workspace_api(ns, resources) as url:
        app = KubeRichApp(
            parse_document({"schema_version": 1}).settings,
            logging.Logger("discarded-browser-refresh", level=100),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=Command.EXPORTS,
            export_service=service,
            updates=UpdateService("0.3.0", tmp_path / "update-cache"),
        )
        try:
            async with app.run_test(size=(40, 12)):
                await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
                browser = app.screen
                await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
                assert len(held) == 1 and not clients and not api_requests
                _, readiness = held[0]
                # Suppress the actual initial readiness notification to model
                # a transient screen discarding its owned after-refresh queue.
                # The test injects no replacement readiness signal.
                await browser.action_back()
                await wait_for(lambda: len(app.screen_stack) == 1 and not browser.is_attached)
                assert app.call_after_refresh(root_refreshed.set)
                await wait_for(root_refreshed.is_set)
                phases.append(
                    {
                        "phase": "root-refreshed",
                        "readiness_set": readiness.is_set(),
                        "browser_attached": browser.is_attached,
                        "foreground": app.views.foreground.active,
                        "client_count": len(clients),
                        "api_requests": list(api_requests),
                    }
                )
                assert not clients and not api_requests
                if lost_callbacks == 2:
                    assert len(held) == 2 and not readiness.is_set()
                    await app.run_command(":exports")
                    await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
                    second = app.screen
                    await wait_for(
                        lambda: second.listing is not None and second.operation_count == 0
                    )
                    root_refreshed.clear()
                    await second.action_back()
                    await wait_for(lambda: len(app.screen_stack) == 1 and not second.is_attached)
                    assert app.call_after_refresh(root_refreshed.set)
                    await wait_for(root_refreshed.is_set)
                    phases.append(
                        {
                            "phase": "second-root-refreshed",
                            "readiness_set": readiness.is_set(),
                            "foreground": app.views.foreground.active,
                            "client_count": len(clients),
                            "api_requests": list(api_requests),
                        }
                    )
                    assert not clients and not api_requests
                await app.run_command(":retry")
                await wait_for(entered.is_set)
                try:
                    await wait_for(lambda: app.resources.row_count == 1)
                except TimeoutError:
                    trace = startup_trace(app, [], api_requests)
                    trace.update(
                        {
                            "phases": phases,
                            "readiness_set": readiness.is_set(),
                            "before_connect_entered": entered.is_set(),
                            "before_connect_returned": returned.is_set(),
                            "client_count": len(clients),
                        }
                    )
                    print(json.dumps(trace, indent=2))
                    (tmp_path / "discarded-readiness-timeout.json").write_text(
                        json.dumps(trace, indent=2)
                    )
                    raise
                assert returned.is_set() and readiness.is_set() and len(clients) == 1
                assert api_requests and app.views.foreground.active
        finally:
            (tmp_path / "discarded-readiness-phases.json").write_text(json.dumps(phases, indent=2))
        assert app.exports.operation_count == 0
