"""Present the active workspace and own its observation subscription."""

import asyncio
from collections.abc import Callable

from textual.app import App
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input

from kuberich.domain.view_actions import TABLE_ACTIONS, ViewState
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import USABLE_CONNECTIONS, ViewObservation, ViewStatus
from kuberich.security.presentation import safe_text
from kuberich.services.access import AccessPolicy
from kuberich.services.command_catalog import COMMAND_CATALOG
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.workspace import ViewSubscription, WorkspaceService
from kuberich.ui.chrome import Breadcrumbs, WorkspaceHeader, WorkspaceLabel
from kuberich.ui.controllers.base import RenderOutcome, RenderRequest
from kuberich.ui.interactions import Interactions
from kuberich.ui.root_views import RootViews
from kuberich.ui.workspace_navigation import WorkspaceNavigation


class WorkspacePresenter:
    def __init__(
        self,
        host: App[None],
        workspace: WorkspaceService,
        views: RootViews,
        interactions: Interactions,
        navigator: WorkspaceNavigation,
        header: WorkspaceHeader,
        breadcrumbs: Breadcrumbs,
        filter_input: Input,
        status_label: WorkspaceLabel,
        policy: AccessPolicy,
        forwards: ForwardManager,
        full_gvr_titles: Callable[[], bool],
        observation_changed: Callable[[], None],
        failed: Callable[[Exception], None],
        *,
        recover: Callable[[RenderRequest, Exception], None] | None = None,
    ) -> None:
        self.host, self.workspace, self.views = host, workspace, views
        self.interactions, self.navigator = interactions, navigator
        self.header, self.breadcrumbs = header, breadcrumbs
        self.filter_input, self.status_label = filter_input, status_label
        self.policy, self.forwards = policy, forwards
        self.full_gvr_titles, self.observation_changed = full_gvr_titles, observation_changed
        self.failed = failed
        self.recover = recover
        self._selection_notice: tuple[ViewObservation, str] | None = None
        self._observation_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._observation_task = asyncio.create_task(self.observe(self.workspace.subscribe()))

    async def close(self) -> None:
        # WorkspaceService closes its subscription before presentation is drained.
        if self._observation_task is not None:
            await asyncio.gather(self._observation_task, return_exceptions=True)

    def update_trail(self) -> None:
        if not self.host.screen_stack:
            return
        trail = self.navigator.trail()
        self.breadcrumbs.trail, self.breadcrumbs.destination = trail.tokens, trail.destination
        self.breadcrumbs.show_trail()

    def status(self, message: str) -> None:
        prefix = "Read-only · " if self.policy.read_only else ""
        insecure = (
            "Insecure transport · " if self.workspace.store.observation.connection.insecure else ""
        )
        forwards = (
            f" · Forwards: {self.forwards.active_count}" if self.forwards.active_count else ""
        )
        try:
            self.status_label.update_text(safe_text(prefix + insecure + message + forwards))
        except Exception as error:
            if self.recover is None:
                raise
            self.recover(self.capture(), error)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        view = ViewState(
            request.route.display_key,
            generic=request.route.kind is ViewKind.CUSTOM,
            modal=isinstance(self.host.screen, ModalScreen),
            typing=isinstance(self.host.focused, Input),
        )
        names = TABLE_ACTIONS | frozenset(
            spec.ui_action for spec in COMMAND_CATALOG.specs if spec.ui_action is not None
        )
        return frozenset(name for name in names if COMMAND_CATALOG.available(name, view))

    def capture(self) -> RenderRequest:
        view, query = self.workspace.store.observation, self.filter_input.value
        route, interaction_revision = self.views.route, self.interactions.revision

        def current() -> bool:
            return (
                self.host.is_running
                and not isinstance(self.host.screen, ModalScreen)
                and view is self.workspace.store.observation
                and query == self.filter_input.value
                and route == self.views.route
                and interaction_revision == self.interactions.revision
            )

        return RenderRequest(view, query, current, route)

    def refresh_ages(self) -> None:
        if not self.host.is_running or isinstance(self.host.screen, ModalScreen):
            return
        self.views.tables.pods.refresh_ages()
        self.views.tables.namespaces.refresh_ages()
        self.views.tables.standard.refresh_ages()
        self.views.tables.custom.refresh_ages()
        self.views.request()

    async def observe(self, subscription: ViewSubscription) -> None:
        header_identity: tuple[str, str, str, str, str] | None = None
        try:
            async for observation in subscription:
                if observation.context is None:
                    continue
                if (
                    self.host.is_running
                    and observation.revision == self.workspace.store.observation.revision
                ):
                    self.views.request()
                    # Target/process invalidation remains outside the UI boundary.
                    self.observation_changed()
                    try:
                        identity = self.header.chrome.identity()
                        if identity != header_identity:
                            for header in self.host.query(WorkspaceHeader):
                                header.update_identity()
                            header_identity = identity
                    except Exception as error:
                        if self.recover is None:
                            raise
                        self.recover(self.capture(), error)
                    for screen in tuple(self.host.screen_stack):
                        if not isinstance(screen, ModalScreen):
                            continue
                        from kuberich.ui.configuration_data import ConfigurationScreen
                        from kuberich.ui.containers import ContainerScreen
                        from kuberich.ui.inspection import InspectionScreen
                        from kuberich.ui.logs import LogScreen
                        from kuberich.ui.terminal import ShellScreen

                        if isinstance(
                            screen,
                            (
                                InspectionScreen,
                                LogScreen,
                                ContainerScreen,
                                ShellScreen,
                                ConfigurationScreen,
                            ),
                        ):
                            screen.validate_target()
                            if (
                                isinstance(screen, ContainerScreen)
                                and observation.snapshot is not None
                            ):
                                record = next(
                                    (
                                        item
                                        for item in observation.snapshot.items
                                        if item.uid == screen.stream.target.uid
                                    ),
                                    None,
                                )
                                if record is not None:
                                    screen.observe_record(record)
                            if (
                                (
                                    isinstance(screen, (ContainerScreen, InspectionScreen))
                                    and screen.invalidated
                                )
                                or (isinstance(screen, LogScreen) and screen.stale)
                                or (isinstance(screen, ShellScreen) and screen.stop_requested)
                            ):
                                await screen.stop_owned()
        except Exception as error:
            self.failed(error)
        finally:
            subscription.close()

    def publish(self, request: RenderRequest, outcome: RenderOutcome) -> None:
        view, query, kind = request.observation, request.query, request.route.display_key
        count, filtered = outcome.count, outcome.filtered
        if view.revision != self.interactions.scope_revision:
            self.interactions.selection.marked = frozenset()
            self.interactions.selection.anchor = None
            self.interactions.scope_revision = view.revision
        self.interactions.selection.prune(
            tuple(
                row.key.value for row in self.views.table.ordered_rows if row.key.value is not None
            )
        )
        self.interactions.paint_selection()
        self.show(view)
        if (
            query
            or self.interactions.errors
            or (kind == "namespaces" and self.interactions.favorites)
        ):
            detail = "Local kubeconfig catalogue" if kind == "contexts" else view.message
            self.view_status(
                view, outcome.problem or f"Filter active · {filtered}/{count} {kind} · {detail}"
            )
            if (
                count
                and not filtered
                and (view.status is ViewStatus.LIVE or kind == "contexts")
                and outcome.problem is None
            ):
                self.host.query_one("#empty-title", WorkspaceLabel).update_text(
                    f"No retained {kind} match this filter"
                    if kind != "contexts"
                    and view.snapshot is not None
                    and not view.snapshot.collection.complete
                    else f"No {kind} match this filter"
                )
                self.host.query_one("#empty-description", WorkspaceLabel).update_text(
                    "The collection is incomplete. :server label/field or :ns can narrow the server results."
                    if kind != "contexts"
                    and view.snapshot is not None
                    and not view.snapshot.collection.complete
                    else "Escape in the table clears the filter."
                )
        self.navigator.after_render(view)
        self.update_trail()

    def show(self, view: ViewObservation) -> None:
        observation = view.connection
        self.header.update_identity()
        if self.views.route.display_key == "contexts":
            self.host.query_one("#resource-view", Vertical).border_title = safe_text(
                f"contexts[{self.views.tables.contexts.row_count}]"
            )
            self.host.query_one("#empty-state").set_class(
                bool(self.views.tables.contexts.row_count), "populated"
            )
            self.views.tables.contexts.set_class(
                bool(self.views.tables.contexts.row_count), "populated"
            )
            self.host.query_one("#empty-title", WorkspaceLabel).update_text(
                "No contexts match this filter"
            )
            self.host.query_one("#empty-description", WorkspaceLabel).update_text(
                "Escape in the table clears the filter."
            )
            self.show_sort()
            self.view_status(view, "Local kubeconfig contexts · Enter connect · Esc previous view")
            return
        if (
            view.status is ViewStatus.DISCONNECTED
            and view.context is None
            and view.scope is None
            and view.snapshot is None
        ):
            self.host.query_one(
                "#resource-view", Vertical
            ).border_title = "Resources · no connection"
            self.host.query_one("#empty-title", WorkspaceLabel).update_text("No cluster connection")
            self.host.query_one("#empty-description", WorkspaceLabel).update_text(
                "Live resources are not connected in this preview."
            )
            self.host.query_one("#empty-state").set_class(False, "populated")
            self.views.table.set_class(False, "populated")
            self.show_sort()
            self.view_status(view, view.message)
            return
        usable = observation.state in USABLE_CONNECTIONS
        incomplete = view.snapshot is not None and not view.snapshot.collection.complete
        self.host.query_one("#empty-title", WorkspaceLabel).update_text(
            "Stale resource data"
            if view.snapshot is not None and view.problem is not None
            else "Resource data unavailable"
            if usable and view.status is ViewStatus.FAILED
            else f"No retained {self.views.route.display_key} in this incomplete collection"
            if incomplete and view.snapshot is not None and not view.snapshot.items
            else f"No {self.views.route.display_key} in this scope"
            if view.snapshot is not None and not view.snapshot.items
            else f"{self.views.route.display_key.title()} ready"
            if view.status is ViewStatus.LIVE
            else "Loading resources"
            if usable
            else "Connection unavailable"
        )
        self.host.query_one("#empty-description", WorkspaceLabel).update_text(
            "Collection incomplete; retained rows are only a subset. :server label/field or :ns to narrow."
            if incomplete
            else f"No {self.views.route.display_key} were returned. :ns namespaces · :ctx contexts."
            if view.status is ViewStatus.LIVE
            else "Keeping the last snapshot while reconnecting. Press i for details."
            if view.status is ViewStatus.STALE
            else "Press i for status · r retry · :ctx choose context."
        )
        scope = (
            "all"
            if self.views.route.display_key == "namespaces"
            else "cluster"
            if view.scope is not None and not view.scope.resource.namespaced
            else observation.namespace or "all"
        )
        self.host.query_one("#resource-view", Vertical).border_title = safe_text(
            ("INCOMPLETE · " if incomplete else "")
            + f"{self.views.route.display_key}({scope})[{self.views.table.row_count}]"
            + (
                f" · {view.scope.resource.api_version}"
                if (self.views.tables.custom.display or self.full_gvr_titles())
                and view.scope is not None
                else ""
            )
            + f" · {view.status.name.lower()}"
        )
        self.host.query_one("#empty-state").set_class(bool(self.views.table.row_count), "populated")
        self.views.table.set_class(bool(self.views.table.row_count), "populated")
        self.show_sort()
        self.view_status(view, view.message)

    def view_status(self, view: ViewObservation, message: str) -> None:
        if self._selection_notice is not None:
            notice_view, notice = self._selection_notice
            if notice_view is view:
                message = notice
            else:
                self._selection_notice = None
        self.status(message)

    def notice(self, message: str) -> None:
        """Show a message that survives re-renders of the current view."""
        self._selection_notice = self.workspace.store.observation, message
        self.status(message)

    def show_sort(self) -> None:
        self.host.query_one("#resource-view", Vertical).border_subtitle = (
            self.views.tables.pods.sort_summary
            if self.views.route.display_key == "pods"
            else "Name ↑ · Enter connect · * selected session"
            if self.views.route.display_key == "contexts"
            else self.views.tables.namespaces.sort_summary + " · Enter use namespace · 0 all"
            if self.views.route.display_key == "namespaces"
            else self.views.tables.custom.sort_summary
            if self.views.tables.custom.display
            else self.views.tables.standard.sort_summary
        )
