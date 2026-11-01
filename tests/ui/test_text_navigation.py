"""The canonical editor and lightweight scroll view retain public Vim navigation."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from kuberich.ui import text_navigation
from kuberich.ui.read_only_text import ReadOnlyText
from kuberich.ui.text_navigation import ReadOnlyScroll


def test_legacy_read_only_text_import_is_the_actual_canonical_class():
    assert text_navigation.ReadOnlyText is ReadOnlyText
    with pytest.raises(AttributeError, match="unknown_owned_export"):
        _ = text_navigation.unknown_owned_export


@pytest.mark.asyncio
async def test_read_only_editor_retains_edges_half_pages_and_literal_document():
    document = "\n".join(f"row {index:03} · 雪\tvalue" for index in range(80))

    class EditorApp(App):
        def __init__(self):
            super().__init__()
            self.viewer = ReadOnlyText(document, read_only=True, soft_wrap=False)

        def compose(self) -> ComposeResult:
            yield self.viewer

        def on_mount(self):
            self.set_focus(self.viewer)

    app = EditorApp()
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.press("G")
        assert app.viewer.cursor_location == (79, 0)
        await pilot.press("g")
        assert app.viewer.cursor_location == (0, 0)
        await pilot.press("ctrl+d")
        assert app.viewer.cursor_location[0] == max(1, app.viewer.content_region.height // 2)
        await pilot.press("ctrl+u")
        assert app.viewer.cursor_location == (0, 0)
        await pilot.press("j", "k", "x", "enter")
        assert app.viewer.text == document and app.viewer.read_only


@pytest.mark.asyncio
async def test_read_only_scroll_retains_cursor_edges_pages_and_half_pages():
    class ScrollApp(App):
        def __init__(self):
            super().__init__()
            self.viewer = ReadOnlyScroll()

        def compose(self) -> ComposeResult:
            with self.viewer:
                yield Static("\n".join(f"row {index:03}" for index in range(80)))

        def on_mount(self):
            self.set_focus(self.viewer)

    app = ScrollApp()
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.press("G")
        assert app.viewer.scroll_y == app.viewer.max_scroll_y > 0
        await pilot.press("g")
        assert app.viewer.scroll_y == 0
        await pilot.press("j")
        assert app.viewer.scroll_y == 1
        await pilot.press("k")
        assert app.viewer.scroll_y == 0
        await pilot.press("ctrl+f")
        assert app.viewer.scroll_y == app.viewer.scrollable_content_region.height
        await pilot.press("ctrl+b")
        assert app.viewer.scroll_y == 0
        await pilot.press("ctrl+d")
        assert app.viewer.scroll_y == max(1, app.viewer.scrollable_content_region.height // 2)
        await pilot.press("ctrl+u")
        assert app.viewer.scroll_y == 0
