"""Fresh Helm scopes behind native commands, namespace picker and history."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from kuberich.domain.connections import ConnectionState
from kuberich.domain.helm import HelmScope, HelmSettings
from kuberich.domain.navigation import NamespaceChoice, NavigationState
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import USABLE_CONNECTIONS, ViewObservation
from kuberich.errors import AppError

if TYPE_CHECKING:
    from kuberich.services.workspace import WorkspaceService
    from kuberich.ui.root_views import RootViews
    from kuberich.ui.workspace_navigation import WorkspaceNavigation


class HelmNavigation:
    def __init__(
        self,
        workspace: WorkspaceService,
        views: RootViews,
        navigation: WorkspaceNavigation,
        settings: Callable[[], HelmSettings],
    ) -> None:
        self.workspace, self.views, self.navigation, self.settings = (
            workspace,
            views,
            navigation,
            settings,
        )
        self._pending: tuple[str, NamespaceChoice | None, NavigationState | None, bool] | None = (
            None
        )
        self._picker_parent: NavigationState | None = None

    @property
    def active(self) -> bool:
        return self.views.route.kind is ViewKind.HELM

    def departing(self, kind: ViewKind) -> None:
        if kind is not ViewKind.HELM:
            self._pending = None
        if kind not in {ViewKind.HELM, ViewKind.NAMESPACES}:
            self._picker_parent = None

    def command(self, argument: str | None = None) -> None:
        self.settings()  # Validate the explicitly requested driver before changing route.
        view = self.workspace.store.observation
        choice = (
            None
            if argument is None and view.connection.state not in USABLE_CONNECTIONS
            else NamespaceChoice(
                view.connection.namespace
                if argument is None
                else None
                if argument == "*"
                else argument
            )
        )
        self.open(choice)

    def open(
        self,
        choice: NamespaceChoice | None,
        *,
        state: NavigationState | None = None,
        remember: bool = True,
        collect: bool = True,
    ) -> asyncio.Task[None] | None:
        settings = self.settings()
        view = self.workspace.store.observation
        session = view.connection.identity
        context = (
            state.context
            if state is not None
            else view.context
            or self.navigation.sessions.request.context
            or self.navigation.sessions.catalog.current
        )
        if context is None:
            raise AppError("Connect to a context before browsing Helm releases.")
        if (
            session is None
            or context != view.context
            or view.connection.state not in USABLE_CONNECTIONS
        ):
            if remember:
                self.navigation.remember()
            self.navigation.display("helm")
            self.navigation.clear_rows()
            self._pending = context, choice, state, collect
            if context != view.context or view.connection.state not in USABLE_CONNECTIONS:
                self.navigation.connect(context, scope=choice, remember=False)
            self.navigation.notice("Helm is waiting for the current context connection.")
            return None
        choice = choice or NamespaceChoice(view.connection.namespace)
        previous = self.navigation.capture()
        self.navigation.cancel_pending_resource_restore()
        transition = self.workspace.select_helm(
            HelmScope(session, choice.namespace, settings.driver), header=choice, collect=collect
        )
        if remember and previous is not None:
            self.navigation.history.visit(previous)
        self._pending = None
        self.navigation.display("helm")
        self.navigation.clear_rows()
        self.navigation.filter_input.value = state.query if state is not None else ""
        self.navigation.set_errors(False)
        if state is not None:
            self.navigation.restore_pending(state)
        self.views.request()
        return transition

    def resolve_pending(self) -> None:
        pending = self._pending
        if pending is None:
            return
        context, choice, state, collect = pending
        view = self.workspace.store.observation
        if self.active and context == view.context and view.connection.state in USABLE_CONNECTIONS:
            self._pending = None
            self.open(choice, state=state, remember=False, collect=collect)

    def restore(self, state: NavigationState) -> None:
        bookmark = state.helm
        if bookmark is not None:
            self.open(NamespaceChoice(bookmark.namespace), state=state, remember=False)

    def begin_namespace_picker(self) -> None:
        if self.active:
            self._picker_parent = self.navigation.capture()

    def namespace_selected(self, choice: NamespaceChoice, current: NavigationState | None) -> bool:
        parent = self.navigation.capture() if self.active else self._picker_parent
        view = self.workspace.store.observation
        if parent is None or parent.helm is None or parent.context != view.context:
            return False
        if current is not None:
            self.navigation.history.visit(current)
        self._picker_parent = None
        self.open(choice, remember=False)
        return True

    def refresh(self) -> None:
        view = self.workspace.store.observation
        request = self.workspace.helm_request
        if request is None or view.connection.state not in USABLE_CONNECTIONS:
            if self._pending is not None:
                context, choice, state, collect = self._pending
                if view.connection.state in USABLE_CONNECTIONS:
                    self.open(choice, state=state, remember=False, collect=collect)
                else:
                    # None preserves an inherited namespace until connection;
                    # NamespaceChoice(None) preserves explicitly requested all.
                    self.navigation.connect(context, scope=choice, remember=False)
            else:
                self.open(
                    NamespaceChoice(
                        request.scope.namespace
                        if request is not None
                        else view.connection.namespace
                    ),
                    remember=False,
                )
            self.views.request()
            return
        state = self.navigation.capture()
        self.workspace.refresh_helm()
        if state is not None:
            self.navigation.restore_pending(state)
        self.views.request()

    def restore_ready(self, view: ViewObservation) -> bool:
        snapshot = view.helm
        return (
            snapshot is not None
            and not snapshot.collecting
            and self.views.tables.helm.request == snapshot.request
        )

    def message(self, view: ViewObservation) -> str:
        if view.connection.state not in USABLE_CONNECTIONS | {
            ConnectionState.CONNECTING,
            ConnectionState.DISCONNECTED,
        }:
            return view.connection.message + " · F4 or :refresh reconnect · :ctx choose context"
        snapshot = view.helm
        if snapshot is None:
            return "Helm · waiting for current connection"
        if snapshot.problem is not None:
            retained = " · STALE retained releases" if snapshot.listing is not None else ""
            return str(snapshot.problem) + retained + " · F4 retry · :helm NAMESPACE narrow scope"
        if snapshot.collecting:
            return "Helm · refreshing release storage · previous rows are stale"
        if snapshot.listing is None:
            return "Helm release collection has not started · F4 collect · :helmcharts browse cached charts"
        return "Helm releases · Enter inspect · F4 refresh · :helm NAMESPACE or *" + (
            " · INCOMPLETE: first 500 releases; narrow namespace"
            if snapshot.listing is not None and not snapshot.listing.complete
            else ""
        )
