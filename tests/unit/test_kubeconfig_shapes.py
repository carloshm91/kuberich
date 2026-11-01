"""Kubectl serialization defaults and opaque provider metadata stay compatible."""

import copy

import pytest
import yaml

from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest
from kuberich.errors import AppError


def document():
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": "demo",
        "clusters": [{"name": "demo", "cluster": {"server": "https://api.example.invalid"}}],
        "users": [{"name": "demo", "user": {}}],
        "contexts": [{"name": "demo", "context": {"cluster": "demo", "user": "demo"}}],
    }


def load(path, data):
    path.write_text(yaml.safe_dump(data))
    before = path.read_bytes()
    result = load_catalog(ConnectionRequest(kubeconfig=str(path)), {})
    assert path.read_bytes() == before
    return result


@pytest.mark.parametrize("namespace", [None, ""])
@pytest.mark.parametrize("user", [None, ""])
def test_serialized_empty_context_strings_select_anonymous_default_namespace(
    tmp_path, namespace, user
):
    data = document()
    data["contexts"][0]["context"].update(namespace=namespace, user=user)
    selected = load(tmp_path / "input", data).select("demo")
    assert selected.namespace == "default" and selected.user.data == {}


def test_null_user_and_optional_metadata_preserve_opaque_extension_values(tmp_path):
    data = document()
    data["users"][0]["user"] = None
    data["preferences"] = {
        "colors": True,
        "extensions": [{"name": "demo", "extension": ["opaque"]}],
    }
    data["extensions"] = [{"name": "demo", "extension": "opaque"}]
    data["clusters"][0]["cluster"]["extensions"] = [
        {"name": "teleport.kube.name", "extension": "demo"}
    ]
    data["contexts"][0]["context"]["extensions"] = None
    before = copy.deepcopy(data)
    selected = load(tmp_path / "input", data).select("demo")
    assert selected.user.data == {}
    assert selected.cluster.data["extensions"] == data["clusters"][0]["cluster"]["extensions"]
    assert data == before


@pytest.mark.parametrize(
    "section,payload", [("clusters", "cluster"), ("users", "user"), ("contexts", "context")]
)
def test_invalid_named_payload_identifies_the_field(tmp_path, section, payload):
    data = document()
    data[section][0][payload] = "private-invalid"
    with pytest.raises(AppError, match=section + r"\." + payload) as caught:
        load(tmp_path / "input", data)
    assert "private-invalid" not in str(caught.value)


@pytest.mark.parametrize(
    "extra,field",
    [
        ({"apiVersion": "private-invalid"}, "apiVersion"),
        ({"kind": "private-invalid"}, "kind"),
        ({"preferences": []}, "preferences"),
        ({"preferences": {"colors": "private-invalid"}}, "preferences.colors"),
        ({"extensions": {}}, "extensions"),
        ({"extensions": [None]}, "extensions"),
        ({"extensions": [{"name": False}]}, "extensions"),
        ({"preferences": {"extensions": False}}, "preferences.extensions"),
        ({"extensions": [{} for _ in range(2049)]}, "extensions"),
    ],
)
def test_metadata_type_errors_name_fields_without_raw_values(tmp_path, extra, field):
    data = document()
    data.update(extra)
    with pytest.raises(AppError) as caught:
        load(tmp_path / "input", data)
    assert field in str(caught.value) and "private-invalid" not in str(caught.value)


@pytest.mark.parametrize(
    "extra",
    [
        {"apiVersion": None, "kind": ""},
        {"preferences": None, "extensions": None},
        {"preferences": {"colors": None}},
    ],
)
def test_optional_metadata_defaults_do_not_disable_other_validation(tmp_path, extra):
    data = document()
    data.update(extra)
    assert load(tmp_path / "input", data).select("demo").namespace == "default"


@pytest.mark.parametrize(
    "field,value",
    [("namespace", False), ("namespace", "bad/name"), ("cluster", None), ("user", False)],
)
def test_context_invalid_values_still_reject_with_field_names(tmp_path, field, value):
    data = document()
    data["contexts"][0]["context"][field] = value
    catalog = load(tmp_path / "input", data)
    with pytest.raises((AppError, ConnectionProblem)) as caught:
        catalog.select("demo")
    assert "contexts.context." + field in str(caught.value)


@pytest.mark.parametrize("current", [False, 0, [], {}, 123, "private\x1b"])
def test_invalid_current_context_is_not_hidden_by_false_values_or_an_earlier_file(
    tmp_path, current
):
    import os

    first = tmp_path / "first"
    load(first, document())
    second = tmp_path / "second"
    data = document()
    data["current-context"] = current
    second.write_text(yaml.safe_dump(data))
    with pytest.raises(AppError, match="current-context") as caught:
        load_catalog(ConnectionRequest(), {"KUBECONFIG": str(first) + os.pathsep + str(second)})
    assert "private" not in str(caught.value)
