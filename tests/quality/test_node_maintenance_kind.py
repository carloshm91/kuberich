"""Owned node-maintenance proof refuses unbound tools and retains exact failures."""

import asyncio
import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import verify_node_maintenance_kind as rehearsal


def arguments(tmp_path, monkeypatch):
    kind, kubectl = tmp_path / "kind", tmp_path / "kubectl"
    kind.write_bytes(b"synthetic-kind")
    kubectl.write_bytes(b"synthetic-kubectl")
    evidence = tmp_path / "proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_node_maintenance_kind",
            "--kind",
            str(kind),
            "--kubectl",
            str(kubectl),
            "--docker",
            "owned-docker",
            "--evidence",
            str(evidence),
        ],
    )
    return kind, kubectl, evidence


def test_existing_evidence_is_preserved_before_tool_reads(tmp_path, monkeypatch):
    kind, _, evidence = arguments(tmp_path, monkeypatch)
    evidence.write_text("retained-original")
    kind.unlink()
    with pytest.raises(ValueError, match="fresh"):
        rehearsal.main()
    assert evidence.read_text() == "retained-original"


@pytest.mark.parametrize("unverified", ["kind", "kubectl"])
def test_tool_digest_refusal_precedes_any_cluster_creation(tmp_path, monkeypatch, unverified):
    arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rehearsal,
        "sha256_file",
        lambda path: (
            "bad"
            if path.name == unverified
            else (rehearsal.KIND_SHA256 if path.name == "kind" else rehearsal.KUBECTL_SHA256)
        ),
    )
    monkeypatch.setattr(rehearsal, "owned_cluster", lambda *args, **kwargs: pytest.fail("cluster"))
    with pytest.raises(ValueError, match="checksum-verified"):
        rehearsal.main()


def test_relative_tools_are_refused_before_digest_reads(tmp_path, monkeypatch):
    _, _, evidence = arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "--kind",
            "relative-kind",
            "--kubectl",
            "relative-kubectl",
            "--evidence",
            str(evidence),
        ],
    )
    monkeypatch.setattr(rehearsal, "sha256_file", lambda path: pytest.fail("digest read"))
    with pytest.raises(ValueError, match="explicit"):
        rehearsal.main()


@pytest.mark.parametrize("failure", [None, "verify", "cleanup", "source"])
def test_main_retains_actual_cleanup_and_failure_without_exception_values(
    tmp_path, monkeypatch, failure
):
    _, _, evidence = arguments(tmp_path, monkeypatch)
    directory = tmp_path / "owned-private"
    directory.mkdir()
    cluster = SimpleNamespace(name="kuberich-test-fixture", directory=directory)
    events = []

    @contextmanager
    def owned(kind, **kwargs):
        assert kwargs == {"docker": "owned-docker", "worker_count": 2}
        events.append("create")
        try:
            yield cluster
        finally:
            events.append("delete")
            if failure == "cleanup":
                raise ValueError("synthetic-private-cleanup-detail")
            directory.rmdir()

    async def verify(*args):
        events.append("verify")
        if failure == "verify":
            raise RuntimeError("synthetic-private-response")
        return {"checks": ["actual-fixture-check"]}

    hashes = iter([{"fixture": "a" * 64}, {"fixture": ("b" if failure == "source" else "a") * 64}])
    monkeypatch.setattr(rehearsal, "owned_cluster", owned)
    monkeypatch.setattr(rehearsal, "verify", verify)
    monkeypatch.setattr(rehearsal, "input_hashes", lambda root: next(hashes))
    monkeypatch.setattr(
        rehearsal,
        "sha256_file",
        lambda path: rehearsal.KIND_SHA256 if path.name == "kind" else rehearsal.KUBECTL_SHA256,
    )
    if failure:
        expected = {"verify": RuntimeError, "cleanup": ValueError, "source": AssertionError}[
            failure
        ]
        with pytest.raises(expected):
            rehearsal.main()
    else:
        rehearsal.main()
    result = json.loads(evidence.read_text())
    assert events == ["create", "verify", "delete"]
    assert result["status"] == ("failed" if failure else "passed")
    assert result["owned_cluster_deleted"] is (failure != "cleanup")
    assert result["private_directory_deleted"] is (failure != "cleanup")
    assert "synthetic-private" not in evidence.read_text()


def test_input_binding_includes_runtime_assets_lock_and_actual_verifier(tmp_path):
    source = tmp_path / "src/kuberich"
    source.mkdir(parents=True)
    (source / "owned.py").write_text("value = 1\n")
    (source / "owned.tcss").write_text("Screen {}\n")
    (source / "__pycache__").mkdir()
    (source / "__pycache__/ignored.pyc").write_bytes(b"ignored")
    (tmp_path / "scripts").mkdir()
    for name in [
        "pyproject.toml",
        "uv.lock",
        "scripts/owned_kind.py",
        "scripts/verify_node_maintenance_kind.py",
    ]:
        (tmp_path / name).write_text(name)
    before = rehearsal.input_hashes(tmp_path)
    assert len(before) == 6 and "src/kuberich/owned.tcss" in before
    (source / "owned.py").write_text("value = 2\n")
    assert rehearsal.input_hashes(tmp_path) != before


@pytest.mark.asyncio
async def test_fixture_wait_observes_success_and_a_real_finite_timeout():
    calls = 0

    async def ready():
        nonlocal calls
        calls += 1
        return calls == 2

    await rehearsal.wait_for(ready, seconds=1)
    assert calls == 2

    async def held():
        await asyncio.Event().wait()
        return False

    with pytest.raises(TimeoutError):
        await rehearsal.wait_for(held, seconds=0.01)
    assert rehearsal.VERIFY_SECONDS <= 600
