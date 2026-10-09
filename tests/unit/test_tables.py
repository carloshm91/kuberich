"""Server formatter limits, immutable metadata and complete-object watch decisions."""

from dataclasses import FrozenInstanceError

import pytest

from kuberich.domain import tables
from kuberich.domain.resources import ResourceSnapshot
from kuberich.domain.tables import TableDecoder, TableUnavailable, is_table
from kuberich.domain.views import ResourceSelection
from kuberich.domain.watches import EventType, WatchState
from kuberich.errors import AppError
from tests.support.tables import custom_item, custom_resource, server_table
from tests.support.watches import bookmark, error_event


def test_table_metadata_is_separate_immutable_bounded_and_not_in_resource_yaml():
    payload = server_table(custom_item())
    decoder = TableDecoder(custom_resource(), "team")
    record = decoder.records(payload)[0]
    assert record.name == "one" and record.uid == "owned-one"
    assert record.server.cells == ("one", 3, True)
    assert record.server.columns[1].type == "integer"
    assert record.size_bytes > len(record._manifest)
    assert "columnDefinitions" not in record.manifest
    payload["rows"][0]["object"]["spec"]["level"] = 90
    payload["rows"][0]["cells"][1] = 90
    payload["columnDefinitions"][0]["name"] = "changed"
    assert record.manifest["spec"]["level"] == 3
    assert record.server.cells[1] == 3 and decoder.columns[0].name == "Name"
    assert "one" not in repr(record.server) and "level" not in repr(record)
    with pytest.raises(FrozenInstanceError):
        record.server.columns[0].name = "changed"
    assert decoder.records(server_table())[0:] == ()


@pytest.mark.parametrize(
    "kind,value",
    [
        ("string", "literal [bold]\x1b[2J"),
        ("date", "2h"),
        ("boolean", False),
        ("integer", -(2**63)),
        ("integer", 2**63 - 1),
        ("number", 1.5),
        ("number", -2),
        ("string", None),
        ("number", None),
    ],
)
def test_typed_server_cells_preserve_null_boolean_numeric_and_literal_values(kind, value):
    payload = server_table(custom_item())
    payload["columnDefinitions"] = [{"name": "Owned", "type": kind}]
    payload["rows"][0]["cells"] = [value]
    record = TableDecoder(custom_resource(), "team").records(payload)[0]
    assert record.server.cells == (value,)


@pytest.mark.parametrize(
    "column",
    [
        None,
        {},
        {"name": "", "type": "string"},
        {"name": "x" * 129, "type": "string"},
        {"name": [], "type": "string"},
        {"name": "x", "type": []},
        {"name": "x", "type": "object"},
        {"name": "x", "type": "string", "priority": True},
        {"name": "x", "type": "string", "priority": -1},
        {"name": "x", "type": "string", "priority": 2**31},
        {"name": "x", "type": "string", "description": "x" * 4097},
        {"name": "x", "type": "string", "format": False},
        {"name": "\ud800", "type": "string"},
    ],
)
def test_invalid_column_metadata_requests_fallback_without_interpreting_it(column):
    payload = server_table(custom_item())
    payload["columnDefinitions"] = [column]
    with pytest.raises(TableUnavailable):
        TableDecoder(custom_resource(), "team").records(payload)


@pytest.mark.parametrize(
    "headers", [None, [], {}, "invalid", [{"name": "x", "type": "string"}] * 65]
)
def test_missing_or_excessive_initial_headers_do_not_guess_a_schema(headers):
    payload = server_table(custom_item())
    payload["columnDefinitions"] = headers
    with pytest.raises(TableUnavailable):
        TableDecoder(custom_resource(), "team").records(payload)


def test_total_utf8_header_metadata_is_bounded(monkeypatch):
    payload = server_table(custom_item())
    monkeypatch.setattr(tables, "MAX_TABLE_METADATA_BYTES", 64)
    with pytest.raises(TableUnavailable):
        TableDecoder(custom_resource(), "team").records(payload)


@pytest.mark.parametrize(
    "kind,value",
    [
        ("string", 1),
        ("string", "x" * 65537),
        ("boolean", 1),
        ("integer", True),
        ("integer", 1.5),
        ("integer", 2**63),
        ("number", -(2**63) - 1),
        ("number", float("inf")),
        ("number", float("nan")),
        ("string", {}),
        ("string", "\ud800"),
    ],
)
def test_malformed_cells_are_not_coerced_to_zero_or_interpreted(kind, value):
    payload = server_table(custom_item())
    payload["columnDefinitions"] = [{"name": "Owned", "type": kind}]
    payload["rows"][0]["cells"] = [value]
    with pytest.raises(TableUnavailable):
        TableDecoder(custom_resource(), "team").records(payload)


@pytest.mark.parametrize(
    "change",
    ["version", "kind", "rows", "object", "partial", "no_kind", "no_version", "cells", "width"],
)
def test_incomplete_or_unknown_table_shapes_require_plain_objects(change):
    payload = server_table(custom_item())
    if change == "version":
        payload["apiVersion"] = "meta.k8s.io/v1beta1"
    elif change == "kind":
        payload["kind"] = "Unknown"
    elif change == "rows":
        payload["rows"] = None
    elif change == "object":
        payload["rows"][0]["object"] = None
    elif change == "partial":
        payload["rows"][0]["object"]["kind"] = "PartialObjectMetadata"
    elif change == "no_kind":
        del payload["rows"][0]["object"]["kind"]
    elif change == "no_version":
        del payload["rows"][0]["object"]["apiVersion"]
    elif change == "cells":
        payload["rows"][0]["cells"] = False
    else:
        payload["rows"][0]["cells"].pop()
    with pytest.raises(TableUnavailable):
        TableDecoder(custom_resource(), "team").records(payload)


def test_wrong_scope_and_type_remain_resource_errors_not_formatter_fallback():
    for change in ("namespace", "kind", "apiVersion"):
        payload = server_table(custom_item())
        payload["rows"][0]["object"]["metadata" if change == "namespace" else change] = (
            {**payload["rows"][0]["object"]["metadata"], "namespace": "elsewhere"}
            if change == "namespace"
            else "wrong"
        )
        with pytest.raises(AppError) as error:
            TableDecoder(custom_resource(), "team").records(payload)
        assert not isinstance(error.value, TableUnavailable)


def test_each_opened_stream_requires_its_own_headers_and_preserves_checkpoint():
    resource = custom_resource()
    decoder = TableDecoder(resource, "team")
    initial = decoder.records(server_table(custom_item()))
    state = WatchState(ResourceSnapshot(resource, "team", "start", initial, decoder.columns))
    changed = server_table(custom_item(rv="changed"), headers=False)
    event = decoder.event({"type": "MODIFIED", "object": changed})
    assert state.apply(event) and state.snapshot.columns == decoder.columns
    assert state.snapshot.items[0].server.cells == ("one", 3, True)
    mark = server_table(custom_item(rv="checkpoint"), headers=False)
    mark["rows"][0]["object"]["metadata"].pop("name")
    marker = decoder.event({"type": "BOOKMARK", "object": mark})
    assert marker.type is EventType.BOOKMARK and state.apply(marker)
    assert state.snapshot.resource_version == "checkpoint"
    with pytest.raises(TableUnavailable):
        TableDecoder(resource, "team").event({"type": "MODIFIED", "object": changed})
    with pytest.raises(TableUnavailable):
        decoder.records({**changed, "columnDefinitions": {}})
    with pytest.raises(TableUnavailable):
        decoder.records({**changed, "columnDefinitions": [{"name": "changed", "type": "string"}]})
    raw = custom_item(rv="raw")
    assert state.apply(decoder.event({"type": "MODIFIED", "object": raw}))
    assert state.snapshot.columns == () and state.snapshot.items[0].server is None


def test_table_envelope_recognition_and_single_object_bounds(monkeypatch):
    assert is_table(server_table())
    assert not is_table(custom_item())
    assert not is_table({"kind": "Table", "apiVersion": None})
    assert not is_table({"kind": "Table", "apiVersion": "owned/v1"})
    decoder = TableDecoder(custom_resource(), "team")
    for payload in (server_table(), server_table(custom_item(), custom_item("two", uid="other"))):
        with pytest.raises(TableUnavailable):
            decoder.records(payload, single=True)
    for row in (None, {}, {"object": []}):
        with pytest.raises(TableUnavailable):
            decoder.records({**server_table(), "rows": [row]})
    monkeypatch.setattr(tables, "MAX_RESOURCE_ITEMS", 0)
    with pytest.raises(TableUnavailable):
        decoder.records(server_table(custom_item()))


def test_plain_watch_markers_and_http_errors_remain_the_original_protocol():
    decoder = TableDecoder(custom_resource(), "team")
    marker = bookmark("checkpoint")
    marker["object"].update({"apiVersion": decoder.resource.api_version, "kind": "Widget"})
    assert decoder.event(marker).resource_version == "checkpoint"
    from kuberich.domain.connections import HttpProblem

    with pytest.raises(HttpProblem) as error:
        decoder.event(error_event(410))
    assert error.value.status == 410
    with pytest.raises(AppError):
        decoder.event({"type": "ADDED", "object": None})


def test_table_negotiation_is_a_boolean_resource_selection():
    assert ResourceSelection("widgets", "owned.example.test", server_columns=True).server_columns
    with pytest.raises(AppError):
        ResourceSelection(server_columns="yes")
