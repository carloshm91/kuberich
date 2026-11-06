"""Inspector navigation stays configurable without shadowing disclosure or section actions."""

import pytest

from kuberich.domain.keyboard import effective_keymap, key_mapping, keys_for, parse_keys
from kuberich.errors import AppError


def test_inspector_has_an_independent_roundtrippable_table_navigation_profile():
    parsed = parse_keys({"container-inspection": {"down": "b"}})
    assert parse_keys(key_mapping(parsed)) == parsed
    assert keys_for(parsed, "container-inspection")["down"] == "b"
    assert keys_for(parsed, "containers")["down"] == "j"
    assert dict(effective_keymap(parsed))["container-inspection.down"] == "b"


@pytest.mark.parametrize("key", ["e", "i", "s", "r", "R", "ctrl+y"])
def test_inspector_sections_disclosure_reload_and_copy_cannot_be_navigation_keys(key):
    with pytest.raises(AppError, match="fixed action"):
        parse_keys({"container-inspection": {"down": key}})


def test_container_environment_entry_key_cannot_be_shadowed_by_navigation():
    with pytest.raises(AppError, match="fixed action"):
        parse_keys({"containers": {"down": "e"}})
