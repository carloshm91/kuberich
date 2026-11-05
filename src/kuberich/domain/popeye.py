"""Pinned Popeye JSON decoding with bounded, name-only diagnostic provenance."""

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kuberich.domain.cluster_diagnostics import (
    MAX_DIAGNOSTIC_FINDINGS,
    MAX_DIAGNOSTIC_TEXT_BYTES,
    SOURCE_TEXT_RESERVE,
    DiagnosticCategory,
    DiagnosticEvidence,
    DiagnosticFinding,
    DiagnosticIdentity,
    DiagnosticRequest,
    DiagnosticSeverity,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
    diagnostic_key,
    diagnostic_text,
    diagnostic_text_bytes,
)
from kuberich.domain.connections import namespace_name
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, Discovery, api_segment, resource_name
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

POPEYE_VERSION = "0.22.1"
POPEYE_PARSER_ID = "popeye-json/0.22.1"
MAX_POPEYE_INPUT_BYTES = 8 * 1024 * 1024
MAX_POPEYE_NODES = 200000
MAX_POPEYE_DEPTH = 32
MAX_POPEYE_STRING_BYTES = 65536
MAX_POPEYE_SECTIONS = 64
MAX_POPEYE_ISSUES = 10000
MAX_POPEYE_ERRORS = 256
# Leave space for the service's process/dependency notice within the shared reserve.
MAX_POPEYE_SOURCE_BYTES = SOURCE_TEXT_RESERVE // 2
_SEVERITIES = tuple(DiagnosticSeverity)
_SGR = re.compile(r"\x1b\[(?:0|38;5;(?:15|75|122))m")
_VERSION = re.compile(r"(?m)^Version:[ \t]+(v?[0-9]+\.[0-9]+\.[0-9]+)[ \t]*$")
_CODE = re.compile(r"^\[POP-([0-9]{1,10})\]")


@dataclass(frozen=True, slots=True)
class PopeyeReport:
    format_version: int
    producer_version: str
    parser_id: str
    report_time: datetime
    score: int
    grade: str
    findings: tuple[DiagnosticFinding, ...]
    sources: tuple[DiagnosticSource, ...]
    omitted_findings: int
    omitted_source_notices: int


@dataclass(slots=True)
class _Pairs:
    pairs: list[tuple[str, Any]]


def parse_popeye_version(data: bytes) -> str:
    """Accept only the pinned version tuple and the pinned logo's ANSI palette."""
    if not data or len(data) > 16384:
        raise AppError("Popeye version output is empty or exceeds 16 KiB.")
    try:
        text = _SGR.sub("", data.decode("utf-8"))
    except UnicodeError:
        raise AppError("Popeye version output is not UTF-8.") from None
    unindented = text.replace("\t", " ")
    if escape_controls(unindented, allow_newlines=True) != unindented:
        raise AppError("Popeye version output contains unsupported controls.")
    versions = _VERSION.findall(text)
    # Count malformed/extra Version tuples too; an unrelated valid tuple is insufficient.
    if len(versions) != 1 or len(re.findall(r"\bVersion:", text)) != 1:
        raise AppError("Popeye version output requires one supported Version tuple.")
    version: str = versions[0].removeprefix("v")
    if version != POPEYE_VERSION:
        raise AppError("Unsupported Popeye producer version; configure v0.22.1.")
    return version


def popeye_limits(max_findings: int, max_text_bytes: int, max_source_text_bytes: int) -> None:
    if type(max_findings) is not int or not 0 <= max_findings <= MAX_DIAGNOSTIC_FINDINGS:
        raise AppError("Popeye finding limit must be between zero and 1000.")
    if type(max_text_bytes) is not int or not 0 <= max_text_bytes <= (
        MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE
    ):
        raise AppError("Popeye text limit exceeds the shared diagnostic finding allowance.")
    if (
        type(max_source_text_bytes) is not int
        or not 0 <= max_source_text_bytes <= MAX_POPEYE_SOURCE_BYTES
    ):
        raise AppError("Popeye source limit must be between zero and 16 KiB.")


def _reject_constant(value: str) -> None:
    raise AppError("Popeye JSON numbers must be finite.")


def _validate_json(value: Any, path: tuple[str, ...], depth: int, nodes: list[int]) -> None:
    nodes[0] += 1
    if nodes[0] > MAX_POPEYE_NODES or depth > MAX_POPEYE_DEPTH:
        raise AppError("Popeye JSON exceeds its structural budget.")
    if isinstance(value, str):
        if len(value.encode("utf-8", errors="surrogatepass")) > MAX_POPEYE_STRING_BYTES:
            raise AppError("Popeye JSON string exceeds 64 KiB.")
    elif isinstance(value, _Pairs):
        keys: set[str] = set()
        for key, item in value.pairs:
            if key in keys and not (path == ("popeye", "errors") and key == "error"):
                raise AppError("Popeye JSON contains a duplicate key outside its errors list.")
            keys.add(key)
            _validate_json(key, path, depth + 1, nodes)
            _validate_json(item, (*path, key), depth + 1, nodes)
    elif isinstance(value, list):
        for item in value:
            _validate_json(item, (*path, "[]"), depth + 1, nodes)
    elif isinstance(value, float) and not math.isfinite(value):
        raise AppError("Popeye JSON numbers must be finite.")


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, _Pairs):
        raise AppError("Popeye report requires a JSON object.")
    return dict(value.pairs)


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise AppError("Popeye report requires a text field.")
    return value


def _integer(value: Any, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise AppError("Popeye report contains an invalid integer field.")
    return value


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise AppError("Popeye report requires a JSON array.")
    return value


def _name(value: str) -> str:
    if len(value) > 253 or value.startswith("-") or any(char.isspace() for char in value):
        raise AppError("Popeye report contains an invalid object name.")
    return resource_name(value)


def _resource(gvr: str, discovery: Discovery) -> tuple[str | None, str, ApiResource | None]:
    parts = gvr.split("/")
    if len(parts) not in (1, 2, 3):
        raise AppError("Popeye section GVR must have a group/version/resource identity.")
    parts = [api_segment(item) for item in parts]
    if len(parts) == 1:
        # The pinned producer has a non-API `cluster`/`Version` check.
        return None, parts[0], None
    group, version, name = ("", *parts) if len(parts) == 2 else tuple(parts)
    resource = next(
        (
            item
            for item in discovery.resources
            if (item.group, item.version, item.name) == (group, version, name)
        ),
        None,
    )
    return f"{group}/{version}" if group else version, name, resource


def _reference(
    gvr: str, fqn: str, discovery: Discovery, request: DiagnosticRequest
) -> RelationshipRef | None:
    api_version, resource_name_, resource = _resource(gvr, discovery)
    parts = fqn.split("/")
    if len(parts) == 1:
        if api_version is not None and (resource is None or resource.namespaced):
            raise AppError("Bare Popeye object names require a discovered cluster-scoped resource.")
        namespace, name = None, _name(parts[0])
    elif len(parts) == 2:
        namespace = None if parts[0] == "-" else namespace_name(_name(parts[0]))
        name = _name(parts[1])
    else:
        raise AppError("Popeye object identity has too many path segments.")
    if resource is not None and resource.namespaced != (namespace is not None):
        raise AppError("Popeye object identity conflicts with discovered resource scope.")
    if namespace is not None and request.scope.namespace not in (None, namespace):
        raise AppError("Popeye object namespace differs from the captured scan scope.")
    if api_version is None:
        return None
    return RelationshipRef(
        api_version,
        resource.kind if resource is not None else resource_name_,
        namespace,
        name,
        None,
        resource,
    )


def _source(
    key: str,
    request: DiagnosticRequest,
    observed_at: datetime,
    detail: str,
    status: DiagnosticStatus = DiagnosticStatus.READY,
    resource: ApiResource | None = None,
    omitted: int = 0,
) -> DiagnosticSource:
    return DiagnosticSource(
        key,
        DiagnosticSourceKind.POPEYE,
        resource,
        request.scope.namespace,
        status,
        None,
        None,
        observed_at,
        diagnostic_text(detail),
        omitted,
    )


def _finding(
    issue: dict[str, Any],
    ref: RelationshipRef | None,
    gvr: str,
    fqn: str,
    section_index: int,
    issue_index: int,
    occurrence: int,
    observed_at: datetime,
    report_time: datetime,
) -> DiagnosticFinding:
    level = _integer(issue.get("level"), 3)
    group, issue_gvr = _string(issue.get("group")), _string(issue.get("gvr"))
    raw_message = _string(issue.get("message"))
    message = diagnostic_text(raw_message)
    code_match = _CODE.match(raw_message)
    code = "POP-" + code_match[1] if code_match is not None else None
    key = diagnostic_key(
        "popeye",
        POPEYE_VERSION,
        gvr,
        fqn,
        issue_gvr,
        group,
        code,
        level,
        diagnostic_key(message),
        occurrence,
    )
    # A report does not establish that a container still exists; logs need a fresh Pod GET.
    container = None
    if (
        ref is not None
        and ref.resource is not None
        and (ref.resource.group, ref.resource.name) == ("", "pods")
        and issue_gvr == "containers"
        and group != "__root__"
    ):
        container = _name(group)
    explanation = diagnostic_text(
        f"Popeye {POPEYE_VERSION}; level={level}; section={gvr}; issue gvr={issue_gvr}; "
        f"group={group}; FQN={fqn}; report_time={report_time.isoformat()}. "
        "Current object by name; report has no UID. "
        "This external observation does not establish a root cause or historical object identity."
    )
    evidence = (
        ()
        if ref is None
        else (
            DiagnosticEvidence(
                diagnostic_key(key, "report"),
                DiagnosticSourceKind.POPEYE,
                ref,
                f"popeye.sections[{section_index}].issues[{fqn}][{issue_index}]",
                code,
                message,
                observed_at,
                report_time,
                False,
            ),
        )
    )
    return DiagnosticFinding(
        key,
        _SEVERITIES[level],
        DiagnosticCategory.OTHER,
        ref,
        container,
        message,
        explanation,
        evidence,
        frozenset(),
        DiagnosticSourceKind.POPEYE,
        POPEYE_VERSION,
        code,
        DiagnosticIdentity.NAME_ONLY
        if ref is not None and ref.resource is not None
        else DiagnosticIdentity.UNRESOLVED,
    )


def parse_popeye_report(
    data: bytes,
    *,
    producer_version: str,
    request: DiagnosticRequest,
    discovery: Discovery,
    observed_at: datetime,
    max_findings: int = MAX_DIAGNOSTIC_FINDINGS,
    max_text_bytes: int = MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE,
    max_source_text_bytes: int = MAX_POPEYE_SOURCE_BYTES,
) -> PopeyeReport:
    """Normalize a complete pinned report; limits retain a deterministic issue prefix.

    ``max_text_bytes`` bounds finding strings after native carryover. Sources use
    only the shared reserved notice allowance; no raw/second report is retained.
    Every decoded field is structurally checked, including ignored additions.
    """
    popeye_limits(max_findings, max_text_bytes, max_source_text_bytes)
    if producer_version != POPEYE_VERSION:
        raise AppError("Unsupported Popeye producer version; parser requires 0.22.1.")
    if not data or len(data) > MAX_POPEYE_INPUT_BYTES:
        raise AppError("Popeye report is empty or exceeds 8 MiB.")
    try:
        decoded = json.loads(
            data.decode("utf-8"), object_pairs_hook=_Pairs, parse_constant=_reject_constant
        )
        _validate_json(decoded, (), 0, [0])
    except (UnicodeError, ValueError, RecursionError):
        raise AppError("Popeye report is not complete bounded UTF-8 JSON.") from None
    root = _mapping(decoded)
    if _string(root.get("ContextName")) != request.scope.session.context or (
        _string(root.get("ClusterName")) != "kuberich-session"
    ):
        raise AppError("Popeye report context or delegated cluster differs from the captured scan.")
    report = _mapping(root.get("popeye"))
    if "sanitizers" in report or "schemaVersion" in report or "schemaVersion" in root:
        raise AppError("Unsupported Popeye report layout; use the pinned sections writer.")
    try:
        timestamp = _string(report.get("report_time"))
        if (
            re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.[0-9]{1,9})?(?:Z|[+-]\d{2}:\d{2})",
                timestamp,
            )
            is None
        ):
            raise ValueError
        report_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise AppError("Popeye report_time must be an RFC3339 timestamp.") from None
    if report_time.tzinfo is None or observed_at.tzinfo is None:
        raise AppError("Popeye report and observation times require explicit time zones.")
    score = _integer(report.get("score"), 100)
    # Grade is short in the pinned producer. Bound this metadata independently
    # so the mandatory omission summary always fits its reserved 1 KiB.
    grade = diagnostic_text(_string(report.get("grade")))
    if len(grade.encode()) > 64:
        raise AppError("Popeye grade metadata exceeds its bounded field.")
    findings: list[DiagnosticFinding] = []
    sources: list[DiagnosticSource] = []
    source_bytes = finding_bytes = seen_issues = omitted = omitted_notices = 0
    limited = False

    def notice(source: DiagnosticSource) -> None:
        nonlocal source_bytes, omitted_notices
        size = diagnostic_text_bytes(source)
        if source_bytes + size <= max(0, max_source_text_bytes - 1024):
            sources.append(source)
            source_bytes += size
        else:
            omitted_notices += 1

    errors = report.get("errors", _Pairs([]))
    _mapping(errors)
    for index, (key, value) in enumerate(errors.pairs):
        if key != "error":
            raise AppError("Popeye errors accepts only repeated error entries.")
        detail = _string(value)
        if index < MAX_POPEYE_ERRORS:
            notice(
                _source(
                    f"popeye:error:{index}",
                    request,
                    observed_at,
                    detail,
                    DiagnosticStatus.FORBIDDEN
                    if re.search(r"\b(?:403|forbidden)\b", detail, re.I)
                    else DiagnosticStatus.PARTIAL,
                )
            )
        else:
            omitted_notices += 1

    occurrences: dict[str, int] = {}
    for section_index, raw_section in enumerate(_array(report.get("sections", []))):
        section = _mapping(raw_section)
        title, gvr = _string(section.get("linter")), _string(section.get("gvr"))
        _, _, resource = _resource(gvr, discovery)
        tally = _mapping(section.get("tally"))
        counts = tuple(
            _integer(tally.get(field), MAX_POPEYE_NODES)
            for field in ("ok", "info", "warning", "error")
        )
        section_score = _integer(tally.get("score"), 100)
        section_omitted = 0
        issues = _mapping(section.get("issues", _Pairs([])))
        for fqn, raw_issues in issues.items():
            ref = _reference(gvr, fqn, discovery, request)
            for issue_index, raw_issue in enumerate(_array(raw_issues)):
                issue = _mapping(raw_issue)
                occurrence_key = diagnostic_key(
                    gvr,
                    fqn,
                    _string(issue.get("gvr")),
                    _string(issue.get("group")),
                    _integer(issue.get("level"), 3),
                    diagnostic_text(_string(issue.get("message"))),
                )
                occurrence = occurrences.get(occurrence_key, 0)
                occurrences[occurrence_key] = occurrence + 1
                finding = _finding(
                    issue,
                    ref,
                    gvr,
                    fqn,
                    section_index,
                    issue_index,
                    occurrence,
                    observed_at,
                    report_time,
                )
                size = diagnostic_text_bytes(finding)
                seen_issues += 1
                limited = (
                    limited
                    or section_index >= MAX_POPEYE_SECTIONS
                    or seen_issues > MAX_POPEYE_ISSUES
                    or (len(findings) >= max_findings or finding_bytes + size > max_text_bytes)
                )
                if limited:
                    omitted += 1
                    section_omitted += 1
                else:
                    findings.append(finding)
                    finding_bytes += size
        detail = f"{title} ({gvr}); tally ok/info/warning/error={counts}; score={section_score}."
        status = DiagnosticStatus.READY
        if resource is None:
            detail += " API/version was not discovered; object linkage is unresolved."
            status = DiagnosticStatus.PARTIAL
        if section_omitted:
            detail += f" Omitted {section_omitted} findings at collection/publication limits."
            status = DiagnosticStatus.PARTIAL
        if section_index < MAX_POPEYE_SECTIONS:
            notice(
                _source(
                    f"popeye:section:{section_index}",
                    request,
                    observed_at,
                    detail,
                    status,
                    resource,
                    section_omitted,
                )
            )
        else:
            omitted_notices += 1

    partial = (
        omitted > 0
        or omitted_notices > 0
        or bool(errors.pairs)
        or any(source.status is not DiagnosticStatus.READY for source in sources)
    )
    summary = _source(
        "popeye:report",
        request,
        observed_at,
        f"{POPEYE_PARSER_ID}; format=1; report_time={report_time.isoformat()}; score={score}; grade={grade}. "
        f"Omitted findings={omitted}; omitted source notices={omitted_notices}. "
        "External API reads are unknown and are outside the native read budget.",
        DiagnosticStatus.PARTIAL if partial else DiagnosticStatus.READY,
        omitted=omitted,
    )
    if diagnostic_text_bytes(summary) + source_bytes <= max_source_text_bytes:
        sources.insert(0, summary)
    else:
        omitted_notices += 1
    return PopeyeReport(
        1,
        producer_version,
        POPEYE_PARSER_ID,
        report_time,
        score,
        grade,
        tuple(findings),
        tuple(sources),
        omitted,
        omitted_notices,
    )
