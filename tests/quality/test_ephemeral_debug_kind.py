"""Owned debug proof fails closed before effects and preserves failed cleanup evidence."""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.processes import ProcessMode, ProcessPurpose, capture_command
from scripts import verify_ephemeral_debug_kind as proof
from tests.support.connections import catalog_fixture, certificate


def arguments(tmp_path, monkeypatch):
    kind, kubectl = tmp_path / "kind", tmp_path / "kubectl"
    kind.write_bytes(b"synthetic-kind")
    kubectl.write_bytes(b"synthetic-kubectl")
    evidence = tmp_path / "proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
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


def tool_digests(monkeypatch):
    monkeypatch.setattr(
        proof,
        "sha256_file",
        lambda path: proof.KIND_SHA256 if path.name == "kind" else proof.KUBECTL_SHA256,
    )


def test_existing_evidence_is_retained_before_tools_or_cluster(tmp_path, monkeypatch):
    kind, _, evidence = arguments(tmp_path, monkeypatch)
    evidence.write_text("original-failed-evidence")
    kind.unlink()
    with pytest.raises(ValueError, match="fresh"):
        proof.main()
    assert evidence.read_text() == "original-failed-evidence"


def test_relative_tool_path_is_refused_without_reading_it(tmp_path, monkeypatch):
    _, _, evidence = arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["proof", "--kind", "kind", "--kubectl", "kubectl", "--evidence", str(evidence)],
    )
    monkeypatch.setattr(proof, "sha256_file", lambda path: pytest.fail("tool read"))
    with pytest.raises(ValueError, match="explicit"):
        proof.main()


@pytest.mark.parametrize("unverified", ["kind", "kubectl"])
def test_unbound_tools_never_create_a_cluster(tmp_path, monkeypatch, unverified):
    arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(
        proof,
        "sha256_file",
        lambda path: (
            "bad"
            if path.name == unverified
            else (proof.KIND_SHA256 if path.name == "kind" else proof.KUBECTL_SHA256)
        ),
    )
    monkeypatch.setattr(proof, "owned_cluster", lambda *args, **kwargs: pytest.fail("cluster"))
    with pytest.raises(ValueError, match="checksum-verified"):
        proof.main()


def test_dirty_source_refusal_precedes_cluster_creation(tmp_path, monkeypatch):
    arguments(tmp_path, monkeypatch)
    tool_digests(monkeypatch)
    monkeypatch.setattr(
        proof, "source_identity", lambda root: (_ for _ in ()).throw(ValueError("freeze"))
    )
    monkeypatch.setattr(proof, "owned_cluster", lambda *args, **kwargs: pytest.fail("cluster"))
    with pytest.raises(ValueError, match="freeze"):
        proof.main()


@pytest.mark.parametrize("failure", [None, "verify", "cleanup", "source"])
def test_main_preserves_actual_result_and_cleanup_failure_without_private_details(
    tmp_path, monkeypatch, failure
):
    _, kubectl, evidence = arguments(tmp_path, monkeypatch)
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

    async def verify(actual, progress, tool):
        assert actual is cluster and tool == kubectl and progress["status"] == "failed"
        events.append("verify")
        if failure == "verify":
            raise RuntimeError("synthetic-private-server-receipt")
        return {"checks": ["owned-fixture-behavior"]}

    hashes = iter([{"fixture": "a" * 64}, {"fixture": ("b" if failure == "source" else "a") * 64}])
    monkeypatch.setattr(proof, "owned_cluster", owned)
    monkeypatch.setattr(proof, "verify", verify)
    monkeypatch.setattr(proof, "source_identity", lambda root: "1" * 40)
    monkeypatch.setattr(proof, "input_hashes", lambda root: next(hashes))
    tool_digests(monkeypatch)
    if failure:
        with pytest.raises(
            {"verify": RuntimeError, "cleanup": ValueError, "source": AssertionError}[failure]
        ):
            proof.main()
    else:
        proof.main()
    result = json.loads(evidence.read_text())
    assert events == ["create", "verify", "delete"]
    assert result["status"] == ("failed" if failure else "passed")
    assert result["owned_cluster_deleted"] is (failure != "cleanup")
    assert result["private_directory_deleted"] is (failure != "cleanup")
    assert "synthetic-private" not in evidence.read_text()


def test_source_identity_requires_clean_committed_inputs(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["cwd"] == tmp_path and kwargs["check"] and kwargs["timeout"] == 10
        return subprocess.CompletedProcess(
            argv, 0, stdout="f" * 40 + "\n" if "rev-parse" in argv else b""
        )

    monkeypatch.setattr(proof.subprocess, "run", run)
    assert proof.source_identity(tmp_path) == "f" * 40
    assert len(calls) == 2
    monkeypatch.setattr(
        proof.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"?? proof.py\n")
    )
    with pytest.raises(ValueError, match="freeze"):
        proof.source_identity(tmp_path)


def test_hash_binding_includes_assets_locks_tool_constants_and_proof_support(tmp_path):
    source = tmp_path / "src/kuberich"
    source.mkdir(parents=True)
    (source / "module.py").write_text("value=1\n")
    (source / "styles.tcss").write_text("Screen {}\n")
    (source / "__pycache__").mkdir()
    (source / "__pycache__/ignore.pyc").write_bytes(b"ignored")
    for name in proof.PROOF_INPUTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    hashes = proof.input_hashes(tmp_path)
    assert len(hashes) == len(proof.PROOF_INPUTS) + 2
    assert "src/kuberich/styles.tcss" in hashes
    path = tmp_path / "scripts/diagnostics_tools.py"
    path.write_text("changed-tool-constant")
    assert proof.input_hashes(tmp_path) != hashes


@pytest.mark.asyncio
async def test_wait_requires_an_observation_and_has_a_finite_deadline():
    calls = 0

    async def ready():
        nonlocal calls
        calls += 1
        return calls == 2

    await proof.wait_for(ready, seconds=1)
    assert calls == 2

    async def held():
        await asyncio.Event().wait()
        return False

    with pytest.raises(TimeoutError):
        await proof.wait_for(held, seconds=0.01)
    assert proof.VERIFY_SECONDS <= 600


@asynccontextmanager
async def server(handler, *, tls=None):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("drop", [False, True])
async def test_proxy_observes_exact_commit_once_and_lost_receipt_without_recording_credentials(
    tmp_path, drop
):
    committed, requests = [], []

    async def api(request):
        requests.append(
            (
                request.method,
                await request.read(),
                request.headers.get("Content-Type"),
                request.headers.get("Impersonate-User"),
            )
        )
        if request.method == "GET":
            return web.json_response({"resources": []})
        value = json.loads(requests[-1][1])
        if request.query.get("dryRun") != "All":
            committed.append(value[-1]["value"][0]["name"])
        return web.json_response({"accepted": True})

    tls, credentials = certificate(tmp_path, client_auth=True)
    user = {key: value for key, value in credentials.items() if key.startswith("client-")}
    cluster = {"certificate-authority-data": credentials["certificate-authority-data"]}
    async with server(api, tls=tls) as endpoint:
        upstream = KubernetesSession(
            catalog_fixture(tmp_path, endpoint, user, cluster).select("kuberich-test-one"), 2
        )
        await upstream.open()
        try:
            async with proof.observed_client(upstream, as_user="owned-reader") as (client, proxy):
                assert await client.get_json("/api/v1") == {"resources": []}
                assert requests == [("GET", b"", None, "owned-reader")]
                if drop:
                    proxy.drop_name = "debug-one"
                body = [
                    {"op": "test", "path": "/metadata/uid", "value": "pod-uid"},
                    {"op": "test", "path": "/metadata/resourceVersion", "value": "opaque/rv"},
                    {
                        "op": "add",
                        "path": "/spec/ephemeralContainers",
                        "value": [{"name": "debug-one"}],
                    },
                ]
                async with aiohttp.ClientSession() as caller:
                    invocation = caller.patch(
                        str(client.configuration.host)
                        + "/api/v1/namespaces/team/pods/one/ephemeralcontainers",
                        json=body,
                        params={"fieldValidation": "Strict"},
                        headers={
                            "Content-Type": "application/json-patch+json",
                            "Authorization": "Bearer synthetic-private-token",
                        },
                    )
                    if drop:
                        with pytest.raises(aiohttp.ServerDisconnectedError):
                            async with invocation as response:
                                await response.read()
                    else:
                        async with invocation as response:
                            assert response.status == 200
                            await response.read()
                assert committed == ["debug-one"] and len(requests) == 2
                receipt = proxy.receipts[-1]
                assert receipt["uid"] == "pod-uid" and receipt["resource_version"] == "opaque/rv"
                assert receipt["strict"] and receipt["status"] == 200 and not receipt["dry_run"]
                assert ("owned_fault" in receipt) is drop
                assert "synthetic-private" not in json.dumps(proxy.receipts)
        finally:
            await upstream.close()


@pytest.mark.asyncio
async def test_websocket_relay_preserves_protocol_input_output_and_closes_both_directions():
    async def api(request):
        ws = web.WebSocketResponse(protocols=("v5.channel.k8s.io",))
        await ws.prepare(request)
        message = await ws.receive()
        assert message.data == b"\x00owned-input"
        await ws.send_bytes(b"\x01owned-output")
        await ws.close()
        return ws

    async with server(api) as endpoint, aiohttp.ClientSession() as upstream:
        proxy = proof.DebugProxy(upstream, endpoint)
        async with server(proxy.handle) as local:
            async with upstream.ws_connect(
                local + "/api/v1/namespaces/team/pods/one/attach", protocols=("v5.channel.k8s.io",)
            ) as ws:
                assert ws.protocol == "v5.channel.k8s.io"
                await ws.send_bytes(b"\x00owned-input")
                assert (await ws.receive()).data == b"\x01owned-output"
            assert proxy.receipts == [
                {
                    "method": "GET",
                    "path": "/api/v1/namespaces/team/pods/one/attach",
                    "status": 101,
                    "transport": "websocket",
                }
            ]


@pytest.mark.asyncio
async def test_discovery_relay_preserves_negotiated_aggregated_content_type_exactly():
    negotiated = "application/json;g=apidiscovery.k8s.io;v=v2;as=APIGroupDiscoveryList"
    received = []

    async def api(request):
        received.append((request.path, request.headers["Accept"], await request.read()))
        return web.Response(
            body=b'{"apiVersion":"apidiscovery.k8s.io/v2","kind":"APIGroupDiscoveryList","items":[]}',
            headers={"Content-Type": negotiated},
        )

    async with server(api) as endpoint, aiohttp.ClientSession() as upstream:
        proxy = proof.DebugProxy(upstream, endpoint)
        async with (
            server(proxy.handle) as local,
            upstream.get(local + "/apis", headers={"Accept": negotiated}) as response,
        ):
            assert response.headers["Content-Type"] == negotiated
            assert (await response.json())["kind"] == "APIGroupDiscoveryList"
        assert received == [("/apis", negotiated, b"")]


@pytest.mark.asyncio
async def test_terminal_proof_accepts_no_prompt_and_confines_completion_monitor_cancellation(
    tmp_path,
):
    helper = tmp_path / "owned-helper.py"
    exited = tmp_path / "remote-completed"
    helper.write_text(
        "import os,sys,time,tty\n"
        "from pathlib import Path\n"
        "tty.setraw(0)\n"
        "data=b''\n"
        "while True:\n"
        " data+=os.read(0,4096)\n"
        " if b'printf' in data:\n"
        "  os.write(1,b'OWNED-DEBUG-COMPLETE\\r\\n');data=b''\n"
        " if b'exit 7' in data:\n"
        f"  Path({str(exited)!r}).write_text('terminated');time.sleep(.1);sys.exit(7)\n"
    )
    path = tmp_path / "delegated-config"
    command = capture_command(
        (sys.executable, str(helper), "--context=owned", "--namespace=owned", "attach"),
        environment=dict(os.environ),
        directory=tmp_path,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.ATTACH,
    )

    class Terminal:
        def require_current(self):
            pass

        @asynccontextmanager
        async def stage(self, request):
            owner = asyncio.current_task()
            path.write_text("owned-synthetic-config")

            async def monitor():
                while not exited.exists():
                    await asyncio.sleep(0.001)
                owner.cancel()

            task = asyncio.create_task(monitor())
            try:
                yield command
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                path.unlink()

    class Service:
        async def prepare_shell(self, name):
            assert name == "debug-complete"
            return Terminal(), SimpleNamespace(path=path)

    progress = {}
    result = await proof.terminal_trial(
        Service(), "debug-complete", detach=False, progress=progress
    )
    assert result["returncode"] == 7 and result["process_reaped"]
    assert progress["terminal_attempts"][0]["completion_monitor_cancelled"]
    assert not path.exists() and not asyncio.current_task().cancelling()
