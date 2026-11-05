"""Pinned writer goldens, strict scope, retained prefixes and hostile source text."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kuberich.domain.cluster_diagnostics import (
    DiagnosticIdentity,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSeverity,
    DiagnosticStatus,
    diagnostic_text_bytes,
)
from kuberich.domain.popeye import parse_popeye_report, parse_popeye_version
from kuberich.domain.resources import ApiResource, Discovery
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError

NOW = datetime(2026, 11, 5, 10, 1, tzinfo=UTC)
REQUEST = DiagnosticRequest(DiagnosticScope(SessionIdentity("owned-preview", 1), "team"), 1)
PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get"}))
DEPLOYMENTS = ApiResource("apps", "v1", "deployments", "Deployment", True, frozenset({"get"}))
NODES = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get"}))
DISCOVERY = Discovery((PODS, DEPLOYMENTS, NODES))
FIXTURES = Path(__file__).parents[1] / "fixtures/popeye/0.22.1"


def document():
    return {
        "popeye": {
            "report_time": "2026-11-05T10:00:00Z",
            "score": 75,
            "grade": "B",
            "sections": [
                {
                    "linter": "pods",
                    "gvr": "v1/pods",
                    "tally": {"ok": 0, "info": 0, "warning": 1, "error": 0, "score": 75},
                    "issues": {
                        "team/worker": [
                            {
                                "group": "main",
                                "gvr": "containers",
                                "level": 2,
                                "message": "[POP-123] Synthetic warning",
                            }
                        ]
                    },
                }
            ],
        },
        "ClusterName": "kuberich-session",
        "ContextName": "owned-preview",
    }


def parse(value=None, **options):
    data = json.dumps(document() if value is None else value).encode()
    return raw(data, **options)


def raw(data, **options):
    return parse_popeye_report(
        data,
        **{
            "producer_version": "0.22.1",
            "request": REQUEST,
            "discovery": DISCOVERY,
            "observed_at": NOW,
            **options,
        },
    )


def test_pinned_synthetic_golden_preserves_error_order_levels_and_subissue_identity():
    metadata = json.loads((FIXTURES / "metadata.json").read_text())
    assert metadata["producer_commit"] == "35b554961dcdabfa7aba6bd070673c6c24c70884"
    assert (
        metadata["fixture_sha256"]["synthetic-current.json"]
        == hashlib.sha256((FIXTURES / "synthetic-current.json").read_bytes()).hexdigest()
    )
    assert "not actual upstream" in metadata["fixtures"]["synthetic-current.json"]
    result = raw((FIXTURES / "synthetic-current.json").read_bytes())
    assert result.format_version == 1 and result.parser_id == "popeye-json/0.22.1"
    assert result.producer_version == "0.22.1" and result.score == 75 and result.grade == "B"
    assert [row.severity for row in result.findings] == [
        *DiagnosticSeverity,
        DiagnosticSeverity.ERROR,
    ]
    assert len({row.key for row in result.findings}) == 5
    row = result.findings[2]
    assert row.container == "main" and row.subject.resource == PODS and row.subject.uid is None
    assert row.identity is DiagnosticIdentity.NAME_ONLY and row.source_code == "POP-3"
    assert (
        not row.log_modes
        and "level=2" in row.explanation
        and "issue gvr=containers" in row.explanation
    )
    errors = [source for source in result.sources if source.key.startswith("popeye:error:")]
    assert [source.detail for source in errors] == [
        "Synthetic first source unavailable",
        "Synthetic second source forbidden (403)",
    ]
    assert errors[1].status is DiagnosticStatus.FORBIDDEN
    assert result.sources[0].status is DiagnosticStatus.PARTIAL
    assert row.evidence[0].reported_at == datetime(2026, 11, 5, 10, tzinfo=UTC)


def test_additions_empty_reports_and_stable_keys_preserve_pinned_semantics():
    value = document()
    value["extra"] = {"nested": [True, None, 0.5]}
    value["popeye"]["sections"][0]["issues"]["team/worker"][0]["extra"] = {"ignored": "safe"}
    assert parse(value).findings[0].key == parse().findings[0].key
    assert (
        parse(request=replace(REQUEST, revision=2), observed_at=NOW.replace(minute=2))
        .findings[0]
        .key
        == parse().findings[0].key
    )
    del value["popeye"]["sections"]
    assert parse(value).findings == () and parse(value).sources[0].status is DiagnosticStatus.READY
    value["popeye"]["sections"] = []
    assert not parse(value).findings


@pytest.mark.parametrize(
    "gvr,fqn,identity,namespace",
    [
        ("v1/nodes", "-/node-one", DiagnosticIdentity.NAME_ONLY, None),
        ("v1/nodes", "node-one", DiagnosticIdentity.NAME_ONLY, None),
        ("example.test/v1/widgets", "team/object", DiagnosticIdentity.UNRESOLVED, "team"),
        ("v1/unknowns", "-/object", DiagnosticIdentity.UNRESOLVED, None),
    ],
)
def test_served_gvr_cluster_scope_and_unknown_api_are_never_guessed(gvr, fqn, identity, namespace):
    value = document()
    section = value["popeye"]["sections"][0]
    section["gvr"], section["issues"] = (
        gvr,
        {fqn: [{"group": "__root__", "gvr": gvr, "level": 0, "message": "Synthetic observation"}]},
    )
    row = parse(value).findings[0]
    assert row.identity is identity and row.subject.namespace == namespace and row.container is None
    assert row.source_code is None


@pytest.mark.parametrize("fqn", ["Version", "team/synthetic"])
def test_pinned_non_api_cluster_section_is_visible_without_a_fake_resource(fqn):
    value = document()
    section = value["popeye"]["sections"][0]
    section["gvr"] = "cluster"
    section["issues"] = {
        fqn: [
            {
                "group": "__root__",
                "gvr": "cluster",
                "level": 1,
                "message": "[POP-406] Synthetic version observation",
            }
        ]
    }
    row = parse(value).findings[0]
    assert (
        row.subject is None and not row.evidence and row.identity is DiagnosticIdentity.UNRESOLVED
    )
    assert "report_time=" in row.explanation and "FQN=" + fqn in row.explanation
    assert parse(value).sources[0].status is DiagnosticStatus.PARTIAL


@pytest.mark.parametrize(
    "gvr,fqn",
    [
        ("v1/pods", "other/worker"),
        ("v1/pods", "worker"),
        ("v1/pods", "-/worker"),
        ("v1/nodes", "team/node"),
        ("v1/unknowns", "bare"),
        ("v1/pods", "team/a/b"),
        ("v1/pods", "team/.."),
        ("v1/pods", "team/-option"),
        ("v1/pods", "team/a b"),
        ("v1/pods", "Team/worker"),
        ("v1/pods", "team/" + "x" * 254),
        ("too/many/path/parts", "team/worker"),
        ("BAD/v1/pods", "team/worker"),
    ],
)
def test_scope_and_object_identifiers_fail_closed(gvr, fqn):
    value = document()
    section = value["popeye"]["sections"][0]
    section["gvr"], section["issues"] = gvr, {fqn: section["issues"]["team/worker"]}
    with pytest.raises(AppError):
        parse(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("level", True),
        ("level", -1),
        ("level", 4),
        ("level", 2.0),
        ("group", None),
        ("gvr", []),
        ("message", {}),
        ("group", "-not-container"),
    ],
)
def test_invalid_issue_fields_are_rejected_even_after_prefix_limit(field, value):
    doc = document()
    doc["popeye"]["sections"][0]["issues"]["team/worker"][0][field] = value
    with pytest.raises(AppError):
        parse(doc, max_findings=0)


@pytest.mark.parametrize(
    "path,value",
    [
        (("ContextName",), "other"),
        (("ClusterName",), "ambient"),
        (("ContextName",), None),
        (("popeye",), []),
        (("popeye", "score"), True),
        (("popeye", "grade"), 5),
        (("popeye", "report_time"), "invalid"),
        (("popeye", "report_time"), "2026-11-05T10:00:00"),
        (("popeye", "report_time"), "2026-99-05T10:00:00Z"),
        (("popeye", "grade"), "x" * 65),
        (("popeye", "sections"), {}),
        (("popeye", "sections"), [None]),
        (("popeye", "errors"), []),
        (("popeye", "errors"), {"different": "error"}),
        (("popeye", "errors"), {"error": 4}),
        (("popeye", "sanitizers"), []),
        (("popeye", "schemaVersion"), 1),
        (("schemaVersion",), 1),
    ],
)
def test_invalid_current_or_stale_schema_is_not_silently_accepted(path, value):
    doc = document()
    target = doc
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(AppError):
        parse(doc)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff",
        b"{} trailing",
        b'{"popeye":',
        b"[]",
        b"NaN",
        b"1e999",
        b"[" * 1100 + b"]" * 1100,
        b" " * (8 * 1024 * 1024 + 1),
        b'{"extra":1,"extra":2}',
        b'{"popeye":{"errors":{"other":1,"other":2}}}',
    ],
)
def test_complete_finite_utf8_json_and_duplicate_rules_are_strict(data):
    with pytest.raises(AppError):
        raw(data)


def test_ignored_additions_still_obey_depth_node_and_string_bounds():
    for extra in ([[]] * 200001, "x" * 65537, {"x" * 65537: None}):
        value = document()
        value["extra"] = extra
        with pytest.raises(AppError):
            parse(value)
    extra = 0
    for _ in range(34):
        extra = [extra]
    value["extra"] = extra
    with pytest.raises(AppError):
        parse(value)


def test_redaction_controls_and_truncation_precede_published_retention():
    value = document()
    issue = value["popeye"]["sections"][0]["issues"]["team/worker"][0]
    issue["message"] = (
        "password="
        + "synthetic-credential" * 800
        + " [red] \x1b]8;;https://example.invalid\x07link\ud800"
    )
    result = parse(value)
    row = result.findings[0]
    assert "synthetic-credential" not in repr(result) and "[REDACTED]" in row.summary
    assert "\x1b" not in repr(result) and "\\u001b" in row.summary and "\\ud800" in row.summary
    issue["message"] = "界" * 10000
    row = parse(value).findings[0]
    assert len(row.summary.encode()) <= 4096 and row.summary.endswith("[truncated]")


def test_prefix_limits_count_every_retained_occurrence_and_empty_budget_discloses_omission():
    value = document()
    issues = value["popeye"]["sections"][0]["issues"]["team/worker"]
    issues *= 3
    one = parse(value, max_findings=1)
    assert len(one.findings) == 1 and one.omitted_findings == 2
    size = diagnostic_text_bytes(one.findings)
    assert len(parse(value, max_text_bytes=size).findings) == 1
    empty = parse(value, max_text_bytes=0)
    assert not empty.findings and empty.omitted_findings == 3
    assert (
        empty.sources[0].status is DiagnosticStatus.PARTIAL
        and empty.sources[0].omitted_findings == 3
    )
    assert diagnostic_text_bytes(empty.sources) <= 16384
    no_sources = parse(max_source_text_bytes=0)
    assert not no_sources.sources and no_sources.omitted_source_notices > 0


def test_section_issue_and_repeated_error_limits_disclose_partial_prefix():
    value = document()
    value["popeye"]["sections"] *= 65
    assert parse(value).omitted_findings == 1
    value = document()
    value["popeye"]["sections"][0]["issues"]["team/worker"] *= 10001
    result = parse(value)
    assert len(result.findings) <= 1000 and result.omitted_findings == 10001 - len(result.findings)
    encoded = (
        json.dumps(document())
        .replace(
            '"grade": "B"',
            '"grade": "B", "errors": {'
            + ",".join('"error":"Synthetic error"' for _ in range(257))
            + "}",
        )
        .encode()
    )
    result = raw(encoded)
    assert (
        result.omitted_source_notices > 0 and result.sources[0].status is DiagnosticStatus.PARTIAL
    )
    assert diagnostic_text_bytes(result.sources) <= 16384


@pytest.mark.parametrize(
    "options",
    [
        {"producer_version": "0.22.0"},
        {"max_findings": True},
        {"max_findings": 1001},
        {"max_text_bytes": -1},
        {"max_text_bytes": True},
        {"max_text_bytes": 2097152},
        {"max_source_text_bytes": True},
        {"max_source_text_bytes": 16385},
        {"observed_at": NOW.replace(tzinfo=None)},
    ],
)
def test_producer_and_remaining_budget_validation(options):
    with pytest.raises(AppError):
        parse(**options)


@pytest.mark.parametrize(
    "data",
    [
        b"Version: 0.22.1\n",
        b"Version: v0.22.1\n",
        b"\x1b[38;5;122mVersion:  \x1b[0m \x1b[38;5;15m0.22.1\x1b[0m\n",
    ],
)
def test_pinned_version_command_output(data):
    assert parse_popeye_version(data) == "0.22.1"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x" * 16385,
        b"\xff",
        b"Version: 0.22.0\n",
        b"Version: 0.22.1\nVersion: 0.22.1\n",
        b"version: 0.22.1\n",
        b"Version: dev\nVersion: 0.22.1\n",
        b"\x1b]8;;evil\x07Version: 0.22.1\n",
        b"\x1b[31mVersion: 0.22.1\n",
        b"Version: 0.22.1\r\n",
    ],
)
def test_unknown_or_malformed_versions_and_controls_are_rejected(data):
    with pytest.raises(AppError):
        parse_popeye_version(data)
