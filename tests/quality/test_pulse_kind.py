"""Owned Pulse verifier fixtures, source receipts and failure cleanup reporting."""

import json
import sys
from contextlib import contextmanager

import pytest
import yaml
from aiohttp import web

from kuberich.domain.history import HistoryBackend, HistorySnapshot
from scripts import verify_pulse_kind as verification
from scripts.owned_kind import SHELL_IMAGE, OwnedCluster
from tests.support.pulse import pulse_object, pulse_record, pulse_roots
from tests.support.resources import collection, reader_fixture


def test_owned_fixtures_pin_images_and_keep_pending_and_terminal_budgets_explicit():
    manifests = verification.fixture_manifests()
    by_name = {value["metadata"]["name"]: value for value in manifests}
    healthy = by_name["owned-healthy"]["spec"]["template"]
    degraded = by_name["owned-degraded"]["spec"]["template"]
    pending = by_name["owned-pending"]["spec"]
    assert healthy["spec"]["containers"][0]["image"] == SHELL_IMAGE
    assert "nodeSelector" not in healthy["spec"]
    assert degraded["spec"]["nodeSelector"] == pending["nodeSelector"]
    assert pending["containers"][0]["resources"]["requests"] == {"cpu": "100m", "memory": "32Mi"}
    completed = by_name["owned-completed"]["spec"]["template"]["spec"]
    assert completed["restartPolicy"] == "Never" and completed["containers"][0]["command"] == [
        "true"
    ]
    assert by_name["owned-suspended"]["spec"]["suspend"] is True


def test_prometheus_genuinely_scrapes_a_separate_explicitly_synthetic_exporter():
    config, service, pod = verification.prometheus_manifests()
    configured = yaml.safe_load(config["data"]["prometheus.yml"])
    assert configured["scrape_configs"] == [
        {
            "job_name": "owned-synthetic-container-metrics",
            "static_configs": [{"targets": ["127.0.0.1:9100"]}],
        }
    ]
    assert config["data"]["exporter.sh"] == verification.EXPORTER_SCRIPT
    assert "counter=$(date +%s)" in verification.EXPORTER_SCRIPT
    assert 'container="exporter",cluster="owned-pulse-fixture"' in verification.EXPORTER_SCRIPT
    assert "exec nc -lk -p 9100 -e /export/respond" in verification.EXPORTER_SCRIPT
    assert "Content-Type: text/plain; version=0.0.4" in verification.EXPORTER_SCRIPT
    assert "Content-Length: %s" in verification.EXPORTER_SCRIPT
    containers = {value["name"]: value for value in pod["spec"]["containers"]}
    assert containers["prometheus"]["image"] == verification.PROMETHEUS_IMAGE
    assert "@sha256:" in verification.PROMETHEUS_IMAGE
    assert containers["exporter"]["image"] == SHELL_IMAGE
    assert containers["exporter"]["command"] == ["sh", "/etc/owned/exporter.sh"]
    assert pod["spec"]["automountServiceAccountToken"] is False
    assert service["spec"]["ports"][0]["port"] == 9090
    backend = HistoryBackend(verification.NAMESPACE, verification.PROMETHEUS)
    assert backend.path.startswith("/api/v1/namespaces/kuberich-owned-pulse/services/")


def test_source_receipt_includes_ui_assets_and_ignores_generated_bytecode(tmp_path):
    paths = (
        "src/kuberich/domain/pulse.py",
        "src/kuberich/ui/pulse.tcss",
        "uv.lock",
        "pyproject.toml",
        "scripts/owned_kind.py",
        "scripts/verify_pulse_kind.py",
    )
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen input")
    ignored = tmp_path / "src/kuberich/__pycache__/pulse.pyc"
    ignored.parent.mkdir()
    ignored.write_bytes(b"generated")
    before = verification.input_hashes(tmp_path)
    assert set(before) == set(paths)
    ignored.write_bytes(b"changed generated")
    assert verification.input_hashes(tmp_path) == before
    (tmp_path / "src/kuberich/ui/pulse.tcss").write_text("changed production style")
    assert verification.input_hashes(tmp_path) != before


def test_history_receipt_keeps_missing_points_explicit():
    receipt = verification.history_evidence(HistorySnapshot())
    assert receipt["observed_at"] is receipt["start"] is receipt["end"] is None
    assert receipt["series"] == {}


def test_failed_verification_still_drains_owned_cluster_and_preserves_failure_without_raw_values(
    tmp_path, monkeypatch
):
    events = []
    private = tmp_path / "private-owned"
    path = private / "owned-kubeconfig"

    @contextmanager
    def owned(kind, *, docker):
        assert kind == "/explicit/kind" and docker == "/explicit/docker"
        private.mkdir()
        path.write_text("synthetic fixture")
        events.append("created")
        try:
            yield OwnedCluster(
                "kuberich-test-fixture",
                path,
                private,
                "kind-kuberich-test-fixture",
                ("owned-node",),
            )
        finally:
            path.unlink()
            private.rmdir()
            events.append("deleted")

    async def fail(cluster, evidence):
        raise RuntimeError("raw-values-must-not-enter-evidence")

    evidence = tmp_path / "evidence/pulse.json"
    monkeypatch.setattr(verification, "owned_cluster", owned)
    monkeypatch.setattr(verification, "verify", fail)
    monkeypatch.setattr(verification, "input_hashes", lambda _: {"fixed-source": "fixture"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_pulse_kind",
            "--kind",
            "/explicit/kind",
            "--docker",
            "/explicit/docker",
            "--evidence",
            str(evidence),
        ],
    )
    with pytest.raises(RuntimeError):
        verification.main()
    result = json.loads(evidence.read_text())
    assert events == ["created", "deleted"]
    assert result["status"] == "failed" and result["failure_type"] == "RuntimeError"
    assert result["owned_cluster_deleted"] and result["private_directory_deleted"]
    assert result["inputs_unchanged"]
    assert "raw-values" not in evidence.read_text()


def test_existing_evidence_is_never_overwritten(tmp_path, monkeypatch):
    evidence = tmp_path / "existing.json"
    evidence.write_text("previous failure")
    monkeypatch.setattr(
        sys, "argv", ["verify_pulse_kind", "--kind", "/explicit/kind", "--evidence", str(evidence)]
    )
    with pytest.raises(ValueError, match="fresh evidence"):
        verification.main()
    assert evidence.read_text() == "previous failure"


def test_stage_receipt_and_pod_status_omit_raw_messages_and_payloads(tmp_path):
    verification.checkpoint(tmp_path, "waiting-for-controller-pod-health-and-budget-state")
    stage = json.loads((tmp_path / "pulse-stage.json").read_text())
    assert stage["stage"] == "waiting-for-controller-pod-health-and-budget-state"
    status = {
        "phase": "Pending",
        "message": "do-not-record-private-message",
        "containerStatuses": [
            {
                "name": "app",
                "ready": False,
                "restartCount": 1,
                "state": {
                    "waiting": {
                        "reason": "ImagePullBackOff",
                        "message": "do-not-record-private-message",
                    }
                },
                "env": {"token": "do-not-record-private-message"},
            },
            None,
            {"state": None, "name": "bad\nname"},
        ],
    }
    observed = verification.pod_status(pulse_record(status=status))
    assert observed["phase"] == "Pending"
    assert observed["containers"][0]["waiting_reason"] == "ImagePullBackOff"
    assert observed["containers"][1]["name"] is None
    assert "do-not-record" not in json.dumps(observed)
    assert verification.pod_status(pulse_record(status=None))["containers"] == []


@pytest.mark.asyncio
async def test_failure_diagnostics_read_only_owned_namespace_pods_and_preserve_denial(tmp_path):
    roots = pulse_roots()
    denied = [False]

    async def handler(request):
        if request.path in roots:
            return web.json_response(roots[request.path])
        assert request.path == "/api/v1/namespaces/kuberich-owned-pulse/pods"
        if denied[0]:
            return web.Response(status=403)
        return web.json_response(
            collection(
                pulse_object(identity="owned-fixture", namespace=verification.NAMESPACE),
                pulse_object(identity="unrelated", namespace=verification.NAMESPACE),
            )
        )

    async with reader_fixture(tmp_path, handler) as reader:
        directory = tmp_path / "diagnostics"
        await verification.preserve_failure_pods(reader.session, directory)
        result = json.loads((directory / "pulse-failure-pods.json").read_text())
        assert result["status"] == "observed" and len(result["pods"]) == 1
        assert result["pods"][0]["name"] == "owned-fixture"
        denied[0] = True
        await verification.preserve_failure_pods(reader.session, directory)
        result = json.loads((directory / "pulse-failure-pods.json").read_text())
        assert result["status"] == "unavailable" and result["failure_type"] == "HttpProblem"
        await verification.preserve_failure_pods(None, directory)
        assert (
            json.loads((directory / "pulse-failure-pods.json").read_text())["status"]
            == "unavailable"
        )
