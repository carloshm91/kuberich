"""Lazy composition freezes source captures and owns local screens/services."""

import asyncio
import subprocess
import sys
from dataclasses import replace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from kuberich.domain.targets import SessionIdentity
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.artifact_viewer import ArtifactViewerScreen
from kuberich.ui.export_actions import ExportActions
from kuberich.ui.export_review import ExportReviewScreen
from tests.support.workspace import wait_for
from tests.ui.test_export_review import AT, lease_for, preview_ready, saved_ref, service_for


class ActionsApp(App):
    def __init__(self, service, *, capture=None):
        super().__init__()
        self.notices = []
        self.captures = []

        def capture_now(at):
            self.captures.append(at)
            return (("screen", lease_for()),)

        self.exports = ExportActions(
            service=service,
            capture=capture or capture_now,
            push_screen=lambda screen: self.push_screen(screen),
            copy_to_clipboard=self.copy_to_clipboard,
            notice=self.notices.append,
            clock=lambda: AT,
        )

    def compose(self) -> ComposeResult:
        yield Button("Root", id="root")


@pytest.mark.asyncio
async def test_capture_before_modal_save_then_local_browser_roundtrip_and_stop(tmp_path):
    service = service_for(tmp_path)
    app = ActionsApp(service)
    async with app.run_test() as pilot:
        app.exports.open_export()
        assert app.captures == [AT]
        await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
        review = app.screen
        await preview_ready(review)
        await pilot.click("#export-save")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert "saved locally" in app.notices[-1].lower()
        assert app.exports.directory == service.default_root
        app.exports.open_browser()
        await wait_for(
            lambda: isinstance(app.screen, ArtifactBrowserScreen) and app.screen.listing is not None
        )
        browser = app.screen
        browser.action_view()
        await wait_for(
            lambda: isinstance(app.screen, ArtifactViewerScreen) and app.screen.page is not None
        )
        await pilot.press("escape")
        browser.action_save_copy()
        await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
        await preview_ready(app.screen)
        assert app.screen.filename.value.startswith("copy-")
        await pilot.press("escape", "escape")
        await app.exports.stop_owned()
        assert app.exports.operation_count == 0
        app.exports.open_browser()
        app.exports.open_export()
        assert len(app.screen_stack) == 1 and app.captures == [AT]


@pytest.mark.asyncio
async def test_empty_source_notice_custom_origin_and_session_closure(tmp_path):
    service = service_for(tmp_path)
    app = ActionsApp(service, capture=lambda at: ())
    async with app.run_test() as pilot:
        app.exports.open_export()
        assert "No supported" in app.notices[-1]
        session = SessionIdentity("fixture", 1)
        lease = replace(lease_for("origin screen\n"), session=session)
        app.exports.open_export(lambda at: (("screen", lease),), preferred="screen")
        await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
        await preview_ready(app.screen)
        assert "origin screen" in app.screen.viewer.text
        await app.exports.close_for_session(session)
        assert app.screen.operation_count == 0 and app.screen.prepared is None
        await pilot.press("escape")
        await app.exports.stop_owned()


def test_fresh_actions_import_keeps_document_and_heavy_screens_unloaded():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import kuberich.ui.export_actions; assert 'textual.document' not in sys.modules; assert 'textual.widgets._text_area' not in sys.modules; assert 'kuberich.ui.export_review' not in sys.modules; assert 'kuberich.ui.artifact_browser' not in sys.modules; assert 'kuberich.ui.artifact_viewer' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_successfully_chosen_browser_directory_is_retained_only_in_session(tmp_path):
    service = service_for(tmp_path)
    chosen = tmp_path / "chosen"
    chosen.mkdir(mode=0o700)
    app = ActionsApp(service)
    async with app.run_test() as pilot:
        app.exports.open_browser()
        await wait_for(
            lambda: isinstance(app.screen, ArtifactBrowserScreen) and app.screen.listing is not None
        )
        browser = app.screen
        browser.location.value = str(chosen)
        await wait_for(lambda: browser.listing is None)
        browser.location.focus()
        await pilot.press("enter")
        await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
        await pilot.press("escape")
        app.exports.open_browser()
        await wait_for(
            lambda: isinstance(app.screen, ArtifactBrowserScreen) and app.screen.listing is not None
        )
        assert app.exports.directory == chosen and app.screen.location.value == str(chosen)
        await pilot.press("escape")
        await app.exports.stop_owned()
    new_service = service_for(tmp_path)
    new_app = ActionsApp(new_service)
    assert new_app.exports.directory == new_service.default_root
    await new_app.exports.stop_owned()


@pytest.mark.asyncio
async def test_connection_close_drains_held_old_generation_and_keeps_local_files_usable(
    tmp_path, monkeypatch
):
    from tests.ui.test_export_review import resource_lease

    service = service_for(tmp_path)
    await saved_ref(service, text="offline artifact remains readable\n")
    lease, client = resource_lease()
    original = client.get_json
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held(path):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            raise
        return await original(path)

    monkeypatch.setattr(client, "get_json", held)
    lease = replace(
        lease,
        capture=replace(
            lease.capture,
            source=replace(
                lease.capture.source,
                record=replace(lease.capture.source.record, metadata_only=True),
            ),
        ),
    )
    app = ActionsApp(service, capture=lambda at: (("resource-yaml", lease),))
    async with app.run_test() as pilot:
        try:
            app.exports.open_browser()
            await wait_for(
                lambda: (
                    isinstance(app.screen, ArtifactBrowserScreen) and app.screen.listing is not None
                )
            )
            browser = app.screen
            browser.action_view()
            await wait_for(
                lambda: isinstance(app.screen, ArtifactViewerScreen) and app.screen.page is not None
            )
            viewer = app.screen
            app.exports.open_export()
            await asyncio.wait_for(started.wait(), 5)
            review = app.screen
            latest = replace(lease.session, generation=lease.session.generation + 1)
            await app.exports.close_for_session(latest)
            assert review.operation_count == 1 and not review.stopped and not cancelled.is_set()
            closing = asyncio.create_task(app.exports.close_for_connection(latest.connection_id))
            await asyncio.wait_for(cancelled.wait(), 5)
            closing.cancel()
            release.set()
            await closing
            assert review.stopped and review.subject == () and review.prepared is None
            assert app.exports.operation_count == 0
            assert not browser.stopped and not viewer.stopped
            assert "offline artifact" in viewer.viewer.text
            await pilot.press("escape")
            await pilot.click("#artifact-copy")
            await wait_for(lambda: "offline artifact" in app.clipboard)
            await pilot.press("escape")
            browser.action_refresh()
            await wait_for(lambda: browser.operation_count == 0)
            assert browser.table.row_count == 1
            await pilot.press("escape")
            await app.exports.stop_owned()
        finally:
            release.set()
