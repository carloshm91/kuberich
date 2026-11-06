"""Immutable local artifacts and bounded, default-redacted pure codecs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Hashable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

import yaml
from yaml.events import AliasEvent, CollectionStartEvent, ScalarEvent
from yaml.nodes import MappingNode

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.aggregate_logs import AggregateLine, LogSource
from kuberich.domain.cluster_diagnostics import DiagnosticSnapshot
from kuberich.domain.log_json import TIMESTAMP
from kuberich.domain.log_view import LogEntry
from kuberich.domain.logs import LogOptions
from kuberich.domain.navigation import Viewport
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

MAX_METADATA_BYTES = 8192
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_ENTRIES = 2048
MAX_PAGE_BYTES = 256 * 1024
MAX_FIELD_CHARS = 65536
MAX_DEPTH = 64
MAX_NODES = 250000
REDACTED = "[REDACTED]"
TEXT_PREFIX = "# kuberich-export: "
JSON_PREFIX = '{"kuberich_export":'
_LOG_PREFIX = "# kuberich-log-source: "
_SENSITIVE = re.compile(
    r"password|passwd|token|credential|private[-_]?key|client[-_]?key|authorization|"
    r"api[-_]?key|access[-_]?key|secret(?!Ref|KeyRef|Name)",
    re.IGNORECASE,
)
_KEY = re.compile(r"-----(BEGIN|END) [^-\n]{0,64}PRIVATE KEY-----", re.IGNORECASE)

type ExportKind = Literal[
    "resource-yaml", "logs", "diagnostics", "screen", "support", "legacy-report"
]
type ExportIntent = Literal["save", "view", "copy"]
type NamespaceMode = Literal["one", "all", "cluster", "local", "unknown"]


@dataclass(frozen=True, kw_only=True, slots=True)
class ExportScope:
    export_at: datetime | None
    source_at: datetime | None
    context: str | None
    header_namespace: str | None
    collection_namespace: str | None
    namespace_mode: NamespaceMode
    api_version: str | None = None
    resource: str | None = None
    kind: str | None = None
    name: str | None = None
    uid: str | None = None
    resource_version: str | None = None
    container: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ExportPresentation:
    view: str
    query: str = ""
    sort: str | None = None
    descending: bool = False
    viewport: Viewport | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ResourceSource:
    resource: ApiResource
    record: ResourceRecord = field(repr=False)
    tag: Literal["resource"] = field(default="resource", init=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class DocumentSource:
    page: Literal["yaml", "managed-yaml", "details", "events", "evidence"]
    text: str = field(repr=False)
    tag: Literal["document"] = field(default="document", init=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class SingleLogsSource:
    options: LogOptions
    head_lines: int | None
    entries: tuple[LogEntry, ...] = field(repr=False)
    dropped_lines: int
    show_timestamps: bool
    tag: Literal["single-logs"] = field(default="single-logs", init=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class AggregateLogsSource:
    options: LogOptions
    head_lines: int | None
    records: tuple[AggregateLine, ...] = field(repr=False)
    dropped_lines: int
    json_mode: bool
    show_timestamps: bool
    source_filter: tuple[str, str] | None
    selected_sources: frozenset[tuple[str, str]] | None
    source_statuses: tuple[tuple[LogSource, str], ...]
    excess: int
    tag: Literal["aggregate-logs"] = field(default="aggregate-logs", init=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class DiagnosticsSource:
    snapshot: DiagnosticSnapshot = field(repr=False)
    tag: Literal["diagnostics"] = field(default="diagnostics", init=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class TableSource:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = field(repr=False)
    row_keys: tuple[str, ...]
    concealed_columns: frozenset[int]
    tag: Literal["table"] = field(default="table", init=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class SupportSource:
    diagnostics: ExportCapture | None = field(default=None, repr=False)
    resource: ExportCapture | None = field(default=None, repr=False)
    logs: ExportCapture | None = field(default=None, repr=False)
    omissions: tuple[str, ...] = ()
    tag: Literal["support"] = field(default="support", init=False)


type ExportSource = (
    ResourceSource
    | DocumentSource
    | SingleLogsSource
    | AggregateLogsSource
    | DiagnosticsSource
    | TableSource
    | SupportSource
)


@dataclass(frozen=True, kw_only=True, slots=True)
class ExportCapture:
    scope: ExportScope
    source: ExportSource = field(repr=False)
    presentation: ExportPresentation | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class ArtifactMetadata:
    schema_version: int
    format: ExportKind
    scope: ExportScope
    sensitive: bool
    presentation: ExportPresentation | None
    notices: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class PreparedArtifact:
    id: UUID
    metadata: ArtifactMetadata
    payload: bytes = field(repr=False)
    preview: str = field(repr=False)
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True, kw_only=True, slots=True)
class SensitiveApproval:
    nonce: UUID
    binding_sha256: str


@dataclass(frozen=True, kw_only=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int
    nlink: int


@dataclass(frozen=True, kw_only=True, slots=True)
class DirectoryRef:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True, kw_only=True, slots=True)
class ArtifactRef:
    directory: DirectoryRef
    name: str
    identity: FileIdentity
    sha256: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class DestinationReview:
    directory: DirectoryRef
    name: str
    expected: FileIdentity | None
    replace: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class FileOutcome:
    effect: Literal["none", "published", "deleted"]
    ref: ArtifactRef | None
    durable: bool
    cleanup_complete: bool
    notice: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class FileScan:
    refs: tuple[ArtifactRef, ...]
    limited: bool
    skipped: int


@dataclass(frozen=True, kw_only=True, slots=True)
class ArtifactEntry:
    ref: ArtifactRef
    metadata: ArtifactMetadata | None
    problem: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ArtifactListing:
    entries: tuple[ArtifactEntry, ...]
    limited: bool
    skipped: int
    notice: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class TextPage:
    index: int
    total: int
    text: str = field(repr=False)


def _invalid() -> AppError:
    return AppError("Invalid, unsupported or excessive local artifact.")


def _bounded(value: Any, depth: int = 0, count: list[int] | None = None) -> None:
    counter = [0] if count is None else count
    counter[0] += 1
    if depth > MAX_DEPTH or counter[0] > MAX_NODES:
        raise _invalid()
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid()
            _bounded(key, depth + 1, counter)
            _bounded(item, depth + 1, counter)
    elif isinstance(value, list):
        for item in value:
            _bounded(item, depth + 1, counter)
    elif isinstance(value, str):
        if len(value) > MAX_FIELD_CHARS:
            raise _invalid()
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise _invalid() from None
    elif (
        value is None
        or type(value) in {bool, int}
        or (type(value) is float and math.isfinite(value))
    ):
        pass
    else:
        raise _invalid()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise _invalid()


def _json_load(text: str) -> Any:
    try:
        result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        _bounded(result)
        return result
    except (ValueError, RecursionError):
        raise _invalid() from None


class _ArtifactLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        result: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise _invalid()
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _yaml_load(text: str) -> Any:
    try:
        depth = nodes = 0
        for event in yaml.parse(text):
            if isinstance(event, AliasEvent):
                raise _invalid()
            if isinstance(event, (ScalarEvent, CollectionStartEvent)):
                nodes += 1
                if event.tag is not None or event.anchor is not None:
                    raise _invalid()
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, (yaml.events.CollectionEndEvent,)):
                depth -= 1
            if depth > MAX_DEPTH or nodes > MAX_NODES:
                raise _invalid()
        result = yaml.load(text, Loader=_ArtifactLoader)
        _bounded(result)
        return result
    except (yaml.YAMLError, ValueError, RecursionError):
        raise _invalid() from None


def _json(value: Any) -> str:
    try:
        _bounded(value)
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, UnicodeError):
        raise _invalid() from None


def _safe_text(text: str) -> str:
    _bounded(text)
    return sanitize_text(text, allow_newlines=True)


def _redact(value: Any, *, key: str = "", secret: bool = False) -> Any:
    if key in {"annotations", "fieldsV1", "command", "args"} or _SENSITIVE.search(key):
        return REDACTED
    if secret and key in {"data", "stringData", "binaryData"}:
        return (
            {_safe_text(name): REDACTED for name in value} if isinstance(value, dict) else REDACTED
        )
    if isinstance(value, dict):
        secret = secret or value.get("kind") in ("Secret", "ConfigMap")
        inline = "name" in value and "value" in value
        return {
            _safe_text(name): REDACTED
            if inline and name == "value"
            else _redact(item, key=name, secret=secret)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secret=secret) for item in value]
    return _safe_text(value) if isinstance(value, str) else value


def _safe(value: Any) -> Any:
    _bounded(value)
    return _redact(value)


def _text(text: str) -> str:
    """Sanitize complete records, retaining key suppression beyond line/chunk boundaries."""
    output = []
    private = False
    for line in text.split("\n"):
        prefix = ""
        label = re.match(r"^\[s[0-9]+ [^\n\]]{1,512}\] ", line)
        if label is not None:
            prefix, line = label.group(), line[label.end() :]
        timestamp = TIMESTAMP.match(line)
        if timestamp is not None:
            prefix += timestamp.group()
            line = line[timestamp.end() :]
        prefix = _safe_text(prefix)
        markers = tuple(_KEY.finditer(line))
        hidden = private or any(match.group(1).upper() == "BEGIN" for match in markers)
        for match in markers:
            private = match.group(1).upper() == "BEGIN"
        if line.lstrip().startswith(("{", "[")):
            try:
                parsed = _json_load(line)
            except AppError:
                # Bracketed log labels/Rich markup are plain text. JSON-shaped
                # records must validate strictly; duplicate keys cannot demote a
                # nested Secret to unstructured prose and bypass its policy.
                if not hidden and not re.match(r'^\s*\[[^{}\[\]"\n,]{1,512}\]', line):
                    raise _invalid() from None
                output.append(prefix + ("[REDACTED KEY]" if hidden else _safe_text(line)))
            else:
                if hidden:
                    if isinstance(parsed, dict) and "payload" in parsed:
                        parsed["payload"] = "[REDACTED KEY]"
                    else:
                        parsed = "[REDACTED KEY]"
                output.append(prefix + _json(_safe(parsed)))
        else:
            output.append(prefix + ("[REDACTED KEY]" if hidden else _safe_text(line)))
    return "\n".join(output)


def _document_text(text: str) -> str:
    # Read-only details/events are often YAML. Disk format labels confer no trust.
    if re.match(r"\s*(?:apiVersion|kind|metadata|spec|status|data):|\s*- ", text):
        value = _yaml_load(text)
        return yaml.safe_dump(_safe(value), allow_unicode=True, sort_keys=False)
    return _text(text)


def _time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise _invalid()
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _scope(scope: ExportScope) -> dict[str, Any]:
    if scope.namespace_mode not in {"one", "all", "cluster", "local", "unknown"}:
        raise _invalid()
    return {
        "export_at": _time(scope.export_at),
        "source_at": _time(scope.source_at),
        "context": scope.context,
        "header_namespace": scope.header_namespace,
        "collection_namespace": scope.collection_namespace,
        "namespace_mode": scope.namespace_mode,
        "api_version": scope.api_version,
        "resource": scope.resource,
        "kind": scope.kind,
        "name": scope.name,
        "uid": scope.uid,
        "resource_version": scope.resource_version,
        "container": scope.container,
    }


def _presentation(value: ExportPresentation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    viewport = value.viewport
    if viewport is not None and (
        type(viewport.index) is not int
        or not all(
            type(number) in {int, float} and math.isfinite(number)
            for number in (viewport.x, viewport.y, viewport.top_offset)
        )
    ):
        raise _invalid()
    return {
        "view": value.view,
        "query": value.query,
        "sort": value.sort,
        "descending": value.descending,
        "viewport": None
        if viewport is None
        else {
            "selected": viewport.selected,
            "index": viewport.index,
            "x": viewport.x,
            "y": viewport.y,
            "top": viewport.top,
            "top_offset": viewport.top_offset,
        },
    }


def _metadata(value: ArtifactMetadata) -> dict[str, Any]:
    # Explicit field projection deliberately excludes runtime UUIDs and freshness guards.
    return cast(
        dict[str, Any],
        _safe(
            {
                "schema_version": value.schema_version,
                "format": value.format,
                "scope": _scope(value.scope),
                "sensitive": value.sensitive,
                "presentation": _presentation(value.presentation),
                "notices": list(value.notices),
            }
        ),
    )


def _fields(value: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != names:
        raise _invalid()
    return value


def _string(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise _invalid()
    return _safe_text(value)


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise _invalid()
    return value


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid() from None
    _time(result)
    return result.astimezone(UTC)


def _read_metadata(value: Any) -> ArtifactMetadata:
    data = _fields(
        value, {"schema_version", "format", "scope", "sensitive", "presentation", "notices"}
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise _invalid()
    if data["format"] not in (
        "resource-yaml",
        "logs",
        "diagnostics",
        "screen",
        "support",
        "legacy-report",
    ):
        raise _invalid()
    raw = _fields(
        data["scope"],
        {
            "export_at",
            "source_at",
            "context",
            "header_namespace",
            "collection_namespace",
            "namespace_mode",
            "api_version",
            "resource",
            "kind",
            "name",
            "uid",
            "resource_version",
            "container",
        },
    )
    if raw["namespace_mode"] not in ("one", "all", "cluster", "local", "unknown"):
        raise _invalid()
    scope = ExportScope(
        export_at=_datetime(raw["export_at"]),
        source_at=_datetime(raw["source_at"]),
        namespace_mode=raw["namespace_mode"],
        **{
            name: _string(raw[name], optional=True)
            for name in (
                "context",
                "header_namespace",
                "collection_namespace",
                "api_version",
                "resource",
                "kind",
                "name",
                "uid",
                "resource_version",
                "container",
            )
        },
    )
    presentation = None
    if data["presentation"] is not None:
        p = _fields(data["presentation"], {"view", "query", "sort", "descending", "viewport"})
        viewport = None
        if p["viewport"] is not None:
            v = _fields(p["viewport"], {"selected", "index", "x", "y", "top", "top_offset"})
            if type(v["index"]) is not int or not all(
                type(v[name]) in {int, float} and math.isfinite(v[name])
                for name in ("x", "y", "top_offset")
            ):
                raise _invalid()
            viewport = Viewport(
                _string(v["selected"], optional=True),
                v["index"],
                v["x"],
                v["y"],
                _string(v["top"], optional=True),
                v["top_offset"],
            )
        presentation = ExportPresentation(
            view=cast(str, _string(p["view"])),
            query=cast(str, _string(p["query"])),
            sort=_string(p["sort"], optional=True),
            descending=_boolean(p["descending"]),
            viewport=viewport,
        )
    notices = data["notices"]
    if not isinstance(notices, list) or not all(isinstance(notice, str) for notice in notices):
        raise _invalid()
    return ArtifactMetadata(
        schema_version=1,
        format=data["format"],
        scope=scope,
        sensitive=_boolean(data["sensitive"]),
        presentation=presentation,
        notices=tuple(_safe_text(notice) for notice in notices),
    )


def _api(resource: ApiResource | None) -> dict[str, Any] | None:
    return (
        None
        if resource is None
        else {
            "group": resource.group,
            "version": resource.version,
            "name": resource.name,
            "kind": resource.kind,
            "namespaced": resource.namespaced,
        }
    )


def _reference(ref: RelationshipRef | None) -> dict[str, Any] | None:
    return (
        None
        if ref is None
        else {
            "api_version": ref.api_version,
            "kind": ref.kind,
            "namespace": ref.namespace,
            "name": ref.name,
            "uid": ref.uid,
            "resource": _api(ref.resource),
        }
    )


def _diagnostics(snapshot: DiagnosticSnapshot) -> dict[str, Any]:
    return {
        "request": {
            "scope": {
                "context": snapshot.request.scope.session.context,
                "namespace": snapshot.request.scope.namespace,
                "root": _reference(snapshot.request.scope.root),
            }
        },
        "findings": [
            {
                "key": finding.key,
                "severity": finding.severity.value,
                "category": finding.category.value,
                "subject": _reference(finding.subject),
                "container": finding.container,
                "summary": finding.summary,
                "explanation": finding.explanation,
                "evidence": [
                    {
                        "key": evidence.key,
                        "source": evidence.source.value,
                        "ref": _reference(evidence.ref),
                        "field_path": evidence.field_path,
                        "reason": evidence.reason,
                        "message": evidence.message,
                        "observed_at": _time(evidence.observed_at),
                        "reported_at": _time(evidence.reported_at),
                        "historical": evidence.historical,
                    }
                    for evidence in finding.evidence
                ],
                "log_modes": sorted(mode.value for mode in finding.log_modes),
                "source": finding.source.value,
                "tool_version": finding.tool_version,
                "source_code": finding.source_code,
                "identity": finding.identity.value,
            }
            for finding in snapshot.findings
        ],
        "sources": [
            {
                "key": source.key,
                "kind": source.kind.value,
                "resource": _api(source.resource),
                "namespace": source.namespace,
                "status": source.status.value,
                "collection": None
                if source.collection is None
                else {
                    "complete": source.collection.complete,
                    "limited": source.collection.limited,
                    "pages": source.collection.pages,
                    "retained_bytes": source.collection.retained_bytes,
                },
                "resource_version": source.resource_version,
                "observed_at": _time(source.observed_at),
                "detail": source.detail,
                "omitted_findings": source.omitted_findings,
            }
            for source in snapshot.sources
        ],
        "collecting": snapshot.collecting,
        "native_requests_used": snapshot.native_requests_used,
        "observed_at": _time(snapshot.observed_at),
    }


def _options(options: LogOptions, head: int | None, dropped: int) -> dict[str, Any]:
    if head is not None and (type(head) is not int or head < 1):
        raise _invalid()
    if type(dropped) is not int or dropped < 0:
        raise _invalid()
    return {
        "follow": options.follow,
        "previous": options.previous,
        "timestamps": options.timestamps,
        "tail_lines": options.tail_lines,
        "since_seconds": options.since_seconds,
        "since_time": _time(options.since_time),
        "head_lines": head,
        "dropped_lines": dropped,
        "retained_only": True,
    }


def _log_source(source: LogSource) -> dict[str, Any]:
    return {
        "namespace": source.namespace,
        "pod": source.pod,
        "uid": source.uid,
        "container": source.container,
    }


def _log_document(value: Any) -> dict[str, Any]:
    common = {
        "follow",
        "previous",
        "timestamps",
        "tail_lines",
        "since_seconds",
        "since_time",
        "head_lines",
        "dropped_lines",
        "retained_only",
        "tag",
    }
    if not isinstance(value, dict) or value.get("tag") not in ("single-logs", "aggregate-logs"):
        raise _invalid()
    aggregate = value["tag"] == "aggregate-logs"
    _fields(
        value,
        common
        | (
            {"json_mode", "source_filter", "selected_sources", "source_statuses", "excess"}
            if aggregate
            else set()
        ),
    )
    options = LogOptions(
        follow=_boolean(value["follow"]),
        previous=_boolean(value["previous"]),
        timestamps=_boolean(value["timestamps"]),
        tail_lines=value["tail_lines"],
        since_seconds=value["since_seconds"],
        since_time=_datetime(value["since_time"]),
    )
    _options(options, value["head_lines"], value["dropped_lines"])
    if value["retained_only"] is not True:
        raise _invalid()
    if aggregate:
        _boolean(value["json_mode"])
        for key in [
            value["source_filter"],
            *([] if value["selected_sources"] is None else _list(value["selected_sources"])),
        ]:
            if key is not None and (
                not isinstance(key, list)
                or len(key) != 2
                or not all(isinstance(part, str) for part in key)
            ):
                raise _invalid()
        for status in _list(value["source_statuses"]):
            _fields(status, {"source", "status"})
            _fields(status["source"], {"namespace", "pod", "uid", "container"})
            for text in (*status["source"].values(), status["status"]):
                _string(text)
        if type(value["excess"]) is not int or value["excess"] < 0:
            raise _invalid()
    return cast(dict[str, Any], _safe(value))


def _logs(source: SingleLogsSource | AggregateLogsSource, *, screen: bool) -> str:
    descriptor = _options(source.options, source.head_lines, source.dropped_lines)
    descriptor["tag"] = source.tag
    if isinstance(source, SingleLogsSource):
        lines = [entry.text(source.show_timestamps if screen else True) for entry in source.entries]
    else:
        descriptor.update(
            {
                "json_mode": source.json_mode,
                "source_filter": list(source.source_filter) if source.source_filter else None,
                "selected_sources": None
                if source.selected_sources is None
                else [list(key) for key in sorted(source.selected_sources)],
                "source_statuses": [
                    {"source": _log_source(item), "status": status}
                    for item, status in source.source_statuses
                ],
                "excess": source.excess,
            }
        )
        lines = []
        for record in source.records:
            if source.source_filter is not None and record.source.key != source.source_filter:
                continue
            if (
                source.selected_sources is not None
                and record.source.key not in source.selected_sources
            ):
                continue
            # Export facts always retain identity, timestamp and line numbers in JSON records.
            if not screen or source.json_mode:
                lines.append(
                    _json(
                        {
                            "source": {"id": record.source_number, **_log_source(record.source)},
                            "line": record.number,
                            "timestamp": record.timestamp
                            if not screen or source.show_timestamps
                            else None,
                            "payload": _json_load(record.structured)
                            if record.structured is not None
                            else record.payload,
                        }
                    )
                )
            else:
                lines.append(record.text(json_mode=False, timestamps=source.show_timestamps))
    text = _text("\n".join(lines))
    return text if screen else _LOG_PREFIX + _json(_safe(descriptor)) + "\n" + text


def _table(source: TableSource) -> str:
    if (
        len(source.rows) != len(source.row_keys)
        or len(set(source.row_keys)) != len(source.row_keys)
        or any(len(row) != len(source.columns) for row in source.rows)
        or any(
            type(index) is not int or not 0 <= index < len(source.columns)
            for index in source.concealed_columns
        )
    ):
        raise _invalid()
    rows = ["\t".join(_safe_text(column) for column in source.columns)]
    rows.extend(
        "\t".join(
            "[REDACTED COLUMN]" if index in source.concealed_columns else _safe_text(cell)
            for index, cell in enumerate(row)
        )
        for row in source.rows
    )
    return "\n".join(rows)


def _report(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
    ):
        raise _invalid()
    required = {
        "schema_version",
        "version",
        "python",
        "platform",
        "terminal",
        "config_check",
        "recent_log",
    }
    if not required <= set(value) or set(value) - required - {"failure"}:
        raise _invalid()
    for name in ("version", "python", "platform"):
        _string(value[name])
    if value["config_check"] not in ("valid", "invalid", "missing", "unavailable"):
        raise _invalid()
    if not isinstance(value["terminal"], dict) or set(value["terminal"]) - {
        "stdin_tty",
        "stdout_tty",
        "columns",
        "rows",
    }:
        raise _invalid()
    if not {"stdin_tty", "stdout_tty"} <= set(value["terminal"]):
        raise _invalid()
    for name in ("stdin_tty", "stdout_tty"):
        _boolean(value["terminal"][name])
    for name in ("columns", "rows"):
        if name in value["terminal"] and (
            type(value["terminal"][name]) is not int or value["terminal"][name] < 1
        ):
            raise _invalid()
    recent = value["recent_log"]
    if not isinstance(recent, dict) or set(recent) - {"status", "text"} or "status" not in recent:
        raise _invalid()
    if recent["status"] not in ("included", "unavailable"):
        raise _invalid()
    if recent["status"] == "included":
        _string(recent.get("text"))
    elif "text" in recent:
        raise _invalid()
    if "failure" in value:
        failure = _fields(value["failure"], {"kind", "frames"})
        _string(failure["kind"])
        if not isinstance(failure["frames"], list):
            raise _invalid()
        if len(failure["frames"]) > 32:
            raise _invalid()
        for frame in failure["frames"]:
            _fields(frame, {"file", "line", "function"})
            validate_basename(cast(str, _string(frame["file"])))
            _string(frame["function"])
            if type(frame["line"]) is not int or frame["line"] < 1:
                raise _invalid()
    return cast(dict[str, Any], _safe(value))


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid()
    return value


def _reference_document(value: Any) -> None:
    if value is None:
        return
    ref = _fields(value, {"api_version", "kind", "namespace", "name", "uid", "resource"})
    for key in ("api_version", "kind", "name"):
        _string(ref[key])
    for key in ("namespace", "uid"):
        _string(ref[key], optional=True)
    _api_document(ref["resource"])


def _api_document(value: Any) -> None:
    if value is not None:
        resource = _fields(value, {"group", "version", "name", "kind", "namespaced"})
        for key in ("group", "version", "name", "kind"):
            _string(resource[key])
        _boolean(resource["namespaced"])


def _diagnostic_document(value: Any) -> dict[str, Any]:
    """Validate the persisted factual schema; disk cannot add session/producer internals."""
    data = _fields(
        value,
        {"request", "findings", "sources", "collecting", "native_requests_used", "observed_at"},
    )
    request = _fields(data["request"], {"scope"})
    scope = _fields(request["scope"], {"context", "namespace", "root"})
    _string(scope["context"])
    _string(scope["namespace"], optional=True)
    _reference_document(scope["root"])
    _boolean(data["collecting"])
    if type(data["native_requests_used"]) is not int or data["native_requests_used"] < 0:
        raise _invalid()
    _datetime(data["observed_at"])
    for finding in _list(data["findings"]):
        _fields(
            finding,
            {
                "key",
                "severity",
                "category",
                "subject",
                "container",
                "summary",
                "explanation",
                "evidence",
                "log_modes",
                "source",
                "tool_version",
                "source_code",
                "identity",
            },
        )
        _reference_document(finding["subject"])
        for name in ("key", "severity", "category", "summary", "explanation", "source", "identity"):
            _string(finding[name])
        for name in ("container", "tool_version", "source_code"):
            _string(finding[name], optional=True)
        for mode in _list(finding["log_modes"]):
            _string(mode)
        for evidence in _list(finding["evidence"]):
            _fields(
                evidence,
                {
                    "key",
                    "source",
                    "ref",
                    "field_path",
                    "reason",
                    "message",
                    "observed_at",
                    "reported_at",
                    "historical",
                },
            )
            _reference_document(evidence["ref"])
            for name in ("key", "source", "field_path", "message"):
                _string(evidence[name])
            _string(evidence["reason"], optional=True)
            _datetime(evidence["observed_at"])
            _datetime(evidence["reported_at"])
            _boolean(evidence["historical"])
    for source in _list(data["sources"]):
        _fields(
            source,
            {
                "key",
                "kind",
                "resource",
                "namespace",
                "status",
                "collection",
                "resource_version",
                "observed_at",
                "detail",
                "omitted_findings",
            },
        )
        _api_document(source["resource"])
        for name in ("key", "kind", "status", "detail"):
            _string(source[name])
        for name in ("namespace", "resource_version"):
            _string(source[name], optional=True)
        _datetime(source["observed_at"])
        if type(source["omitted_findings"]) is not int or source["omitted_findings"] < 0:
            raise _invalid()
        collection = source["collection"]
        if collection is not None:
            _fields(collection, {"complete", "limited", "pages", "retained_bytes"})
            _boolean(collection["complete"])
            _boolean(collection["limited"])
            for name in ("pages", "retained_bytes"):
                if type(collection[name]) is not int or collection[name] < 0:
                    raise _invalid()
    return cast(dict[str, Any], _safe(data))


def available_formats(capture: ExportCapture) -> tuple[ExportKind, ...]:
    source = capture.source
    if isinstance(source, ResourceSource):
        return ("resource-yaml",)
    if isinstance(source, DocumentSource):
        return (
            ("resource-yaml", "screen") if source.page in {"yaml", "managed-yaml"} else ("screen",)
        )
    if isinstance(source, (SingleLogsSource, AggregateLogsSource)):
        return ("logs", "screen")
    if isinstance(source, DiagnosticsSource):
        return ("diagnostics",)
    if isinstance(source, TableSource):
        return ("screen",)
    return ("support",)


def _body(
    capture: ExportCapture, kind: ExportKind, *, sensitive: bool, report_json: bytes | None
) -> Any:
    source = capture.source
    if isinstance(source, ResourceSource):
        if source.record.metadata_only:
            raise AppError("A full captured resource is required for export.")
        value = source.record.manifest
        _bounded(value)
        return yaml.safe_dump(
            value if sensitive else _safe(value), allow_unicode=True, sort_keys=False
        )
    if isinstance(source, DocumentSource):
        if source.page in {"yaml", "managed-yaml"}:
            parsed = _yaml_load(source.text)
            if not isinstance(parsed, dict):
                raise _invalid()
            return yaml.safe_dump(_safe(parsed), allow_unicode=True, sort_keys=False)
        return _document_text(source.text)
    if isinstance(source, (SingleLogsSource, AggregateLogsSource)):
        return _logs(source, screen=kind == "screen")
    if isinstance(source, TableSource):
        return _table(source)
    if isinstance(source, DiagnosticsSource):
        return _safe(_diagnostics(source.snapshot))
    if report_json is None:
        raise AppError("A safe application report is required for a support export.")
    result: dict[str, Any] = {
        "report": _report(_json_load(_decode(report_json))),
        "omissions": list(source.omissions),
    }
    for role, component, expected in (
        ("diagnostics", source.diagnostics, "diagnostics"),
        ("resource", source.resource, "resource-yaml"),
        ("logs", source.logs, "logs"),
    ):
        if component is None:
            result[role] = None
        else:
            if isinstance(component.source, SupportSource) or expected not in available_formats(
                component
            ):
                raise _invalid()
            component_body = _body(component, expected, sensitive=False, report_json=None)
            if role == "resource":
                component_body = _yaml_load(component_body)
            elif role == "logs":
                descriptor, _, records = component_body.partition("\n")
                component_body = {
                    "provenance": _json_load(descriptor[len(_LOG_PREFIX) :]),
                    "records": records.split("\n"),
                }
            result[role] = {
                "scope": _safe(_scope(component.scope)),
                "notices": [_safe_text(item) for item in component.notices],
                "payload": component_body,
            }
    return _safe(result)


def _decode(payload: bytes) -> str:
    if not payload or len(payload) > MAX_ARTIFACT_BYTES:
        raise _invalid()
    try:
        return payload.decode("utf-8")
    except UnicodeError:
        raise _invalid() from None


def _page_text(text: str) -> tuple[str, ...]:
    pages: list[str] = []
    current: list[str] = []
    size = 0
    for character in text:
        length = len(character.encode("utf-8"))
        if size + length > MAX_PAGE_BYTES:
            pages.append("".join(current))
            current, size = [], 0
        current.append(character)
        size += length
    pages.append("".join(current))
    return tuple(pages)


def _prepared(
    metadata: ArtifactMetadata, body: Any, artifact_id: UUID, *, preview_body: Any | None = None
) -> PreparedArtifact:
    meta = _metadata(metadata)
    encoded_meta = _json(meta)
    prefix_size = (
        len(JSON_PREFIX) + 2
        if metadata.format in {"diagnostics", "support", "legacy-report"}
        else len(TEXT_PREFIX) + 1
    )
    if len(encoded_meta.encode("utf-8")) + prefix_size > MAX_METADATA_BYTES:
        raise AppError("Export metadata exceeds 8 KiB; content was not truncated.")
    metadata = _read_metadata(meta)
    if metadata.format in {"diagnostics", "support", "legacy-report"}:
        text = JSON_PREFIX + encoded_meta + ',\n"payload":' + _json(body) + "}\n"
    else:
        text = TEXT_PREFIX + encoded_meta + "\n" + body
        if not text.endswith("\n"):
            text += "\n"
    payload = text.encode("utf-8")
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise AppError("Export exceeds 16 MiB; content was not truncated.")
    preview = body if preview_body is None else preview_body
    if not isinstance(preview, str):
        preview = _json(preview)
    preview = escape_controls(preview, allow_newlines=True)
    return PreparedArtifact(
        id=artifact_id,
        metadata=metadata,
        payload=payload,
        preview=_page_text(preview)[0],
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def prepare_capture(
    capture: ExportCapture,
    kind: ExportKind,
    *,
    artifact_id: UUID,
    sensitive: bool = False,
    report_json: bytes | None = None,
) -> PreparedArtifact:
    if kind not in available_formats(capture):
        raise AppError("That format is unavailable for this captured source.")
    if sensitive and not (isinstance(capture.source, ResourceSource) and kind == "resource-yaml"):
        raise AppError("Sensitive export is available only for a full live resource YAML capture.")
    notices = capture.notices
    if isinstance(capture.source, DocumentSource):
        notices += (f"Captured document page: {capture.source.page}.",)
    metadata = ArtifactMetadata(
        schema_version=1,
        format=kind,
        scope=capture.scope,
        sensitive=sensitive,
        presentation=capture.presentation,
        notices=notices,
    )
    body = _body(capture, kind, sensitive=sensitive, report_json=report_json)
    preview = _body(capture, kind, sensitive=False, report_json=report_json) if sensitive else body
    return _prepared(metadata, body, artifact_id, preview_body=preview)


def _prefix(text: str) -> ArtifactMetadata | None:
    line, separator, _ = text.partition("\n")
    if not separator or len(line.encode("utf-8")) + 1 > MAX_METADATA_BYTES:
        return None
    if line.startswith(TEXT_PREFIX):
        raw = line[len(TEXT_PREFIX) :]
    elif line.startswith(JSON_PREFIX) and line.endswith(","):
        raw = line[len(JSON_PREFIX) : -1]
    else:
        return None
    return _read_metadata(_json_load(raw))


def inspect_metadata(prefix: bytes) -> ArtifactMetadata | None:
    try:
        # The adapter intentionally reads metadata bound plus a sentinel.
        line, separator, _ = prefix.partition(b"\n")
        return _prefix((line + separator).decode("utf-8"))
    except (AppError, UnicodeError, TypeError):
        return None


def _read_body(metadata: ArtifactMetadata, body: Any, *, sensitive: bool) -> tuple[Any, Any]:
    safe: Any
    kind = metadata.format
    if kind == "resource-yaml":
        value = _yaml_load(body)
        if not isinstance(value, dict):
            raise _invalid()
        safe = yaml.safe_dump(_safe(value), allow_unicode=True, sort_keys=False)
        return yaml.safe_dump(
            value, allow_unicode=True, sort_keys=False
        ) if sensitive else safe, safe
    if kind in {"screen", "logs"}:
        if kind == "logs":
            line, separator, content = body.partition("\n")
            if not line.startswith(_LOG_PREFIX) or not separator:
                raise _invalid()
            descriptor = _json_load(line[len(_LOG_PREFIX) :])
            safe = _LOG_PREFIX + _json(_log_document(descriptor)) + "\n" + _text(content)
        else:
            safe = _document_text(body)
        return safe, safe
    if kind == "legacy-report":
        safe = _report(body)
    elif kind == "diagnostics":
        safe = _diagnostic_document(body)
    else:
        if not isinstance(body, dict):
            raise _invalid()
        safe = _safe(body)
        _fields(body, {"report", "omissions", "diagnostics", "resource", "logs"})
        safe["report"] = _report(body["report"])
        if not all(isinstance(item, str) for item in _list(body["omissions"])):
            raise _invalid()
        for role in ("diagnostics", "resource", "logs"):
            if body[role] is not None:
                component = _fields(body[role], {"scope", "notices", "payload"})
                component_metadata = _metadata(metadata)
                component_metadata["scope"] = component["scope"]
                component_metadata["notices"] = component["notices"]
                _read_metadata(component_metadata)
                if role == "diagnostics":
                    safe[role]["payload"] = _diagnostic_document(component["payload"])
                elif role == "resource":
                    if not isinstance(component["payload"], dict):
                        raise _invalid()
                    safe[role]["payload"] = _safe(component["payload"])
                else:
                    logs = _fields(component["payload"], {"provenance", "records"})
                    records = _list(logs["records"])
                    if not isinstance(logs["provenance"], dict) or not all(
                        isinstance(record, str) for record in records
                    ):
                        raise _invalid()
                    safe[role]["payload"] = {
                        "provenance": _log_document(logs["provenance"]),
                        "records": _text("\n".join(records)).split("\n"),
                    }
    return safe, safe


def read_artifact(
    payload: bytes, *, artifact_id: UUID, sensitive: bool = False
) -> PreparedArtifact:
    text = _decode(payload)
    body: Any
    metadata = _prefix(text)
    if metadata is None:
        body = _report(_json_load(text))
        metadata = ArtifactMetadata(
            schema_version=1,
            format="legacy-report",
            sensitive=False,
            presentation=None,
            scope=ExportScope(
                export_at=None,
                source_at=None,
                context=None,
                header_namespace=None,
                collection_namespace=None,
                namespace_mode="unknown",
            ),
            notices=("Legacy report: original context, scope and times are unknown.",),
        )
    elif text.startswith(JSON_PREFIX):
        envelope = _fields(_json_load(text), {"kuberich_export", "payload"})
        # Validate the complete header independently of the listing hint.
        metadata = _read_metadata(envelope["kuberich_export"])
        if metadata.format not in {"diagnostics", "support", "legacy-report"}:
            raise _invalid()
        body = envelope["payload"]
    else:
        if metadata.format not in {"resource-yaml", "logs", "screen"}:
            raise _invalid()
        body = text.partition("\n")[2]
    if sensitive and metadata.format != "resource-yaml":
        raise AppError("Sensitive reading is available only for resource YAML artifacts.")
    body, preview = _read_body(metadata, body, sensitive=sensitive)
    return _prepared(
        replace(metadata, sensitive=sensitive), body, artifact_id, preview_body=preview
    )


def artifact_page(prepared: PreparedArtifact, index: int) -> TextPage:
    text = _decode(prepared.payload)
    if text.startswith(JSON_PREFIX):
        value = _json_load(text)["payload"]
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    else:
        text = text.partition("\n")[2]
    pages = _page_text(escape_controls(text, allow_newlines=True))
    if type(index) is not int or not 0 <= index < len(pages):
        raise AppError("That artifact page is unavailable.")
    return TextPage(index=index, total=len(pages), text=pages[index])


def validate_basename(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or len(name.encode("utf-8", errors="surrogatepass")) > 255
        or escape_controls(name) != name
    ):
        raise AppError("Choose a direct filename without separators, dot components or controls.")
    return name


def matches_entry(entry: ArtifactEntry, query: str) -> bool:
    if not query:
        return True
    metadata = entry.metadata
    values = [entry.ref.name, entry.problem or ""]
    if metadata is not None:
        values.extend(
            (
                metadata.format,
                metadata.scope.context or "",
                metadata.scope.name or "",
                metadata.scope.header_namespace or "",
                metadata.scope.collection_namespace or "",
            )
        )
    return (
        _safe_text(query).casefold() in " ".join(_safe_text(value) for value in values).casefold()
    )
