"""Byte-preserved official Popeye output from the owned synthetic kind trial."""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from kuberich.domain.cluster_diagnostics import (
    DiagnosticCategory,
    DiagnosticIdentity,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSourceKind,
    DiagnosticStatus,
)
from kuberich.domain.popeye import parse_popeye_report
from kuberich.domain.resources import ApiResource, Discovery
from kuberich.domain.targets import SessionIdentity
from scripts.diagnostics_tools import tool_provenance


def test_actual_pinned_report_preserves_scope_severity_code_and_name_only_identity():
    directory = Path(__file__).parents[1] / "fixtures/popeye/0.22.1"
    metadata = json.loads((directory / "actual-owned-pods.metadata.json").read_text())
    data = (directory / metadata["fixture"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
    assert metadata["provenance"] == tool_provenance()
    assert "Actual official binary output" in metadata["capture"] and metadata["returncode"] == 1
    request = DiagnosticRequest(
        DiagnosticScope(SessionIdentity(metadata["context"], 1), metadata["namespace"]), 1
    )
    pods = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}))
    reported = datetime.fromisoformat(metadata["report_time"])
    report = parse_popeye_report(
        data,
        producer_version="0.22.1",
        request=request,
        discovery=Discovery((pods,)),
        observed_at=reported + timedelta(seconds=1),
    )
    assert len(report.findings) == metadata["normalized_findings"] == 87
    assert report.report_time == reported and report.parser_id == "popeye-json/0.22.1"
    assert report.sources[0].status is DiagnosticStatus.READY
    assert {row.subject.name for row in report.findings if row.subject is not None} >= {
        "owned-image",
        "owned-scheduling",
        "owned-crash",
        "owned-readiness",
        "owned-volume",
    }
    for row in report.findings:
        assert row.subject is not None and row.subject.namespace == metadata["namespace"]
        assert row.subject.resource == pods and row.subject.uid is None
        assert (
            row.identity is DiagnosticIdentity.NAME_ONLY
            and row.category is DiagnosticCategory.OTHER
        )
        assert row.source is DiagnosticSourceKind.POPEYE and row.tool_version == "0.22.1"
        assert row.source_code is not None and row.source_code.startswith("POP-")
        assert not row.log_modes and row.evidence[0].reported_at == reported
    raw = json.loads(data)
    assert set(raw) == {"popeye", "ClusterName", "ContextName"}
    assert not {"schemaVersion", "uid", "resourceVersion"}.intersection(raw["popeye"])


def test_actual_report_obeys_the_same_remaining_publication_budget():
    directory = Path(__file__).parents[1] / "fixtures/popeye/0.22.1"
    metadata = json.loads((directory / "actual-owned-pods.metadata.json").read_text())
    request = DiagnosticRequest(
        DiagnosticScope(SessionIdentity(metadata["context"], 1), metadata["namespace"]), 1
    )
    report = parse_popeye_report(
        (directory / metadata["fixture"]).read_bytes(),
        producer_version="0.22.1",
        request=request,
        discovery=Discovery(()),
        observed_at=datetime.fromisoformat(metadata["report_time"]),
        max_findings=0,
        max_text_bytes=0,
    )
    assert not report.findings and report.omitted_findings == 87
    assert (
        report.sources[0].status is DiagnosticStatus.PARTIAL
        and report.sources[0].omitted_findings == 87
    )
