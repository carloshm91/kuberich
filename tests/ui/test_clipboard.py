"""Application clipboard wiring through an inert driver and an owned adapter boundary."""

import asyncio
import base64
import logging
import os
from pathlib import Path

import pytest
from textual.drivers.headless_driver import HeadlessDriver

from kuberich.config.schema import Settings
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.clipboard import NativeClipboard
from kuberich.services.processes import ProcessRunner
from kuberich.ui.app import KubeRichApp
from tests.support.workspace import wait_for


class RecordingDriver(HeadlessDriver):
    """Emulate native rendering without writing a real TTY or host clipboard."""

    @property
    def is_headless(self):
        return False


class ClipboardApp(KubeRichApp):
    def __init__(self):
        self.clipboard_requests = []
        self.native_clipboard = NativeClipboard(
            ProcessRunner(AccessPolicy(False)), dict(os.environ), Path.cwd()
        )
        super().__init__(
            Settings(),
            logging.Logger("clipboard-boundary", level=100),
            clipboard=self.native_clipboard,
        )

    def get_driver_class(self):
        requests = self.clipboard_requests

        class BoundDriver(RecordingDriver):
            def write(self, data):
                if "]52;" in data:
                    requests.append(data)

        return BoundDriver


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preference,oversize", [("auto", False), ("auto", True), ("native", False)]
)
async def test_native_failure_falls_back_only_when_allowed_and_bounded(
    monkeypatch, preference, oversize
):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", preference)
    monkeypatch.setenv("DISPLAY", ":owned-adapter-boundary")
    for variable in ("WAYLAND_DISPLAY", "SSH_TTY", "SSH_CONNECTION", "TMUX"):
        monkeypatch.delenv(variable, raising=False)
    app = ClipboardApp()
    notices = []
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append(str(message)))

    async def failed(data, backend, **kwargs):
        raise AppError("Native clipboard is unavailable in this owned fixture.")

    monkeypatch.setattr(app.native_clipboard, "write", failed)
    async with app.run_test(headless=False):
        text = "x" * 65537 if oversize else "inert\x1b]52;c;literal\x07中文"
        app.copy_to_clipboard(text)
        await wait_for(lambda: bool(app.clipboard_requests) or bool(notices))
        assert app.clipboard == text
        if preference == "auto" and not oversize:
            assert app.clipboard_requests == [
                "\x1b]52;c;" + base64.b64encode(text.encode()).decode() + "\x07"
            ]
            assert not notices
        else:
            assert not app.clipboard_requests and notices
            assert text not in notices[-1]


@pytest.mark.asyncio
async def test_rapid_native_copies_coalesce_and_old_failures_do_not_overwrite_new_intent(
    monkeypatch,
):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", "auto")
    monkeypatch.setenv("DISPLAY", ":owned-adapter-boundary")
    for variable in ("WAYLAND_DISPLAY", "SSH_TTY", "SSH_CONNECTION", "TMUX"):
        monkeypatch.delenv(variable, raising=False)
    app = ClipboardApp()
    entered, release = asyncio.Event(), asyncio.Event()
    written = []

    async def writer(data, backend, **kwargs):
        written.append(data)
        if data == b"first":
            entered.set()
            await release.wait()
            raise AppError("Superseded copy failed")

    monkeypatch.setattr(app.native_clipboard, "write", writer)
    async with app.run_test(headless=False):
        app.copy_to_clipboard("first")
        await entered.wait()
        app.copy_to_clipboard("middle")
        app.copy_to_clipboard("latest")
        release.set()
        await wait_for(lambda: written == [b"first", b"latest"])
        assert written == [b"first", b"latest"] and app.clipboard == "latest"
        assert not app.clipboard_requests
        app.copy_to_clipboard("next")
        await wait_for(lambda: written[-1] == b"next")
        assert written[-1] == b"next"


@pytest.mark.asyncio
async def test_explicit_terminal_tmux_writes_are_inert_and_headless_has_no_host_effect(monkeypatch):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", "osc52")
    monkeypatch.setenv("TMUX", "owned-test-transport")
    app = ClipboardApp()
    async with app.run_test(headless=False):
        app.copy_to_clipboard("name")
        assert app.clipboard_requests == ["\x1bPtmux;\x1b\x1b]52;c;bmFtZQ==\x07\x1b\\"]
        with pytest.raises(AppError, match="64 KiB"):
            app.copy_to_clipboard("x" * 65537)
    app = ClipboardApp()
    app.copy_to_clipboard("before mount stays in memory")
    assert not app.clipboard_requests
    async with app.run_test():
        app.copy_to_clipboard("owned memory")
        assert app.clipboard == "owned memory" and not app.clipboard_requests
        with pytest.raises(AppError, match="1024 KiB"):
            app.copy_to_clipboard("x" * (1024 * 1024 + 1))
        assert not app.clipboard_requests and app.processes.active_count == 0


@pytest.mark.asyncio
async def test_app_exit_cancels_and_drains_active_native_write(monkeypatch):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", "native")
    monkeypatch.setenv("DISPLAY", ":owned-adapter-boundary")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    app = ClipboardApp()
    entered, finished = asyncio.Event(), asyncio.Event()
    written = []
    owners = []

    async def writer(data, backend, **kwargs):
        owners.append(asyncio.current_task())
        written.append(data)
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finished.set()

    monkeypatch.setattr(app.native_clipboard, "write", writer)
    async with app.run_test(headless=False):
        app.copy_to_clipboard("owned in-flight copy")
        await entered.wait()
        app.copy_to_clipboard("superseded on exit")
    assert finished.is_set() and written == [b"owned in-flight copy"]
    assert owners and all(task is not None and task.done() for task in owners)
    assert app.processes.active_count == 0


@pytest.mark.asyncio
async def test_late_native_failure_uses_bounded_fallback_and_is_silent_after_exit(monkeypatch):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", "auto")
    monkeypatch.setenv("DISPLAY", ":owned-adapter-boundary")
    for variable in ("WAYLAND_DISPLAY", "SSH_TTY", "SSH_CONNECTION", "TMUX"):
        monkeypatch.delenv(variable, raising=False)
    app = ClipboardApp()
    callbacks = []

    async def writer(data, backend, *, failed):
        callbacks.append(failed)

    monkeypatch.setattr(app.native_clipboard, "write", writer)
    async with app.run_test(headless=False):
        app.copy_to_clipboard("owned late copy")
        await wait_for(lambda: len(callbacks) == 1)
        callbacks[-1](AppError("Owned selection process exited later."))
        assert app.clipboard_requests == [
            "\x1b]52;c;" + base64.b64encode(b"owned late copy").decode() + "\x07"
        ]
    previous = list(app.clipboard_requests)
    callbacks[-1](AppError("Late completion after exit"))
    assert app.clipboard_requests == previous
