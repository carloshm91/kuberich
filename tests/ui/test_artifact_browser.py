"""Local metadata stays inert through selection, filtering and named actions."""

import asyncio
import threading

import pytest

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.export_review import ArtifactConfirmation
from tests.support.workspace import wait_for
from tests.ui.test_export_review import ExportTestApp, saved_ref, service_for


def browser_for(service, *, views=None, reviews=None, copies=None, directory=None):
    return ArtifactBrowserScreen(
        service=service,
        directory=directory or service.default_root,
        open_review=lambda ref, path: reviews.append((ref, path)) if reviews is not None else None,
        open_viewer=lambda ref: views.append(ref) if views is not None else None,
        copy_to_clipboard=lambda text: copies.append(text) if copies is not None else None,
    )


async def browser_ready(screen):
    await wait_for(lambda: screen.listing is not None and screen.operation_count == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_offline_list_filter_refresh_cursor_scroll_and_explicit_view_copy_save(
    tmp_path, size
):
    service = service_for(tmp_path)
    for index in range(16):
        await saved_ref(service, text=f"line {index} [red]\n", name=f"row-{index:02}.txt")
    views, reviews, copies = [], [], []
    screen = browser_for(service, views=views, reviews=reviews, copies=copies)
    app = ExportTestApp(screen)
    async with app.run_test(size=size) as pilot:
        await browser_ready(screen)
        assert screen.table.row_count == 16 and not copies
        screen.table.move_cursor(row=12)
        selected = screen.selected_entry().ref
        screen.table.scroll_to(y=5, animate=False)
        screen.action_refresh()
        await browser_ready(screen)
        assert screen.selected_entry().ref == selected
        screen.filter.value = "row-12"
        await wait_for(lambda: screen.table.row_count == 1)
        assert not copies and not views
        await pilot.press("tab", "shift+tab")
        screen.table.focus()
        await pilot.press("enter")
        assert views == [selected]
        screen.action_save_copy()
        assert reviews == [(selected, service.default_root)]
        screen.action_copy()
        await wait_for(lambda: bool(copies))
        assert "line 12 [red]" in copies[0]
        screen.filter.value = "no matches"
        await wait_for(lambda: screen.table.row_count == 0)
        screen.action_view()
        screen.action_save_copy()
        screen.action_copy()
        screen.action_delete()
        assert "Select" in str(screen.status.content)
        await pilot.press("escape")
        assert screen.operation_count == service.operation_count == 0
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_named_delete_cancel_then_confirm_refreshes_selection(tmp_path, size):
    service = service_for(tmp_path)
    ref = await saved_ref(service)
    screen = browser_for(service)
    app = ExportTestApp(screen)
    async with app.run_test(size=size) as pilot:
        await browser_ready(screen)
        await pilot.click("#artifacts-delete")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        assert ref.name in app.screen.message and str(ref.directory.path) in app.screen.message
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert (ref.directory.path / ref.name).exists()
        await pilot.click("#artifacts-delete")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: screen.table.row_count == 0 and screen.operation_count == 0)
        assert not (ref.directory.path / ref.name).exists()
        await pilot.click("#artifacts-back")
        await wait_for(lambda: len(app.screen_stack) == 1)
    await service.close()


@pytest.mark.asyncio
async def test_missing_default_is_empty_and_directory_change_stays_local(tmp_path):
    service = service_for(tmp_path)
    screen = browser_for(service)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await browser_ready(screen)
        assert "No saved" in str(screen.status.content)
        assert screen.listing.entries == () and screen.entries == ()
        assert screen.table.row_count == 0 and not service.default_root.exists()
        missing = tmp_path / "opaque-selected-location"
        screen.location.value = str(missing)
        await wait_for(lambda: screen.listing is None)
        screen.location.focus()
        await pilot.press("enter")
        await wait_for(
            lambda: (
                screen.operation_count == 0
                and str(screen.status.content) == "The selected export directory is missing."
            )
        )
        assert screen.listing is None and screen.entries == () and screen.table.row_count == 0
        assert str(missing) not in str(screen.status.content) and missing.name not in str(
            screen.status.content
        )
        assert not missing.exists() and not service.default_root.exists()
        assert app.clipboard == ""
        screen.location.value = str(service.default_root)
        screen.location.focus()
        await pilot.press("enter")
        await browser_ready(screen)
        assert screen.listing.entries == () and "No saved" in str(screen.status.content)
        assert not service.default_root.exists()
        await pilot.press("escape")
        assert screen.operation_count == service.operation_count == 0
    await service.close()


class HeldFiles(ArtifactFiles):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.exited = threading.Event()
        self.cancel_event = None

    def scan(self, root, *, cancel):
        self.cancel_event = cancel
        self.started.set()
        self.release.wait(5)
        try:
            return super().scan(root, cancel=cancel)
        finally:
            self.exited.set()


@pytest.mark.asyncio
async def test_close_drains_held_scan_without_late_table_updates(tmp_path):
    files = HeldFiles()
    service = service_for(tmp_path, files=files)
    await saved_ref(service)
    screen = browser_for(service)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        assert await asyncio.to_thread(files.started.wait, 5)
        closing = asyncio.create_task(screen.stop_owned())
        await wait_for(lambda: files.cancel_event.is_set())
        closing.cancel()
        files.release.set()
        await closing
        assert files.exited.is_set() and screen.operation_count == service.operation_count == 0
        assert screen.listing is None and screen.table.row_count == 0
        await screen.stop_owned()
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_copy_failure_is_literal_and_scan_problems_remain_browsable(tmp_path, monkeypatch):
    service = service_for(tmp_path)
    await saved_ref(service)
    screen = browser_for(service)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await browser_ready(screen)

        def failed(text):
            raise RuntimeError("hidden payload")

        screen.copy_to_clipboard = failed
        screen.action_copy()
        await wait_for(lambda: "Clipboard write failed" in str(screen.status.content))
        assert "hidden payload" not in str(screen.status.content)
        path = screen.selected_entry().ref.directory.path / screen.selected_entry().ref.name
        path.unlink()
        screen.action_copy()
        await wait_for(lambda: screen.operation_count == 0)
        assert "artifact" in str(screen.status.content).lower()
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_sensitive_browser_copy_requires_fresh_named_ack(tmp_path):
    from tests.ui.test_export_review import sensitive_ref

    service = service_for(tmp_path)
    await sensitive_ref(service)
    copies = []
    screen = browser_for(service, copies=copies)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await browser_ready(screen)
        assert screen.selected_entry().metadata.sensitive
        screen.action_copy()
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        assert "Copy sensitive" in app.screen.message
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert not copies
        screen.action_copy()
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: bool(copies))
        assert "ui-secret-value" in copies[0]
        await wait_for(lambda: screen.operation_count == 0)
        assert not screen.sensitive
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_legacy_report_unsupported_file_and_literal_metadata_remain_offline(tmp_path):
    from tests.ui.test_export_review import REPORT

    service = service_for(tmp_path)
    service.default_root.mkdir(mode=0o700)
    (service.default_root / "legacy.json").write_bytes(REPORT)
    (service.default_root / "unrecognized.txt").write_text("not an artifact; $(touch ignored)")
    (service.default_root / "legacy.json").chmod(0o600)
    views = []
    screen = browser_for(service, views=views)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await browser_ready(screen)
        assert screen.listing.skipped == 1 and screen.table.row_count == 1
        assert screen.selected_entry().metadata.format == "legacy-report"
        assert screen.selected_entry().metadata.scope.context is None
        screen.filter.value = "legacy-report"
        await wait_for(lambda: screen.table.row_count == 1)
        screen.action_view()
        assert views[0].name == "legacy.json"
        await pilot.press("escape")
    await service.close()


class HeldReadFiles(ArtifactFiles):
    def __init__(self):
        super().__init__()
        self.hold = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.exited = threading.Event()
        self.cancel_event = None

    def read(self, ref, *, prefix=False, cancel):
        if self.hold and not prefix:
            self.cancel_event = cancel
            self.started.set()
            self.release.wait(5)
        try:
            return super().read(ref, prefix=prefix, cancel=cancel)
        finally:
            self.exited.set()


@pytest.mark.asyncio
async def test_selection_change_cancels_held_copy_and_never_copies_previous_entry(tmp_path):
    files = HeldReadFiles()
    service = service_for(tmp_path, files=files)
    await saved_ref(service, name="first.txt")
    await saved_ref(service, name="second.txt")
    copies = []
    screen = browser_for(service, copies=copies)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await browser_ready(screen)
        files.hold = True
        screen.action_copy()
        assert await asyncio.to_thread(files.started.wait, 5)
        screen.table.move_cursor(row=1)
        await wait_for(lambda: files.cancel_event.is_set())
        files.release.set()
        await wait_for(lambda: screen.operation_count == service.operation_count == 0)
        assert screen.selected_entry().ref.name == "second.txt" and not copies
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_scan_unexpected_failure_omits_raw_error_and_refresh_recovers(tmp_path, monkeypatch):
    service = service_for(tmp_path)
    await saved_ref(service)
    original = service.scan

    async def refused(root):
        raise RuntimeError("raw artifact credentials")

    monkeypatch.setattr(service, "scan", refused)
    screen = browser_for(service)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: "operation failed" in str(screen.status.content))
        assert "raw artifact credentials" not in str(screen.status.content)
        monkeypatch.setattr(service, "scan", original)
        await pilot.click("#artifacts-refresh")
        await browser_ready(screen)
        assert screen.table.row_count == 1
        await pilot.press("escape")
    await service.close()
