"""Bounded, write-only clipboard decisions and trusted terminal framing."""

import base64
from collections.abc import Mapping
from enum import StrEnum

from kuberich.errors import AppError

MAX_NATIVE_BYTES = 1024 * 1024
MAX_OSC52_BYTES = 64 * 1024


class ClipboardBackend(StrEnum):
    MEMORY = "memory"
    MACOS = "macos"
    WAYLAND = "wayland"
    X11 = "x11"
    OSC52 = "osc52"


def clipboard_backend(
    environment: Mapping[str, str], platform: str, *, headless: bool = False
) -> ClipboardBackend:
    preference = environment.get("KUBERICH_CLIPBOARD", "auto")
    if preference not in {"auto", "native", "osc52"}:
        raise AppError("KUBERICH_CLIPBOARD must be auto, native or osc52.")
    if headless:
        return ClipboardBackend.MEMORY
    if preference == "osc52" or (
        preference == "auto" and ("SSH_CONNECTION" in environment or "SSH_TTY" in environment)
    ):
        return ClipboardBackend.OSC52
    if platform == "darwin":
        return ClipboardBackend.MACOS
    if environment.get("WAYLAND_DISPLAY"):
        return ClipboardBackend.WAYLAND
    if environment.get("DISPLAY"):
        return ClipboardBackend.X11
    if preference == "native":
        raise AppError(
            "Native clipboard is unavailable; use a Wayland, X11 or macOS session, "
            "or set KUBERICH_CLIPBOARD=osc52."
        )
    return ClipboardBackend.OSC52


def clipboard_bytes(text: str, backend: ClipboardBackend) -> bytes:
    try:
        data = text.encode("utf-8", "strict")
    except UnicodeError:
        raise AppError("Clipboard text is not valid UTF-8.") from None
    limit = MAX_OSC52_BYTES if backend is ClipboardBackend.OSC52 else MAX_NATIVE_BYTES
    if len(data) > limit:
        raise AppError(
            f"Clipboard exceeds the {limit // 1024} KiB backend limit; select less text."
        )
    return data


def osc52(data: bytes, *, tmux: bool) -> str:
    # Never concatenate remote text into a terminal control sequence.
    if len(data) > MAX_OSC52_BYTES:
        raise AppError("Terminal clipboard exceeds 64 KiB.")
    framed = "\x1b]52;c;" + base64.b64encode(data).decode("ascii") + "\x07"
    return "\x1bPtmux;" + framed.replace("\x1b", "\x1b\x1b") + "\x1b\\" if tmux else framed
