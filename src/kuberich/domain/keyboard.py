"""Bounded additional navigation keys, validated against each actual owner."""

import re

from kuberich.errors import AppError

type KeyOverrides = tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

TABLE_KEYS = (
    ("down", "j"),
    ("up", "k"),
    ("first", "g"),
    ("last", "G"),
    ("page_up", "ctrl+b"),
    ("page_down", "ctrl+f"),
    ("half_up", "ctrl+u"),
    ("half_down", "J"),
    ("left", "h"),
    ("right", "alt+l"),
)
SORT_KEYS = (("sort", "s"), ("reverse_sort", "S"))
LOG_KEYS = tuple(
    (name, "ctrl+d" if name == "half_down" else "l" if name == "right" else key)
    for name, key in TABLE_KEYS
)
TABLE_PROFILES = (
    "table",
    "resources",
    "namespaces",
    "contexts",
    "containers",
    "data",
    "themes",
    "forwards",
    "sources",
)
PROFILES = (*TABLE_PROFILES, "logs")
SORT_PROFILES = frozenset({"resources", "namespaces"})
_SAFETY = frozenset(
    {
        "escape",
        "q",
        "ctrl+q",
        "ctrl+c",
        "ctrl+p",
        "ctrl+z",
        "ctrl+y",
        "enter",
        "tab",
        "shift+tab",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end",
        "pageup",
        "pagedown",
        "ctrl+home",
        "ctrl+end",
        "colon",
        "slash",
        "question_mark",
        "f1",
        "f2",
        "f3",
        "f4",
        "f5",
    }
)
_RESOURCE = frozenset({"c", "n", "l", "L", "x", "F", "d", "y", "e", "E", "v", "r", "i", "ctrl+d"})
FIXED_KEYS = {
    "table": _SAFETY,
    "resources": _SAFETY | _RESOURCE,
    "namespaces": _SAFETY | _RESOURCE | {"0"},
    "contexts": _SAFETY | _RESOURCE,
    "containers": _SAFETY | {"s", "x", "a", "u", "d", "l"},
    "data": _SAFETY | {"r", "R", "x"},
    "themes": _SAFETY,
    "forwards": _SAFETY | {"s"},
    "sources": _SAFETY | {"space", "r", "a"},
    "logs": _SAFETY
    | {"c", "v", "o", "p", "f", "t", "w", "L", "C", "m", "z", "n", "N", "ctrl+s", "s", "J"},
}


def navigation_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:[A-Za-z0-9]|ctrl\+[a-z]|alt\+[A-Za-z0-9])", value) is None
    ):
        raise AppError(
            "Navigation keys use one ASCII letter/digit or ctrl+/alt+ plus a letter; chords and native fallback keys are reserved."
        )
    if value in {"ctrl+m", "ctrl+j", "ctrl+i", "ctrl+h"}:
        raise AppError("This control key shares Enter, Tab or Backspace in common terminals.")
    return value


def keys_for(overrides: KeyOverrides, profile: str) -> dict[str, str]:
    if profile not in PROFILES:
        raise AppError("Unknown navigation profile.")
    defaults = dict(LOG_KEYS if profile == "logs" else TABLE_KEYS)
    if profile in SORT_PROFILES:
        defaults.update(SORT_KEYS)
    configured = dict(overrides)
    if profile != "logs":
        defaults.update(
            (name, key) for name, key in configured.get("table", ()) if name in defaults
        )
    defaults.update(configured.get(profile, ()))
    return defaults


def parse_keys(value: object) -> KeyOverrides:
    if not isinstance(value, dict) or value.keys() - set(PROFILES):
        raise AppError("keys must contain only documented navigation profiles.")
    result = []
    for profile, fields in value.items():
        allowed = dict(LOG_KEYS if profile == "logs" else TABLE_KEYS)
        if profile in SORT_PROFILES or profile == "table":
            allowed.update(SORT_KEYS)
        if not isinstance(fields, dict) or fields.keys() - allowed.keys():
            raise AppError("Unknown navigation action for this profile.")
        result.append(
            (
                str(profile),
                tuple(sorted((str(name), navigation_key(key)) for name, key in fields.items())),
            )
        )
    parsed = tuple(sorted(result))
    for profile in PROFILES:
        keys = tuple(keys_for(parsed, profile).values())
        if len(set(keys)) != len(keys):
            raise AppError(
                f"Duplicate effective navigation keys in {profile}; working defaults are retained."
            )
        if set(keys) & FIXED_KEYS[profile]:
            raise AppError(
                f"Navigation conflicts with a fixed action in {profile}; choose a different key."
            )
    return parsed


def effective_keymap(overrides: KeyOverrides) -> tuple[tuple[str, str], ...]:
    return tuple(
        (f"{profile}.{action}", key)
        for profile in PROFILES
        for action, key in keys_for(overrides, profile).items()
    )


def key_label(key: str) -> str:
    parts = key.split("+")
    return key if len(parts) == 1 else parts[0].capitalize() + "+" + parts[1].upper()


def key_mapping(overrides: KeyOverrides) -> dict[str, object]:
    return {profile: dict(fields) for profile, fields in overrides}
