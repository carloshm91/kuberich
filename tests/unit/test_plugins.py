"""Plugin trust, typed input, scope, shortcut and literal argument contracts."""

from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.config.plugins import parse_layer, parse_plugins, plugins_from
from kuberich.config.schema import ConfigDocument, parse_document
from kuberich.domain.plugins import (
    PluginSelection,
    expand_plugin,
    parse_input,
    parse_plugin,
    plugin_bindings,
    plugin_command,
)
from kuberich.domain.processes import ProcessMode, ProcessPurpose
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError


def definition(**fields):
    return {"command": "inspect-tool", **fields}


def plugin(**fields):
    return parse_plugin("inspect", definition(**fields), Path("/owned/config"))


def selection(**fields):
    target = ResourceTarget(SessionIdentity("demo", 1), "", "pods", "team", "worker", "uid")
    return PluginSelection("demo", "v1/pods", target, **fields)


def test_capture_is_literal_immutable_scoped_and_has_explicit_defaults():
    selected = selection(columns=(("NAME", "$(touch /never); [red]界"),))
    original = {"PATH": "/owned/bin", "ORIGINAL": "retained"}
    configured = plugin(
        args=["--context=${CONTEXT}", "--namespace=$NAMESPACE", "$NAME", "${COL-NAME}", "$$HOME"],
        environment={"SELECTED": "$NAME", "EMPTY": ""},
    )
    command = plugin_command(configured, selected, {}, original)
    assert command.argv == (
        "inspect-tool",
        "--context=demo",
        "--namespace=team",
        "worker",
        "$(touch /never); [red]界",
        "$HOME",
    )
    original["PATH"] = "/changed"
    assert dict(command.environment) == {
        "PATH": "/owned/bin",
        "ORIGINAL": "retained",
        "SELECTED": "worker",
        "EMPTY": "",
    }
    assert command.target is selected.target and command.purpose is ProcessPurpose.PLUGIN
    assert command.directory == Path("/owned/config") and command.mode is ProcessMode.CAPTURE
    assert configured.confirm and configured.dangerous and not configured.trusted_read_only
    assert configured.timeout == 300 and configured.output_limit == 65536
    assert "touch" not in repr(command) and "inspect-tool" not in repr(configured)


@pytest.mark.parametrize(
    "text,values,expected",
    [
        ("literal", {}, "literal"),
        ("", {}, ""),
        ("$$", {}, "$"),
        (
            "$NAME/$NAME/${NAMESPACE}",
            {"NAME": "$UNPARSED", "NAMESPACE": "team"},
            "$UNPARSED/$UNPARSED/team",
        ),
        ("$COL-AGE", {"COL-AGE": "5m"}, "5m"),
        ("${NAME}suffix", {"NAME": "worker"}, "workersuffix"),
        ("$$HOME:$NAME", {"NAME": "one"}, "$HOME:one"),
        ("$$!NAME/$${!NAME}", {}, "$!NAME/${!NAME}"),
    ],
)
def test_expansion_is_one_pass_and_explicit(text, values, expected):
    assert expand_plugin(text, values) == expected


@pytest.mark.parametrize(
    "text,values",
    [
        ("$!NAME", {"NAME": "x"}),
        ("${!NAME}", {}),
        ("$MISSING", {}),
        ("$", {}),
        ("${NAME", {}),
        ("${}", {}),
        ("$lower", {}),
        ("prefix$?suffix$NAME", {"NAME": "x"}),
        ("$NAME$?", {"NAME": "x"}),
        ("\x1b", {}),
        ("$NAME", {"NAME": "\x00"}),
        ("$NAME$NAME", {"NAME": "x" * 5000}),
    ],
)
def test_expansion_rejects_missing_malformed_and_control_values(text, values):
    with pytest.raises(AppError):
        expand_plugin(text, values)


@pytest.mark.parametrize("text", ["$!COL-SUSPEND", "${!COL-SUSPEND}"])
def test_upstream_boolean_inversion_requires_a_deliberate_input(text):
    with pytest.raises(AppError, match="boolean inversion"):
        expand_plugin(text, {"COL-SUSPEND": "true"})


@pytest.mark.parametrize(
    "scope",
    [
        "v1/pods",
        "example.test/v1/a",
        "example.test/v1/" + "a" * 63,
        "k8s.cni.cncf.io/v1/network-attachment-definitions",
    ],
)
def test_scopes_accept_dns_resource_plurals_and_match_exact_served_version(scope):
    value = plugin(scopes=[scope])
    assert value.applies(scope)
    assert not value.applies(scope.replace("v1/", "v2/", 1))


@pytest.mark.parametrize(
    "plural", ["-pods", "pods-", "pods/status", "pods.name", "1pods", "a" * 64]
)
def test_scopes_reject_invalid_resource_plural_boundaries(plural):
    with pytest.raises(AppError, match="scopes"):
        plugin(scopes=["example.test/v1/" + plural])


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("string", "a ; $(not-run) 界", "a ; $(not-run) 界"),
        ("number", 12, "12"),
        ("number", "-2.5e3", "-2.5e3"),
        ("bool", True, "true"),
        ("bool", False, "false"),
        ("bool", "false", "false"),
        ("bool", "true", "true"),
        ("dropdown", "fast", "fast"),
    ],
)
def test_typed_inputs_preserve_validated_literal_values(kind, value, expected):
    item = parse_input(
        {
            "name": "mode",
            "type": kind,
            **({"options": ["fast", "safe"]} if kind == "dropdown" else {}),
        }
    )
    assert item.accept(value) == expected


@pytest.mark.parametrize(
    "kind,value",
    [
        ("number", []),
        ("number", True),
        ("number", "NaN"),
        ("number", float("inf")),
        ("number", 10**1000),
        ("number", "not a number"),
        ("bool", 1),
        ("bool", "yes"),
        ("bool", []),
        ("string", 12),
        ("string", "\n"),
        ("dropdown", "unlisted"),
    ],
)
def test_invalid_typed_inputs_fail_without_echoing_values(kind, value):
    item = parse_input(
        {"name": "choice", "type": kind, **({"options": ["safe"]} if kind == "dropdown" else {})}
    )
    with pytest.raises(AppError, match="Plugin"):
        item.accept(value)


def test_defaults_optional_inputs_required_and_deliberate_cancel():
    optional = parse_input({"name": "note", "required": False})
    assert optional.accept(None) == optional.accept("") == ""
    with pytest.raises(AppError, match="required"):
        parse_input({"name": "note"}).accept(None)
    configured = plugin(
        inputs=[{"name": "count", "type": "number", "default": 2}], args=["${INPUT_COUNT}"]
    )
    assert plugin_command(configured, selection(), {}, {}).argv[-1] == "2"
    assert plugin_command(configured, selection(), {"count": 3}, {}).argv[-1] == "3"
    assert plugin_command(configured, selection(), None, {}) is None
    with pytest.raises(AppError, match="Unknown plugin input"):
        plugin_command(configured, selection(), {"unconfigured": "secret"}, {})
    with pytest.raises(AppError, match="nonempty"):
        plugin_command(
            plugin(inputs=[{"name": "note", "required": False}], args=["$INPUT_NOTE"]),
            selection(),
            {},
            {},
        )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"unknown": 1},
        {"name": ""},
        {"name": "BAD"},
        {"name": "a", "type": []},
        {"name": "a", "type": "password"},
        {"name": "a", "required": 1},
        {"name": "a", "default": []},
        {"name": "a", "default": True},
        {"name": "a", "type": "dropdown"},
        {"name": "a", "options": ["one"]},
        {"name": "a", "type": "dropdown", "options": ["one", "one"]},
        {"name": "a", "type": "dropdown", "options": ["one"], "default": "missing"},
        {"name": "a", "options": "wrong"},
        {"name": "a", "options": ["x"] * 65},
    ],
)
def test_invalid_input_contracts_are_rejected(raw):
    with pytest.raises(AppError):
        parse_input(raw)


@pytest.mark.parametrize(
    "fields",
    [
        {"command": None},
        {"command": "-tool"},
        {"command": "$NAME"},
        {"command": "\x1btool"},
        {"command": "x" * 8193},
        {"args": "one string"},
        {"args": ["x"] * 256},
        {"args": [""]},
        {"scopes": []},
        {"scopes": ["pods"]},
        {"scopes": ["apps/v1/deployments", "bad/?"]},
        {"environment": []},
        {"environment": {str(i): "x" for i in range(65)}},
        {"environment": {1: "x"}},
        {"environment": {"A=B": "x"}},
        {"environment": {"A" * 129: "x"}},
        {"environment": {"TOKEN": 1}},
        {"environment": {"KUBECONFIG": "foreign"}},
        {"environment": {"KUBERICH_TARGET": "foreign"}},
        {"mode": "detached"},
        {"mode": []},
        {"shortcut": "ctrl+q"},
        {"shortcut": "ctrl+i"},
        {"inputs": {}},
        {"inputs": [{}] * 17},
        {"inputs": [{"name": "a-b"}, {"name": "a_b"}]},
        {"output_limit": True},
        {"output_limit": 1023},
        {"output_limit": 1048577},
        {"timeout": True},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": 86401},
        {"override": "yes"},
        {"dangerous": 1},
        {"confirm": None},
        {"trusted_read_only": "true"},
        {"directory": "\n"},
        {"unknown": "ignored?"},
    ],
)
def test_malformed_manifest_fields_fail_closed(fields):
    with pytest.raises(AppError):
        plugin(**fields)


@pytest.mark.parametrize("name", [None, "", "A", "two words", "a" * 65])
def test_names_are_safe_bounded_identifiers(name):
    with pytest.raises(AppError):
        parse_plugin(name, definition(), Path("/owned"))


@pytest.mark.parametrize("raw", [None, [], {1: 2}])
def test_definition_requires_string_mapping(raw):
    with pytest.raises(AppError):
        parse_plugin("inspect", raw, Path("/owned"))


def test_directory_scope_modes_and_context_values_are_captured():
    assert plugin(directory="work").directory == Path("/owned/config/work")
    assert plugin(directory="/explicit").directory == Path("/explicit")
    with pytest.raises(AppError, match="absolute"):
        parse_plugin("inspect", definition(), Path("relative"))
    assert plugin(mode="foreground").mode is ProcessMode.FOREGROUND
    assert plugin(mode="background").mode is ProcessMode.BACKGROUND
    scoped = plugin(scopes=["apps/v1/deployments"])
    assert scoped.applies("apps/v1/deployments") and not scoped.applies("v1/pods")
    assert not scoped.applies(None) and plugin().applies(None)
    with pytest.raises(AppError, match="does not apply"):
        plugin_command(scoped, selection(), {}, {})
    target = ResourceTarget(
        SessionIdentity("demo", 1), "apps", "deployments", None, "worker", "id", "app"
    )
    selected = PluginSelection(
        "demo",
        "apps/v1/deployments",
        target,
        (
            ("CLUSTER", "demo-cluster"),
            ("USER", "operator"),
            ("FILTER", ""),
            ("KUBECONFIG", "/owned/session"),
        ),
    )
    values = selected.values()
    assert values["GROUP"] == "apps" and values["VERSION"] == "v1"
    assert values["NAMESPACE"] == "" and values["CONTAINER"] == "app"
    assert values["KUBECONFIG"] == "/owned/session" and values["USER"] == "operator"
    assert PluginSelection("offline").values() == {"CONTEXT": "offline"}
    for changed in (
        replace(selected, context="foreign"),
        replace(selected, resource="v1/pods"),
        replace(selected, resource="other/v1/deployments"),
        replace(selected, variables=(("TOKEN", "private"),)),
        replace(selected, columns=(("bad", "x"),)),
    ):
        with pytest.raises(AppError):
            changed.values()


def test_scope_aware_shortcuts_require_deliberate_override_and_unique_keys():
    first = plugin(shortcut="a", scopes=["v1/pods"])
    second = replace(first, name="other", scopes=("v1/services",))
    assert plugin_bindings((first, second), "v1/pods") == (("a", "inspect"),)
    assert plugin_bindings((first,), None) == ()
    assert plugin_bindings((plugin(),), "v1/pods") == ()
    with pytest.raises(AppError, match="conflicting"):
        plugin_bindings((first, replace(first, name="duplicate")), "v1/pods")
    for key in ("l", "j", "ctrl+d"):
        with pytest.raises(AppError, match="override"):
            plugin_bindings((plugin(shortcut=key),), "v1/pods")
        assert plugin_bindings((plugin(shortcut=key, override=True),), "v1/pods") == (
            (key, "inspect"),
        )
    with pytest.raises(AppError, match="override"):
        plugin_bindings((first,), "v1/pods", (("resources", (("down", "a"),)),))


def test_read_only_classification_is_explicit_and_dangerous_always_wins():
    plugin().require_access(False)
    safe = plugin(trusted_read_only=True, dangerous=False)
    safe.require_access(True)
    for unsafe in (plugin(), plugin(trusted_read_only=True), plugin(dangerous=False)):
        with pytest.raises(AppError, match="Read-only"):
            unsafe.require_access(True)


def test_unresolvable_home_paths_and_invalid_captured_scopes_fail_usefully(monkeypatch):
    def unavailable_home(path):
        raise RuntimeError("private home detail")

    monkeypatch.setattr(Path, "expanduser", unavailable_home)
    with pytest.raises(AppError, match="working directory"):
        plugin(directory="~missing/work")
    with pytest.raises(AppError, match="location"):
        parse_layer({"locations": ["~missing/plugins"]}, Path("/owned"))
    with pytest.raises(AppError, match="scope"):
        replace(selection(), resource="pods").values()


def test_configuration_layers_are_explicit_and_context_precedence_is_preserved():
    raw = {
        "schema_version": 1,
        "locations": ["plugins", "/explicit.yaml"],
        "commands": {"inspect": definition()},
        "contexts": {
            "demo": {
                "locations": ["demo-plugins"],
                "commands": {"inspect": definition(command="context-tool")},
            }
        },
    }
    parsed = parse_plugins(raw, Path("/owned"))
    assert parsed.global_layer.locations == (Path("/owned/plugins"), Path("/explicit.yaml"))
    assert parsed.global_layer.commands[0].command == "inspect-tool"
    assert dict(parsed.contexts)["demo"].commands[0].command == "context-tool"
    assert (
        plugins_from(parse_document({"schema_version": 1, "plugins": raw}), Path("/owned"))
        == parsed
    )
    assert plugins_from(ConfigDocument(), Path("/owned")).contexts == ()
    assert parse_layer({}, Path("/owned"), external=True).commands == ()


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"schema_version": True},
        {"schema_version": 2},
        {"schema_version": 1, "unknown": {}},
        {"schema_version": 1, "contexts": []},
        {"schema_version": 1, "contexts": {str(i): {} for i in range(129)}},
        {"schema_version": 1, "contexts": {"x" * 254: {}}},
        {"schema_version": 1, "contexts": {"\n": {}}},
        {"schema_version": 1, "contexts": {"demo": {"unknown": []}}},
        {"schema_version": 1, "commands": []},
        {"schema_version": 1, "commands": {str(i): {} for i in range(65)}},
        {"schema_version": 1, "locations": "plugins"},
        {"schema_version": 1, "locations": ["x"] * 9},
        {"schema_version": 1, "locations": ["x", "x"]},
        {"schema_version": 1, "locations": ["\n"]},
    ],
)
def test_configuration_errors_are_not_silently_ignored(raw):
    with pytest.raises(AppError):
        parse_plugins(raw, Path("/owned"))
    with pytest.raises(AppError):
        parse_layer({"locations": ["nested"]}, Path("/owned"), external=True)
