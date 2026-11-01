"""Only owned synthetic data is written/read in native clipboard qualification."""

import asyncio
import os
import shutil
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
from tests.support.clipboard import owned_x11_display, read_x11_selection


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
    async with owned_x11_display() as env, ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, env, tmp_path)
        for phase, data in enumerate(
            [
                b"",
                "é 中文\n\x1b]52;c;inert\x07\x00".encode(),
                b"{\\rtf1 plain}",
                b"%!PS-Adobe-3.0 EPSF-3.0",
                b"replacement",
            ]
        ):
            await clipboard.write(data, B.X11)
            stdout = await read_x11_selection(
                runner, env, tmp_path, data, receipt=tmp_path / f"selection-{phase}.json"
            )
            assert stdout == data
            assert clipboard.owner is not None and clipboard.owner.running
        await clipboard.close()
        await clipboard.close()
        assert runner.active_count == 0


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


@pytest.mark.asyncio
async def test_owned_x11_startup_denial_is_visible_and_does_not_leak_input(tmp_path):
    if sys.platform != "linux" or not shutil.which("xclip"):
        pytest.skip("X11 helper failure qualification runs on Linux with xclip")
    # Invalid local display syntax fails before any network/display connection.
    environment = {**os.environ, "DISPLAY": "owned-invalid-display-without-colon"}
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, environment, tmp_path)
        with pytest.raises(AppError, match="Native clipboard write failed") as failure:
            await clipboard.write(b"synthetic private payload", B.X11)
        assert "synthetic private payload" not in str(failure.value)
        await clipboard.close()
        assert runner.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["owned-selection", "success", "denied"])
async def test_selection_process_ownership_contract_on_every_platform(tmp_path, outcome):
    import shlex

    # This private helper models process ownership only. Real X11 receipt is
    # separately verified against the owned Xvfb display; no host GUI is touched.
    helper = tmp_path / "xclip"
    code = (
        "import pathlib,sys,time; assert sys.argv[1:]==['-quiet','-selection','clipboard']; pathlib.Path('owned-input').write_bytes(sys.stdin.buffer.read()); "
        + (
            "time.sleep(30)"
            if outcome == "owned-selection"
            else "time.sleep(.2); raise SystemExit(3)"
            if outcome == "denied"
            else "raise SystemExit(0)"
        )
    )
    helper.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -c " + shlex.quote(code) + ' "$@"\n'
    )
    helper.chmod(0o700)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", "")}
    data = b"owned\x00\x1b]52;c;inert\x07"
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, env, tmp_path)
        errors = []
        observed = asyncio.Event()

        def failed(error):
            errors.append(str(error))
            observed.set()

        try:
            await clipboard.write(data, B.X11, failed=failed)
        except AppError as error:
            failed(error)
        async with asyncio.timeout(5):
            while not (
                (tmp_path / "owned-input").exists()
                and (tmp_path / "owned-input").read_bytes() == data
            ):
                await asyncio.sleep(0.005)
        if outcome == "denied":
            await asyncio.wait_for(observed.wait(), 5)
            assert len(errors) == 1 and "Native clipboard" in errors[0]
        else:
            assert not errors
        assert (tmp_path / "owned-input").read_bytes() == data
        if outcome == "owned-selection":
            original = clipboard.owner
            assert original.running
            await clipboard.write(b"replacement", B.X11)
            assert original.task.done() and clipboard.owner.running
            async with asyncio.timeout(5):
                while (tmp_path / "owned-input").read_bytes() != b"replacement":
                    await asyncio.sleep(0.005)
            assert not errors
        await clipboard.close()
        assert runner.active_count == 0
