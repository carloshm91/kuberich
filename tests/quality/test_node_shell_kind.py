"""The owned-kind rehearsal pins inputs and exercises actual bounded HTTP fault injection."""

import ast
import asyncio
import json
import signal
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell_files import NodeShellJournal
from kuberich.domain.mutations import MutationState
from kuberich.errors import AppError
from kuberich.services.node_shell import NodeShellManager, NodeShellState
from scripts import verify_node_shell_kind as rehearsal
from tests.contract.test_node_shell import create, source_fixture
from tests.support.connections import catalog_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["drop_create", "drop_delete", "replace"])
async def test_bounded_proxy_faults_after_real_upstream_commit_without_replay(tmp_path, mode):
    async with source_fixture(tmp_path) as values:
        _, upstream_client, api, policy, current, config = values
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as upstream:
            proxy = rehearsal.FaultProxy(upstream, upstream_client.configuration.host, mode)
            app = web.Application(client_max_size=1024 * 1024)
            app.router.add_route("*", "/{path:.*}", proxy.handle)
            server = web.AppRunner(app)
            await server.setup()
            site = web.TCPSite(server, "127.0.0.1", 0)
            await site.start()
            directory = tmp_path / "proxy-catalog"
            directory.mkdir()
            client = KubernetesSession(
                catalog_fixture(
                    directory, f"http://127.0.0.1:{server.addresses[0][1]}", None, None
                ).select("kuberich-test-one"),
                2,
            )
            manager = NodeShellManager(NodeShellJournal(tmp_path / "proxy-journal"))
            try:
                await client.open()
                owner = create((manager, client, api, policy, current, config), tmp_path)
                intent = await owner.prepare()
                result = await owner.execute(owner.confirm(intent))
                assert sum(item["create"] for item in proxy.receipts) == 1
                if mode == "drop_create":
                    assert result.state is MutationState.UNCERTAIN and api.pod is not None
                    (record,) = await manager.scan()
                    assert record.pod_uid is None and api.deletes == []
                else:
                    assert owner.observation.state is NodeShellState.READY
                    await owner.close()
                    assert sum(item["delete"] for item in proxy.receipts) == 1
                    assert await manager.scan() == ()
                    if mode == "replace":
                        assert (
                            api.pod["metadata"]["uid"] == proxy.replacement_uid == "replacement-uid"
                        )
                        assert any(
                            item["delete"] and item["status"] == 409 for item in proxy.receipts
                        )
                    else:
                        assert api.pod is None
            finally:
                await manager.close()
                await client.close()
                await server.cleanup()


def arguments(tmp_path, monkeypatch):
    kind, kubectl = tmp_path / "kind", tmp_path / "kubectl"
    kind.write_bytes(b"synthetic-kind")
    kubectl.write_bytes(b"synthetic-kubectl")
    evidence = tmp_path / "proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_node_shell_kind",
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


def test_main_refuses_unverified_kind_before_creating_any_cluster(tmp_path, monkeypatch):
    arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rehearsal, "owned_cluster", lambda *args, **kwargs: pytest.fail("Unexpected cluster")
    )
    with pytest.raises(ValueError, match="checksum-verified"):
        rehearsal.main()


def test_main_preserves_existing_evidence_before_reading_tools(tmp_path, monkeypatch):
    kind, _, evidence = arguments(tmp_path, monkeypatch)
    evidence.write_text("original")
    kind.unlink()
    with pytest.raises(ValueError, match="fresh"):
        rehearsal.main()
    assert evidence.read_text() == "original"


def test_main_retains_failure_after_cluster_cleanup_and_checks_actual_absence(
    tmp_path, monkeypatch
):
    _, _, evidence = arguments(tmp_path, monkeypatch)
    events = []
    directory = tmp_path / "owned-private"
    directory.mkdir()
    cluster = SimpleNamespace(name="kuberich-test-fixture", directory=directory)

    @contextmanager
    def owned(*args, **kwargs):
        events.append("create")
        try:
            yield cluster
        finally:
            events.append("delete")
            directory.rmdir()

    async def fail(*args):
        events.append("verify")
        raise RuntimeError("synthetic fixture failure")

    monkeypatch.setattr(
        rehearsal,
        "sha256_file",
        lambda path: rehearsal.KIND_SHA256 if path.name == "kind" else rehearsal.KUBECTL_SHA256,
    )
    monkeypatch.setattr(rehearsal, "owned_cluster", owned)
    monkeypatch.setattr(rehearsal, "verify", fail)
    monkeypatch.setattr(rehearsal, "input_hashes", lambda root: {"fixture": "a" * 64})
    monkeypatch.setattr(rehearsal, "capture_docker", lambda docker: {})
    monkeypatch.setattr(rehearsal, "run_owned", lambda argv, environment: "")
    with pytest.raises(RuntimeError, match="synthetic"):
        rehearsal.main()
    result = json.loads(evidence.read_text())
    assert events == ["create", "verify", "delete"]
    assert result["status"] == "failed" and result["failure_type"] == "RuntimeError"
    assert result["private_directory_deleted"] and result["owned_cluster_deleted"]
    assert "synthetic fixture failure" not in evidence.read_text()


def test_input_hashes_include_product_lock_and_verifier(tmp_path):
    source = tmp_path / "src/kuberich"
    source.mkdir(parents=True)
    (source / "owned.py").write_text("value = 1\n")
    (source / "__pycache__").mkdir()
    (source / "__pycache__/ignored.pyc").write_bytes(b"ignored")
    (tmp_path / "scripts").mkdir()
    for name in (
        "pyproject.toml",
        "uv.lock",
        "scripts/owned_kind.py",
        "scripts/verify_node_shell_kind.py",
    ):
        (tmp_path / name).write_text(name)
    captured = rehearsal.input_hashes(tmp_path)
    assert len(captured) == 5 and "src/kuberich/owned.py" in captured
    (source / "owned.py").write_text("value = 2\n")
    assert rehearsal.input_hashes(tmp_path) != captured


@pytest.mark.asyncio
async def test_absence_requires_404_and_wait_uses_a_finite_deadline():
    class Client:
        async def get_json(self, path):
            from kuberich.domain.connections import HttpProblem

            raise HttpProblem(403)

    from kuberich.domain.connections import HttpProblem

    with pytest.raises(HttpProblem):
        await rehearsal.absent(Client(), "owned")
    assert rehearsal.VERIFY_SECONDS <= 600
    assert asyncio.iscoroutinefunction(rehearsal.wait_absent)


def producer_marker():
    return {
        "state": "ready",
        "operation_id": "a" * 32,
        "pod_name": "kuberich-node-shell-" + "a" * 32,
        "pod_uid": "owned-kubernetes-uid",
    }


def test_producer_handoff_accepts_only_bounded_operation_metadata():
    marker = producer_marker()
    assert rehearsal.producer_receipt(json.dumps(marker).encode()) == marker


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"x" * 4097,
        b"\xff",
        b"not-json",
        b"[]",
        b"null",
        json.dumps({**producer_marker(), "certificate": "synthetic-private-TLS-material"}).encode(),
        json.dumps({**producer_marker(), "state": "failed"}).encode(),
        json.dumps({**producer_marker(), "pod_uid": ""}).encode(),
        json.dumps({**producer_marker(), "pod_uid": "a" * 254}).encode(),
        json.dumps({**producer_marker(), "pod_uid": "synthetic-private\u001b[31m"}).encode(),
        json.dumps({**producer_marker(), "pod_uid": {"private-key": "synthetic-private"}}).encode(),
        json.dumps({**producer_marker(), "operation_id": "not-an-operation"}).encode(),
        json.dumps({**producer_marker(), "pod_name": "unrelated-pod"}).encode(),
        b'{"state":"ready","state":"ready","operation_id":"a","pod_name":"p","pod_uid":"u"}',
        json.dumps(list(producer_marker().items())).encode(),
    ],
)
def test_unverified_producer_output_is_refused_without_echoing_tls_or_raw_bytes(payload):
    with pytest.raises(AppError, match="readiness could not be verified") as failure:
        rehearsal.producer_receipt(payload)
    assert "synthetic-private" not in str(failure.value) and "\x1b" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "already_exited,lookup_race", [(False, False), (True, False), (False, True)]
)
async def test_producer_reap_uses_only_guarded_owned_handle_and_awaits_exit(
    already_exited, lookup_race
):
    calls = []

    class Process:
        returncode = 0 if already_exited else None

        def kill(self):
            calls.append("kill")
            if lookup_race:
                raise ProcessLookupError

        async def wait(self):
            calls.append("wait")
            self.returncode = 0 if already_exited else -signal.SIGKILL
            return self.returncode

    process = Process()
    await rehearsal.reap_producer(process)
    assert calls == (["wait"] if already_exited else ["kill", "wait"])
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_producer_reap_has_a_finite_wait_deadline(monkeypatch):
    timeout = asyncio.timeout
    monkeypatch.setattr(rehearsal.asyncio, "timeout", lambda duration: timeout(0.01))

    class Process:
        returncode = None

        def kill(self):
            pass

        async def wait(self):
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await rehearsal.reap_producer(Process())


def test_static_crash_producer_is_valid_and_prints_only_reviewed_metadata():
    tree = ast.parse(rehearsal.CRASH_PRODUCER)
    output_keys = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            assert len(node.args) == 1 and isinstance(node.args[0], ast.Call)
            payload = node.args[0].args[0]
            assert isinstance(payload, ast.Dict)
            output_keys.append({key.value for key in payload.keys if isinstance(key, ast.Constant)})
    assert output_keys == [set(producer_marker()), {"state", "failure_type"}]


def test_verifier_hash_pins_its_embedded_crash_producer(tmp_path):
    source = tmp_path / "src/kuberich"
    source.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    for name in ("pyproject.toml", "uv.lock", "scripts/owned_kind.py"):
        (tmp_path / name).write_text(name)
    verifier = tmp_path / "scripts/verify_node_shell_kind.py"
    verifier.write_text(rehearsal.CRASH_PRODUCER)
    captured = rehearsal.input_hashes(tmp_path)
    verifier.write_text(rehearsal.CRASH_PRODUCER + "\n# changed fixture\n")
    assert (
        rehearsal.input_hashes(tmp_path)["scripts/verify_node_shell_kind.py"]
        != captured["scripts/verify_node_shell_kind.py"]
    )
