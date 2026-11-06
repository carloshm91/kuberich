"""Captured identity, exact content binding and explicit metadata projections."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from kuberich.domain.container_inspection import (
    MAX_GET_BYTES,
    ContainerIdentity,
    ReasonCode,
    ResolvedValue,
    SourceRead,
    SourceRef,
    build_inspection,
    container_declaration,
    metadata_table,
    object_binding,
    reference_plan,
    resolve_selected,
)
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

NOW = datetime(2026, 11, 5, tzinfo=UTC)
APP = ContainerIdentity("containers", "worker", "App")


def pod(spec=None, status=None, metadata=None):
    return resource_record(
        ApiResource("", "v1", "pods", "Pod", True, frozenset({"get"})),
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "owned-pod",
                "namespace": "team",
                "uid": "pod-uid",
                "resourceVersion": "opaque/1",
                **(metadata or {}),
            },
            "spec": spec if spec is not None else {"containers": [{"name": "worker"}]},
            "status": status or {},
        },
        "team",
    )


def snapshot(record, identity=APP, sources=(), **kwargs):
    return build_inspection(
        record,
        identity,
        sources,
        target=ResourceTarget(
            SessionIdentity("owned", 1), "", "pods", "team", record.name, record.uid
        ),
        snapshot_id=UUID(int=74),
        started_at=NOW,
        observed_at=NOW,
        reads=2,
        **kwargs,
    )


def test_canonical_binding_ignores_order_but_detects_bytes_and_hides_digest():
    record = pod()
    reversed_data = dict(reversed(list(record.manifest.items())))
    reordered = replace(record, _manifest=json.dumps(reversed_data).encode())
    binding = object_binding(record, kind="Pod")
    assert binding == object_binding(reordered, kind="Pod")
    assert binding.payload_sha256 not in repr(binding)
    assert binding != object_binding(pod(metadata={"labels": {"plain": "changed"}}), kind="Pod")
    assert binding.resource_version == "opaque/1"


@pytest.mark.parametrize(
    "change",
    ["metadata-only", "size", "api", "kind", "metadata", "empty", "type", "length", "inconsistent"],
)
def test_full_binding_rejects_incomplete_or_inconsistent_objects_without_payload(change):
    record = pod()
    data = record.manifest
    if change == "metadata-only":
        record = replace(record, metadata_only=True)
    elif change == "size":
        record = replace(
            record, _manifest=b" " * MAX_GET_BYTES + json.dumps(record.manifest).encode()
        )
    elif change == "inconsistent":
        record = replace(record, uid="different")
    else:
        if change == "api":
            data["apiVersion"] = "other/v1"
        elif change == "kind":
            data["kind"] = "Secret"
        elif change == "metadata":
            data["metadata"] = []
        else:
            data["metadata"]["uid"] = {"empty": "", "type": 1, "length": "x" * 4097}[change]
        record = replace(record, _manifest=json.dumps(data).encode())
    with pytest.raises(AppError):
        object_binding(record, kind="Pod")


@pytest.mark.parametrize(
    "field,kind,restart,statusfield",
    [
        ("containers", "App", None, "containerStatuses"),
        ("initContainers", "Init", None, "initContainerStatuses"),
        ("initContainers", "Sidecar", "Always", "initContainerStatuses"),
        ("ephemeralContainers", "Ephemeral", None, "ephemeralContainerStatuses"),
    ],
)
def test_family_and_name_match_status_and_keep_image_origins(field, kind, restart, statusfield):
    declaration = {"name": "worker", "image": "opaque:declared", "imagePullPolicy": "Never"}
    if restart:
        declaration["restartPolicy"] = restart
    record = pod(
        {field: [declaration], "imagePullSecrets": [{"name": "pull-name"}, {"name": 42}]},
        {
            statusfield: [
                {"name": "unrelated", "image": "wrong"},
                {
                    "name": "worker",
                    "image": "opaque:status",
                    "imageID": "runtime://unparsed",
                    "containerID": "anything",
                },
            ]
        },
    )
    observed = snapshot(record, ContainerIdentity(field, "worker", kind))
    assert observed.image.declared == "opaque:declared"
    assert observed.image.status_image == "opaque:status"
    assert observed.image.image_id == "runtime://unparsed"
    assert observed.image.pull_secret_names == ("pull-name",)
    table = metadata_table(observed, "image")
    assert len({row.key for row in table.rows}) == len(table.rows)
    assert table.rows[0].cells == ("declaration", "image", "opaque:declared")
    assert table.rows[2].cells == ("status", "image", "opaque:status")


@pytest.mark.parametrize(
    "data,identity",
    [
        ({}, APP),
        ({"spec": []}, APP),
        ({"spec": {"containers": {}}}, APP),
        ({"spec": {"containers": [{"name": "worker"}, {"name": "worker"}]}}, APP),
        (
            {"spec": {"containers": [{"name": "worker"}]}},
            ContainerIdentity("containers", "worker", "Init"),
        ),
        ({"spec": {"other": [{"name": "worker"}]}}, ContainerIdentity("other", "worker", "Init")),
        ({}, ContainerIdentity("containers", "", "App")),
        ({}, ContainerIdentity("containers", "x" * 4097, "App")),
    ],
)
def test_captured_family_identity_cannot_be_guessed_or_truncated(data, identity):
    with pytest.raises(AppError):
        container_declaration(data, identity)


def test_reference_plan_deduplicates_in_first_use_order_and_preserves_per_use_provenance():
    record = pod(
        {
            "containers": [
                {
                    "name": "worker",
                    "envFrom": [
                        {"secretRef": {"name": "one", "optional": True}, "prefix": "A_"},
                        {"configMapRef": {"name": "two"}},
                        {"secretRef": {"name": "one"}, "prefix": "B_"},
                    ],
                    "env": [
                        {
                            "name": "X",
                            "valueFrom": {"secretKeyRef": {"name": "one", "key": "plain"}},
                        }
                    ],
                }
            ]
        }
    )
    plan = reference_plan(record, APP)
    assert plan.total == 2 and not plan.limited
    assert plan.refs == (SourceRef("Secret", "team", "one"), SourceRef("ConfigMap", "team", "two"))
    reads = tuple(SourceRead(ref, "not-found", None, NOW) for ref in plan.refs)
    observed = snapshot(record, sources=reads)
    uses = observed.sources[0].references
    assert [(use.optional, use.prefix, use.key) for use in uses] == [
        (True, "A_", None),
        (False, "B_", None),
        (False, "", "plain"),
    ]
    assert metadata_table(observed, "sources").rows[0].cells[3] == "not-found"


def test_literal_hidden_snapshots_and_selected_result_reprs_are_value_free():
    marker = "harmless_value_with_private_marker"
    record = pod({"containers": [{"name": "worker", "env": [{"name": "NORMAL", "value": marker}]}]})
    observed = snapshot(record)
    result = resolve_selected(observed, ("env", 0, None), record, ())
    assert result == ResolvedValue(marker, True, ())
    for value in (
        observed,
        result,
        SourceRead(SourceRef("ConfigMap", "team", "one"), "available", record, NOW),
        *(metadata_table(observed, section) for section in ("environment", "image", "sources")),
    ):
        assert marker not in repr(value)
        assert observed.pod.payload_sha256 not in repr(value)


def test_missing_status_and_omitted_oversized_image_have_explicit_metadata():
    record = pod({"containers": [{"name": "worker", "image": "i" * 4097}]})
    observed = snapshot(record)
    assert observed.image.declared is None and observed.image.status_image is None
    assert not observed.complete and ReasonCode.METADATA_LIMIT in observed.notices
    assert metadata_table(observed, "image").rows[0].cells[-1] == "unavailable"


def test_public_metadata_projection_enforces_total_byte_budget_without_partial_rows():
    record = pod(
        {
            "containers": [
                {"name": "worker", "env": [{"name": "NORMAL", "value": "never projected"}]}
            ]
        }
    )
    observed = snapshot(record)
    # A projection is independently bounded even for externally assembled records.
    entries = tuple(
        replace(observed.entries[0], id=("env", ordinal, None), name="A" * 253, path="P" * 253)
        for ordinal in range(4096)
    )
    external = replace(observed, entries=entries)
    table = metadata_table(external, "environment")
    assert len(table.rows) == 1 and table.rows[0].key == "limit"
    assert set(table.rows[0].cells) == {"(metadata omitted: limit)"}
    assert "never projected" not in repr(table)


@pytest.mark.parametrize(
    "field", ["image", "imageID", "containerID", "imagePullSecrets", "imagePullPolicy"]
)
def test_each_opaque_image_field_omission_is_explicit(field):
    declaration = {"name": "worker"}
    spec = {"containers": [declaration]}
    status = {"containerStatuses": [{"name": "worker"}]}
    if field == "imagePullSecrets":
        spec[field] = [{"name": "x" * 4097}]
    elif field == "imagePullPolicy":
        declaration[field] = "x" * 4097
    else:
        status["containerStatuses"][0][field] = "x" * 4097
    observed = snapshot(pod(spec, status))
    assert not observed.complete and ReasonCode.METADATA_LIMIT in observed.notices
    assert "x" * 4097 not in repr(observed)
