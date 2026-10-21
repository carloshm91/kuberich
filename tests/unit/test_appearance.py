"""Real color/contrast, bounded files and effective preference decisions."""

from dataclasses import replace

import pytest

from kuberich.config.schema import ConfigDocument, parse_document
from kuberich.domain.appearance import (
    Appearance,
    contrast,
    effective_theme,
    parse_appearance,
    theme_name,
)
from kuberich.errors import AppError
from kuberich.ui.theme_catalog import BUILTINS, appearance_from, invert_theme, themes_for

PALETTE = {"primary": "#5fd7ff", "foreground": "#ffffff", "background": "#000000"}


def test_custom_palette_roundtrip_conversion_and_effective_precedence():
    raw = {
        "themes": {"ocean": {**PALETTE, "dark": False}},
        "contexts": {"demo-lab": "ocean"},
        "check_updates": True,
    }
    value = parse_appearance(raw, BUILTINS)
    assert parse_appearance(value.mapping(), BUILTINS) == value
    assert parse_appearance({}, BUILTINS) == Appearance()
    assert parse_appearance({"contexts": {"demo": "ocean"}}).contexts == (("demo", "ocean"),)
    assert theme_name("ocean") == "ocean" and contrast("#000000", "#ffffff") == 21
    converted = themes_for(value)
    assert converted[-1].name == "ocean" and not converted[-1].dark
    assert converted[-1].primary == PALETTE["primary"]
    names = {*BUILTINS, "ocean"}
    for context, override, expected in [
        ("demo-lab", None, "ocean"),
        ("other", None, "textual-dark"),
        (None, None, "textual-dark"),
        ("demo-lab", "k9s", "k9s"),
    ]:
        assert effective_theme("textual-dark", value, context, override, names) == (expected, False)
    assert effective_theme("missing", value, None, None, names) == ("k9s", True)
    document = parse_document({"schema_version": 1, "appearance": raw, "opaque": "retained"})
    assert document.extensions == {"appearance": raw} and document.unknown == {"opaque": "retained"}
    assert appearance_from(document) == value
    assert document.to_mapping()["appearance"] == raw
    assert "demo-lab" not in repr(document)
    assert appearance_from(ConfigDocument()) == Appearance()


@pytest.mark.parametrize("value", [None, 1, "", "two words", "a" * 65, "é", "esc\x1b"])
def test_theme_identifiers_are_bounded_ascii(value):
    with pytest.raises(AppError):
        theme_name(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"wrong": 1},
        {"schema_version": True},
        {"schema_version": 2},
        {"check_updates": "yes"},
        {"themes": []},
        {"themes": {str(n): {} for n in range(33)}},
        {"contexts": []},
        {"contexts": {str(n): "k9s" for n in range(129)}},
        {"themes": {"k9s": PALETTE}},
        {"themes": {"demo": []}},
        {"themes": {"demo": {"primary": "#ffffff"}}},
        {"themes": {"demo": {**PALETTE, "css": "display:none"}}},
        {"themes": {"demo": {**PALETTE, "dark": 1}}},
        {"themes": {"demo": {**PALETTE, "foreground": "red"}}},
        {"themes": {"demo": {**PALETTE, "foreground": None}}},
        {"themes": {"demo": {**PALETTE, "foreground": "#010101"}}},
        {"themes": {"demo": {**PALETTE, "surface": "#ffffff"}}},
        {"themes": {"demo": {**PALETTE, "panel": "#ffffff"}}},
        {"themes": {"demo": {**PALETTE, "accent": "#000000"}}},
        {"contexts": {1: "k9s"}},
        {"contexts": {"": "k9s"}},
        {"contexts": {"a" * 254: "k9s"}},
        {"contexts": {"bad\x1b": "k9s"}},
        {"contexts": {"bad\x80": "k9s"}},
        {"contexts": {"demo": "missing"}},
        {"contexts": {"demo": 1}},
        {"full_gvr_titles": "yes"},
        {"themes": {"demo": {**PALETTE, "foreground": "default"}}},
        {"themes": {"demo": {**PALETTE, "primary": "default"}}},
        {"themes": {"demo": {**PALETTE, "background": "Default"}}},
        {"themes": {"demo": {**PALETTE, "background": "default", "surface": "#ffffff"}}},
    ],
)
def test_invalid_appearance_is_actionable_and_original_values_are_unmodified(value):
    before = repr(value)
    with pytest.raises(AppError):
        parse_appearance(value, BUILTINS)
    assert repr(value) == before


def test_all_supported_colors_convert_without_css_or_loss():
    raw = {
        "themes": {
            "demo": {
                **PALETTE,
                "secondary": "#eeeeee",
                "accent": "#dddddd",
                "warning": "#ffff00",
                "error": "#ff8080",
                "success": "#80ff80",
                "surface": "#111111",
                "panel": "#222222",
            }
        }
    }
    theme = themes_for(parse_appearance(raw, BUILTINS))[-1]
    assert theme.panel == "#222222" and theme.warning == "#ffff00"
    assert parse_document({}).extensions == {}
    with pytest.raises(AppError, match="Unknown preference"):
        from kuberich.config.schema import resolve_settings

        resolve_settings(
            replace(ConfigDocument(), extensions={"appearance": {}}), {}, {"appearance": {}}
        )


def test_transparent_surfaces_use_the_terminal_background():
    raw = {
        "themes": {
            "glass": {**PALETTE, "background": "default", "surface": "default", "accent": "#111111"}
        },
        "full_gvr_titles": True,
    }
    value = parse_appearance(raw, BUILTINS)
    assert value.full_gvr_titles and parse_appearance(value.mapping(), BUILTINS) == value
    assert "full_gvr_titles" not in Appearance().mapping()
    theme = themes_for(value)[-1]
    assert theme.ansi and theme.background == theme.surface == theme.panel == "ansi_default"
    assert not themes_for(parse_appearance({"themes": {"solid": PALETTE}}, BUILTINS))[-1].ansi
    inverted = invert_theme(theme)
    assert inverted.background == "#ffffff" and not inverted.ansi


def test_inversion_repairs_text_surfaces_and_accents_without_mutating_base_colors():
    from kuberich.domain.appearance import COLORS, invert_palette

    base = {key: "#ffffff" for key in COLORS}
    base.update(background="#000000", surface="#000000", panel="#000000")
    original = base.copy()
    inverted = invert_palette(base)
    assert inverted["foreground"] == "#000000" and inverted["background"] == "#ffffff"
    assert base == original
    repaired = invert_palette(
        {
            **base,
            "foreground": "#888888",
            "surface": "#ffffff",
            "panel": "#ffffff",
            "primary": "#333333",
        }
    )
    for surface in ("background", "surface", "panel"):
        assert contrast(repaired["foreground"], repaired[surface]) >= 4.5
    assert contrast(repaired["primary"], repaired["background"]) >= 3


def test_each_framework_theme_can_be_inverted_as_an_owned_copy():
    from textual.theme import BUILTIN_THEMES

    from kuberich.ui.theme_catalog import invert_theme

    original = [
        (theme.name, theme.foreground, theme.background, theme.dark)
        for theme in BUILTIN_THEMES.values()
    ]
    for theme in (*BUILTIN_THEMES.values(), *themes_for(Appearance())):
        inverted = invert_theme(theme)
        assert inverted.name == theme.name and inverted.dark != theme.dark
        assert contrast(inverted.foreground, inverted.background) >= 4.5
    assert [
        (theme.name, theme.foreground, theme.background, theme.dark)
        for theme in BUILTIN_THEMES.values()
    ] == original


def test_cursor_text_keeps_contrast_in_custom_and_monochrome_palettes():
    for primary, foreground, background in [
        ("#5fd7ff", "#ffffff", "#000000"),
        ("#000099", "#000000", "#ffffff"),
    ]:
        value = parse_appearance(
            {
                "themes": {
                    "demo": {"primary": primary, "foreground": foreground, "background": background}
                }
            },
            BUILTINS,
        )
        for theme in themes_for(value):
            assert (
                contrast(
                    theme.variables["block-cursor-background"],
                    theme.variables["block-cursor-foreground"],
                )
                >= 4.5
            )
