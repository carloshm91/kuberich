"""The real-provider verifier refuses drifting artifacts before cluster creation."""

import re
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import yaml

from kuberich.domain.history import (
    HistoryPoint,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    MemberIdentity,
    MembershipEvidence,
)
from scripts import verify_history_kind as verifier
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster


def test_actual_provider_images_chart_sources_and_dependency_locks_are_pinned():
    assert {pin.name for pin in verifier.CHARTS} == {
        "kube-prometheus-stack",
        "victoria-metrics-single",
    }
    for pin in verifier.CHARTS:
        assert re.fullmatch(r"[0-9a-f]{64}", pin.sha256)
        assert re.fullmatch(r"[0-9a-f]{40}", pin.source)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin.lock_digest)
        assert pin.url.endswith(pin.name + "-" + pin.version + ".tgz")
    assert {
        "operator",
        "reloader",
        "prometheus",
        "ksm",
        "node-exporter",
        "victoriametrics",
        "thanos",
    } == set(verifier.IMAGES)
    for image in (*verifier.IMAGES.values(), NODE_IMAGE, SHELL_IMAGE):
        assert re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image)


def test_every_direct_and_operator_rendered_image_is_checked():
    documents = verifier.fixture_manifests()
    assert set(verifier.rendered_images(documents)) == {SHELL_IMAGE, verifier.IMAGES["thanos"]}
    with pytest.raises(ValueError, match="digest-pinned"):
        verifier.rendered_images(({"spec": {"image": "prometheus:latest"}},))
    with pytest.raises(ValueError, match="digest-pinned"):
        verifier.rendered_images(
            (
                {
                    "spec": {
                        "containers": [
                            {"args": ["--prometheus-config-reloader-image=unqualified:latest"]}
                        ]
                    }
                },
            )
        )


def test_minimal_stack_retains_native_collectors_and_thanos_sidecar():
    values = verifier.stack_values()
    assert not values["grafana"]["enabled"] and not values["alertmanager"]["enabled"]
    assert not values["defaultRules"]["create"]
    assert "kube-state-metrics" in values and "prometheus-node-exporter" in values
    assert values["prometheus"]["prometheusSpec"]["thanos"]["image"] == verifier.IMAGES["thanos"]
    assert values["prometheus"]["prometheusSpec"]["remoteWrite"][0]["url"].endswith("/api/v1/write")
    assert values["prometheus-node-exporter"]["image"]["digest"].startswith("sha256:")
    assert not verifier.vm_values()["server"]["persistentVolume"]["enabled"]
    assert "@sha256:" in verifier.vm_values()["server"]["image"]["tag"]


def test_query_observations_bound_series_and_preserve_actual_absence():
    assert verifier._samples({"status": "success", "data": {"result": []}}) == ()
    assert verifier._samples(
        {"status": "success", "data": {"result": [{"metric": {"container": "POD"}}]}}
    ) == ({"container": "POD"},)
    for document in (
        None,
        {"status": "error"},
        {"status": "success", "data": {"result": [None] * 129}},
    ):
        with pytest.raises(AssertionError):
            verifier._samples(document)


def test_owned_receiver_and_reset_exporter_emit_valid_bounded_http_and_only_presence_metadata():
    synthetic_request = "GET /api/v1/query_range?end=0 HTTP/1.1\r\nAuthorization: synthetic-control\r\nImpersonate-User: synthetic-control\r\n\r\n"
    captured = subprocess.run(
        ["sh", "-c", verifier.CAPTURE_RESPONDER],
        input=synthetic_request,
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert "synthetic-control" not in captured.stderr
    assert (
        '"authorization_present":1' in captured.stderr
        and '"impersonation_count":1' in captured.stderr
    )
    with pytest.raises(AssertionError):
        verifier.assert_backend_isolation(
            ({"authorization_present": 1, "impersonation_count": 1, "query_range": 1},)
        )
    verifier.assert_backend_isolation(
        ({"authorization_present": 0, "impersonation_count": 0, "query_range": 1},)
    )
    exported = subprocess.run(
        ["sh", "-c", verifier.RESET_RESPONDER],
        input=synthetic_request,
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    header, body = exported.stdout.split("\n\n", 1)
    length = int(re.search(r"Content-Length: ([0-9]+)", header)[1])
    assert len(body.encode()) == length and body.endswith("\n")
    assert "kuberich_fixture_counter_total" in body and "synthetic-reset" in body
    assert "container_cpu_usage_seconds_total" not in body


def test_native_qualification_requires_parsed_positive_values_for_both_core_families():
    empty = verifier.native_value_summary(HistorySnapshot(HistoryStatus.NO_DATA))
    assert empty["cpu"]["positive_points"] == empty["memory"]["positive_points"] == 0
    point = HistoryPoint(datetime(2026, 11, 6, tzinfo=UTC), Decimal("0.25"))
    observed = verifier.native_value_summary(
        HistorySnapshot(
            HistoryStatus.PARTIAL,
            series=(
                HistorySeries("cpu", "Native CPU", "cores", (point,)),
                HistorySeries("memory", "Native memory", "bytes", (point,)),
            ),
        )
    )
    assert observed["cpu"]["positive_points"] == observed["memory"]["positive_points"] == 1
    assert observed["cpu"]["minimum"] == "0.25"


def test_rollout_comparison_rejects_old_uid_rebind_lost_history_and_fabricated_young_values():
    now = datetime(2026, 11, 6, tzinfo=UTC)
    historical = HistorySnapshot(
        HistoryStatus.PARTIAL,
        series=(
            HistorySeries("cpu", "CPU", "cores", (HistoryPoint(now, Decimal("0.25")),)),
            HistorySeries("memory", "Memory", "bytes", (HistoryPoint(now, Decimal("1024")),)),
        ),
        membership_evidence=MembershipEvidence(),
    )
    projection = HistorySnapshot(
        HistoryStatus.NO_DATA,
        end=now + timedelta(seconds=60),
        membership_evidence=MembershipEvidence(
            "current-members",
            "current-only",
            now,
            (MemberIdentity("owned", "new", "new-uid", now),),
        ),
    )
    evidence = verifier.rollout_comparison(historical, projection, frozenset({"old-uid"}))
    assert evidence["historical_membership_status"] == "name-inferred"
    assert evidence["current_member_uids"] == ["new-uid"]
    for previous, current in (
        (replace(historical, series=()), projection),
        (historical, replace(projection, series=historical.series)),
        (historical, replace(projection, end=now + timedelta(seconds=301))),
        (
            historical,
            replace(
                projection,
                membership_evidence=replace(
                    projection.membership_evidence,
                    members=(MemberIdentity("owned", "old", "old-uid", now),),
                ),
            ),
        ),
    ):
        with pytest.raises(AssertionError):
            verifier.rollout_comparison(previous, current, frozenset({"old-uid"}))


@pytest.mark.asyncio
async def test_mixed_manifest_apply_preserves_namespaces_and_owned_destination(
    tmp_path, monkeypatch
):
    cluster = OwnedCluster(
        "owned", tmp_path / "owned-kubeconfig", tmp_path, "kind-owned", ("owned-node",)
    )
    calls = []

    def capture(argv, environment, timeout):
        calls.append((argv, environment["KUBECONFIG"]))
        return "owned result"

    monkeypatch.setattr(verifier, "run_owned", capture)
    documents = (
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "system", "namespace": "kube-system"},
        },
        {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "fixture"}},
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "owned-role"},
        },
    )
    await verifier._apply(cluster, "owned-kubectl", "mixed", documents)
    argv, config = calls[0]
    assert argv[:5] == [
        "owned-kubectl",
        "--kubeconfig",
        str(cluster.path),
        "--context",
        cluster.context,
    ]
    assert "--namespace" not in argv and argv[5] == "apply"
    assert config == str(cluster.path)
    written = tuple(yaml.safe_load_all((tmp_path / "mixed.yaml").read_text()))
    assert written[0]["metadata"]["namespace"] == "kube-system"
    assert written[1]["metadata"]["namespace"] == verifier.NAMESPACE
    assert "namespace" not in written[2]["metadata"]
    assert "namespace" not in documents[1]["metadata"]
    await verifier._command(cluster, "owned-kubectl", "get", "pods")
    ordinary, _ = calls[1]
    assert ordinary[5:7] == ["--namespace", verifier.NAMESPACE]
    with pytest.raises(ValueError, match="manifest application"):
        await verifier._command(cluster, "owned-kubectl", "get", "pods", namespace=None)
    with pytest.raises(ValueError, match="owned fixture"):
        await verifier._apply(
            cluster,
            "owned-kubectl",
            "other",
            ({"kind": "Pod", "metadata": {"name": "outside", "namespace": "unselected"}},),
        )
