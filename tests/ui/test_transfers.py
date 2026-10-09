"""Copy UI: explicit review, default Cancel, literal paths and cancellation-owned processes."""

import asyncio
import logging
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Button, Checkbox, Input, Static

from kuberich.config.schema import Settings
from kuberich.domain.transfers import TransferDirection
from kuberich.ui.app import KubeRichApp
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.transfers import TransferScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.transfers import executable
from tests.support.workspace import stable_watch, wait_for, workspace_api


@pytest.mark.asyncio
async def test_changed_paths_during_pending_review_require_another_review(tmp_path, monkeypatch):
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("copy", level=100), catalog=catalog_fixture(tmp_path, url)
        )
        app._process_environment = executable(tmp_path / "tools")
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "d")
            screen = app.screen
            assert isinstance(screen, TransferScreen)
            screen.query_one("#copy-local", Input).value = str(tmp_path / "first")
            screen.query_one("#copy-remote", Input).value = "/tmp/data"
            await pilot.pause()
            entered, release = asyncio.Event(), asyncio.Event()
            prepare = screen.source.prepare
            calls = 0

            async def held_prepare(*args, **kwargs):
                nonlocal calls
                calls += 1
                entered.set()
                await release.wait()
                return await prepare(*args, **kwargs)

            monkeypatch.setattr(screen.source, "prepare", held_prepare)
            screen.prepare()
            await entered.wait()
            operation = screen._operation_task
            screen.prepare()
            screen.confirm()
            assert screen._operation_task is operation and not screen._transferring
            screen.query_one("#copy-local", Input).value = str(tmp_path / "second")
            await pilot.pause()
            release.set()
            await operation
            assert calls == 1 and screen.review is None and screen.source.review is None
            assert "Paths changed" in str(screen.query_one("#copy-feedback", Static).content)
            assert screen.query_one("#copy-confirm", Button).disabled
            assert not (tmp_path / "tools/arguments").exists()
            assert not list(tmp_path.glob(".kuberich-copy-*"))
            await pilot.press("escape")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid-path", "missing-tar"])
async def test_refused_review_or_failed_copy_displays_safe_feedback_and_retains_destination(
    tmp_path, failure
):
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("copy", level=100), catalog=catalog_fixture(tmp_path, url)
        )
        app._process_environment = executable(tmp_path / "tools", failure=failure)
        local = tmp_path / "retained"
        local.write_bytes(b"keep original")
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "d")
            screen = app.screen
            assert isinstance(screen, TransferScreen)
            screen.query_one("#copy-local", Input).value = (
                "relative" if failure == "invalid-path" else str(local)
            )
            screen.query_one("#copy-remote", Input).value = "/tmp/data"
            screen.query_one("#copy-overwrite", Checkbox).value = True
            await pilot.pause()
            screen.prepare()
            await screen._operation_task
            if failure == "invalid-path":
                assert "Review refused" in str(screen.query_one("#copy-feedback", Static).content)
                assert screen.review is None and screen.query_one("#copy-confirm", Button).disabled
            else:
                screen.confirm()
                # A second confirmation cannot start another copy while this one is owned.
                operation = screen._operation_task
                screen.confirm()
                assert screen._operation_task is operation
                await operation
                assert "Download incomplete" in str(
                    screen.query_one("#copy-feedback", Static).content
                )
                assert screen.query_one("#copy-cancel", Button).label == "Back"
            assert local.read_bytes() == b"keep original" and screen.source.review is None
            await pilot.press("escape")
            assert isinstance(app.screen, ContainerScreen)


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", list(TransferDirection))
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_copy_review_never_transfers_on_enter_and_explicit_confirm_retains_views(
    tmp_path, direction, size
):
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("copy", level=100), catalog=catalog_fixture(tmp_path, url)
        )
        app._process_environment = executable(tmp_path / "tools")
        local = tmp_path / "space local.bin"
        remote = tmp_path / "tools/remote/tmp/data.bin"
        (local if direction is TransferDirection.UPLOAD else remote).write_bytes(
            b"owned binary\x00"
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            viewport = app.resources.capture_viewport()
            await pilot.press(
                "colon",
                *("upload" if direction is TransferDirection.UPLOAD else "download"),
                "enter",
            )
            assert isinstance(app.screen, ContainerScreen)
            containers = app.screen
            await pilot.press("u" if direction is TransferDirection.UPLOAD else "d")
            await wait_for(lambda: isinstance(app.screen, TransferScreen))
            screen = app.screen
            screen.query_one("#copy-local", Input).value = str(local)
            screen.query_one("#copy-remote", Input).value = "/tmp/data.bin"
            await pilot.pause()
            screen.query_one("#copy-remote", Input).focus()
            await pilot.press("enter")
            await wait_for(lambda: screen.review is not None)
            assert app.focused is screen.query_one("#copy-cancel", Button)
            assert not (tmp_path / "tools/arguments").exists()
            assert screen.query_one("#copy-confirm", Button).disabled is False
            assert "Destination" in str(screen.query_one("#copy-preview", Static).content)
            assert "Overwrite: refuse" in str(screen.query_one("#copy-preview", Static).content)
            assert screen.query_one("#copy-cancel").region.bottom <= size[1]
            # Changing intent invalidates confirmation, then re-review creates new owned input.
            screen.query_one("#copy-overwrite", Checkbox).value = True
            await pilot.pause()
            assert screen.review is None and screen.query_one("#copy-confirm", Button).disabled
            screen.prepare()
            await wait_for(lambda: screen.review is not None)
            screen.confirm()
            await wait_for(
                lambda: "complete:" in str(screen.query_one("#copy-feedback", Static).content)
            )
            destination = remote if direction is TransferDirection.UPLOAD else local
            assert destination.read_bytes() == b"owned binary\x00"
            await pilot.press("escape")
            await wait_for(lambda: app.screen is containers)
            assert "complete" in str(containers.status.content)
            await pilot.press("escape")
            assert app.resources.capture_viewport() == viewport
        assert screen.source.review is None
        assert not list(tmp_path.glob(".kuberich-copy-*"))


@pytest.mark.asyncio
async def test_readonly_keeps_explicit_download_and_blocks_upload_before_form(tmp_path):
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("copy", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        app._process_environment = executable(tmp_path / "tools")
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "u")
            assert isinstance(app.screen, ContainerScreen) and "Read-only" in str(
                app.screen.status.content
            )
            await pilot.press("d")
            assert isinstance(app.screen, TransferScreen)
            await pilot.press("escape")
            assert isinstance(app.screen, ContainerScreen)
        assert not (tmp_path / "tools/arguments").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", ["escape", "quit", "retry"])
async def test_escape_during_transfer_drains_child_before_source_client_cleanup(
    tmp_path, monkeypatch, closing
):
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("copy", level=100), catalog=catalog_fixture(tmp_path, url)
        )
        app._process_environment = executable(tmp_path / "tools", failure="cancel-download")
        local = tmp_path / "chosen"
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "d")
            screen = app.screen
            assert isinstance(screen, TransferScreen)
            screen.query_one("#copy-local", Input).value = str(local)
            screen.query_one("#copy-remote", Input).value = "/tmp/data"
            await pilot.pause()
            screen.prepare()
            await wait_for(lambda: screen.review is not None)
            review = screen.review
            screen.confirm()
            await wait_for(lambda: (tmp_path / "tools/started").exists())
            old_client = screen.source.client
            original_close = old_client.close

            async def checked_close():
                assert screen._operation_task.done() and screen.source.review is None
                await original_close()

            monkeypatch.setattr(old_client, "close", checked_close)
            if closing == "retry":
                await pilot.press("f4")
            else:
                await pilot.press("ctrl+q" if closing == "quit" else "escape")
                if closing == "escape":
                    await wait_for(lambda: isinstance(app.screen, ContainerScreen))
                    assert "cancelled" in str(app.screen.status.content).lower()
            if closing != "quit":
                await wait_for(lambda: screen._operation_task.done())
            if closing == "retry":
                await wait_for(lambda: app.sessions.client is not old_client)
        assert screen._operation_task.done() and screen.source.review is None
        assert not review.connection.path.exists() and not Path(review.temporary.name).exists()
        assert not local.exists()
