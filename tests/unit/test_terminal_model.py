"""Actual VT screen semantics, host-control isolation, geometry and key encoding."""

import pytest

from kubetrol.adapters.emulator import TerminalModel, _Router
from kubetrol.domain.terminal import terminal_key, terminal_paste, terminal_size
from kubetrol.errors import AppError


@pytest.mark.parametrize(
    "key,data",
    [
        ("enter", b"\r"),
        ("tab", b"\t"),
        ("escape", b"\x1b"),
        ("backspace", b"\x7f"),
        ("shift+tab", b"\x1b[Z"),
        ("insert", b"\x1b[2~"),
        ("delete", b"\x1b[3~"),
        ("pageup", b"\x1b[5~"),
        ("pagedown", b"\x1b[6~"),
        ("f1", b"\x1bOP"),
        ("f2", b"\x1bOQ"),
        ("f3", b"\x1bOR"),
        ("f4", b"\x1bOS"),
        ("f5", b"\x1b[15~"),
        ("f6", b"\x1b[17~"),
        ("f7", b"\x1b[18~"),
        ("f8", b"\x1b[19~"),
        ("f9", b"\x1b[20~"),
        ("f10", b"\x1b[21~"),
        ("f11", b"\x1b[23~"),
        ("f12", b"\x1b[24~"),
        ("ctrl+space", b"\0"),
        ("ctrl+at", b"\0"),
        ("ctrl+left_square_bracket", b"\x1b"),
        ("ctrl+backslash", b"\x1c"),
        ("ctrl+right_square_bracket", b"\x1d"),
        ("ctrl+circumflex_accent", b"\x1e"),
        ("ctrl+underscore", b"\x1f"),
        ("ctrl+c", b"\x03"),
        ("ctrl+z", b"\x1a"),
        ("ctrl+shift+left", b"\x1b[1;6D"),
        ("alt+right", b"\x1b[1;3C"),
        ("ctrl+alt+shift+up", b"\x1b[1;8A"),
        ("alt+x", b"\x1bx"),
    ],
)
def test_remote_keyboard_contract(key, data):
    assert terminal_key(key, None, application_cursor=False) == data


@pytest.mark.parametrize("application", [False, True])
@pytest.mark.parametrize(
    "key,suffix",
    [("up", "A"), ("down", "B"), ("right", "C"), ("left", "D"), ("home", "H"), ("end", "F")],
)
def test_cursor_application_mode(key, suffix, application):
    assert (
        terminal_key(key, None, application_cursor=application)
        == ("\x1b" + ("O" if application else "[") + suffix).encode()
    )


def test_printable_unicode_unknown_and_malformed_keys():
    assert terminal_key("é", "é", application_cursor=False) == "é".encode()
    for key in ["f99", "ctrl+abc", "ctrl+!", "meta+up", "ctrl+alt+x", "alt+word"]:
        assert terminal_key(key, None, application_cursor=False) == b""


def test_paste_is_bounded_literal_input_with_optional_bracketing():
    assert terminal_paste("á\r\nb\rc\n\t\x00\x1b\x7f", bracketed=False) == "á\rb\rc\r\t".encode()
    assert terminal_paste("abc", bracketed=True) == b"\x1b[200~abc\x1b[201~"
    with pytest.raises(AppError, match="too large"):
        terminal_paste("x" * 16385, bracketed=False)
    assert terminal_size(-1, 0) == (1, 1)
    assert terminal_size(10000, 10000) == (400, 150)
    assert terminal_size(81, 23) == (81, 23)


def test_cursor_erase_color_unicode_and_chunked_utf8():
    model = TerminalModel(12, 4, lambda _: None)
    data = "hello\r\x1b[31mRED\x1b[0m\x1b[2;2H界é".encode()
    for value in data:
        model.feed(bytes([value]))
    assert model.screen.display[0].startswith("REDlo")
    assert model.screen.display[1].startswith(" 界é")
    assert model.screen.buffer[0][0].fg == "red"
    model.feed(b"\x1b[H\x1b[2Jclear")
    assert model.screen.display[0].startswith("clear") and model.screen.display[1].strip() == ""
    model.feed(b"\x1b[38;2;10;20;30mX\x1b[48;5;27mY")
    assert model.screen.buffer[0][5].fg == "0a141e" and model.screen.buffer[0][6].bg == "005fff"


@pytest.mark.parametrize("mode", [47, 1047, 1049])
def test_fullscreen_buffers_and_resize_preserve_shell(mode):
    model = TerminalModel(20, 6, lambda _: None)
    model.feed(b"prompt> \x1b[?1h\x1b[?2004h")
    model.feed(f"\x1b[?{mode}h".encode() + b"EDITOR\x1b[?25l")
    assert model.screen.display[0].startswith("EDITOR") and model.screen.cursor.hidden
    model.resize(30, 8)
    model.feed(f"\x1b[?{mode}l\x1b[?1l\x1b[?2004l".encode())
    assert model.screen.display[0].startswith("prompt> ") and model.screen.columns == 30
    assert not model.application_cursor and not model.bracketed_paste
    model.alternate(True, clear=True)
    model.alternate(True, clear=True)
    assert model.screen.display[0].strip() == ""


def test_modes_reports_and_hostile_control_strings_are_bounded():
    replies = []
    model = TerminalModel(20, 6, replies.append)
    model.feed(b"\x1b[6n\x1b[5n\x1b[c")
    assert replies == [b"\x1b[1;1R", b"\x1b[0n", b"\x1b[?6c"]
    for prefix in [b"\x1b]52;c;", b"\x1bP", b"\x1bX", b"\x1b^", b"\x1b_", "\x9d".encode()]:
        model.feed(prefix + b"x" * 150000)
        assert len(model.controls.sequence) <= 128
        model.feed(b"\x1b\\")
    model.feed(b"\x1b]0;untrusted-title\x07\x1b[" + b"1;" * 200 + b"m")
    model.feed(b"\x1b[1:4m\x1b[4h\x1b[4l\x1b[?7h\x1b[?7l\x1b[?3h\x1b(B\x1b#8\rSAFE")
    assert model.screen.columns == 20 and model.screen.display[0].startswith("SAFE")
    assert len(replies) == 3 and model.screen.title == ""
    model.feed(b"\x1b[38;5;999m\x1b[?9999h\x00\x7f")
    with pytest.raises(AttributeError):
        _Router(model).__getattr__("not_an_event")


def test_saved_cursor_and_combining_cell_memory_remain_bounded():
    model = TerminalModel(20, 4, lambda _: None)
    model.feed(b"x" + b"\x1b7" * 2000)
    assert len(model.screen.savepoints) == 1
    model.feed(("\u0301" * 4000).encode())
    assert len(model.screen.buffer[0][0].data) <= 32
    model.feed(b"\x1b[2;1H" + "\u0301".encode())
    model.feed(b"\x1b[H" + "\u0301".encode())
    model.feed(b"\x1b8")
    assert model.screen.cursor.x == 1


def test_reset_c1_controls_and_cursor_visibility():
    model = TerminalModel(20, 4, lambda _: None)
    model.feed("\x9b31mRED\x9dtitle\x9c\x1b]discard\x1b!continued\x07".encode())
    model.feed(b"\x1b[?25h\x1b[?1049h\x1b[?1h\x1b[?2004h\x1bc")
    assert (
        model.screen is model.normal and not model.application_cursor and not model.bracketed_paste
    )
    assert model.screen.display[0].strip() == "" and not model.screen.cursor.hidden


@pytest.mark.parametrize("sequence", [b"\x1b[1;2;3H", b"\x1b[?6n", b"\x1b[1;2;3f"])
def test_malformed_or_unsupported_csi_cannot_abort_the_terminal(sequence):
    replies = []
    model = TerminalModel(20, 4, replies.append)
    model.feed(b"BEFORE")
    model.feed(sequence)
    model.feed(b"\rAFTER")
    assert model.screen.display[0].startswith("AFTER")
    assert not replies
