"""Benchmark qualification keeps frozen inputs, failures and cleanup receipts honest."""

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import verify_benchmarks_kind as proof


def arguments(tmp_path, monkeypatch):
    tools = []
    for name in ("kind", "kubectl", "vegeta"):
        path = tmp_path / name
        path.write_bytes(b"synthetic-" + name.encode())
        tools.append(path)
    evidence = tmp_path / "proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "--kind",
            str(tools[0]),
            "--kubectl",
            str(tools[1]),
            "--vegeta",
            str(tools[2]),
            "--docker",
            "owned-docker",
            "--evidence",
            str(evidence),
        ],
    )
    return tools, evidence


def pins(monkeypatch):
    monkeypatch.setattr(
        proof,
        "sha256_file",
        lambda path: proof.KIND_SHA256 if path.name == "kind" else proof.KUBECTL_SHA256,
    )
    monkeypatch.setattr(proof, "verify_benchmark_binary", lambda path: "synthetic-verified-sha")


def test_existing_receipt_refused_before_any_tool_read(tmp_path, monkeypatch):
    tools, evidence = arguments(tmp_path, monkeypatch)
    evidence.write_text("original-failed-evidence")
    tools[0].unlink()
    with pytest.raises(ValueError, match="fresh"):
        proof.main()
    assert evidence.read_text() == "original-failed-evidence"


def test_relative_paths_refused_before_tool_execution_or_cluster(tmp_path, monkeypatch):
    _, evidence = arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "--kind",
            "relative",
            "--kubectl",
            "relative",
            "--vegeta",
            "relative",
            "--evidence",
            str(evidence),
        ],
    )
    monkeypatch.setattr(proof, "sha256_file", lambda path: pytest.fail("tool read"))
    with pytest.raises(ValueError, match="absolute"):
        proof.main()


@pytest.mark.parametrize("wrong", ["kind", "kubectl"])
def test_wrong_owned_tool_refused_before_cluster_or_vegeta(tmp_path, monkeypatch, wrong):
    arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        proof,
        "sha256_file",
        lambda path: (
            "bad"
            if path.name == wrong
            else proof.KIND_SHA256
            if path.name == "kind"
            else proof.KUBECTL_SHA256
        ),
    )
    monkeypatch.setattr(
        proof, "verify_benchmark_binary", lambda path: pytest.fail("benchmark execution")
    )
    with pytest.raises(ValueError, match="reviewed pins"):
        proof.main()


def test_dirty_source_refuses_before_optionaltool_or_cluster(tmp_path, monkeypatch):
    arguments(tmp_path, monkeypatch)
    pins(monkeypatch)
    monkeypatch.setattr(
        proof, "source_identity", lambda root: (_ for _ in ()).throw(ValueError("freeze"))
    )
    monkeypatch.setattr(
        proof, "verify_benchmark_binary", lambda path: pytest.fail("benchmark execution")
    )
    with pytest.raises(ValueError, match="freeze"):
        proof.main()


@pytest.mark.parametrize("failure", [None, "verify", "cleanup", "source"])
def test_exact_source_actual_failure_and_cleanup_are_retained_without_private_errors(
    tmp_path, monkeypatch, failure
):
    _, evidence = arguments(tmp_path, monkeypatch)
    pins(monkeypatch)
    directory = tmp_path / "owned-private"
    directory.mkdir()
    cluster = SimpleNamespace(name="kuberich-test-fixture", directory=directory)
    events = []

    @contextmanager
    def owned(kind, **kwargs):
        assert kwargs == {"docker": "owned-docker"}
        events.append("create")
        try:
            yield cluster
        finally:
            events.append("delete")
            if failure == "cleanup":
                raise ValueError("synthetic-private-cleanup")
            directory.rmdir()

    async def verify(actual, progress, kubectl, vegeta):
        assert actual is cluster and progress["status"] == "failed"
        progress["phase"] = "controlled-behavior"
        events.append("verify")
        if failure == "verify":
            raise RuntimeError("synthetic-private-raw-report")
        return {"checks": list(proof.BENCHMARK_CHECKS)}

    monkeypatch.setattr(proof, "owned_cluster", owned)
    monkeypatch.setattr(proof, "verify", verify)
    monkeypatch.setattr(proof, "source_identity", lambda root: "exact-head")
    count = 0

    def hashes(root):
        nonlocal count
        count += 1
        return {"owned-input": "modified" if failure == "source" and count > 1 else "original"}

    monkeypatch.setattr(proof, "input_hashes", hashes)
    if failure:
        with pytest.raises((RuntimeError, ValueError, AssertionError)):
            proof.main()
    else:
        proof.main()
    result = json.loads(evidence.read_text())
    assert result["status"] == ("failed" if failure else "passed")
    assert result["source_commit"] == "exact-head" and result["input_hashes"] == {
        "owned-input": "original"
    }
    assert result["owned_cluster_deleted"] == (failure != "cleanup")
    assert result["private_directory_deleted"] == (failure != "cleanup")
    assert result["tools"]["signatures_verified"] is False
    assert events == ["create", "verify", "delete"]
    assert "synthetic-private" not in evidence.read_text()
    if failure:
        assert result["failure_type"] and result["failure_locations"]


def test_pre_drain_connections_are_reported_separately_without_an_atomic_unsend_claim():
    traffic = proof.ReplacementTraffic()
    traffic.connect()
    traffic.connect()
    traffic.request()
    before = traffic.snapshot()
    assert before["connections_before_drain"] == 2 and before["requests_before_drain"] == 1
    assert before["connections_after_drain"] == before["requests_after_drain"] == 0
    with pytest.raises(AssertionError):
        traffic.require_stopped()
    traffic.drained = True
    traffic.require_stopped()
    assert traffic.snapshot()["connections_before_drain"] == 2


@pytest.mark.parametrize("kind", ["connect", "request"])
def test_any_injected_post_drain_traffic_still_fails(kind):
    traffic = proof.ReplacementTraffic(drained=True)
    getattr(traffic, kind)()
    with pytest.raises(AssertionError):
        traffic.require_stopped()
    assert (
        traffic.snapshot()[f"{'connections' if kind == 'connect' else 'requests'}_after_drain"] == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "ready_forward", "review_replay"])
async def test_lost_forward_or_consumed_review_cannot_become_a_new_authority(fault):
    from kuberich.errors import AppError

    class Forwards:
        def owned_source(self, identity, attempt):
            assert identity == "owned-id" and attempt == 0
            if fault == "ready_forward":
                return object()
            raise AppError("not ready")

    class Owner:
        async def run(self, review):
            assert review == "one-use-review"
            if fault == "review_replay":
                return object()
            raise AppError("consumed")

    if fault:
        with pytest.raises(AssertionError):
            await proof.require_retired(Owner(), "one-use-review", Forwards(), "owned-id")
    else:
        await proof.require_retired(Owner(), "one-use-review", Forwards(), "owned-id")
