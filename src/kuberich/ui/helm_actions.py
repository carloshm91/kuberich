"""Capture a release from the current native request before asynchronous inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.worker import Worker

from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.views import USABLE_CONNECTIONS
from kuberich.errors import AppError

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp


class HelmActions:
    def __init__(self, app: KubeRichApp) -> None:
        self.app = app
        self.pending_catalog_context: str | None = None

    def catalog(self) -> None:
        self.pending_catalog_context = None
        _worker: Worker[None] = self.app.run_worker(
            self._catalog, group="helm-catalog", exclusive=True
        )

    async def _catalog(self) -> None:
        try:
            await self._open_catalog()
        except AppError as error:
            self.app.navigator.notice(str(error))

    async def _open_catalog(self) -> None:
        from kuberich.ui.helm_catalog import HelmCatalogScreen

        app = self.app
        view = app.workspace.store.observation
        if view.connection.state not in USABLE_CONNECTIONS or view.connection.identity is None:
            context = view.context or app.sessions.request.context or app.sessions.catalog.current
            if context is None:
                app.navigator.notice("Choose a context before choosing a chart release scope.")
                return
            self.pending_catalog_context = context
            app.helm_navigation.open(None, collect=False)
            return
        if not app.helm_navigation.active or app.workspace.helm_service is None:
            transition = app.helm_navigation.open(
                NamespaceChoice(view.connection.namespace), collect=False
            )
            if transition is not None:
                await transition
        request, service = app.workspace.helm_request, app.workspace.helm_service
        if request is None or service is None or not service.current(request):
            app.navigator.notice("Helm scope changed; open the chart catalog again.")
            return
        app.push_screen(HelmCatalogScreen(service=service, request=request, runner=app.processes))

    def resolve_pending(self) -> None:
        context = self.pending_catalog_context
        if context is None:
            return
        view = self.app.workspace.store.observation
        if not self.app.helm_navigation.active or view.context != context:
            self.pending_catalog_context = None
        elif self.app.workspace.helm_service is not None:
            self.catalog()

    async def inspect(self) -> None:
        from kuberich.ui.helm_inspection import HelmInspectionScreen

        app = self.app
        request, service = app.workspace.helm_request, app.workspace.helm_service
        snapshot = app.workspace.store.observation.helm
        table = app.helm_table
        release = table.selected_release()
        if (
            not app.helm_navigation.active
            or request is None
            or service is None
            or request != table.request
            or release is None
            or snapshot is None
            or snapshot.request != request
            or snapshot.collecting
            or snapshot.problem is not None
            or snapshot.listing is None
            or release not in snapshot.listing.releases
        ):
            app.navigator.notice(
                "Select a current Helm release after collection completes; F4 refreshes stale rows."
            )
            return
        try:
            inspection = await service.inspect(request, release)
        except AppError as error:
            if app.helm_navigation.active and app.workspace.helm_request == request:
                app.navigator.notice(str(error))
            return
        if (
            app.helm_navigation.active
            and app.workspace.helm_request == request
            and service.current(request)
        ):
            app.push_screen(HelmInspectionScreen(service, inspection, runner=app.processes))
