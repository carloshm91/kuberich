"""Freeze the actual foreground export origin through public workspace ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import uuid4

from textual.screen import Screen

from kuberich.domain.authorization import AuthorizationScopeKind
from kuberich.domain.exports import (
    DiagnosticsSource,
    DocumentSource,
    ExportCapture,
    ExportPresentation,
    ExportScope,
    NamespaceMode,
    ResourceSource,
    SupportSource,
)
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.errors import AppError
from kuberich.services.exports import ExportChoices, ExportLease
from kuberich.ui.workspace_screen import WorkspaceScreen

if TYPE_CHECKING:
    from kuberich.services.sessions import SessionService
    from kuberich.services.workspace import WorkspaceService
    from kuberich.ui.nested import CommandWorkspace
    from kuberich.ui.resource_operations import ResourceOperations
    from kuberich.ui.root_views import RootViews
    from kuberich.ui.workspace_presenter import WorkspacePresenter


@runtime_checkable
class CapturableView(Protocol):
    def capture_export(self, at: datetime) -> ExportChoices: ...


_RESOURCE_VIEWS = frozenset(
    {ViewKind.PODS, ViewKind.NAMESPACES, ViewKind.STANDARD, ViewKind.CUSTOM}
)
_PUBLICATION_NOTICE = "Source time is the display publication time; API read time is unavailable."


class WorkspaceExportSources:
    def __init__(
        self,
        *,
        workspace: WorkspaceService,
        sessions: SessionService,
        views: RootViews,
        operations: ResourceOperations,
        presenter: WorkspacePresenter,
        screen: Callable[[], Screen[Any]],
        query: Callable[[], str],
    ) -> None:
        self.workspace, self.sessions, self.views = workspace, sessions, views
        self.operations, self.presenter = operations, presenter
        self.screen, self.query = screen, query

    def capture(self, at: datetime) -> ExportChoices:
        origin = self.screen()
        return self._capture(origin, at, root=isinstance(origin, WorkspaceScreen))

    def origin(self, origin: CommandWorkspace, at: datetime) -> ExportChoices:
        """Freeze a nested command's origin before command navigation can dismiss it."""
        return self._capture(origin, at, root=False)

    def _frame_ready(self, route: ViewRoute, query: str, view: ViewObservation) -> bool:
        frame = self.presenter.export_frame
        return (
            frame is not None
            and frame[:3] == (route, query, view.revision)
            and not self.views.renderer.is_failed(self.presenter.capture())
        )

    def _scope(self, at: datetime, route: ViewRoute, view: ViewObservation) -> ExportScope:
        identity = self.sessions.observation.identity
        header = self.sessions.observation.namespace
        context = identity.context if identity is not None else None
        namespace = None
        mode: NamespaceMode = "unknown"
        api_version = resource = kind = None
        if route.kind is ViewKind.CONTEXTS:
            context, header, mode = None, None, "local"
        elif route.kind in _RESOURCE_VIEWS and view.scope is not None:
            scope = view.scope
            context, namespace = scope.session.context, scope.namespace
            mode = (
                "one"
                if namespace is not None
                else "all"
                if scope.resource.namespaced
                else "cluster"
            )
            api_version, resource, kind = (
                scope.resource.api_version,
                scope.resource.name,
                scope.resource.kind,
            )
        elif route.kind is ViewKind.PULSE and view.pulse is not None:
            context, namespace = view.pulse.scope.session.context, view.pulse.scope.namespace
            mode = "one" if namespace is not None else "all"
        elif route.kind is ViewKind.RELATIONSHIPS and view.relationships is not None:
            relationship_scope = view.relationships.request.scope
            context, namespace = (
                relationship_scope.root.session.context,
                relationship_scope.namespace,
            )
            mode = "one" if namespace is not None else "all"
        elif route.kind is ViewKind.AUTHORIZATION and view.authorization is not None:
            request = view.authorization.request
            context, namespace = request.session.context, request.intent.scope.namespace
            modes: dict[AuthorizationScopeKind, NamespaceMode] = {
                AuthorizationScopeKind.NAMESPACE: "one",
                AuthorizationScopeKind.ALL_NAMESPACES: "all",
                AuthorizationScopeKind.CLUSTER: "cluster",
            }
            mode = modes[request.intent.scope.kind]
        return ExportScope(
            export_at=at,
            source_at=None,
            context=context,
            header_namespace=header,
            collection_namespace=namespace,
            namespace_mode=mode,
            api_version=api_version,
            resource=resource,
            kind=kind,
        )

    def _root(self, origin: Screen[Any], at: datetime) -> ExportChoices:
        route, query, view = self.views.route, self.query(), self.workspace.store.observation
        ready = self._frame_ready(route, query, view)
        if route.kind is ViewKind.DIAGNOSTICS:
            choices = self.views.tables.diagnostics.capture_export(at)
            request = self.workspace.diagnostic_request
            identity, header = (
                self.sessions.observation.identity,
                self.sessions.observation.namespace,
            )
            if request is None or request.scope.session != identity:
                return ()

            def guard(original: Callable[[], bool]) -> Callable[[], bool]:
                return lambda: (
                    original()
                    and self.views.route == route
                    and self.query() == query
                    and self.workspace.diagnostic_request == request
                    and self.sessions.observation.identity == identity
                    and self.sessions.observation.namespace == header
                )

            return tuple(
                (kind, replace(lease, current=guard(lease.current), session=identity))
                for kind, lease in choices
                if (kind != "screen" or ready)
                and (
                    not isinstance(lease.capture.source, DiagnosticsSource)
                    or lease.capture.source.snapshot.request == request
                )
            )
        choices = self.operations.capture_export(at) if route.kind in _RESOURCE_VIEWS else ()
        if not ready:
            return choices
        table = self.views.table
        columns = tuple(column.label.plain for column in table.ordered_columns)
        concealed = frozenset(range(len(columns))) if route.kind is ViewKind.CUSTOM else frozenset()
        try:
            source = table.capture_dump(columns=columns, concealed_columns=concealed)
        except AppError:
            return choices
        identity, header = self.sessions.observation.identity, self.sessions.observation.namespace
        catalog = self.views.catalog() if route.kind is ViewKind.CONTEXTS else None
        sort = getattr(table, "sort_summary", None)
        descending = bool(getattr(table, "descending", False))
        published = self.presenter.export_frame
        assert published is not None
        scope = replace(self._scope(at, route, view), source_at=published[3])

        def current() -> bool:
            return (
                origin.is_mounted
                and origin in origin.app.screen_stack
                and self.views.route == route
                and self.query() == query
                and self.views.table is table
                and getattr(table, "sort_summary", None) == sort
                and bool(getattr(table, "descending", False)) == descending
                and (
                    (self.views.catalog() is catalog)
                    if route.kind is ViewKind.CONTEXTS
                    else (
                        self.sessions.observation.identity == identity
                        and self.sessions.observation.namespace == header
                    )
                )
            )

        notices: tuple[str, ...] = (_PUBLICATION_NOTICE,)
        if route.kind is not ViewKind.CONTEXTS:
            notices += (view.message,)
        lease = ExportLease(
            id=uuid4(),
            capture=ExportCapture(
                scope=scope,
                source=source,
                presentation=ExportPresentation(
                    view=route.display_key,
                    query=query,
                    sort=sort,
                    descending=descending,
                    viewport=table.capture_viewport(),
                ),
                notices=notices,
            ),
            current=current,
            session=None if route.kind is ViewKind.CONTEXTS else identity,
        )
        return (*choices, ("screen", lease))

    def _diagnostics(self, at: datetime) -> ExportLease | None:
        snapshot = self.workspace.store.observation.diagnostics
        request = self.workspace.diagnostic_request
        identity, header = self.sessions.observation.identity, self.sessions.observation.namespace
        if (
            snapshot is None
            or request is None
            or snapshot.request != request
            or request.scope.session != identity
        ):
            return None
        scope = ExportScope(
            export_at=at,
            source_at=snapshot.observed_at,
            context=request.scope.session.context,
            header_namespace=header,
            collection_namespace=request.scope.namespace,
            namespace_mode="one" if request.scope.namespace is not None else "all",
        )

        def current() -> bool:
            return (
                self.workspace.diagnostic_request == request
                and self.sessions.observation.identity == identity
                and self.sessions.observation.namespace == header
            )

        return ExportLease(
            id=uuid4(),
            capture=ExportCapture(scope=scope, source=DiagnosticsSource(snapshot=snapshot)),
            current=current,
            session=identity,
        )

    def _capture(self, origin: Screen[Any], at: datetime, *, root: bool) -> ExportChoices:
        # A screen without a public capture port contributes no underlying table,
        # selected object, configuration, plugin or terminal contents.
        choices = (
            self._root(origin, at)
            if root
            else (origin.capture_export(at) if isinstance(origin, CapturableView) else ())
        )
        diagnostic = self._diagnostics(at)
        resource = logs = None
        omissions: list[str] = []
        for kind, lease in choices:
            source = lease.capture.source
            if kind == "resource-yaml":
                if isinstance(source, ResourceSource) and source.record.metadata_only:
                    omissions.append(
                        "Resource omitted: only metadata is retained; no extra API read was made."
                    )
                elif isinstance(source, ResourceSource) or (
                    isinstance(source, DocumentSource) and source.page in {"yaml", "managed-yaml"}
                ):
                    resource = lease
            elif kind == "logs":
                logs = lease
        if resource is None and not omissions:
            omissions.append("Resource YAML is unavailable for this origin.")
        if logs is None:
            omissions.append("Retained logs are unavailable for this origin.")
        if diagnostic is None:
            omissions.append("A current diagnostic snapshot is unavailable.")
        identity, header = self.sessions.observation.identity, self.sessions.observation.namespace
        local = root and self.views.route.kind is ViewKind.CONTEXTS
        route, query = self.views.route, self.query()
        catalog = self.views.catalog() if local else None
        scope = ExportScope(
            export_at=at,
            source_at=None,
            context=None if local or identity is None else identity.context,
            header_namespace=None if local else header,
            collection_namespace=None if local else header,
            namespace_mode="local"
            if local or identity is None
            else "one"
            if header is not None
            else "all",
        )
        dependencies = tuple(item for item in (diagnostic, resource, logs) if item is not None)

        def current() -> bool:
            return (
                origin.is_mounted
                and origin in origin.app.screen_stack
                and all(item.current() for item in dependencies)
                and (not root or (self.views.route == route and self.query() == query))
                and (not local or self.views.catalog() is catalog)
                and (
                    local
                    or (
                        self.sessions.observation.identity == identity
                        and self.sessions.observation.namespace == header
                    )
                )
            )

        support = ExportLease(
            id=uuid4(),
            capture=ExportCapture(
                scope=scope,
                source=SupportSource(
                    diagnostics=diagnostic.capture if diagnostic else None,
                    resource=resource.capture if resource else None,
                    logs=logs.capture if logs else None,
                    omissions=tuple(omissions),
                ),
            ),
            current=current,
            session=None if local else identity,
        )
        return (*choices, ("support", support))
