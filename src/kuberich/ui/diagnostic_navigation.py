"""Captured diagnostic actions and atomic header/root history restoration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from kuberich.domain.cluster_diagnostics import (
    DiagnosticFinding,
    DiagnosticIdentity,
    DiagnosticLogMode,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSourceKind,
)
from kuberich.domain.navigation import NamespaceChoice, NavigationState
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import USABLE_CONNECTIONS, ViewObservation
from kuberich.errors import AppError
from kuberich.ui.diagnostic_evidence import DiagnosticEvidenceScreen, available_log_modes

if TYPE_CHECKING:
    from kuberich.services.workspace import WorkspaceService
    from kuberich.ui.root_views import RootViews
    from kuberich.ui.workspace_navigation import WorkspaceNavigation


class DiagnosticSubmit(Protocol):
    def __call__(
        self, scope: DiagnosticScope, *, header: NamespaceChoice | None = None
    ) -> asyncio.Task[None]: ...


@dataclass(frozen=True)
class _Pending:
    epoch: int
    context: str
    session: SessionIdentity | None
    state: NavigationState | None = None
    after_open: Callable[[], None] | None = None


class DiagnosticNavigation:
    def __init__(
        self,
        workspace: WorkspaceService,
        views: RootViews,
        navigation: WorkspaceNavigation,
        submit: DiagnosticSubmit,
        *,
        resolve: Callable[[DiagnosticRequest, RelationshipRef], Awaitable[ResourceRecord]],
        open_logs: Callable[
            [DiagnosticRequest, DiagnosticFinding, DiagnosticLogMode], Awaitable[None]
        ],
        show_evidence: Callable[[DiagnosticEvidenceScreen], None],
    ) -> None:
        self.workspace, self.views, self.navigation, self.submit = (
            workspace,
            views,
            navigation,
            submit,
        )
        self.resolve, self.show_logs, self.show_evidence = resolve, open_logs, show_evidence
        self._epoch = 0
        self._pending: _Pending | None = None
        self._picker_parent: NavigationState | None = None
        self._picker_session: SessionIdentity | None = None

    @property
    def active(self) -> bool:
        return self.views.route.kind is ViewKind.DIAGNOSTICS

    def invalidate(self) -> None:
        self._epoch += 1
        self._pending = None
        self._picker_parent = None
        self._picker_session = None

    def departing(self, kind: ViewKind) -> None:
        if kind is ViewKind.DIAGNOSTICS:
            return
        parent = self._picker_parent if kind is ViewKind.NAMESPACES else None
        session = self._picker_session if kind is ViewKind.NAMESPACES else None
        self.invalidate()
        self._picker_parent, self._picker_session = parent, session

    def context_changing(self, context: str, *, explicit: bool) -> None:
        active = self.active
        if explicit or context != self.workspace.store.observation.context:
            self.invalidate()
            if active:
                self._pending = _Pending(self._epoch, context, None)

    def overview(self, *, after_open: Callable[[], None] | None = None) -> None:
        view = self.workspace.store.observation
        session = view.connection.identity
        context = (
            self.navigation.sessions.request.context
            or view.context
            or self.navigation.sessions.catalog.current
        )
        if (
            session is not None
            and session.context == context
            and view.context == context
            and view.connection.state in USABLE_CONNECTIONS
            and self.workspace.discovery is not None
        ):
            self.open(DiagnosticScope(session, view.connection.namespace))
            if after_open is not None:
                after_open()
            return
        if context is None:
            raise AppError("Connect to a context before collecting diagnostics.")
        self.navigation.cancel_pending_resource_restore()
        self.invalidate()
        self._pending = _Pending(
            self._epoch,
            context,
            session if session is not None and session.context == context else None,
            after_open=after_open,
        )
        self.navigation.remember()
        self.navigation.display("diagnostics")
        self.navigation.clear_rows()
        self.navigation.notice("Diagnostics is waiting for current session discovery.")
        self.views.request()

    def open(
        self,
        scope: DiagnosticScope,
        *,
        header: NamespaceChoice | None = None,
        remember: bool = True,
    ) -> None:
        previous = self.navigation.capture()
        self.navigation.cancel_pending_resource_restore()
        self.invalidate()
        self.submit(scope, header=header)
        if remember and previous is not None:
            self.navigation.history.visit(previous)
        self.navigation.display("diagnostics")
        self.navigation.clear_rows()
        self.navigation.filter_input.value = ""
        self.navigation.set_errors(False)
        self.views.tables.diagnostics.set_sort("severity", True)
        self.views.request()

    def resolve_pending(self) -> None:
        view = self.workspace.store.observation
        if self._picker_parent is not None and (
            self._picker_parent.context != view.context
            or self._picker_session != view.connection.identity
        ):
            self._picker_parent = None
            self._picker_session = None
        pending = self._pending
        if pending is None:
            return
        if (
            pending.context != view.context
            and pending.context == self.navigation.sessions.request.context
        ):
            return
        if (
            pending.epoch != self._epoch
            or pending.context != view.context
            or (pending.session is not None and pending.session != view.connection.identity)
        ):
            self.invalidate()
            return
        if self.workspace.discovery is None or view.connection.state not in USABLE_CONNECTIONS:
            return
        self._pending = None
        if pending.state is not None:
            self.restore(pending.state)
        else:
            session = view.connection.identity
            assert session is not None
            self.open(DiagnosticScope(session, view.connection.namespace), remember=False)
            if pending.after_open is not None:
                pending.after_open()

    def restore(self, state: NavigationState) -> None:
        bookmark = state.diagnostics
        if bookmark is None:
            return
        self.invalidate()
        view = self.workspace.store.observation
        reconnect = state.context != view.context or view.connection.state not in USABLE_CONNECTIONS
        if reconnect or self.workspace.discovery is None:
            if reconnect:
                self.navigation.connect(
                    state.context, scope=NamespaceChoice(state.namespace), remember=False
                )
            self.navigation.display("diagnostics")
            self.navigation.clear_rows()
            self._pending = _Pending(
                self._epoch, state.context, None if reconnect else view.connection.identity, state
            )
            self.views.request()
            return
        session = view.connection.identity
        assert session is not None
        self.open(
            DiagnosticScope(session, bookmark.namespace, bookmark.root),
            header=NamespaceChoice(state.namespace),
            remember=False,
        )
        self.views.tables.diagnostics.set_sort(state.column, state.descending)
        self.navigation.filter_input.value = state.query
        self.navigation.set_errors(state.errors)
        self.navigation.restore_pending(state)

    def begin_namespace_picker(self) -> None:
        if self.active:
            self._picker_parent = self.navigation.capture()
            self._picker_session = self.workspace.store.observation.connection.identity

    def namespace_selected(self, choice: NamespaceChoice, current: NavigationState | None) -> bool:
        view = self.workspace.store.observation
        parent = (
            self.navigation.capture()
            if self.active
            else self._picker_parent
            if self._picker_session == view.connection.identity
            and self._picker_parent is not None
            and self._picker_parent.context == view.context
            else None
        )
        if parent is None or parent.diagnostics is None or view.connection.identity is None:
            return False
        if current is not None:
            self.navigation.history.visit(current)
        self.open(
            DiagnosticScope(view.connection.identity, choice.namespace),
            header=choice,
            remember=False,
        )
        return True

    def _require_current(self, request: DiagnosticRequest, finding: DiagnosticFinding) -> None:
        view = self.workspace.store.observation
        snapshot = view.diagnostics
        if (
            not self.active
            or request != self.workspace.diagnostic_request
            or request != self.views.tables.diagnostics.request
            or request.scope.session != self.navigation.sessions.observation.identity
            or view.connection.state not in USABLE_CONNECTIONS
            or snapshot is None
            or snapshot.request != request
            or finding not in snapshot.findings
        ):
            raise AppError("Diagnostic evidence changed; return and select a current finding.")

    def _finding(self, key: str | None) -> tuple[DiagnosticRequest, DiagnosticFinding] | None:
        table = self.views.tables.diagnostics
        row = table.row_at(key if key is not None else table.selected_key())
        request = self.workspace.diagnostic_request
        if row is None or row.finding is None or request is None:
            self.navigation.notice(
                "Select a current finding; source and summary rows are informational."
            )
            return None
        self._require_current(request, row.finding)
        return request, row.finding

    def selected(self, key: str | None) -> None:
        selected = self._finding(key)
        if selected is None:
            return
        request, finding = selected

        def current() -> bool:
            try:
                self._require_current(request, finding)
            except AppError:
                return False
            return True

        async def open_object(ref: RelationshipRef) -> None:
            await self._open_reference(request, finding, ref)

        async def open_logs(mode: DiagnosticLogMode) -> None:
            await self._open_logs(request, finding, mode)

        snapshot = self.workspace.store.observation.diagnostics
        assert snapshot is not None
        self.show_evidence(
            DiagnosticEvidenceScreen(
                request,
                finding,
                sources=tuple(
                    source
                    for source in snapshot.sources
                    if source.kind in {finding.source, *(item.source for item in finding.evidence)}
                ),
                current=current,
                open_object=open_object,
                open_logs=open_logs,
                refresh=self.refresh,
            )
        )

    async def _open_reference(
        self, request: DiagnosticRequest, finding: DiagnosticFinding, ref: RelationshipRef
    ) -> None:
        self._require_current(request, finding)
        if (
            ref.resource is None
            or "get" not in ref.resource.verbs
            or (ref != finding.subject and not any(item.ref == ref for item in finding.evidence))
        ):
            raise AppError("This evidence has no served resource identity to open.")
        record = await self.resolve(request, ref)
        self._require_current(request, finding)
        if (
            record.uid is None
            or record.name != ref.name
            or record.namespace != ref.namespace
            or (ref.uid is not None and record.uid != ref.uid)
        ):
            raise AppError("The diagnostic object is missing or replaced; refresh its evidence.")
        if finding.identity is DiagnosticIdentity.NAME_ONLY and ref == finding.subject:
            reported = tuple(
                item.reported_at for item in finding.evidence if item.reported_at is not None
            )
            if record.created_at is not None and reported and record.created_at > min(reported):
                raise AppError(
                    "The current object was created after the report; rerun Popeye for diagnostic linkage."
                )
            self.navigation.notice(
                "Current object by name; report has no UID. Historical identity remains unverified."
            )
        self.navigation.open_resource(ref.resource, ref.namespace, uid=record.uid)

    async def open_object(self, key: str | None = None) -> None:
        selected = self._finding(key)
        if selected is not None:
            request, finding = selected
            if finding.subject is None:
                raise AppError("This finding has no resource identity to open.")
            await self._open_reference(request, finding, finding.subject)

    async def _open_logs(
        self, request: DiagnosticRequest, finding: DiagnosticFinding, mode: DiagnosticLogMode
    ) -> None:
        self._require_current(request, finding)
        if mode not in available_log_modes(finding):
            raise AppError("This finding has no evidence for the requested container log mode.")
        await self.show_logs(request, finding, mode)

    async def open_logs(
        self, key: str | None = None, mode: DiagnosticLogMode = DiagnosticLogMode.CURRENT
    ) -> None:
        selected = self._finding(key)
        if selected is not None:
            await self._open_logs(*selected, mode)

    def refresh(self) -> None:
        state = self.navigation.capture()
        self.workspace.refresh_diagnostics()
        self.navigation.clear_rows()
        if state is not None:
            self.navigation.restore_pending(state)
        self.views.request()

    def restore_ready(self, view: ViewObservation) -> bool:
        snapshot = view.diagnostics
        return (
            snapshot is not None
            and not snapshot.collecting
            and not self.workspace.diagnostic_collecting
            and self.views.tables.diagnostics.request == snapshot.request
            and self.views.tables.diagnostics.snapshot == snapshot
        )

    def message(self, view: ViewObservation) -> str:
        snapshot = view.diagnostics
        banner = ""
        if (
            snapshot is not None
            and snapshot.request.scope.root is not None
            and any(source.kind is DiagnosticSourceKind.POPEYE for source in snapshot.sources)
        ):
            scope = snapshot.request.scope
            assert scope.root is not None
            banner = f" · Popeye scans namespace {scope.namespace}; selected root is {scope.root.name}, not the scan boundary."
        return (
            view.message
            + banner
            + " · Enter evidence · o open resource · Refresh collects native evidence; use :popeye explicitly."
        )
