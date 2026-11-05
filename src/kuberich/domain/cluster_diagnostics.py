"""Immutable native/external diagnostic evidence, bounded independently of the UI."""

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import namespace_name
from kuberich.domain.relationships import DeclaredReference, RelationshipRef, relationship_identity
from kuberich.domain.resources import ApiResource, CollectionState, ResourceRecord, resource_name
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError

MAX_DIAGNOSTIC_FINDINGS = 1000
MAX_DIAGNOSTIC_TEXT_BYTES = 2 * 1024 * 1024
SOURCE_TEXT_RESERVE = 32 * 1024
MAX_DIAGNOSTIC_MESSAGE_BYTES = 4096
MAX_DIAGNOSTIC_EVIDENCE = 16
MAX_DIAGNOSTIC_ITEMS = 10000
MAX_DIAGNOSTIC_RAW_BYTES = 16 * 1024 * 1024
MAX_DIAGNOSTIC_FACT_BYTES = 2 * 1024 * 1024
MAX_DIAGNOSTIC_FIELDS = 128
DIAGNOSTIC_DEADLINE = 30.0
DIAGNOSTIC_STALE_SECONDS = 60


class DiagnosticSeverity(StrEnum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCategory(StrEnum):
    IMAGE_PULL = "image_pull"
    SCHEDULING = "scheduling"
    CRASH_LOOP = "crash_loop"
    READINESS = "readiness"
    VOLUME = "volume"
    WORKLOAD = "workload"
    OTHER = "other"


class DiagnosticSourceKind(StrEnum):
    CONDITION = "condition"
    EVENT = "event"
    POPEYE = "popeye"


class DiagnosticLogMode(StrEnum):
    CURRENT = "current"
    PREVIOUS = "previous"


class DiagnosticIdentity(StrEnum):
    UID_BOUND = "uid_bound"
    NAME_ONLY = "name_only"
    UNRESOLVED = "unresolved"


class DiagnosticStatus(StrEnum):
    LOADING = "loading"
    READY = "ready"
    PARTIAL = "partial"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class DiagnosticScope:
    session: SessionIdentity
    namespace: str | None
    root: RelationshipRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionIdentity):
            raise AppError("Diagnostics requires an explicit session identity.")
        if self.namespace is not None:
            namespace_name(self.namespace)
        if self.root is not None:
            root = self.root
            if (
                root.uid is None
                or root.resource is None
                or not root.resource.namespaced
                or root.namespace is None
                or root.namespace != self.namespace
                or root.api_version != root.resource.api_version
                or root.kind != root.resource.kind
            ):
                raise AppError("Diagnostic root requires an exact served namespaced UID identity.")
            resource_name(root.name)
            resource_name(root.uid)
        if diagnostic_text_bytes(self) > 8192:
            raise AppError("Diagnostic scope metadata exceeds the retained text bound.")


@dataclass(frozen=True, slots=True)
class DiagnosticRequest:
    scope: DiagnosticScope
    revision: int

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1:
            raise AppError("Diagnostic revision must be a positive integer.")


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    key: str
    source: DiagnosticSourceKind
    ref: RelationshipRef
    field_path: str
    reason: str | None
    message: str
    observed_at: datetime
    reported_at: datetime | None
    historical: bool


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    key: str
    severity: DiagnosticSeverity
    category: DiagnosticCategory
    subject: RelationshipRef | None
    container: str | None
    summary: str
    explanation: str
    evidence: tuple[DiagnosticEvidence, ...]
    log_modes: frozenset[DiagnosticLogMode]
    source: DiagnosticSourceKind
    tool_version: str | None
    source_code: str | None
    identity: DiagnosticIdentity


@dataclass(frozen=True, slots=True)
class DiagnosticSource:
    key: str
    kind: DiagnosticSourceKind
    resource: ApiResource | None
    namespace: str | None
    status: DiagnosticStatus
    collection: CollectionState | None
    resource_version: str | None
    observed_at: datetime | None
    detail: str
    omitted_findings: int = 0


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    request: DiagnosticRequest
    findings: tuple[DiagnosticFinding, ...]
    sources: tuple[DiagnosticSource, ...]
    collecting: bool
    native_requests_used: int
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DiagnosticBookmark:
    namespace: str | None
    root: RelationshipRef | None


def diagnostic_key(*values: object) -> str:
    """Canonical tuple keys never depend on local observation time/revision."""
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def finding_key(ref: RelationshipRef, category: DiagnosticCategory, container: str | None) -> str:
    return diagnostic_key("native", relationship_identity(ref), category, container)


def diagnostic_text(value: str) -> str:
    """Redact and escape the complete bounded field before UTF-8 truncation."""
    safe = sanitize_text(value)
    encoded = safe.encode()
    if len(encoded) <= MAX_DIAGNOSTIC_MESSAGE_BYTES:
        return safe
    return (
        encoded[: MAX_DIAGNOSTIC_MESSAGE_BYTES - 16].decode("utf-8", errors="ignore")
        + " [truncated]"
    )


def diagnostic_text_bytes(value: object) -> int:
    """Count every stored string occurrence, including keys, enums and descriptors."""
    if isinstance(value, str):
        return len(value.encode())
    if is_dataclass(value) and not isinstance(value, type):
        return sum(diagnostic_text_bytes(getattr(value, item.name)) for item in fields(value))
    if isinstance(value, (tuple, list, frozenset)):
        return sum(diagnostic_text_bytes(item) for item in value)
    return 0


def _bounded_sources(
    sources: tuple[DiagnosticSource, ...], allowance: int
) -> tuple[DiagnosticSource, ...]:
    if not sources:
        return ()
    selected = list(sources[:32])
    if len(sources) > 32:
        selected[-1] = replace(
            selected[-1],
            status=DiagnosticStatus.PARTIAL,
            detail="Additional source summaries omitted by the shared source limit.",
        )
    per_source = allowance // len(selected)
    result: list[DiagnosticSource] = []
    for source in selected:
        detail = diagnostic_text(source.detail)
        resource = replace(source.resource, aliases=()) if source.resource is not None else None
        source = replace(
            source,
            key=source.key if len(source.key) <= 64 else diagnostic_key(source.key),
            resource=resource,
            detail="",
        )
        if diagnostic_text_bytes(source) + 96 > per_source:
            source = replace(
                source,
                resource=None,
                resource_version=None,
                status=DiagnosticStatus.PARTIAL
                if source.status is DiagnosticStatus.READY
                else source.status,
            )
            detail = "Source descriptor/details omitted by the shared text limit. " + detail
        room = max(0, per_source - diagnostic_text_bytes(source))
        if len(detail.encode()) > room:
            source = replace(
                source,
                status=DiagnosticStatus.PARTIAL
                if source.status is DiagnosticStatus.READY
                else source.status,
            )
            suffix = " [source text omitted]"
            detail = (
                detail.encode()[: max(0, room - len(suffix))].decode("utf-8", errors="ignore")
                + suffix
            )
        result.append(replace(source, detail=detail))
    return tuple(result)


def bounded_diagnostic_snapshot(snapshot: DiagnosticSnapshot) -> DiagnosticSnapshot:
    """One conservative combined publication budget, with visible omissions."""
    base = diagnostic_text_bytes(replace(snapshot, findings=(), sources=()))
    remaining = max(0, MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE)
    findings: list[DiagnosticFinding] = []
    omitted: dict[DiagnosticSourceKind, int] = {}
    for finding in snapshot.findings:
        size = diagnostic_text_bytes(finding)
        if len(findings) >= MAX_DIAGNOSTIC_FINDINGS or size > remaining:
            omitted[finding.source] = omitted.get(finding.source, 0) + 1
        else:
            findings.append(finding)
            remaining -= size
    sources = list(snapshot.sources)
    for kind, count in omitted.items():
        source_index = next((i for i, item in enumerate(sources) if item.kind is kind), None)
        if source_index is None:
            sources.append(
                DiagnosticSource(
                    "source:limit:" + kind.value,
                    kind,
                    None,
                    snapshot.request.scope.namespace,
                    DiagnosticStatus.PARTIAL,
                    None,
                    None,
                    snapshot.observed_at,
                    "Findings omitted by the shared row/text limit.",
                    count,
                )
            )
        else:
            source = sources[source_index]
            sources[source_index] = replace(
                source,
                status=DiagnosticStatus.PARTIAL,
                detail=source.detail + " Findings omitted by the shared row/text limit.",
                omitted_findings=source.omitted_findings + count,
            )
    native = _bounded_sources(
        tuple(s for s in sources if s.kind is not DiagnosticSourceKind.POPEYE),
        SOURCE_TEXT_RESERVE // 2 - base,
    )
    external = _bounded_sources(
        tuple(s for s in sources if s.kind is DiagnosticSourceKind.POPEYE), SOURCE_TEXT_RESERVE // 2
    )
    return replace(snapshot, findings=tuple(findings), sources=(*native, *external))


# Deliberately finite reason sets: generic prose is never treated as a diagnosis.
_IMAGE_REASONS = frozenset(
    {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "ErrImageNeverPull"}
)
_VOLUME_REASONS = frozenset(
    {"FailedMount", "FailedAttachVolume", "FailedMapVolume", "FailedBinding", "ProvisioningFailed"}
)


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError("Malformed diagnostic evidence mapping.")
    return value


def _items(value: Any) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_DIAGNOSTIC_FIELDS:
        raise AppError("Malformed or excessive diagnostic evidence fields.")
    return value


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise AppError("Malformed diagnostic evidence text.")
    return diagnostic_text(value)


def diagnostic_reported_at(value: Any, observed_at: datetime) -> datetime | None:
    """Missing, malformed, naive and future server timestamps have unknown age."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed > observed_at:
            return None
        return parsed
    except ValueError:
        return None


def diagnostic_evidence(
    ref: RelationshipRef,
    source: DiagnosticSourceKind,
    path: str,
    reason: str | None,
    message: str,
    observed_at: datetime,
    reported_at: Any = None,
    historical: bool = False,
) -> DiagnosticEvidence:
    return DiagnosticEvidence(
        diagnostic_key(source, relationship_identity(ref), path, reason),
        source,
        ref,
        path,
        reason,
        diagnostic_text(message),
        observed_at,
        diagnostic_reported_at(reported_at, observed_at),
        historical,
    )


def native_finding(
    subject: RelationshipRef,
    category: DiagnosticCategory,
    evidence: DiagnosticEvidence,
    *,
    container: str | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
    summary: str,
    explanation: str,
    log_modes: frozenset[DiagnosticLogMode] = frozenset(),
) -> DiagnosticFinding:
    return DiagnosticFinding(
        finding_key(subject, category, container),
        severity,
        category,
        subject,
        container,
        diagnostic_text(summary),
        diagnostic_text(explanation),
        (evidence,),
        log_modes,
        evidence.source,
        None,
        None,
        DiagnosticIdentity.UID_BOUND if subject.uid is not None else DiagnosticIdentity.NAME_ONLY,
    )


def merge_native_findings(
    findings: tuple[DiagnosticFinding, ...],
) -> tuple[tuple[DiagnosticFinding, ...], int]:
    """Merge only exact native identity/category/container, preserving declaration paths."""
    merged: dict[str, DiagnosticFinding] = {}
    omitted = 0
    priority = {
        DiagnosticSeverity.OK: 0,
        DiagnosticSeverity.INFO: 1,
        DiagnosticSeverity.WARNING: 2,
        DiagnosticSeverity.ERROR: 3,
    }
    for finding in findings:
        previous = merged.get(finding.key)
        if previous is None:
            merged[finding.key] = finding
            continue
        evidence = dict.fromkeys(item.key for item in previous.evidence)
        retained = list(previous.evidence)
        for item in finding.evidence:
            if item.key in evidence:
                continue
            evidence[item.key] = None
            if len(retained) < MAX_DIAGNOSTIC_EVIDENCE:
                retained.append(item)
            else:
                omitted += 1
        preferred = (
            finding if priority[finding.severity] > priority[previous.severity] else previous
        )
        merged[finding.key] = replace(
            preferred, evidence=tuple(retained), log_modes=previous.log_modes | finding.log_modes
        )
    return tuple(merged.values()), omitted


def diagnose_record(
    resource: ApiResource, record: ResourceRecord, observed_at: datetime
) -> tuple[DiagnosticFinding, ...]:
    """Allowlist conditions/container states; never retain env, commands or manifests."""
    from kuberich.domain.relationships import reference_for

    if record.metadata_only:
        raise AppError("Diagnostic evidence requires full status fields.")
    ref = reference_for(resource, record)
    data = record.manifest
    status = _mapping(data.get("status", {}))
    findings: list[DiagnosticFinding] = []
    field_count = len(_items(status.get("conditions", [])))
    for field in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses"):
        field_count += len(_items(status.get(field, [])))
    if field_count > MAX_DIAGNOSTIC_FIELDS:
        raise AppError("Excessive diagnostic conditions/container statuses per object.")
    pod = resource.group == "" and resource.name == "pods"
    completed = status.get("phase") == "Succeeded"
    context: list[DiagnosticEvidence] = []
    for index, raw in enumerate(_items(status.get("conditions", []))):
        condition = _mapping(raw)
        kind, state = _text(condition.get("type")), _text(condition.get("status"))
        reason, message = _text(condition.get("reason")), _text(condition.get("message"))
        category: DiagnosticCategory | None = None
        severity = DiagnosticSeverity.WARNING
        if pod:
            if kind == "PodScheduled" and state == "False" and reason == "Unschedulable":
                category = DiagnosticCategory.SCHEDULING
            elif (
                kind in {"Ready", "ContainersReady"}
                and state in {"False", "Unknown"}
                and not completed
            ):
                category = DiagnosticCategory.READINESS
                if state == "Unknown":
                    severity = DiagnosticSeverity.INFO
        elif (kind in {"Progressing", "Available"} and state == "False") or (
            kind in {"ReplicaFailure", "Failed"} and state == "True"
        ):
            category = DiagnosticCategory.WORKLOAD
        if category is None:
            if kind not in {
                "Ready",
                "ContainersReady",
                "PodScheduled",
                "Initialized",
                "PodReadyToStartContainers",
                "Progressing",
                "Available",
                "ReplicaFailure",
                "Failed",
                "Complete",
                "Suspended",
            }:
                context.append(
                    diagnostic_evidence(
                        ref,
                        DiagnosticSourceKind.CONDITION,
                        f"status.conditions[{index}]",
                        reason or None,
                        f"Unclassified condition {kind}={state}; {message}",
                        observed_at,
                        condition.get("lastTransitionTime"),
                    )
                )
            continue
        generation = _mapping(data.get("metadata", {})).get("generation")
        observed = condition.get("observedGeneration", status.get("observedGeneration"))
        stale = (
            not pod and type(generation) is int and type(observed) is int and observed < generation
        )
        currency = (
            " Condition is stale: observedGeneration is older than metadata.generation."
            if stale
            else " Condition generation currency is unknown."
            if not pod and type(observed) is not int
            else ""
        )
        evidence = diagnostic_evidence(
            ref,
            DiagnosticSourceKind.CONDITION,
            f"status.conditions[{index}]",
            reason or None,
            f"{kind}={state}; {message}" + currency,
            observed_at,
            condition.get("lastTransitionTime"),
            stale,
        )
        findings.append(
            native_finding(
                ref,
                category,
                evidence,
                severity=DiagnosticSeverity.INFO if stale else severity,
                summary=f"{kind}={state}" + (" (stale condition)" if stale else ""),
                explanation="Observed controller condition; this does not establish the underlying cause."
                + currency,
            )
        )
    if not pod:
        return _with_condition_context(findings, context)
    for field in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses"):
        for index, raw in enumerate(_items(status.get(field, []))):
            entry = _mapping(raw)
            container = resource_name(entry.get("name"))
            container_state = _mapping(entry.get("state", {}))
            last = _mapping(entry.get("lastState", {}))
            previous = _mapping(last.get("terminated", {}))
            modes: set[DiagnosticLogMode] = set()
            if isinstance(container_state.get("running"), dict) or isinstance(
                container_state.get("terminated"), dict
            ):
                modes.add(DiagnosticLogMode.CURRENT)
            if previous:
                modes.add(DiagnosticLogMode.PREVIOUS)
            waiting = _mapping(container_state.get("waiting", {}))
            reason = _text(waiting.get("reason"))
            message = _text(waiting.get("message"))
            category = (
                DiagnosticCategory.IMAGE_PULL
                if reason in _IMAGE_REASONS
                else DiagnosticCategory.CRASH_LOOP
                if reason == "CrashLoopBackOff"
                else None
            )
            path = f"status.{field}[{index}]"
            if category is not None:
                evidence = diagnostic_evidence(
                    ref,
                    DiagnosticSourceKind.CONDITION,
                    path + ".state.waiting",
                    reason,
                    message or reason,
                    observed_at,
                )
                explanation = (
                    "Image acquisition/backoff failure was observed; registry, credential and image causes are not established."
                    if category is DiagnosticCategory.IMAGE_PULL
                    else "Restart backoff was observed; this does not establish the application's root cause."
                )
                finding = native_finding(
                    ref,
                    category,
                    evidence,
                    container=container,
                    summary=reason,
                    explanation=explanation,
                    log_modes=frozenset(modes),
                )
                if previous:
                    termination = diagnostic_evidence(
                        ref,
                        DiagnosticSourceKind.CONDITION,
                        path + ".lastState.terminated",
                        _text(previous.get("reason")) or None,
                        f"Previous termination: reason={_text(previous.get('reason'))}; exitCode={previous.get('exitCode') if type(previous.get('exitCode')) is int else 'unknown'}; restartCount={entry.get('restartCount') if type(entry.get('restartCount')) is int else 'unknown'}",
                        observed_at,
                        previous.get("finishedAt"),
                    )
                    finding = replace(finding, evidence=(*finding.evidence, termination))
                findings.append(finding)
            if (
                not completed
                and isinstance(container_state.get("running"), dict)
                and entry.get("ready") is False
            ):
                evidence = diagnostic_evidence(
                    ref,
                    DiagnosticSourceKind.CONDITION,
                    path + ".ready",
                    None,
                    "Running container reports ready=false.",
                    observed_at,
                )
                findings.append(
                    native_finding(
                        ref,
                        DiagnosticCategory.READINESS,
                        evidence,
                        container=container,
                        summary="Running container is not ready",
                        explanation="False readiness does not establish a probe failure or its cause.",
                        log_modes=frozenset(modes),
                    )
                )
    return _with_condition_context(findings, context)


def diagnose_event(
    resource: ApiResource,
    record: ResourceRecord,
    subjects: tuple[RelationshipRef, ...],
    observed_at: datetime,
) -> tuple[DiagnosticFinding | None, bool]:
    """Match exact UID/name/kind/group/namespace; report malformed/unmatched references."""
    from kuberich.domain.relationships import reference_for
    from kuberich.domain.resources import split_api_version

    data = record.manifest
    new_api = resource.group == "events.k8s.io"
    raw = _mapping(data.get("regarding" if new_api else "involvedObject", {}))
    group, _ = split_api_version(raw.get("apiVersion", "v1"))
    subject = next(
        (
            ref
            for ref in subjects
            if ref.uid is not None
            and raw.get("uid") == ref.uid
            and raw.get("name") == ref.name
            and raw.get("namespace") == ref.namespace
            and record.namespace == ref.namespace
            and raw.get("kind") == ref.kind
            and split_api_version(ref.api_version)[0] == group
        ),
        None,
    )
    if subject is None:
        return None, True
    reason = _text(data.get("reason"))
    path = "note" if new_api else "message"
    series = _mapping(data.get("series", {}))
    reported = series.get("lastObservedTime") or data.get("eventTime") or data.get("lastTimestamp")
    timestamp = diagnostic_reported_at(reported, observed_at)
    historical = timestamp is not None and (observed_at - timestamp).total_seconds() > 3600
    category = (
        DiagnosticCategory.SCHEDULING
        if reason == "FailedScheduling"
        else DiagnosticCategory.VOLUME
        if reason in _VOLUME_REASONS
        else DiagnosticCategory.OTHER
    )
    evidence = diagnostic_evidence(
        reference_for(resource, record),
        DiagnosticSourceKind.EVENT,
        path,
        reason or None,
        _text(data.get(path)),
        observed_at,
        reported,
        historical,
    )
    qualification = (
        "Historical event; this does not establish a current failure."
        if historical
        else "Event time is unknown; this does not establish a current failure."
        if timestamp is None
        else "A controller reported this event; correlation does not establish cause."
    )
    if reason == "Unhealthy":
        qualification += " A probe failure was reported; readiness/liveness/startup is not identified by this reason alone."
    return native_finding(
        subject,
        category,
        evidence,
        severity=DiagnosticSeverity.WARNING
        if not historical and timestamp is not None and category is not DiagnosticCategory.OTHER
        else DiagnosticSeverity.INFO,
        summary=("Historical " if historical else "") + (reason or "Observed event"),
        explanation=qualification,
    ), False


def _with_condition_context(
    findings: list[DiagnosticFinding], context: list[DiagnosticEvidence]
) -> tuple[DiagnosticFinding, ...]:
    # Return independent facts so the service's merge records every evidence omission.
    if context:
        if not findings:
            item = context.pop(0)
            findings.append(
                native_finding(
                    item.ref,
                    DiagnosticCategory.OTHER,
                    item,
                    severity=DiagnosticSeverity.INFO,
                    summary="Unclassified condition evidence",
                    explanation="Observed condition names/reasons do not establish a known failure category.",
                )
            )
        findings.extend(replace(findings[0], evidence=(item,)) for item in context)
    return tuple(findings)


def diagnose_claim(
    subject: RelationshipRef,
    resource: ApiResource,
    record: ResourceRecord,
    declaration: DeclaredReference,
    observed_at: datetime,
) -> tuple[DiagnosticFinding, ...]:
    from kuberich.domain.relationships import reference_for

    status = _mapping(record.manifest.get("status", {}))
    phase = _text(status.get("phase"))
    conditions = _items(status.get("conditions", []))
    if phase not in {"Pending", "Lost"} and not conditions:
        return ()
    actual = reference_for(resource, record)
    evidence = [
        diagnostic_evidence(
            actual,
            DiagnosticSourceKind.CONDITION,
            declaration.path + " -> status.phase",
            phase or None,
            f"Explicit PVC declaration optional={declaration.optional}, defaulted={declaration.defaulted}; observed phase={phase or 'unknown'}. Pending can be expected with delayed binding; correlation does not establish cause.",
            observed_at,
        )
    ]
    for index, raw in enumerate(conditions):
        condition = _mapping(raw)
        evidence.append(
            diagnostic_evidence(
                actual,
                DiagnosticSourceKind.CONDITION,
                declaration.path + f" -> status.conditions[{index}]",
                _text(condition.get("reason")) or None,
                f"{_text(condition.get('type'))}={_text(condition.get('status'))}; {_text(condition.get('message'))}",
                observed_at,
                condition.get("lastTransitionTime"),
            )
        )
    finding = native_finding(
        subject,
        DiagnosticCategory.VOLUME,
        evidence[0],
        severity=DiagnosticSeverity.INFO if phase != "Lost" else DiagnosticSeverity.WARNING,
        summary="Referenced PVC " + (phase or "condition"),
        explanation="Observed referenced claim state; this does not prove the cause of a Pod failure.",
    )
    return tuple(replace(finding, evidence=(item,)) for item in evidence)
