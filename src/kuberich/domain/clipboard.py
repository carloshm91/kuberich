"""Bounded explicit clipboard decisions and trusted write-only terminal framing."""

import base64
from collections.abc import Mapping
from enum import StrEnum

from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

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


def clipboard_read_arguments(backend: ClipboardBackend) -> tuple[str, ...]:
    if backend is ClipboardBackend.MACOS:
        return ("/usr/bin/pbpaste",)
    if backend is ClipboardBackend.WAYLAND:
        return ("wl-paste", "--no-newline", "--type", "text/plain")
    if backend is ClipboardBackend.X11:
        return ("xclip", "-selection", "clipboard", "-out", "-target", "UTF8_STRING")
    raise AppError("Native clipboard reads are unavailable; choose explicit Paste capture.")


def clipboard_source_bytes(data: bytes) -> bytes:
    """Accept complete UTF-8 text only; do not partially import or normalize it."""
    if type(data) is not bytes or len(data) > MAX_NATIVE_BYTES:
        raise AppError("Clipboard source must be complete immutable text of at most 1 MiB.")
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeError:
        raise AppError("Clipboard source is not valid UTF-8.") from None
    whitespace = text.replace("\t", "").replace("\r", "")
    if escape_controls(whitespace, allow_newlines=True) != whitespace:
        raise AppError("Clipboard source contains unsupported control characters.")
    return data


def pasted_source_bytes(text: str) -> bytes:
    if not isinstance(text, str):
        raise AppError("Paste capture requires explicit UTF-8 text.")
    if len(text) > MAX_NATIVE_BYTES:
        raise AppError("Paste exceeds the 1024 KiB backend limit; select less text.")
    return clipboard_source_bytes(clipboard_bytes(text, ClipboardBackend.MEMORY))


def osc52(data: bytes, *, tmux: bool) -> str:
    # Never concatenate remote text into a terminal control sequence.
    if len(data) > MAX_OSC52_BYTES:
        raise AppError("Terminal clipboard exceeds 64 KiB.")
    framed = "\x1b]52;c;" + base64.b64encode(data).decode("ascii") + "\x07"
    return "\x1bPtmux;" + framed.replace("\x1b", "\x1b\x1b") + "\x1b\\" if tmux else framed
