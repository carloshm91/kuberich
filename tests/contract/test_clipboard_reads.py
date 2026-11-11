"""Owned read helpers, failures, bounds and synthetic X11 native round trips."""

import asyncio
import os
import shutil
import sys
from unittest.mock import AsyncMock

import pytest

from kuberich.domain.clipboard import ClipboardBackend
from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.clipboard import NativeClipboard
from kuberich.services.processes import ProcessRunner
from tests.support.clipboard import owned_x11_display

BODY = b"apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-clipboard}\ndata: {private: owned-private}\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backend", [ClipboardBackend.MACOS, ClipboardBackend.WAYLAND, ClipboardBackend.X11]
)
async def test_explicit_read_uses_selected_environment_directory_guard_and_no_payload_argv(
    tmp_path, backend
):
    runner = ProcessRunner(AccessPolicy(True))
    runner.capture = AsyncMock(return_value=ProcessResult(ProcessStatus.SUCCEEDED, 0, BODY))
    clipboard = NativeClipboard(runner, {"PATH": "/owned/tools", "DISPLAY": ":owned"}, tmp_path)
    calls = []
    assert await clipboard.read(backend, guard=lambda: calls.append("current")) == BODY
    command = runner.capture.call_args.args[0]
    assert command.directory == tmp_path and dict(command.environment)["DISPLAY"] == ":owned"
    assert command.input_data is None and "owned-private" not in repr(command)
    assert runner.capture.call_args.kwargs["timeout"] == 5 and calls == ["current"]
    await clipboard.close()
    await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment", [{"SSH_TTY": "owned"}, {"SSH_CONNECTION": "owned"}, {"TMUX": "owned"}]
)
async def test_remote_or_multiplexer_read_is_explicit_paste_only_without_helper(
    tmp_path, environment
):
    runner = ProcessRunner(AccessPolicy(True))
    runner.capture = AsyncMock()
    clipboard = NativeClipboard(runner, environment, tmp_path)
    with pytest.raises(AppError, match="Paste capture"):
        await clipboard.read(ClipboardBackend.X11)
    runner.capture.assert_not_called()
    await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        ProcessStatus.FAILED,
        ProcessStatus.TIMED_OUT,
        ProcessStatus.OUTPUT_LIMIT,
        ProcessStatus.CANCELLED,
    ],
)
async def test_failed_or_partial_helper_output_is_never_imported(tmp_path, status):
    runner = ProcessRunner(AccessPolicy(True))
    runner.capture = AsyncMock(return_value=ProcessResult(status, 1, BODY, b"private-stderr"))
    clipboard = NativeClipboard(runner, {}, tmp_path)
    with pytest.raises(AppError) as failure:
        await clipboard.read(ClipboardBackend.WAYLAND)
    assert "private" not in str(failure.value)
    await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "invalid", "oversized", "cancel"])
async def test_actual_owned_helper_is_bounded_and_cancellation_reaps_it(tmp_path, mode):
    helper = tmp_path / "wl-paste"
    helper.write_text(
        "#!" + sys.executable + "\nimport os,pathlib,sys,time\n"
        "assert sys.argv[1:]==['--no-newline','--type','text/plain']\n"
        "pathlib.Path('helper-pid').write_text(str(os.getpid()))\n"
        + (
            "time.sleep(30)\n"
            if mode == "cancel"
            else "sys.stdout.buffer.write("
            + repr(
                b"\xff"
                if mode == "invalid"
                else b"x" * (1024 * 1024 + 1)
                if mode == "oversized"
                else BODY
            )
            + ")\n"
        )
    )
    helper.chmod(0o700)
    runner = ProcessRunner(AccessPolicy(True))
    clipboard = NativeClipboard(runner, {"PATH": str(tmp_path)}, tmp_path)
    try:
        if mode == "cancel":
            task = asyncio.create_task(clipboard.read(ClipboardBackend.WAYLAND))
            async with asyncio.timeout(5):
                while not (tmp_path / "helper-pid").exists():
                    await asyncio.sleep(0.001)
            pid = int((tmp_path / "helper-pid").read_text())
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        elif mode == "success":
            assert await clipboard.read(ClipboardBackend.WAYLAND) == BODY
        else:
            with pytest.raises(AppError):
                await clipboard.read(ClipboardBackend.WAYLAND)
        assert runner.active_count == 0
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_owned_x11_reads_same_selection_without_retiring_writer(tmp_path):
    if sys.platform != "linux" or not shutil.which("Xvfb") or not shutil.which("xclip"):
        pytest.skip("Owned Xvfb/xclip round trip requires both local tools")
    async with owned_x11_display() as environment, ProcessRunner(AccessPolicy(True)) as runner:
        environment = {
            key: value
            for key, value in environment.items()
            if key not in {"SSH_CONNECTION", "SSH_TTY", "TMUX"}
        }
        clipboard = NativeClipboard(runner, environment, tmp_path)
        await clipboard.write(BODY, ClipboardBackend.X11)
        owner = clipboard.owner
        assert await clipboard.read(ClipboardBackend.X11) == BODY
        assert clipboard.owner is owner and owner.running
        await clipboard.close()
        assert runner.active_count == 0


@pytest.mark.asyncio
async def test_owned_ephemeral_macos_native_read_roundtrip(tmp_path):
    if not (
        sys.platform == "darwin"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("KUBERICH_NATIVE_CLIPBOARD_TEST") == "1"
    ):
        pytest.skip("Host clipboard is used only on the explicitly owned ephemeral macOS runner")
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, dict(os.environ), tmp_path)
        try:
            await clipboard.write(BODY, ClipboardBackend.MACOS)
            assert await clipboard.read(ClipboardBackend.MACOS) == BODY
            assert runner.active_count == 0
        finally:
            await clipboard.close()
