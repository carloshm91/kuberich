"""Data-only templates preserve exact types and refuse executable or ambiguous input."""

import copy
import hashlib
import json
from dataclasses import replace

import pytest

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
