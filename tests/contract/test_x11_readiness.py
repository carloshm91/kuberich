"""Delayed real selection ownership must keep the exact native contract intact."""

import asyncio
import json
import os
import shutil
import sys

import pytest

from kuberich.domain.clipboard import ClipboardBackend
from kuberich.services.access import AccessPolicy
from kuberich.services.clipboard import NativeClipboard
from kuberich.services.processes import ProcessRunner
from tests.contract.test_clipboard import (
    test_owned_x11_roundtrip_replacement_and_owner_cleanup as qualify_x11,
)
from tests.support.clipboard import owned_x11_display, read_x11_selection


@pytest.mark.asyncio
async def test_delayed_real_x11_owner_still_qualifies_all_original_payloads(tmp_path, monkeypatch):
    real_xclip = shutil.which("xclip")
    if sys.platform != "linux" or not shutil.which("Xvfb") or real_xclip is None:
        pytest.skip("Owned delayed selection qualification requires Linux Xvfb and xclip")
    tools = tmp_path / "tools"
    tools.mkdir()
    wrapper = tools / "xclip"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os,sys,time\n"
        "if '-quiet' in sys.argv[1:]: time.sleep(0.3)\n"
        f"os.execv({real_xclip!r}, [{real_xclip!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ.get("PATH", ""))
    await qualify_x11(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["absent", "different"])
async def test_missing_owned_selection_expires_and_leaves_no_reader(tmp_path, selection):
    if sys.platform != "linux" or not shutil.which("Xvfb") or not shutil.which("xclip"):
        pytest.skip("Owned selection readiness requires Linux Xvfb and xclip")
    receipt = tmp_path / "missing.json"
    expected = b"synthetic-private-selection"
    other = b"synthetic-different-owned-selection"
    async with owned_x11_display() as environment, ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, environment, tmp_path)
        if selection == "different":
            await clipboard.write(other, ClipboardBackend.X11)
            await read_x11_selection(
                runner, environment, tmp_path, other, receipt=tmp_path / "prior-selection.json"
            )
        with pytest.raises(TimeoutError, match="did not serve"):
            await read_x11_selection(
                runner, environment, tmp_path, expected, receipt=receipt, timeout=0.15
            )
        await clipboard.close()
        assert runner.active_count == 0
    report = json.loads(receipt.read_text())
    assert not report["ready"] and report["attempts"] > 0
    assert len(report["recent"]) <= 16
    assert not any(item["matched"] for item in report["recent"])
    assert expected.decode() not in receipt.read_text()
    assert other.decode() not in receipt.read_text()
    if selection == "different":
        assert any(item["status"] == "SUCCEEDED" for item in report["recent"])


@pytest.mark.asyncio
async def test_cancelled_selection_reader_is_reaped_before_return(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    pid = tmp_path / "reader-pid"
    wrapper = tools / "xclip"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os,time\nfrom pathlib import Path\n"
        f"Path({str(pid)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    wrapper.chmod(0o700)
    receipt = tmp_path / "cancelled.json"
    async with ProcessRunner(AccessPolicy(True)) as runner:
        task = asyncio.create_task(
            read_x11_selection(
                runner,
                {**os.environ, "PATH": str(tools)},
                tmp_path,
                b"synthetic-unread-payload",
                receipt=receipt,
            )
        )
        try:
            async with asyncio.timeout(5):
                while not pid.exists():
                    await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert runner.active_count == 0
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid.read_text()), 0)
    assert not json.loads(receipt.read_text())["ready"]
