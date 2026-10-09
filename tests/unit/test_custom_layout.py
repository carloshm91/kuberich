"""Generic projection boundaries before the B06 widget integration."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.custom import CustomLayout
from kuberich.domain.inspection import REDACTED
from kuberich.domain.registry import order_resources
from kuberich.domain.resources import ServerColumn, ServerRow, resource_record
from kuberich.errors import AppError
from tests.support.tables import custom_item, custom_resource


def captured(headers, cells, *, name="one", namespace="team"):
    record = resource_record(
        custom_resource(namespaced=namespace is not None),
        custom_item(name, namespace=namespace, uid="owned-" + name),
        namespace,
    )
    return replace(record, server=ServerRow(headers, tuple(cells), 0))


def test_generic_layout_owns_identity_fallback_and_explicit_wide_selection():
    headers = (
        ServerColumn("Name", "string", "name"),
        ServerColumn("Level", "integer"),
        ServerColumn("Age", "date"),
        ServerColumn("Extra", "string", priority=1),
    )
    resource = custom_resource()
    layout = CustomLayout.build(resource, headers)
    assert layout.visible == (1,)
    assert layout.definition.group == resource.group
    assert [c.key for c in layout.definition.columns] == ["namespace", "name", "c2", "age"]
    assert layout.label("c2") == "Level" and layout.label("name") == "NAME"
    row = layout.row(captured(headers, ("fake-name", 3, "99d", "wide")))
    assert [v.text for v in row.values] == ["team", "one", "3", "—"]
    assert layout.configure(("c4", "c2")).visible == (3, 1)
    assert layout.configure(()).visible == ()
    for invalid in (("unknown",), ("c2", "c2"), ("c1",), ("c3",), ("c2",) * 65):
        with pytest.raises(AppError):
            layout.configure(invalid)
        assert layout.visible == (1,)


@pytest.mark.parametrize(
    "kind,cell,text,sort",
    [
        ("boolean", True, "true", 1),
        ("boolean", False, "false", 0),
        ("integer", 12, "12", 12),
        ("number", 2.5, "2.5", 2.5),
        ("string", "[bold]Alpha", "[bold]Alpha", "[bold]alpha"),
        ("date", "2h3m", "2h3m", 7380),
        (
            "date",
            "2026-10-09T00:00:00Z",
            "2026-10-09T00:00:00Z",
            43200,
        ),
        ("date", "2026-10-09", "2026-10-09", None),
        ("date", "invalid", "invalid", None),
        ("date", "9" * 400 + "s", "9" * 400 + "s", None),
        ("integer", None, "—", None),
        ("integer", "12", "—", None),
        ("integer", 3.5, "—", None),
        ("integer", True, "—", None),
        ("integer", 2**63, "—", None),
        ("number", float("nan"), "—", None),
        ("number", float("inf"), "—", None),
        ("boolean", "false", "—", None),
    ],
)
def test_column_values_preserve_types_and_safe_unknowns(kind, cell, text, sort):
    headers = (ServerColumn("Field", kind),)
    value = (
        CustomLayout.build(custom_resource(), headers)
        .row(captured(headers, (cell,)), now=datetime(2026, 10, 9, 12, tzinfo=UTC))
        .values[2]
    )
    assert value.text == text and value.sort == sort


def test_schema_changes_and_plain_records_never_reinterpret_old_cells():
    old = (ServerColumn("Level", "integer"),)
    new = (ServerColumn("Ready", "boolean"),)
    record = captured(old, (12,))
    layout = CustomLayout.build(custom_resource(), new)
    for source in (
        record,
        replace(record, server=None),
        replace(record, server=ServerRow(new, (), 0)),
    ):
        assert layout.row(source).values[2].text == "—"
    fallback = CustomLayout.build(custom_resource(), ())
    assert [c.key for c in fallback.definition.columns] == ["namespace", "name", "age"]
    assert (
        fallback.row(replace(record, created_at=datetime(2026, 1, 1, tzinfo=UTC))).values[-1].sort
        is not None
    )
    with pytest.raises(AppError):
        layout.row(replace(record, uid=None))


def test_cluster_scope_redaction_literal_headers_and_typed_ordering():
    resource = custom_resource(namespaced=False)
    headers = (
        ServerColumn("Level", "integer"),
        ServerColumn("apiToken", "string"),
        ServerColumn("[bold]\x1bName", "string"),
    )
    layout = CustomLayout.build(resource, headers)
    rows = [
        layout.row(
            captured(headers, (number, "opaque-token", "Bearer owned"), name=name, namespace=None)
        )
        for name, number in (("ten", 10), ("two", 2), ("missing", None))
    ]
    assert [r.name for r in order_resources(tuple(rows), 1)] == ["two", "ten", "missing"]
    assert [r.name for r in order_resources(tuple(rows), 1, True)] == ["ten", "two", "missing"]
    assert rows[0].values[2].text == REDACTED and rows[0].values[2].sort is None
    assert "owned" not in rows[0].values[3].text
    assert "\x1b" not in layout.label("c3") and "[bold]" in layout.label("c3")
    opaque = CustomLayout.build(replace(resource, kind="Secret"), headers)
    assert all(
        v.text == REDACTED
        for v in opaque.row(captured(headers, (10, "token", "literal"), namespace=None)).values[
            1:-1
        ]
    )
