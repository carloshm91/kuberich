"""Failure families, uncertainty, stable identity and strict published-text bounds."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from kuberich.domain import cluster_diagnostics as domain
from kuberich.domain.cluster_diagnostics import (
    DiagnosticCategory as Category,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticIdentity,
    DiagnosticScope,
    bounded_diagnostic_snapshot,
    diagnose_event,
    diagnose_record,
    diagnostic_key,
    diagnostic_reported_at,
    diagnostic_text,
    diagnostic_text_bytes,
    finding_key,
    merge_native_findings,
    native_finding,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticLogMode as LogMode,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticSeverity as Severity,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticSourceKind as Kind,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticStatus as Status,
)
from kuberich.domain.diagnostic_rows import diagnostic_age, diagnostic_rows
from kuberich.errors import AppError
from tests.support.diagnostic_native import (
    DEPLOYMENTS,
    EVENTS,
    NEW_EVENTS,
    NOW,
    PODS,
    record,
    ref,
    request,
    snapshot,
    source,
)


def waiting(reason, *, previous=None, extra=None):
    entry = {
        "name": "app",
        "state": {"waiting": {"reason": reason, "message": "token=PRIVATE\x1b[31m"}},
        **(extra or {}),
    }
    if previous is not None:
        entry["lastState"] = {"terminated": previous}
    return record(status={"containerStatuses": [entry]})


def test_records_validate_scope_revision_and_are_immutable():
    req = request(ref())
    with pytest.raises(FrozenInstanceError):
        req.revision = 3
    assert not hasattr(req, "__dict__")
    for root in [
        replace(ref(), uid=None),
        replace(ref(), resource=None),
        replace(ref(), namespace=None),
        replace(ref(), namespace="other"),
        replace(ref(), api_version="v2"),
        replace(ref(), kind="Other"),
        replace(ref(), resource=replace(PODS, namespaced=False)),
        replace(ref(), name="../bad"),
    ]:
        with pytest.raises(AppError):
            request(root)
    with pytest.raises(AppError):
        DiagnosticScope(None, "team")
    with pytest.raises(AppError):
        request(namespace="INVALID")
    with pytest.raises(AppError):
        request(session=replace(req.scope.session, context="x" * 9000))
    with pytest.raises(AppError, match="scope metadata"):
        request(
            replace(ref(), name="x" * 4000, uid="y" * 4000),
            session=replace(req.scope.session, context="z" * 4000),
        )
    for revision in [0, -1, True]:
        with pytest.raises(AppError):
            request(revision=revision)
    assert request(namespace=None).scope.namespace is None
    assert domain.DiagnosticBookmark("team", ref()).root.uid == "owned-one"


@pytest.mark.parametrize(
    "reason",
    [
        "ErrImagePull",
        "ImagePullBackOff",
        "InvalidImageName",
        "ErrImageNeverPull",
        "CrashLoopBackOff",
    ],
)
def test_container_failures_are_explicit_and_sanitized(reason):
    results = diagnose_record(PODS, waiting(reason), NOW)
    assert len(results) == 1
    finding = results[0]
    assert finding.category is (
        Category.CRASH_LOOP if reason == "CrashLoopBackOff" else Category.IMAGE_PULL
    )
    assert finding.identity is DiagnosticIdentity.UID_BOUND
    assert "PRIVATE" not in repr(finding) and "\x1b" not in repr(finding)
    assert not finding.log_modes
    assert "not establish" in finding.explanation


@pytest.mark.parametrize("reason", ["BackOff", "Failed", "OOMKilled", "", None])
def test_generic_reason_restart_or_oom_does_not_establish_crash_loop(reason):
    value = waiting(
        reason, previous={"reason": "OOMKilled", "exitCode": 137}, extra={"restartCount": 9}
    )
    assert diagnose_record(PODS, value, NOW) == ()


def test_termination_context_and_exact_available_log_modes():
    value = waiting(
        "CrashLoopBackOff",
        previous={"reason": "Error", "exitCode": 1, "finishedAt": NOW.isoformat()},
        extra={"restartCount": 2},
    )
    result = diagnose_record(PODS, value, NOW)[0]
    assert result.log_modes == {LogMode.PREVIOUS}
    assert "exitCode=1" in result.evidence[1].message
    assert result.evidence[1].reported_at == NOW
    unknown = diagnose_record(PODS, waiting("CrashLoopBackOff", previous={"reason": "Error"}), NOW)[
        0
    ]
    assert "exitCode=unknown" in unknown.evidence[1].message
    value = record(
        status={"containerStatuses": [{"name": "app", "state": {"running": {}}, "ready": False}]}
    )
    assert diagnose_record(PODS, value, NOW)[0].log_modes == {LogMode.CURRENT}
    terminated = value.manifest
    terminated["status"]["containerStatuses"][0]["state"] = {"terminated": {}}
    from kuberich.domain.resources import resource_record

    assert diagnose_record(PODS, resource_record(PODS, terminated), NOW) == ()


@pytest.mark.parametrize(
    "kind,state,reason,category,severity",
    [
        ("PodScheduled", "False", "Unschedulable", Category.SCHEDULING, Severity.WARNING),
        ("Ready", "False", "", Category.READINESS, Severity.WARNING),
        ("ContainersReady", "Unknown", "", Category.READINESS, Severity.INFO),
    ],
)
def test_condition_categories_and_unknown_is_not_failure(kind, state, reason, category, severity):
    value = record(
        status={
            "conditions": [
                {
                    "type": kind,
                    "status": state,
                    "reason": reason,
                    "lastTransitionTime": (NOW - timedelta(days=30)).isoformat(),
                }
            ]
        }
    )
    result = diagnose_record(PODS, value, NOW)[0]
    assert (result.category, result.severity) == (category, severity)
    assert not result.evidence[0].historical  # old transition does not imply stale observation
    assert result.evidence[0].reason == (reason or None)


def test_completed_and_pending_pods_do_not_invent_active_failures():
    assert diagnose_record(PODS, record(status={"phase": "Pending"}), NOW) == ()
    value = record(
        status={
            "phase": "Succeeded",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": [{"name": "app", "state": {"running": {}}, "ready": False}],
        }
    )
    assert diagnose_record(PODS, value, NOW) == ()
    assert (
        diagnose_record(
            PODS,
            record(
                status={
                    "conditions": [
                        {"type": "Initialized", "status": "False"},
                        {"type": "Ready", "status": "True"},
                    ]
                }
            ),
            NOW,
        )
        == ()
    )


@pytest.mark.parametrize(
    "condition,state",
    [
        ("Progressing", "False"),
        ("Available", "False"),
        ("ReplicaFailure", "True"),
        ("Failed", "True"),
    ],
)
def test_workload_generation_currency_is_explicit(condition, state):
    value = record(DEPLOYMENTS, status={"conditions": [{"type": condition, "status": state}]})
    result = diagnose_record(DEPLOYMENTS, value, NOW)[0]
    assert "currency is unknown" in result.explanation
    raw = value.manifest
    raw["metadata"]["generation"] = 4
    raw["status"]["observedGeneration"] = 3
    from kuberich.domain.resources import resource_record

    stale = diagnose_record(DEPLOYMENTS, resource_record(DEPLOYMENTS, raw), NOW)[0]
    assert stale.evidence[0].historical and stale.severity is Severity.INFO
    raw["status"]["observedGeneration"] = 4
    assert (
        "stale"
        not in diagnose_record(DEPLOYMENTS, resource_record(DEPLOYMENTS, raw), NOW)[0].summary
    )
    assert (
        diagnose_record(
            DEPLOYMENTS,
            record(DEPLOYMENTS, status={"conditions": [{"type": "Suspended", "status": "True"}]}),
            NOW,
        )
        == ()
    )


@pytest.mark.parametrize(
    "status",
    [
        {"conditions": {}},
        {"conditions": [None]},
        {"conditions": [{"type": 7}]},
        {"conditions": [{"type": "Ready", "status": 7}]},
        {"conditions": [dict(type="Ready", status="False")] * 129},
        {"containerStatuses": [None]},
        {"containerStatuses": [{"name": "app", "state": 4}]},
        {"containerStatuses": [{"name": "app", "lastState": {"terminated": []}}]},
    ],
)
def test_malformed_fields_fail_closed_without_raw_error(status):
    with pytest.raises(AppError, match=r"Malformed|excessive"):
        diagnose_record(PODS, record(status=status), NOW)
    with pytest.raises(AppError, match="full status"):
        diagnose_record(PODS, replace(record(), metadata_only=True), NOW)


@pytest.mark.parametrize(
    "timestamp",
    [None, 7, "invalid", "2026-11-05T12:00:00", (NOW + timedelta(seconds=1)).isoformat()],
)
def test_unknown_or_future_times_never_become_recent(timestamp):
    assert diagnostic_reported_at(timestamp, NOW) is None


def event(resource=EVENTS, *, reason="FailedMount", uid="owned-one", time=None, **reference):
    involved = {
        "apiVersion": "v1",
        "kind": "Pod",
        "name": "one",
        "namespace": "team",
        "uid": uid,
        **reference,
    }
    return record(
        resource,
        "event",
        **(
            {"regarding": involved, "note": "Observed", "eventTime": time or NOW.isoformat()}
            if resource is NEW_EVENTS
            else {
                "involvedObject": involved,
                "message": "Observed",
                "lastTimestamp": time or NOW.isoformat(),
            }
        ),
        reason=reason,
    )


@pytest.mark.parametrize(
    "reason,category",
    [
        ("FailedScheduling", Category.SCHEDULING),
        ("FailedMount", Category.VOLUME),
        ("FailedAttachVolume", Category.VOLUME),
        ("FailedMapVolume", Category.VOLUME),
        ("FailedBinding", Category.VOLUME),
        ("ProvisioningFailed", Category.VOLUME),
        ("BackOff", Category.OTHER),
        ("Unhealthy", Category.OTHER),
        ("", Category.OTHER),
    ],
)
def test_exact_uid_events_and_reason_categories(reason, category):
    finding, missing = diagnose_event(EVENTS, event(reason=reason), (ref(),), NOW)
    assert not missing and finding.category is category
    assert finding.evidence[0].ref.uid == "owned-event"
    assert finding.evidence[0].ref.resource is EVENTS
    assert finding.source is Kind.EVENT
    if reason == "Unhealthy":
        assert "readiness/liveness/startup" in finding.explanation


def test_historical_unknown_and_series_time_event_provenance():
    finding, _ = diagnose_event(
        EVENTS, event(time=(NOW - timedelta(hours=2)).isoformat()), (ref(),), NOW
    )
    assert finding.evidence[0].historical and finding.severity is Severity.INFO
    assert finding.summary.startswith("Historical")
    finding, _ = diagnose_event(EVENTS, event(time="malformed"), (ref(),), NOW)
    assert finding.severity is Severity.INFO and "unknown" in finding.explanation
    value = event(NEW_EVENTS)
    raw = value.manifest
    raw["series"] = {"lastObservedTime": NOW.isoformat()}
    from kuberich.domain.resources import resource_record

    finding, _ = diagnose_event(NEW_EVENTS, resource_record(NEW_EVENTS, raw), (ref(),), NOW)
    assert finding.evidence[0].field_path == "note"
    assert finding.evidence[0].reported_at == NOW


@pytest.mark.parametrize(
    "reference",
    [
        {"uid": None},
        {"uid": "replacement"},
        {"name": "other"},
        {"namespace": "other"},
        {"kind": "Deployment"},
        {"apiVersion": "apps/v1"},
    ],
)
def test_unrelated_event_never_attaches_by_name(reference):
    assert diagnose_event(EVENTS, event(**reference), (ref(),), NOW) == (None, True)


def test_keys_merge_exact_identity_and_distinct_declaration_paths():
    a = diagnose_record(PODS, waiting("ErrImagePull"), NOW)[0]
    assert a.key == diagnose_record(PODS, waiting("ErrImagePull"), NOW + timedelta(hours=1))[0].key
    assert a.key != finding_key(replace(ref(), uid="replacement"), Category.IMAGE_PULL, "app")
    assert diagnostic_key("a", "bc") != diagnostic_key("ab", "c")
    evidence = a.evidence[0]
    variants = tuple(
        replace(
            a,
            evidence=(
                replace(
                    evidence, key=str(i), field_path=f"spec.volumes[{i}].persistentVolumeClaim"
                ),
            ),
        )
        for i in range(19)
    )
    merged, omitted = merge_native_findings((a, a, *variants))
    assert len(merged) == 1 and len(merged[0].evidence) == 16 and omitted == 4
    assert len({e.field_path for e in merged[0].evidence}) == 16
    severe = replace(a, severity=Severity.ERROR)
    assert merge_native_findings((a, severe))[0][0].severity is Severity.ERROR
    loose = native_finding(
        replace(ref(), uid=None),
        Category.OTHER,
        evidence,
        summary="Observed",
        explanation="Unknown",
    )
    assert loose.identity is DiagnosticIdentity.NAME_ONLY


def test_sanitization_precedes_utf8_truncation_and_count_is_conservative():
    value = diagnostic_text("é" * 6000 + " token=PRIVATE")
    assert len(value.encode()) <= 4096 and value.endswith("[truncated]")
    assert "PRIVATE" not in diagnostic_text("token=PRIVATE")
    assert diagnostic_text_bytes(("abc", ["abc"], frozenset({"abc"}), 7, None)) == 9
    assert diagnostic_text_bytes(source()) > len(source().detail)


def test_combined_budgets_omissions_sources_and_idempotence(monkeypatch):
    finding = diagnose_record(PODS, waiting("ErrImagePull"), NOW)[0]
    items = tuple(replace(finding, key=str(i)) for i in range(1002))
    limited = bounded_diagnostic_snapshot(snapshot(findings=items))
    assert len(limited.findings) == 1000
    assert limited.sources[0].omitted_findings == 2 and limited.sources[0].status is Status.PARTIAL
    assert bounded_diagnostic_snapshot(limited) == limited
    no_sources = bounded_diagnostic_snapshot(snapshot(findings=items, sources=()))
    assert no_sources.sources[0].omitted_findings == 2
    large = replace(finding, summary="x" * (2 * 1024 * 1024))
    assert not bounded_diagnostic_snapshot(snapshot(findings=(large,))).findings
    enormous = tuple(
        replace(
            source(key=str(i)),
            detail="é" * 20000,
            resource=replace(PODS, aliases=("alias" * 1000,)),
        )
        for i in range(40)
    )
    result = bounded_diagnostic_snapshot(
        snapshot(sources=(*enormous, replace(source(Kind.POPEYE), detail="x" * 20000)))
    )
    assert len(result.sources) == 33
    assert diagnostic_text_bytes(result) <= 2 * 1024 * 1024
    assert any("omitted" in s.detail for s in result.sources)
    huge_descriptors = tuple(
        replace(source(key="k" * 100 + str(i)), resource=replace(PODS, kind="K" * 1000))
        for i in range(32)
    )
    assert all(
        s.resource is None
        for s in bounded_diagnostic_snapshot(snapshot(sources=huge_descriptors)).sources
    )
    assert bounded_diagnostic_snapshot(snapshot(sources=())).sources == ()


def test_rows_keep_partial_and_age_independent_and_informational_nonactionable():
    assert diagnostic_rows(None, now=NOW)[0].finding is None
    finding = diagnose_record(PODS, waiting("ErrImagePull"), NOW)[0]
    result = diagnostic_rows(
        snapshot(
            findings=(finding,),
            sources=(source(status=Status.PARTIAL), source(Kind.POPEYE, key="external")),
        ),
        now=NOW + timedelta(seconds=60),
    )
    assert result[0].summary == "partial" and "stale" in result[0].age
    assert result[0].finding is None and result[2].finding is finding
    assert "unknown" in result[1].details[-1]
    assert (
        diagnostic_age(None, NOW) == "unknown"
        and diagnostic_age(NOW, NOW - timedelta(seconds=1)) == "0s"
    )
    assert "No failure evidence" in diagnostic_rows(snapshot(), now=NOW)[1].summary
    assert "Collecting" in diagnostic_rows(snapshot(collecting=True), now=NOW)[1].summary
    external = replace(finding, subject=None, evidence=(), container=None)
    assert (
        diagnostic_rows(snapshot(findings=(external,), sources=()), now=NOW)[0].resource
        == "Unresolved object"
    )
    assert (
        diagnostic_rows(
            snapshot(
                findings=(replace(finding, subject=replace(ref(), namespace=None)),), sources=()
            ),
            now=NOW,
        )[0].resource
        == "Pod/one"
    )


def test_total_status_bound_unknown_condition_context_and_pvc_conditions():
    value = record(
        status={
            "conditions": [{"type": "Ready", "status": "False"}] * 64,
            "containerStatuses": [{"name": "app", "state": {}}] * 65,
        }
    )
    with pytest.raises(AppError, match="Excessive"):
        diagnose_record(PODS, value, NOW)
    value = record(
        status={
            "conditions": [
                {"type": "Ready", "status": "False"},
                {"type": "CustomCondition", "status": "False", "reason": "Synthetic"},
            ]
        }
    )
    findings = diagnose_record(PODS, value, NOW)
    merged, omitted = merge_native_findings(findings)
    assert len(merged) == 1 and len(merged[0].evidence) == 2 and omitted == 0
    unclassified = diagnose_record(
        PODS, record(status={"conditions": [{"type": "Custom", "status": "Unknown"}]}), NOW
    )[0]
    assert unclassified.category is Category.OTHER and unclassified.severity is Severity.INFO
    assert "Custom=Unknown" in unclassified.evidence[0].message
    from kuberich.domain.cluster_diagnostics import diagnose_claim
    from kuberich.domain.relationships import DeclaredReference
    from tests.support.diagnostic_native import PVC

    declaration = DeclaredReference(ref(PVC), "spec.volumes[0].persistentVolumeClaim", False)
    claim = record(
        PVC,
        status={
            "phase": "Lost",
            "conditions": [
                {
                    "type": "Resizing",
                    "status": "True",
                    "reason": "Reported",
                    "lastTransitionTime": NOW.isoformat(),
                }
            ],
        },
    )
    findings = diagnose_claim(ref(), PVC, claim, declaration, NOW)
    assert len(findings) == 2 and findings[0].severity is Severity.WARNING
    assert "status.conditions[0]" in findings[1].evidence[0].field_path
    unknown = diagnose_claim(
        ref(),
        PVC,
        record(PVC, status={"conditions": [{"type": "Other", "status": "Unknown"}]}),
        declaration,
        NOW,
    )
    assert unknown[0].summary.endswith("condition")


def test_source_metadata_clamp_preserves_denied_and_cancelled_acquisition_status():
    sources = tuple(
        replace(
            source(status=Status.FORBIDDEN if i % 2 else Status.CANCELLED, key=str(i)),
            resource=replace(PODS, kind="K" * 1000),
            detail="Denied or cancelled source. " + "x" * 10000,
        )
        for i in range(32)
    )
    bounded = bounded_diagnostic_snapshot(snapshot(sources=sources))
    assert {item.status for item in bounded.sources} == {Status.FORBIDDEN, Status.CANCELLED}
    assert all("omitted" in item.detail for item in bounded.sources)
    assert diagnostic_text_bytes(bounded) <= 32768
