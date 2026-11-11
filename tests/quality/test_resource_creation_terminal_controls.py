"""Creation CLI input waits for its phase's complete public footer paint."""

from types import SimpleNamespace

import pyte
import pytest

from tests.support.resource_creation_cli import click_visible


@pytest.mark.parametrize("label", ["Validate", "Confirm Create", "Stop"])
def test_review_click_refuses_mixed_source_footer_and_uses_one_complete_row(label):
    screen = pyte.Screen(120, 36)
    stream = pyte.Stream(screen)
    # The retained macOS failure has this exact mixed row during modal repaint:
    # the new status starts with Validate while the old source controls survive.
    stream.feed(
        "\x1b[1;1HManifest cluster review"
        "\x1b[32;1H │ ValidateImport file                  Edit draft"
        "                Review Create                    Stop              │  "
    )
    mixed = screen.display[31]
    assert "Validate" in mixed and "Import file" in mixed and "Stop" in mixed
    sent = []
    reads = []

    def read(timeout):
        assert not sent, "Input was sent before the review footer finished painting"
        reads.append(timeout)
        assert len(reads) == 1
        stream.feed(
            "\x1b[32;1H\x1b[2K"
            "\x1b[33;1H │               Validate                           Confirm Create"
            "                             Stop                  │  "
        )

    terminal = SimpleNamespace(screen=screen, read=read, send=sent.append)
    click_visible(terminal, label, controls=("Validate", "Confirm Create", "Stop"))
    column = screen.display[32].index(label) + len(label) // 2 + 1
    assert reads == [0.01]
    assert sent == [f"\x1b[<0;{column};33M\x1b[<0;{column};33m".encode()]


def test_missing_complete_footer_keeps_the_original_deadline(monkeypatch):
    moments = iter((0, 16))
    monkeypatch.setattr("tests.support.resource_creation_cli.time.monotonic", lambda: next(moments))
    terminal = SimpleNamespace(
        screen=SimpleNamespace(display=["ValidateImport file Edit draft Review Create Stop"]),
        send=lambda data: pytest.fail("Incomplete footer must not receive input"),
        read=lambda timeout: pytest.fail("Expired original deadline must refuse"),
    )
    with pytest.raises(AssertionError, match="Public control footer was not rendered"):
        click_visible(terminal, "Validate", controls=("Validate", "Confirm Create", "Stop"))
