"""Native CSS semantics with bounded, per-owner reuse of exact variable snapshots."""

import gc
import weakref
from dataclasses import FrozenInstanceError

import pytest
from textual.cache import LRUCache
from textual.css.stylesheet import Stylesheet, StylesheetParseError

from kuberich.ui import style_cache
from kuberich.ui.style_cache import ComponentStylesheet


def snapshot(sheet):
    return [(rule.css, rule.is_default_rules, rule.tie_breaker) for rule in sheet.rules]


def test_revisiting_themes_reuses_parses_and_preserves_native_rules(monkeypatch):
    from textual.css import stylesheet as module

    original = module.parse
    calls = []

    def observed(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "parse", observed)
    owned = ComponentStylesheet(variables={"accent": "red"})
    native = Stylesheet(variables={"accent": "red"})
    for sheet in (owned, native):
        sheet.add_source("Static { color: $accent; }", ("owned", "colors"))
    for index, color in enumerate(("red", "blue", "red", "blue")):
        owned.set_variables({"accent": color})
        before = len(calls)
        owned.reparse()
        assert len(calls) - before == (1 if index < 2 else 0)
        native.set_variables({"accent": color})
        before = len(calls)
        native.reparse()
        assert len(calls) - before == 1
        assert snapshot(owned) == snapshot(native)
        assert owned.rules[0].styles.node is None


def test_source_content_order_scope_priority_and_removal_remain_native():
    owned, native = ComponentStylesheet(), Stylesheet()
    for sheet in (owned, native):
        sheet.add_source("Static { color: red; }", ("owned", "first"), True, 1, "Screen")
        sheet.add_source("Static { color: blue; }", ("owned", "second"), False, 2)
        sheet.reparse()
    assert snapshot(owned) == snapshot(native)
    for sheet in (owned, native):
        sheet.add_source("Static { color: green; width: 17; }", ("owned", "first"), False, 3)
        sheet.reparse()
    assert snapshot(owned) == snapshot(native)
    for sheet in (owned, native):
        del sheet.source["owned", "second"]
        sheet.reparse()
    assert snapshot(owned) == snapshot(native) and len(owned.rules) == 1
    assert owned.rules[0].styles.width.value == 17


def test_unknown_variable_changes_do_not_reuse_another_variables_rules():
    owned, native = ComponentStylesheet(), Stylesheet()
    for sheet in (owned, native):
        sheet.add_source("Static { color: $accent; }", ("owned", "vars"))
        sheet.set_variables({"accent": "red", "unused": "one"})
        sheet.reparse()
        sheet.set_variables({"accent": "green", "unused": "two"})
        sheet.reparse()
    assert snapshot(owned) == snapshot(native)
    assert owned.rules[0].styles.color.g == 128


def test_errors_keep_original_rules_and_recovery_is_not_hidden_by_cache():
    owned, native = ComponentStylesheet(), Stylesheet()
    for sheet in (owned, native):
        sheet.add_source("Static { color: red; }", ("owned", "valid"))
        sheet.reparse()
        before = sheet.rules
        publication = owned.parse_state
        sheet.add_source("Static { unknown-property: 1; }", ("owned", "bad"))
        with pytest.raises(StylesheetParseError):
            sheet.reparse()
        if sheet is native:
            # The pinned native negative control owns its framework internals.
            assert native._rules is before
            assert "Static { unknown-property: 1; }" in native._invalid_css
        else:
            assert owned.parse_state.published_digest == publication.published_digest
            assert owned.parse_state.rule_count == len(before)
            assert owned.parse_state.invalid_source_count == 1
        with pytest.raises(StylesheetParseError):
            sheet.reparse()
        sheet.add_source("Static { width: 5; }", ("owned", "bad"))
        sheet.set_variables({})
        sheet.reparse()
    assert snapshot(owned) == snapshot(native)


def test_cache_is_bounded_and_copies_and_other_apps_have_independent_owners(monkeypatch):
    created = []

    class ObservedCache(LRUCache):
        def __init__(self, capacity):
            super().__init__(capacity)
            created.append(weakref.ref(self))

    monkeypatch.setattr(style_cache, "LRUCache", ObservedCache)
    sheet = ComponentStylesheet()
    sheet.add_source("Static { color: $accent; }", ("owned", "vars"))
    for index in range(8):
        sheet.set_variables({"accent": f"#{index:06x}"})
        sheet.reparse()
    gc.collect()
    original = tuple(reference() for reference in created if reference() is not None)
    assert len(original) == len(sheet.parse_state.retained_cache_sizes) == 3
    marker = len(created)
    copied = sheet.copy()
    copied_caches = tuple(reference() for reference in created[marker:] if reference() is not None)
    assert len(copied_caches) == len(copied.parse_state.retained_cache_sizes) == 1
    assert all(
        cache is not original_cache for cache in copied_caches for original_cache in original
    )
    copied.reparse()
    assert snapshot(copied) == snapshot(sheet)
    assert copied.rules[0] is not sheet.rules[0]
    independent = ComponentStylesheet()
    independent_cache = created[-1]()
    assert independent_cache is not None
    assert all(independent_cache is not cache for cache in (*original, *copied_caches))
    assert independent.parse_state.retained_cache_sizes == (0,)
    for index in range(70):
        sheet.add_source(f".owned-{index} {{ width: {index + 1}; }}", ("bounded", str(index)))
    sheet.reparse()
    assert len(sheet.rules) == 71
    assert all(size <= 64 for size in sheet.parse_state.retained_cache_sizes)
    assert all(cache.maxsize == 64 for cache in (*original, *copied_caches, independent_cache))


def test_parse_state_is_frozen_and_observes_native_parse_and_copy_without_mutable_rules():
    sheet = ComponentStylesheet()
    empty = sheet.parse_state
    assert empty.rule_count == empty.invalid_source_count == 0
    sheet.add_source("Static { color: red; }", ("owned", "public-state"))
    assert sheet.parse_state == empty  # Observation does not eagerly parse.
    sheet.parse()
    published = sheet.parse_state
    assert published.rule_count == 1 and published.published_digest != empty.published_digest
    with pytest.raises(FrozenInstanceError):
        published.rule_count = 100
    copied = sheet.copy()
    copied.reparse()
    assert copied.parse_state == published
    copied.add_source("Static { color: blue; }", ("owned", "public-state"))
    copied.reparse()
    assert copied.parse_state.published_digest != published.published_digest
    assert sheet.parse_state == published
