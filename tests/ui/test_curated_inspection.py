"""Physical curated links, truthful captures and detached Inspector ownership over HTTP."""

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.config.forwarding import ForwardPreferences
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.services.access import AccessPolicy
from kuberich.services.curated_navigation import CuratedOrigin
from kuberich.services.mutations import MutationManager
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.inspection import InspectionScreen
from kuberich.ui.resource_operations import OperationContext, ResourceOperations
from kuberich.ui.target_capture import CapturedResource
from tests.support.curated_navigation import PODS, SOURCE, TARGET, navigation_fixture, path, payload
from tests.support.curated_scaling import record
from tests.support.resources import collection
from tests.support.workspace import wait_for


class InspectionHost(App):
    def __init__(self, client, api, *, source_resource=SOURCE):
        super().__init__()
        self.client, self.api = client, api
        self.source_resource = source_resource
        self.valid, self.revision = True, 13
        self.handoffs, self.notices = [], []
        self.session = SessionIdentity(client.context.name, 9)
        self.chrome = WorkspaceChrome(
            lambda: (client.context.name, "owned", "owned", "team", "Live"),
            "owned",
            namespace=lambda: "team",
        )
        if source_resource == SOURCE:
            source = record(SOURCE).manifest
        else:
            from tests.support.pods import pod

            source = pod("owned-source")
        source["metadata"].update(
            name="owned-source", uid="source-uid", resourceVersion="fresh-source-rv"
        )
        if source_resource == SOURCE:
            source["spec"]["scaleTargetRef"]["name"] = "owned-target"
        api.responses[path(source_resource, "owned-source")] = source
        api.responses[path(TARGET, "owned-target")] = payload(TARGET, "owned-target")
        api.responses["/api/v1/namespaces/team/events"] = collection()
        self.source = resource_record(source_resource, source)
        policy = AccessPolicy(True)
        processes = ProcessRunner(policy)
        self.operations = ResourceOperations(
            self,
            self.capture,
            self.context,
            policy,
            MutationManager(),
            ForwardManager(processes),
            processes,
            self.notices.append,
            session_current=lambda client, session: (
                client is self.client and session == self.session and self.valid
            ),
            forwarding=ForwardPreferences,
            delete_context=lambda: None,
            stop_plugins=self.stop_plugins,
            navigate_curated=self.navigate,
        )

    def compose(self) -> ComposeResult:
        yield Static("Owned resource table")

    def context(self):
        return OperationContext(
            self.chrome,
            ("horizontalpodautoscalers",),
            ("sh",),
            {},
            Path("/"),
            ViewRoute.pods(),
            False,
            discovery=self.api.discovery,
            revision=self.revision,
        )

    def capture(self, uid=None):
        return CapturedResource(
            self.client,
            self.source_resource,
            self.source,
            ResourceTarget(
                self.session,
                self.source_resource.group,
                self.source_resource.name,
                "team",
                "owned-source",
                "source-uid",
            ),
            lambda: self.valid,
        )

    async def stop_plugins(self, client):
        return None

    def navigate(self, origin, destination):
        inspector = next(
            (screen for screen in self.screen_stack if isinstance(screen, InspectionScreen)), None
        )
        assert inspector is None or inspector.operation_count == 0
        self.handoffs.append((origin, destination))

    def on_mount(self):
        self.operations.inspect("details")


async def ready(app):
    await wait_for(
        lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
    )
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_physical_links_pane_and_visible_capture_navigate_with_fresh_origin_without_self_cancel(
    tmp_path, size
):
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        async with app.run_test(size=size) as pilot:
            screen = await ready(app)
            assert screen.result.curated is not None
            assert "Scale target" in screen.viewer.text
            await pilot.click("#show-links")
            await pilot.pause()
            assert screen.page == "links" and screen.links.display and not screen.viewer.display
            assert app.focused is screen.links
            assert screen.links.region.width > 0 and screen.links.region.height >= 1
            assert screen.links.region.bottom <= size[1]
            choices = screen.capture_export(datetime.now(UTC))
            assert len(choices) == 1
            lease = choices[0][1]
            assert lease.capture.source.page == "evidence"
            text = lease.capture.source.text
            assert "Scale target" in text and "fresh target lookup required" in text
            assert "owned-target" not in text and "target-uid" not in text
            assert lease.capture.presentation.view == "inspection/links"
            await pilot.press("d")
            assert not lease.current()
            await pilot.press("L", "enter")
            try:
                await wait_for(lambda: len(app.handoffs) == 1)
            except TimeoutError:
                raise AssertionError(
                    f"Link did not hand off: page={screen.page}, status={screen.status.content}, focus={type(app.focused).__name__}, highlighted={screen.links.highlighted}, options={screen.links.option_count}, requests={api.ledger}, operations={screen.operation_count}"
                ) from None
            origin, destination = app.handoffs[0]
            assert origin.resource_version == "fresh-source-rv" and origin.revision == 13
            assert (origin.record_name, origin.record_uid) == ("owned-source", "source-uid")
            assert destination.record.uid == "target-uid"
            await wait_for(lambda: app.operations.retained_general_inspection_count == 0)
            assert app.operations.retained_inspection_count == 0
            assert screen.operation_count == 0
            assert (await client.get_json(path(TARGET, "owned-target")))["metadata"][
                "uid"
            ] == "target-uid"


@pytest.mark.asyncio
async def test_changed_source_rv_refuses_old_link_without_target_request(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        async with app.run_test() as pilot:
            screen = await ready(app)
            api.responses[path(SOURCE, "owned-source")]["metadata"]["resourceVersion"] = (
                "changed-rv"
            )
            await pilot.press("L", "enter")
            await wait_for(lambda: "source changed" in str(screen.status.content))
            assert not app.handoffs
            assert path(TARGET, "owned-target") not in [entry[1] for entry in api.ledger]
            assert screen.page == "links"
            await screen.stop_owned()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["detached", "revision"])
async def test_pending_link_is_drained_on_dom_removal_or_revision_change_without_late_handoff(
    tmp_path, ending
):
    from aiohttp import web

    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        async with app.run_test() as pilot:
            screen = await ready(app)
            source = api.responses[path(SOURCE, "owned-source")]
            entered, release = asyncio.Event(), asyncio.Event()

            async def held(request):
                entered.set()
                await release.wait()
                return web.json_response(source)

            api.responses[path(SOURCE, "owned-source")] = held
            try:
                await pilot.press("L", "enter")
                await asyncio.wait_for(entered.wait(), 1)
                assert screen.operation_count > 0
                if ending == "detached":
                    app.pop_screen()
                    await app.operations.close_for_client(client)
                else:
                    app.revision += 1
                    screen.validate_target()
                    await screen.stop_owned()
                release.set()
                await wait_for(lambda: app.operations.retained_general_inspection_count == 0)
                assert not app.handoffs and screen.operation_count == 0
                assert path(TARGET, "owned-target") not in [entry[1] for entry in api.ledger]
            finally:
                release.set()
                await screen.stop_owned()


@pytest.mark.asyncio
async def test_general_inspector_retained_after_stack_removal_until_real_serializer_thread_drains(
    tmp_path, monkeypatch
):
    from kuberich.services import inspection

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = inspection.inspection_documents

    def held(*args):
        entered.set()
        try:
            release.wait(5)
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(inspection, "inspection_documents", held)
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        async with app.run_test():
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                screen = app.screen
                app.pop_screen()
                await wait_for(lambda: screen not in app.screen_stack)
                assert app.operations.retained_general_inspection_count == 1
                close = asyncio.create_task(app.operations.close_for_client(client))
                await asyncio.sleep(0)
                assert not close.done() and not finished.is_set()
                app.operations.inspect("details")
                assert "Previous inspection is closing" in app.notices[-1]
                release.set()
                await close
                assert finished.is_set() and screen.operation_count == 0
                assert app.operations.retained_general_inspection_count == 0
                assert (await client.get_json(path(TARGET, "owned-target")))["metadata"][
                    "uid"
                ] == "target-uid"
            finally:
                release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["revision", "newer-link-intent", "overlay"])
async def test_completed_http_resolution_revalidates_when_queued_ui_handoff_is_delivered(
    tmp_path, monkeypatch, changed
):
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        async with app.run_test() as pilot:
            screen = await ready(app)
            queued = []
            original = screen.call_later

            def defer_handoff(callback, *args, **kwargs):
                if args and isinstance(args[0], CuratedOrigin):
                    queued.append((callback, args))
                    return True
                return original(callback, *args, **kwargs)

            monkeypatch.setattr(screen, "call_later", defer_handoff)
            await pilot.press("L", "enter")
            await wait_for(lambda: len(queued) == 1)
            assert screen.operation_count == 0 and not app.handoffs
            if changed == "revision":
                app.revision += 1
                queued[0][0](*queued[0][1])
                await screen.stop_owned()
                assert screen.invalidated and not app.handoffs
            elif changed == "overlay":
                overlay = ModalScreen()
                await app.push_screen(overlay)
                queued[0][0](*queued[0][1])
                assert app.screen is overlay and not app.handoffs
                overlay.dismiss()
                await wait_for(lambda: app.screen is screen)
                await screen.stop_owned()
            else:
                await pilot.press("enter")
                await wait_for(lambda: len(queued) == 2)
                queued[0][0](*queued[0][1])
                assert not app.handoffs
                queued[1][0](*queued[1][1])
                await wait_for(lambda: len(app.handoffs) == 1)
            await wait_for(lambda: app.operations.retained_general_inspection_count == 0)
            assert sum(entry[1] == path(TARGET, "owned-target") for entry in api.ledger) == (
                2 if changed == "newer-link-intent" else 1
            )


@pytest.mark.asyncio
async def test_target_replacement_before_link_activation_invalidates_without_new_get(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        async with app.run_test() as pilot:
            screen = await ready(app)
            await pilot.press("L")
            before = len(api.ledger)
            app.valid = False
            await pilot.press("enter")
            await wait_for(lambda: screen.invalidated)
            await screen.stop_owned()
            assert len(api.ledger) == before and not app.handoffs


@pytest.mark.asyncio
async def test_standalone_inspector_without_navigation_callback_reports_unavailable(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api)
        app.operations.navigate_curated = None
        async with app.run_test() as pilot:
            screen = await ready(app)
            before = len(api.ledger)
            await pilot.press("L", "enter")
            await wait_for(lambda: "unavailable in this workspace" in str(screen.status.content))
            assert len(api.ledger) == before and not app.handoffs
            await screen.stop_owned()


@pytest.mark.asyncio
async def test_normal_pod_empty_links_pane_shows_exact_authored_export_text(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        app = InspectionHost(client, api, source_resource=PODS)
        async with app.run_test(size=(40, 12)) as pilot:
            screen = await ready(app)
            assert screen.result.curated is None
            await pilot.click("#show-links")
            await pilot.pause()
            assert screen.links.option_count == 1
            option = screen.links.get_option_at_index(0)
            assert option.disabled
            lease = screen.capture_export(datetime.now(UTC))[0][1]
            assert option.prompt.plain == lease.capture.source.text
            assert "No declared curated links are available." in option.prompt.plain
            before = len(api.ledger)
            await pilot.press("enter")
            assert len(api.ledger) == before and not app.handoffs
            await screen.stop_owned()
