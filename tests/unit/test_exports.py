"""Real codec round trips, hostile inputs and retained factual export contracts."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from kuberich.domain.aggregate_logs import AggregateLine, LogSource
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
from kuberich.domain.exports import (
    JSON_PREFIX,
    MAX_ARTIFACT_BYTES,
    MAX_METADATA_BYTES,
    MAX_PAGE_BYTES,
    TEXT_PREFIX,
    AggregateLogsSource,
    ArtifactEntry,
    ArtifactRef,
    DiagnosticsSource,
    DirectoryRef,
    DocumentSource,
    ExportCapture,
    ExportPresentation,
    ExportScope,
    FileIdentity,
    ResourceSource,
    SingleLogsSource,
    SupportSource,
    TableSource,
    artifact_page,
    available_formats,
    inspect_metadata,
    matches_entry,
    prepare_capture,
    read_artifact,
    validate_basename,
)
from kuberich.domain.log_view import LogEntry
from kuberich.domain.logs import LogLine, LogOptions
from kuberich.domain.navigation import Viewport
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, CollectionState, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError

AT = datetime(2026, 11, 5, 12, 30, tzinfo=UTC)
ID = UUID("00000000-0000-0000-0000-000000000073")
FIXTURES = Path(__file__).parents[1] / "fixtures" / "exports"
API = ApiResource("", "v1", "lists", "List", True, frozenset({"get"}))
SCOPE = ExportScope(
    export_at=AT,
    source_at=AT - timedelta(seconds=10),
    context="synthetic",
    header_namespace="header",
    collection_namespace="fixture",
    namespace_mode="one",
    api_version="v1",
    resource="lists",
    kind="List",
    name="synthetic-list",
    uid="list-uid",
    resource_version="7",
    container="app",
)
PRESENTATION = ExportPresentation(
    view="fixture",
    query="running",
    sort="name",
    descending=True,
    viewport=Viewport("list-uid", 2, 1.5, 3, "top", 0.5),
)


def capture(source, *, presentation=PRESENTATION):
    return ExportCapture(
        scope=SCOPE,
        source=source,
        presentation=presentation,
        notices=("Retained observations only.",),
    )


def resource_source():
    raw = json.loads((FIXTURES / "nested-resource.json").read_text())
    return ResourceSource(resource=API, record=resource_record(API, raw))


def single_source(*, text=None):
    lines = text if text is not None else ("2026-11-05T12:29:50Z ready", "Bearer LOG_SENTINEL")
    return SingleLogsSource(
        options=LogOptions(previous=True, since_seconds=60),
        head_lines=1000,
        entries=tuple(LogEntry(index, LogLine(line)) for index, line in enumerate(lines, 1)),
        dropped_lines=3,
        show_timestamps=False,
    )


def aggregate_source():
    source = LogSource("fixture", "pod", "pod-uid", "app", "INTERNAL_START_TOKEN")
    other = LogSource("fixture", "other", "other-uid", "sidecar")
    return AggregateLogsSource(
        options=LogOptions(since_time=AT),
        head_lines=None,
        records=(
            AggregateLine(1, source, 1, "2026-11-05T12:29:50Z", "ready", None),
            AggregateLine(2, other, 2, None, "omitted-by-filter", None),
            AggregateLine(
                3, source, 1, None, "", '{"kind":"Secret","data":{"normal":"AGG_SENTINEL"}}'
            ),
        ),
        dropped_lines=9,
        json_mode=False,
        show_timestamps=False,
        source_filter=source.key,
        selected_sources=frozenset({source.key}),
        source_statuses=((source, "ready"), (other, "denied")),
        excess=2,
    )


def snapshot(*, root=True):
    api = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get"}), ("po",))
    ref = RelationshipRef("v1", "Pod", "fixture", "pod", "pod-uid", api)
    name_only = RelationshipRef("v1", "Pod", "fixture", "historical", None, None)
    evidence = DiagnosticEvidence(
        "evidence",
        DiagnosticSourceKind.EVENT,
        ref,
        "message",
        None,
        "Bearer DIAGNOSTIC_SENTINEL",
        AT,
        AT - timedelta(hours=2),
        True,
    )
    finding = DiagnosticFinding(
        "finding",
        DiagnosticSeverity.WARNING,
        DiagnosticCategory.SCHEDULING,
        name_only,
        None,
        "Observed failure",
        "Identity remains name-only.",
        (evidence,),
        frozenset({DiagnosticLogMode.CURRENT, DiagnosticLogMode.PREVIOUS}),
        DiagnosticSourceKind.POPEYE,
        "0.22.1",
        "POP-101",
        DiagnosticIdentity.NAME_ONLY,
    )
    sources = (
        DiagnosticSource(
            "native",
            DiagnosticSourceKind.EVENT,
            api,
            "fixture",
            DiagnosticStatus.PARTIAL,
            CollectionState(False, True, 2, 100),
            "version-4",
            AT,
            "Collection limited.",
            3,
        ),
        DiagnosticSource(
            "external",
            DiagnosticSourceKind.POPEYE,
            None,
            None,
            DiagnosticStatus.CANCELLED,
            None,
            None,
            None,
            "Cancelled.",
            4,
        ),
    )
    return DiagnosticSnapshot(
        DiagnosticRequest(
            DiagnosticScope(SessionIdentity("synthetic", 8, ID), "fixture", ref if root else None),
            99,
        ),
        (finding,),
        sources,
        True,
        5,
        AT,
    )


def report():
    return {
        "schema_version": 1,
        "version": "0.3.0",
        "python": "3.12",
        "platform": "linux",
        "terminal": {"stdin_tty": True, "stdout_tty": True, "columns": 80, "rows": 24},
        "config_check": "valid",
        "recent_log": {"status": "included", "text": "Bearer REPORT_SENTINEL"},
        "failure": {
            "kind": "ExampleError",
            "frames": [{"file": "main.py", "line": 3, "function": "main"}],
        },
    }


def prepared(source, kind, **kwargs):
    return prepare_capture(capture(source), kind, artifact_id=ID, **kwargs)


def envelope(metadata, body):
    meta = json.dumps(metadata, separators=(",", ":"))
    if metadata["format"] in ("diagnostics", "support", "legacy-report"):
        return (JSON_PREFIX + meta + ',\n"payload":' + json.dumps(body) + "}\n").encode()
    return (TEXT_PREFIX + meta + "\n" + body).encode()


def metadata_for(kind="screen"):
    sample = prepared(DocumentSource(page="evidence", text="safe"), "screen")
    value = json.loads(sample.payload.decode().splitlines()[0][len(TEXT_PREFIX) :])
    value["format"] = kind
    return value


def test_nested_resource_default_and_sensitive_roundtrip_golden():
    source = resource_source()
    default = prepared(source, "resource-yaml")
    assert default.payload == (FIXTURES / "default-resource.yaml").read_bytes()
    assert default.size_bytes == len(default.payload)
    assert default.sha256 == hashlib.sha256(default.payload).hexdigest()
    assert str(ID) not in default.payload.decode()
    for marker in (
        "ANNOTATION",
        "BINARY",
        "SECRET",
        "ENCODED",
        "CONFIG",
        "ENV",
        "COMMAND",
        "ARG",
        "PASSWORD",
        "URL",
        "BEARER",
        "BASIC",
        "PRIVATE",
    ):
        assert f"{marker}_SENTINEL" not in default.payload.decode()
    assert "safe-reference" in default.preview and "[bold]literal[/bold]" in default.preview
    assert (
        "\x1b" not in default.preview
        and "\r" not in default.preview
        and "\u202e" not in default.preview
    )
    assert yaml.safe_load(default.payload)["kind"] == "List"
    assert read_artifact(default.payload, artifact_id=ID).payload == default.payload
    sensitive = prepared(source, "resource-yaml", sensitive=True)
    assert b"SECRET_SENTINEL" in sensitive.payload and "SECRET_SENTINEL" not in sensitive.preview
    assert read_artifact(sensitive.payload, artifact_id=ID).payload == default.payload
    raw = read_artifact(sensitive.payload, artifact_id=ID, sensitive=True)
    assert raw.metadata.sensitive and b"SECRET_SENTINEL" in raw.payload
    assert "SECRET_SENTINEL" not in raw.preview
    assert "SECRET_SENTINEL" in artifact_page(raw, 0).text
    assert "SECRET_SENTINEL" not in repr(source) + repr(sensitive)


@pytest.mark.parametrize("page", ["yaml", "managed-yaml"])
def test_loaded_document_stays_redacted_and_preserves_page(page):
    source = DocumentSource(page=page, text="kind: Secret\ndata:\n  ordinary: LOADED_SENTINEL\n")
    assert available_formats(capture(source)) == ("resource-yaml", "screen")
    for kind in available_formats(capture(source)):
        result = prepared(source, kind)
        assert b"LOADED_SENTINEL" not in result.payload
        assert read_artifact(result.payload, artifact_id=ID).metadata.format == kind
    with pytest.raises(AppError, match="Sensitive export"):
        prepared(source, "resource-yaml", sensitive=True)


@pytest.mark.parametrize("page", ["details", "events", "evidence"])
def test_document_formats_and_literal_text(page):
    source = DocumentSource(
        page=page, text="[bold]literal[/bold]\nBearer TEXT_SENTINEL\n\x1b[31mred"
    )
    assert available_formats(capture(source)) == ("screen",)
    output = prepared(source, "screen")
    assert "[bold]literal[/bold]" in output.preview and "TEXT_SENTINEL" not in output.preview
    assert "\x1b" not in artifact_page(output, 0).text
    with pytest.raises(AppError, match="unavailable"):
        prepared(source, "logs")


def test_logs_complete_over_64k_split_keys_structured_nested_and_golden():
    source = single_source()
    result = prepared(source, "logs")
    assert result.payload == (FIXTURES / "single-logs.txt").read_bytes()
    assert available_formats(capture(source)) == ("logs", "screen")
    assert "2026-11-05T12:29:50Z" in result.preview
    assert "2026-11-05T12:29:50Z" not in prepared(source, "screen").preview
    lines = [f"line-{index:04d} {'x' * 80}" for index in range(900)]
    lines += [
        "-----BEGIN PRIVATE KEY-----",
        "SPLIT_SENTINEL",
        "-----END PRIVATE KEY-----",
        '{"kind":"ConfigMap","data":{"simple":"LOG_CONFIG_SENTINEL"}}',
        "tail survives",
    ]
    output = prepared(single_source(text=lines), "logs")
    assert len(output.payload) > 65536 and b"tail survives" in output.payload
    assert b"SPLIT_SENTINEL" not in output.payload and b"LOG_CONFIG_SENTINEL" not in output.payload
    assert b"tail survives" in read_artifact(output.payload, artifact_id=ID).payload
    forged = envelope(
        metadata_for("logs"),
        result.payload.decode().partition("\n")[2]
        + "\n-----BEGIN PRIVATE KEY-----\nDISK_KEY_SENTINEL\n-----END PRIVATE KEY-----\nAFTER_KEY\n",
    )
    reread = read_artifact(forged, artifact_id=ID)
    assert b"DISK_KEY_SENTINEL" not in reread.payload and b"AFTER_KEY" in reread.payload
    with pytest.raises(AppError, match="Sensitive"):
        read_artifact(result.payload, artifact_id=ID, sensitive=True)


def test_aggregate_preserves_source_facts_filter_statuses_and_screen_modes():
    source = aggregate_source()
    assert available_formats(capture(source)) == ("logs", "screen")
    result = prepared(source, "logs")
    assert b"omitted-by-filter" not in result.payload and b"AGG_SENTINEL" not in result.payload
    assert b"INTERNAL_START_TOKEN" not in result.payload
    assert b'"status":"denied"' in result.payload and b'"excess":2' in result.payload
    assert b'"uid":"pod-uid"' in result.payload and b'"line":3' in result.payload
    assert b'"timestamp":"2026-11-05T12:29:50Z"' in result.payload
    assert result.payload == read_artifact(result.payload, artifact_id=ID).payload
    assert "[s1 fixture/pod:app uid=pod-uid]" in prepared(source, "screen").preview
    assert '"timestamp":null' in prepared(replace(source, json_mode=True), "screen").preview
    all_sources = prepared(replace(source, source_filter=None, selected_sources=None), "logs")
    assert b"omitted-by-filter" in all_sources.payload
    none_selected = prepared(
        replace(source, source_filter=None, selected_sources=frozenset()), "logs"
    )
    assert b"omitted-by-filter" not in none_selected.payload


def test_diagnostics_full_factual_projection_and_golden():
    result = prepared(DiagnosticsSource(snapshot=snapshot()), "diagnostics")
    assert available_formats(capture(DiagnosticsSource(snapshot=snapshot()))) == ("diagnostics",)
    assert result.payload == (FIXTURES / "diagnostics.json").read_bytes()
    data = json.loads(result.payload)["payload"]
    assert data["request"]["scope"]["context"] == "synthetic"
    assert data["request"]["scope"]["namespace"] == "fixture"
    assert data["request"]["scope"]["root"]["resource"] == {
        "group": "",
        "version": "v1",
        "name": "pods",
        "kind": "Pod",
        "namespaced": True,
    }
    assert result.metadata.scope.header_namespace == "header"
    finding = data["findings"][0]
    assert finding["identity"] == "name_only" and finding["subject"]["uid"] is None
    assert finding["tool_version"] == "0.22.1" and finding["source_code"] == "POP-101"
    assert finding["evidence"][0]["historical"]
    assert finding["evidence"][0]["reported_at"] == "2026-11-05T10:30:00Z"
    assert data["sources"][0]["collection"] == {
        "complete": False,
        "limited": True,
        "pages": 2,
        "retained_bytes": 100,
    }
    assert data["sources"][1]["omitted_findings"] == 4
    assert data["collecting"] and data["native_requests_used"] == 5
    assert str(ID) not in result.payload.decode()
    assert not any(
        key in result.payload.decode()
        for key in (
            "connection_id",
            "generation",
            "revision",
            "aliases",
            "verbs",
            "DIAGNOSTIC_SENTINEL",
        )
    )
    assert read_artifact(result.payload, artifact_id=ID).payload == result.payload
    assert '"request": {' in artifact_page(result, 0).text
    without_root = prepared(DiagnosticsSource(snapshot=snapshot(root=False)), "diagnostics")
    assert json.loads(without_root.payload)["payload"]["request"]["scope"]["root"] is None


def test_support_fixed_roles_inspectable_optins_and_legacy_report():
    source = SupportSource(
        diagnostics=capture(DiagnosticsSource(snapshot=snapshot())),
        resource=capture(resource_source()),
        logs=capture(single_source()),
        omissions=("Events unavailable.",),
    )
    assert available_formats(capture(source)) == ("support",)
    result = prepared(source, "support", report_json=json.dumps(report()).encode())
    assert result.payload == (FIXTURES / "support.json").read_bytes()
    assert read_artifact(result.payload, artifact_id=ID).payload == result.payload
    assert b"REPORT_SENTINEL" not in result.payload and b"SECRET_SENTINEL" not in result.payload
    empty = prepared(
        SupportSource(omissions=("Resource omitted by choice.",)),
        "support",
        report_json=json.dumps(report()).encode(),
    )
    body = json.loads(empty.payload)["payload"]
    assert body["resource"] is body["diagnostics"] is body["logs"] is None
    assert "omitted by choice" in body["omissions"][0]
    with pytest.raises(AppError, match="report is required"):
        prepared(source, "support")
    with pytest.raises(AppError):
        prepared(
            replace(source, resource=capture(SupportSource())),
            "support",
            report_json=json.dumps(report()).encode(),
        )
    with pytest.raises(AppError, match="Sensitive"):
        prepared(source, "support", sensitive=True, report_json=json.dumps(report()).encode())
    legacy = read_artifact(json.dumps(report()).encode(), artifact_id=ID)
    assert (
        legacy.metadata.format == "legacy-report"
        and legacy.metadata.scope.namespace_mode == "unknown"
    )
    assert legacy.metadata.scope.export_at is legacy.metadata.scope.context is None
    assert b"REPORT_SENTINEL" not in legacy.payload
    assert read_artifact(legacy.payload, artifact_id=ID).payload == legacy.payload
    minimal = report()
    del minimal["failure"]
    assert (
        read_artifact(json.dumps(minimal).encode(), artifact_id=ID).metadata.format
        == "legacy-report"
    )


def test_table_conceals_by_provenance_before_preview_and_retains_safe_plain_cells():
    source = TableSource(
        columns=("Name", "Innocent", "Status"),
        rows=(("pod", "CUSTOM_SECRET_SENTINEL", "[bold]literal[/bold]"),),
        row_keys=("uid",),
        concealed_columns=frozenset({1}),
    )
    assert available_formats(capture(source)) == ("screen",)
    result = prepared(source, "screen")
    assert b"CUSTOM_SECRET_SENTINEL" not in result.payload and "[REDACTED COLUMN]" in result.preview
    assert "[bold]literal[/bold]" in result.preview
    for bad in (
        replace(source, row_keys=()),
        replace(source, rows=(("short",),)),
        replace(source, rows=source.rows * 2, row_keys=("uid", "uid")),
        replace(source, concealed_columns=frozenset({3})),
        replace(source, concealed_columns=frozenset({True})),
    ):
        with pytest.raises(AppError):
            prepared(bad, "screen")


def test_paging_complete_utf8_bounded_and_safe_preview():
    text = "\n".join(["💫" * 15000] * 6)
    result = prepared(DocumentSource(page="evidence", text=text), "screen")
    pages = [artifact_page(result, index) for index in range(2)]
    assert all(page.total == 2 and len(page.text.encode()) <= MAX_PAGE_BYTES for page in pages)
    assert "".join(page.text for page in pages) == text + "\n"
    assert len(result.preview.encode()) <= MAX_PAGE_BYTES
    for index in (-1, 2, True, 0.5):
        with pytest.raises(AppError, match="page is unavailable"):
            artifact_page(result, index)


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../file",
        "dir/file",
        "a\\b",
        "bad\nname",
        "bad\x1bname",
        "\u202ename",
        "x" * 256,
        None,
    ],
)
def test_filename_rejects_nonentry_names_and_controls(name):
    with pytest.raises(AppError, match="direct filename"):
        validate_basename(name)


def test_listing_hints_literal_filter_scope_and_invalid_prefixes():
    result = prepared(DocumentSource(page="evidence", text="text"), "screen")
    metadata = inspect_metadata(result.payload)
    assert metadata == result.metadata
    ref = ArtifactRef(
        directory=DirectoryRef(path=Path("/synthetic"), device=1, inode=2),
        name="fixture-export.txt",
        identity=FileIdentity(
            device=1, inode=3, size=10, mtime_ns=4, ctime_ns=5, mode=0o600, uid=1, nlink=1
        ),
    )
    entry = ArtifactEntry(ref=ref, metadata=metadata)
    assert validate_basename("fixture-export.txt") == "fixture-export.txt"
    assert all(
        matches_entry(entry, query) for query in ("", "FIXTURE", "synthetic", "screen", "header")
    )
    assert not matches_entry(entry, ".*")
    assert matches_entry(
        ArtifactEntry(ref=ref, metadata=None, problem="Unavailable"), "unavailable"
    )
    for value in (
        b"plain",
        b"\xff",
        b"# kuberich-export: {}\n",
        result.payload.splitlines()[0],
        b"x" * (MAX_METADATA_BYTES + 100) + b"\n",
    ):
        assert inspect_metadata(value) is None


@pytest.mark.parametrize(
    "body",
    [
        "kind: Secret\ndata:\n  ordinary: FORGED_SENTINEL\n",
        "kind: List\nitems:\n- kind: ConfigMap\n  data:\n    ordinary: FORGED_SENTINEL\n",
    ],
)
def test_forged_redaction_labels_cannot_reveal_nested_yaml_in_screen_or_resource(body):
    for kind in ("screen", "resource-yaml"):
        raw = metadata_for(kind)
        raw["sensitive"] = False
        value = read_artifact(envelope(raw, body), artifact_id=ID)
        assert b"FORGED_SENTINEL" not in value.payload
        assert not value.metadata.sensitive


@pytest.mark.parametrize(
    "body",
    [
        "kind: Pod\nkind: Secret\ndata: value\n",
        "kind: [",
        "&anchor {kind: Secret}",
        "a: &one [x]\nb: *one",
        "!!python/object:builtins.str {}",
        "!!str text",
        "{1: value}",
        "{yes: value}",
        "{a: .nan}",
        "{a: .inf}",
        "{a: 2026-01-01}",
        "---\nkind: Pod\n---\nkind: Secret\n",
        "plain text",
        "[one, two]",
        "kind: " + "[" * 65 + "0" + "]" * 65,
        "kind: Pod\nlong: " + "x" * 65537,
    ],
)
def test_resource_yaml_rejects_duplicate_keys_tags_aliases_nonscalars_and_limits(body):
    with pytest.raises(AppError):
        read_artifact(envelope(metadata_for("resource-yaml"), body), artifact_id=ID)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\xff",
        b"{}",
        b"not an artifact",
        b'{"schema_version":1,"schema_version":1}',
        b'{"number":NaN}',
        b'{"number":Infinity}',
        b'{"number":-Infinity}',
        b'{"number":1e9999}',
        b'{"text":"\\ud800"}',
        b"[" * 1100 + b"0" + b"]" * 1100,
        b"[" * 66 + b"0" + b"]" * 66,
        b"x" * (MAX_ARTIFACT_BYTES + 1),
    ],
)
def test_invalid_full_documents_have_fixed_failure_without_payload_disclosure(payload):
    with pytest.raises(AppError) as failure:
        read_artifact(payload, artifact_id=ID)
    assert "Invalid" in str(failure.value)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), 2),
        (("schema_version",), True),
        (("format",), "future"),
        (("format",), []),
        (("sensitive",), "false"),
        (("scope",), None),
        (("scope", "namespace_mode"), "future"),
        (("scope", "namespace_mode"), []),
        (("scope", "context"), 2),
        (("scope", "export_at"), 4),
        (("scope", "export_at"), "yesterday"),
        (("scope", "export_at"), "2026-11-05T00:00:00"),
        (("presentation", "view"), 7),
        (("presentation", "descending"), "yes"),
        (("presentation", "viewport", "index"), 0.1),
        (("presentation", "viewport", "x"), "1"),
        (("notices",), "none"),
        (("notices",), [3]),
        (("scope", "name"), "x" * 65537),
    ],
)
def test_untrusted_metadata_shape_types_version_and_times_are_validated(path, value):
    raw = metadata_for()
    target = raw
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    encoded = envelope(raw, "safe")
    assert inspect_metadata(encoded) is None
    with pytest.raises(AppError):
        read_artifact(encoded, artifact_id=ID)


def test_metadata_extra_fields_controls_normalization_optional_values_and_size_bound():
    raw = metadata_for()
    raw["path"] = "../../outside"
    with pytest.raises(AppError):
        read_artifact(envelope(raw, "safe"), artifact_id=ID)
    raw = metadata_for()
    raw["scope"]["context"] = "Bearer METADATA_SENTINEL\x1b[31m"
    raw["scope"]["source_at"] = None
    raw["scope"]["export_at"] = "2026-11-05T08:30:00-04:00"
    raw["presentation"] = None
    value = read_artifact(envelope(raw, "safe"), artifact_id=ID)
    assert (
        "METADATA_SENTINEL" not in value.metadata.scope.context
        and "\x1b" not in value.metadata.scope.context
    )
    assert value.metadata.scope.export_at == AT and value.metadata.scope.source_at is None
    assert value.metadata.presentation is None
    base = capture(DocumentSource(page="evidence", text="safe"), presentation=None)
    for scope in (
        replace(SCOPE, export_at=AT.replace(tzinfo=None)),
        replace(SCOPE, namespace_mode="future"),
    ):
        with pytest.raises(AppError):
            prepare_capture(replace(base, scope=scope), "screen", artifact_id=ID)
    with pytest.raises(AppError, match="metadata exceeds 8 KiB"):
        prepare_capture(
            replace(base, scope=replace(SCOPE, context="x" * 9000)), "screen", artifact_id=ID
        )
    over = metadata_for()
    over["scope"]["context"] = "x" * 9000
    assert inspect_metadata(envelope(over, "safe")) is None
    # A valid full JSON artifact cannot smuggle a different format behind the listing prefix.
    raw = metadata_for("diagnostics")
    payload = envelope(raw, {})
    assert inspect_metadata(payload) is not None
    with pytest.raises(AppError):
        read_artifact(payload, artifact_id=ID)
    raw["format"] = "screen"
    json_header = (JSON_PREFIX + json.dumps(raw) + ',\n"payload":"safe"}\n').encode()
    with pytest.raises(AppError):
        read_artifact(json_header, artifact_id=ID)
    raw["format"] = "diagnostics"
    text_header = (TEXT_PREFIX + json.dumps(raw) + "\n{}\n").encode()
    with pytest.raises(AppError):
        read_artifact(text_header, artifact_id=ID)


@pytest.mark.parametrize(
    "viewport",
    [
        Viewport(None, 0, float("nan"), 0, None),
        Viewport(None, 0, 0, float("inf"), None),
        Viewport(None, True, 0, 0, None),
    ],
)
def test_nonfinite_and_malformed_live_viewports_are_refused(viewport):
    source = DocumentSource(page="evidence", text="safe")
    with pytest.raises(AppError):
        prepare_capture(
            capture(source, presentation=replace(PRESENTATION, viewport=viewport)),
            "screen",
            artifact_id=ID,
        )


def test_metadata_without_viewport_and_explicit_unknown_scope_roundtrip():
    result = prepare_capture(
        capture(
            DocumentSource(page="evidence", text="safe"),
            presentation=replace(PRESENTATION, viewport=None),
        ),
        "screen",
        artifact_id=ID,
    )
    assert read_artifact(result.payload, artifact_id=ID).metadata.presentation.viewport is None
    metadata = metadata_for()
    metadata["notices"] = []
    assert read_artifact(envelope(metadata, "safe"), artifact_id=ID).metadata.notices == ()


@pytest.mark.parametrize(
    "override",
    [{"head_lines": 0}, {"head_lines": True}, {"dropped_lines": -1}, {"dropped_lines": False}],
)
def test_live_log_retention_qualification_requires_bounded_integers(override):
    with pytest.raises(AppError):
        prepared(replace(single_source(), **override), "logs")


def test_complete_records_private_key_state_and_structured_scalars_are_redacted_without_tail_loss():
    text = "\n".join(
        [
            "[not JSON] literal",
            '{"value":1.25,"more":[true,null,false]}',
            '{"source":{"uid":"pod"},"payload":"-----BEGIN PRIVATE KEY-----"}',
            '{"source":{"uid":"pod"},"payload":"JSON_KEY_SENTINEL"}',
            '{"source":{"uid":"pod"},"payload":"-----END PRIVATE KEY-----"}',
            '{"line":"-----BEGIN PRIVATE KEY-----"}',
            '{"broken": "MALFORMED_KEY_SENTINEL"',
            '{"line":"-----END PRIVATE KEY-----"}',
            "after keys",
        ]
    )
    result = prepared(DocumentSource(page="evidence", text=text), "screen")
    assert (
        b"JSON_KEY_SENTINEL" not in result.payload
        and b"MALFORMED_KEY_SENTINEL" not in result.payload
    )
    assert '"source":{"uid":"pod"},"payload":"[REDACTED KEY]"' in result.preview
    assert "[not JSON] literal" in result.preview and b"after keys" in result.payload
    assert '"value":1.25' in result.preview


def test_full_resource_and_field_output_limits_fail_without_truncation():
    source = resource_source()
    with pytest.raises(AppError, match="full captured resource"):
        prepared(
            replace(source, record=replace(source.record, metadata_only=True)), "resource-yaml"
        )
    for document in ("[]", "- string"):
        with pytest.raises(AppError):
            prepared(DocumentSource(page="yaml", text=document), "resource-yaml")
    with pytest.raises(AppError):
        prepared(DocumentSource(page="evidence", text="x" * 65537), "screen")
    with pytest.raises(AppError, match=r"16 MiB.*not truncated"):
        prepared(DocumentSource(page="evidence", text=("x" * 65536 + "\n") * 257), "screen")
    # Count bound is independent of the encoded byte limit and nesting depth.
    with pytest.raises(AppError):
        read_artifact(("[" + ",".join(["null"] * 250001) + "]").encode(), artifact_id=ID)
    with pytest.raises(AppError):
        prepared(
            DocumentSource(page="yaml", text="values: [" + ",".join(["0"] * 250001) + "]"),
            "resource-yaml",
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(schema_version=2),
        lambda value: value.update(kubeconfig="REPORT_EXTRA_SENTINEL"),
        lambda value: value.update(terminal=[]),
        lambda value: value["terminal"].update(environment="REPORT_EXTRA_SENTINEL"),
        lambda value: value.update(recent_log=[]),
        lambda value: value["recent_log"].update(path="REPORT_EXTRA_SENTINEL"),
        lambda value: value.update(failure={"kind": "Error", "frames": "bad"}),
        lambda value: value["failure"]["frames"][0].update(locals="REPORT_EXTRA_SENTINEL"),
    ],
)
def test_legacy_reports_use_explicit_allowlist(mutate):
    value = report()
    mutate(value)
    with pytest.raises(AppError):
        read_artifact(json.dumps(value).encode(), artifact_id=ID)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("request", "scope", "session"), "INTERNAL_SESSION"),
        (("findings",), {}),
        (("findings", 0, "evidence"), "bad"),
        (("findings", 0, "subject", "uid"), 1),
        (("findings", 0, "subject", "resource"), {}),
        (("findings", 0, "log_modes"), 1),
        (("sources", 0, "collection", "pages"), -1),
        (("sources", 0, "omitted_findings"), -1),
        (("native_requests_used",), -1),
        (("collecting",), "true"),
        (("sources",), {}),
        (("findings", 0, "evidence", 0, "historical"), 0),
    ],
)
def test_diagnostic_files_reject_internal_or_malformed_facts(path, value):
    original = prepared(DiagnosticsSource(snapshot=snapshot()), "diagnostics")
    data = json.loads(original.payload)
    target = data["payload"]
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(AppError):
        read_artifact(envelope(data["kuberich_export"], data["payload"]), artifact_id=ID)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tag",), "unknown"),
        (("generation",), 1),
        (("retained_only",), False),
        (("source_filter",), ["one"]),
        (("selected_sources",), "one"),
        (("source_statuses", 0, "source", "start_token"), "NEVER_PERSIST"),
        (("source_statuses",), {}),
        (("excess",), -1),
    ],
)
def test_log_provenance_rejects_unowned_fields_or_invalid_shapes(path, value):
    original = prepared(aggregate_source(), "logs")
    _, _, body = original.payload.decode().partition("\n")
    line, _, records = body.partition("\n")
    prefix, _, descriptor = line.partition(": ")
    data = json.loads(descriptor)
    target = data
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(AppError):
        read_artifact(
            envelope(metadata_for("logs"), prefix + ": " + json.dumps(data) + "\n" + records),
            artifact_id=ID,
        )


@pytest.mark.parametrize(
    "body", ["plain logs", "# kuberich-log-source: []\ntext", "# kuberich-log-source: {}\ntext"]
)
def test_log_payload_requires_valid_provenance(body):
    with pytest.raises(AppError):
        read_artifact(envelope(metadata_for("logs"), body), artifact_id=ID)


def test_support_large_retained_logs_and_hostile_role_payloads_stay_redacted():
    logs = capture(
        single_source(text=["retained " + "x" * 100 for _ in range(800)] + ["last line"])
    )
    output = prepared(
        SupportSource(logs=logs), "support", report_json=json.dumps(report()).encode()
    )
    assert b"last line" in read_artifact(output.payload, artifact_id=ID).payload
    full = prepared(
        SupportSource(resource=capture(resource_source()), logs=capture(single_source())),
        "support",
        report_json=json.dumps(report()).encode(),
    )
    for path, value in [
        (("omissions",), [1]),
        (("resource", "payload"), "raw"),
        (("logs", "payload", "records"), [1]),
        (("logs", "payload", "provenance"), []),
        (("resource", "notices"), "none"),
    ]:
        data = json.loads(full.payload)
        target = data["payload"]
        for name in path[:-1]:
            target = target[name]
        target[path[-1]] = value
        with pytest.raises(AppError):
            read_artifact(envelope(data["kuberich_export"], data["payload"]), artifact_id=ID)


def test_malformed_producer_facts_are_rejected_before_encoding():
    original = snapshot()
    source = original.sources[0]
    invalid_resource = replace(source.resource, group={1: "unexpected key"})
    malformed = replace(original, sources=(replace(source, resource=invalid_resource),))
    with pytest.raises(AppError):
        prepared(DiagnosticsSource(snapshot=malformed), "diagnostics")
    huge_coordinate = Viewport(None, 10**5000, 0, 0, None)
    with pytest.raises(AppError):
        prepare_capture(
            capture(
                DocumentSource(page="evidence", text="safe"),
                presentation=replace(PRESENTATION, viewport=huge_coordinate),
            ),
            "screen",
            artifact_id=ID,
        )
    unresolved = replace(original.findings[0], subject=None)
    result = prepared(
        DiagnosticsSource(snapshot=replace(original, findings=(unresolved,))), "diagnostics"
    )
    assert (
        json.loads(read_artifact(result.payload, artifact_id=ID).payload)["payload"]["findings"][0][
            "subject"
        ]
        is None
    )


def test_alias_events_oversized_raw_metadata_and_trailing_partial_utf8():
    with pytest.raises(AppError):
        read_artifact(envelope(metadata_for("resource-yaml"), "alias: *undefined"), artifact_id=ID)
    assert inspect_metadata(b"unknown header\ntext") is None
    assert inspect_metadata((TEXT_PREFIX + " " * (MAX_METADATA_BYTES + 1) + "\n").encode()) is None
    output = prepared(DocumentSource(page="evidence", text="💫"), "screen")
    header = output.payload.partition(b"\n")[0] + b"\n"
    assert inspect_metadata(header + b"\xf0\x9f") == output.metadata
    with pytest.raises(AppError):
        read_artifact(envelope(metadata_for("support"), []), artifact_id=ID)
    assert (
        b"OPAQUE_SENTINEL"
        not in read_artifact(
            envelope(metadata_for("resource-yaml"), "kind: Secret\ndata: OPAQUE_SENTINEL"),
            artifact_id=ID,
        ).payload
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("version",), {}),
        (("config_check",), "unknown"),
        (("terminal",), {}),
        (("terminal", "stdin_tty"), 1),
        (("terminal", "columns"), 0),
        (("terminal", "rows"), True),
        (("recent_log", "status"), "unknown"),
        (("recent_log", "text"), None),
        (("failure", "kind"), {}),
        (("failure", "frames"), []),
        (("failure", "frames", 0, "line"), 0),
        (("failure", "frames", 0, "line"), True),
        (("failure", "frames", 0, "file"), "outside/private.py"),
        (("failure", "frames", 0, "function"), None),
    ],
)
def test_legacy_report_known_fields_require_their_actual_scalar_types(path, value):
    # Empty frame lists are valid reports from exceptions without an active traceback.
    data = report()
    target = data
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    if path == ("failure", "frames"):
        assert (
            read_artifact(json.dumps(data).encode(), artifact_id=ID).metadata.format
            == "legacy-report"
        )
    else:
        with pytest.raises(AppError):
            read_artifact(json.dumps(data).encode(), artifact_id=ID)


def test_legacy_unavailable_log_minimal_terminal_and_frame_count_bound():
    data = report()
    data["terminal"] = {"stdin_tty": False, "stdout_tty": False}
    data["recent_log"] = {"status": "unavailable"}
    result = read_artifact(json.dumps(data).encode(), artifact_id=ID)
    assert json.loads(result.payload)["payload"]["recent_log"] == {"status": "unavailable"}
    data["recent_log"]["text"] = "NOT_A_RETAINED_LOG"
    with pytest.raises(AppError):
        read_artifact(json.dumps(data).encode(), artifact_id=ID)
    data["recent_log"] = {"status": "unavailable"}
    data["failure"]["frames"] *= 33
    with pytest.raises(AppError):
        read_artifact(json.dumps(data).encode(), artifact_id=ID)


def test_document_page_provenance_and_exact_encoded_header_budget():
    for page in ("yaml", "managed-yaml", "details", "events", "evidence"):
        text = "kind: Pod" if "yaml" in page else "safe text"
        output = prepared(DocumentSource(page=page, text=text), "screen")
        assert f"Captured document page: {page}." in output.metadata.notices
        assert (
            read_artifact(output.payload, artifact_id=ID).metadata.notices
            == output.metadata.notices
        )
    source = capture(DocumentSource(page="evidence", text="safe"), presentation=None)
    sample = prepare_capture(source, "screen", artifact_id=ID)
    header_size = len(sample.payload.partition(b"\n")[0]) + 1
    extra = MAX_METADATA_BYTES - header_size
    boundary = replace(source, scope=replace(SCOPE, context=SCOPE.context + "x" * extra))
    output = prepare_capture(boundary, "screen", artifact_id=ID)
    assert len(output.payload.partition(b"\n")[0]) + 1 == MAX_METADATA_BYTES
    assert inspect_metadata(output.payload[: MAX_METADATA_BYTES + 1]) == output.metadata
    with pytest.raises(AppError, match="metadata exceeds 8 KiB"):
        prepare_capture(
            replace(boundary, scope=replace(boundary.scope, context=boundary.scope.context + "x")),
            "screen",
            artifact_id=ID,
        )


@pytest.mark.parametrize(
    "line",
    [
        '{"kind":"Pod","kind":"Secret","data":{"normal":"DUPLICATE_LOG_SENTINEL"}}',
        '[{"kind":"Secret","data":{"normal":"DUPLICATE_LOG_SENTINEL","normal":"other"}}]',
        '{"field":NaN}',
        '{"broken":',
        '[null,{"field":NaN}]',
    ],
)
def test_json_log_parse_failures_cannot_bypass_structured_redaction(line):
    with pytest.raises(AppError):
        prepared(single_source(text=[line]), "logs")
    source = prepared(single_source(text=["safe line"]), "logs")
    raw = source.payload + line.encode() + b"\n"
    with pytest.raises(AppError):
        read_artifact(raw, artifact_id=ID)


def test_timestamped_single_and_plain_aggregate_json_recheck_nested_kinds():
    structured = '{"kind":"Secret","data":{"normal":"TIMESTAMP_JSON_SENTINEL"}}'
    single = prepared(single_source(text=["2026-11-05T12:29:50Z " + structured]), "logs")
    assert b"TIMESTAMP_JSON_SENTINEL" not in single.payload
    assert b"2026-11-05T12:29:50Z" in single.payload
    source = aggregate_source()
    record = replace(source.records[0], payload=structured, structured=structured)
    aggregate = prepared(replace(source, records=(record,), show_timestamps=True), "screen")
    assert b"TIMESTAMP_JSON_SENTINEL" not in aggregate.payload
    assert "[s1 fixture/pod:app uid=pod-uid] 2026-11-05T12:29:50Z" in aggregate.preview
    forged = envelope(
        metadata_for("logs"),
        single.payload.decode().partition("\n")[2] + "\n2026-11-05T12:30:00Z " + structured,
    )
    assert b"TIMESTAMP_JSON_SENTINEL" not in read_artifact(forged, artifact_id=ID).payload
