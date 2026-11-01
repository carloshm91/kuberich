"""Application clipboard wiring through an inert driver and an owned adapter boundary."""

import asyncio
import base64
import logging
from types import SimpleNamespace

import pytest
from textual.drivers.headless_driver import HeadlessDriver

from kuberich.config.schema import Settings
from kuberich.domain.clipboard import ClipboardBackend
from kuberich.errors import AppError
from kuberich.services.clipboard import NativeClipboard
from kuberich.ui.app import KubeRichApp


class RecordingDriver(HeadlessDriver):
    """Emulate native rendering without writing a real TTY or host clipboard."""

    @property
    def is_headless(self):
        return False

    def write(self, data):
        if "]52;" in data:
            self._app.clipboard_requests.append(data)


class ClipboardApp(KubeRichApp):
    def __init__(self):
        self.clipboard_requests = []
        super().__init__(Settings(), logging.Logger("clipboard-boundary", level=100))

    def get_driver_class(self):
        return RecordingDriver


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preference,oversize", [("auto", False), ("auto", True), ("native", False)]
)
@pytest.mark.parametrize("session", ["x11", "wayland", "macos"])
async def test_native_failure_falls_back_only_when_allowed_and_bounded(
    monkeypatch, preference, oversize, session
):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", preference)
    monkeypatch.setenv("DISPLAY", ":owned-adapter-boundary")
    for variable in ("WAYLAND_DISPLAY", "SSH_TTY", "SSH_CONNECTION", "TMUX"):
        monkeypatch.delenv(variable, raising=False)
    if session == "wayland":
        monkeypatch.setenv("WAYLAND_DISPLAY", "owned-wayland-test")
    # Scope the platform to this adapter fixture, without changing Python's
    # platform for Textual, asyncio or the other host-native controls.
    monkeypatch.setattr(
        "kuberich.ui.app.sys",
        SimpleNamespace(platform="darwin" if session == "macos" else "linux"),
    )
    app = ClipboardApp()
    notices = []
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append(str(message)))

    async def failed(self, data, backend, **kwargs):
        assert (
            backend
            is {
                "x11": ClipboardBackend.X11,
                "wayland": ClipboardBackend.WAYLAND,
                "macos": ClipboardBackend.MACOS,
            }[session]
        )
        raise AppError("Native clipboard is unavailable in this owned fixture.")

    monkeypatch.setattr(NativeClipboard, "write", failed)
    async with app.run_test(headless=False):
        text = "x" * 65537 if oversize else "inert\x1b]52;c;literal\x07中文"
        app.copy_to_clipboard(text)
        await app._clipboard_task
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

    monkeypatch.setattr(app._native_clipboard, "write", writer)
    async with app.run_test(headless=False):
        app.copy_to_clipboard("first")
        await entered.wait()
        app.copy_to_clipboard("middle")
        app.copy_to_clipboard("latest")
        release.set()
        await app._clipboard_task
        assert written == [b"first", b"latest"] and app.clipboard == "latest"
        assert not app.clipboard_requests
        app.copy_to_clipboard("next")
        await app._clipboard_task
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
        assert app._clipboard_task is None


@pytest.mark.asyncio
async def test_app_exit_cancels_and_drains_active_native_write(monkeypatch):
    monkeypatch.setenv("KUBERICH_CLIPBOARD", "native")
    monkeypatch.setenv("DISPLAY", ":owned-adapter-boundary")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    app = ClipboardApp()
    entered, finished = asyncio.Event(), asyncio.Event()

    async def writer(data, backend, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finished.set()

    monkeypatch.setattr(app._native_clipboard, "write", writer)
    async with app.run_test(headless=False):
        app.copy_to_clipboard("owned in-flight copy")
        await entered.wait()
        app.copy_to_clipboard("superseded on exit")
    assert finished.is_set() and app._clipboard_task.done()
    assert app._clipboard_pending is None and app.processes.active_count == 0


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

    monkeypatch.setattr(app._native_clipboard, "write", writer)
    async with app.run_test(headless=False):
        app.copy_to_clipboard("owned late copy")
        await app._clipboard_task
        callbacks[-1](AppError("Owned selection process exited later."))
        assert app.clipboard_requests == [
            "\x1b]52;c;" + base64.b64encode(b"owned late copy").decode() + "\x07"
        ]
    previous = list(app.clipboard_requests)
    callbacks[-1](AppError("Late completion after exit"))
    assert app.clipboard_requests == previous
