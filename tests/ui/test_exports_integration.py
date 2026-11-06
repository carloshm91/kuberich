"""Real root command, cancellation and local-browser flow with owned HTTP/files."""

import asyncio
import logging
from uuid import uuid4

import pytest
from aiohttp import web
from textual.widgets import Button

from kuberich.config.schema import Settings
from kuberich.domain.exports import read_artifact
from kuberich.ui.app import KubeRichApp
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.artifact_viewer import ArtifactViewerScreen
from kuberich.ui.export_review import ArtifactConfirmation, ExportReviewScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.export_ui import choose_destination, service_for
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


async def click_ready(app, pilot, screen, selector):
    async with asyncio.timeout(5):
        assert await screen.wait_for_refresh()
        button = screen.query_one(selector, Button)
        await wait_for(
            lambda: (
                app.screen is screen
                and screen.is_mounted
                and button.is_mounted
                and button.display
                and button.visible
                and not button.disabled
                and not button.has_class("-active")
                and button.region.area > 0
                and app.get_widget_at(*button.region.offset)[0] is button
            )
        )
        assert await pilot.click(button)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
@pytest.mark.parametrize("hold_feedback", [False, True])
async def test_root_export_overwrite_cancel_save_browser_copy_and_delete(
    tmp_path, size, hold_feedback, monkeypatch
):
    requests = []

    async def ns(request):
        return namespaces("team", "default")

    async def handler(request):
        requests.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        value = pod("owned-api")
        value["spec"]["containers"][0]["env"] = [
            {"name": "PASSWORD", "value": "synthetic-never-share"}
        ]
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    service = service_for(tmp_path)
    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("local-export-flow", level=100),
            catalog=catalog_fixture(tmp_path, url),
            export_service=service,
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await app.run_command(":export")
            await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
            first = app.screen
            await wait_for(lambda: first.prepared is not None and first.operation_count == 0)
            assert not service.default_root.exists()
            await pilot.press("escape")
            await wait_for(lambda: first.stopped and len(app.screen_stack) == 1)
            assert first.prepared is None and service.operation_count == 0
            assert not service.default_root.exists()

            # The real root Escape action must answer a confirmation, preserving
            # the review; it must not dismiss the review or leave its worker held.
            service.default_root.mkdir(mode=0o700)
            destination = service.default_root / "owned.yaml"
            destination.write_text("existing local text\n")
            destination.chmod(0o600)
            await app.run_command(":export")
            await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
            review = app.screen
            await wait_for(lambda: review.prepared is not None and review.operation_count == 0)
            await choose_destination(review, destination)
            await click_ready(app, pilot, review, "#export-save")
            await wait_for(lambda: isinstance(app.screen, ArtifactConfirmation))
            await pilot.press("escape")
            await wait_for(lambda: app.screen is review and review.operation_count == 0)
            assert destination.read_text() == "existing local text\n"
            await click_ready(app, pilot, review, "#export-save")
            await wait_for(lambda: isinstance(app.screen, ArtifactConfirmation))
            await click_ready(app, pilot, app.screen, "#artifact-confirm-yes")
            await wait_for(lambda: review.stopped and len(app.screen_stack) == 1)
            prepared = read_artifact(destination.read_bytes(), artifact_id=uuid4())
            assert prepared.metadata.format == "resource-yaml"
            assert prepared.metadata.scope.context == "kuberich-test-one"
            assert prepared.metadata.scope.collection_namespace == "team"
            assert "synthetic-never-share" not in destination.read_text()
            assert destination.stat().st_mode & 0o777 == 0o600
            assert app.exports.directory == destination.parent

            before = len(requests)
            connected = app.sessions.client
            await app.run_command(":exports")
            await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
            browser = app.screen
            await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
            assert browser.table.row_count == 1
            await click_ready(app, pilot, browser, "#artifacts-view")
            await wait_for(lambda: isinstance(app.screen, ArtifactViewerScreen))
            viewer = app.screen
            await wait_for(lambda: viewer.prepared is not None and viewer.operation_count == 0)
            assert "synthetic-never-share" not in viewer.viewer.text
            await pilot.press("ctrl+y")
            await wait_for(lambda: bool(app.clipboard))
            assert "synthetic-never-share" not in app.clipboard
            assert "kind: Pod" in app.clipboard
            await pilot.press("escape")
            await wait_for(lambda: app.screen is browser and viewer.stopped)
            delete = browser.query_one("#artifacts-delete", Button)
            native_timer, native_message = delete.set_timer, delete.post_message
            feedback_timers, delete_presses = [], []

            def timer(*args, **kwargs):
                result = native_timer(*args, **kwargs)
                if hold_feedback and not feedback_timers:
                    result.pause()
                    feedback_timers.append(result)
                return result

            def message(value):
                if isinstance(value, Button.Pressed):
                    delete_presses.append(value)
                return native_message(value)

            monkeypatch.setattr(delete, "set_timer", timer)
            monkeypatch.setattr(delete, "post_message", message)
            repeated = None
            try:
                await click_ready(app, pilot, browser, "#artifacts-delete")
                await wait_for(lambda: isinstance(app.screen, ArtifactConfirmation))
                first_confirmation = app.screen
                assert len(delete_presses) == 1
                await pilot.press("escape")
                await wait_for(lambda: app.screen is browser and browser.operation_count == 0)
                assert destination.exists()

                async def delete_again():
                    await click_ready(app, pilot, browser, "#artifacts-delete")
                    await wait_for(lambda: isinstance(app.screen, ArtifactConfirmation))

                repeated = asyncio.create_task(delete_again())
                async with asyncio.timeout(5):
                    if hold_feedback:
                        # Drain queued UI work while native feedback stays held.
                        await pilot.pause()
                        assert feedback_timers and delete.has_class("-active")
                        assert not repeated.done() and app.screen is browser
                        assert browser.operation_count == 0 and destination.exists()
                        assert len(delete_presses) == 1
                        feedback_timers[0].resume()
                    await repeated
                assert app.screen is not first_confirmation and len(delete_presses) == 2
                await click_ready(app, pilot, app.screen, "#artifact-confirm-yes")
                await wait_for(lambda: browser.operation_count == 0 and not destination.exists())
            finally:
                for feedback in feedback_timers:
                    feedback.resume()
                if repeated is not None:
                    if not repeated.done():
                        repeated.cancel()
                    await asyncio.gather(repeated, return_exceptions=True)
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1 and browser.stopped)
            assert app.sessions.client is connected and len(requests) == before
        assert app.sessions.client is None and app.exports.operation_count == 0
    assert list(service.default_root.iterdir()) == []
