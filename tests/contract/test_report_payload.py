"""The shared safe report builder preserves writer privacy and output semantics."""

import json

from kuberich.diagnostics.logging import LOG_HEADER
from kuberich.diagnostics.reports import report_payload, write_report


def test_payload_excludes_error_values_paths_and_config_body(tmp_path):
    secret = "DO-NOT-EXPORT-THIS-CREDENTIAL"
    path = tmp_path / "owned.log"
    path.write_bytes(LOG_HEADER + b"INFO retained record\n")
    try:
        raise RuntimeError(secret)
    except RuntimeError as error:
        payload = report_payload(config_status="valid", log_path=path, error=error)
    report = json.loads(payload)
    assert report["schema_version"] == 1 and report["config_check"] == "valid"
    assert report["failure"]["kind"] == "RuntimeError"
    assert report["failure"]["frames"][-1]["file"] == "test_report_payload.py"
    assert report["recent_log"]["status"] == "included"
    assert "retained record" in report["recent_log"]["text"]
    assert secret.encode() not in payload and str(tmp_path).encode() not in payload
    assert payload.endswith(b"\n")


def test_writer_uses_shared_payload_without_recollecting(tmp_path, monkeypatch):
    from kuberich.diagnostics import reports

    seen = []

    def build(**kwargs):
        seen.append(kwargs)
        return b'{"safe":"shared payload"}\n'

    monkeypatch.setattr(reports, "report_payload", build)
    destination = tmp_path / "report.json"
    assert write_report(config_status="missing", output=destination) == destination
    assert destination.read_bytes() == b'{"safe":"shared payload"}\n'
    assert seen == [{"config_status": "missing", "log_path": None, "error": None}]
