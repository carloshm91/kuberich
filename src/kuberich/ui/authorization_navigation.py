"""Own authorization intents and their history without adding transport work to widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationRequest,
)
from kuberich.domain.authorization_rows import AuthorizationRow
from kuberich.domain.navigation import NamespaceChoice, NavigationState
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import USABLE_CONNECTIONS, ResourceSelection, ViewObservation
from kuberich.errors import AppError
from kuberich.services.authorization_commands import AuthorizationCommand, authorization_intent
from kuberich.services.authorization_workspace import AuthorizationSubmit

if TYPE_CHECKING:
    from kuberich.domain.targets import SessionIdentity
    from kuberich.services.workspace import WorkspaceService
    from kuberich.ui.root_views import RootViews
    from kuberich.ui.workspace_navigation import WorkspaceNavigation


@dataclass(frozen=True)
class _Pending:
    epoch: int
    context: str
    session: SessionIdentity | None
    command: AuthorizationCommand | None = None
    state: NavigationState | None = None


class AuthorizationNavigation:
    def __init__(
        self,
        workspace: WorkspaceService,
        views: RootViews,
        navigation: WorkspaceNavigation,
        submit: AuthorizationSubmit,
    ) -> None:
        self.workspace, self.views, self.navigation, self.submit = (
            workspace,
            views,
            navigation,
            submit,
        )
        self._epoch = 0
        self._pending: _Pending | None = None
        self._picker_parent: NavigationState | None = None
        self._picker_session: SessionIdentity | None = None
        self._transition_notice: tuple[AuthorizationRequest, str] | None = None

    @property
    def active(self) -> bool:
        return self.views.route.kind is ViewKind.AUTHORIZATION

    def invalidate(self) -> None:
        self._epoch += 1
        self._pending = None
        self._picker_parent = None
        self._picker_session = None

    def departing(self, kind: ViewKind) -> None:
        if kind is ViewKind.AUTHORIZATION:
            return
        parent = self._picker_parent if kind is ViewKind.NAMESPACES else None
        session = self._picker_session if kind is ViewKind.NAMESPACES else None
        self.invalidate()
        self._picker_parent = parent
        self._picker_session = session

    def context_changing(self, context: str, *, explicit: bool) -> None:
        if explicit or context != self.workspace.store.observation.context:
            self.invalidate()
        if self.active and context != self.workspace.store.observation.context:
            self.workspace.prepare_resource(ResourceSelection())
            self.navigation.display("pods")

    def command(self, command: AuthorizationCommand) -> None:
        self.navigation.cancel_pending_resource_restore()
        self.invalidate()
        view, discovery = self.workspace.store.observation, self.workspace.discovery
        if discovery is None:
            context = (
                view.context
                or self.navigation.sessions.request.context
                or self.navigation.sessions.catalog.current
            )
            if context is None:
                raise AppError("Connect to a context before asking an authorization question.")
            self._pending = _Pending(
                self._epoch, context, view.connection.identity, command=command
            )
            self.navigation.remember()
            self.navigation.display("authorization")
            self.navigation.clear_rows()
            self.navigation.notice("Authorization question is waiting for current discovery.")
            self.views.request()
            return
        self.open(authorization_intent(command, discovery, view.connection.namespace))

    def open(
        self,
        intent: AuthorizationIntent,
        *,
        remember: bool = True,
        scope: NamespaceChoice | None = None,
        preserve_intent: bool = False,
    ) -> None:
        previous = self.navigation.capture()
        self.navigation.cancel_pending_resource_restore()
        self.invalidate()
        self._transition_notice = None
        self.submit(intent, scope=scope, preserve_intent=preserve_intent)
        if remember and previous is not None:
            self.navigation.history.visit(previous)
        self.navigation.display("authorization")
        self.navigation.clear_rows()
        self.navigation.filter_input.value = ""
        self.navigation.set_errors(False)
        request = self.workspace.authorization_request
        if (
            intent.mode is AuthorizationMode.SELF_RULES
            and request is not None
            and request.intent.mode is AuthorizationMode.SUBJECTS
        ):
            self._transition_notice = (
                request,
                "Rules require one namespace; showing subjects for all namespaces.",
            )
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
            pending.epoch != self._epoch
            or view.context != pending.context
            or (pending.session is not None and view.connection.identity != pending.session)
        ):
            self.invalidate()
            return
        if self.workspace.discovery is None or view.connection.state not in USABLE_CONNECTIONS:
            return
        self._pending = None
        try:
            if pending.command is not None:
                intent = authorization_intent(
                    pending.command, self.workspace.discovery, view.connection.namespace
                )
                self.open(intent, remember=False)
            elif pending.state is not None:
                self.restore(pending.state)
        except AppError as error:
            self.navigation.notice(str(error))

    def restore(self, state: NavigationState) -> None:
        intent = state.authorization
        if intent is None:
            return
        self.invalidate()
        view = self.workspace.store.observation
        if (
            state.context != view.context
            or view.connection.state not in USABLE_CONNECTIONS
            or self.workspace.discovery is None
        ):
            reconnect = (
                state.context != view.context or view.connection.state not in USABLE_CONNECTIONS
            )
            if reconnect:
                self.workspace.prepare_resource(ResourceSelection())
                self.navigation.display("pods")
                self.navigation.connect(
                    state.context, scope=NamespaceChoice(state.namespace), remember=False
                )
            self.navigation.display("authorization")
            self.navigation.clear_rows()
            self._pending = _Pending(
                self._epoch,
                state.context,
                None if reconnect else view.connection.identity,
                state=state,
            )
            self.views.request()
            return
        self.open(
            intent, remember=False, scope=NamespaceChoice(state.namespace), preserve_intent=True
        )
        self.navigation.filter_input.value = state.query
        self.navigation.set_errors(state.errors)
        self.navigation.restore_pending(state)

    def begin_namespace_picker(self) -> None:
        if self.active:
            self._picker_parent = self.navigation.capture()
            self._picker_session = self.workspace.store.observation.connection.identity

    def namespace_selected(self, choice: NamespaceChoice, current: NavigationState | None) -> bool:
        parent = (
            self.navigation.capture()
            if self.active
            else self._picker_parent
            if self._picker_session == self.workspace.store.observation.connection.identity
            and self._picker_parent is not None
            and self._picker_parent.context == self.workspace.store.observation.context
            else None
        )
        if parent is None or parent.authorization is None:
            return False
        if current is not None:
            self.navigation.history.visit(current)
        self.open(parent.authorization, remember=False, scope=choice)
        self.navigation.filter_input.value = parent.query
        self.navigation.restore_pending(parent)
        return True

    def selected(self, key: str | None) -> None:
        row = self._current_row(key)
        if row is None:
            return
        if row.destination is None:
            self.navigation.notice(
                "This row is informational evidence. Use o only for an observed RBAC object."
            )
            return
        self.open(row.destination)

    def open_object(self) -> None:
        row = self._current_row(self.views.tables.authorization.selected_key())
        if row is None:
            return
        ref, discovery = row.object_ref, self.workspace.discovery
        if ref is None or not ref.uid or discovery is None:
            self.navigation.notice(
                "Open requires an observed RBAC object UID; aggregate evidence is not a resource."
            )
            return
        plural = {
            "Role": "roles",
            "ClusterRole": "clusterroles",
            "RoleBinding": "rolebindings",
            "ClusterRoleBinding": "clusterrolebindings",
        }[ref.kind]
        resource = discovery.resolve(plural, group="rbac.authorization.k8s.io")
        self.navigation.open_resource(resource, ref.namespace, uid=ref.uid)

    def _current_row(self, key: str | None) -> AuthorizationRow | None:
        table, request = self.views.tables.authorization, self.workspace.authorization_request
        if (
            not self.active
            or request is None
            or table.request != request
            or request.session != self.navigation.sessions.observation.identity
        ):
            self.navigation.notice("Authorization evidence changed; select a current row.")
            return None
        row = table.row_at(key)
        if row is None:
            self.navigation.notice("Select an authorization evidence row.")
        return row

    def refresh(self) -> None:
        state = self.navigation.capture()
        self.workspace.refresh_authorization()
        self.navigation.clear_rows()
        if state is not None:
            self.navigation.restore_pending(state)
        self.views.request()

    def restore_ready(self, view: ViewObservation) -> bool:
        snapshot = view.authorization
        return (
            snapshot is not None
            and not snapshot.collecting
            and self.views.tables.authorization.request == snapshot.request
        )

    def message(self, view: ViewObservation) -> str:
        request = self.workspace.authorization_request
        if self._transition_notice is not None and request is not None:
            original, message = self._transition_notice
            if (
                original.revision == request.revision
                and original.intent == request.intent
                and original.session.connection_id == request.session.connection_id
            ):
                return message
        return (
            view.message + " · Enter follow evidence · o open observed object · Esc previous view"
        )
