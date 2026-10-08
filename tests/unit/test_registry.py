"""Resource semantics, typed ordering, unknowns and secret-free display contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kubetrol.domain.registry import (
    RESOURCE_ALIASES,
    STANDARD_RESOURCES,
    order_resources,
    quantity,
    resource_row,
    resource_selection,
)
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.commands import CommandService, ResourceCommand, suggestions
from kubetrol.services.filtering import filter_rows
from tests.support.standard import api, row_record

EXPECTED = (
    ("10", "12", "11", "9"),
    ("12", "11", "10"),
    ("10", "12", "11", "9"),
    ("12", "11", "10", "9"),
    ("Active", "10", "12", "1", "2"),
    ("*/5 * * * *", "false", "1", "2026-10-01T12:00:00Z"),
    ("ClusterIP", "10.0.0.2", "192.0.2.1", "8080/TCP"),
    ("1", "1", "8080/TCP"),
    ("owned", "owned.example", "ingress.example"),
    ("1", "1"),
    ("Opaque", "1"),
    ("Ready", "control-plane", "v1.36.4"),
    ("Bound", "owned-volume", "2Gi", "ReadWriteOnce", "owned"),
    ("2Gi", "ReadWriteOnce", "Retain", "Bound", "team/owned-claim", "owned"),
    ("kubernetes.io/no-provisioner", "Retain", "Immediate", "false"),
)


@pytest.mark.parametrize(
    "definition,expected",
    tuple(zip(STANDARD_RESOURCES, EXPECTED, strict=True)),
    ids=[d.name for d in STANDARD_RESOURCES],
)
def test_all_resource_columns_are_meaningful_and_endpoint_scope_is_explicit(definition, expected):
    row = resource_row(row_record(definition), definition)
    values = row.cells(datetime(2026, 10, 8, tzinfo=UTC))
    assert values == (*(("team",) if definition.namespaced else ()), "owned-one", *expected, "7d")
    assert len(values) == len(definition.columns)
    assert api(definition).group == definition.selection.group
    for alias in (definition.name, *definition.aliases):
        assert resource_selection(alias) == definition.selection
        assert CommandService(AccessPolicy(True)).resolve(alias) == ResourceCommand(definition)
    assert [column.key for column in definition.columns][-1] == "age"
    assert len(set(column.key for column in definition.columns)) == len(definition.columns)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1Ki", 1024),
        ("2Gi", 2147483648),
        ("1G", 1000000000),
        ("500m", Decimal("0.5")),
        ("1e3", 1000),
        ("1E", 10**18),
        (".5", Decimal("0.5")),
        ("0", 0),
        ("+2", 2),
    ],
)
def test_storage_quantity_sort_values(value, expected):
    assert quantity(value).sort == expected


@pytest.mark.parametrize(
    "value", [None, True, "", "bad", "-1Gi", "NaN", "1e999999", "1e-999999", "9" * 65]
)
def test_unknown_and_unbounded_quantities_are_not_zero(value):
    assert quantity(value).sort is None


def test_numeric_capacity_sort_and_unknown_last_in_both_directions():
    definition = RESOURCE_ALIASES["pv"]
    rows = tuple(
        resource_row(
            row_record(
                definition, name=name, overrides={"spec": {"capacity": {"storage": capacity}}}
            ),
            definition,
        )
        for name, capacity in (
            ("large", "2Gi"),
            ("unknown", "bad"),
            ("small", "900M"),
            ("medium", "1Gi"),
        )
    )
    index = [c.key for c in definition.columns].index("capacity")
    assert [r.name for r in order_resources(rows, index)] == ["small", "medium", "large", "unknown"]
    assert [r.name for r in order_resources(rows, index, True)] == [
        "large",
        "medium",
        "small",
        "unknown",
    ]
    age_index = len(definition.columns) - 1
    missing = resource_row(
        replace(row_record(definition, name="no-age"), created_at=None), definition
    )
    assert order_resources((*rows, missing), age_index, True)[-1] is missing
    assert missing.cells(datetime.now(UTC))[-1] == "—"


@pytest.mark.parametrize("name", ["cm", "sec"])
def test_payload_never_enters_rows_or_filter(name):
    definition = RESOURCE_ALIASES[name]
    row = resource_row(row_record(definition), definition)
    assert "private-" not in repr(row)
    assert filter_rows((row,), "private-").rows == ()
    assert filter_rows((row,), "owned-one").rows == (row,)


def test_identity_required_and_missing_status_is_unknown_while_omitted_counter_is_zero():
    definition = RESOURCE_ALIASES["deploy"]
    with pytest.raises(AppError, match="UID"):
        resource_row(replace(row_record(definition), uid=None), definition)
    missing = resource_row(
        row_record(definition, overrides={"spec": {"replicas": True}, "status": {}}), definition
    )
    assert missing.values[2].text == "—" and missing.values[3].text == "—"
    present = resource_row(
        row_record(definition, overrides={"status": {"observedGeneration": 1}}), definition
    )
    assert present.values[2].text == "0"
    assert resource_selection("pods").group == ""


@pytest.mark.parametrize("alias", list(RESOURCE_ALIASES))
def test_commands_validate_namespace_and_do_not_advertise_cluster_scoped_arguments(alias):
    definition = RESOURCE_ALIASES[alias]
    commands = CommandService(AccessPolicy(True))
    if definition.namespaced:
        assert commands.resolve(alias + " *") == ResourceCommand(definition, "*")
        assert commands.resolve(alias + " team") == ResourceCommand(definition, "team")
        assert suggestions(alias + " t", (), ("team",)) == (alias + " team",)
        with pytest.raises(AppError):
            commands.resolve(alias + " ../escape")
    else:
        with pytest.raises(AppError, match="cluster-scoped"):
            commands.resolve(alias + " team")
        assert suggestions(alias + " t", (), ("team",)) == ()


@pytest.mark.parametrize("name", [d.name for d in STANDARD_RESOURCES])
def test_malformed_optional_fields_stay_bounded_and_safe(name):
    definition = RESOURCE_ALIASES[name]
    row = resource_row(
        row_record(
            definition,
            overrides={
                "spec": [],
                "status": "unexpected",
                "data": [],
                "binaryData": None,
                "subsets": True,
                "provisioner": "[red]\x1b" * 1000,
            },
        ),
        definition,
    )
    assert all(len(value.text) <= 256 for value in row.values)


@pytest.mark.parametrize(
    "status,expected",
    [
        ({}, "Pending"),
        ({"active": 2}, "Active"),
        (
            {
                "conditions": [
                    {"type": "Complete", "status": "False"},
                    {"type": "Other", "status": "True"},
                    {"type": "Failed", "status": "True"},
                ]
            },
            "Failed",
        ),
        ({"conditions": [{"type": "Complete", "status": "True"}]}, "Complete"),
    ],
)
def test_job_lifecycle_conditions(status, expected):
    definition = RESOURCE_ALIASES["job"]
    row = resource_row(row_record(definition, overrides={"status": status}), definition)
    assert row.values[2].text == expected
    row = resource_row(
        row_record(definition, overrides={"spec": {"suspend": True}, "status": {}}), definition
    )
    assert row.values[2].text == "Suspended"


@pytest.mark.parametrize(
    "ready,expected", [("False", "NotReady"), ("Unknown", "Unknown"), (None, "Unknown")]
)
def test_node_conditions_and_unschedulable(ready, expected):
    definition = RESOURCE_ALIASES["no"]
    row = resource_row(
        row_record(
            definition,
            overrides={
                "spec": {"unschedulable": True},
                "status": {
                    "conditions": [
                        {"type": "Other", "status": "True"},
                        {"type": "Ready", "status": ready},
                    ]
                },
            },
        ),
        definition,
    )
    assert row.values[1].text == expected + ",SchedulingDisabled"


@pytest.mark.parametrize("counter", [-1, True, "12", 2**63])
def test_invalid_counts_do_not_become_zero(counter):
    definition = RESOURCE_ALIASES["deploy"]
    row = resource_row(
        row_record(
            definition,
            overrides={"status": {"readyReplicas": counter}, "spec": {"replicas": counter}},
        ),
        definition,
    )
    assert row.values[2].sort is None and row.values[3].sort is None


def test_service_external_name_addresses_protocol_and_literal_bounds():
    definition = RESOURCE_ALIASES["svc"]
    row = resource_row(
        row_record(
            definition, overrides={"spec": {"type": "ExternalName", "externalName": "dns.example"}}
        ),
        definition,
    )
    assert row.values[4].text == "dns.example"
    row = resource_row(
        row_record(
            definition,
            overrides={
                "status": {},
                "spec": {
                    "externalIPs": ["192.0.2.3", 1],
                    "ports": [{"port": 53, "protocol": "UDP"}, None],
                },
            },
        ),
        definition,
    )
    assert row.values[4].text == "192.0.2.3"
    assert row.values[5].text == "53/UDP,—/TCP"
    row = resource_row(
        row_record(definition, overrides={"spec": {"clusterIP": "[red]\x1b" * 1000}}), definition
    )
    assert len(row.values[3].text) == 256


@pytest.mark.parametrize("timestamp", ["not-a-time", "2026-10-01T00:00:00"])
def test_unknown_and_naive_schedule_time_never_sort_as_known(timestamp):
    definition = RESOURCE_ALIASES["cj"]
    row = resource_row(
        row_record(definition, overrides={"status": {"lastScheduleTime": timestamp}}), definition
    )
    assert row.values[-2].sort is None


def test_timestamp_sort_uses_instant_not_timezone_spelling():
    definition = RESOURCE_ALIASES["cj"]
    early = resource_row(
        row_record(
            definition,
            name="early",
            overrides={"status": {"lastScheduleTime": "2026-10-01T10:00:00+02:00"}},
        ),
        definition,
    )
    late = resource_row(
        row_record(
            definition,
            name="late",
            overrides={"status": {"lastScheduleTime": "2026-10-01T09:00:00Z"}},
        ),
        definition,
    )
    assert order_resources((late, early), len(definition.columns) - 2) == (early, late)


@pytest.mark.parametrize("definition", STANDARD_RESOURCES, ids=[d.name for d in STANDARD_RESOURCES])
def test_initial_cli_passes_the_real_resource_command_to_launcher(
    tmp_path, monkeypatch, definition
):
    from kubetrol import cli

    captured = []
    monkeypatch.setattr(
        cli,
        "run_terminal",
        lambda settings, logger, **kwargs: captured.append(kwargs["initial_command"]),
    )
    command = definition.aliases[0] + (" team" if definition.namespaced else "")
    assert cli.main(["--readonly", "--command", command]) == 0
    assert captured == [ResourceCommand(definition, "team" if definition.namespaced else None)]
