"""Owned verifier failure receipts, source freezing and bounded forwarding ownership."""

import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from scripts import verify_manifests_kind as verifier
from scripts.owned_kind import OwnedCluster


def controlled_run(tmp_path, monkeypatch):
    root = tmp_path / "source"
    for relative in (
        "src/kuberich/unimported.py",
        "scripts/verify_manifests_kind.py",
        "scripts/owned_kind.py",
        "scripts/diagnostics_tools.py",
        "pyproject.toml",
        "uv.lock",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("owned-original\n")
    kind, kubectl = tmp_path / "kind", tmp_path / "kubectl"
    kind.write_bytes(b"controlled-kind")
    kubectl.write_bytes(b"controlled-kubectl")
    kind.chmod(0o700)
    kubectl.chmod(0o700)
    monkeypatch.setattr(verifier, "KIND_SHA256", hashlib.sha256(kind.read_bytes()).hexdigest())
    monkeypatch.setattr(
        verifier, "KUBECTL_SHA256", hashlib.sha256(kubectl.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(verifier.sys, "platform", "linux")
    monkeypatch.setattr(verifier.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        verifier, "capture_docker", lambda docker: {"DOCKER_HOST": "unix:///owned-fixture.sock"}
    )
    monkeypatch.setattr(verifier, "run_owned", lambda *args, **kwargs: "")
    cluster_path = tmp_path / "cluster-config"
    cluster_path.write_bytes(b"synthetic-private-fixture")
    lifecycle = []

    @contextmanager
    def cluster(*args, **kwargs):
        lifecycle.append("opened")
        try:
            yield OwnedCluster(
                "kuberich-test-controlled", cluster_path, tmp_path, "kind-owned", ("owned-node",)
            )
        finally:
            lifecycle.append("cleaned")

    monkeypatch.setattr(verifier, "owned_cluster", cluster)
    args = argparse.Namespace(
        kind=kind, kubectl=kubectl, docker="owned-docker", evidence=tmp_path / "evidence.json"
    )
    return root, args, lifecycle


def test_verifier_retains_failure_and_cleanup_truth_without_sensitive_exception_text(
    tmp_path, monkeypatch, capsys
):
    root, args, lifecycle = controlled_run(tmp_path, monkeypatch)

    async def failed(cluster, kubectl, report):
        report["checks"].append("completed-before-failure")
        raise RuntimeError("synthetic-private-credential-from-exception")

    monkeypatch.setattr(verifier, "verify", failed)
    assert verifier.run(args, root) == 1
    report = json.loads(args.evidence.read_text())
    assert report["status"] == "failed" and report["error_type"] == "RuntimeError"
    assert report["owned_cluster_deleted"] and report["source_unchanged"]
    assert report["checks"] == ["completed-before-failure"] and lifecycle == ["opened", "cleaned"]
    assert "private" not in args.evidence.read_text() + capsys.readouterr().out
    assert args.evidence.stat().st_mode & 0o777 == 0o600


def test_frozen_input_change_fails_even_after_behavior_completed_and_cluster_cleaned(
    tmp_path, monkeypatch
):
    root, args, lifecycle = controlled_run(tmp_path, monkeypatch)

    async def changed(cluster, kubectl, report):
        (root / "src/kuberich/unimported.py").write_text("changed during measurement\n")
        report["checks"].append("behavior-finished")

    monkeypatch.setattr(verifier, "verify", changed)
    assert verifier.run(args, root) == 1
    report = json.loads(args.evidence.read_text())
    assert report["status"] == "failed" and not report["source_unchanged"]
    assert report["owned_cluster_deleted"] and lifecycle[-1] == "cleaned"


def test_success_is_impossible_when_cluster_absence_cannot_be_verified(tmp_path, monkeypatch):
    root, args, _ = controlled_run(tmp_path, monkeypatch)

    async def completed(cluster, kubectl, report):
        report["checks"].append("controlled-fixture-completed")

    monkeypatch.setattr(verifier, "verify", completed)
    monkeypatch.setattr(verifier, "run_owned", lambda *args, **kwargs: "owned-node-still-present\n")
    assert verifier.run(args, root) == 1
    report = json.loads(args.evidence.read_text())
    assert report["status"] == "failed" and not report["owned_cluster_deleted"]
    assert report["source_unchanged"]


def test_existing_evidence_is_never_overwritten_or_requalified(tmp_path, monkeypatch):
    root, args, lifecycle = controlled_run(tmp_path, monkeypatch)
    args.evidence.write_bytes(b"original-failure-receipt\n")
    with pytest.raises(FileExistsError):
        verifier.run(args, root)
    assert args.evidence.read_bytes() == b"original-failure-receipt\n" and not lifecycle


@pytest.mark.parametrize("change", ["wrong-digest", "relative", "symlink"])
def test_tool_validation_fails_before_any_cluster_is_created(tmp_path, monkeypatch, change):
    root, args, lifecycle = controlled_run(tmp_path, monkeypatch)
    if change == "wrong-digest":
        args.kubectl.write_bytes(b"different-unverified-tool")
    elif change == "relative":
        args.kubectl = Path("relative-kubectl")
    else:
        link = tmp_path / "tool-link"
        link.symlink_to(args.kubectl)
        args.kubectl = link
    assert verifier.run(args, root) == 1
    report = json.loads(args.evidence.read_text())
    assert report["status"] == "failed" and report["error_type"] == "ValueError"
    assert not lifecycle and not report["owned_cluster_deleted"]


def test_source_inventory_includes_unimported_new_modules_and_rejects_links(tmp_path):
    source = tmp_path / "src/kuberich"
    source.mkdir(parents=True)
    path = source / "unimported.py"
    path.write_bytes(b"first")
    first = verifier.input_hashes(tmp_path)
    assert first == {"src/kuberich/unimported.py": hashlib.sha256(b"first").hexdigest()}
    path.write_bytes(b"changed")
    assert verifier.input_hashes(tmp_path) != first
    (source / "link.py").symlink_to(path)
    with pytest.raises(ValueError, match="never links"):
        verifier.input_hashes(tmp_path)


@asynccontextmanager
async def backend_fixture(handler):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield "http://127.0.0.1:" + str(runner.addresses[0][1])
    finally:
        await runner.cleanup()


def healthy_client(session, url):
    return SimpleNamespace(
        api=SimpleNamespace(rest_client=SimpleNamespace(pool_manager=session)),
        configuration=SimpleNamespace(host=url, tls_server_name=None),
        impersonation=(),
        authorization_header=lambda: None,
        request_proxy=None,
    )


@pytest.mark.asyncio
async def test_fault_barrier_occurs_only_after_backend_commit_and_never_replays_request():
    commits = []

    async def backend(request):
        if request.method == "PATCH" and "dryRun" not in request.query:
            commits.append(await request.read())
        return web.json_response({"committed": len(commits)})

    async with (
        backend_fixture(backend) as url,
        aiohttp.ClientSession() as transport,
        verifier.LoopbackProxy(healthy_client(transport, url)) as proxy,
    ):
        proxy.hold = True
        async with aiohttp.ClientSession() as frontend:
            async with frontend.patch(
                proxy.url + "/owned", params={"dryRun": "All"}, data=b"[]"
            ) as response:
                assert response.status == 200
            assert not commits and not proxy.committed.is_set()

            async def write():
                async with frontend.patch(proxy.url + "/owned", data=b"[]") as response:
                    return await response.read()

            operation = asyncio.create_task(write())
            await asyncio.wait_for(proxy.committed.wait(), 2)
            assert commits == [b"[]"] and not operation.done()
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
            proxy.release.set()
        assert proxy.writes == [("PATCH", "/owned", 200)] and len(commits) == 1


@pytest.mark.asyncio
async def test_delete_observation_barrier_never_holds_precondition_revalidation_or_dry_run():
    async def backend(request):
        return web.json_response({"fixture": True})

    async with (
        backend_fixture(backend) as url,
        aiohttp.ClientSession() as transport,
        verifier.LoopbackProxy(healthy_client(transport, url)) as proxy,
    ):
        proxy.hold_after_delete_read = "/owned"
        async with aiohttp.ClientSession() as frontend:
            async with frontend.get(proxy.url + "/owned") as response:
                assert response.status == 200
            async with frontend.delete(proxy.url + "/owned", params={"dryRun": "All"}) as response:
                assert response.status == 200
            assert not proxy.deletion_observed.is_set()
            async with frontend.delete(proxy.url + "/owned") as response:
                assert response.status == 200

            async def observe():
                async with frontend.get(proxy.url + "/owned") as response:
                    return await response.read()

            operation = asyncio.create_task(observe())
            await asyncio.wait_for(proxy.deletion_observed.wait(), 2)
            assert not operation.done()
            proxy.observation_release.set()
            assert await operation
        assert proxy.writes == [("DELETE", "/owned", 200)]


@pytest.mark.asyncio
async def test_proxy_bounds_backend_output_and_preserves_actual_failure_status(monkeypatch):
    async def backend(request):
        if request.path == "/oversized":
            return web.Response(body=b"x" * 129)
        return web.Response(status=409, body=b"owned-conflict")

    monkeypatch.setattr(verifier, "MAX_PROXY_BYTES", 128)
    async with (
        backend_fixture(backend) as url,
        aiohttp.ClientSession() as transport,
        verifier.LoopbackProxy(healthy_client(transport, url)) as proxy,
    ):
        async with aiohttp.ClientSession() as frontend:
            async with frontend.post(proxy.url + "/conflict") as response:
                assert response.status == 409 and await response.read() == b"owned-conflict"
            async with frontend.get(proxy.url + "/oversized") as response:
                assert response.status == 500
        assert proxy.writes == [("POST", "/conflict", 409)]


def test_cli_reports_failure_with_nonzero_exit_before_cluster_creation(tmp_path, monkeypatch):
    _, args, lifecycle = controlled_run(tmp_path, monkeypatch)
    args.kubectl.write_bytes(b"unverified")
    monkeypatch.setattr(
        verifier.sys,
        "argv",
        [
            "verify_manifests_kind",
            "--kind",
            str(args.kind),
            "--kubectl",
            str(args.kubectl),
            "--docker",
            args.docker,
            "--evidence",
            str(args.evidence),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        verifier.main()
    assert stopped.value.code == 1 and not lifecycle
    assert json.loads(args.evidence.read_text())["status"] == "failed"


def test_failure_diagnostics_omit_payloads_previews_and_control_credentials():
    from uuid import uuid4

    from kuberich.domain.manifests import (
        ManifestDocument,
        ManifestPlan,
        ManifestPlanItem,
        ManifestScope,
    )
    from kuberich.domain.mutations import MutationResult, MutationState
    from kuberich.domain.resources import ApiResource
    from kuberich.domain.targets import ResourceAddress, SessionIdentity

    session = SessionIdentity("owned", 1)
    address = ResourceAddress(session, "", "configmaps", "owned", "owned-name")
    document = ManifestDocument(
        ordinal=1,
        source_path="private-path-sentinel",
        api_version="v1",
        kind="ConfigMap",
        name="owned-name",
        namespace="owned",
        body=b"private-body-sentinel",
    )
    result = MutationResult(
        MutationState.REJECTED, "Bearer private-token-sentinel\x1b[31m" + "x" * 8192
    )
    item = ManifestPlanItem(
        document=document,
        resource=ApiResource(
            "", "v1", "configmaps", "ConfigMap", True, frozenset({"get", "create"})
        ),
        target=address,
        change="create",
        request=None,
        validation=result,
        preview_pages=("private-preview-sentinel",),
    )
    plan = ManifestPlan(
        identity=uuid4(),
        source_identity=uuid4(),
        source_sha256="source",
        scope=ManifestScope(session=session, namespace="owned"),
        action="apply",
        items=(item,) * 101,
    )
    review = verifier.review_diagnostics(plan)
    outcome = verifier.result_diagnostics(
        MutationResult(MutationState.REJECTED, result.message, ((address, result),) * 101)
    )
    encoded = json.dumps({"review": review, "outcome": outcome})
    assert len(review) == len(outcome["items"]) == 100
    assert all(len(row["safe_message"]) <= 2048 for row in review)
    assert "owned-name" in encoded and "Rejected" in encoded
    assert "private-" not in encoded and "\x1b" not in encoded


@pytest.mark.asyncio
async def test_delete_fault_proxy_observes_body_options_precedence_over_query_dry_run():
    commits = []

    async def backend(request):
        body = await request.read()
        if body:
            options = json.loads(body)
            dry = options.get("dryRun") == ["All"]
        else:
            dry = request.query.get("dryRun") == "All"
        if not dry:
            commits.append(request.method)
        return web.json_response({"dry_run": dry})

    async with (
        backend_fixture(backend) as url,
        aiohttp.ClientSession() as transport,
        verifier.LoopbackProxy(healthy_client(transport, url)) as proxy,
        aiohttp.ClientSession() as frontend,
    ):
        async with frontend.delete(
            proxy.url + "/owned", params={"dryRun": "All"}, json={"kind": "DeleteOptions"}
        ) as response:
            assert response.status == 200 and not (await response.json())["dry_run"]
        assert commits == ["DELETE"] and proxy.writes == [("DELETE", "/owned", 200)]
        async with frontend.delete(
            proxy.url + "/owned",
            params={"dryRun": "All"},
            json={"kind": "DeleteOptions", "dryRun": ["All"]},
        ) as response:
            assert response.status == 200 and (await response.json())["dry_run"]
        assert commits == ["DELETE"] and proxy.writes == [("DELETE", "/owned", 200)]
