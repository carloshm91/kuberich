"""Explicit read arguments and complete, bounded private text captures."""

import pytest

from kuberich.domain.clipboard import (
    MAX_NATIVE_BYTES,
    ClipboardBackend,
    clipboard_read_arguments,
    clipboard_source_bytes,
    pasted_source_bytes,
)
from kuberich.errors import AppError


@pytest.mark.parametrize(
    "backend,expected",
    [
        (ClipboardBackend.MACOS, ("/usr/bin/pbpaste",)),
        (ClipboardBackend.WAYLAND, ("wl-paste", "--no-newline", "--type", "text/plain")),
        (
            ClipboardBackend.X11,
            ("xclip", "-selection", "clipboard", "-out", "-target", "UTF8_STRING"),
        ),
    ],
)
def test_native_read_arguments_are_literal(backend, expected):
    assert clipboard_read_arguments(backend) == expected


@pytest.mark.parametrize("backend", [ClipboardBackend.MEMORY, ClipboardBackend.OSC52, "unknown"])
def test_unsupported_backends_never_query_terminal_clipboard(backend):
    with pytest.raises(AppError, match="Paste capture"):
        clipboard_read_arguments(backend)


@pytest.mark.parametrize("text", ["", "é 中文\n\t\rvalue", "x" * MAX_NATIVE_BYTES])
def test_text_capture_preserves_exact_bytes_and_allowed_whitespace(text):
    assert clipboard_source_bytes(text.encode()) == text.encode()
    assert pasted_source_bytes(text) == text.encode()


@pytest.mark.parametrize("data", [bytearray(b"x"), "text", b"x" * (MAX_NATIVE_BYTES + 1)])
def test_source_requires_immutable_bounded_bytes(data):
    with pytest.raises(AppError, match="immutable"):
        clipboard_source_bytes(data)


@pytest.mark.parametrize("data", [b"\xff", b"\xc3", b"\xed\xa0\x80"])
def test_invalid_utf8_is_refused_without_partial_capture(data):
    with pytest.raises(AppError, match="UTF-8"):
        clipboard_source_bytes(data)


@pytest.mark.parametrize("control", ["\0", "\x1b", "\x7f", "\x85", "\u202e", "\u2066"])
def test_terminal_and_directional_controls_are_refused(control):
    with pytest.raises(AppError, match="control"):
        pasted_source_bytes("private" + control)


@pytest.mark.parametrize("text", [None, b"bytes"])
def test_paste_requires_text(text):
    with pytest.raises(AppError, match="text"):
        pasted_source_bytes(text)


def test_paste_invalid_unicode_and_excess_are_refusals():
    with pytest.raises(AppError, match="UTF-8"):
        pasted_source_bytes("\ud800")
    with pytest.raises(AppError, match="backend limit"):
        pasted_source_bytes("é" * (MAX_NATIVE_BYTES // 2 + 1))


def test_oversized_paste_is_refused_before_encoding_another_copy():
    class NeverEncode(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("Oversized paste must be refused before encoding")

    with pytest.raises(AppError, match="backend limit"):
        pasted_source_bytes(NeverEncode("x" * (MAX_NATIVE_BYTES + 1)))
