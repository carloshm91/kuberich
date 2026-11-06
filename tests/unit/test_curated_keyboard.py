"""Events controls and inspector Links cannot be shadowed by navigation overrides."""

import pytest

from kuberich.domain.keyboard import effective_keymap, keys_for, parse_keys
from kuberich.errors import AppError
from kuberich.ui.keybindings import navigation_help


def test_events_preserves_vim_navigation_sorting_and_documents_local_controls():
    keys = keys_for((), "events")
    assert keys["first"] == "g" and keys["last"] == "G"
    assert keys["sort"] == "s" and keys["reverse_sort"] == "S"
    assert {"w", "t"}.isdisjoint(keys.values())
    assert "First row" in navigation_help(effective_keymap(()), "events")


@pytest.mark.parametrize("key", ["w", "t"])
def test_events_option_keys_remain_local_actions_even_with_common_overrides(key):
    with pytest.raises(AppError, match=r"conflicts.*events"):
        parse_keys({"events": {"first": key}})
    overrides = parse_keys({"table": {"first": key}, "events": {"first": "b"}})
    assert keys_for(overrides, "events")["first"] == "b"


def test_document_horizontal_scroll_and_inspection_links_keep_distinct_keys():
    assert keys_for((), "text")["right"] == "l"
    with pytest.raises(AppError, match=r"conflicts.*text"):
        parse_keys({"text": {"first": "L"}})
