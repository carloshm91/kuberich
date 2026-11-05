"""Overview health, exact predicates and independently scoped metric quantities."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.history import HistorySnapshot, HistoryStatus
from kuberich.domain.metrics import MetricReport, MetricStatus, ResourceAmount
from kuberich.domain.pulse import (
    FAMILIES,
    PulseDrilldown,
    PulseHealth,
    PulsePredicate,
    PulseScope,
    PulseSnapshot,
    PulseSource,
    PulseStatus,
    expire_metrics,
    health,
    overview_metrics,
    pod_budgets,
    predicates,
    rows,
)
from kuberich.domain.resources import ResourceSnapshot, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ViewStatus, ViewStore
from kuberich.errors import AppError
from kuberich.services.pulse import PulseAccumulator
from tests.support.metrics import NOW, sample, samples
from tests.support.pulse import pulse_object, pulse_record, pulse_resource, pulse_snapshot


def test_pulse_scope_is_explicit_and_never_an_api_resource():
    session = SessionIdentity("owned", 1)
    assert PulseScope(session, None).session is session
    assert PulseScope(session, "team").namespace == "team"
    with pytest.raises(AppError):
        PulseScope(session, "INVALID")
    scope = PulseScope(session, "team")
    snapshot = PulseSnapshot(scope)
    assert snapshot.history is None and snapshot.node_metrics.cpu.usage is None
    target = PulseDrilldown(pulse_resource(), "team")
    assert target.predicate is PulsePredicate.ALL and target.query.empty and target.uid is None


@pytest.mark.parametrize("name", [name for _, name in FAMILIES])
def test_each_supported_resource_family_has_observed_healthy_and_unknown_states(name):
    assert health(pulse_record(name)) is PulseHealth.HEALTHY
    assert health(pulse_record(name, status={})) is PulseHealth.UNKNOWN
    assert health(replace(pulse_record(name), metadata_only=True)) is PulseHealth.UNKNOWN


@pytest.mark.parametrize(
    "conditions,expected",
    [
        ([{"type": "Ready", "status": "False"}], PulseHealth.DEGRADED),
        ([{"type": "Ready", "status": "Unknown"}], PulseHealth.UNKNOWN),
        (
            [{"type": "Ready", "status": "True"}, {"type": "DiskPressure", "status": "True"}],
            PulseHealth.DEGRADED,
        ),
        (
            [{"type": "Ready", "status": "True"}, {"type": "Ready", "status": "False"}],
            PulseHealth.UNKNOWN,
        ),
        (None, PulseHealth.UNKNOWN),
        ({}, PulseHealth.UNKNOWN),
        ([{}] * 129, PulseHealth.UNKNOWN),
        ([None, {}, {"type": "Ready", "status": {}}], PulseHealth.UNKNOWN),
    ],
)
def test_node_health_requires_noncontradictory_readiness_and_preserves_pressure(
    conditions, expected
):
    record = pulse_record("nodes", status={"conditions": conditions})
    assert health(record) is expected


@pytest.mark.parametrize(
    "phase,ready,expected",
    [
        ("Succeeded", None, PulseHealth.COMPLETED),
        ("Failed", None, PulseHealth.DEGRADED),
        ("Pending", None, PulseHealth.DEGRADED),
        ("Running", "True", PulseHealth.HEALTHY),
        ("Running", "False", PulseHealth.DEGRADED),
        ("Running", "Unknown", PulseHealth.UNKNOWN),
        ("Running", None, PulseHealth.UNKNOWN),
        (None, None, PulseHealth.UNKNOWN),
        ("Other", "True", PulseHealth.UNKNOWN),
        ({}, None, PulseHealth.UNKNOWN),
    ],
)
def test_pod_phases_and_readiness_are_distinct(phase, ready, expected):
    record = pulse_record(
        status={"phase": phase, "conditions": [{"type": "Ready", "status": ready}]}
    )
    assert health(record) is expected


@pytest.mark.parametrize(
    "status,spec,expected",
    [
        ({"conditions": [{"type": "Failed", "status": "True"}]}, {}, PulseHealth.DEGRADED),
        ({"conditions": [{"type": "Complete", "status": "True"}]}, {}, PulseHealth.COMPLETED),
        ({"conditions": [{"type": "Failed", "status": "Unknown"}]}, {}, PulseHealth.UNKNOWN),
        ({"active": 1}, {"suspend": True}, PulseHealth.UNKNOWN),
        ({"active": 1, "failed": 1}, {}, PulseHealth.DEGRADED),
        ({"active": 0}, {}, PulseHealth.UNKNOWN),
        ({"active": -1, "failed": "invalid"}, {}, PulseHealth.UNKNOWN),
        ({"active": True}, {}, PulseHealth.UNKNOWN),
    ],
)
def test_job_completion_failure_activity_and_suspension(status, spec, expected):
    assert health(pulse_record("jobs", status=status, spec=spec)) is expected


@pytest.mark.parametrize("spec", [{"suspend": True}, {}, {"schedule": 1}])
def test_cronjob_declaration_or_suspension_does_not_establish_health(spec):
    assert health(pulse_record("cronjobs", spec=spec)) is PulseHealth.UNKNOWN


@pytest.mark.parametrize(
    "timestamp",
    [None, "x" * 65, "invalid", "2026-11-04T12:00:00", "2026-11-04T11:00:00Z"],
)
def test_cronjob_latest_schedule_requires_an_observed_success_with_valid_time(timestamp):
    status = {"lastScheduleTime": "2026-11-04T12:00:00Z", "lastSuccessfulTime": timestamp}
    assert health(pulse_record("cronjobs", status=status)) is PulseHealth.UNKNOWN


@pytest.mark.parametrize("name", ["deployments", "replicasets", "statefulsets", "daemonsets"])
@pytest.mark.parametrize("observed", [None, 0])
def test_controller_generation_must_have_been_observed(name, observed):
    value = pulse_object(name)
    value["status"]["observedGeneration"] = observed
    assert health(resource_record(pulse_resource(name), value)) is PulseHealth.UNKNOWN


@pytest.mark.parametrize(
    "name,field,value,expected",
    [
        ("deployments", "readyReplicas", 0, PulseHealth.DEGRADED),
        ("deployments", "updatedReplicas", "1", PulseHealth.UNKNOWN),
        ("deployments", "readyReplicas", 2**63, PulseHealth.UNKNOWN),
        ("replicasets", "availableReplicas", 0, PulseHealth.DEGRADED),
        ("statefulsets", "updateRevision", "different", PulseHealth.DEGRADED),
        ("daemonsets", "desiredNumberScheduled", -1, PulseHealth.UNKNOWN),
        ("daemonsets", "numberAvailable", 0, PulseHealth.DEGRADED),
    ],
)
def test_workload_counts_and_revisions_use_typed_observed_values(name, field, value, expected):
    manifest = pulse_object(name)
    manifest["status"][field] = value
    assert health(resource_record(pulse_resource(name), manifest)) is expected


@pytest.mark.parametrize(
    "condition,expected",
    [
        ({"type": "Available", "status": "False"}, PulseHealth.DEGRADED),
        ({"type": "Progressing", "status": "False"}, PulseHealth.DEGRADED),
        ({"type": "ReplicaFailure", "status": "True"}, PulseHealth.DEGRADED),
        ({"type": "Available", "status": "Unknown"}, PulseHealth.UNKNOWN),
    ],
)
def test_workload_conditions_cannot_be_hidden_by_replica_counts(condition, expected):
    manifest = pulse_object("deployments")
    manifest["status"]["conditions"] = [condition]
    assert health(resource_record(pulse_resource("deployments"), manifest)) is expected


def test_missing_generation_defaults_and_unknown_kind_remain_explicit():
    value = pulse_object("deployments")
    del value["metadata"]["generation"]
    value["spec"] = {}
    assert health(resource_record(pulse_resource("deployments"), value)) is PulseHealth.UNKNOWN
    value["metadata"]["generation"] = 1
    assert health(resource_record(pulse_resource("deployments"), value)) is PulseHealth.HEALTHY
    value["spec"] = {"replicas": None}
    assert health(resource_record(pulse_resource("deployments"), value)) is PulseHealth.UNKNOWN
    resource = replace(pulse_resource(), name="other", kind="Other")
    value = pulse_object()
    value["kind"] = "Other"
    value["status"]["observedGeneration"] = 1
    assert health(resource_record(resource, value)) is PulseHealth.UNKNOWN
    value["status"] = []
    assert health(resource_record(resource, value)) is PulseHealth.UNKNOWN


@pytest.mark.parametrize("name", ["deployments", "replicasets", "statefulsets", "daemonsets"])
@pytest.mark.parametrize("generation", [None, "1", True, -1])
def test_controller_health_cannot_trust_replica_status_without_valid_generation(name, generation):
    value = pulse_object(name)
    value["metadata"]["generation"] = generation
    assert health(resource_record(pulse_resource(name), value)) is PulseHealth.UNKNOWN


@pytest.mark.parametrize("predicate", list(PulsePredicate))
def test_predicates_apply_exactly_the_same_membership_in_counts_and_drilldowns(predicate):
    records = [pulse_record("nodes"), pulse_record(), pulse_record("jobs")]
    for phase in ("Running", "Pending", "Succeeded", "Failed", "Unknown"):
        for state in ("True", "False", "Unknown"):
            records.append(
                pulse_record(
                    status={"phase": phase, "conditions": [{"type": "Ready", "status": state}]}
                )
            )
    records.append(
        pulse_record(
            "nodes",
            spec={"unschedulable": True},
            status={
                "conditions": [
                    {"type": "Ready", "status": "False"},
                    {"type": "MemoryPressure", "status": "True"},
                ]
            },
        )
    )
    selected = [record for record in records if predicate.matches(record)]
    source = PulseSource("pods", pulse_resource(), "team", PulseStatus.VALID, NOW, True)
    counts = {predicate: len(selected)}
    row = next((row for row in rows(source, counts) if row.drilldown.predicate is predicate), None)
    if row is not None:
        assert row.count == len(selected)
        assert row.drilldown.query == predicate.query
    assert isinstance(predicate.query.parameters, dict)
    if predicate is not PulsePredicate.ALL:
        assert (
            not predicate.matches(replace(pulse_record(), metadata_only=True))
            or predicate is PulsePredicate.UNKNOWN
        )


def test_node_and_pod_predicates_have_exact_field_selectors_and_no_generic_error_filter():
    assert PulsePredicate.NODE_CORDONED.query.field_selector == "spec.unschedulable=true"
    assert (
        PulsePredicate.POD_UNSCHEDULED.query.field_selector == "status.phase=Pending,spec.nodeName="
    )
    assert PulsePredicate.HEALTHY.query.empty
    pending = pulse_object(status={"phase": "Pending"}, spec={"nodeName": "node"})
    assert not PulsePredicate.POD_UNSCHEDULED.matches(resource_record(pulse_resource(), pending))
    assert not PulsePredicate.NODE_READY.matches(pulse_record())
    assert not PulsePredicate.POD_PENDING.matches(pulse_record("nodes"))


def test_missing_source_rows_are_unknown_and_cannot_drill_into_a_fictitious_api():
    source = PulseSource("deployments", None, "team", PulseStatus.FORBIDDEN, None)
    assert all(row.count is None and row.drilldown is None for row in rows(source, None))
    assert len(predicates("deployments")) == 5
    assert len(predicates("nodes")) == 6


def test_incremental_accumulator_reuses_prefixes_and_resets_on_restart_or_shrink():
    one, two = (
        pulse_object(identity="one"),
        pulse_object(identity="two", status={"phase": "Failed"}),
    )
    accumulator = PulseAccumulator("pods")
    assert accumulator.apply(pulse_snapshot("pods", one, complete=False))[PulsePredicate.ALL] == 1
    assert accumulator.apply(pulse_snapshot("pods", one, two))[PulsePredicate.ALL] == 2
    assert accumulator.counts[PulsePredicate.POD_FAILED] == 1
    assert accumulator.apply(pulse_snapshot("pods", two))[PulsePredicate.POD_FAILED] == 1
    assert (
        accumulator.apply(pulse_snapshot("pods", one, version="replacement"))[
            PulsePredicate.POD_FAILED
        ]
        == 0
    )
    assert accumulator.apply(pulse_snapshot("pods"))[PulsePredicate.ALL] == 0
    assert accumulator.apply(pulse_snapshot("pods", one))[PulsePredicate.ALL] == 1


def test_node_capacity_and_real_usage_stay_distinct_from_pod_usage_and_budgets():
    nodes = pulse_snapshot("nodes", pulse_object("nodes", "node"))
    node_metrics = overview_metrics(
        nodes,
        samples(sample("node", cpu="2", memory="2Gi", namespace=None), name="nodes"),
        nodes,
        NOW,
    )
    pods = pulse_snapshot("pods", pulse_object())
    pod_metrics = overview_metrics(pods, samples(sample()), pods, NOW)
    assert node_metrics.status is pod_metrics.status is MetricStatus.VALID
    assert node_metrics.cpu.usage == 2 and node_metrics.cpu.capacity == 4
    assert node_metrics.cpu.allocatable == Decimal("3.5")
    assert node_metrics.memory.capacity == 8 * 2**30
    assert node_metrics.cpu.request is node_metrics.cpu.limit is None
    assert pod_metrics.cpu.usage == Decimal(".25") and pod_metrics.cpu.request == Decimal(".1")
    assert pod_metrics.cpu.capacity is None


@pytest.mark.parametrize("name", ["pods", "nodes"])
@pytest.mark.parametrize(
    "mode",
    [
        "absent",
        "incomplete",
        "replacement",
        "unverified",
        "empty",
        "partial",
        "missing-field",
        "stale",
    ],
)
def test_missing_incomplete_stale_and_recreated_membership_never_fabricates_current_zero(
    name, mode
):
    selected = pulse_snapshot(name, pulse_object(name))
    metrics = samples(sample(namespace=None if name == "nodes" else "team"), name=name)
    after = selected
    if mode == "absent":
        metrics = None
    elif mode == "incomplete":
        selected = replace(selected, collection=replace(selected.collection, complete=False))
    elif mode == "replacement":
        value = pulse_object(name)
        value["metadata"]["uid"] = "replacement"
        after = pulse_snapshot(name, value)
    elif mode == "unverified":
        after = None
    elif mode == "empty":
        metrics = replace(metrics, items=())
        selected = replace(selected, items=())
        after = selected
    elif mode == "partial":
        metrics = replace(metrics, collection=replace(metrics.collection, complete=False))
    elif mode == "missing-field":
        value = pulse_object(name)
        if name == "nodes":
            value["status"].pop("capacity")
        selected = pulse_snapshot(name, value)
        after = selected
    else:
        metrics = samples(
            sample(namespace=None if name == "nodes" else "team", now=NOW - timedelta(seconds=61)),
            name=name,
        )
    result = overview_metrics(selected, metrics, after, NOW)
    if mode in {"absent", "replacement", "unverified", "empty", "stale"}:
        assert result.cpu.usage is None
    if mode in {"incomplete", "replacement", "unverified", "partial"}:
        assert result.cpu.uncertain and result.cpu.partial
    if mode == "missing-field" and name == "nodes":
        assert result.cpu.capacity is None


def test_completed_pods_do_not_inflate_active_requests_and_uncertain_unlimited_budgets_survive():
    active = pulse_object()
    active["spec"]["containers"][0]["resources"]["limits"] = {}
    active["spec"]["overhead"] = {"cpu": "10m"}
    completed = pulse_object(identity="completed", status={"phase": "Succeeded"})
    selected = pulse_snapshot("pods", active, completed, complete=False)
    report = pod_budgets(selected)
    assert report.cpu.unlimited and report.cpu.uncertain and report.allocation_uncertain
    assert report.cpu.request == Decimal(".1")
    report = overview_metrics(selected, samples(sample()), selected, NOW)
    assert report.cpu.request == Decimal(".1")


def test_expiry_keeps_scope_capacity_and_budget_but_clears_old_current_values_and_history():
    report = MetricReport(
        MetricStatus.VALID,
        ResourceAmount(usage=Decimal(1), request=Decimal(2), capacity=Decimal(4)),
        timestamp=NOW,
    )
    snapshot = PulseSnapshot(
        PulseScope(SessionIdentity("owned", 1), None),
        sources=(
            PulseSource("node_metrics", None, None, PulseStatus.VALID, NOW),
            PulseSource("pod_metrics", None, "team", PulseStatus.VALID, NOW),
            PulseSource("pods", pulse_resource(), "team", PulseStatus.VALID, NOW),
        ),
        node_metrics=report,
        pod_metrics=report,
        history=HistorySnapshot(HistoryStatus.VALID, observed_at=NOW),
    )
    assert expire_metrics(snapshot, NOW) == snapshot
    expired = expire_metrics(snapshot, NOW + timedelta(seconds=61))
    assert expired.node_metrics.cpu.usage is expired.pod_metrics.cpu.usage is None
    assert expired.node_metrics.cpu.capacity == 4 and expired.pod_metrics.cpu.request == 2
    assert expired.history.status is HistoryStatus.STALE
    assert expired.sources[0].status is expired.sources[1].status is PulseStatus.STALE
    assert expired.sources[2] is snapshot.sources[2]
    assert expire_metrics(replace(snapshot, history=None), NOW).history is None


def test_empty_node_overview_has_no_invented_capacity_and_no_sample_time():
    selected = ResourceSnapshot(pulse_resource("nodes"), None, "rv", ())
    result = overview_metrics(selected, None, None, NOW)
    assert result.status is MetricStatus.NO_SAMPLE
    assert result.cpu.capacity is result.cpu.usage is result.timestamp is result.window is None


def test_pulse_view_store_validates_scope_rejects_old_results_and_reports_loading():
    store = ViewStore()
    revision = store.begin("owned")
    session = SessionIdentity("owned", 1)
    connection = SessionObservation(ConnectionState.CONNECTED, "Connected", session, "team")
    store.connected(revision, connection)
    scope = PulseScope(session, "team")
    snapshot = PulseSnapshot(scope)
    assert not store.bind_pulse(revision - 1, scope)
    assert not store.apply_pulse(revision, snapshot)
    for invalid in (
        replace(scope, namespace=None),
        replace(scope, session=SessionIdentity("owned", 1)),
    ):
        with pytest.raises(AppError, match="active connection"):
            store.bind_pulse(revision, invalid)
    store.connected(revision, replace(connection, state=ConnectionState.AUTH_ERROR))
    with pytest.raises(AppError, match="active connection"):
        store.bind_pulse(revision, scope)
    store.connected(revision, connection)
    assert store.bind_pulse(revision, scope)
    assert not store.apply_pulse(revision - 1, snapshot)
    assert not store.apply_pulse(revision, replace(snapshot, scope=replace(scope, namespace=None)))
    source = PulseSource("pods", pulse_resource(), "team", PulseStatus.LOADING, None)
    snapshot = replace(snapshot, sources=(source,))
    assert store.apply_pulse(revision, snapshot)
    assert (
        store.observation.status is ViewStatus.LOADING and "Loading 1" in store.observation.message
    )
    assert "partial/unavailable" in store.observation.message
    snapshot = replace(snapshot, sources=(replace(source, status=PulseStatus.VALID),))
    assert store.apply_pulse(revision, snapshot)
    assert (
        store.observation.status is ViewStatus.LIVE
        and "Observed sources" in store.observation.message
    )
    assert "partial/unavailable" not in store.observation.message
    store.begin("owned", connection)
    assert store.observation.pulse is None
    assert not store.apply_pulse(revision, snapshot)
