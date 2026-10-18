"""Native CSS semantics with bounded, per-owner reuse of exact variable snapshots."""

import pytest
from textual.css.stylesheet import Stylesheet, StylesheetParseError

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
        before = sheet._rules
        sheet.add_source("Static { unknown-property: 1; }", ("owned", "bad"))
        with pytest.raises(StylesheetParseError):
            sheet.reparse()
        assert sheet._rules is before
        assert "Static { unknown-property: 1; }" in sheet._invalid_css
        with pytest.raises(StylesheetParseError):
            sheet.reparse()
        sheet.add_source("Static { width: 5; }", ("owned", "bad"))
        sheet.set_variables({})
        sheet.reparse()
    assert snapshot(owned) == snapshot(native)


def test_cache_is_bounded_and_copies_and_other_apps_have_independent_owners():
    sheet = ComponentStylesheet()
    sheet.add_source("Static { color: $accent; }", ("owned", "vars"))
    for index in range(8):
        sheet.set_variables({"accent": f"#{index:06x}"})
        sheet.reparse()
    assert len(sheet._variable_caches) == 3
    copied = sheet.copy()
    assert copied._variable_caches is not sheet._variable_caches
    assert len(copied._variable_caches) == 1
    copied.reparse()
    assert snapshot(copied) == snapshot(sheet)
    assert copied.rules[0] is not sheet.rules[0]
    independent = ComponentStylesheet()
    assert independent._variable_caches is not sheet._variable_caches
    for index in range(70):
        sheet.add_source(f".owned-{index} {{ width: {index + 1}; }}", ("bounded", str(index)))
    sheet.reparse()
    assert len(sheet.rules) == 71
    assert all(len(cache) <= 64 for cache in sheet._variable_caches.values())
