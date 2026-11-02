"""Delayed real selection ownership must keep the exact native contract intact."""

import asyncio
import ctypes
import ctypes.util
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


def generation_marker(environment, *, create=False):
    # libX11 is the existing xclip runtime dependency; no new executable is
    # required. A root property belongs to this disposable server generation.
    library = ctypes.util.find_library("X11")
    assert library is not None, "The required Linux xclip lane needs its libX11 runtime."
    x11 = ctypes.CDLL(library)
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XChangeProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XFree.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(environment["DISPLAY"].encode("ascii"))
    assert display, "The owned Xvfb display must accept its generation probe."
    try:
        root = x11.XDefaultRootWindow(display)
        atom = x11.XInternAtom(display, b"KUBERICH_OWNED_GENERATION", False)
        marker = b"owned-generation"
        if create:
            x11.XChangeProperty(display, root, atom, 31, 8, 0, marker, len(marker))
            x11.XSync(display, False)
        kind, width = ctypes.c_ulong(), ctypes.c_int()
        count, remaining, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        result = x11.XGetWindowProperty(
            display,
            root,
            atom,
            0,
            32,
            False,
            0,
            ctypes.byref(kind),
            ctypes.byref(width),
            ctypes.byref(count),
            ctypes.byref(remaining),
            ctypes.byref(data),
        )
        try:
            assert result == 0 and remaining.value == 0 and count.value <= len(marker)
            assert kind.value == 0 or (kind.value == 31 and width.value == 8)
            return ctypes.string_at(data, count.value) if data.value else b""
        finally:
            if data.value:
                x11.XFree(data)
    finally:
        x11.XCloseDisplay(display)


@pytest.mark.asyncio
async def test_owned_display_generation_survives_the_gap_between_selection_owners(tmp_path):
    if sys.platform != "linux":
        pytest.skip("The owned Xvfb generation contract is required on the Linux lane.")
    assert shutil.which("Xvfb") and shutil.which("xclip"), "Install the required Xvfb/xclip tools."
    async with owned_x11_display() as environment, ProcessRunner(AccessPolicy(True)) as runner:
        clipboard = NativeClipboard(runner, environment, tmp_path)
        try:
            data = b"synthetic-owned-generation"
            await clipboard.write(data, ClipboardBackend.X11)
            assert (
                await read_x11_selection(
                    runner, environment, tmp_path, data, receipt=tmp_path / "before-gap.json"
                )
                == data
            )
            owner = clipboard.owner
            assert owner is not None and owner.running
            assert generation_marker(environment, create=True) == b"owned-generation"
            await clipboard.close()
            assert owner.task.done() and runner.active_count == 0
            with pytest.raises(ProcessLookupError):
                os.kill(owner.pid, 0)
            assert generation_marker(environment) == b"owned-generation"
        finally:
            await clipboard.close()
