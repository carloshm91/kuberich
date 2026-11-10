"""Deterministic identity, data-risk, consent, PDB and retry decisions."""

import copy
from dataclasses import replace

import pytest

from kuberich.domain.node_maintenance import (
    DrainOptions,
    MaintenanceMode,
    PodReview,
    consent_blockers,
    eviction_body,
    eviction_receipt,
    matching_pdb,
    matching_pdbs,
    node_patch,
    node_state,
    pod_facts,
    retry_delay,
)
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from tests.support.node_maintenance import NODE, PDB, POD, pod

TARGET = ResourceTarget(SessionIdentity("synthetic", 1), "", "nodes", None, "node-one", "node-uid")


def node():
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": "node-one", "uid": "node-uid", "resourceVersion": "opaque/rv"},
        "spec": {},
    }


def pdb():
    return {
        "apiVersion": "policy/v1",
        "kind": "PodDisruptionBudget",
        "metadata": {
            "name": "budget",
            "namespace": "team",
            "uid": "pdb-uid",
            "resourceVersion": "rv",
            "generation": 3,
        },
        "spec": {"selector": {}, "minAvailable": "50%", "maxUnavailable": 1},
        "status": {
            "observedGeneration": 3,
            "disruptionsAllowed": 0,
            "currentHealthy": 2,
            "desiredHealthy": 2,
        },
    }


def record(value):
    return resource_record(POD, value, value["metadata"]["namespace"])


def reviewed(**kwargs):
    target = replace(TARGET, resource="pods", namespace="team", name="one", uid="pod-uid")
    values = dict(
        target=target,
        resource_version="rv",
        owner="owner",
        managed=True,
        daemonset=False,
        mirror=False,
        terminating=False,
        phase="Running",
        ready=True,
        storage=(),
        emptydir=False,
        pdbs=(),
    )
    return PodReview(**(values | kwargs))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"force": 1},
        {"delete_emptydir_data": None},
        {"leave_daemonsets": "yes"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 3601},
        {"timeout_seconds": True},
    ],
)
def test_options_reject_implicit_consent_and_unbounded_deadline(kwargs):
    with pytest.raises(AppError):
        DrainOptions(**kwargs)


def test_node_default_state_and_exact_patch():
    original = resource_record(NODE, node())
    assert node_state(original, TARGET) is False
    for mode, value in [
        (MaintenanceMode.CORDON, True),
        (MaintenanceMode.DRAIN, True),
        (MaintenanceMode.UNCORDON, False),
    ]:
        patch = node_patch(NODE, TARGET, original, mode)
        assert patch.body.endswith(b'"value":' + str(value).lower().encode() + b"}]")
    data = node()
    data["spec"]["unschedulable"] = True
    assert node_state(resource_record(NODE, data), TARGET)


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", "other"),
        ("name", "other"),
        ("resourceVersion", None),
        ("deletionTimestamp", "2026-01-01T00:00:00Z"),
    ],
)
def test_node_identity_and_deletion_fail_closed(field, value):
    data = node()
    data["metadata"][field] = value
    with pytest.raises(AppError):
        node_state(resource_record(NODE, data), TARGET)


@pytest.mark.parametrize("value", [None, "true", 1, {}, []])
def test_node_malformed_scheduling_not_coerced(value):
    data = node()
    data["spec"]["unschedulable"] = value
    with pytest.raises(AppError):
        node_state(resource_record(NODE, data), TARGET)


def test_domain_rejects_wrong_record_type_and_scope():
    original = resource_record(NODE, node())
    with pytest.raises(AppError):
        node_state(replace(original, namespace="team"), TARGET)
    wrong = copy.deepcopy(node())
    wrong["kind"] = "Other"
    with pytest.raises(AppError):
        node_state(replace(original, _manifest=__import__("json").dumps(wrong).encode()), TARGET)


def test_eviction_body_contains_only_original_preconditions():
    item = reviewed()
    assert b'"gracePeriodSeconds"' not in eviction_body(item.target, "opaque/version")
    with pytest.raises(AppError):
        eviction_body(TARGET, "rv")
    with pytest.raises(AppError):
        eviction_body(replace(item.target, name="bad?query"), "rv")
    with pytest.raises(AppError):
        eviction_body(item.target, "")


def test_pod_storage_readiness_and_terminal_facts_are_safe():
    data = pod(emptydir=True, mirror=True)
    data["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    data["metadata"]["finalizers"] = ["example.io/hold"]
    data["spec"]["volumes"] += [
        {"name": "host", "hostPath": {"path": "/private-path"}},
        {"name": "disk", "persistentVolumeClaim": {"claimName": "claim"}},
        {"name": "temporary", "ephemeral": {}},
    ]
    data["status"]["conditions"].append({"type": "Other", "status": "Unknown"})
    mirror, terminating, phase, ready, storage, emptydir = pod_facts(record(data), TARGET)
    assert (mirror, terminating, phase, ready, emptydir) == (True, True, "Running", True, True)
    assert len(storage) == 4 and "private-path" not in repr(storage)
    data["status"] = {}
    assert pod_facts(record(data), TARGET)[2:4] == ("Unknown", None)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("spec", "nodeName", "wrong"),
        ("metadata", "uid", None),
        ("metadata", "resourceVersion", None),
        ("metadata", "annotations", {"key": 1}),
        ("metadata", "deletionTimestamp", 1),
        ("metadata", "finalizers", "bad"),
        ("metadata", "finalizers", [None]),
        ("status", "phase", "NotPhase"),
        ("status", "phase", []),
        ("status", "conditions", {}),
        ("status", "conditions", [None]),
        ("status", "conditions", [{"type": "Ready", "status": "invalid"}]),
        ("spec", "volumes", {}),
        ("spec", "volumes", [None]),
        ("spec", "volumes", [{"name": "a", "emptyDir": {"medium": "disk"}}]),
        ("spec", "volumes", [{"name": "a", "hostPath": {"path": 1}}]),
        (
            "spec",
            "volumes",
            [{"name": "a", "persistentVolumeClaim": {"claimName": "claim", "readOnly": 1}}],
        ),
    ],
)
def test_malformed_safety_evidence_never_becomes_eligible(section, field, value):
    data = pod()
    data[section][field] = value
    with pytest.raises(AppError):
        pod_facts(record(data), TARGET)


def test_pod_scope_and_collection_limits_fail_closed():
    data = record(pod())
    with pytest.raises(AppError):
        pod_facts(replace(data, namespace=None), TARGET)
    for section, field in [
        ("spec", "volumes"),
        ("metadata", "finalizers"),
        ("status", "conditions"),
    ]:
        raw = pod()
        raw[section][field] = [{}] * 129
        with pytest.raises(AppError):
            pod_facts(record(raw), TARGET)


@pytest.mark.parametrize(
    "managed,emptydir,force,data,expected",
    [
        (False, True, False, False, 2),
        (False, True, True, False, 1),
        (False, True, False, True, 1),
        (False, True, True, True, 0),
        (True, False, False, False, 0),
    ],
)
def test_independent_consent_matrix(managed, emptydir, force, data, expected):
    assert (
        len(
            consent_blockers(
                reviewed(managed=managed, emptydir=emptydir),
                DrainOptions(force=force, delete_emptydir_data=data),
            )
        )
        == expected
    )


def test_retained_pods_and_unverified_owner_cannot_be_overridden():
    assert len(consent_blockers(reviewed(daemonset=True), DrainOptions())) == 1
    assert not consent_blockers(reviewed(daemonset=True), DrainOptions(leave_daemonsets=True))
    assert not consent_blockers(reviewed(mirror=True, managed=False, emptydir=True), DrainOptions())
    assert consent_blockers(reviewed(blockers=("unknown owner",)), DrainOptions(force=True)) == (
        "unknown owner",
    )


def test_pdb_namespace_null_empty_and_all_selector_operators():
    item = record(pod())
    raw = pdb()
    budget = resource_record(PDB, raw)
    assert matching_pdb(budget, item).status_current
    assert len(matching_pdbs((budget,), item)) == 1
    raw["spec"]["selector"] = None
    assert matching_pdb(resource_record(PDB, raw), item) is None
    raw["spec"]["selector"] = {}
    raw["metadata"]["namespace"] = "other"
    assert matching_pdb(resource_record(PDB, raw), item) is None
    raw["metadata"]["namespace"] = "team"
    raw["spec"]["selector"] = {"matchLabels": {"app": "different"}}
    assert not matching_pdbs((resource_record(PDB, raw),), item)
    raw["spec"]["selector"] = {
        "matchExpressions": [
            {"key": "app", "operator": "In", "values": ["test"]},
            {"key": "app", "operator": "Exists"},
            {"key": "other", "operator": "DoesNotExist"},
            {"key": "app", "operator": "NotIn", "values": ["other"]},
        ]
    }
    raw["spec"]["unhealthyPodEvictionPolicy"] = "AlwaysAllow"
    raw["status"]["observedGeneration"] = 2
    result = matching_pdb(resource_record(PDB, raw), item)
    assert not result.status_current and result.unhealthy_policy == "AlwaysAllow"
    raw["status"] = {}
    raw["metadata"].pop("generation")
    raw["spec"].pop("minAvailable")
    raw["spec"].pop("maxUnavailable")
    assert matching_pdb(resource_record(PDB, raw), item).disruptions_allowed is None


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("metadata", "uid", None),
        ("metadata", "generation", -1),
        ("status", "disruptionsAllowed", True),
        ("status", "observedGeneration", "3"),
        ("spec", "unhealthyPodEvictionPolicy", "Ignore"),
        ("spec", "minAvailable", -1),
        ("spec", "minAvailable", "101%"),
        ("spec", "maxUnavailable", True),
        ("spec", "selector", {"matchExpressions": [{"key": "app", "operator": "Wrong"}]}),
    ],
)
def test_pdb_malformed_evidence_blocks_complete_review(section, field, value):
    raw = pdb()
    raw[section][field] = value
    with pytest.raises(AppError):
        matching_pdb(resource_record(PDB, raw), record(pod()))


@pytest.mark.parametrize(
    "header,status,expected",
    [
        (None, None, 5),
        ("invalid", None, 5),
        ("-1", -1, 5),
        ("3", 9, 9),
        ("0", 0, 1),
        (None, True, 5),
        ("Wed, 01 Jan 2025 00:00:09 GMT", None, 9),
        ("01 Jan 2025 00:00:09", None, 9),
        ("Wed, 01 Jan 2020 00:00:09 GMT", None, 1),
        ("9" * 100, None, 10**12),
        (None, 10**400, 10**12),
    ],
)
def test_retry_hint_boundaries_and_http_dates(header, status, expected):
    assert retry_delay(header, status, 1735689600) == expected


@pytest.mark.parametrize(
    "value,accepted",
    [
        ({}, False),
        ({"status": "Success"}, False),
        ({"apiVersion": "v1", "kind": "Status", "status": "Success"}, True),
        ({"apiVersion": "v1", "kind": "Status", "status": "Failure", "code": 200}, False),
        ({"apiVersion": "v1", "kind": "Status", "status": "Success", "code": 201}, False),
    ],
)
def test_accepted_receipt_requires_actual_status_success(value, accepted):
    assert eviction_receipt(value) is accepted
