"""Cache immutable background styles without retaining removed widget renderers."""

from functools import lru_cache
from typing import Self

from textual._styles_cache import StylesCache
from textual.color import Color
from textual.css.stylesheet import Stylesheet
from textual.dom import DOMNode
from textual.style import Style


class ColorStylesCache(StylesCache):
    """Keep native rendering; color memoization must not own the line cache.

    Textual 8.2.8 includes the renderer instance in this color-only cache's key
    (Textualize/textual#6665). The application installs this subclass only on its
    own registered widgets; other Textual applications remain untouched.
    """

    @staticmethod
    @lru_cache(maxsize=1024)
    def get_inner_outer(base_background: Color, background: Color) -> tuple[Style, Style]:
        return (
            Style(background=base_background + background),
            Style(background=base_background),
        )


class ComponentStylesheet(Stylesheet):
    """Reuse each widget's virtual component nodes during native CSS evaluation.

    Textual 8.2.8 recreates these cyclic DOM graphs on every style application,
    including focus and theme changes. Keep their lifetime with their owning
    widget, while recomputing selectors and clearing previous rules as native
    evaluation does. No global caches or garbage-collection policy are changed.
    """

    def copy(self) -> Self:
        stylesheet = type(self)(variables=self._variables.copy())
        stylesheet.source = self.source.copy()
        return stylesheet

    def _process_component_classes(self, node: DOMNode) -> None:
        components = node._get_component_classes()
        if not components:
            return
        previous = node._component_styles.copy()
        node._component_styles.clear()
        changed = False
        for component in sorted(components):
            old = previous.get(component)
            before = None if old is None else (old.base.get_rules(), old.inline.get_rules())
            virtual = None if old is None else old.node
            if virtual is None:
                virtual = DOMNode(classes=component)
            else:
                virtual.styles.base.reset()
                virtual.styles.inline.reset()
            virtual._attach(node)
            self.apply(virtual, animate=False)
            styles = virtual.styles
            changed |= before != (styles.base.get_rules(), styles.inline.get_rules())
            node._component_styles[component] = styles
        if changed:
            node.refresh()
