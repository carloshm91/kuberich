"""Clipboard policy bounds UTF-8 and never treats copied bytes as terminal controls."""

import base64
from dataclasses import replace

import pytest

from kuberich.domain.clipboard import (
    MAX_NATIVE_BYTES,
    MAX_OSC52_BYTES,
    clipboard_backend,
    clipboard_bytes,
    osc52,
)
from kuberich.domain.clipboard import (
    ClipboardBackend as B,
)
from kuberich.domain.processes import ProcessMode, ProcessPurpose
from kuberich.errors import AppError
from tests.unit.test_processes import command


@pytest.mark.parametrize(
    "environment,platform,headless,expected",
    [
        ({}, "linux", True, B.MEMORY),
        ({"KUBERICH_CLIPBOARD": "native"}, "linux", True, B.MEMORY),
        ({"KUBERICH_CLIPBOARD": "osc52"}, "darwin", False, B.OSC52),
        ({"SSH_CONNECTION": "fixture"}, "darwin", False, B.OSC52),
        ({"SSH_TTY": "/dev/owned"}, "linux", False, B.OSC52),
        ({}, "darwin", False, B.MACOS),
        ({"DISPLAY": ":77"}, "linux", False, B.X11),
        ({"DISPLAY": ":77", "WAYLAND_DISPLAY": "owned"}, "linux", False, B.WAYLAND),
        ({"WAYLAND_DISPLAY": "owned"}, "linux", False, B.WAYLAND),
        ({"DISPLAY": ":77", "WAYLAND_DISPLAY": ""}, "linux", False, B.X11),
        ({"WAYLAND_DISPLAY": "owned"}, "linux", True, B.MEMORY),
        ({"WAYLAND_DISPLAY": "owned", "SSH_TTY": "owned"}, "linux", False, B.OSC52),
        ({"WAYLAND_DISPLAY": "owned", "SSH_CONNECTION": "owned"}, "linux", False, B.OSC52),
        (
            {"WAYLAND_DISPLAY": "owned", "KUBERICH_CLIPBOARD": "osc52"},
            "linux",
            False,
            B.OSC52,
        ),
        (
            {"WAYLAND_DISPLAY": "owned", "KUBERICH_CLIPBOARD": "native", "SSH_TTY": "owned"},
            "linux",
            False,
            B.WAYLAND,
        ),
        ({"WAYLAND_DISPLAY": "owned", "DISPLAY": ":77"}, "darwin", False, B.MACOS),
        ({}, "linux", False, B.OSC52),
        ({"KUBERICH_CLIPBOARD": "native", "SSH_TTY": "owned"}, "darwin", False, B.MACOS),
    ],
)
def test_backend_uses_captured_transport_and_explicit_override(
    environment, platform, headless, expected
):
    assert clipboard_backend(environment, platform, headless=headless) is expected


@pytest.mark.parametrize("env", [{"KUBERICH_CLIPBOARD": "bad"}, {"KUBERICH_CLIPBOARD": "native"}])
def test_unavailable_or_invalid_explicit_backend_is_visible(env):
    with pytest.raises(AppError):
        clipboard_backend(env, "linux")


@pytest.mark.parametrize(
    "backend,limit",
    [
        (B.MEMORY, MAX_NATIVE_BYTES),
        (B.MACOS, MAX_NATIVE_BYTES),
        (B.WAYLAND, MAX_NATIVE_BYTES),
        (B.X11, MAX_NATIVE_BYTES),
        (B.OSC52, MAX_OSC52_BYTES),
    ],
)
def test_byte_bound_and_invalid_unicode(backend, limit):
    assert len(clipboard_bytes("é" * (limit // 2), backend)) == limit
    with pytest.raises(AppError, match="backend limit"):
        clipboard_bytes("é" * (limit // 2) + "x", backend)
    with pytest.raises(AppError, match="UTF-8"):
        clipboard_bytes("\ud800", backend)
    assert clipboard_bytes("", backend) == b""


def test_osc52_exact_safe_framing_and_tmux_escape():
    payload = "\x1b]52;c;hostile\x07[markup] 中文\x00".encode()
    expected = "\x1b]52;c;" + base64.b64encode(payload).decode() + "\x07"
    assert osc52(payload, tmux=False) == expected
    assert (
        osc52(payload, tmux=True) == "\x1bPtmux;" + expected.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    )
    with pytest.raises(AppError, match="64 KiB"):
        osc52(b"x" * (MAX_OSC52_BYTES + 1), tmux=False)


@pytest.mark.parametrize(
    "changes",
    [
        {"input_data": "not bytes"},
        {"input_data": b"x" * (MAX_NATIVE_BYTES + 1)},
        {"purpose": ProcessPurpose.PLUGIN},
        {"mode": ProcessMode.FOREGROUND},
    ],
)
def test_process_stdin_is_clipboard_only_and_bounded(tmp_path, changes):
    value = command(tmp_path, purpose=ProcessPurpose.CLIPBOARD, input_data=b"synthetic")
    assert value.purpose.action.name == "READ"
    assert "synthetic" not in repr(value)
    with pytest.raises(AppError, match="clipboard commands"):
        replace(value, **changes)
