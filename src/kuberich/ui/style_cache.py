"""Cache immutable background styles without retaining removed widget renderers."""

from functools import lru_cache

from textual._styles_cache import StylesCache
from textual.color import Color
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
