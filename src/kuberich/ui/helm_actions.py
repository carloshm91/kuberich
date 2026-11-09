"""Capture a release from the current native request before asynchronous inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kuberich.errors import AppError

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp


class HelmActions:
    def __init__(self, app: KubeRichApp) -> None:
        self.app = app

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
            app.push_screen(HelmInspectionScreen(service, inspection))
