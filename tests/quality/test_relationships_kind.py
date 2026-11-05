"""Owned relationship verifier fixture contracts, receipts and failure preservation."""

import json
import sys
from contextlib import contextmanager

import pytest
from aiohttp import web

from kuberich.domain.reference_fields import declared_references
from kuberich.domain.resources import api_resource, resource_record
from scripts import verify_relationships_kind as verification
from scripts.owned_kind import SHELL_IMAGE, OwnedCluster
from tests.support.resources import descriptor, item, reader_fixture

KIND_RESOURCES = {
    "Deployment": "deployments",
    "ReplicaSet": "replicasets",
    "StatefulSet": "statefulsets",
    "DaemonSet": "daemonsets",
    "Job": "jobs",
    "CronJob": "cronjobs",
    "ReplicationController": "replicationcontrollers",
}


def test_actual_fixture_declarations_cover_all_five_targets_in_all_seven_workload_families():
    families = set()
    zero = set()
    for manifest in verification.fixture_manifests():
        if manifest["kind"] not in KIND_RESOURCES:
            continue
        family = manifest["kind"]
        families.add(family)
        resource = api_resource(
            manifest["apiVersion"], descriptor(KIND_RESOURCES[family], kind=family)
        )
        value = {
            **manifest,
            "metadata": {
                **manifest["metadata"],
                "namespace": verification.NAMESPACE,
                "uid": "fixture-" + manifest["metadata"]["name"],
                "resourceVersion": "fixture",
            },
        }
        record = resource_record(resource, value, verification.NAMESPACE)
        declared = declared_references(resource, record)
        assert {(ref.target.kind, ref.target.name) for ref in declared} >= {
            ("ConfigMap", verification.CONFIGMAP),
            ("Secret", verification.SECRET),
            ("ServiceAccount", verification.SERVICEACCOUNT),
            ("PersistentVolumeClaim", verification.PVC),
            ("PriorityClass", verification.PRIORITYCLASS),
        }
        spec = manifest["spec"]
        if spec.get("replicas") == 0 or spec.get("suspend") is True or family == "DaemonSet":
            zero.add(family)
        if family == "CronJob":
            spec = spec["jobTemplate"]["spec"]
        pod_spec = spec["template"]["spec"]
        assert pod_spec["containers"][0]["image"] == SHELL_IMAGE and "@sha256:" in SHELL_IMAGE
        assert pod_spec["automountServiceAccountToken"] is False
        assert pod_spec["terminationGracePeriodSeconds"] == 0
    assert families == zero == set(KIND_RESOURCES)


def test_fixtures_use_owned_static_storage_and_distinct_address_only_service():
    by_name = {
        manifest["metadata"]["name"]: manifest for manifest in verification.fixture_manifests()
    }
    pv = by_name[verification.PV]["spec"]
    pvc = by_name[verification.PVC]["spec"]
    assert pv["claimRef"] == {"namespace": verification.NAMESPACE, "name": verification.PVC}
    assert (
        pvc["volumeName"] == verification.PV
        and pvc["storageClassName"] == pv["storageClassName"] == ""
    )
    assert pv["hostPath"]["path"].startswith("/tmp/kuberich-owned-")
    assert "selector" not in by_name[verification.SELECTORLESS]["spec"]
    slice_body = by_name["owned-address-only"]
    assert (
        slice_body["metadata"]["labels"]["kubernetes.io/service-name"] == verification.SELECTORLESS
    )
    assert slice_body["endpoints"][0]["addresses"] == ["192.0.2.70"]
    assert "targetRef" not in slice_body["endpoints"][0]
    assert slice_body["endpoints"][0]["conditions"]["ready"] is False
    definition = verification.custom_resource_definition()
    assert (
        definition["metadata"]["name"] == verification.CUSTOM_NAME + "." + verification.CUSTOM_GROUP
    )
    assert definition["spec"]["scope"] == "Namespaced"
    assert definition["spec"]["names"]["kind"] == verification.CUSTOM_KIND
    assert definition["spec"]["versions"][0]["storage"] is True


@pytest.mark.asyncio
async def test_read_receipts_wrap_real_owned_http_without_altering_network_operation(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(item())

    receipts = []
    async with reader_fixture(tmp_path, handler) as reader:
        resource = api_resource("v1", descriptor())
        with verification.trace_reads(receipts):
            record = await reader.get(resource, "one", "team")
        assert record.uid == "owned-one"
        assert receipts == [{"path": "/api/v1/namespaces/team/pods/one", "params": None}]
        assert calls == [receipts[0]["path"]]
        assert "synthetic" not in json.dumps(receipts)
        await reader.get(resource, "one", "team")
        assert len(calls) == 2 and len(receipts) == 1


def test_source_hashes_include_assets_and_installed_package_inputs(tmp_path):
    paths = (
        "src/kuberich/services/relationships.py",
        "src/kuberich/ui/styles.tcss",
        "uv.lock",
        "pyproject.toml",
        "scripts/owned_kind.py",
        "scripts/verify_relationships_kind.py",
    )
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen source")
    bytecode = tmp_path / "src/kuberich/__pycache__/generated.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"generated")
    before = verification.input_hashes(tmp_path)
    assert set(before) == set(paths)
    bytecode.write_bytes(b"other generated")
    assert verification.input_hashes(tmp_path) == before
    (tmp_path / "src/kuberich/ui/styles.tcss").write_text("changed input")
    assert verification.input_hashes(tmp_path) != before


def test_stage_receipts_are_appended_before_assertions_and_keep_numeric_failure_observations(
    tmp_path,
):
    verification.checkpoint(
        tmp_path,
        "observed-before-assertion",
        expected_uid="synthetic-before",
        observed_uid="synthetic-after",
        row_count=3,
    )
    verification.checkpoint(tmp_path, "failure-retained", status="replaced", requests_used=7)
    entries = [
        json.loads(line)
        for line in (tmp_path / "relationships-stages.jsonl").read_text().splitlines()
    ]
    assert [entry["stage"] for entry in entries] == [
        "observed-before-assertion",
        "failure-retained",
    ]
    assert entries[0]["row_count"] == 3 and entries[1]["requests_used"] == 7
    assert json.loads((tmp_path / "relationships-stage.json").read_text()) == entries[-1]


def test_failure_always_deletes_owned_cluster_and_retains_only_failure_type(tmp_path, monkeypatch):
    events = []
    private = tmp_path / "private"
    config = private / "owned-kubeconfig"

    @contextmanager
    def owned(kind, *, docker):
        assert kind == "/verified/kind" and docker == "/verified/docker"
        private.mkdir()
        config.write_text("synthetic private material")
        events.append("created")
        try:
            yield OwnedCluster(
                "kuberich-test-fixture",
                config,
                private,
                "kind-kuberich-test-fixture",
                ("owned-node",),
            )
        finally:
            config.unlink()
            private.rmdir()
            events.append("deleted")

    async def fail(cluster, directory):
        verification.checkpoint(
            directory, "before-controlled-failure", observed_uid="synthetic-observed", row_count=0
        )
        raise AssertionError("PRIVATE-error-message-never-exported")

    evidence = tmp_path / "evidence/relationships.json"
    monkeypatch.setattr(verification, "owned_cluster", owned)
    monkeypatch.setattr(verification, "verify", fail)
    monkeypatch.setattr(verification, "input_hashes", lambda _: {"frozen-source": "receipt"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_relationships_kind",
            "--kind",
            "/verified/kind",
            "--docker",
            "/verified/docker",
            "--evidence",
            str(evidence),
        ],
    )
    with pytest.raises(AssertionError):
        verification.main()
    result = json.loads(evidence.read_text())
    assert events == ["created", "deleted"]
    assert result["status"] == "failed" and result["failure_type"] == "AssertionError"
    assert (
        result["owned_cluster_deleted"]
        and result["private_directory_deleted"]
        and result["inputs_unchanged"]
    )
    assert result["deadline_seconds"] == verification.VERIFY_SECONDS
    assert "PRIVATE" not in evidence.read_text()
    stage = json.loads((evidence.parent / "relationships-stage.json").read_text())
    assert stage["row_count"] == 0 and stage["observed_uid"] == "synthetic-observed"


def test_previous_failure_and_stage_evidence_cannot_be_overwritten(tmp_path, monkeypatch):
    evidence = tmp_path / "relationships.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_relationships_kind", "--kind", "/verified/kind", "--evidence", str(evidence)],
    )
    evidence.write_text("retained failure")
    with pytest.raises(ValueError, match="fresh evidence"):
        verification.main()
    assert evidence.read_text() == "retained failure"
    evidence.unlink()
    (tmp_path / "relationships-stages.jsonl").write_text("retained stage")
    with pytest.raises(ValueError, match="fresh evidence"):
        verification.main()
    assert not evidence.exists()


def test_pod_wait_receipt_retains_state_codes_and_omits_arbitrary_messages():
    resource = api_resource("v1", descriptor())
    record = resource_record(
        resource,
        {
            **item(),
            "status": {
                "phase": "Pending",
                "message": "PRIVATE-raw-server-message",
                "containerStatuses": [
                    {
                        "ready": False,
                        "restartCount": 3,
                        "state": {
                            "waiting": {
                                "reason": "ImagePullBackOff",
                                "message": "PRIVATE-raw-server-message",
                            }
                        },
                    },
                    {"state": {"waiting": {"reason": "PRIVATE-raw-server-message"}}},
                    None,
                ],
            },
        },
        "team",
    )
    receipt = verification.pod_wait_receipt(record)
    assert receipt["phase"] == "Pending"
    assert receipt["containers"][0]["restart_count"] == 3
    assert receipt["containers"][0]["waiting_reason"] == "ImagePullBackOff"
    assert receipt["containers"][1]["waiting_reason"] == "Other"
    assert "PRIVATE" not in json.dumps(receipt)
    assert verification.pod_wait_receipt(None) is None
