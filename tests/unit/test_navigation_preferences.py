"""Actual bounded preferences, per-owner keys, literal aliases and view migration."""

from dataclasses import replace

import pytest

from kuberich.config.navigation import (
    NavigationPreferences,
    navigation_from,
    parse_navigation,
    validate_resource_views,
)
from kuberich.config.schema import parse_document
from kuberich.domain.aliases import expand_alias, parse_aliases
from kuberich.domain.keyboard import (
    PROFILES,
    effective_keymap,
    key_label,
    key_mapping,
    keys_for,
    navigation_key,
    parse_keys,
)
from kuberich.domain.resource_preferences import (
    ColumnSpec,
    ViewSpec,
    applicable_view,
    column_text,
    field_key,
    parse_column_text,
    parse_view,
    printer_signature,
    resource_key,
)
from kuberich.domain.resources import ServerColumn
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import (
    RESERVED_COMMANDS,
    Command,
    CommandService,
    GenericResourceCommand,
    ScopedCommand,
    discovered_alias_names,
    suggestions,
)
from tests.unit.test_generic_commands import catalogue


def test_effective_profiles_use_common_then_owner_and_preserve_view_actions():
    overrides = parse_keys(
        {"table": {"down": "b"}, "resources": {"down": "j", "sort": "a"}, "logs": {"last": "K"}}
    )
    assert keys_for(overrides, "resources")["down"] == "j"
    assert keys_for(overrides, "resources")["sort"] == "a"
    assert keys_for(overrides, "containers")["down"] == "b"
    assert "sort" not in keys_for(overrides, "containers")
    assert keys_for(overrides, "logs")["down"] == "j"
    assert keys_for(overrides, "logs")["last"] == "K"
    assert keys_for(overrides, "logs")["half_down"] == "ctrl+d"
    assert keys_for(overrides, "resources")["right"] == "alt+l"
    assert keys_for(overrides, "logs")["right"] == "l"
    assert parse_keys(key_mapping(overrides)) == overrides
    mapping = dict(effective_keymap(overrides))
    assert mapping["resources.sort"] == "a" and mapping["logs.last"] == "K"
    assert {key.split(".")[0] for key in mapping} == set(PROFILES)
    assert key_label("g") == "g" and key_label("G") == "G"
    assert key_label("ctrl+b") == "Ctrl+B" and key_label("alt+l") == "Alt+L"
    assert navigation_key("1") == "1"
    assert parse_keys({}) == ()
    with pytest.raises(AppError, match="profile"):
        keys_for((), "absent")


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"unknown": {}},
        {"table": None},
        {"table": {"unknown": "b"}},
        {"contexts": {"sort": "a"}},
    ],
)
def test_invalid_profile_shapes_are_actionable(value):
    with pytest.raises(AppError):
        parse_keys(value)


@pytest.mark.parametrize(
    "key",
    [
        None,
        1,
        "",
        "gg",
        "g,G",
        "shift+g",
        "up",
        "ctrl+Q",
        "ctrl+m",
        "ctrl+j",
        "ctrl+i",
        "ctrl+h",
        "é",
        "\x1b",
        "ctrl+",
        "a b",
    ],
)
def test_chords_controls_and_native_fallback_aliases_are_rejected(key):
    with pytest.raises(AppError):
        navigation_key(key)


@pytest.mark.parametrize(
    "raw",
    [
        {"resources": {"first": "G"}},
        {"table": {"down": "a"}},
        {"resources": {"right": "l"}},
        {"resources": {"down": "n"}},
        {"logs": {"down": "n"}},
        {"resources": {"half_down": "ctrl+d"}},
        {"logs": {"up": "ctrl+y"}},
        {"data": {"down": "R"}},
        {"sources": {"down": "a"}},
        {"namespaces": {"first": "0"}},
        {"forwards": {"down": "s"}},
        {"themes": {"down": "q"}},
    ],
)
def test_effective_owner_conflicts_never_replace_real_actions(raw):
    with pytest.raises(AppError):
        parse_keys(raw)
    assert keys_for((), "resources")["first"] == "g"


def test_case_sensitive_keys_and_resource_only_overrides_remain_distinct():
    value = parse_keys({"resources": {"first": "H", "last": "K", "sort": "u"}})
    assert keys_for(value, "resources")["first"] == "H"
    assert keys_for(value, "containers")["first"] == "g"
    assert keys_for(value, "resources")["last"] == "K"


def test_literal_alias_chains_preserve_context_spaces_and_policy():
    aliases = parse_aliases(
        {"work": "pods", "production": "ctx demo lab", "indirect": "work", "erase": "delete"},
        RESERVED_COMMANDS,
    )
    service = CommandService(AccessPolicy(False), aliases)
    assert service.resolve(":indirect team") == ScopedCommand(Command.PODS, "team")
    assert service.resolve("PRODUCTION") == ScopedCommand(Command.CONTEXTS, "demo lab")
    assert service.resolve("erase") is Command.DELETE
    with pytest.raises(AppError):
        CommandService(AccessPolicy(True), aliases).resolve("erase")
    with pytest.raises(AppError, match="already supplies"):
        service.resolve("production other")
    assert expand_alias("", aliases) == ""
    assert expand_alias("unknown", aliases) == "unknown"
    assert parse_aliases({"hint": ":?"}, RESERVED_COMMANDS) == (("hint", "?"),)
    assert suggestions("ind", (), (), aliases=aliases) == ("indirect",)
    assert suggestions("work t", (), ("team",), aliases=aliases) == ("work team",)
    assert suggestions("production ", ("demo lab",), (), aliases=aliases) == ()
    assert suggestions("hint ", (), (), aliases=aliases) == ()


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {str(n): "po" for n in range(65)},
        {"Upper": "po"},
        {"a" * 33: "po"},
        {"x": None},
        {"x": ""},
        {"x": "a" * 257},
        {"x": "\npo"},
        {"x": "  "},
        {"x": "po;touch"},
        {"po": "ns"},
    ],
)
def test_alias_syntax_bounds_and_reserved_commands(value):
    with pytest.raises(AppError):
        parse_aliases(value, RESERVED_COMMANDS)


def test_recursive_excessive_and_ambiguous_aliases_are_rejected():
    for raw in ({"a": "a"}, {"a": "b", "b": "a"}, {"a": "b team", "b": "pods other"}):
        with pytest.raises(AppError):
            parse_aliases(raw, RESERVED_COMMANDS)
    chain = {f"a{n}": f"a{n + 1}" for n in range(8)}
    chain["a8"] = "pods"
    with pytest.raises(AppError, match="eight"):
        parse_aliases(chain)
    del chain["a0"]
    assert expand_alias("a1", parse_aliases(chain)) == "pods"
    with pytest.raises(AppError, match="256"):
        expand_alias("a " + "n" * 257, (("a", "pods"),))


def test_discovery_collisions_keep_explicit_resources_and_hide_invalid_completions():
    aliases = parse_aliases(
        {"wdg": "pods", "custom": "widgets.owned.example.test/v1"}, RESERVED_COMMANDS
    )
    service = CommandService(AccessPolicy(True), aliases)
    discovery = catalogue()
    assert "wdg" in discovered_alias_names(discovery)
    assert discovered_alias_names(None) == frozenset()
    with pytest.raises(AppError, match="conflicts"):
        service.resolve("wdg", discovery)
    assert suggestions("wd", (), (), discovery, aliases) == ()
    assert suggestions("wdg t", (), ("team",), discovery, aliases) == ()
    assert suggestions("resource wd", (), (), discovery, aliases) == ("resource wdg",)
    assert suggestions("custom t", (), ("team",), discovery, aliases) == ("custom team",)
    assert service.resolve("custom team", discovery) == GenericResourceCommand(
        "widgets", "owned.example.test", "v1", "team"
    )
    assert service.resolve("resource wdg", discovery).name == "widgets"


def test_width_alignment_roundtrip_and_namespace_identity_are_independent_of_sort():
    columns = parse_column_text("name:24:left ready::center age:8 restarts")
    assert column_text(columns) == "name:24:left ready::center age:8 restarts"
    view = ViewSpec(columns, "restarts", True)
    assert parse_view(view.mapping()) == view
    result = applicable_view(
        view, ("namespace", "name", "ready", "age", "restarts"), all_namespaces=True
    )
    assert result.columns[0] == ColumnSpec("namespace")
    assert result.sort == "restarts" and result.descending
    assert ColumnSpec("age").justify is None and columns[0].justify == "left"
    assert applicable_view(ViewSpec(), ("name", "age")).columns == (
        ColumnSpec("name"),
        ColumnSpec("age"),
    )
    assert applicable_view(view, ("name", "ready", "age", "restarts")).columns == columns
    assert parse_column_text("name:auto:right") == (ColumnSpec("name", alignment="right"),)
    assert field_key("storage-class") == "storage-class"
    assert resource_key("apps/v1/deployments") == "apps/v1/deployments"
    assert resource_key("v1/pods") == "v1/pods"


@pytest.mark.parametrize("value", [None, 3, "", "Name", "private.path", "x" * 65])
def test_invalid_field_keys_are_not_jsonpath_expressions(value):
    with pytest.raises(AppError):
        field_key(value)


@pytest.mark.parametrize(
    "value",
    [None, 3, "x" * 769, "pods", "core/v1/pods", "a/b/c/d", "apps//deployments", "Apps/v1/pods"],
)
def test_resource_preferences_are_explicit_canonical_gvrs(value):
    with pytest.raises(AppError):
        resource_key(value)


@pytest.mark.parametrize("width", [True, False, 0, -1, 257, "24", 2.5])
def test_invalid_widths_never_reach_native_columns(width):
    with pytest.raises(AppError):
        ColumnSpec("name", width)


@pytest.mark.parametrize("alignment", [None, [], "Right", "full", "\x1b[31m"])
def test_invalid_alignments_are_actionable(alignment):
    with pytest.raises(AppError):
        ColumnSpec("name", alignment=alignment)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"unknown": True},
        {"columns": []},
        {"columns": "name"},
        {"columns": ["name"]},
        {"columns": [{"key": "name", "extra": True}]},
        {"columns": [{"key": "name"}] * 2},
        {"columns": [{"key": "name"}] * 68},
        {"sort": "name"},
        {"sort": {"bad": 1}},
        {"sort": {"descending": "true"}},
        {"printer_signature": []},
        {"printer_signature": "wrong"},
    ],
)
def test_malformed_typed_views_retain_a_working_default(raw):
    with pytest.raises(AppError):
        parse_view(raw)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "name:0",
        "name:257",
        "name:abc",
        "name:24:right:extra",
        "name:٢٤",
        "name name",
        "n" * 8193,
    ],
)
def test_column_editor_grammar_is_bounded(text):
    with pytest.raises(AppError):
        parse_column_text(text)


def test_schema_evidence_prevents_positional_reinterpretation_but_not_description_edits():
    headers = (ServerColumn("Name", "string", "name"), ServerColumn("Load", "integer"))
    signature = printer_signature(headers)
    assert applicable_view(ViewSpec(), ("name", "c2"), signature=signature).columns == (
        ColumnSpec("name"),
        ColumnSpec("c2"),
    )
    assert signature == printer_signature(
        (replace(headers[0], description="new description"), headers[1])
    )
    assert signature != printer_signature(tuple(reversed(headers)))
    assert signature != printer_signature((headers[0], replace(headers[1], type="string")))
    view = ViewSpec((ColumnSpec("name"), ColumnSpec("c2")), "c2", printer_signature=signature)
    assert (
        applicable_view(view, ("namespace", "name", "c2", "age"), signature=signature).columns
        == view.columns
    )
    for bad, fields, evidence in (
        (replace(view, printer_signature=None), ("name", "c2"), signature),
        (view, ("name", "c2"), "0" * 64),
        (ViewSpec((ColumnSpec("age"),)), ("name", "age"), None),
        (ViewSpec((ColumnSpec("name"), ColumnSpec("missing"))), ("name", "age"), None),
        (ViewSpec(sort="missing"), ("name", "age"), None),
    ):
        with pytest.raises(AppError):
            applicable_view(bad, fields, signature=evidence)


def test_legacy_views_migrate_in_memory_without_overwriting_input():
    raw = {
        "keys": {"down": "b"},
        "aliases": {"work": "pods"},
        "views": {
            "v1/pods": {
                "columns": ["name", "age"],
                "widths": {"name": 24},
                "sort": "age",
                "descending": True,
            }
        },
        "contexts": {"demo lab": {"views": {"v1/pods": {"columns": ["name"]}}}},
    }
    nav = parse_navigation(raw, RESERVED_COMMANDS)
    assert nav.migrated and nav.views[0][1].columns[0].width == 24
    assert raw["views"]["v1/pods"]["columns"] == ["name", "age"]
    assert nav.mapping()["schema_version"] == 1
    assert parse_navigation(nav.mapping(), RESERVED_COMMANDS) == replace(nav, migrated=False)
    assert nav.choices("v1/pods", "demo lab") == (
        dict(nav.contexts)["demo lab"][0][1],
        nav.views[0][1],
    )
    assert nav.choices("v1/pods", None) == (nav.views[0][1],)
    assert nav.choices("v1/secrets", "absent") == ()
    current = NavigationPreferences().with_view("v1/pods", ViewSpec(sort="age"), None)
    scoped = current.with_view("v1/pods", ViewSpec(descending=True), "demo lab")
    assert scoped.choices("v1/pods", "demo lab") == (
        ViewSpec(descending=True),
        ViewSpec(sort="age"),
    )
    document = parse_document({"schema_version": 1, "navigation": nav.mapping(), "opaque": "kept"})
    assert navigation_from(document) == replace(nav, migrated=False)
    assert document.unknown == {"opaque": "kept"}
    assert navigation_from(parse_document({})) == NavigationPreferences()
    assert parse_view({}, legacy=True) == ViewSpec()


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"bad": 1},
        {"schema_version": True},
        {"schema_version": 2},
        {"views": []},
        {"views": {f"v1/r{n}": {} for n in range(129)}},
        {"contexts": []},
        {"contexts": {str(n): {} for n in range(129)}},
        {"contexts": {"": {}}},
        {"contexts": {"x" * 254: {}}},
        {"contexts": {"bad\n": {}}},
        {"contexts": {"demo": []}},
        {"contexts": {"demo": {"unknown": 1}}},
    ],
)
def test_invalid_navigation_sections_are_safe_for_ui_fallback(raw):
    with pytest.raises(AppError):
        parse_navigation(raw, RESERVED_COMMANDS)


@pytest.mark.parametrize(
    "raw",
    [
        {"columns": ["name"], "widths": []},
        {"columns": [{}]},
        {"columns": ["name"], "widths": {"age": 1}},
        {"widths": {"name": 1}},
    ],
)
def test_legacy_widths_cannot_silently_drop_unrelated_fields(raw):
    with pytest.raises(AppError):
        parse_view(raw, legacy=True)


def test_native_and_server_views_of_the_same_gvr_do_not_share_positional_fields():
    signature = "a" * 64
    server = {"columns": ["name", "c2"], "printer_signature": signature}
    migrated = parse_navigation({"views": {"v1/configmaps": server}})
    assert migrated.views[0][0] == "server:v1/configmaps"
    assert parse_navigation(migrated.mapping()).views == migrated.views
    with pytest.raises(AppError, match="server:"):
        parse_navigation(
            {
                "schema_version": 1,
                "views": {"v1/configmaps": parse_view(server, legacy=True).mapping()},
            }
        )
    with pytest.raises(AppError, match="duplicate"):
        parse_navigation({"views": {"v1/configmaps": server, "server:v1/configmaps": server}})
    assert resource_key("server:apps/v1/deployments") == "server:apps/v1/deployments"
    with pytest.raises(AppError):
        resource_key("x" * 776)


def test_offline_applicability_checks_native_fields_and_defers_discovery():
    native = NavigationPreferences().with_view("v1/pods", ViewSpec(sort="restarts"), None)
    native = native.with_view("apps/v1/deployments", ViewSpec(sort="desired"), "demo")
    native = native.with_view("server:owned.example.test/v1/widgets", ViewSpec(sort="c2"), None)
    validate_resource_views(native)
    validate_resource_views(NavigationPreferences())
    with pytest.raises(AppError, match="unavailable"):
        validate_resource_views(native.with_view("v1/pods", ViewSpec(sort="desired"), None))


@pytest.mark.parametrize("descending", [False, True])
def test_namespace_sort_keeps_unknown_dates_last_with_typed_age(descending):
    from datetime import UTC, datetime

    from kuberich.domain.namespaces import NamespaceRow, order_namespaces

    old = NamespaceRow("old", "z", "Active", datetime(2024, 1, 1, tzinfo=UTC))
    new = NamespaceRow("new", "a", "Terminating", datetime(2026, 1, 1, tzinfo=UTC))
    missing = NamespaceRow("missing", "m", "Unknown", None)
    rows = (old, missing, new)
    assert order_namespaces(rows, "age", descending) == (
        (old, new, missing) if descending else (new, old, missing)
    )
    assert order_namespaces(rows, "name", descending) == tuple(
        sorted(rows, key=lambda row: row.name, reverse=descending)
    )
    assert order_namespaces(rows, "status", descending) == tuple(
        sorted(rows, key=lambda row: row.status, reverse=descending)
    )
    with pytest.raises(AppError, match="Unknown"):
        order_namespaces(rows, "desired", descending)
