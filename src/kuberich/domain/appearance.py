"""Validated appearance values and deterministic theme precedence, without widgets."""

import re
from collections.abc import Collection
from dataclasses import dataclass

from kuberich.errors import AppError

COLORS = frozenset(
    {
        "primary",
        "secondary",
        "accent",
        "foreground",
        "background",
        "surface",
        "panel",
        "warning",
        "error",
        "success",
    }
)


def theme_name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z][\w-]{0,63}", value, re.ASCII) is None:
        raise AppError("Theme names must be 1-64 ASCII letters, digits, underscores or hyphens.")
    return value


def _luminance(color: str) -> float:
    values = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values
    ]
    return sum(
        channel * weight for channel, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True)
    )


def contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@dataclass(frozen=True)
class CustomTheme:
    name: str
    colors: tuple[tuple[str, str], ...]
    dark: bool = True

    def mapping(self) -> dict[str, object]:
        return {**dict(self.colors), "dark": self.dark}


@dataclass(frozen=True)
class Appearance:
    themes: tuple[CustomTheme, ...] = ()
    contexts: tuple[tuple[str, str], ...] = ()
    check_updates: bool = False

    def mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "themes": {theme.name: theme.mapping() for theme in self.themes},
            "contexts": dict(self.contexts),
            "check_updates": self.check_updates,
        }


def parse_appearance(value: object, builtins: Collection[str] = ()) -> Appearance:
    if not isinstance(value, dict) or value.keys() - {
        "schema_version",
        "themes",
        "contexts",
        "check_updates",
    }:
        raise AppError(
            "appearance must contain only schema_version, themes, contexts and check_updates."
        )
    if type(value.get("schema_version", 1)) is not int or value.get("schema_version", 1) != 1:
        raise AppError("Unsupported appearance.schema_version; use version 1.")
    enabled = value.get("check_updates", False)
    themes, contexts = value.get("themes", {}), value.get("contexts", {})
    if type(enabled) is not bool:
        raise AppError("appearance.check_updates must be true or false.")
    if (
        not isinstance(themes, dict)
        or len(themes) > 32
        or not isinstance(contexts, dict)
        or len(contexts) > 128
    ):
        raise AppError("Appearance allows at most 32 themes and 128 context preferences.")
    parsed = []
    for name, fields in themes.items():
        name = theme_name(name)
        if name in builtins:
            raise AppError("Custom themes must not replace built-in theme names.")
        if (
            not isinstance(fields, dict)
            or fields.keys() - COLORS - {"dark"}
            or not {"primary", "foreground", "background"} <= fields.keys()
        ):
            raise AppError(
                "Custom themes require primary, foreground and background; use documented color fields."
            )
        dark = fields.get("dark", True)
        if type(dark) is not bool:
            raise AppError("Custom theme dark must be true or false.")
        colors = {key: color for key, color in fields.items() if key != "dark"}
        if any(
            not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None
            for color in colors.values()
        ):
            raise AppError(
                "Theme colors must be quoted six-digit hexadecimal values, such as '#ffffff'."
            )
        foreground = str(colors["foreground"])
        if any(
            contrast(foreground, str(colors.get(surface, colors["background"]))) < 4.5
            for surface in ("background", "surface", "panel")
        ):
            raise AppError(
                "Theme foreground needs at least 4.5:1 contrast against background, surface and panel."
            )
        if any(
            contrast(str(color), str(colors["background"])) < 3
            for key, color in colors.items()
            if key in {"primary", "accent", "warning", "error", "success"}
        ):
            raise AppError(
                "Theme primary, accent and status colors need at least 3:1 background contrast."
            )
        parsed.append(
            CustomTheme(
                name, tuple(sorted((key, str(color)) for key, color in colors.items())), dark
            )
        )
    scoped = []
    for context, name in contexts.items():
        if (
            not isinstance(context, str)
            or not 1 <= len(context) <= 253
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in context)
        ):
            raise AppError("Appearance context names must be bounded text without controls.")
        scoped.append((context, theme_name(name)))
    available = set(builtins) | {theme.name for theme in parsed}
    if builtins and any(name not in available for _, name in scoped):
        raise AppError(
            "A context preference selects an unavailable theme; choose a registered theme."
        )
    return Appearance(tuple(parsed), tuple(sorted(scoped)), enabled)


def effective_theme(
    global_theme: str,
    appearance: Appearance,
    context: str | None,
    override: str | None,
    available: Collection[str],
) -> tuple[str, bool]:
    chosen = override or dict(appearance.contexts).get(context or "", global_theme)
    return (chosen, False) if chosen in available else ("k9s", True)


def invert_palette(colors: dict[str, str]) -> dict[str, str]:
    """Reverse resolved RGB colors, repairing text/accent contrast where needed."""
    inverted = {
        key: "#" + "".join(f"{255 - int(color[index : index + 2], 16):02x}" for index in (1, 3, 5))
        for key, color in colors.items()
    }
    background = inverted["background"]
    foreground = inverted["foreground"]
    if contrast(foreground, background) < 4.5:
        foreground = max(("#000000", "#ffffff"), key=lambda color: contrast(color, background))
        inverted["foreground"] = foreground
    for surface in ("surface", "panel"):
        if contrast(foreground, inverted[surface]) < 4.5:
            inverted[surface] = background
    for role in ("primary", "secondary", "accent", "warning", "error", "success"):
        if contrast(inverted[role], background) < 3:
            inverted[role] = foreground
    return inverted
