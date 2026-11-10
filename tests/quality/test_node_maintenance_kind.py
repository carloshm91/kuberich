"""Owned node-maintenance proof refuses unbound tools and retains exact failures."""

import asyncio
import json
import sys
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.mutations import MutationState
from kuberich.domain.node_maintenance import MaintenanceMode, PodState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.node_maintenance import NodeMaintenanceService
from scripts import verify_node_maintenance_kind as rehearsal
from tests.support.connections import catalog_fixture, certificate
from tests.support.node_maintenance import DISCOVERY, NODE, MaintenanceApi


@asynccontextmanager
async def maintenance_server(api, tls=None):
    from aiohttp import web

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", api.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        await runner.cleanup()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("drop", [False, True])
async def test_owned_mutual_tls_forwarder_preserves_conditions_and_postcommit_uncertainty(
    tmp_path, drop
):
    api = MaintenanceApi()
    api.success_status = 201
    tls, credentials = certificate(tmp_path, client_auth=True)
    user = {key: value for key, value in credentials.items() if key.startswith("client-")}
    cluster = {"certificate-authority-data": credentials["certificate-authority-data"]}
    async with maintenance_server(api, tls=tls) as endpoint:
        upstream = KubernetesSession(
            catalog_fixture(tmp_path, endpoint, user, cluster).select("kuberich-test-one"), 2
        )
        await upstream.open()
        try:
            async with rehearsal.observed_client(upstream, as_user="owned-reader") as (
                client,
                proxy,
            ):
                target = ResourceTarget(
                    SessionIdentity("kuberich-test-one", 1),
                    "",
                    "nodes",
                    None,
                    "node-one",
                    "node-uid",
                )
                source = NodeMaintenanceService(
                    client, NODE, target, DISCOVERY, AccessPolicy(False), lambda: True
                )
                try:
                    review = await source.prepare(MaintenanceMode.DRAIN)
                    if drop:
                        proxy.drop_uid = review.pods[0].target.uid
                    result = await source.execute(source.confirm(review))
                    assert result.state is (
                        MutationState.UNCERTAIN if drop else MutationState.SUCCEEDED
                    )
                    assert source.progress.pods[0].state is (
                        PodState.UNCERTAIN if drop else PodState.ABSENT
                    )
                    assert api.pods == []
                    writes = [item for item in proxy.receipts if item["method"] != "GET"]
                    assert [item["method"] for item in writes] == ["PATCH", "POST"]
                    assert api.requests[0][3]["Content-Type"] == "application/json-patch+json"
                    assert api.requests[1][3]["Content-Type"] == "application/json"
                    assert writes[1]["status"] == 201 and writes[1]["normal_grace"]
                    assert writes[1]["preconditions"] == {
                        "uid": "pod-one",
                        "resourceVersion": "opaque/pod-one",
                    }
                    assert all(
                        request[3].get("Impersonate-User") == "owned-reader"
                        for request in api.requests
                    )
                    assert "Authorization" not in json.dumps(proxy.receipts)
                    if drop:
                        assert (
                            writes[1]["owned_fault"] == "post-commit-response-loss"
                            and proxy.drop_uid is None
                        )
                finally:
                    await source.close()
        finally:
            await upstream.close()


@pytest.mark.asyncio
async def test_forwarded_get_discovery_keeps_no_body_or_content_type(tmp_path):
    from aiohttp import web

    class DiscoveryApi:
        def __init__(self):
            self.requests = []

        async def handle(self, request):
            body = await request.read()
            self.requests.append(
                (
                    request.method,
                    body,
                    request.headers.get("Content-Type"),
                    request.headers.get("Accept"),
                )
            )
            return web.json_response(
                {"resources": []},
                status=415 if request.headers.get("Content-Type") or body else 200,
            )

    api = DiscoveryApi()
    tls, credentials = certificate(tmp_path, client_auth=True)
    user = {key: value for key, value in credentials.items() if key.startswith("client-")}
    cluster = {"certificate-authority-data": credentials["certificate-authority-data"]}
    async with maintenance_server(api, tls=tls) as endpoint:
        upstream = KubernetesSession(
            catalog_fixture(tmp_path, endpoint, user, cluster).select("kuberich-test-one"), 2
        )
        await upstream.open()
        try:
            async with rehearsal.observed_client(upstream) as (client, proxy):
                assert await client.get_json("/api/v1") == {"resources": []}
                assert proxy.receipts == [{"method": "GET", "path": "/api/v1", "status": 200}]
        finally:
            await upstream.close()
    assert api.requests == [("GET", b"", None, "application/json")]


@pytest.mark.asyncio
async def test_forwarded_refusal_retains_retry_after_without_exposing_headers(tmp_path):
    import aiohttp
    from aiohttp import web

    api = MaintenanceApi()
    api.statuses["one"] = [429]
    api.retry_after = "37"
    async with maintenance_server(api) as endpoint, aiohttp.ClientSession() as upstream:
        proxy = rehearsal.MaintenanceProxy(upstream, endpoint)
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", proxy.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            async with upstream.post(
                f"http://127.0.0.1:{runner.addresses[0][1]}/api/v1/namespaces/team/pods/one/eviction",
                json={
                    "deleteOptions": {
                        "preconditions": {"uid": "pod-one", "resourceVersion": "opaque/pod-one"}
                    }
                },
                headers={"Authorization": "Bearer synthetic-private-token"},
            ) as response:
                await response.read()
                assert response.status == 429 and response.headers["Retry-After"] == "37"
            assert "synthetic-private" not in json.dumps(proxy.receipts)
            assert len(proxy.receipts) == 1
        finally:
            await runner.cleanup()
