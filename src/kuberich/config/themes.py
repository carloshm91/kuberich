"""Built-in theme names and offline appearance validation without importing Textual."""

from kuberich.config.schema import ConfigDocument
from kuberich.domain.appearance import Appearance, parse_appearance

# Pinned Textual 8.2.8 built-in theme IDs; CI parity tests verify this set against Textual.
TEXTUAL_BUILTIN_THEMES = frozenset(
    {
        "textual-dark",
        "textual-light",
        "nord",
        "gruvbox",
        "catppuccin-mocha",
        "dracula",
        "tokyo-night",
        "monokai",
        "flexoki",
        "catppuccin-latte",
        "catppuccin-frappe",
        "catppuccin-macchiato",
        "solarized-light",
        "solarized-dark",
        "rose-pine",
        "rose-pine-moon",
        "rose-pine-dawn",
        "atom-one-dark",
        "atom-one-light",
        "ansi-dark",
        "ansi-light",
    }
)
BUILTINS = frozenset({*TEXTUAL_BUILTIN_THEMES, "k9s", "kuberich-mono"})


def appearance_from(document: ConfigDocument) -> Appearance:
    return parse_appearance(document.extensions.get("appearance", {}), BUILTINS)
