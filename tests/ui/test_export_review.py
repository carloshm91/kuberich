"""Actual save review actions against the owned local artifact service."""

import asyncio
import json
import stat
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.domain.exports import (
    DocumentSource,
    ExportCapture,
    ExportScope,
    ResourceSource,
    SupportSource,
)
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.exports import ExportLease, ExportService, ResourceExportReader
from kuberich.ui.export_review import ArtifactConfirmation, ExportReviewScreen
from tests.support.workspace import wait_for

AT = datetime(2026, 11, 5, 12, tzinfo=UTC)
REPORT = json.dumps(
    {
        "schema_version": 1,
        "version": "0.4.0.dev0",
        "python": "3.12",
        "platform": "local",
        "terminal": {"stdin_tty": False, "stdout_tty": False},
        "config_check": "valid",
        "recent_log": {"status": "unavailable"},
    }
).encode()


def service_for(tmp_path, *, files=None):
    return ExportService(
        files=files or ArtifactFiles(),
        default_root=tmp_path / "exports",
        report_payload=lambda: REPORT,
        clock=lambda: AT,
        new_id=uuid4,
    )


def capture_for(text="literal [red] report\n", *, source=None):
    return ExportCapture(
        scope=ExportScope(
            export_at=AT,
            source_at=AT,
            context="fixture",
            header_namespace="header",
            collection_namespace="team",
            namespace_mode="one",
        ),
        source=source or DocumentSource(page="details", text=text),
    )


def lease_for(text="literal [red] report\n", *, source=None, current=lambda: True):
    return ExportLease(
        id=uuid4(), capture=capture_for(text, source=source), current=current, session=None
    )


class ExportTestApp(App):
    def __init__(self, screen):
        super().__init__()
        self.initial_screen = screen

    def compose(self) -> ComposeResult:
        yield Button("Root", id="root")

    def on_mount(self):
        self.push_screen(self.initial_screen)


async def preview_ready(screen):
    try:
        await wait_for(lambda: screen.prepared is not None and screen.operation_count == 0)
    except TimeoutError:
        pytest.fail(f"Preview unavailable: {screen.status.content}")


async def saved_ref(
    service, *, text="literal [red] report\n", name="fixture.txt", lease=None, kind="screen"
):
    lease = lease or lease_for(text)
    review = await service.review_destination(service.default_root, name)
    prepared = await service.prepare(lease, kind, destination=review)
    outcome = await service.publish(prepared, review)
    service.discard(prepared)
    return outcome.ref


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 32), (40, 12)])
async def test_safe_preview_explicit_save_directory_metadata_and_focus(tmp_path, size):
    service = service_for(tmp_path)
    outcomes = []
    screen = ExportReviewScreen(
        subject=(("screen", lease_for()),),
        service=service,
        directory=service.default_root,
        on_finish=outcomes.append,
    )
    app = ExportTestApp(screen)
    async with app.run_test(size=size) as pilot:
        await preview_ready(screen)
        assert not service.default_root.exists()
        assert "literal [red] report" in screen.viewer.text
        assert "fixture" in str(screen.metadata.content) and "2026-11-05" in str(
            screen.metadata.content
        )
        assert app.clipboard == "" and not screen.sensitive
        await pilot.press("tab", "shift+tab")
        assert app.focused is not None
        await pilot.click("#export-save")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert outcomes[0].effect == "published"
        path = outcomes[0].ref.directory.path / outcomes[0].ref.name
        assert "literal [red] report" in path.read_text()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert screen.viewer.text == "" and screen.subject == ()
        assert screen.operation_count == service.operation_count == 0
    await service.close()


@pytest.mark.asyncio
async def test_cancel_and_invalid_destination_leave_review_usable(tmp_path):
    service = service_for(tmp_path)
    outcomes = []
    screen = ExportReviewScreen(
        subject=(("screen", lease_for()),),
        service=service,
        directory=tmp_path / "missing",
        on_finish=outcomes.append,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        await pilot.click("#export-save")
        await wait_for(lambda: screen.operation_count == 0)
        assert (
            "local" in str(screen.status.content).lower()
            or "directory" in str(screen.status.content).lower()
        )
        assert not (tmp_path / "missing").exists()
        screen.location.value = str(service.default_root)
        screen.filename.value = "../invalid.txt"
        await preview_ready(screen)
        await pilot.click("#export-save")
        await wait_for(lambda: screen.operation_count == 0)
        assert not (tmp_path / "invalid.txt").exists()
        await pilot.press("escape")
        assert outcomes == [None] and screen.prepared is None
    await service.close()


@pytest.mark.asyncio
async def test_named_overwrite_has_separate_default_cancel_acknowledgement(tmp_path):
    service = service_for(tmp_path)
    ref = await saved_ref(service, text="old\n", name="kuberich-screen.txt")
    screen = ExportReviewScreen(
        subject=(("screen", lease_for("new\n")),),
        service=service,
        directory=service.default_root,
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        assert ref.name in app.screen.message and str(ref.directory.path) in app.screen.message
        assert app.focused.id == "artifact-confirm-cancel"
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert "old" in (ref.directory.path / ref.name).read_text()
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert "new" in (ref.directory.path / ref.name).read_text()
    await service.close()


@pytest.mark.asyncio
async def test_support_resource_and_logs_are_explicit_opt_ins_and_format_changes(tmp_path):
    service = service_for(tmp_path)
    resource = ApiResource("", "v1", "configmaps", "ConfigMap", True, frozenset({"get"}))
    record = resource_record(
        resource,
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "settings",
                "namespace": "team",
                "uid": "uid",
                "resourceVersion": "1",
            },
            "data": {"token": "hidden"},
        },
        "team",
    )
    support = SupportSource(
        resource=capture_for(source=ResourceSource(resource=resource, record=record))
    )
    choices = (("screen", lease_for()), ("support", lease_for(source=support)))
    screen = ExportReviewScreen(
        subject=choices,
        service=service,
        directory=service.default_root,
        preferred="support",
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        assert not screen.resource_choice.value and screen.resource_choice.display
        assert "Selected resource omitted" in screen.viewer.text
        previous = screen.prepared
        screen.resource_choice.value = True
        await wait_for(
            lambda: (
                screen.prepared is not None
                and screen.prepared is not previous
                and screen.operation_count == 0
            )
        )
        assert "ConfigMap" in screen.viewer.text and "hidden" not in screen.viewer.text
        previous = screen.prepared
        screen.format.value = "screen"
        await wait_for(
            lambda: (
                screen.prepared is not None
                and screen.prepared is not previous
                and screen.operation_count == 0
            )
        )
        assert "literal [red] report" in screen.viewer.text
        assert screen.filename.value.endswith(".txt") and not screen.resource_choice.display
        await pilot.click("#export-cancel")
    await service.close()


@pytest.mark.asyncio
async def test_changed_capture_is_rejected_and_held_preview_drains_on_repeated_close(tmp_path):
    current = [True]
    service = service_for(tmp_path)
    screen = ExportReviewScreen(
        subject=(("screen", lease_for(current=lambda: current[0])),),
        service=service,
        directory=service.default_root,
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        current[0] = False
        await pilot.click("#export-save")
        await wait_for(lambda: screen.operation_count == 0)
        assert "changed" in str(screen.status.content)
        await pilot.press("escape")
        await screen.stop_owned()
        assert screen.operation_count == service.operation_count == 0
    await service.close()


def resource_lease():
    resource = ApiResource("", "v1", "secrets", "Secret", True, frozenset({"get"}))
    record = resource_record(
        resource,
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "selected",
                "namespace": "team",
                "uid": "uid-ui",
                "resourceVersion": "7",
            },
            "stringData": {"value": "ui-secret-value"},
        },
        "team",
    )

    class Client:
        calls = 0
        context = SimpleNamespace(name="fixture")

        async def get_json(self, path):
            self.calls += 1
            assert path == "/api/v1/namespaces/team/secrets/selected"
            return record.manifest

    client = Client()
    session = SessionIdentity("fixture", 1)
    target = ResourceTarget(session, "", "secrets", "team", "selected", "uid-ui")
    reader = ResourceExportReader(client, resource, target, AccessPolicy(True), lambda: True)
    capture = capture_for(source=ResourceSource(resource=resource, record=record))
    capture = replace(
        capture,
        scope=replace(
            capture.scope,
            api_version="v1",
            resource="secrets",
            kind="Secret",
            name="selected",
            uid="uid-ui",
            resource_version="7",
        ),
    )
    return ExportLease(
        id=uuid4(), capture=capture, current=lambda: True, session=session, resource_reader=reader
    ), client


async def sensitive_ref(service, *, labelled=True):
    from kuberich.domain.exports import prepare_capture

    lease, _ = resource_lease()
    prepared = prepare_capture(lease.capture, "resource-yaml", artifact_id=uuid4(), sensitive=True)
    service.default_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = service.default_root / "sensitive.yaml"
    path.write_bytes(
        prepared.payload
        if labelled
        else prepared.payload.replace(b'"sensitive":true', b'"sensitive":false')
    )
    path.chmod(0o600)
    listing = await service.scan(service.default_root)
    return listing.entries[0].ref


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_live_sensitive_save_requires_separate_ack_and_exact_reader_recheck(tmp_path, size):
    service = service_for(tmp_path)
    lease, reader = resource_lease()
    outcomes = []
    screen = ExportReviewScreen(
        subject=(("resource-yaml", lease),),
        service=service,
        directory=service.default_root,
        on_finish=outcomes.append,
    )
    app = ExportTestApp(screen)
    async with app.run_test(size=size) as pilot:
        await preview_ready(screen)
        assert "ui-secret-value" not in screen.viewer.text and reader.calls == 0
        previous = screen.prepared
        screen.sensitive_choice.value = True
        await wait_for(
            lambda: (
                screen.prepared is not None
                and screen.prepared is not previous
                and screen.operation_count == 0
            )
        )
        assert "ui-secret-value" not in screen.viewer.text
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        assert (
            "private local file" in app.screen.message
            and "kuberich-resource-yaml.yaml" in app.screen.message
        )
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert reader.calls == 0 and not list(service.default_root.iterdir())
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert reader.calls == 1
        path = outcomes[0].ref.directory.path / outcomes[0].ref.name
        assert "ui-secret-value" in path.read_text() and stat.S_IMODE(path.stat().st_mode) == 0o600
    await service.close()


@pytest.mark.asyncio
async def test_local_save_copy_default_redacts_and_sensitive_copy_requires_new_ack(tmp_path):
    service = service_for(tmp_path)
    ref = await sensitive_ref(service)
    outcomes = []
    screen = ExportReviewScreen(
        subject=ref, service=service, directory=service.default_root, on_finish=outcomes.append
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        assert "ui-secret-value" not in screen.viewer.text and not screen.sensitive_choice.disabled
        screen.sensitive_choice.value = True
        await wait_for(lambda: screen.operation_count == 0 and screen.sensitive_choice.value)
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert (
            "ui-secret-value" in (outcomes[0].ref.directory.path / outcomes[0].ref.name).read_text()
        )
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["logs", "diagnostics", "resource-yaml"])
async def test_review_saves_complete_supported_format_with_frozen_scope(tmp_path, kind):
    from kuberich.domain.cluster_diagnostics import (
        DiagnosticRequest,
        DiagnosticScope,
        DiagnosticSnapshot,
    )
    from kuberich.domain.exports import DiagnosticsSource, SingleLogsSource
    from kuberich.domain.log_view import LogEntry
    from kuberich.domain.logs import LogLine, LogOptions

    service = service_for(tmp_path)
    if kind == "logs":
        lease = lease_for(
            source=SingleLogsSource(
                options=LogOptions(previous=True),
                head_lines=None,
                entries=(LogEntry(1, LogLine("2026-11-05T12:00:00Z retained message")),),
                dropped_lines=3,
                show_timestamps=False,
            )
        )
    elif kind == "diagnostics":
        snapshot = DiagnosticSnapshot(
            DiagnosticRequest(DiagnosticScope(SessionIdentity("fixture", 1), "team"), 1),
            (),
            (),
            True,
            4,
            AT,
        )
        lease = lease_for(source=DiagnosticsSource(snapshot=snapshot))
    else:
        lease, _ = resource_lease()
    outcomes = []
    screen = ExportReviewScreen(
        subject=((kind, lease),),
        service=service,
        directory=service.default_root,
        on_finish=outcomes.append,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        assert screen.prepared.metadata.format == kind
        assert "ui-secret-value" not in screen.viewer.text
        await pilot.click("#export-save")
        await wait_for(lambda: len(app.screen_stack) == 1)
        ref = outcomes[0].ref
        prepared = await service.read(ref)
        assert prepared.metadata.scope.context == "fixture"
        if kind == "logs":
            assert (
                "retained message" in prepared.payload.decode()
                and "2026-11-05T12:00:00Z" in prepared.payload.decode()
            )
        elif kind == "diagnostics":
            assert (
                '"collecting":true' in prepared.payload.decode()
                and '"native_requests_used":4' in prepared.payload.decode()
            )
        else:
            assert "[REDACTED]" in prepared.payload.decode()
        service.discard(prepared)
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("sensitive", [False, True])
async def test_cancel_during_committed_publish_reports_actual_saved_file(tmp_path, sensitive):
    import threading

    from kuberich.adapters.artifact_files import ArtifactFiles

    class HeldPublish(ArtifactFiles):
        def __init__(self):
            super().__init__()
            self.committed = threading.Event()
            self.release = threading.Event()
            self.cancel_event = None

        def publish(self, prepared, review, *, cancel):
            outcome = super().publish(prepared, review, cancel=cancel)
            self.cancel_event = cancel
            self.committed.set()
            self.release.wait(5)
            return outcome

    files = HeldPublish()
    service = service_for(tmp_path, files=files)
    outcomes = []
    lease, _ = resource_lease() if sensitive else (lease_for(), None)
    screen = ExportReviewScreen(
        subject=(("resource-yaml" if sensitive else "screen", lease),),
        service=service,
        directory=service.default_root,
        on_finish=outcomes.append,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        if sensitive:
            previous = screen.prepared
            screen.sensitive_choice.value = True
            await wait_for(
                lambda: (
                    screen.prepared is not None
                    and screen.prepared is not previous
                    and screen.operation_count == 0
                )
            )
        await pilot.click("#export-save")
        if sensitive:
            await wait_for(
                lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
            )
            await pilot.click("#artifact-confirm-yes")
        assert await asyncio.to_thread(files.committed.wait, 5)
        assert screen.sensitive is sensitive and not screen.prepared.metadata.sensitive
        assert "ui-secret-value" not in screen.viewer.text
        closing = asyncio.create_task(screen.action_cancel())
        await wait_for(lambda: files.cancel_event.is_set())
        closing.cancel()
        files.release.set()
        await closing
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert outcomes[0].effect == "published"
        assert service.last_outcome == outcomes[0]
        assert (outcomes[0].ref.directory.path / outcomes[0].ref.name).is_file()
        assert screen.operation_count == service.operation_count == 0 and not screen.sensitive
    await service.close()


@pytest.mark.asyncio
async def test_destination_replaced_during_overwrite_ack_is_rejected(tmp_path):
    service = service_for(tmp_path)
    ref = await saved_ref(service, text="original\n", name="kuberich-screen.txt")
    screen = ExportReviewScreen(
        subject=(("screen", lease_for("new export\n")),),
        service=service,
        directory=service.default_root,
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        path = ref.directory.path / ref.name
        path.write_text("concurrent local update")
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: screen.operation_count == 0)
        assert "changed" in str(screen.status.content)
        assert path.read_text() == "concurrent local update"
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_unexpected_prepare_error_stays_safe_and_cancel_works(tmp_path, monkeypatch):
    service = service_for(tmp_path)

    async def refused(*args, **kwargs):
        raise RuntimeError("raw manifest content")

    monkeypatch.setattr(service, "prepare", refused)
    screen = ExportReviewScreen(
        subject=(("screen", lease_for()),),
        service=service,
        directory=service.default_root,
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: "Export operation failed" in str(screen.status.content))
        assert "raw manifest content" not in str(screen.status.content)
        assert not screen.viewer.text
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_destination_edits_keep_one_safe_preview_and_recheck_source_guard(
    tmp_path, monkeypatch
):
    service = service_for(tmp_path)
    current = [True]
    calls = []
    original = service.prepare

    async def observed(*args, **kwargs):
        calls.append(kwargs.get("destination"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "prepare", observed)
    screen = ExportReviewScreen(
        subject=(("screen", lease_for(current=lambda: current[0])),),
        service=service,
        directory=service.default_root,
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        prepared = screen.prepared
        screen.location.value = str(tmp_path)
        screen.filename.value = "changed.txt"
        await pilot.pause()
        await wait_for(lambda: screen.operation_count == 0)
        assert len(calls) == 1 and screen.prepared is prepared
        assert "literal [red] report" in screen.viewer.text
        current[0] = False
        screen.filename.value = "stale.txt"
        await pilot.pause()
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.prepared is None and "changed" in str(screen.status.content)
        assert not screen.viewer.text
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_save_failure_and_overwrite_cancel_keep_the_original_preview_binding(
    tmp_path, monkeypatch
):
    from kuberich.errors import AppError

    class FailSelected(ArtifactFiles):
        def publish(self, prepared, review, *, cancel):
            if review.name == "kuberich-screen.txt":
                raise AppError("Controlled publication refusal.")
            return super().publish(prepared, review, cancel=cancel)

    service = service_for(tmp_path, files=FailSelected())
    calls = []
    original = service.prepare

    async def observed(*args, **kwargs):
        result = await original(*args, **kwargs)
        calls.append((result, kwargs.get("destination")))
        return result

    monkeypatch.setattr(service, "prepare", observed)
    outcomes = []
    screen = ExportReviewScreen(
        subject=(("screen", lease_for()),),
        service=service,
        directory=service.default_root,
        on_finish=outcomes.append,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await preview_ready(screen)
        preview = screen.prepared
        await wait_for(
            lambda: (
                screen.ready_to_save
                and not screen.query_one("#export-save", Button).has_class("-active")
            )
        )
        await pilot.click("#export-save")
        await wait_for(
            lambda: (
                "Controlled publication refusal" in str(screen.status.content)
                and screen.operation_count == 0
            )
        )
        assert screen.prepared is preview and len(calls) == 2
        destination = service.default_root / "existing.txt"
        destination.write_text("unchanged")
        screen.filename.value = destination.name
        await pilot.pause()
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.prepared is preview and len(calls) == 2
        await wait_for(
            lambda: (
                screen.ready_to_save
                and not screen.query_one("#export-save", Button).has_class("-active")
            )
        )
        await pilot.click("#export-save")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.prepared is preview and len(calls) == 2
        assert destination.read_text() == "unchanged"
        screen.filename.value = "fresh.txt"
        await pilot.pause()
        await wait_for(lambda: screen.operation_count == 0)
        await wait_for(
            lambda: (
                screen.ready_to_save
                and not screen.query_one("#export-save", Button).has_class("-active")
            )
        )
        await pilot.click("#export-save")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert len(calls) == 3 and calls[-1][1].name == "fresh.txt"
        assert outcomes[0].effect == "published" and outcomes[0].ref.name == "fresh.txt"
        assert "literal [red] report" in (service.default_root / "fresh.txt").read_text()
    await service.close()


@pytest.mark.asyncio
async def test_destination_change_drains_sensitive_recheck_and_requires_fresh_consent(
    tmp_path, monkeypatch
):
    service = service_for(tmp_path)
    lease, client = resource_lease()
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    attempts = []
    original_read = client.get_json

    async def held(path):
        attempts.append(path)
        if len(attempts) == 1:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                raise
        return await original_read(path)

    monkeypatch.setattr(client, "get_json", held)
    preparations = []
    original_prepare = service.prepare

    async def observed(*args, **kwargs):
        preparations.append(kwargs.get("approval"))
        return await original_prepare(*args, **kwargs)

    monkeypatch.setattr(service, "prepare", observed)
    screen = ExportReviewScreen(
        subject=(("resource-yaml", lease),),
        service=service,
        directory=service.default_root,
        on_finish=lambda _: None,
    )
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        try:
            await preview_ready(screen)
            previous = screen.prepared
            screen.sensitive_choice.value = True
            await wait_for(
                lambda: (
                    screen.prepared is not None
                    and screen.prepared is not previous
                    and screen.operation_count == 0
                )
            )
            preview = screen.prepared
            await pilot.click("#export-save")
            await wait_for(
                lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
            )
            await pilot.click("#artifact-confirm-yes")
            await asyncio.wait_for(started.wait(), 5)
            before = len(preparations)
            screen.filename.value = "moved.yaml"
            await asyncio.wait_for(cancelled.wait(), 5)
            assert screen.operation_count > 0 and service.operation_count > 0
            release.set()
            await wait_for(lambda: screen.operation_count == service.operation_count == 0)
            assert len(preparations) == before and screen.prepared is preview
            assert "ui-secret-value" not in screen.viewer.text and not screen.sensitive
            assert not (service.default_root / "kuberich-resource-yaml.yaml").exists()
            await pilot.click("#export-save")
            await wait_for(
                lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
            )
            assert "moved.yaml" in app.screen.message
            await pilot.click("#artifact-confirm-yes")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert len(attempts) == 2
            assert "ui-secret-value" in (service.default_root / "moved.yaml").read_text()
        finally:
            release.set()
    await service.close()
