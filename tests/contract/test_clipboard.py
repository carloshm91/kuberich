"""Only owned synthetic data is written/read in native clipboard qualification."""

import asyncio
import os
import shutil
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest

from kuberich.domain.clipboard import ClipboardBackend as B
from kuberich.domain.processes import (
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
)
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.clipboard import NativeClipboard
from kuberich.services.processes import ProcessRunner


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ProcessStatus.SUCCEEDED, ProcessStatus.FAILED])
async def test_mac_program_is_constant_single_line_and_data_uses_stdin(tmp_path, status):
    runner = ProcessRunner(AccessPolicy(True))
    runner.capture = AsyncMock(return_value=ProcessResult(status, 0))
    clipboard = NativeClipboard(runner, {"PATH": "/usr/bin"}, tmp_path)
    data = b"private\x00\x1b]52;c;inert\x07"
    if status is ProcessStatus.FAILED:
        with pytest.raises(AppError, match="Native clipboard write failed"):
            await clipboard.write(data, B.MACOS)
    else:
        await clipboard.write(data, B.MACOS)
    command = runner.capture.call_args.args[0]
    assert command.input_data == data
    assert all("\n" not in argument and "private" not in argument for argument in command.argv)
    await clipboard.close()
    await runner.close()


@pytest.mark.asyncio
async def test_real_process_stdin_is_literal_private_and_closed(tmp_path):
    data = "\x00\x1b]52;c;inert\x07é 中文 $(touch bad)".encode()
    value = capture_command(
        (sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"),
        environment=dict(os.environ),
        directory=tmp_path,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.CLIPBOARD,
        input_data=data,
    )
    async with ProcessRunner(AccessPolicy(True)) as runner:
        result = await runner.capture(value)
        assert result.status is ProcessStatus.SUCCEEDED and result.stdout == data
        assert runner.active_count == 0
    assert not (tmp_path / "bad").exists()


@pytest.mark.asyncio
async def test_owned_x11_roundtrip_replacement_and_owner_cleanup(tmp_path):
    if sys.platform != "linux" or not shutil.which("Xvfb") or not shutil.which("xclip"):
        pytest.skip("Owned Xvfb/xclip qualification runs on Linux with both tools")
    # -displayfd atomically allocates an unused display; never uses the user's DISPLAY.
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-nolisten", "tcp"],
        pass_fds=(write_fd,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(write_fd)
    try:
        display = await asyncio.wait_for(asyncio.to_thread(os.read, read_fd, 32), 10)
        env = {**os.environ, "DISPLAY": ":" + display.decode().strip()}
        async with ProcessRunner(AccessPolicy(True)) as runner:
            clipboard = NativeClipboard(runner, env, tmp_path)
            for data in [
                b"",
                "é 中文\n\x1b]52;c;inert\x07\x00".encode(),
                b"{\\rtf1 plain}",
                b"%!PS-Adobe-3.0 EPSF-3.0",
                b"replacement",
            ]:
                await clipboard.write(data, B.X11)
                child = await asyncio.create_subprocess_exec(
                    "xclip",
                    "-selection",
                    "clipboard",
                    "-o",
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(child.communicate(), 5)
                assert child.returncode == 0, stderr
                assert stdout == data
                assert clipboard.owner is not None and clipboard.owner.running
            await clipboard.close()
            await clipboard.close()
            assert runner.active_count == 0
    finally:
        os.close(read_fd)
        server.terminate()
        await asyncio.to_thread(server.wait, 10)


@pytest.mark.asyncio
async def test_owned_hosted_macos_plaintext_roundtrip(tmp_path):
    if not (
        sys.platform == "darwin"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("KUBERICH_NATIVE_CLIPBOARD_TEST") == "1"
    ):
        pytest.skip("Writes host clipboard only on an explicitly owned ephemeral macOS runner")
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, dict(os.environ), tmp_path)
        for data in [
            b"",
            "é 中文\n\x1b]52;c;inert\x07\x00".encode(),
            b"{\\rtf1 plain}",
            b"%!PS-Adobe-3.0 EPSF-3.0",
            b"replacement",
        ]:
            await clipboard.write(data, B.MACOS)
            child = await asyncio.create_subprocess_exec(
                "/usr/bin/pbpaste", stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await child.communicate()
            assert child.returncode == 0 and stdout == data
        await clipboard.close()
        assert runner.active_count == 0
