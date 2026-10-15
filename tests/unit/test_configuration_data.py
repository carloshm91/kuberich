"""Real encoded inputs, disclosure boundaries and payload-free metadata."""

import base64
from dataclasses import replace

import pytest

from kuberich.domain.configuration_data import (
    MAX_CLIPBOARD_BYTES,
    MAX_DATA_BYTES,
    MAX_DATA_KEYS,
    clipboard_value,
    configuration_index,
    configuration_value,
)
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.errors import AppError


def resource(kind="Secret"):
    return ApiResource(
        "",
        "v1",
        "secrets" if kind == "Secret" else "configmaps",
        kind,
        True,
        frozenset({"get", "patch"}),
    )


def record(kind="Secret", **fields):
    return resource_record(
        resource(kind),
        {
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {
                "name": "owned-one",
                "namespace": "team",
                "uid": "owned-uid",
                "resourceVersion": "rv/1",
            },
            **fields,
        },
        "team",
    )


@pytest.mark.parametrize("kind,section", [("Secret", "data"), ("ConfigMap", "binaryData")])
def test_encoded_payload_metadata_never_contains_values_and_round_trips_binary(kind, section):
    payload = b"\xff\x00owned-payload"
    encoded = base64.b64encode(payload).decode()
    value = record(kind, **{section: {"blob": encoded}})
    index = configuration_index(value)
    assert index.resource_version == "rv/1"
    (key,) = index.keys
    assert key.identity == (section, "blob") and key.binary and key.size == len(payload)
    assert encoded not in repr(index) and "owned-payload" not in repr(index)
    assert configuration_value(value, key.identity, encoded=True) == encoded
    with pytest.raises(AppError, match="binary"):
        configuration_value(value, key.identity, encoded=False)


@pytest.mark.parametrize("kind,section", [("Secret", "stringData"), ("ConfigMap", "data")])
@pytest.mark.parametrize("text", ["", "owned text", "password=explicit\n[red]\x1b[2J", "café 👋"])
def test_explicit_text_and_base64_representations_preserve_selected_payload(kind, section, text):
    value = record(kind, **{section: {"chosen": text}})
    (key,) = configuration_index(value).keys
    assert not key.binary and key.size == len(text.encode())
    assert configuration_value(value, key.identity, encoded=False) == text
    assert (
        configuration_value(value, key.identity, encoded=True)
        == base64.b64encode(text.encode()).decode()
    )


def test_real_secret_base64_decodes_only_the_selected_key_and_indexes_are_sorted():
    value = record(data={"z": "b3duZWQ=", "a": "dGV4dA=="}, stringData={"z": "plain"})
    index = configuration_index(value)
    assert [key.identity for key in index.keys] == [
        ("data", "a"),
        ("data", "z"),
        ("stringData", "z"),
    ]
    assert configuration_value(value, ("data", "a"), encoded=False) == "text"
    with pytest.raises(AppError, match="unavailable"):
        configuration_value(value, ("data", "absent"), encoded=False)


@pytest.mark.parametrize("kind", ["Secret", "ConfigMap"])
@pytest.mark.parametrize("fields", [{}, {"data": None}, {"data": {}}])
def test_empty_optional_payloads_have_no_revealable_keys(kind, fields):
    assert configuration_index(record(kind, **fields)).keys == ()


@pytest.mark.parametrize("data", [[], "sensitive", 12])
def test_invalid_data_container_has_a_payload_free_error(data):
    with pytest.raises(AppError) as error:
        configuration_index(record(data=data))
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("", "encoded"),
        ("bad/key", "encoded"),
        ("x" * 254, "encoded"),
        ("valid", 42),
        ("valid", None),
    ],
)
def test_invalid_keys_or_value_types_are_rejected_without_values(key, value):
    with pytest.raises(AppError, match="invalid key or value type"):
        configuration_index(record(data={key: value}))


@pytest.mark.parametrize("value", ["not-base64!", "private-encoded-payload", "ü-sensitive"])
def test_malformed_base64_is_never_echoed(value):
    with pytest.raises(AppError, match="Invalid base64") as error:
        configuration_index(record(data={"chosen": value}))
    assert value not in str(error.value) and error.value.__suppress_context__


def test_wrong_kind_missing_version_and_allocation_limits_fail_before_disclosure():
    with pytest.raises(AppError, match="core ConfigMap"):
        configuration_index(record("Pod"))
    with pytest.raises(AppError, match="resource version"):
        configuration_index(replace(record(), resource_version=None))
    with pytest.raises(AppError, match="2 MiB"):
        configuration_index(record("ConfigMap", data={"large": "x" * (2 * MAX_DATA_BYTES)}))
    with pytest.raises(AppError, match="1 MiB"):
        configuration_index(record("ConfigMap", data={"large": "x" * (MAX_DATA_BYTES + 1)}))
    with pytest.raises(AppError, match="4096"):
        configuration_index(
            record("ConfigMap", data={f"key-{i}": "" for i in range(MAX_DATA_KEYS + 1)})
        )


def test_malformed_unicode_and_clipboard_byte_bounds_have_content_free_errors():
    # resource_record preserves escaped surrogates only in a synthetic immutable input.
    value = replace(record(), _manifest=b'{"kind":"Secret","stringData":{"key":"\\ud800"}}')
    with pytest.raises(AppError, match="UTF-8"):
        configuration_index(value)
    assert clipboard_value("x" * MAX_CLIPBOARD_BYTES) == "x" * MAX_CLIPBOARD_BYTES
    for text in ["sensitive" * MAX_CLIPBOARD_BYTES, "👋" * (MAX_CLIPBOARD_BYTES // 4 + 1)]:
        with pytest.raises(AppError, match="64 KiB") as error:
            clipboard_value(text)
        assert "sensitive" not in str(error.value)
    with pytest.raises(AppError, match="UTF-8"):
        clipboard_value("\ud800")
