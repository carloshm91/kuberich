"""Foreground-only export capture, actual painted tables and honest retained scopes."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from kuberich.domain.cluster_diagnostics import (
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSnapshot,
)
from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.events import EventOptions
from kuberich.domain.exports import (
    DiagnosticsSource,
    DocumentSource,
    ExportCapture,
    ExportScope,
    ResourceSource,
    SingleLogsSource,
    SupportSource,
    prepare_capture,
)
from kuberich.domain.log_view import LogEntry
from kuberich.domain.logs import LogLine, LogOptions
from kuberich.domain.navigation import Viewport
from kuberich.domain.resources import (
    ApiResource,
    resource_record,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ResourceScope, ResourceSelection, ViewObservation, ViewStatus
from kuberich.errors import AppError
from kuberich.services.exports import ExportLease
from kuberich.ui.export_sources import WorkspaceExportSources
from kuberich.ui.foreground import ForegroundGate
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.presentation import FrameTable
from kuberich.ui.workspace_screen import WorkspaceScreen
from tests.support.pods import pod

AT = datetime(2026, 11, 5, 12, tzinfo=UTC)
PUBLISHED = datetime(2026, 11, 5, 11, 59, tzinfo=UTC)
PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list", "watch"}))


def captured(source, *, session=None, current=lambda: True):
    return ExportLease(
        id=uuid4(),
        capture=ExportCapture(
            scope=ExportScope(
                export_at=AT,
                source_at=PUBLISHED,
                context=session.context if session else None,
                header_namespace="header",
                collection_namespace="collection",
                namespace_mode="one",
            ),
            source=source,
        ),
        current=current,
        session=session,
    )


def resource_choice(session, *, metadata_only=False):
    record = resource_record(
        PODS, pod("owned", uid="owned-uid", namespace="collection"), "collection"
    )
    return captured(
        ResourceSource(resource=PODS, record=replace(record, metadata_only=metadata_only)),
        session=session,
    )


class CapturedTable(FrameTable[str]):
    sort_summary = "NAME ascending"
    descending = False
    inconsistent = False

    def capture_viewport(self):
        return Viewport("owned-uid", self.cursor_row, self.scroll_x, self.scroll_y, "owned-uid")

    def capture_dump(self, **kwargs):
        if self.inconsistent:
            raise AppError("owned inconsistent shape")
        return super().capture_dump(**kwargs)


class RootScreen(WorkspaceScreen):
    def __init__(self, table):
        super().__init__(ForegroundGate(lambda: None))
        self.table = table

    def compose(self) -> ComposeResult:
        yield self.table


class CaptureApp(App[None]):
    def __init__(self):
        super().__init__()
        self.table = CapturedTable()
        self.root = RootScreen(self.table)

    def get_default_screen(self):
        return self.root


class Origin(CommandWorkspace):
    def __init__(self, choices):
        super().__init__()
        self.choices = choices

    def capture_export(self, at):
        return self.choices

    def compose(self) -> ComposeResult:
        yield Static("captured nested origin")


class Uncapturable(Screen[None]):
    sensitive = True

    def compose(self) -> ComposeResult:
        yield Static("private contents must never enter support")


class SourceState:
    def __init__(self, app):
        self.app = app
        self.identity = SessionIdentity("fixture", 1)
        self.query = ["painted"]
        self.catalog = [object()]
        self.sessions = SimpleNamespace(
            observation=SessionObservation(
                ConnectionState.CONNECTED, "connected", self.identity, "header"
            )
        )
        scope = ResourceScope(self.identity, PODS, "collection")
        self.workspace = SimpleNamespace(
            store=SimpleNamespace(
                observation=ViewObservation(
                    revision=7,
                    context="fixture",
                    connection=self.sessions.observation,
                    scope=scope,
                    status=ViewStatus.LIVE,
                )
            ),
            diagnostic_request=None,
        )
        self.resource = resource_choice(self.identity)
        self.operations = SimpleNamespace(calls=0)

        def resources(at):
            self.operations.calls += 1
            return (("resource-yaml", self.resource),)

        self.operations.capture_export = resources
        self.renderer = SimpleNamespace(failed=False)
        self.renderer.is_failed = lambda request: self.renderer.failed
        self.diagnostics = SimpleNamespace(choices=())
        self.diagnostics.capture_export = lambda at: self.diagnostics.choices
        self.views = SimpleNamespace(
            route=ViewRoute.pods(),
            curated=None,
            event_options=EventOptions(),
            table=app.table,
            renderer=self.renderer,
            catalog=lambda: self.catalog[0],
            tables=SimpleNamespace(diagnostics=self.diagnostics),
        )
        self.presenter = SimpleNamespace(
            export_frame=(self.views.route, self.query[0], 7, PUBLISHED), capture=lambda: object()
        )
        self.source = WorkspaceExportSources(
            workspace=self.workspace,
            sessions=self.sessions,
            views=self.views,
            operations=self.operations,
            presenter=self.presenter,
            screen=lambda: app.screen,
            query=lambda: self.query[0],
        )

    def paint(self, route, view=None):
        self.views.route = route
        if view is not None:
            self.workspace.store.observation = view
        self.presenter.export_frame = (
            route,
            self.query[0],
            self.workspace.store.observation.revision,
            PUBLISHED,
        )


@pytest_asyncio.fixture
async def painted():
    app = CaptureApp()
    async with app.run_test() as pilot:
        app.table.add_columns("NAME", "DETAIL")
        app.table.add_row("owned", "literal [red] retained", key="owned-uid")
        state = SourceState(app)
        yield state, pilot


@pytest.mark.asyncio
async def test_root_dump_matches_painted_frame_and_survives_new_rows_scroll_and_watch(painted):
    state, _ = painted
    choices = dict(state.source.capture(AT))
    lease = choices["screen"]
    assert lease.capture.source.rows == (("owned", "literal [red] retained"),)
    assert lease.capture.scope.header_namespace == "header"
    assert lease.capture.scope.collection_namespace == "collection"
    assert lease.capture.scope.source_at == PUBLISHED
    assert "publication" in lease.capture.notices[0]
    assert lease.capture.presentation.query == "painted"
    state.app.table.add_row("new-watch-row", "more", key="new-uid")
    state.workspace.store.observation = replace(state.workspace.store.observation, revision=8)
    state.app.table.move_cursor(row=1)
    state.app.table.scroll_to(y=1, animate=False)
    assert lease.current() and len(lease.capture.source.rows) == 1
    # The current frame is now pending; an independently captured object remains usable.
    assert set(dict(state.source.capture(AT))) == {"resource-yaml", "support"}
    state.query[0] = "unpainted"
    assert not lease.current()
    state.query[0] = "painted"
    state.app.table.sort_summary = "NAME descending"
    assert not lease.current()
    state.app.table.sort_summary = "NAME ascending"
    state.sessions.observation = replace(state.sessions.observation, namespace=None)
    assert not lease.current()
    state.sessions.observation = replace(
        state.sessions.observation, namespace="header", identity=SessionIdentity("fixture", 2)
    )
    assert not lease.current()


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["missing", "route", "query", "revision", "failed", "shape"])
async def test_pending_or_failed_frame_never_relabels_table_data(painted, pending):
    state, _ = painted
    if pending == "missing":
        state.presenter.export_frame = None
    elif pending == "failed":
        state.renderer.failed = True
    elif pending == "shape":
        state.app.table.inconsistent = True
    else:
        route, query, revision, at = state.presenter.export_frame
        state.presenter.export_frame = (
            ViewRoute.namespaces() if pending == "route" else route,
            "other" if pending == "query" else query,
            revision + 1 if pending == "revision" else revision,
            at,
        )
    assert set(dict(state.source.capture(AT))) == {"resource-yaml", "support"}


@pytest.mark.asyncio
async def test_custom_columns_are_concealed_by_provenance_even_with_innocent_headings(painted):
    state, _ = painted
    route = ViewRoute.custom(ResourceSelection("widgets", "example.test", server_columns=True))
    state.paint(route)
    state.app.table.update_cell(
        "owned-uid", state.app.table.ordered_columns[1].key, "SECRET-SERVER-COLUMN"
    )
    lease = dict(state.source.capture(AT))["screen"]
    assert lease.capture.source.concealed_columns == frozenset({0, 1})
    assert "SECRET-SERVER-COLUMN" not in str(lease.capture.source.rows)
    assert all(value == "[REDACTED COLUMN]" for value in lease.capture.source.rows[0])
    assert (
        b"SECRET-SERVER-COLUMN"
        not in prepare_capture(lease.capture, "screen", artifact_id=uuid4()).payload
    )


@pytest.mark.asyncio
async def test_context_dump_is_local_and_tracks_catalog_instead_of_connected_scope(painted):
    state, _ = painted
    state.paint(ViewRoute.contexts())
    lease = dict(state.source.capture(AT))["screen"]
    assert lease.capture.scope.context is None and lease.capture.scope.namespace_mode == "local"
    assert lease.session is None and lease.capture.scope.header_namespace is None
    assert state.operations.calls == 0
    state.sessions.observation = replace(
        state.sessions.observation, identity=SessionIdentity("different", 9), namespace=None
    )
    assert lease.current()
    state.catalog[0] = object()
    assert not lease.current()


@pytest.mark.asyncio
async def test_unknown_sensitive_screen_offers_only_fixed_safe_report(painted):
    state, pilot = painted
    state.app.push_screen(Uncapturable())
    await pilot.pause()
    choices = dict(state.source.capture(AT))
    assert set(choices) == {"support"} and state.operations.calls == 0
    support = choices["support"].capture.source
    assert isinstance(support, SupportSource)
    assert support.resource is None and support.logs is None and support.diagnostics is None
    assert "private contents" not in repr(support)
    assert choices["support"].capture.scope.uid is None
    assert choices["support"].capture.scope.source_at is None


@pytest.mark.asyncio
async def test_nested_origin_frozen_before_navigation_and_only_public_optins(painted):
    state, pilot = painted
    document = captured(
        DocumentSource(page="managed-yaml", text="kind: Pod\nmetadata:\n  name: loaded"),
        session=state.identity,
    )
    logs = captured(
        SingleLogsSource(
            options=LogOptions(),
            head_lines=None,
            entries=(LogEntry(1, LogLine("2026-11-05T10:00:00Z retained")),),
            dropped_lines=2,
            show_timestamps=True,
        ),
        session=state.identity,
    )
    screen = Origin((("resource-yaml", document), ("screen", document), ("logs", logs)))
    state.app.push_screen(screen)
    await pilot.pause()
    choices = dict(state.source.origin(screen, AT))
    assert state.operations.calls == 0 and choices["resource-yaml"] is document
    support = choices["support"]
    assert support.capture.source.resource is document.capture
    assert support.capture.source.logs is logs.capture
    assert support.current()
    state.app.pop_screen()
    await pilot.pause()
    assert not support.current()


@pytest.mark.asyncio
async def test_metadata_only_resource_omitted_from_support_without_get(painted):
    state, _ = painted
    state.resource = resource_choice(state.identity, metadata_only=True)
    choices = dict(state.source.capture(AT))
    assert choices["resource-yaml"] is state.resource
    source = choices["support"].capture.source
    assert source.resource is None and "metadata" in source.omissions[0]
    assert "extra API read" in source.omissions[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["collection", None])
async def test_progress_diagnostic_support_keeps_full_current_snapshot_scope(painted, namespace):
    state, _ = painted
    request = DiagnosticRequest(DiagnosticScope(state.identity, namespace), 1)
    snapshot = DiagnosticSnapshot(request, (), (), True, 3, PUBLISHED)
    state.workspace.diagnostic_request = request
    state.workspace.store.observation = replace(
        state.workspace.store.observation, diagnostics=snapshot
    )
    support = dict(state.source.capture(AT))["support"]
    assert support.capture.source.diagnostics.source.snapshot is snapshot
    component = support.capture.source.diagnostics
    assert (
        component.scope.collection_namespace == namespace
        and component.scope.header_namespace == "header"
    )
    assert component.scope.source_at == PUBLISHED and component.source.snapshot.collecting
    assert (
        support.capture.scope.collection_namespace == "header" and support.capture.scope.uid is None
    )
    state.workspace.store.observation = replace(
        state.workspace.store.observation, diagnostics=replace(snapshot, native_requests_used=4)
    )
    assert support.current()  # Normal collection progress cannot mutate the captured tuple.
    state.workspace.diagnostic_request = replace(request, revision=2)
    assert not support.current()
    stale = dict(state.source.capture(AT))["support"].capture.source
    assert stale.diagnostics is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family,namespace,mode",
    [
        ("resource", None, "all"),
        ("cluster", None, "cluster"),
        ("missing", None, "unknown"),
        ("pulse", "collection", "one"),
        ("pulse", None, "all"),
        ("relationships", "collection", "one"),
        ("relationships", None, "all"),
        ("authorization", "collection", "one"),
        ("authorization", None, "all"),
        ("authorization-cluster", None, "cluster"),
    ],
)
async def test_table_scopes_use_collection_contract_instead_of_header(
    painted, family, namespace, mode
):
    from kuberich.domain.authorization import (
        AuthorizationIntent,
        AuthorizationMode,
        AuthorizationRequest,
        AuthorizationScope,
        AuthorizationScopeKind,
        AuthorizationSnapshot,
    )
    from kuberich.domain.pulse import PulseScope, PulseSnapshot
    from kuberich.domain.relationships import (
        RelationshipMode,
        RelationshipRequest,
        RelationshipScope,
        RelationshipSnapshot,
    )
    from kuberich.domain.targets import ResourceTarget

    state, _ = painted
    view = state.workspace.store.observation
    if family in {"resource", "cluster", "missing"}:
        route = ViewRoute.namespaces() if family == "cluster" else ViewRoute.pods()
        resource = (
            ApiResource("", "v1", "namespaces", "Namespace", False, frozenset({"list"}))
            if family == "cluster"
            else PODS
        )
        view = replace(
            view,
            scope=None
            if family == "missing"
            else ResourceScope(state.identity, resource, namespace),
        )
    elif family == "pulse":
        route = ViewRoute.pulse()
        view = replace(view, pulse=PulseSnapshot(PulseScope(state.identity, namespace)))
    elif family == "relationships":
        route = ViewRoute.relationships()
        target = ResourceTarget(state.identity, "", "pods", "root", "owned", "uid")
        request = RelationshipRequest(
            RelationshipScope(target, PODS, namespace, RelationshipMode.XRAY), 1, frozenset()
        )
        view = replace(view, relationships=RelationshipSnapshot(request, (), (), 0, PUBLISHED))
    else:
        route = ViewRoute.authorization()
        kind = (
            AuthorizationScopeKind.CLUSTER
            if family == "authorization-cluster"
            else AuthorizationScopeKind.NAMESPACE
            if namespace
            else AuthorizationScopeKind.ALL_NAMESPACES
        )
        request = AuthorizationRequest(
            state.identity,
            1,
            AuthorizationIntent(AuthorizationMode.ROLES, AuthorizationScope(kind, namespace)),
        )
        view = replace(
            view, authorization=AuthorizationSnapshot(request, None, None, None, None, None, True)
        )
    state.paint(route, view)
    scope = dict(state.source.capture(AT))["screen"].capture.scope
    assert scope.collection_namespace == namespace and scope.header_namespace == "header"
    assert scope.namespace_mode == mode and scope.context == "fixture"


@pytest.mark.asyncio
async def test_incomplete_stale_collection_and_unknown_native_payload_remain_visible_notices(
    painted,
):
    from kuberich.domain.connections import HttpProblem
    from kuberich.domain.resources import CollectionState, ResourceSnapshot

    state, _ = painted
    snapshot = ResourceSnapshot(
        PODS, "collection", "list-version", (), collection=CollectionState(False, True, 1, 0)
    )
    view = replace(state.workspace.store.observation, snapshot=snapshot)
    state.paint(ViewRoute.pods(), view)
    assert "INCOMPLETE" in dict(state.source.capture(AT))["screen"].capture.notices[1]
    view = replace(view, status=ViewStatus.STALE, problem=HttpProblem(403))
    state.paint(ViewRoute.pods(), view)
    assert "403" in dict(state.source.capture(AT))["screen"].capture.notices[1]
    # Missing optional aggregate evidence remains explicitly unknown.
    for route in (ViewRoute.pulse(), ViewRoute.relationships(), ViewRoute.authorization()):
        state.paint(route, replace(view, scope=None))
        assert dict(state.source.capture(AT))["screen"].capture.scope.namespace_mode == "unknown"


@pytest.mark.asyncio
async def test_diagnostic_table_full_facts_remain_separate_from_pending_screen(painted):
    from kuberich.domain.exports import TableSource

    state, _ = painted
    request = DiagnosticRequest(DiagnosticScope(state.identity, "collection"), 1)
    snapshot = DiagnosticSnapshot(request, (), (), True, 2, PUBLISHED)
    state.workspace.diagnostic_request = request
    diagnostic = captured(DiagnosticsSource(snapshot=snapshot), session=state.identity)
    screen = captured(
        TableSource(
            columns=("FINDING",),
            rows=(("painted finding",),),
            row_keys=("finding",),
            concealed_columns=frozenset(),
        )
    )
    state.diagnostics.choices = (("diagnostics", diagnostic), ("screen", screen))
    state.paint(
        ViewRoute.diagnostics(), replace(state.workspace.store.observation, diagnostics=snapshot)
    )
    choices = dict(state.source.capture(AT))
    assert choices["diagnostics"].capture.source.snapshot is snapshot
    assert choices["screen"].capture.source.rows == (("painted finding",),)
    state.presenter.export_frame = None
    assert set(dict(state.source.capture(AT))) == {"diagnostics", "support"}
    state.workspace.diagnostic_request = replace(request, revision=2)
    assert not choices["diagnostics"].current()
    assert set(dict(state.source.capture(AT))) == {"support"}
    state.workspace.diagnostic_request = None
    assert set(dict(state.source.capture(AT))) == {"support"}


@pytest.mark.asyncio
async def test_support_guards_own_route_query_catalog_and_exact_diagnostic_session(painted):
    state, _ = painted
    state.paint(ViewRoute.contexts())
    support = dict(state.source.capture(AT))["support"]
    assert support.capture.scope.namespace_mode == "local"
    state.catalog[0] = object()
    assert not support.current()
    state.paint(ViewRoute.pods())
    support = dict(state.source.capture(AT))["support"]
    state.query[0] = "new-query"
    assert not support.current()
    state.query[0] = "painted"
    request = DiagnosticRequest(DiagnosticScope(SessionIdentity("other", 2), "collection"), 1)
    state.workspace.diagnostic_request = request
    state.workspace.store.observation = replace(
        state.workspace.store.observation,
        diagnostics=DiagnosticSnapshot(request, (), (), False, 0, None),
    )
    assert dict(state.source.capture(AT))["support"].capture.source.diagnostics is None
    state.sessions.observation = SessionObservation()
    # Disconnected support describes only this local safe report.
    support = dict(state.source.capture(AT))["support"]
    assert support.capture.scope.namespace_mode == "local" and support.capture.scope.context is None


@pytest.mark.asyncio
async def test_actual_app_capture_and_secret_curated_table_never_collects_secret_values(tmp_path):
    import logging

    from aiohttp import web

    from kuberich.config.schema import Settings
    from kuberich.domain.registry import RESOURCE_ALIASES
    from kuberich.ui.app import KubeRichApp
    from tests.support.connections import catalog_fixture, namespaces
    from tests.support.resources import collection
    from tests.support.workspace import stable_watch, wait_for, workspace_api

    async def namespace_handler(request):
        return namespaces("team")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("owned", uid="actual-owned")))

    async with workspace_api(namespace_handler, resources) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("exports", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        async with app.run_test() as pilot:
            await wait_for(
                lambda: app.presenter.export_frame is not None and app.resources.row_count == 1
            )
            choices = dict(app.export_sources.capture(AT))
            assert {"screen", "resource-yaml", "support"} <= set(choices)
            assert choices["screen"].capture.scope.header_namespace == "team"
            # Standard Secret projection is a native counts/type view, independently
            # verified with the actual static definition rather than title matching.
            definition = RESOURCE_ALIASES["secrets"]
            assert {field.key for field in definition.fields} == {"type", "data"}
            from kuberich.domain.registry import resource_row

            secret_resource = ApiResource("", "v1", "secrets", "Secret", True, frozenset({"get"}))
            record = resource_record(
                secret_resource,
                {
                    "metadata": {"name": "one", "namespace": "team", "uid": "secret-uid"},
                    "data": {"value": "DO-NOT-COLLECT-SECRET"},
                    "type": "Opaque",
                },
                "team",
            )
            row = resource_row(record, definition)
            assert "DO-NOT-COLLECT-SECRET" not in str(row)
            app.views.select(ViewRoute.contexts())
            await pilot.pause()
            # Selection alone does not invent a newly painted context frame.
            assert "screen" not in dict(app.export_sources.capture(AT))


@pytest.mark.asyncio
async def test_bundle_role_uses_document_provenance_instead_of_claimed_format_name(painted):
    state, pilot = painted
    document = captured(DocumentSource(page="evidence", text="observed evidence"))
    origin = Origin((("resource-yaml", document),))
    state.app.push_screen(origin)
    await pilot.pause()
    support = dict(state.source.origin(origin, AT))["support"].capture.source
    assert support.resource is None and "unavailable" in support.omissions[0]


def test_fresh_export_source_import_has_no_transport_or_document_editor_side_effects():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import kuberich.ui.export_sources; assert not any(name.startswith(('aiohttp', 'kubernetes_asyncio')) for name in sys.modules); assert 'textual.widgets._text_area' not in sys.modules; assert 'textual.document' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
