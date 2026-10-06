"""Bounded terminal geometry and literal keyboard encoding, independent of widgets."""

from kubetrol.errors import AppError


def terminal_size(width: int, height: int) -> tuple[int, int]:
    return min(400, max(1, width)), min(150, max(1, height))


_KEYS = {
    "enter": b"\r",
    "tab": b"\t",
    "backspace": b"\x7f",
    "escape": b"\x1b",
    "shift+tab": b"\x1b[Z",
    "insert": b"\x1b[2~",
    "delete": b"\x1b[3~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "f5": b"\x1b[15~",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "f11": b"\x1b[23~",
    "f12": b"\x1b[24~",
    "ctrl+space": b"\x00",
    "ctrl+at": b"\x00",
    "ctrl+left_square_bracket": b"\x1b",
    "ctrl+backslash": b"\x1c",
    "ctrl+right_square_bracket": b"\x1d",
    "ctrl+circumflex_accent": b"\x1e",
    "ctrl+underscore": b"\x1f",
}
_CURSORS = {"up": "A", "down": "B", "right": "C", "left": "D", "home": "H", "end": "F"}


def terminal_key(key: str, character: str | None, *, application_cursor: bool) -> bytes:
    if key in _CURSORS:
        return ("\x1b" + ("O" if application_cursor else "[") + _CURSORS[key]).encode()
    if key in _KEYS:
        return _KEYS[key]
    parts = key.split("+")
    if len(parts) == 2 and parts[0] == "ctrl" and len(parts[1]) == 1 and "a" <= parts[1] <= "z":
        return bytes([ord(parts[1]) - ord("a") + 1])
    if len(parts) > 1 and parts[-1] in _CURSORS and set(parts[:-1]) <= {"ctrl", "alt", "shift"}:
        modifier = 1 + ("shift" in parts) + 2 * ("alt" in parts) + 4 * ("ctrl" in parts)
        return f"\x1b[1;{modifier}{_CURSORS[parts[-1]]}".encode()
    if len(parts) == 2 and parts[0] == "alt" and len(parts[1]) == 1:
        return b"\x1b" + parts[1].encode("utf-8")
    return character.encode("utf-8") if character is not None else b""


def terminal_paste(text: str, *, bracketed: bool) -> bytes:
    if len(text) > 16384:
        raise AppError("Paste is too large; use at most 16384 characters at a time.")
    # A clipboard paste is text, not a second source of terminal protocol/input controls.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(c for c in text if c in "\n\t" or (c.isprintable() and c != "\x7f"))
    data = value.replace("\r\n", "\n").replace("\n", "\r").encode("utf-8")
    if bracketed:
        return b"\x1b[200~" + data + b"\x1b[201~"
    return data
