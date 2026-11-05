"""Actual diagnostic App routes, captured identities and owned HTTP log requests."""

from pathlib import Path

import pytest

from kuberich.domain.cluster_diagnostics import (
    DiagnosticCategory,
    DiagnosticLogMode,
    DiagnosticStatus,
)
from kuberich.domain.views import USABLE_CONNECTIONS
from kuberich.ui.diagnostic_evidence import DiagnosticEvidenceScreen
from kuberich.ui.logs import LogScreen
from tests.support.authorization_ui import authorization_api
from tests.support.connections import catalog_fixture
from tests.support.diagnostic_api import DiagnosticAPI
from tests.support.workspace import wait_for
from tests.ui.test_navigation import make_app


async def pods_ready(app, namespace="team", count=1):
    await wait_for(
        lambda: (
            app.state.view_kind == "pods"
            and app.state.namespace == namespace
            and app.resources.row_count == count
        )
    )


def rows(app):
    return tuple(
        app.diagnostics_table.row_at(row.key.value) for row in app.diagnostics_table.ordered_rows
    )


async def diagnostics_ready(app, *, category=None):
    def ready():
        data = app.workspace.store.observation.diagnostics
        if (
            app.state.view_kind != "diagnostics"
            or data is None
            or data.collecting
            or app.workspace.diagnostic_collecting
            or app.diagnostics_table.request != data.request
            or app.diagnostics_table.snapshot != data
        ):
            return False
        expected = {
            item.key for item in data.findings if category is None or item.category is category
        }
        return {row.key for row in rows(app) if row.finding is not None} == expected

    await wait_for(ready)


def select(app, category=DiagnosticCategory.CRASH_LOOP, *, log_mode=None):
    row = next(
        row
        for row in rows(app)
        if row.finding is not None
        and row.finding.category is category
        and (log_mode is None or log_mode in row.finding.log_modes)
    )
    app.diagnostics_table.move_cursor(row=app.diagnostics_table.get_row_index(row.key))
    app.diagnostics_table.focus()
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("size,mode", [((40, 12), "previous"), ((120, 30), "current")])
async def test_native_frame_sources_filter_evidence_and_real_initial_log_mode(tmp_path, size, mode):
    api = DiagnosticAPI()
    api.forbidden.add("events")
    if mode == "current":
        api.objects[("", "pods", "team", "example")]["status"]["containerStatuses"][0]["state"] = {
            "running": {}
        }
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=size) as pilot:
            await pods_ready(app)
            frame = app.query_one("#resource-view").region
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            assert app.query_one("#resource-view").region == frame and len(app.screen_stack) == 1
            assert any(
                row.source_record is not None
                and row.source_record.status is DiagnosticStatus.FORBIDDEN
                for row in rows(app)
            )
            assert not app.check_action("review_delete", ()) and not app.check_action(
                "inspect_yaml", ()
            )
            assert not api.log_reads
            original = app.workspace.diagnostic_request
            app.filter_input.value = "not-a-finding"
            await wait_for(lambda: all(row.finding is None for row in rows(app)))
            assert app.workspace.diagnostic_request == original
            assert any(row.source_record is not None for row in rows(app))
            app.filter_input.value = ""
            await diagnostics_ready(app)
            row = select(
                app,
                DiagnosticCategory.READINESS
                if mode == "current"
                else DiagnosticCategory.CRASH_LOOP,
                log_mode=DiagnosticLogMode(mode),
            )
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            detail = app.screen
            assert (
                "Running container is not ready" if mode == "current" else "CrashLoopBackOff"
            ) in detail.viewer.text
            assert "pod-team" in detail.viewer.text
            assert not api.log_reads
            await pilot.press("p" if mode == "previous" else "l")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and bool(api.log_reads))
            screen = app.screen
            await wait_for(lambda: bool(screen.history.entries))
            assert api.log_reads[0][0] == "/api/v1/namespaces/team/pods/example/log"
            assert api.log_reads[0][1]["previous"] == str(mode == "previous").lower()
            assert api.log_reads[0][1]["container"] == "app"
            assert all(
                query["previous"] == api.log_reads[0][1]["previous"] for _, query in api.log_reads
            )
            assert screen.stream.target.uid == row.finding.subject.uid
            assert screen.stream.target.namespace == "team"
            await pilot.press("escape")
            await wait_for(lambda: app.screen is detail)
            assert screen.active_count == 0 and screen.closed
            await pilot.press("escape")
            await diagnostics_ready(app)
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_root_namespace_and_header_restore_together_with_exact_filtered_viewport(tmp_path):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(100, 16)) as pilot:
            await pods_ready(app)
            await app.run_command("ns *")
            await pods_ready(app, None, 3)
            app.resources.move_cursor(row=app.resources.get_row_index("pod-other"))
            app.resources.focus()
            await app.run_command("diagnose")
            await diagnostics_ready(app)
            original = app.workspace.diagnostic_request
            assert app.state.namespace is None and original.scope.namespace == "other"
            assert original.scope.root.uid == "pod-other"
            assert app.workspace.store.observation.diagnostics.findings
            assert all(
                item.subject.namespace == "other"
                for item in app.workspace.store.observation.diagnostics.findings
            )
            app.filter_input.value = "CrashLoopBackOff"
            await diagnostics_ready(app, category=DiagnosticCategory.CRASH_LOOP)
            selected = select(app)
            app.diagnostics_table.set_sort("source", False)
            await pilot.pause()
            app.diagnostics_table.scroll_to(x=9, animate=False, immediate=True, force=True)
            await pilot.pause()
            viewport = app.diagnostics_table.capture_viewport()
            assert viewport.x == 9
            await app.run_command("open")
            await pods_ready(app, "other")
            assert app.state.selected == "pod-other" and app.views.expected_uid == "pod-other"
            await pilot.press("alt+left")
            await diagnostics_ready(app, category=DiagnosticCategory.CRASH_LOOP)
            restored = app.workspace.diagnostic_request
            assert restored.scope.session != original.scope.session
            assert restored.scope.session.connection_id == original.scope.session.connection_id
            assert (
                restored.scope.root == original.scope.root and restored.scope.namespace == "other"
            )
            assert app.state.namespace is None and app.filter_input.value == "CrashLoopBackOff"
            await wait_for(lambda: app.diagnostics_table.capture_viewport() == viewport)
            assert app.diagnostics_table.selected_key() == selected.key
            assert (
                app.diagnostics_table.sort_column == "source"
                and not app.diagnostics_table.descending
            )
            await app.run_command("ns other")
            await diagnostics_ready(app)
            assert (
                app.state.namespace == "other"
                and app.workspace.diagnostic_request.scope.root is None
            )


@pytest.mark.asyncio
async def test_native_event_open_uses_retained_event_uid_and_replacement_pod_cannot_open(tmp_path):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            select(app)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            detail = app.screen
            event = detail.events[0].ref
            await pilot.press("e")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.name == "events"
                    and app.state.selected == event.uid
                )
            )
            assert app.views.expected_uid == event.uid
            await pilot.press("alt+left")
            await diagnostics_ready(app)
            select(app)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            detail = app.screen
            api.objects[("", "pods", "team", "example")]["metadata"]["uid"] = "replacement"
            await pilot.press("o")
            await wait_for(lambda: "replaced" in str(detail.status.content).lower())
            assert app.state.view_kind == "diagnostics" and app.screen is detail
            assert not api.log_reads


@pytest.mark.asyncio
async def test_cancel_retains_observed_native_rows_and_late_old_source_cannot_publish(tmp_path):
    api = DiagnosticAPI()
    api.hold_path = "/api/v1/namespaces/team/events"
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await wait_for(api.started.is_set)
            partial = app.workspace.store.observation.diagnostics
            assert partial is not None and partial.findings and partial.collecting
            times = tuple(
                item.observed_at for finding in partial.findings for item in finding.evidence
            )
            await app.run_command("diagnostics cancel")
            await diagnostics_ready(app)
            cancelled = app.workspace.store.observation.diagnostics
            assert cancelled.request != partial.request
            assert cancelled.findings == partial.findings
            assert any(
                source.status in {DiagnosticStatus.CANCELLED, DiagnosticStatus.PARTIAL}
                for source in cancelled.sources
            )
            assert (
                tuple(
                    item.observed_at for finding in cancelled.findings for item in finding.evidence
                )
                == times
            )
            api.release.set()
            await pilot.pause()
            assert app.workspace.store.observation.diagnostics == cancelled
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_context_switch_during_collection_rejects_old_sources_and_opens_new_overview(
    tmp_path,
):
    api = DiagnosticAPI()
    api.hold_path = "/api/v1/namespaces/team/events"
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await wait_for(api.started.is_set)
            original = app.workspace.diagnostic_request
            await app.run_command("ctx kuberich-test-Two")
            await diagnostics_ready(app)
            assert app.state.context == "kuberich-test-Two" and app.state.namespace == "default"
            fresh = app.workspace.diagnostic_request
            assert fresh.scope.session.connection_id != original.scope.session.connection_id
            assert fresh.scope.root is None and fresh.scope.namespace == "default"
            api.release.set()
            await pilot.pause()
            assert app.workspace.diagnostic_request == fresh
            assert not app.workspace.store.observation.diagnostics.findings
            assert any("No failure evidence found" in row.summary for row in rows(app))


@pytest.mark.asyncio
async def test_open_log_lifetime_survives_same_scope_collection_refresh_then_context_change_drains_it(
    tmp_path,
):
    api = DiagnosticAPI()
    api.objects[("", "pods", "other", "example")]["status"]["containerStatuses"][0]["state"] = {
        "running": {}
    }
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("ns *")
            await pods_ready(app, None, 3)
            app.resources.move_cursor(row=app.resources.get_row_index("pod-other"))
            app.resources.focus()
            await app.run_command("diagnose")
            await diagnostics_ready(app)
            select(app, DiagnosticCategory.READINESS, log_mode=DiagnosticLogMode.CURRENT)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            await pilot.press("l")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and bool(api.log_reads))
            screen = app.screen
            await wait_for(lambda: bool(screen.history.entries))
            assert app.state.namespace is None
            assert (
                screen.stream.target.namespace == "other"
                and screen.stream.target.uid == "pod-other"
            )
            assert api.log_reads[0][0] == "/api/v1/namespaces/other/pods/example/log"
            original = app.workspace.diagnostic_request
            app.workspace.refresh_diagnostics()
            await wait_for(
                lambda: (
                    app.workspace.diagnostic_request != original
                    and not app.workspace.diagnostic_collecting
                )
            )
            screen.stream.require_current()
            assert not screen.stale and not screen.closed
            await app.run_command("ctx kuberich-test-Two")
            await wait_for(lambda: screen.closed and screen.active_count == 0)
        await wait_for(lambda: api.active_watches == 0)


@pytest.mark.asyncio
async def test_selected_workload_uses_exact_controller_chain_and_overview_command_clears_root(
    tmp_path,
):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test():
            await pods_ready(app)
            await app.run_command("deployments other")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.kind == "Deployment"
                    and app.views.table.row_count == 1
                )
            )
            app.views.table.move_cursor(row=0)
            app.views.table.focus()
            await app.run_command("diagnose")
            await diagnostics_ready(app)
            request = app.workspace.diagnostic_request
            assert (
                request.scope.root.kind == "Deployment"
                and request.scope.root.uid == "deployment-other"
            )
            assert request.scope.namespace == "other" and app.state.namespace == "other"
            assert app.workspace.store.observation.diagnostics.findings
            assert any(
                item.category is DiagnosticCategory.CRASH_LOOP and item.subject.uid == "pod-other"
                for item in app.workspace.store.observation.diagnostics.findings
            )
            assert any(
                item.subject.uid == "pod-other"
                for item in app.workspace.store.observation.diagnostics.findings
            )
            assert not any(
                item.subject.uid == "pod-team"
                for item in app.workspace.store.observation.diagnostics.findings
            )
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            assert app.workspace.diagnostic_request.scope.root is None


@pytest.mark.asyncio
@pytest.mark.parametrize("picker", [False, True], ids=["command", "picker"])
async def test_same_namespace_intent_drops_root_advances_generation_and_retires_old_log_capture(
    tmp_path, picker
):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            app.resources.focus()
            await app.run_command("diagnose")
            await diagnostics_ready(app)
            original = app.workspace.diagnostic_request
            assert original.scope.root.uid == "pod-team" and app.state.namespace == "team"
            select(app, log_mode=DiagnosticLogMode.PREVIOUS)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            detail = app.screen
            await pilot.press("p")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and bool(api.log_reads))
            log_screen = app.screen
            await wait_for(lambda: bool(log_screen.history.entries))
            await pilot.press("escape")
            await wait_for(
                lambda: app.screen is detail and log_screen.closed and log_screen.active_count == 0
            )
            await pilot.press("escape")
            await diagnostics_ready(app)
            assert log_screen.stream.current()
            assert app.sessions.observation.identity == original.scope.session
            if picker:
                await app.run_command("ns")
                await wait_for(
                    lambda: (
                        app.state.view_kind == "namespaces"
                        and "namespace-team" in app.namespace_table.rows
                    )
                )
                app.namespace_table.move_cursor(
                    row=app.namespace_table.get_row_index("namespace-team")
                )
                app.namespace_table.focus()
                await pilot.press("enter")
            else:
                await app.run_command("ns team")
            await diagnostics_ready(app)
            fresh = app.workspace.diagnostic_request
            assert (
                fresh.scope.root is None and fresh.scope.namespace == app.state.namespace == "team"
            )
            assert fresh.scope.session.connection_id == original.scope.session.connection_id
            assert fresh.scope.session.generation > original.scope.session.generation
            assert fresh.scope.session == app.sessions.observation.identity
            assert app.workspace.store.observation.diagnostics.request == fresh
            assert app.diagnostics_table.snapshot.request == fresh
            assert not log_screen.stream.current()
            assert api.log_reads[0][1]["previous"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,status",
    [("o", 403), ("e", 403), ("p", 403), ("o", 404), ("e", 404), ("p", 404)],
    ids=["resource-403", "event-403", "previous-403", "resource-404", "event-404", "previous-404"],
)
async def test_expected_finding_get_problem_stays_inline_without_losing_the_native_route(
    tmp_path, action, status
):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            selected = select(app)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            detail = app.screen
            target = detail.events[0].ref if action == "e" else selected.finding.subject
            path = target.resource.path(target.namespace) + "/" + target.name
            api.get_status[path] = status
            before = str(detail.status.content)
            await pilot.press(action)
            await wait_for(lambda: str(detail.status.content) != before)
            assert app.screen is detail and app.state.view_kind == "diagnostics"
            assert str(status) in str(detail.status.content)
            assert path in [path for path, _ in api.reads]
            assert not api.log_reads
            assert app.workspace.store.observation.diagnostics.findings
            api.get_status.clear()
            await pilot.press("escape")
            await diagnostics_ready(app)
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None and app.workspace.ownership.diagnostics_count == 0


@pytest.mark.asyncio
async def test_priority_reconnect_drains_held_evidence_worker_before_client_private_files(tmp_path):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            select(app)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, DiagnosticEvidenceScreen))
            detail = app.screen
            old_client = app.sessions.client
            old_session = app.sessions.observation.identity
            old_directory = Path(old_client.directory.name)
            original_close = app.sessions.before_close
            pending, before_private_close = [], []

            async def observe_close(client):
                await original_close(client)
                if client is old_client:
                    before_private_close.append(
                        (
                            bool(pending) and all(worker.is_finished for worker in pending),
                            old_directory.exists(),
                        )
                    )

            app.sessions.before_close = observe_close
            api.hold_path = "/api/v1/namespaces/team/pods/example"
            try:
                await pilot.press("o")
                await wait_for(api.started.is_set)
                pending.extend(worker for worker in app.workers if worker.node is detail)
                assert pending and any(worker.is_running for worker in pending)
                await pilot.press("f4")
                await wait_for(
                    lambda: (
                        app.sessions.client is not old_client
                        and app.sessions.observation.state in USABLE_CONNECTIONS
                        and not old_directory.exists()
                    )
                )
                assert before_private_close == [(True, True)]
                assert detail.invalidated and all(worker.is_finished for worker in pending)
                assert not any(worker.node is detail for worker in app.workers)
                assert app.sessions.observation.identity.connection_id != old_session.connection_id
                assert app.is_running and not api.log_reads
                await pilot.press("escape")
                await diagnostics_ready(app)
                assert (
                    app.workspace.diagnostic_request.scope.session
                    == app.sessions.observation.identity
                )
            finally:
                api.release.set()
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None
