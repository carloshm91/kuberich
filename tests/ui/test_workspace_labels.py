"""Owned repeated text preserves native rendering, styling and external edits."""

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.theme import Theme
from textual.widgets import Static

from kuberich.ui.chrome import POD_SHORTCUTS, WorkspaceChrome, WorkspaceHeader, WorkspaceLabel


class LabelsApp(App):
    def compose(self) -> ComposeResult:
        yield WorkspaceLabel("initial", id="first", markup=False)
        yield WorkspaceLabel("initial", id="second", markup=False)
        yield Static("initial", id="native", markup=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content", ["same literal [value]", Text("same Unicode 界🙂", style="bold")]
)
async def test_repeated_owned_text_avoids_native_layout_updates_and_keeps_rendering(
    monkeypatch, content
):
    calls = []
    original = Static.update

    def observed(widget, *args, **kwargs):
        calls.append(widget.id)
        return original(widget, *args, **kwargs)

    monkeypatch.setattr(Static, "update", observed)
    app = LabelsApp()
    async with app.run_test(size=(70, 20)) as pilot:
        first = app.query_one("#first", WorkspaceLabel)
        second = app.query_one("#second", WorkspaceLabel)
        native = app.query_one("#native", Static)
        for _ in range(100):
            first.update_text(content.copy() if isinstance(content, Text) else content)
        second.update_text(content)
        native.update(content)
        await pilot.pause()
        assert calls.count("first") == calls.count("second") == calls.count("native") == 1
        assert first.content == second.content == native.content == content
        assert first.render_lines(first.content_region.at_offset((0, 0))) == native.render_lines(
            native.content_region.at_offset((0, 0))
        )


@pytest.mark.asyncio
async def test_style_changes_and_mutated_original_text_still_receive_native_updates(monkeypatch):
    calls = []
    original = Static.update

    def observed(widget, *args, **kwargs):
        calls.append(widget.content)
        return original(widget, *args, **kwargs)

    monkeypatch.setattr(Static, "update", observed)
    app = LabelsApp()
    async with app.run_test() as pilot:
        label = app.query_one("#first", WorkspaceLabel)
        value = Text("value", style="red")
        label.update_text(value)
        label.update_text(Text("value", style="green"))
        assert len(calls) == 2
        assert label.content.style == "green"
        current = label.content
        assert isinstance(current, Text)
        current.append(" changed")
        label.update_text(current.copy())
        assert len(calls) == 3
        assert label.content == Text("value changed", style="green")
        label.update_text(Text("value", style="green"))
        assert len(calls) == 4
        await pilot.pause()


@pytest.mark.asyncio
async def test_inherited_updates_and_custom_renderables_keep_the_native_contract(monkeypatch):
    class Renderable:
        def __rich__(self):
            return Text("custom")

        def __eq__(self, other):
            raise AssertionError("Unknown renderer must not be compared with owned text")

    class TextSubclass(Text):
        pass

    calls = []
    original = Static.update

    def observed(widget, *args, **kwargs):
        calls.append(widget.id)
        return original(widget, *args, **kwargs)

    monkeypatch.setattr(Static, "update", observed)
    app = LabelsApp()
    async with app.run_test() as pilot:
        label = app.query_one("#first", WorkspaceLabel)
        label.update_text("owned")
        label.update(Renderable())
        label.update_text("owned")
        label.content = "externally changed"
        label.update_text("owned")
        label.update_text(TextSubclass("owned"))
        label.update_text(TextSubclass("owned"))
        assert calls.count("first") == 6
        assert label.content.plain == "owned"
        await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("style", "bold"),
        ("justify", "right"),
        ("overflow", "ellipsis"),
        ("no_wrap", True),
        ("end", ""),
        ("tab_size", 4),
    ],
)
async def test_all_public_text_render_attributes_invalidate_the_projection(
    monkeypatch, attribute, value
):
    calls = []
    original = Static.update

    def observed(widget, *args, **kwargs):
        calls.append(widget.id)
        return original(widget, *args, **kwargs)

    monkeypatch.setattr(Static, "update", observed)
    app = LabelsApp()
    async with app.run_test() as pilot:
        label = app.query_one("#first", WorkspaceLabel)
        native = app.query_one("#native", Static)
        initial = Text("text with a\ttab")
        changed = initial.copy()
        setattr(changed, attribute, value)
        label.update_text(initial)
        label.update_text(changed)
        native.update(changed)
        await pilot.pause()
        assert calls.count("first") == 2
        assert getattr(label.content, attribute) == getattr(native.content, attribute) == value
        assert label.render_lines(label.content_region.at_offset((0, 0))) == native.render_lines(
            native.content_region.at_offset((0, 0))
        )


@pytest.mark.asyncio
async def test_header_reuses_unchanged_fields_but_repaints_identity_and_theme_changes(monkeypatch):
    identity = ["owned", "cluster", "user", "default", "Live"]
    chrome = WorkspaceChrome(lambda: tuple(identity), "0.0.1.dev0")
    header = WorkspaceHeader(chrome, POD_SHORTCUTS)

    class HeaderApp(App):
        def compose(self) -> ComposeResult:
            yield header

    calls = []
    original = Static.update

    def observed(widget, *args, **kwargs):
        if isinstance(widget, WorkspaceLabel):
            calls.append(widget.id)
        return original(widget, *args, **kwargs)

    monkeypatch.setattr(Static, "update", observed)
    app = HeaderApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(calls) == 5
        for _ in range(100):
            header.update_identity()
        assert len(calls) == 5
        identity[4] = "Retrying"
        header.update_identity()
        assert calls[-1] == "connection" and len(calls) == 6
        assert header.query_one("#connection", WorkspaceLabel).content.plain == "State: Retrying"
        before = header.query_one("#context", WorkspaceLabel).content.copy()
        app.register_theme(Theme(name="owned-label-test", primary="#0178d4", accent="#123456"))
        app.theme = "owned-label-test"
        await pilot.pause()
        header.update_identity()
        assert len(calls) == 11
        after = header.query_one("#context", WorkspaceLabel).content
        assert after.plain == before.plain and after != before
