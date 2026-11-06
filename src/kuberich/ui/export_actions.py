"""Lazy composition and session ownership for explicit local exports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from kuberich.domain.exports import ArtifactRef, ExportKind, FileOutcome
from kuberich.domain.targets import SessionIdentity
from kuberich.services.exports import CapturePort, ExportService

if TYPE_CHECKING:
    from textual.screen import Screen

    from kuberich.ui.artifact_browser import ArtifactBrowserScreen
    from kuberich.ui.artifact_viewer import ArtifactViewerScreen
    from kuberich.ui.export_review import ExportReviewScreen


class ExportActions:
    """Capture before opening a modal; retain paths only for this app session."""

    def __init__(
        self,
        *,
        service: ExportService,
        capture: CapturePort,
        push_screen: Callable[[Screen[None]], None],
        copy_to_clipboard: Callable[[str], None],
        notice: Callable[[str], None],
        clock: Callable[[], datetime],
    ) -> None:
        self.service = service
        self.capture = capture
        self.push_screen = push_screen
        self.copy_to_clipboard = copy_to_clipboard
        self.notice = notice
        self.clock = clock
        self.directory = service.default_root
        self._screens: list[ExportReviewScreen | ArtifactBrowserScreen | ArtifactViewerScreen] = []
        self._live_reviews: list[ExportReviewScreen] = []
        self._browsers: list[ArtifactBrowserScreen] = []
        self._observed_directories: dict[ArtifactBrowserScreen, Path] = {}
        self._stopped = False

    @property
    def operation_count(self) -> int:
        return self.service.operation_count + sum(
            screen.operation_count for screen in self._screens
        )

    def _retain(self) -> None:
        for browser in self._browsers:
            if browser.listing is not None:
                directory = Path(browser.location.value)
                if directory != self._observed_directories.get(browser):
                    self.directory = directory
                    self._observed_directories[browser] = directory
        self._screens = [
            screen for screen in self._screens if not screen.stopped or screen.operation_count
        ]
        self._live_reviews = [
            screen for screen in self._live_reviews if not screen.stopped or screen.operation_count
        ]
        self._browsers = [
            screen for screen in self._browsers if not screen.stopped or screen.operation_count
        ]
        self._observed_directories = {
            screen: self._observed_directories[screen] for screen in self._browsers
        }

    def open_export(
        self, source: CapturePort | None = None, *, preferred: ExportKind | None = None
    ) -> None:
        if self._stopped:
            return
        choices = (source or self.capture)(self.clock())
        if not choices:
            self.notice("No supported export source is available in this view.")
            return
        from kuberich.ui.export_review import ExportReviewScreen

        self._retain()
        screen = ExportReviewScreen(
            subject=choices,
            service=self.service,
            directory=self.directory,
            preferred=preferred,
            on_finish=self._finished,
        )
        self._screens.append(screen)
        self._live_reviews.append(screen)
        self.push_screen(screen)

    def _finished(self, outcome: FileOutcome | None) -> None:
        if outcome is not None and outcome.ref is not None:
            self.directory = outcome.ref.directory.path
        if outcome is not None:
            if outcome.effect == "published":
                self.notice(outcome.notice or "Export saved locally; no upload was performed.")
            elif outcome.notice:
                self.notice(outcome.notice)

    def _open_review(self, ref: ArtifactRef, directory: Path) -> None:
        from kuberich.ui.export_review import ExportReviewScreen

        self._retain()
        self.directory = directory
        screen = ExportReviewScreen(
            subject=ref, service=self.service, directory=directory, on_finish=self._finished
        )
        self._screens.append(screen)
        self.push_screen(screen)

    def _open_viewer(self, ref: ArtifactRef) -> None:
        from kuberich.ui.artifact_viewer import ArtifactViewerScreen

        self._retain()
        screen = ArtifactViewerScreen(
            ref=ref, service=self.service, copy_to_clipboard=self.copy_to_clipboard
        )
        self._screens.append(screen)
        self.push_screen(screen)

    def open_browser(self) -> None:
        if self._stopped:
            return
        from kuberich.ui.artifact_browser import ArtifactBrowserScreen

        self._retain()
        screen = ArtifactBrowserScreen(
            service=self.service,
            directory=self.directory,
            open_review=self._open_review,
            open_viewer=self._open_viewer,
            copy_to_clipboard=self.copy_to_clipboard,
        )
        self._screens.append(screen)
        self._browsers.append(screen)
        self._observed_directories[screen] = self.directory
        self.push_screen(screen)

    async def close_for_session(self, session: SessionIdentity) -> None:
        for screen in tuple(self._live_reviews):
            if isinstance(screen.subject, tuple) and any(
                lease.session == session for _, lease in screen.subject
            ):
                await screen.stop_owned()
        self._live_reviews = [
            screen for screen in self._live_reviews if not screen.stopped or screen.operation_count
        ]
        await self.service.close_for_session(session)

    async def close_for_connection(self, connection_id: UUID) -> None:
        """Drain every source generation using the client that is about to close."""
        for screen in tuple(self._live_reviews):
            if isinstance(screen.subject, tuple) and any(
                lease.session is not None and lease.session.connection_id == connection_id
                for _, lease in screen.subject
            ):
                await screen.stop_owned()
        self._live_reviews = [
            screen for screen in self._live_reviews if not screen.stopped or screen.operation_count
        ]
        await self.service.close_for_connection(connection_id)

    async def stop_owned(self) -> None:
        self._stopped = True
        for screen in tuple(self._screens):
            await screen.stop_owned()
        self._screens.clear()
        self._live_reviews.clear()
        self._browsers.clear()
        self._observed_directories.clear()
        await self.service.close()
