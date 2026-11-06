"""Owned-kind fixture, receipt, prerequisite and cleanup verification contracts."""

import asyncio
import base64
import copy
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiohttp import web
from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import HttpProblem
from kuberich.domain.container_inspection import ContainerIdentity
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.container_inspection import ContainerInspectionService
from kuberich.services.resources import ResourceReader
from scripts import verify_container_inspection_kind as verification
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE
from tests.support.connections import catalog_fixture
from tests.support.container_inspection import (
    NAMESPACE,
    POD_NAME,
    POD_PATH,
    POD_UID,
    descriptor,
    discovery,
    inspection_api,
)


def test_fixture_declares_real_ordered_sources_secret_storage_and_each_container_family():
    manifests = verification.fixture_manifests()
    assert len([value for value in manifests if value["kind"] == "Namespace"]) == 1
    pod = next(value for value in manifests if value["kind"] == "Pod")
    spec = pod["spec"]
    assert spec["automountServiceAccountToken"] is False
    assert spec["terminationGracePeriodSeconds"] == 0
    app = spec["containers"][0]
    assert [
        value.get("configMapRef", value.get("secretRef"))["name"] for value in app["envFrom"]
    ] == [
        verification.CONFIG,
        verification.SECOND_CONFIG,
        verification.SECRET,
        verification.MISSING,
    ]
    assert app["envFrom"][-1]["configMapRef"]["optional"] is True
    assert app["envFrom"][2]["prefix"] == "PFX_"
    assert [value["name"] for value in app["env"]][:3] == ["ORDER", "SNAP", "ESCAPED"]
    assert (
        next(value for value in app["env"] if value["name"] == "SNAP")["value"]
        == "$(BASE)/$(ORDER)/$(PFX_ORDER)"
    )
    assert app["resources"]["limits"] == {"cpu": "250m", "memory": "32Mi"}
    assert all(
        value["image"] == SHELL_IMAGE and "@sha256:" in value["image"]
        for value in [app, *spec["initContainers"], verification.ephemeral_fixture()]
    )
    assert "@sha256:" in NODE_IMAGE
    assert spec["initContainers"][0]["name"] == "init"
    assert spec["initContainers"][1]["restartPolicy"] == "Always"
    ephemeral = verification.ephemeral_fixture()
    assert ephemeral["targetContainerName"] == "app" and "resources" not in ephemeral
    secret = next(value for value in manifests if value["kind"] == "Secret")
    assert "stringData" not in secret
    assert base64.b64decode(secret["data"]["TOKEN"]) == b"fixture-synthetic-token"
    assert "TOKEN=" not in app["command"][-1]
    assert not any(value["metadata"]["name"] == verification.MISSING for value in manifests)


def test_fixture_restricted_identity_can_get_named_pod_configs_but_never_secrets_or_logs():
    manifests = verification.fixture_manifests()
    role = next(value for value in manifests if value["kind"] == "Role")
    assert {resource for rule in role["rules"] for resource in rule["resources"]} == {
        "pods",
        "configmaps",
    }
    assert all(
        rule["verbs"] == ["get"] and rule["apiGroups"] == [""] and rule["resourceNames"]
        for rule in role["rules"]
    )
    binding = next(value for value in manifests if value["kind"] == "RoleBinding")
    assert binding["subjects"] == [
        {"apiGroup": "rbac.authorization.k8s.io", "kind": "User", "name": verification.READER}
    ]
    assert binding["roleRef"]["name"] == role["metadata"]["name"]


@pytest.mark.asyncio
async def test_receipts_observe_actual_http_caps_and_403_without_payload_or_credentials(tmp_path):
    async with inspection_api() as (url, api):
        client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
        await client.open()
        receipts = []
        try:
            with verification.inspection_receipts(receipts):
                reader = ResourceReader(client)
                record = await reader.get(descriptor("Pod"), POD_NAME, NAMESPACE, max_bytes=32000)
                assert record.uid == POD_UID
                api.statuses[POD_PATH] = 403
                with pytest.raises(HttpProblem):
                    await reader.get(descriptor("Pod"), POD_NAME, NAMESPACE, max_bytes=64000)
            assert receipts == [
                {"method": "GET", "path": POD_PATH, "max_bytes": 32000, "status": 200},
                {"method": "GET", "path": POD_PATH, "max_bytes": 64000, "status": 403},
            ]
            assert "inspection-private-server-body" not in json.dumps(receipts)
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_selected_verifier_checks_real_service_resolution_and_unresolved_source(tmp_path):
    async with inspection_api() as (url, api):
        client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
        await client.open()
        service = ContainerInspectionService(
            client,
            descriptor("Pod"),
            ResourceTarget(
                SessionIdentity("kuberich-test-one", 1), "", "pods", NAMESPACE, POD_NAME, POD_UID
            ),
            ContainerIdentity("containers", "app", "App"),
            discovery(),
            AccessPolicy(True),
            lambda: True,
            now=lambda: datetime.now(UTC),
        )
        try:
            snapshot = await service.index()
            assert await verification.selected(service, snapshot, "LITERAL") == "synthetic-literal"
            source_path = f"/api/v1/namespaces/{NAMESPACE}/secrets/inspection-secret"
            api.statuses[source_path] = 403
            snapshot = await service.index()
            with pytest.raises(AssertionError, match="unresolved"):
                await verification.selected(service, snapshot, "CHOSEN")
        finally:
            await verification.close_owned([service], [client])
        assert service.operation_count == 0


@pytest.mark.asyncio
async def test_actual_owned_http_serves_the_kind_declarations_and_expected_resolution_vectors(
    tmp_path,
):
    async with inspection_api() as (url, api):
        api.records.clear()
        for manifest in verification.fixture_manifests():
            if manifest["kind"] not in {"Pod", "ConfigMap", "Secret"}:
                continue
            value = copy.deepcopy(manifest)
            metadata = value["metadata"]
            metadata.update(
                namespace=NAMESPACE,
                uid=metadata["name"] + "-uid",
                resourceVersion="fixture-version",
            )
            if value["kind"] == "Pod":
                metadata.update(name=POD_NAME, uid=POD_UID)
            api.records[descriptor(value["kind"]).path(NAMESPACE) + "/" + metadata["name"]] = value
        client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
        await client.open()
        service = ContainerInspectionService(
            client,
            descriptor("Pod"),
            ResourceTarget(
                SessionIdentity("kuberich-test-one", 1), "", "pods", NAMESPACE, POD_NAME, POD_UID
            ),
            ContainerIdentity("containers", "app", "App"),
            discovery(),
            AccessPolicy(True),
            lambda: True,
            now=lambda: datetime.now(UTC),
        )
        try:
            snapshot = await service.index()
            expected = {
                "BASE": "base-start",
                "ORDER": "explicit",
                "PFX_ORDER": "secret-order",
                "SNAP": "base-start/explicit/secret-order",
                "ESCAPED": "$(BASE)",
                "TOKEN": "fixture-synthetic-token",
                "POD_NAME": POD_NAME,
                "LABEL": "fixture-owned",
                "CPU_MILLI": "250",
                "MEMORY_MIB": "32",
            }
            for name, value in expected.items():
                assert await verification.selected(service, snapshot, name) == value
            assert snapshot.reads == 6
            assert len(api.requests) == 66
        finally:
            await verification.close_owned([service], [client])


@pytest.mark.asyncio
async def test_cleanup_finishes_all_services_before_any_client_even_when_service_failed():
    order = []

    async def service_close():
        await asyncio.sleep(0)
        order.append("service")
        raise ValueError("synthetic-close-failure")

    async def client_close():
        assert order == ["service"]
        order.append("client")

    with pytest.raises(AssertionError, match="cleanup failed"):
        await verification.close_owned(
            [SimpleNamespace(close=service_close)], [SimpleNamespace(close=client_close)]
        )
    assert order == ["service", "client"]


@pytest.mark.asyncio
async def test_finite_wait_succeeds_after_observation_and_fails_on_owned_deadline():
    calls = []

    async def eventually():
        calls.append(True)
        return len(calls) == 2

    await verification.until(eventually, timeout=1)
    assert len(calls) == 2

    async def never():
        return False

    with pytest.raises(TimeoutError):
        await verification.until(never, timeout=0.01)


def test_main_refuses_unverified_tools_or_existing_evidence_before_cluster_creation(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "receipt.json"
    kind = tmp_path / "kind"
    kind.write_bytes(b"unverified-tool")
    monkeypatch.setattr(sys, "argv", ["verify", "--kind", str(kind), "--evidence", str(evidence)])

    def forbidden(*args, **kwargs):
        raise AssertionError("Cluster creation must not start")

    monkeypatch.setattr(verification, "owned_cluster", forbidden)
    with pytest.raises(ValueError, match="checksum-verified"):
        verification.main()
    evidence.write_text("preserve-original")
    with pytest.raises(ValueError, match="fresh evidence"):
        verification.main()
    assert evidence.read_text() == "preserve-original"


def test_input_hashes_pin_product_and_owned_cluster_source(tmp_path):
    root = tmp_path / "fixture-root"
    paths = [
        "src/kuberich/domain/container_inspection.py",
        "src/kuberich/services/container_inspection.py",
        "scripts/verify_container_inspection_kind.py",
        "scripts/owned_kind.py",
        "pyproject.toml",
        "uv.lock",
    ]
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    before = verification.input_hashes(root)
    assert set(before) == set(paths)
    (root / paths[0]).write_text("changed")
    assert verification.input_hashes(root) != before


def test_main_records_failure_only_after_owned_cluster_cleanup_and_preserves_safe_receipts(
    tmp_path, monkeypatch
):
    kind, evidence = tmp_path / "kind", tmp_path / "result.json"
    kind.write_bytes(b"verified-by-fixture")
    monkeypatch.setattr(sys, "argv", ["verify", "--kind", str(kind), "--evidence", str(evidence)])
    monkeypatch.setattr(verification, "sha256_file", lambda path: verification.KIND_SHA256)
    inputs = {"fixture": "fixed"}
    monkeypatch.setattr(verification, "input_hashes", lambda root: copy.deepcopy(inputs))
    state = []
    cluster = SimpleNamespace(name="kuberich-test-owned", directory=tmp_path / "deleted-private")

    @contextmanager
    def owned(*args, **kwargs):
        state.append("created")
        try:
            yield cluster
        finally:
            state.append("deleted")

    async def failed(*args, progress):
        state.append("verified")
        progress.update(
            phase="creating-Pod",
            last_write={"method": "POST", "path": "/api/v1/namespaces/owned/pods"},
        )
        raise RuntimeError("synthetic-private-failure")

    monkeypatch.setattr(verification, "owned_cluster", owned)
    monkeypatch.setattr(verification, "verify", failed)
    with pytest.raises(RuntimeError):
        verification.main()
    assert state == ["created", "verified", "deleted"]
    result = json.loads(evidence.read_text())
    assert result["status"] == "failed" and result["owned_cluster_deleted"] is True
    assert result["private_directory_deleted"] is True and result["failure_type"] == "RuntimeError"
    assert result["phase"] == "creating-Pod" and result["last_write"]["method"] == "POST"
    assert "synthetic-private-failure" not in evidence.read_text()


@pytest.mark.asyncio
async def test_real_failed_fixture_write_records_status_schema_without_raw_body_or_values(tmp_path):
    path = f"/api/v1/namespaces/{NAMESPACE}/pods"
    status = {
        "apiVersion": "v1",
        "kind": "Status",
        "status": "Failure",
        "reason": "Invalid",
        "message": "raw-private-server-message",
        "details": {
            "name": "private-object-value",
            "causes": [
                {
                    "reason": "FieldValueInvalid",
                    "field": "spec.containers[0].env[6].valueFrom.resourceFieldRef.divisor",
                    "message": "private-invalid-value",
                },
                {
                    "reason": "private-unknown-type",
                    "field": "metadata.annotations[private-map-value]",
                    "message": "private-cause-message",
                },
            ],
        },
        "code": 422,
    }
    ledger = []

    async def handle(request):
        ledger.append((request.method, request.path))
        await request.json()
        return web.json_response(status, status=422)

    app = web.Application()
    app.router.add_post(path, handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
    progress = {"phase": "creating-Pod"}
    try:
        await client.open()
        with pytest.raises(ApiException):
            await verification.write_owned(
                client.api, path, {"metadata": {"name": "owned"}}, "POST", progress
            )
        assert ledger == [("POST", path)]
        assert progress == {
            "phase": "creating-Pod",
            "last_write": {"method": "POST", "path": path, "state": "failed"},
            "api_failure": {
                "http_status": 422,
                "reason": "Invalid",
                "causes": [
                    {
                        "type": "FieldValueInvalid",
                        "field": "spec.containers[0].env[6].valueFrom.resourceFieldRef.divisor",
                    },
                    {"type": "unrecognized", "field": "(field omitted)"},
                ],
            },
        }
        assert "private" not in json.dumps(progress)
    finally:
        await client.close()
        await runner.cleanup()


@pytest.mark.parametrize("body", [None, "not-json", "[]", '{"kind":"Other"}', "x" * 65537])
def test_non_status_or_excessive_error_bodies_never_enter_failure_evidence(body):
    error = ApiException(status=409)
    error.body = body
    assert verification.status_diagnostic(error) == {
        "http_status": 409,
        "reason": None,
        "causes": [],
    }


def test_unknown_reason_and_excessive_cause_count_are_bounded_without_value_echo():
    error = ApiException(status=422)
    error.body = json.dumps(
        {
            "kind": "Status",
            "reason": "raw-private-reason",
            "details": {
                "causes": [
                    {
                        "reason": "FieldValueRequired",
                        "field": "metadata.name",
                        "message": "raw-private-value",
                    }
                ]
                * 20
            },
        }
    )
    result = verification.status_diagnostic(error)
    assert result["reason"] == "unrecognized" and len(result["causes"]) == 16
    assert result["causes"][0] == {"type": "FieldValueRequired", "field": "metadata.name"}
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_ephemeral_fixture_uses_one_minimal_uid_bound_strategic_patch_and_rejects_replacement(
    tmp_path,
):
    path = (
        f"/api/v1/namespaces/{verification.NAMESPACE}/pods/{verification.POD}/ephemeralcontainers"
    )
    uid = "owned-pod-current-uid"
    ledger = []

    async def handle(request):
        body = await request.json()
        ledger.append((request.method, request.path, request.content_type, body))
        assert request.content_type == "application/strategic-merge-patch+json"
        assert set(body) == {"metadata", "spec"}
        assert set(body["metadata"]) == {"uid"}
        assert set(body["spec"]) == {"ephemeralContainers"}
        if body["metadata"]["uid"] != uid:
            return web.json_response(
                {
                    "kind": "Status",
                    "reason": "Conflict",
                    "details": {
                        "causes": [
                            {
                                "reason": "FieldValueInvalid",
                                "field": "metadata.uid",
                                "message": "private-replacement-detail",
                            }
                        ]
                    },
                },
                status=409,
            )
        return web.json_response({"apiVersion": "v1", "kind": "Pod", "metadata": {"uid": uid}})

    app = web.Application()
    app.router.add_patch(path, handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
    progress = {"phase": "adding-precreated-ephemeral"}
    try:
        await client.open()
        result = await verification.write_owned(
            client.api,
            path,
            verification.ephemeral_patch(uid),
            "PATCH",
            progress,
            content_type="application/strategic-merge-patch+json",
        )
        assert result["metadata"]["uid"] == uid and progress["last_write"]["state"] == "completed"
        assert ledger[0] == (
            "PATCH",
            path,
            "application/strategic-merge-patch+json",
            {
                "metadata": {"uid": uid},
                "spec": {"ephemeralContainers": [verification.ephemeral_fixture()]},
            },
        )
        with pytest.raises(ApiException):
            await verification.write_owned(
                client.api,
                path,
                verification.ephemeral_patch("different-owned-uid"),
                "PATCH",
                progress,
                content_type="application/strategic-merge-patch+json",
            )
        assert len(ledger) == 2  # A failed UID guard is never retried.
        assert progress["api_failure"] == {
            "http_status": 409,
            "reason": "Conflict",
            "causes": [{"type": "FieldValueInvalid", "field": "metadata.uid"}],
        }
        assert "private-replacement-detail" not in json.dumps(progress)
    finally:
        await client.close()
        await runner.cleanup()


@pytest.mark.parametrize("uid", [None, "", "x" * 4097, "bad\nuid"])
def test_ephemeral_patch_requires_a_captured_bounded_uid(uid):
    with pytest.raises(ValueError, match="owned Pod UID"):
        verification.ephemeral_patch(uid)
