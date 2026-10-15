"""Textual conversion stays at the UI boundary; stored values contain no CSS."""

from textual.theme import BUILTIN_THEMES, Theme

from kuberich.config.schema import ConfigDocument
from kuberich.domain.appearance import Appearance, contrast, parse_appearance
from kuberich.ui.chrome import K9S_THEME

MONO_THEME = Theme(
    name="kuberich-mono",
    primary="#ffffff",
    foreground="#ffffff",
    background="#000000",
    secondary="#ffffff",
    accent="#ffffff",
    warning="#ffffff",
    error="#ffffff",
    success="#ffffff",
    surface="#000000",
    panel="#000000",
    text_alpha=1.0,
    variables={
        "text": "#ffffff",
        "text-muted": "#ffffff",
        "border": "#ffffff",
        "border-blurred": "#ffffff",
        "block-cursor-background": "#ffffff",
        "block-cursor-foreground": "#000000",
        "block-cursor-text-style": "none",
    },
)
BUILTINS = frozenset({*BUILTIN_THEMES, "k9s", "kuberich-mono"})


def appearance_from(document: ConfigDocument) -> Appearance:
    return parse_appearance(document.extensions.get("appearance", {}), BUILTINS)


def themes_for(appearance: Appearance) -> tuple[Theme, ...]:
    custom = []
    for definition in appearance.themes:
        colors = dict(definition.colors)
        custom.append(
            Theme(
                name=definition.name,
                primary=colors["primary"],
                foreground=colors["foreground"],
                background=colors["background"],
                secondary=colors.get("secondary"),
                accent=colors.get("accent"),
                warning=colors.get("warning"),
                error=colors.get("error"),
                success=colors.get("success"),
                surface=colors.get("surface", colors["background"]),
                panel=colors.get("panel", colors["background"]),
                dark=definition.dark,
                text_alpha=1.0,
                variables={
                    "text": colors["foreground"],
                    "text-muted": colors["foreground"],
                    "block-cursor-background": colors["primary"],
                    "block-cursor-foreground": max(
                        ("#000000", "#ffffff"),
                        key=lambda color: contrast(color, colors["primary"]),
                    ),
                    "block-cursor-text-style": "none",
                },
            )
        )
    return (K9S_THEME, MONO_THEME, *custom)


def invert_theme(theme: Theme) -> Theme:
    """Resolve native color names once; an inverted session uses explicit RGB."""
    from textual.color import Color

    from kuberich.domain.appearance import COLORS, invert_palette

    palette = theme.to_color_system().generate()
    resolved = {}
    for key in COLORS:
        color = Color.parse(palette[key])
        if color.ansi == -1:
            background = key in {"background", "surface", "panel"}
            resolved[key] = "#000000" if background == theme.dark else "#ffffff"
        else:
            resolved[key] = "#" + "".join(f"{channel:02x}" for channel in color.rgb)
    colors = invert_palette(resolved)
    return Theme(
        name=theme.name,
        primary=colors["primary"],
        secondary=colors["secondary"],
        accent=colors["accent"],
        foreground=colors["foreground"],
        background=colors["background"],
        surface=colors["surface"],
        panel=colors["panel"],
        warning=colors["warning"],
        error=colors["error"],
        success=colors["success"],
        dark=not theme.dark,
        text_alpha=1.0,
        variables={
            "text": colors["foreground"],
            "text-muted": colors["foreground"],
            "block-cursor-background": colors["foreground"],
            "block-cursor-foreground": colors["background"],
            "border": colors["primary"],
            "border-blurred": colors["primary"],
            "input-selection-background": colors["secondary"],
            "input-cursor-background": colors["foreground"],
        },
    )
