"""Captured action identities and atomic diagnostic scope/history ports."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from kuberich.domain.cluster_diagnostics import (
    DiagnosticBookmark,
    DiagnosticIdentity,
    DiagnosticLogMode,
    DiagnosticScope,
    DiagnosticSourceKind,
)
from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.diagnostic_rows import diagnostic_rows
from kuberich.domain.navigation import NamespaceChoice, NavigationHistory, NavigationState
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ViewObservation, ViewStatus
from kuberich.errors import AppError
from kuberich.ui.diagnostic_navigation import DiagnosticNavigation
from tests.support.diagnostic_ui import NOW, POD, PODS, finding, snapshot
from tests.ui.test_cluster_diagnostics_table import Host


class Harness:
    def __init__(self, table, *, data=None):
        data = data or snapshot()
        connection = SessionObservation(
            ConnectionState.CONNECTED, "Connected", data.request.scope.session, "header-a"
        )
        observation = ViewObservation(
            context="A", connection=connection, diagnostics=data, status=ViewStatus.LIVE
        )
        self.calls, self.tasks, self.screens, self.notices = [], [], [], []
        self.state = NavigationState(
            "A",
            "header-a",
            query="backoff",
            column="source",
            selected="finding",
            x=9,
            diagnostics=DiagnosticBookmark("team", POD),
            resource="diagnostics",
        )
        self.workspace = SimpleNamespace(
            store=SimpleNamespace(observation=observation),
            discovery=object(),
            diagnostic_request=data.request,
            diagnostic_collecting=False,
            refresh_diagnostics=lambda: self.calls.append(("refresh",)),
        )
        self.views = SimpleNamespace(
            route=ViewRoute.diagnostics(),
            tables=SimpleNamespace(diagnostics=table),
            request=lambda: self.calls.append(("render",)),
        )
        self.navigation = SimpleNamespace(
            capture=lambda: self.state,
            cancel_pending_resource_restore=lambda: self.calls.append(("cancel-restore",)),
            history=NavigationHistory(),
            display=self.display,
            clear_rows=lambda: table.reset(0),
            filter_input=SimpleNamespace(value=""),
            set_errors=lambda errors: self.calls.append(("errors", errors)),
            restore_pending=lambda state: self.calls.append(("restore", state)),
            sessions=SimpleNamespace(
                observation=connection,
                request=SimpleNamespace(context="A"),
                catalog=SimpleNamespace(current="A"),
            ),
            remember=lambda: self.navigation.history.visit(self.state),
            connect=lambda context, **kwargs: self.calls.append(("connect", context, kwargs)),
            notice=self.notices.append,
            open_resource=lambda resource, namespace, **kwargs: self.calls.append(
                ("open", resource, namespace, kwargs)
            ),
        )
        self.record = resource_record(
            PODS,
            {
                "metadata": {
                    "name": POD.name,
                    "namespace": POD.namespace,
                    "uid": POD.uid,
                    "resourceVersion": "observed-rv",
                    "creationTimestamp": "2026-11-01T12:00:00Z",
                }
            },
        )
        self.nav = DiagnosticNavigation(
            self.workspace,
            self.views,
            self.navigation,
            self.submit,
            resolve=self.resolve,
            open_logs=self.logs,
            show_evidence=self.screens.append,
        )

    def display(self, name):
        self.views.route = ViewRoute.diagnostics() if name == "diagnostics" else ViewRoute.pods()

    def submit(self, scope, *, header=None):
        self.calls.append(("submit", scope, header))

        async def complete():
            return None

        task = asyncio.create_task(complete())
        self.tasks.append(task)
        return task

    async def resolve(self, request, ref):
        self.calls.append(("resolve", request, ref))
        return self.record

    async def logs(self, request, item, mode):
        self.calls.append(("logs", request, item, mode))

    def observe(self, **changes):
        self.workspace.store.observation = replace(self.workspace.store.observation, **changes)

    async def drain(self):
        await asyncio.gather(*self.tasks)


@pytest.mark.asyncio
async def test_enter_is_read_only_and_resource_log_actions_capture_actual_reference_and_request():
    app = Host()
    async with app.run_test():
        data = snapshot()
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        owner = Harness(app.table, data=data)
        owner.nav.selected("source:pods")
        assert "informational" in owner.notices[-1] and owner.screens == []
        owner.nav.selected("finding")
        screen = owner.screens[0]
        assert screen.finding == data.findings[0] and screen.current()
        assert {source.kind for source in screen.sources} == {
            DiagnosticSourceKind.CONDITION,
            DiagnosticSourceKind.EVENT,
        }
        assert not any(call[0] == "resolve" for call in owner.calls)
        await screen.open_object(POD)
        assert owner.calls[-1] == ("open", PODS, "team", {"uid": "pod-uid"})
        await owner.nav.open_logs("finding", DiagnosticLogMode.PREVIOUS)
        assert owner.calls[-1] == (
            "logs",
            data.request,
            data.findings[0],
            DiagnosticLogMode.PREVIOUS,
        )
        owner.views.route = ViewRoute.pods()
        assert not screen.current()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        "route",
        "request",
        "table",
        "session",
        "connection",
        "snapshot",
        "snapshot-request",
        "finding",
    ],
)
async def test_stale_findings_cannot_start_object_reads(changed):
    app = Host()
    async with app.run_test():
        data = snapshot()
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        owner = Harness(app.table, data=data)
        if changed == "route":
            owner.views.route = ViewRoute.pods()
        elif changed == "request":
            owner.workspace.diagnostic_request = replace(data.request, revision=2)
        elif changed == "table":
            app.table.request = replace(data.request, revision=2)
        elif changed == "session":
            owner.navigation.sessions.observation = replace(
                owner.navigation.sessions.observation, identity=SessionIdentity("replacement", 1)
            )
        elif changed == "connection":
            owner.observe(connection=SessionObservation())
        elif changed == "snapshot":
            owner.observe(diagnostics=None)
        elif changed == "snapshot-request":
            owner.observe(diagnostics=replace(data, request=replace(data.request, revision=2)))
        else:
            owner.observe(diagnostics=replace(data, findings=()))
        with pytest.raises(AppError, match="changed"):
            await owner.nav.open_object("finding")
        assert not owner.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["uid", "name", "namespace", "missing"])
async def test_resolved_object_requires_exact_original_identity(mismatch):
    app = Host()
    async with app.run_test():
        data = snapshot()
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        owner = Harness(app.table, data=data)
        change = {
            "uid": {"uid": "replaced"},
            "name": {"name": "other"},
            "namespace": {"namespace": "other"},
            "missing": {"uid": None},
        }[mismatch]
        owner.record = replace(owner.record, **change)
        with pytest.raises(AppError, match="missing or replaced"):
            await owner.nav.open_object("finding")
        assert not any(call[0] == "open" for call in owner.calls)


@pytest.mark.asyncio
async def test_session_change_during_explicit_resolution_rejects_late_record():
    app = Host()
    async with app.run_test():
        data = snapshot()
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        owner = Harness(app.table, data=data)
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(request, ref):
            started.set()
            await release.wait()
            return owner.record

        owner.nav.resolve = delayed
        task = asyncio.create_task(owner.nav.open_object("finding"))
        await started.wait()
        owner.navigation.sessions.observation = replace(
            owner.navigation.sessions.observation, identity=SessionIdentity("new-session", 1)
        )
        release.set()
        with pytest.raises(AppError, match="changed"):
            await task
        assert not any(call[0] == "open" for call in owner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("created_later", [False, True, None])
async def test_external_current_by_name_open_preserves_report_time_uncertainty(created_later):
    app = Host()
    item = finding()
    reported = replace(item.evidence[0], reported_at=NOW, observed_at=NOW)
    item = replace(
        item,
        identity=DiagnosticIdentity.NAME_ONLY,
        subject=replace(POD, uid=None),
        source=DiagnosticSourceKind.POPEYE,
        evidence=(reported,),
        log_modes=frozenset(),
    )
    data = snapshot(findings=(item,))
    async with app.run_test():
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        owner = Harness(app.table, data=data)
        owner.record = replace(
            owner.record,
            created_at=NOW + timedelta(seconds=1)
            if created_later
            else None
            if created_later is None
            else NOW - timedelta(seconds=1),
        )
        if created_later:
            with pytest.raises(AppError, match="created after the report"):
                await owner.nav.open_object(item.key)
        else:
            await owner.nav.open_object(item.key)
            assert "report has no UID" in owner.notices[-1]
        await owner.nav.open_logs(item.key)
        assert owner.calls[-1][-1] is DiagnosticLogMode.CURRENT
        with pytest.raises(AppError, match="no evidence"):
            await owner.nav.open_logs(item.key, DiagnosticLogMode.PREVIOUS)


@pytest.mark.asyncio
async def test_history_restores_header_and_root_atomically_and_refresh_retains_bookmark_only():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        owner.nav.restore(owner.state)
        submit = next(call for call in owner.calls if call[0] == "submit")
        assert submit[1] == DiagnosticScope(
            owner.workspace.store.observation.connection.identity, "team", POD
        )
        assert submit[2] == NamespaceChoice("header-a")
        assert owner.navigation.filter_input.value == "backoff"
        assert app.table.sort_column == "source" and not app.table.descending
        assert not owner.navigation.history.previous
        owner.nav.refresh()
        assert ("refresh",) in owner.calls and ("restore", owner.state) in owner.calls
        assert not any(call[0] == "logs" for call in owner.calls)
        await owner.drain()


@pytest.mark.asyncio
@pytest.mark.parametrize("picker", [False, True])
async def test_namespace_selection_even_same_namespace_drops_root_and_submits_once(picker):
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        if picker:
            owner.nav.begin_namespace_picker()
            owner.nav.departing(ViewKind.NAMESPACES)
            owner.views.route = ViewRoute.namespaces()
        assert owner.nav.namespace_selected(NamespaceChoice("team"), owner.state)
        submissions = tuple(call for call in owner.calls if call[0] == "submit")
        assert len(submissions) == 1
        assert submissions[0][1].namespace == "team" and submissions[0][1].root is None
        assert submissions[0][2] == NamespaceChoice("team")
        assert owner.navigation.history.previous == [owner.state]
        await owner.drain()


@pytest.mark.asyncio
async def test_pending_context_history_uses_new_session_and_departure_cancels_queued_intent():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        saved = replace(owner.state, context="B")
        owner.nav.restore(saved)
        assert owner.calls[0] == (
            "connect",
            "B",
            {"scope": NamespaceChoice("header-a"), "remember": False},
        )
        new = SessionObservation(
            ConnectionState.CONNECTED, "Connected", SessionIdentity("new-context", 7), "header-a"
        )
        owner.observe(context="B", connection=new)
        owner.navigation.sessions.observation = new
        owner.nav.resolve_pending()
        submit = next(call for call in owner.calls if call[0] == "submit")
        assert submit[1].session == new.identity and submit[1].root == POD
        await owner.drain()
        owner.calls.clear()
        owner.nav.context_changing("C", explicit=True)
        owner.nav.departing(ViewKind.PODS)
        owner.observe(context="C")
        owner.nav.resolve_pending()
        assert not owner.calls


@pytest.mark.asyncio
async def test_render_restore_waits_for_actual_terminal_snapshot_and_root_popeye_banner_is_clear():
    app = Host()
    data = snapshot()
    async with app.run_test():
        owner = Harness(app.table, data=data)
        loading = replace(data, collecting=True)
        await app.table.apply_rows(diagnostic_rows(loading, now=NOW), loading, lambda: True)
        assert not owner.nav.restore_ready(owner.workspace.store.observation)
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        assert owner.nav.restore_ready(owner.workspace.store.observation)
        popeye = replace(data.sources[0], kind=DiagnosticSourceKind.POPEYE)
        rooted = replace(
            data,
            request=replace(data.request, scope=replace(data.request.scope, root=POD)),
            sources=(popeye,),
        )
        owner.observe(diagnostics=rooted)
        message = owner.nav.message(owner.workspace.store.observation)
        assert "Popeye scans namespace team" in message and "selected root is example" in message
        assert "not the scan boundary" in message


@pytest.mark.asyncio
async def test_new_context_opens_root_free_overview_after_discovery_then_remembers_regular_entry():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        owner.nav.context_changing("A", explicit=False)
        owner.nav.departing(ViewKind.DIAGNOSTICS)
        owner.nav.resolve_pending()
        assert not owner.calls
        owner.nav.context_changing("B", explicit=True)
        owner.workspace.discovery = None
        new = SessionObservation(
            ConnectionState.CONNECTED, "Connected", SessionIdentity("B", 2), "other"
        )
        owner.observe(context="B", connection=new)
        owner.navigation.sessions.observation = new
        owner.nav.resolve_pending()
        assert not owner.calls
        owner.workspace.discovery = object()
        owner.nav.resolve_pending()
        submit = next(call for call in owner.calls if call[0] == "submit")
        assert submit[1] == DiagnosticScope(new.identity, "other")
        assert submit[1].root is None
        await owner.drain()
        owner.nav.open(DiagnosticScope(new.identity, "team"))
        assert owner.navigation.history.previous == [owner.state]
        owner.state = None
        owner.nav.open(DiagnosticScope(new.identity, "team"))
        owner.nav.refresh()
        await owner.drain()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, "session", "context"])
async def test_same_context_pending_discovery_never_crosses_a_replacement_session(stale):
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        owner.workspace.discovery = None
        owner.nav.restore(owner.state)
        assert not any(call[0] == "connect" for call in owner.calls)
        if stale == "session":
            owner.observe(
                connection=replace(
                    owner.workspace.store.observation.connection, identity=SessionIdentity("A", 99)
                )
            )
        elif stale == "context":
            owner.observe(context="C")
        owner.workspace.discovery = object()
        owner.nav.resolve_pending()
        assert any(call[0] == "submit" for call in owner.calls) is (stale is False)
        await owner.drain()


@pytest.mark.asyncio
async def test_picker_capture_is_discarded_after_context_replacement_and_regular_routes_stay_regular():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        owner.nav.begin_namespace_picker()
        owner.nav.departing(ViewKind.NAMESPACES)
        owner.views.route = ViewRoute.namespaces()
        owner.observe(
            connection=replace(
                owner.workspace.store.observation.connection,
                identity=SessionIdentity("replacement", 2),
            )
        )
        owner.nav.resolve_pending()
        assert not owner.nav.namespace_selected(NamespaceChoice("other"), None)
        owner.nav.begin_namespace_picker()
        owner.nav.context_changing("B", explicit=True)
        owner.nav.restore(replace(owner.state, diagnostics=None))
        assert not any(call[0] == "submit" for call in owner.calls)


@pytest.mark.asyncio
async def test_informational_unresolved_and_unrelated_reference_actions_never_become_resources():
    app = Host()
    async with app.run_test():
        data = snapshot()
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        owner = Harness(app.table, data=data)
        owner.nav.selected("source:pods")
        await owner.nav.open_object("source:pods")
        await owner.nav.open_logs("source:pods")
        owner.nav.selected("finding")
        screen = owner.screens[0]
        with pytest.raises(AppError, match="no served resource identity"):
            await screen.open_object(replace(POD, name="unrelated"))
        unresolved = replace(data.findings[0], subject=replace(POD, resource=None))
        data = replace(data, findings=(unresolved,))
        owner.observe(diagnostics=data)
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        with pytest.raises(AppError, match="no served resource identity"):
            await owner.nav.open_object("finding")
        data = replace(data, findings=(replace(unresolved, subject=None),))
        owner.observe(diagnostics=data)
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        with pytest.raises(AppError, match="no resource identity"):
            await owner.nav.open_object("finding")
        assert not any(call[0] in {"open", "resolve"} for call in owner.calls)
        assert "use :popeye explicitly" in owner.nav.message(owner.workspace.store.observation)


@pytest.mark.asyncio
async def test_startup_overview_defers_without_a_fabricated_session_and_runs_explicit_followup_once():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        waiting = SessionObservation(ConnectionState.CONNECTING)
        owner.observe(connection=waiting)
        owner.navigation.sessions.observation = waiting
        owner.workspace.discovery = None
        explicit = []
        owner.nav.overview(after_open=lambda: explicit.append("popeye"))
        assert not any(call[0] == "submit" for call in owner.calls)
        owner.nav.resolve_pending()
        connection = SessionObservation(
            ConnectionState.CONNECTED, "Ready", SessionIdentity("A", 5), "team"
        )
        owner.observe(connection=connection)
        owner.navigation.sessions.observation = connection
        owner.workspace.discovery = object()
        owner.nav.resolve_pending()
        owner.nav.resolve_pending()
        submitted = tuple(call for call in owner.calls if call[0] == "submit")
        assert len(submitted) == 1 and submitted[0][1].session == connection.identity
        assert explicit == ["popeye"]
        await owner.drain()


@pytest.mark.asyncio
async def test_overview_during_context_transition_waits_for_requested_context_not_old_observation():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        owner.workspace.discovery = None
        owner.navigation.sessions.request.context = "B"
        owner.nav.overview()
        owner.nav.resolve_pending()
        connection = SessionObservation(
            ConnectionState.CONNECTED, "Ready", SessionIdentity("B", 3), "other"
        )
        owner.observe(context="B", connection=connection)
        owner.navigation.sessions.observation = connection
        owner.workspace.discovery = object()
        owner.nav.resolve_pending()
        submitted = tuple(call for call in owner.calls if call[0] == "submit")
        assert len(submitted) == 1
        assert submitted[0][1] == DiagnosticScope(connection.identity, "other")
        await owner.drain()


@pytest.mark.asyncio
async def test_offline_overview_requires_an_actual_context_and_cannot_prepare_a_fake_session():
    app = Host()
    async with app.run_test():
        owner = Harness(app.table)
        owner.observe(context=None, connection=SessionObservation())
        owner.workspace.discovery = None
        owner.navigation.sessions.request.context = None
        owner.navigation.sessions.catalog.current = None
        with pytest.raises(AppError, match="Connect to a context"):
            owner.nav.overview()
        assert not any(call[0] == "submit" for call in owner.calls)
