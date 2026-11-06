"""Full-content paging, literal rendering, and copy intent are separate actions."""

import asyncio

import pytest

from kuberich.ui.artifact_viewer import ArtifactViewerScreen
from tests.support.workspace import wait_for
from tests.ui.test_export_review import ExportTestApp, saved_ref, service_for


async def viewer_ready(screen):
    await wait_for(lambda: screen.page is not None and screen.operation_count == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_literal_pages_full_navigation_copy_and_focus(tmp_path, size):
    service = service_for(tmp_path)
    text = (
        "[red] literal \x1b[31m\n"
        + "line with a deliberately wide column\n" * 10000
        + "\nFINAL LINE\n"
    )
    ref = await saved_ref(service, text=text)
    copies = []
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=copies.append)
    app = ExportTestApp(screen)
    async with app.run_test(size=size) as pilot:
        await viewer_ready(screen)
        assert screen.page.total >= 2 and screen.page.index == 0
        assert "[red] literal" in screen.viewer.text and "\x1b" not in screen.viewer.text
        assert not copies and app.focused is screen.viewer
        await pilot.press("ctrl+right")
        await wait_for(lambda: screen.page.index == 1 and screen.operation_count == 0)
        assert "FINAL LINE" in screen.viewer.text
        await pilot.press("ctrl+left")
        await wait_for(lambda: screen.page.index == 0 and screen.operation_count == 0)
        await pilot.press("tab", "shift+tab")
        await pilot.press("ctrl+y")
        await wait_for(lambda: bool(copies))
        assert "FINAL LINE" in copies[0] and "[red] literal" in copies[0]
        await pilot.press("escape")
        assert screen.viewer.text == "" and screen.prepared is None
        assert screen.operation_count == service.operation_count == 0
    await service.close()


@pytest.mark.asyncio
async def test_changed_file_and_clipboard_failure_leave_viewer_usable(tmp_path):
    service = service_for(tmp_path)
    ref = await saved_ref(service)

    def refused(text):
        raise RuntimeError("never display payload")

    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=refused)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await viewer_ready(screen)
        await pilot.click("#artifact-copy")
        await wait_for(lambda: "Clipboard write failed" in str(screen.status.content))
        assert "never display" not in str(screen.status.content)
        assert "literal" in screen.viewer.text
        (ref.directory.path / ref.name).unlink()
        screen.action_copy()
        await wait_for(lambda: screen.operation_count == 0)
        assert "artifact" in str(screen.status.content).lower()
        await pilot.click("#artifact-back")
        await wait_for(lambda: len(app.screen_stack) == 1)
        await screen.stop_owned()
    await service.close()


@pytest.mark.asyncio
async def test_large_copy_refuses_without_truncating_pages(tmp_path):
    service = service_for(tmp_path)
    ref = await saved_ref(service, text=("many safe bytes " * 140 + "\n") * 600)
    copies = []
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=copies.append)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await viewer_ready(screen)
        screen.action_copy()
        await wait_for(lambda: "1 MiB" in str(screen.status.content))
        assert not copies and screen.page.total > 4
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("labelled", [True, False])
async def test_sensitive_view_and_copy_have_distinct_fresh_acknowledgements(tmp_path, labelled):
    from kuberich.ui.export_review import ArtifactConfirmation
    from tests.ui.test_export_review import sensitive_ref

    service = service_for(tmp_path)
    ref = await sensitive_ref(service, labelled=labelled)
    copies = []
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=copies.append)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await viewer_ready(screen)
        assert "ui-secret-value" not in screen.viewer.text and not screen.sensitive and not copies
        await pilot.click("#artifact-sensitive")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        assert "View sensitive" in app.screen.message
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: screen.sensitive and screen.operation_count == 0)
        assert "ui-secret-value" in screen.viewer.text and not copies
        await pilot.press("ctrl+y")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        assert "Copy sensitive" in app.screen.message
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert not copies and screen.sensitive
        await pilot.press("ctrl+y")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: bool(copies))
        assert "ui-secret-value" in copies[0]
        await pilot.click("#artifact-sensitive")
        await wait_for(
            lambda: not screen.sensitive and screen.page is not None and screen.operation_count == 0
        )
        assert "ui-secret-value" not in screen.viewer.text
        await pilot.press("escape")
        assert not screen.sensitive and not screen.viewer.text
    await service.close()


@pytest.mark.asyncio
async def test_sensitive_ack_cancel_close_and_stale_entry_never_disclose(tmp_path):
    from kuberich.ui.export_review import ArtifactConfirmation
    from tests.ui.test_export_review import sensitive_ref

    service = service_for(tmp_path)
    ref = await sensitive_ref(service)
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=lambda _: None)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await viewer_ready(screen)
        await pilot.click("#artifact-sensitive")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        await pilot.press("escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert not screen.sensitive and not screen.viewer.text
        screen.action_copy()
        assert "validated" in str(screen.status.content)
        await pilot.click("#artifact-sensitive")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        (ref.directory.path / ref.name).write_text("changed local entry")
        await pilot.click("#artifact-confirm-yes")
        await wait_for(lambda: screen.operation_count == 0)
        assert not screen.sensitive and not screen.viewer.text
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_close_during_held_read_drains_without_late_content(tmp_path):
    from tests.ui.test_artifact_browser import HeldReadFiles

    files = HeldReadFiles()
    service = service_for(tmp_path, files=files)
    ref = await saved_ref(service)
    files.hold = True
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=lambda _: None)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        assert await asyncio.to_thread(files.started.wait, 5)
        closing = asyncio.create_task(screen.stop_owned())
        await wait_for(lambda: files.cancel_event.is_set())
        closing.cancel()
        files.release.set()
        await closing
        assert files.exited.is_set() and not screen.viewer.text and screen.prepared is None
        assert screen.operation_count == service.operation_count == 0
        await screen.stop_owned()
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_unexpected_page_failure_never_includes_artifact_content(tmp_path, monkeypatch):
    service = service_for(tmp_path)
    ref = await saved_ref(service)

    async def refused(prepared, index):
        raise RuntimeError("raw document")

    monkeypatch.setattr(service, "page", refused)
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=lambda _: None)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: "Artifact read failed" in str(screen.status.content))
        assert "raw document" not in str(screen.status.content) and not screen.viewer.text
        await pilot.press("escape")
    await service.close()


@pytest.mark.asyncio
async def test_app_exit_during_sensitive_confirmation_clears_owned_disclosure(tmp_path):
    from kuberich.ui.export_review import ArtifactConfirmation
    from tests.ui.test_export_review import sensitive_ref

    service = service_for(tmp_path)
    ref = await sensitive_ref(service)
    screen = ArtifactViewerScreen(ref=ref, service=service, copy_to_clipboard=lambda _: None)
    app = ExportTestApp(screen)
    async with app.run_test() as pilot:
        await viewer_ready(screen)
        await pilot.click("#artifact-sensitive")
        await wait_for(
            lambda: isinstance(app.screen, ArtifactConfirmation) and app.screen.is_mounted
        )
        app.exit()
    assert screen.operation_count == service.operation_count == 0
    assert screen.prepared is None and screen.viewer.text == "" and not screen.sensitive
    await service.close()
