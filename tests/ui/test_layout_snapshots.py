"""Limited layout goldens plus actual SVG evidence for the empty workspace and help."""

import json
import logging
from pathlib import Path

import pytest

from kubetrol.config.schema import Settings
from kubetrol.ui.app import KubetrolApp

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIERS = (
    "brand",
    "context",
    "namespace",
    "connection",
    "resource-view",
    "resources",
    "empty-title",
    "filter",
    "command",
    "status",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,size", [("normal", (100, 30)), ("compact", (40, 12))])
async def test_layout_and_rendered_evidence(
    name: str, size: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = KubetrolApp(Settings(), logging.Logger("snapshot", level=100))
    output = ROOT / "artifacts" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        actual = {
            "size": list(size),
            "compact": app.screen.has_class("compact"),
            "short": app.screen.has_class("short"),
            "regions": {
                identifier: list(app.query_one(f"#{identifier}").region)
                for identifier in IDENTIFIERS
            },
        }
        expected = json.loads((Path(__file__).parent / "snapshots" / f"{name}.json").read_text())
        assert actual == expected
        screenshot = app.export_screenshot(title=f"Kubetrol {name} preview")
        (output / f"shell-{name}.svg").write_text(screenshot)
        assert "Disconnected" in screenshot and "NAMESPACE" in screenshot
        if name == "compact":
            assert app.resources.max_scroll_x > 0
            await pilot.press("right", "end")
            assert app.resources.scroll_x > 0
            assert "AGE" in app.export_screenshot()
        await pilot.press("question_mark")
        help_svg = app.export_screenshot(title=f"Kubetrol {name} help")
        (output / f"help-{name}.svg").write_text(help_svg)
        assert "Keyboard&#160;help" in help_svg or "Keyboard help" in help_svg
