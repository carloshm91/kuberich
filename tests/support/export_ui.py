"""Actual export review actions and controlled public local-file boundaries."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.domain.exports import ArtifactMetadata, read_artifact
from kuberich.errors import AppError, ExitCode
from kuberich.services.exports import ExportService
from tests.support.workspace import wait_for

if TYPE_CHECKING:
    from kuberich.ui.export_review import ExportReviewScreen


def service_for(directory: Path, *, files: ArtifactFiles | None = None) -> ExportService:
    """Every App test owns its export location and can never touch user state."""
    from kuberich.diagnostics.reports import report_payload

    return ExportService(
        files=ArtifactFiles() if files is None else files,
        default_root=directory / "exports",
        report_payload=lambda: report_payload(config_status="unavailable"),
        clock=lambda: datetime.now(UTC),
        new_id=uuid4,
    )


async def open_review(app, pilot) -> ExportReviewScreen:
    from kuberich.ui.export_review import ExportReviewScreen

    await pilot.press("ctrl+s")
    await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
    review = app.screen
    try:
        await wait_for(lambda: review.ready_to_save)
    except TimeoutError as error:
        raise AssertionError(
            f"Export preview did not become ready: status={review.status.content!s}; "
            f"operations={review.operation_count}; mounted={review.is_mounted}; "
            f"stopped={review.stopped}; prepared={review.prepared is not None}"
        ) from error
    return review


async def choose_destination(review: ExportReviewScreen, destination: Path) -> None:
    from textual.widgets import Button

    review.location.value = str(destination.parent)
    review.filename.value = destination.name
    await wait_for(
        lambda: (
            review.ready_to_save
            and not review.query_one("#export-save", Button).has_class("-active")
        )
    )


async def save_review(app, pilot, review: ExportReviewScreen, destination: Path) -> None:
    await choose_destination(review, destination)
    await pilot.click("#export-save")
    await wait_for(lambda: review.stopped and review not in app.screen_stack)
    assert destination.is_file() and review.operation_count == 0


def read_logs(destination: Path) -> tuple[ArtifactMetadata, dict[str, Any], str]:
    """Validate/re-redact the full artifact before inspecting its public wire facts."""
    prepared = read_artifact(destination.read_bytes(), artifact_id=uuid4())
    assert prepared.metadata.format == "logs"
    _, separator, content = prepared.payload.decode().partition("\n")
    assert separator
    provenance, separator, retained = content.partition("\n")
    assert separator and provenance.startswith("# kuberich-log-source: ")
    value = json.loads(provenance.partition(": ")[2])
    assert isinstance(value, dict)
    return prepared.metadata, value, retained


class FailingPublication(ArtifactFiles):
    """One deliberately refused named entry, reached through a real service worker."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.calls = 0

    def publish(self, prepared, review, *, cancel):
        if review.name == self.name:
            self.calls += 1
            raise AppError("Cannot save the selected local artifact.", ExitCode.LOCAL_IO)
        return super().publish(prepared, review, cancel=cancel)


class HeldPublication(ArtifactFiles):
    """Hold a genuinely committed publication so client-close must drain the worker."""

    def __init__(self) -> None:
        super().__init__()
        self.committed = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.finished = threading.Event()

    def publish(self, prepared, review, *, cancel):
        outcome = super().publish(prepared, review, cancel=cancel)
        self.committed.set()
        try:
            while not self.release.wait(0.01):
                if cancel.is_set():
                    self.cancelled.set()
            return outcome
        finally:
            self.finished.set()
