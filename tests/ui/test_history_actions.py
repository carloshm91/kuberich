"""History composition preserves Pulse health and drains captured screen work."""

import asyncio
import copy
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp import web
from textual.app import App, ComposeResult
from textual.widgets import Static

from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.container_inspection import ContainerIdentity
from kuberich.domain.history import HistoryBackend, HistoryOptions, HistoryStatus
from kuberich.domain.pulse import PulseScope, PulseSnapshot, PulseStatus
from kuberich.domain.resources import ApiResource, ResourceSnapshot, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.services import history as history_service
from kuberich.services.access import AccessPolicy
from kuberich.services.pulse import PulseService
from kuberich.ui.history import HistoryScreen
from kuberich.ui.history_actions import HistoryActions
from kuberich.ui.target_capture import CapturedResource
from tests.support.history import history_discovery
from tests.support.history_explorer import NAMESPACE, POD_PATH, HistoryApi
from tests.support.resources import reader_fixture
from tests.support.workspace import wait_for


class HistoryHost(App):
    """Real Textual screens over narrow session/workspace observation ports."""

    def __init__(self, reader, api, *, route=None, configured=True):
        super().__init__()
        self.reader, self.api = reader, api
        self.identity = SessionIdentity("synthetic", 1)
        self.sessions = SimpleNamespace(
            client=reader.session,
            observation=SessionObservation(
                ConnectionState.CONNECTED, identity=self.identity, namespace=NAMESPACE
            ),
        )
        self.scope = PulseScope(self.identity, NAMESPACE)
        self.workspace = SimpleNamespace(
            discovery=history_discovery(),
            store=SimpleNamespace(observation=ViewObservation(pulse=PulseSnapshot(self.scope))),
            pulse_selected=True,
        )
        self.context = SimpleNamespace(
            modal=False, route=route or ViewRoute.pods(), chrome=None, trail=("synthetic",)
        )
        self.selected_path = POD_PATH
        self.capture_enabled = True
        self.options = HistoryOptions(HistoryBackend(NAMESPACE, "metrics")) if configured else None
        self.notices, self.errors, self.pushed = [], [], []
        self.fail_push = False
        self.history = HistoryActions(
            host=self,
            sessions=self.sessions,
            workspace=self.workspace,
            capture=lambda _uid: self.capture(),
            context=lambda: self.context,
            options=lambda _context: self.options,
            policy=AccessPolicy(True),
            notice=self.notices.append,
            on_error=self.errors.append,
        )

    def compose(self) -> ComposeResult:
        yield Static("Synthetic parent resource view")

    def push_screen(self, screen, *args, **kwargs):
        if isinstance(screen, HistoryScreen):
            if self.fail_push:
                raise RuntimeError("Synthetic history mounting failed")
            self.pushed.append(screen)
        return super().push_screen(screen, *args, **kwargs)

    def capture(self):
        if not self.capture_enabled:
            return None
        resource = self.workspace.discovery.find("pods")
        record = resource_record(resource, self.api.records[self.selected_path])
        target = ResourceTarget(
            self.identity, resource.group, resource.name, record.namespace, record.name, record.uid
        )
        client, path, identity, uid = (
            self.sessions.client,
            self.selected_path,
            self.identity,
            record.uid,
        )

        def current():
            return (
                self.sessions.client is client
                and self.sessions.observation.identity == identity
                and self.selected_path == path
                and self.api.records[path]["metadata"]["uid"] == uid
            )

        return CapturedResource(client, resource, record, target, current)

    def select_another_pod(self, suffix):
        path = POD_PATH + "-" + suffix
        record = copy.deepcopy(self.api.records[POD_PATH])
        record["metadata"]["name"] += "-" + suffix
        record["metadata"]["uid"] += "-" + suffix
        self.api.records[path] = record
        self.selected_path = path
        return path

    async def on_unmount(self):
        await self.history.close()


async def settled(host):
    await wait_for(lambda: isinstance(host.screen, HistoryScreen))
    screen = host.screen
    await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
    return screen


@pytest.mark.asyncio
async def test_detail_handoff_cancels_only_overview_history_and_pulse_health_keeps_running(
    tmp_path,
):
    api = HistoryApi()
    entered, release = asyncio.Event(), asyncio.Event()
    active_handlers = set()
    holding = True

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        if holding and incoming.path.endswith("query_range"):
            task = asyncio.current_task()
            active_handlers.add(task)
            entered.set()
            try:
                await release.wait()
            finally:
                active_handlers.discard(task)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api, route=ViewRoute.pulse())
        service = PulseService(
            reader,
            host.workspace.discovery,
            host.scope,
            lambda: True,
            history=lambda: host.history.overview(reader.session, host.scope),
            interval=0.01,
        )
        published = []
        collector = asyncio.create_task(service.run(published.append))
        try:
            async with host.run_test() as pilot:
                await asyncio.wait_for(entered.wait(), 5)
                host.history.open_current()
                await wait_for(lambda: isinstance(host.screen, HistoryScreen))
                await wait_for(lambda: any(snapshot.history is not None for snapshot in published))
                pod_path = "/api/v1/namespaces/team/pods"
                first_count = sum(path == pod_path for path, _ in api.requests)
                await wait_for(
                    lambda: sum(path == pod_path for path, _ in api.requests) > first_count
                )
                assert not collector.done()
                completed = [
                    snapshot
                    for snapshot in published
                    if snapshot.history is not None
                    and any(
                        source.key == "pods" and source.status is PulseStatus.VALID
                        for source in snapshot.sources
                    )
                ]
                assert completed[-1].history.status is HistoryStatus.UNAVAILABLE
                assert "paused" in completed[-1].history.detail
                pods = next(source for source in completed[-1].sources if source.key == "pods")
                assert pods.status is PulseStatus.VALID and pods.complete and pods.count == 1
                assert host.history.owner_count == host.history.retained_screen_count == 1
                holding = False
                release.set()
                await wait_for(lambda: host.screen.operation_count == 0)
                host.pop_screen()
                await wait_for(lambda: host.history.retained_screen_count == 0)
                await wait_for(
                    lambda: any(
                        snapshot.history is not None and snapshot.history.series
                        for snapshot in published
                    )
                )
                assert not host.errors
                await pilot.pause()
        finally:
            holding = False
            release.set()
            collector.cancel()
            with pytest.raises(asyncio.CancelledError):
                await collector
            await host.history.close()
            await wait_for(lambda: not active_handlers)
        assert host.history.operation_count == host.history.owner_count == 0


@pytest.mark.asyncio
async def test_real_parent_cancellation_during_pulse_history_propagates_and_drains(tmp_path):
    api = HistoryApi()
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        if incoming.path.endswith("query_range"):
            entered.set()
            await release.wait()
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        service = PulseService(
            reader,
            host.workspace.discovery,
            host.scope,
            lambda: True,
            history=lambda: host.history.overview(reader.session, host.scope),
        )
        task = asyncio.create_task(service.collect(lambda _snapshot: None))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled() and host.history.operation_count == 0
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await host.history.close()
        assert host.history.owner_count == 0
        assert (await reader.session.get_json("/api/v1/namespaces/team/services/metrics"))[
            "kind"
        ] == "Service"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard",
    [
        "modal",
        "capture-missing",
        "unsupported",
        "pulse-disconnected",
        "pulse-missing",
        "discovery-missing",
        "closed",
    ],
)
async def test_opening_guards_leave_no_screen_or_network_work(tmp_path, guard):
    api = HistoryApi()

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        async with host.run_test() as pilot:
            if guard == "modal":
                host.context.modal = True
            elif guard == "capture-missing":
                host.capture_enabled = False
            elif guard == "unsupported":
                selection = host.capture()
                resource = ApiResource(
                    "", "v1", "configmaps", "ConfigMap", True, frozenset({"get"})
                )
                config = resource_record(
                    resource,
                    {
                        "metadata": {
                            "name": "settings",
                            "namespace": NAMESPACE,
                            "uid": "settings-uid",
                            "resourceVersion": "one",
                        }
                    },
                )
                selection = CapturedResource(
                    selection.client,
                    resource,
                    config,
                    ResourceTarget(
                        host.identity, "", "configmaps", NAMESPACE, config.name, config.uid
                    ),
                    selection.current,
                )
                host.history.capture = lambda _uid: selection
            elif guard.startswith("pulse"):
                host.context.route = ViewRoute.pulse()
                if guard == "pulse-disconnected":
                    host.sessions.client = None
                else:
                    host.workspace.store.observation = ViewObservation()
            elif guard == "discovery-missing":
                host.workspace.discovery = None
                selection = CapturedResource(
                    reader.session,
                    history_discovery().find("pods"),
                    resource_record(history_discovery().find("pods"), api.records[POD_PATH]),
                    ResourceTarget(
                        host.identity, "", "pods", NAMESPACE, "history-pod", "history-pod-uid"
                    ),
                    lambda: True,
                )
                host.history.capture = lambda _uid: selection
            else:
                await host.history.close()
            host.history.open_current()
            await wait_for(lambda: host.history.operation_count == 0)
            await pilot.pause()
            assert not isinstance(host.screen, HistoryScreen)
            assert host.history.retained_screen_count == host.history.owner_count == 0
            assert not api.requests and not host.errors
            assert bool(host.notices) == (guard not in {"capture-missing", "closed"})


@pytest.mark.asyncio
async def test_overview_unconfigured_discovery_and_closed_states_are_explicit(tmp_path):
    api = HistoryApi()

    async def handler(incoming):
        raise AssertionError("A guarded overview must not use transport")

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api, configured=False)
        assert (
            await host.history.overview(reader.session, host.scope)
        ).status is HistoryStatus.UNCONFIGURED
        host.options = HistoryOptions(HistoryBackend(NAMESPACE, "metrics"))
        host.workspace.discovery = None
        report = await host.history.overview(reader.session, host.scope)
        assert report.status is HistoryStatus.UNAVAILABLE and "discovery" in report.detail
        host.workspace.discovery = history_discovery()
        await host.history.close()
        assert (
            await host.history.overview(reader.session, host.scope)
        ).status is HistoryStatus.UNAVAILABLE
        assert host.history.owner_count == 0


@pytest.mark.asyncio
async def test_latest_opening_waits_for_detached_parser_before_claiming_new_screen(
    tmp_path, monkeypatch
):
    api = HistoryApi()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = history_service.parse_history_matrix

    def held(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(10)
            return original(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(history_service, "parse_history_matrix", held)

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        try:
            async with host.run_test() as pilot:
                parent = host.screen
                host.history.open_current()
                await wait_for(lambda: isinstance(host.screen, HistoryScreen))
                first = host.screen
                await asyncio.wait_for(asyncio.to_thread(entered.wait, 5), 6)
                host.pop_screen()
                await wait_for(lambda: host.screen is parent)
                assert host.history.retained_screen_count == 1
                middle = host.select_another_pod("middle")
                host.history.open_current()
                await asyncio.sleep(0)
                await wait_for(lambda: host.history.operation_count >= 2)
                latest = host.select_another_pod("latest")
                host.history.open_current()
                host.history.open_current()
                await asyncio.sleep(0)
                assert host.screen is parent and len(host.pushed) == 1
                assert host.history.retained_screen_count == 1 and not finished.is_set()
                release.set()
                second = await settled(host)
                assert second is not first and second.scope.target.uid.endswith("latest")
                assert second.scope.session == host.identity
                assert len(host.pushed) == 2 and host.history.retained_screen_count == 1
                assert not any(path == middle for path, _ in api.requests)
                assert any(path == latest for path, _ in api.requests)
                assert finished.is_set() and first.invalidated and first.snapshot is None
                host.history.open_current()
                await pilot.pause()
                assert len(host.pushed) == 2 and not host.errors
        finally:
            release.set()
            await host.history.close()
        assert (
            host.history.retained_screen_count
            == host.history.operation_count
            == host.history.owner_count
            == 0
        )


@pytest.mark.asyncio
async def test_cancelled_client_close_drains_detached_work_and_refuses_new_reads(
    tmp_path, monkeypatch
):
    api = HistoryApi()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = history_service.parse_history_matrix

    def held(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(10)
            return original(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(history_service, "parse_history_matrix", held)

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        closing = second_close = None
        try:
            async with host.run_test():
                parent = host.screen
                host.history.open_current()
                await wait_for(lambda: isinstance(host.screen, HistoryScreen))
                await asyncio.wait_for(asyncio.to_thread(entered.wait, 5), 6)
                host.pop_screen()
                await wait_for(lambda: host.screen is parent)
                host.history.open_current()
                await asyncio.sleep(0)
                await wait_for(lambda: host.history.operation_count >= 2)
                assert not finished.is_set()
                obsolete = host.select_another_pod("obsolete")
                host.history.open_current()
                closing = asyncio.create_task(host.history.close_for_client(reader.session))
                await asyncio.sleep(0)
                second_close = asyncio.create_task(host.history.close_for_client(reader.session))
                await asyncio.sleep(0)
                closing.cancel()
                await asyncio.sleep(0)
                closing.cancel()
                await asyncio.sleep(0)
                assert not closing.done() and not second_close.done()
                assert host.history.retained_screen_count == 1 and host.history.detail_active
                paused = await host.history.overview(reader.session, host.scope)
                assert paused.status is HistoryStatus.UNAVAILABLE and "closing" in paused.detail
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await closing
                await second_close
                assert not any(path == obsolete for path, _ in api.requests)
                await wait_for(lambda: host.history.retained_screen_count == 0)
                assert (
                    finished.is_set()
                    and host.history.owner_count == host.history.operation_count == 0
                )
                assert not host.errors
        finally:
            release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            if second_close is not None:
                await asyncio.gather(second_close, return_exceptions=True)
            await host.history.close()
        assert (await reader.session.get_json("/api/v1/namespaces/team/services/metrics"))[
            "kind"
        ] == "Service"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "generation"])
async def test_observed_target_change_revokes_captured_screen_and_connection_owner_drains(
    tmp_path, change
):
    api = HistoryApi()

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        async with host.run_test():
            host.history.open_current()
            screen = await settled(host)
            captured = screen.scope.target
            if change == "uid":
                api.records[POD_PATH]["metadata"]["uid"] = "replacement"
            else:
                host.sessions.observation = replace(
                    host.sessions.observation, identity=replace(host.identity, generation=2)
                )
            resource = history_discovery().find("pods")
            view = ViewObservation(
                snapshot=ResourceSnapshot(
                    resource, NAMESPACE, "next", (resource_record(resource, api.records[POD_PATH]),)
                )
            )
            host.history.observe(view)
            assert screen.invalidated and screen.snapshot is None
            assert screen.scope.target is captured
            await host.history.close_for_client(reader.session)
            assert (
                host.history.retained_screen_count
                == host.history.owner_count
                == host.history.operation_count
                == 0
            )
            assert not host.errors


@pytest.mark.asyncio
async def test_container_capture_and_configure_use_same_owner_with_live_source_limits(tmp_path):
    api = HistoryApi()

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        async with host.run_test():
            selection = host.capture()
            host.history.open_container(
                selection, ContainerIdentity("initContainers", "init", "Init")
            )
            screen = await settled(host)
            assert screen.scope.kind == "container" and screen.scope.target.container == "init"
            assert (
                screen.scope.target.uid == selection.target.uid
                and screen.scope.container_field == "initContainers"
            )
            assert "containers" in screen.trail and host.history.owner_count == 1
            host.options = HistoryOptions(HistoryBackend(NAMESPACE, "alternate"))
            host.history.configure(host.options)
            await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
            assert screen.options == host.options and host.screen is screen
            assert any("services/http:alternate:9090/proxy" in path for path, _ in api.requests)
            count = len(api.requests)
            host.history.configure(host.options)
            await asyncio.sleep(0)
            assert len(api.requests) == count
            host.options = None
            host.history.configure(None)
            await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
            assert screen.snapshot.status is HistoryStatus.UNCONFIGURED
            assert not host.errors


@pytest.mark.asyncio
async def test_configure_revokes_unclaimed_overview_cache_without_creating_another_owner(tmp_path):
    api = HistoryApi()

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        try:
            original = host.options
            await host.history.overview(reader.session, host.scope)
            count = len(api.requests)
            await host.history.overview(reader.session, host.scope)
            assert sum(path.endswith("query_range") for path, _ in api.requests) == 5
            host.options = None
            host.history.configure(None)
            assert (
                await host.history.overview(reader.session, host.scope)
            ).status is HistoryStatus.UNCONFIGURED
            host.options = original
            await host.history.overview(reader.session, host.scope)
            assert len(api.requests) > count
            assert sum(path.endswith("query_range") for path, _ in api.requests) == 10
            assert host.history.owner_count == 1 and not host.errors
        finally:
            await host.history.close()


@pytest.mark.asyncio
async def test_opening_failure_is_reported_once_and_never_abandons_retained_cleanup(tmp_path):
    api = HistoryApi()

    async def handler(incoming):
        raise AssertionError("A failed mounting must not issue history requests")

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        async with host.run_test() as pilot:
            host.fail_push = True
            host.history.open_current()
            await wait_for(lambda: bool(host.errors))
            await pilot.pause()
            assert len(host.errors) == 1 and isinstance(host.errors[0], RuntimeError)
            assert not isinstance(host.screen, HistoryScreen)
            await host.history.close()
            assert (
                host.history.retained_screen_count
                == host.history.owner_count
                == host.history.operation_count
                == 0
            )


@pytest.mark.asyncio
async def test_actual_pulse_backend_reload_preserves_mounted_detail_and_review_claim(tmp_path):
    from datetime import UTC, datetime

    from tests.ui.test_history import app_fixture, open_history, open_review, root_ready
    from tests.ui.test_live_preferences import save

    async with app_fixture(tmp_path) as (app, _api, path, *_), app.run_test() as pilot:
        await root_ready(app)
        await app.run_command(":pulse")
        await wait_for(lambda: app.state.view_kind == "pulse")
        await root_ready(app)
        await pilot.pause()
        _, screen = await open_history(app, pilot)
        original_scope = screen.scope
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        review = await open_review(app, pilot)
        assert lease.current() and screen in app.screen_stack
        save(
            path,
            {
                "read_only": True,
                "observability": {"history": {"namespace": NAMESPACE, "service": "alternate"}},
            },
        )
        await app.live_preferences.check()
        assert not lease.current()
        await wait_for(
            lambda: (
                screen.invalidated or (screen.snapshot is not None and screen.operation_count == 0)
            )
        )
        assert not screen.invalidated and screen.scope == original_scope
        assert screen.options.endpoint.service == "alternate"
        assert screen in app.screen_stack and app.screen is review
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen and review.stopped)
        assert screen.capture_export(datetime.now(UTC))[0][1].current()
        assert app.metric_history.retained_screen_count == app.metric_history.owner_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["node", "workload"])
async def test_resource_routes_capture_served_identity_before_opening(tmp_path, kind):
    api = HistoryApi()

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        resource = (
            ApiResource("", "v1", "nodes", "Node", False, frozenset({"get"}))
            if kind == "node"
            else ApiResource("apps", "v1", "deployments", "Deployment", True, frozenset({"get"}))
        )
        path = (
            "/api/v1/nodes/history-node"
            if kind == "node"
            else "/apis/apps/v1/namespaces/team/deployments/history-workload"
        )
        record = resource_record(resource, api.records[path])
        target = ResourceTarget(
            host.identity, resource.group, resource.name, record.namespace, record.name, record.uid
        )
        selection = CapturedResource(reader.session, resource, record, target, lambda: True)
        host.history.capture = lambda _uid: selection
        async with host.run_test():
            host.history.open_current()
            assert host.history.detail_active
            screen = await settled(host)
            assert screen.scope.kind == kind and screen.scope.resource is resource
            assert screen.scope.target is target and screen.scope.namespace == record.namespace
            assert any(request_path == path for request_path, _ in api.requests)
            host.history.observe(ViewObservation())
            assert not screen.invalidated
            host.history.observe(
                ViewObservation(
                    snapshot=ResourceSnapshot(resource, record.namespace, "one", (record,))
                )
            )
            assert not screen.invalidated
            host.history.observe(
                ViewObservation(snapshot=ResourceSnapshot(resource, record.namespace, "two", ()))
            )
            assert screen.invalidated and screen.snapshot is None
        assert not host.history.detail_active


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["client", "route", "missing", "scope"])
async def test_queued_pulse_capture_is_rejected_if_origin_changes_before_actor_runs(
    tmp_path, change
):
    api = HistoryApi()

    async def handler(incoming):
        raise AssertionError("An obsolete Pulse capture must not issue transport reads")

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api, route=ViewRoute.pulse())
        async with host.run_test():
            host.history.open_current()
            assert host.history.detail_active
            if change == "client":
                host.sessions.client = None
            elif change == "route":
                host.workspace.pulse_selected = False
            elif change == "missing":
                host.workspace.store.observation = ViewObservation()
            else:
                host.workspace.store.observation = ViewObservation(
                    pulse=PulseSnapshot(PulseScope(host.identity, "other"))
                )
            await wait_for(lambda: host.history.operation_count == 0)
            assert not host.pushed and not host.history.detail_active
            assert host.history.owner_count == 0 and not host.errors


@pytest.mark.asyncio
async def test_closing_an_unstarted_actor_and_stale_container_capture_performs_no_reads(tmp_path):
    api = HistoryApi()

    async def handler(incoming):
        raise AssertionError("An obsolete opening must not issue transport reads")

    async with reader_fixture(tmp_path, handler) as reader:
        host = HistoryHost(reader, api)
        selection = host.capture()
        async with host.run_test():
            stale = CapturedResource(
                selection.client,
                selection.resource,
                selection.record,
                selection.target,
                lambda: False,
            )
            host.history.open_container(stale, ContainerIdentity("containers", "app", "App"))
            assert not host.history.detail_active and host.history.operation_count == 0
            host.history.open_current()
            assert host.history.detail_active
            await host.history.close()
            host.history.open_container(selection, ContainerIdentity("containers", "app", "App"))
            assert not host.history.detail_active
            assert (
                host.history.owner_count
                == host.history.retained_screen_count
                == host.history.operation_count
                == 0
            )
            assert not host.pushed and not host.errors


@pytest.mark.asyncio
async def test_unrelated_client_teardown_does_not_retire_current_detail(tmp_path):
    api = HistoryApi()
    other_calls = []

    async def handler(incoming):
        status, value = api.response(incoming.path, incoming.query)
        return web.json_response(value, status=status)

    async def other_handler(incoming):
        other_calls.append(incoming.path)
        return web.Response(status=503)

    other = tmp_path / "other"
    other.mkdir()
    async with (
        reader_fixture(tmp_path, handler) as reader,
        reader_fixture(other, other_handler) as unused,
    ):
        host = HistoryHost(reader, api)
        async with host.run_test():
            await host.history.close_for_client(unused.session)
            host.history.open_current()
            screen = await settled(host)
            await host.history.close_for_client(unused.session)
            assert host.screen is screen and not screen.invalidated
            assert host.history.retained_screen_count == host.history.owner_count == 1
            assert not other_calls and not host.errors
