"""Actual Rich rendering neutralizes markup, hyperlinks, terminal controls and credentials."""

import io

import pytest
from rich.console import Console

from kubetrol.diagnostics.redaction import sanitize_text
from kubetrol.security.controls import escape_controls
from kubetrol.security.presentation import MAX_DISPLAY_CHARACTERS, safe_text


@pytest.mark.parametrize(
    "value",
    [
        "[red]pod[/red]",
        "[link=https://attacker.invalid]click[/link]",
        "[/]",
        "[bold",
        "pod\x1b[2J\x1b[H",
        "\x1b]52;c;fake-clipboard\x07",
        "\x1b]8;;https://attacker.invalid\x1b\\",
        "\x9b2J\x9d52;c;fake\x9c",
        "pod\rforged\nentry\tcell\b",
        "fake\u202euid\u2066",
        "direction\u061c\u200e\u200f\u2028\u2029",
        "malformed\ud800\udfff",
    ],
)
def test_hostile_text_is_literal_and_terminal_controls_are_inert(value: str) -> None:
    text = safe_text(value)
    assert text.spans == [] and text.style == ""
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system="truecolor", width=240)
    console.print(text, end="", soft_wrap=True)
    rendered = output.getvalue()
    assert rendered == text.plain
    assert escape_controls(rendered) == rendered
    if "[" in value and "\x1b" not in value:
        assert value in rendered


def test_safe_error_summary_keeps_status_operation_and_resource_context() -> None:
    value = "403 Forbidden listing pods in fixture-ns: token=synthetic-credential"
    assert safe_text(value).plain == ("403 Forbidden listing pods in fixture-ns: token=[REDACTED]")
    assert "synthetic-credential" not in sanitize_text(value)


def test_multiline_logs_preserve_only_explicit_linefeeds_and_unicode() -> None:
    value = "café 你好 👩‍💻🙂\nnext\tcell\r\x1b[31m"
    assert safe_text(value, multiline=True).plain == (
        "café 你好 👩‍💻🙂\nnext\\u0009cell\\u000d\\u001b[31m"
    )
    assert "\n" not in safe_text(value).plain
    assert escape_controls("literal \\u000a", allow_newlines=True) == "literal \\u000a"


def test_display_bounds_include_a_notice_and_do_not_expose_a_truncated_secret() -> None:
    text = safe_text('password="' + "synthetic" * MAX_DISPLAY_CHARACTERS)
    assert text.plain == "password=[REDACTED] … [truncated]"
    assert safe_text("x" * MAX_DISPLAY_CHARACTERS).plain == "x" * MAX_DISPLAY_CHARACTERS
    assert safe_text("x" * (MAX_DISPLAY_CHARACTERS + 1)).plain.endswith(" … [truncated]")


def test_opaque_values_are_not_claimed_to_be_recognizable_credentials() -> None:
    assert safe_text("opaque-fixture-without-a-secret-label").plain == (
        "opaque-fixture-without-a-secret-label"
    )
