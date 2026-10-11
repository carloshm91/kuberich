"""Component styles preserve native CSS semantics without repeated DOM allocation."""

import weakref
from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.css.stylesheet import Stylesheet
from textual.widgets import Static

from kuberich.ui.style_cache import ComponentStylesheet


class ComponentProbe(Static):
    can_focus = True
    COMPONENT_CLASSES: ClassVar[set[str]] = {"probe-part", "probe-empty"}


class ComponentApp(App):
    CSS = """
    ComponentProbe .probe-part { color: red; background: $surface; text-style: bold; }
    ComponentProbe:focus .probe-part { color: blue; }
    ComponentProbe.picked .probe-part { color: green; }
    ComponentProbe.picked:focus .probe-part { color: yellow; }
    """

    def __init__(self, stylesheet_type):
        super().__init__()
        self.stylesheet = stylesheet_type(variables=self.get_css_variables())

    def compose(self) -> ComposeResult:
        yield ComponentProbe("Literal 界 [red]", id="probe")
        yield ComponentProbe("Other focus target", id="other")


async def component_observations(stylesheet_type):
    app = ComponentApp(stylesheet_type)
    observations = []
    changed_nodes = 0
    async with app.run_test() as pilot:
        probe = app.query_one("#probe", ComponentProbe)
        other = app.query_one("#other", ComponentProbe)
        original_nodes = {
            name: weakref.ref(styles.node) for name, styles in probe._component_styles.items()
        }

        def observe():
            nonlocal changed_nodes
            changed_nodes += sum(
                original_nodes[name]() is not styles.node
                for name, styles in probe._component_styles.items()
            )
            observations.append(
                {
                    name: (styles.base.get_rules(), styles.inline.get_rules())
                    for name, styles in probe._component_styles.items()
                }
            )

        observe()
        for iteration in range(8):
            app.theme = "textual-light" if iteration % 2 else "textual-dark"
            probe.set_class(iteration % 3 == 0, "picked")
            (probe if iteration % 2 else other).focus()
            await pilot.resize_terminal(*((40, 12) if iteration % 2 else (100, 30)))
            await pilot.pause()
            observe()

        # Native component evaluation discards inline edits on the next apply.
        probe.get_component_styles("probe-part").color = "magenta"
        app.stylesheet.apply(probe)
        await pilot.pause()
        observe()

        # CSS copies are used by native file reload; retain the bounded evaluator.
        copied = app.stylesheet.copy()
        assert type(copied) is stylesheet_type
        assert copied.source == app.stylesheet.source
        assert copied.source is not app.stylesheet.source
        app.stylesheet = copied
        copied.add_source(
            "ComponentProbe .probe-part { color: cyan; text-style: italic; }",
            read_from=("component-regression", "override"),
        )
        app.refresh_css(animate=False)
        await pilot.pause()
        observe()

        # Removed declarations must disappear, including an empty component.
        copied.source.clear()
        copied.add_source("ComponentProbe { color: white; }")
        copied.set_variables(app.get_css_variables())
        copied.reparse()
        copied.apply(probe)
        observe()
        assert not probe.get_component_styles("probe-part").get_rules()
        assert not probe.get_component_styles("probe-empty").get_rules()
    return observations, changed_nodes


@pytest.mark.asyncio
async def test_component_css_matches_native_focus_themes_reload_and_removed_rules():
    native, native_replacements = await component_observations(Stylesheet)
    bounded, bounded_replacements = await component_observations(ComponentStylesheet)
    assert bounded == native
    assert native_replacements > 0, "Control must exercise native component allocation"
    assert bounded_replacements == 0, "Focus/theme/reload must reuse owned component graphs"


def test_copy_preserves_variables_and_independent_sources():
    stylesheet = ComponentStylesheet(variables={"accent": "red"})
    stylesheet.add_source("ComponentProbe .probe-part { color: $accent; }")
    copied = stylesheet.copy()
    copied.set_variables({"accent": "blue"})
    stylesheet.parse()
    copied.parse()
    assert stylesheet.rules[0].styles.color != copied.rules[0].styles.color
    copied.source.clear()
    assert stylesheet.source
