"""Render terminal, directional and malformed Unicode controls as inert text."""

import re

_CONTROLS = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069\ud800-\udfff]"
)


def escape_controls(text: str, *, allow_newlines: bool = False) -> str:
    """Only an explicitly requested line feed survives; tabs/CR/escapes never do."""

    def escape(match: re.Match[str]) -> str:
        char = match.group()
        if allow_newlines and char == "\n":
            return char
        return f"\\u{ord(char):04x}"

    return _CONTROLS.sub(escape, text)
