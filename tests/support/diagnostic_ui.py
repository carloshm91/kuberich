"""Synthetic immutable diagnostic observations for native UI behavior."""

from datetime import UTC, datetime, timedelta

from kuberich.domain.cluster_diagnostics import (
    DiagnosticCategory,
    DiagnosticEvidence,
    DiagnosticFinding,
    DiagnosticIdentity,
    DiagnosticLogMode,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSeverity,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
)
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, CollectionState
from kuberich.domain.targets import SessionIdentity

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list", "watch"}))
EVENTS = ApiResource("", "v1", "events", "Event", True, frozenset({"get", "list", "watch"}))
POD = RelationshipRef("v1", "Pod", "team", "example", "pod-uid", PODS)
EVENT = RelationshipRef("v1", "Event", "team", "reported", "event-uid", EVENTS)


def finding(key="finding", *, evidence=True):
    return DiagnosticFinding(
        key,
        DiagnosticSeverity.ERROR,
        DiagnosticCategory.CRASH_LOOP,
        POD,
        "main",
        "Restart backoff observed",
        "Restart backoff does not establish the application's root cause.",
        (
            DiagnosticEvidence(
                "condition",
                DiagnosticSourceKind.CONDITION,
                POD,
                "status.containerStatuses[0].state.waiting.reason",
                "CrashLoopBackOff",
                "A current container state was observed.",
                NOW - timedelta(seconds=70),
                None,
                False,
            ),
            DiagnosticEvidence(
                "event",
                DiagnosticSourceKind.EVENT,
                EVENT,
                "reason",
                "BackOff",
                "A UID-matched event was reported.",
                NOW - timedelta(seconds=10),
                NOW - timedelta(hours=2),
                True,
            ),
        )
        if evidence
        else (),
        frozenset({DiagnosticLogMode.CURRENT, DiagnosticLogMode.PREVIOUS}),
        DiagnosticSourceKind.CONDITION,
        None,
        None,
        DiagnosticIdentity.UID_BOUND,
    )


def snapshot(*, findings=None, collecting=False, revision=1):
    request = DiagnosticRequest(DiagnosticScope(SessionIdentity("owned", 1), "team"), revision)
    return DiagnosticSnapshot(
        request,
        (finding(),) if findings is None else findings,
        (
            DiagnosticSource(
                "pods",
                DiagnosticSourceKind.CONDITION,
                PODS,
                "team",
                DiagnosticStatus.PARTIAL,
                CollectionState(complete=False, limited=True),
                "opaque-rv",
                NOW - timedelta(seconds=70),
                "The retained source is incomplete.",
                3,
            ),
            DiagnosticSource(
                "events",
                DiagnosticSourceKind.EVENT,
                EVENTS,
                "team",
                DiagnosticStatus.FORBIDDEN,
                None,
                None,
                None,
                "Event reads were denied.",
            ),
        ),
        collecting,
        2,
        NOW,
    )
