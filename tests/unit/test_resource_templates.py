"""Data-only templates preserve exact types and refuse executable or ambiguous input."""

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from kuberich.domain import resource_templates
from kuberich.domain.manifests import canonical_manifest, manifest_documents
from kuberich.domain.resource_templates import (
    TemplateCatalogEntry,
    builtin_templates,
    parse_resource_template,
    render_resource_template,
)
from kuberich.errors import AppError


def envelope():
    return {
        "schema_version": 1,
        "kind": "ResourceTemplate",
        "id": "owned-template",
        "revision": 1,
        "title": "Owned synthetic resource",
        "parameters": {"name": {"type": "string", "required": True, "paths": ["/0/metadata/name"]}},
        "objects": [
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": ""}, "data": {}}
        ],
    }


def parse(value):
    return parse_resource_template(canonical_manifest(value))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("kind", "ExecutableTemplate"),
        ("id", False),
        ("id", "Upper"),
        ("id", "x" * 65),
        ("revision", True),
        ("revision", 0),
        ("title", ""),
        ("title", False),
        ("title", "x" * 121),
        ("title", "bad\x1btitle"),
        ("description", "x" * 1025),
        ("parameters", []),
        ("objects", []),
        ("objects", {}),
    ],
)
def test_closed_envelope_metadata_and_bounds(field, value):
    source = envelope()
    source[field] = value
    with pytest.raises(AppError):
        parse(source)


def test_unknown_missing_and_many_parameters_or_objects():
    for value in (
        {**envelope(), "command": "never execute"},
        {key: item for key, item in envelope().items() if key != "schema_version"},
        {**envelope(), "parameters": {f"x-{index}": {} for index in range(33)}},
        {**envelope(), "objects": envelope()["objects"] * 101},
    ):
        with pytest.raises(AppError):
            parse(value)


def test_title_counts_unicode_characters_and_description_counts_utf8_bytes():
    value = envelope()
    value.update(title="é" * 120, description="é" * 512)
    template = parse(value)
    assert template.title == "é" * 120 and template.description == "é" * 512
    for change in ({"title": "é" * 121}, {"description": "é" * 513}):
        with pytest.raises(AppError, match="bound"):
            parse({**value, **change})


def test_parameter_destinations_and_source_digests_do_not_enter_representations():
    value = envelope()
    value["objects"][0]["data"] = {"private-destination-key": ""}
    value["parameters"]["private"] = {
        "type": "string",
        "required": False,
        "default": "private-default-value",
        "paths": ["/0/data/private-destination-key"],
    }
    template = parse(value)
    entry = TemplateCatalogEntry(
        origin="user",
        relative_path="owned.yaml",
        identity=("user", template.id, template.revision, template.source_sha256),
        template=template,
    )
    shown = repr(template) + repr(template.parameters) + repr(entry)
    assert "private-destination-key" not in shown and "private-default-value" not in shown
    assert template.source_sha256 not in shown


@pytest.mark.parametrize(
    "paths",
    [
        ["/0/metadata/name"],
        ["/0/metadata/namespace"],
        ["/0/data/key", "/0/metadata/name"],
        ["/0/metadata/name", "/0/data/key"],
        ["/0/stringData/key", "/0/metadata/namespace"],
    ],
)
def test_sensitive_parameters_cannot_supply_public_routing_identity(paths):
    value = envelope()
    value["objects"][0].update(data={"key": ""}, stringData={"key": ""})
    value["objects"][0]["metadata"]["namespace"] = ""
    value["parameters"] = {
        "identity": {
            "type": "string",
            "required": True,
            "paths": paths,
            "sensitive": len(paths) == 1,
        }
    }
    with pytest.raises(AppError, match="public destination identity"):
        parse(value)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": None},
        {"kind": "Bad-Kind"},
        {"kind": "List"},
        {"kind": "WidgetList"},
        {"status": {}},
        {"metadata": {"name": "x", "uid": "server-only"}},
        {"metadata": {"name": "x", "generateName": "generated-"}},
        {"apiVersion": False},
    ],
)
def test_resource_type_is_literal_and_server_identity_is_not_template_data(change):
    value = envelope()
    value["objects"][0].update(change)
    with pytest.raises(AppError):
        parse(value)
    value["objects"] = [False]
    with pytest.raises(AppError):
        parse(value)


@pytest.mark.parametrize(
    "declaration",
    [
        False,
        {},
        {"type": "string", "required": True},
        {"type": "string", "required": True, "paths": ["/0/metadata/name"], "command": "no"},
        {"type": {}, "required": True, "paths": ["/0/metadata/name"]},
        {"type": "number", "required": True, "paths": ["/0/metadata/name"]},
        {"type": "string", "required": "yes", "paths": ["/0/metadata/name"]},
        {"type": "string", "required": True, "paths": ["/0/metadata/name"], "sensitive": 1},
    ],
)
def test_parameter_declarations_are_closed_and_strictly_typed(declaration):
    value = envelope()
    value["parameters"]["name"] = declaration
    with pytest.raises(AppError):
        parse(value)
    value["parameters"] = {"Bad Name": envelope()["parameters"]["name"]}
    with pytest.raises(AppError):
        parse(value)


@pytest.mark.parametrize(
    "paths",
    [
        None,
        [],
        ["/0/metadata/name"] * 33,
        [False],
        [""],
        ["x" * 1025],
        ["0/metadata/name"],
        ["/0/data/~2bad"],
        ["/0"],
        ["/-/metadata/name"],
        ["/01/metadata/name"],
        ["/0/apiVersion"],
        ["/0/kind"],
        ["/0/status"],
        ["/0/metadata"],
        ["/0/metadata/uid"],
        ["/0/metadata/generateName"],
        ["/1/metadata/name"],
        ["/0/missing/name"],
        ["/0/metadata/missing"],
        ["/0/metadata/name/child"],
        ["/0/data"],
    ],
)
def test_pointers_only_replace_existing_whole_typed_values(paths):
    value = envelope()
    value["parameters"]["name"]["paths"] = paths
    with pytest.raises(AppError):
        parse(value)


@pytest.mark.parametrize(
    "paths",
    [
        ["/0/data", "/0/data/key"],
        ["/0/data/key", "/0/data"],
        ["/0/data/key", "/0/data/key"],
    ],
)
def test_ancestor_descendant_and_duplicate_pointer_destinations_are_refused(paths):
    value = envelope()
    value["objects"][0]["data"] = {"key": "value"}
    value["parameters"] = {
        "first": {
            "type": "string_map" if paths[0].endswith("data") else "string",
            "required": False,
            "paths": [paths[0]],
        },
        "second": {
            "type": "string_map" if paths[1].endswith("data") else "string",
            "required": False,
            "paths": [paths[1]],
        },
    }
    with pytest.raises(AppError, match="overlap"):
        parse(value)


@pytest.mark.parametrize(
    ("extra", "initial", "kind", "supplied"),
    [
        ("enabled", True, "boolean", False),
        ("count", 3, "integer", 0),
        ("text", "initial", "string", ""),
        ("mapping", {}, "string_map", {"key": "value"}),
    ],
)
def test_false_zero_empty_and_map_are_values_not_missing(extra, initial, kind, supplied):
    value = envelope()
    value["objects"][0]["spec"] = {extra: initial}
    value["parameters"][extra] = {"type": kind, "required": True, "paths": [f"/0/spec/{extra}"]}
    template = parse(value)
    result = json.loads(render_resource_template(template, {"name": "owned", extra: supplied}))
    assert result["spec"][extra] == supplied and type(result["spec"][extra]) is type(supplied)
    assert template.source_sha256 == hashlib.sha256(canonical_manifest(value)).hexdigest()
    with pytest.raises(AppError, match="absent"):
        render_resource_template(template, {"name": "owned"})


@pytest.mark.parametrize(
    ("initial", "kind", "wrong"),
    [
        (True, "boolean", 0),
        (1, "integer", True),
        ("", "string", 4),
        ({}, "string_map", {"key": False}),
        ({}, "string_map", {False: "value"}),
        ({}, "string_map", []),
    ],
)
def test_no_implicit_parameter_coercion(initial, kind, wrong):
    value = envelope()
    value["objects"][0]["spec"] = {"input": initial}
    value["parameters"]["input"] = {"type": kind, "required": False, "paths": ["/0/spec/input"]}
    with pytest.raises(AppError, match="different type"):
        render_resource_template(parse(value), {"name": "owned", "input": wrong})


@pytest.mark.parametrize(
    "options",
    [
        {"enum": "not-a-list"},
        {"enum": list(range(65))},
        {"enum": [True]},
        {"enum": [1, 1]},
        {"default": False},
        {"enum": [1, 2], "default": 3},
    ],
)
def test_enum_and_default_are_finite_typed_literals(options):
    value = envelope()
    value["objects"][0]["spec"] = {"replicas": 1}
    value["parameters"]["replicas"] = {
        "type": "integer",
        "required": False,
        "paths": ["/0/spec/replicas"],
        **options,
    }
    with pytest.raises(AppError):
        parse(value)


def test_defaults_optional_values_enums_redaction_and_detached_map_values():
    value = envelope()
    value["objects"][0].update(spec={"enabled": True, "untouched": "literal", "selected": "a"})
    value["parameters"].update(
        {
            "enabled": {
                "type": "boolean",
                "required": True,
                "default": False,
                "paths": ["/0/spec/enabled"],
            },
            "data": {
                "type": "string_map",
                "required": False,
                "default": {"password": "synthetic-template-private"},
                "paths": ["/0/data"],
                "sensitive": False,
            },
            "literal": {"type": "string", "required": False, "paths": ["/0/spec/untouched"]},
            "selected": {
                "type": "string",
                "required": False,
                "default": "a",
                "enum": ["a", "b"],
                "paths": ["/0/spec/selected"],
                "sensitive": True,
            },
        }
    )
    template = parse(value)
    data = next(parameter for parameter in template.parameters if parameter.name == "data")
    assert data.sensitive
    detached = data.default_value
    detached["password"] = "modified"
    assert data.default_value["password"] == "synthetic-template-private"
    assert (
        next(
            parameter for parameter in template.parameters if parameter.name == "name"
        ).default_value
        is None
    )
    assert "synthetic-template-private" not in repr(template) + repr(data)
    result = json.loads(render_resource_template(template, {"name": "owned", "selected": "b"}))
    assert result["spec"] == {"enabled": False, "untouched": "literal", "selected": "b"}
    with pytest.raises(AppError, match="enum"):
        render_resource_template(template, {"name": "owned", "selected": "c"})
    with pytest.raises(AppError, match="unknown"):
        render_resource_template(template, {"name": "owned", "extra": "value"})


def test_rfc6901_escaping_array_destinations_and_literal_shell_or_template_text():
    value = envelope()
    value["objects"][0]["spec"] = {"items": ["old"], "a/b~c": "old"}
    value["parameters"]["literal"] = {
        "type": "string",
        "required": True,
        "paths": ["/0/spec/items/0", "/0/spec/a~1b~0c"],
    }
    template = parse(value)
    text = "${HOME} $(never-run) {{ no-expression }}"
    rendered = json.loads(render_resource_template(template, {"name": "owned", "literal": text}))
    assert rendered["spec"] == {"items": [text], "a/b~c": text}
    for path in ("/0/spec/items/1", "/0/spec/items/-", "/0/spec/items/01", "/0/spec/items/2/name"):
        changed = copy.deepcopy(value)
        changed["parameters"]["literal"]["paths"] = [path]
        with pytest.raises(AppError, match="existing"):
            parse(changed)


def test_multiresource_output_is_revalidated_as_ordinary_manifests():
    value = envelope()
    value["objects"].append(
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "owned"}}
    )
    template = parse(value)
    assert (
        len(
            manifest_documents(
                render_resource_template(template, {"name": "owned"}), source_path="owned"
            )
        )
        == 2
    )
    with pytest.raises(AppError):
        render_resource_template(template, {"name": "bad/name"})
    for data in (
        b"!!python/object/apply:os.system ['never']",
        b"x: &alias {}\ny: *alias",
        b"id: a\nid: b",
    ):
        with pytest.raises(AppError):
            parse_resource_template(data)


def test_repeated_64kib_parameter_refuses_before_first_overbudget_destination_copy(monkeypatch):
    value = envelope()
    value["objects"][0]["metadata"]["name"] = "owned"
    value["objects"][0]["spec"] = {f"field-{index}": "" for index in range(32)}
    value["parameters"] = {
        "repeat": {
            "type": "string",
            "required": True,
            "paths": [f"/0/spec/field-{index}" for index in range(32)],
        }
    }
    template = parse(value)
    supplied = "x" * (64 * 1024)
    encoded = canonical_manifest(supplied)
    original = json.loads
    copies = 0

    def counted(data, *args, **kwargs):
        nonlocal copies
        if data == encoded:
            copies += 1
        return original(data, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counted)
    with pytest.raises(AppError, match="1 MiB object budget"):
        render_resource_template(template, {"repeat": supplied})
    assert copies == 15
    assert all(item == "" for item in original(template.objects)[0]["spec"].values())


def test_large_supplied_map_is_refused_before_full_traversal_or_encoding(monkeypatch):
    value = envelope()
    value["objects"][0]["metadata"]["name"] = "owned"
    value["parameters"] = {"input": {"type": "string_map", "required": True, "paths": ["/0/data"]}}
    template = parse(value)
    visited = []

    class CountedMap(dict):
        def items(self):
            for key, item in super().items():
                visited.append(key)
                yield key, item

    supplied = CountedMap({f"key-{index}": "x" * 100 for index in range(300)})
    original = canonical_manifest

    def bounded(item):
        assert item is not supplied, "Overbudget input must never reach full JSON encoding"
        return original(item)

    monkeypatch.setattr(resource_templates, "MAX_MANIFEST_BYTES", 256)
    monkeypatch.setattr(resource_templates, "canonical_manifest", bounded)
    with pytest.raises(AppError, match="1 MiB value budget"):
        render_resource_template(template, {"input": supplied})
    assert len(visited) == 3


@pytest.mark.parametrize("supplied", ["x" * 129, "é" * 100, "\x01" * 100, "\ud800"])
def test_string_value_preflight_counts_utf8_json_escapes_and_rejects_invalid_unicode(
    monkeypatch, supplied
):
    value = envelope()
    value["objects"][0]["metadata"]["name"] = "owned"
    value["objects"][0]["spec"] = {"input": ""}
    value["parameters"] = {
        "input": {"type": "string", "required": True, "paths": ["/0/spec/input"]}
    }
    template = parse(value)
    original = canonical_manifest

    def bounded(item):
        assert item is not supplied, "Rejected input must not reach JSON encoding"
        return original(item)

    monkeypatch.setattr(resource_templates, "MAX_MANIFEST_BYTES", 128)
    monkeypatch.setattr(resource_templates, "canonical_manifest", bounded)
    with pytest.raises(AppError, match=r"value budget|valid UTF-8"):
        render_resource_template(template, {"input": supplied})


def test_literal_json_preflight_preserves_escaping_unicode_integer_and_false_values():
    value = envelope()
    value["objects"][0]["spec"] = {"text": "", "count": 0, "enabled": True}
    value["parameters"].update(
        {
            "text": {"type": "string", "required": True, "paths": ["/0/spec/text"]},
            "count": {"type": "integer", "required": True, "paths": ["/0/spec/count"]},
            "enabled": {"type": "boolean", "required": True, "paths": ["/0/spec/enabled"]},
            "data": {"type": "string_map", "required": True, "paths": ["/0/data"]},
        }
    )
    supplied = 'ascii " \\ \b \f \n \r \t \x01 é 中 😀'
    result = json.loads(
        render_resource_template(
            parse(value),
            {
                "name": "owned",
                "text": supplied,
                "count": -123,
                "enabled": False,
                "data": {"é": supplied, "second": ""},
            },
        )
    )
    assert result["spec"] == {"text": supplied, "count": -123, "enabled": False}
    assert result["data"] == {"é": supplied, "second": ""}


@pytest.mark.parametrize("bits", [448, 513])
def test_integer_conversion_is_bounded_before_unbounded_decimal_encoding(monkeypatch, bits):
    value = envelope()
    value["objects"][0]["metadata"]["name"] = "owned"
    value["objects"][0]["spec"] = {"count": 0}
    value["parameters"] = {
        "count": {"type": "integer", "required": True, "paths": ["/0/spec/count"]}
    }
    template = parse(value)
    monkeypatch.setattr(resource_templates, "MAX_MANIFEST_BYTES", 128)
    with pytest.raises(AppError, match="1 MiB value budget"):
        render_resource_template(template, {"count": 1 << bits})


def test_initial_and_projected_total_budgets_are_checked_before_substitution(monkeypatch):
    value = envelope()
    value["objects"][0]["metadata"]["name"] = "owned"
    value["objects"][0]["spec"] = {"input": ""}
    value["parameters"] = {
        "input": {"type": "string", "required": True, "paths": ["/0/spec/input", "/1/spec/input"]}
    }
    value["objects"].append(copy.deepcopy(value["objects"][0]))
    value["objects"][1]["metadata"]["name"] = "second"
    template = parse(value)
    original = json.loads
    copies = 0
    supplied = "x" * 64
    encoded = canonical_manifest(supplied)

    def counted(data, *args, **kwargs):
        nonlocal copies
        if data == encoded:
            copies += 1
        return original(data, *args, **kwargs)

    initial_total = sum(len(canonical_manifest(item)) for item in value["objects"]) + 5
    monkeypatch.setattr(json, "loads", counted)
    monkeypatch.setattr(resource_templates, "MAX_SOURCE_BYTES", initial_total + 100)
    with pytest.raises(AppError, match="8 MiB total budget"):
        render_resource_template(template, {"input": supplied})
    assert copies == 1
    monkeypatch.setattr(resource_templates, "MAX_SOURCE_BYTES", initial_total - 1)
    with pytest.raises(AppError, match="8 MiB total budget"):
        render_resource_template(template, {"input": supplied})
    assert copies == 1
    monkeypatch.setattr(resource_templates, "MAX_SOURCE_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(resource_templates, "MAX_MANIFEST_BYTES", 64)
    with pytest.raises(AppError, match="1 MiB object budget"):
        render_resource_template(template, {"input": supplied})
    assert copies == 1


def test_unknown_parameter_with_same_input_count_is_refused():
    with pytest.raises(AppError, match="unknown parameter"):
        render_resource_template(parse(envelope()), {"other": "owned"})


def test_six_builtins_have_conservative_named_defaults_and_finite_constraints():
    templates = {template.id: template for template in builtin_templates()}
    assert set(templates) == {"deployment", "service", "configmap", "secret", "job", "namespace"}
    for identifier, template in templates.items():
        values = {"name": "owned"}
        if identifier in {"deployment", "job"}:
            values["image"] = "registry.example/owned@sha256:" + "a" * 64
        if identifier == "service":
            values["selector"] = "owned"
        result = json.loads(render_resource_template(template, values))
        assert result["metadata"]["name"] == "owned" and len(json.loads(template.objects)) == 1
        with pytest.raises(AppError):
            render_resource_template(template, {**values, "name": "Upper.Name"})
        if identifier in {"deployment", "job"}:
            with pytest.raises(AppError, match="image"):
                render_resource_template(template, {**values, "image": " "})
        if identifier == "deployment":
            assert result["spec"]["replicas"] == 1
            assert (
                result["spec"]["selector"]["matchLabels"]
                == result["spec"]["template"]["metadata"]["labels"]
            )
            assert (
                json.loads(render_resource_template(template, {**values, "replicas": 0}))["spec"][
                    "replicas"
                ]
                == 0
            )
            for replicas in (-1, 2147483648):
                with pytest.raises(AppError, match="replicas"):
                    render_resource_template(template, {**values, "replicas": replicas})
        if identifier == "service":
            assert result["spec"]["type"] == "ClusterIP"
            assert result["spec"]["ports"] == [{"port": 80, "protocol": "TCP", "targetPort": 80}]
            assert (
                json.loads(
                    render_resource_template(template, {**values, "port": 1, "target-port": 65535})
                )["spec"]["ports"][0]["targetPort"]
                == 65535
            )
            for ports in ({"port": 0}, {"target-port": 65536}):
                with pytest.raises(AppError, match="ports"):
                    render_resource_template(template, {**values, **ports})
        if identifier == "secret":
            assert result["type"] == "Opaque" and result["stringData"] == {}
        if identifier == "job":
            assert result["spec"]["backoffLimit"] == 0
            assert result["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    entry = TemplateCatalogEntry(
        origin="builtin",
        relative_path="",
        identity=("builtin", "configmap", 1, "digest"),
        template=templates["configmap"],
    )
    assert entry.enabled
    assert not replace(entry, problem="refused").enabled
    assert not replace(entry, template=None).enabled
