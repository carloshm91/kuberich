"""Literal diagnostic table rows and per-source/evidence presentation age."""

from dataclasses import dataclass
from datetime import datetime

from kuberich.domain.cluster_diagnostics import (
    DIAGNOSTIC_STALE_SECONDS,
    DiagnosticFinding,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
)


@dataclass(frozen=True, slots=True)
class DiagnosticRow:
    key: str
    severity: str
    category: str
    resource: str
    container: str
    summary: str
    source: str
    age: str
    details: tuple[str, ...]
    finding: DiagnosticFinding | None
    source_record: DiagnosticSource | None


def diagnostic_age(observed_at: datetime | None, now: datetime) -> str:
    if observed_at is None:
        return "unknown"
    seconds = max(0, int((now - observed_at).total_seconds()))
    return f"{seconds}s" + (" (stale)" if seconds >= DIAGNOSTIC_STALE_SECONDS else "")


def diagnostic_rows(
    snapshot: DiagnosticSnapshot | None,
    *,
    now: datetime,
) -> tuple[DiagnosticRow, ...]:
    if snapshot is None:
        return (
            DiagnosticRow(
                "summary:loading",
                "",
                "",
                "",
                "",
                "Waiting for diagnostic sources.",
                "",
                "unknown",
                (),
                None,
                None,
            ),
        )
    rows: list[DiagnosticRow] = []
    for source in snapshot.sources:
        detail: tuple[str, ...] = (source.detail, f"omitted findings: {source.omitted_findings}")
        if source.kind is DiagnosticSourceKind.POPEYE:
            detail += (
                "External API read count is unknown; native read quota does not bound the external process.",
            )
        rows.append(
            DiagnosticRow(
                "source:" + source.key,
                "",
                "source",
                source.resource.name if source.resource else "",
                "",
                source.status.value,
                source.kind.value,
                diagnostic_age(source.observed_at, now),
                detail,
                None,
                source,
            )
        )
    for finding in snapshot.findings:
        ref = finding.subject
        label = (
            f"{ref.namespace + '/' if ref.namespace else ''}{ref.kind}/{ref.name}"
            if ref
            else "Unresolved object"
        )
        # Oldest retained item exposes mixed evidence age instead of rejuvenating it.
        observed = min((item.observed_at for item in finding.evidence), default=None)
        rows.append(
            DiagnosticRow(
                finding.key,
                finding.severity.value,
                finding.category.value,
                label,
                finding.container or "",
                finding.summary,
                finding.source.value,
                diagnostic_age(observed, now),
                (finding.explanation,),
                finding,
                None,
            )
        )
    if not snapshot.findings:
        rows.append(
            DiagnosticRow(
                "summary:empty",
                "",
                "",
                "",
                "",
                "Collecting failure evidence…"
                if snapshot.collecting
                else "No failure evidence found in the collected sources.",
                "native",
                "unknown",
                ("Unavailable, incomplete or expired sources cannot establish health.",),
                None,
                None,
            )
        )
    rows.append(
        DiagnosticRow(
            "summary:reads",
            "",
            "",
            "",
            "",
            f"Native API reads: {snapshot.native_requests_used}/64",
            "native",
            "",
            (),
            None,
            None,
        )
    )
    return tuple(rows)
