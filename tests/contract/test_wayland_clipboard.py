"""Exercise a real owned wl-copy-shaped process without a host compositor."""

import asyncio
import json
import os
import shlex
import sys

import pytest

from kuberich.domain.clipboard import MAX_NATIVE_BYTES, ClipboardBackend
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.services.access import AccessPolicy
from kuberich.services.clipboard import NativeClipboard
from kuberich.services.processes import ProcessRunner

PROGRAM = """
import json,os,sys,time
from pathlib import Path
assert sys.argv[1:]==['--foreground','--type','text/plain;charset=utf-8']
assert os.environ['WAYLAND_DISPLAY']=='owned-wayland-test'
data=sys.stdin.buffer.read()
receipt={'pid':os.getpid(),'args':sys.argv[1:],'hex':data.hex()}
pending=Path(f'receipt.{os.getpid()}.pending')
pending.write_text(json.dumps(receipt))
pending.replace('receipt.json')
mode=os.environ['OWNED_WAYLAND_MODE']
if mode in ('late-denied','late-success'):
    while not Path('release').exists(): time.sleep(.005)
if mode in ('denied','late-denied'):
    print('private compositor rejection',file=sys.stderr)
    sys.exit(3)
if mode in ('success','late-success'): sys.exit(0)
while True: time.sleep(1)
"""


def helper(directory, mode="hold"):
    path = directory / "wl-copy"
    path.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -c " + shlex.quote(PROGRAM) + ' "$@"\n'
    )
    path.chmod(0o700)
    return {
        **os.environ,
        "PATH": str(directory),
        "WAYLAND_DISPLAY": "owned-wayland-test",
        "XDG_RUNTIME_DIR": str(directory),
        "OWNED_WAYLAND_MODE": mode,
    }


async def receipt(directory, data):
    path = directory / "receipt.json"
    async with asyncio.timeout(5):
        while True:
            if path.exists():
                value = json.loads(path.read_text())
                if value["hex"] == data.hex():
                    return value
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_literal_plaintext_replacement_cancelled_waiter_and_exit_cleanup(tmp_path):
    payloads = [
        b"",
        "é 中文\n\x00\x1b]52;c;inert\x07 $(touch bad)".encode(),
        b"{\\rtf1 plain}",
        b"%!PS-Adobe-3.0 EPSF-3.0",
        b"replacement\n",
    ]
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, helper(tmp_path), tmp_path)
        previous = None
        try:
            for data in payloads:
                await clipboard.write(data, ClipboardBackend.WAYLAND)
                value = await receipt(tmp_path, data)
                assert value["args"] == [
                    "--foreground",
                    "--type",
                    "text/plain;charset=utf-8",
                ]
                assert clipboard.owner is not None and clipboard.owner.running
                assert value["pid"] == clipboard.owner.pid
                assert runner.active_count == 1
                if previous is not None:
                    assert previous.task.done()
                    with pytest.raises(ProcessLookupError):
                        os.kill(previous.pid, 0)
                previous = clipboard.owner
            waiter = asyncio.create_task(previous.wait())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert previous.running
            assert not (tmp_path / "bad").exists()
        finally:
            await clipboard.close()
            await clipboard.close()
        assert previous.task.done() and runner.active_count == 0
        with pytest.raises(ProcessLookupError):
            os.kill(previous.pid, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "late-success", "denied", "late-denied"])
async def test_success_and_rejection_are_observed_without_disclosing_text(tmp_path, mode):
    data = b"private clipboard payload"
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, helper(tmp_path, mode), tmp_path)
        errors = []
        observed = asyncio.Event()

        def failed(error):
            errors.append(str(error))
            observed.set()

        try:
            try:
                await clipboard.write(data, ClipboardBackend.WAYLAND, failed=failed)
            except AppError as error:
                failed(error)
            await receipt(tmp_path, data)
            if mode.startswith("late-"):
                assert clipboard.owner is not None and clipboard.owner.running
                assert clipboard.monitor is not None
                (tmp_path / "release").touch()
            if mode in {"denied", "late-denied"}:
                await asyncio.wait_for(observed.wait(), 5)
                assert len(errors) == 1
                assert "wl-copy" in errors[0] and "KUBERICH_CLIPBOARD=osc52" in errors[0]
                assert "private" not in errors[0]
            else:
                assert clipboard.owner is not None
                await clipboard.owner.wait()
                if clipboard.monitor is not None:
                    await asyncio.wait_for(clipboard.monitor, 5)
                assert not errors
        finally:
            await clipboard.close()
        assert runner.active_count == 0


@pytest.mark.asyncio
async def test_missing_helper_suggests_terminal_fallback_and_has_no_owner(tmp_path):
    environment = {**os.environ, "PATH": str(tmp_path), "WAYLAND_DISPLAY": "owned-wayland-test"}
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, environment, tmp_path)
        try:
            with pytest.raises(AppError, match=r"wl-copy.*KUBERICH_CLIPBOARD=osc52") as failure:
                await clipboard.write(b"private missing-helper payload", ClipboardBackend.WAYLAND)
            assert "private" not in str(failure.value)
            assert clipboard.owner is None and runner.active_count == 0
        finally:
            await clipboard.close()


@pytest.mark.asyncio
async def test_missing_x11_helper_keeps_its_original_executable_error(tmp_path):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, {"PATH": str(tmp_path)}, tmp_path)
        try:
            with pytest.raises(ExecutableUnavailable, match="installation, PATH"):
                await clipboard.write(b"private X11 payload", ClipboardBackend.X11)
            assert clipboard.owner is None and runner.active_count == 0
        finally:
            await clipboard.close()


@pytest.mark.asyncio
async def test_oversize_stdin_is_rejected_before_executable_start(tmp_path):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, helper(tmp_path), tmp_path)
        try:
            with pytest.raises(AppError, match="bounded input bytes"):
                await clipboard.write(b"x" * (MAX_NATIVE_BYTES + 1), ClipboardBackend.WAYLAND)
            assert not (tmp_path / "receipt.json").exists()
            assert clipboard.owner is None and runner.active_count == 0
        finally:
            await clipboard.close()
