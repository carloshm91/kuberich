"""Real local HTTP metadata negotiation, identity and pagination failure contracts."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.adapters import helm as helm_adapter
from kuberich.adapters.helm import METADATA_ACCEPT, METADATA_LIST_ACCEPT
from kuberich.domain.helm import HelmDriver, HelmProblem, HelmReleaseKey
from tests.support.helm import KEY, PRIVATE_VALUE, adapter_source, storage, storage_list


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", list(HelmDriver))
async def test_real_metadata_null_empty_slice_proves_complete_absence_only(tmp_path, driver):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        adapter.settings = replace(adapter.settings, driver=driver)
        request = replace(request, scope=replace(request.scope, driver=driver))
        page = storage_list([])
        page["items"] = None
        api.pages = [page]
        assert await adapter.storage_history(request, KEY, lambda: None) == ()
        del page["items"]
        with pytest.raises(HelmProblem):
            await adapter.storage_history(request, KEY, lambda: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [False, 0, "", {}, "malformed"])
async def test_metadata_falsy_or_malformed_items_never_prove_absence(tmp_path, items):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        page = storage_list([])
        page["items"] = items
        api.pages = [page]
        with pytest.raises(HelmProblem):
            await adapter.storage_history(request, KEY, lambda: None)
        page["items"] = None
        page["metadata"]["remainingItemCount"] = 1
        with pytest.raises(HelmProblem):
            await adapter.storage_history(request, KEY, lambda: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", list(HelmDriver))
async def test_metadata_only_get_and_complete_paginated_history_for_both_drivers(tmp_path, driver):
    async with adapter_source(tmp_path) as (adapter, client, api, request, *_):
        # Driver agreement is enforced even at the adapter boundary.
        adapter.settings = replace(adapter.settings, driver=driver)
        request = replace(request, scope=replace(request.scope, driver=driver))
        api.pages = [
            storage_list([storage(1)], continuation="1"),
            storage_list([storage(2), storage(3)]),
        ]
        identities = await adapter.storage_history(request, KEY, lambda: None)
        identity = await adapter.storage_identity(request, KEY, 3, lambda: None)
        assert [item.revision for item in identities] == [1, 2, 3] and identity == identities[-1]
        assert identity.uid == "owned-team-demo-3" and identity.resource_version == "opaque-3"
        plural = "secrets" if driver is HelmDriver.SECRET else "configmaps"
        assert [path for path, _, _ in api.requests] == [
            f"/api/v1/namespaces/team/{plural}",
            f"/api/v1/namespaces/team/{plural}",
            f"/api/v1/namespaces/team/{plural}/sh.helm.release.v1.demo.v3",
        ]
        assert api.requests[0][1] == {"labelSelector": "owner=helm,name=demo", "limit": "200"}
        assert api.requests[1][1]["continue"] == "1"
        assert [accept for _, _, accept in api.requests] == [
            METADATA_LIST_ACCEPT,
            METADATA_LIST_ACCEPT,
            METADATA_ACCEPT,
        ]
        assert not list(Path(client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,kind",
    [
        (401, "authentication"),
        (403, "forbidden"),
        (404, "missing-release"),
        (406, "unavailable"),
        (500, "unavailable"),
    ],
)
async def test_metadata_http_errors_never_fallback_or_echo_api_body(tmp_path, status, kind):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        api.status = status
        for operation in (
            lambda: adapter.storage_history(request, KEY, lambda: None),
            lambda: adapter.storage_identity(request, KEY, 3, lambda: None),
        ):
            with pytest.raises(HelmProblem) as failure:
                await operation()
            assert failure.value.kind == kind and PRIVATE_VALUE not in str(failure.value)
        assert len(api.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", ""),
        ("resourceVersion", ""),
        ("namespace", "different"),
        ("name", "sh.helm.release.v1.other.v3"),
    ],
)
async def test_identity_metadata_binding_rejects_incomplete_or_wrong_object(tmp_path, field, value):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        api.records[3]["metadata"][field] = value
        with pytest.raises(HelmProblem):
            await adapter.storage_identity(request, KEY, 3, lambda: None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("owner", "other"), ("name", "other"), ("version", "4"), ("status", "")]
)
async def test_storage_labels_must_match_exact_release_revision_owner_and_state(
    tmp_path, field, value
):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        api.records[3]["metadata"]["labels"][field] = value
        with pytest.raises(HelmProblem):
            await adapter.storage_identity(request, KEY, 3, lambda: None)


@pytest.mark.asyncio
async def test_refuse_full_secret_body_even_when_metadata_exists(tmp_path):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        api.records[3]["kind"] = "Secret"
        api.records[3]["apiVersion"] = "v1"
        api.records[3]["data"] = {"release": PRIVATE_VALUE}
        with pytest.raises(HelmProblem):
            await adapter.storage_identity(request, KEY, 3, lambda: None)
        api.pages = [{"kind": "SecretList", "apiVersion": "v1", "items": [api.records[3]]}]
        with pytest.raises(HelmProblem, match="metadata-only"):
            await adapter.storage_history(request, KEY, lambda: None)
        assert len(api.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "rv",
        "duplicate",
        "loop",
        "pages",
        "large",
        "item-type",
        "metadata",
        "continuation",
        "version",
        "revision",
        "items-limit",
    ],
)
async def test_storage_pagination_is_complete_consistent_unique_and_bounded(tmp_path, fault):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        first = storage_list([storage(1)], continuation="1")
        second = storage_list([storage(2)])
        if fault == "rv":
            second["metadata"]["resourceVersion"] = "other-snapshot"
        elif fault == "duplicate":
            second["items"] = [storage(1)]
        elif fault == "loop":
            second["metadata"]["continue"] = "1"
        elif fault == "pages":
            api.pages = [storage_list([], continuation=str(i + 1)) for i in range(10)]
        elif fault == "large":
            first["items"][0]["metadata"]["annotations"] = {"oversize": "x" * (4 * 1024 * 1024)}
        elif fault == "item-type":
            first["items"] = [None]
        elif fault == "metadata":
            first["metadata"] = None
        elif fault == "continuation":
            first["metadata"]["continue"] = 123
        elif fault == "version":
            first["metadata"]["resourceVersion"] = ""
        elif fault == "revision":
            first["items"][0]["metadata"]["labels"]["version"] = "NaN"
        else:
            first["items"] = [storage(1)] * 201
        api.pages = api.pages or [first, second]
        with pytest.raises(HelmProblem):
            await adapter.storage_history(request, KEY, lambda: None)
        assert len(api.requests) <= 10


@pytest.mark.asyncio
async def test_all_namespace_release_uses_selected_namespace_but_wrong_scoped_namespace_refuses(
    tmp_path,
):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        with pytest.raises(HelmProblem, match="captured namespace"):
            await adapter.storage_history(request, HelmReleaseKey("other", "demo"), lambda: None)
        assert not api.requests
        all_namespaces = replace(request, scope=replace(request.scope, namespace=None))
        assert (await adapter.storage_identity(all_namespaces, KEY, 3, lambda: None)).key == KEY


@pytest.mark.asyncio
async def test_guard_rechecked_after_http_and_read_cancellation_releases_transport(tmp_path):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        api.block = True
        current = [True]

        def guard():
            if not current[0]:
                raise HelmProblem("stale", "Captured request expired.")

        operation = asyncio.create_task(adapter.storage_history(request, KEY, guard))
        await api.started.wait()
        current[0] = False
        api.release.set()
        with pytest.raises(HelmProblem, match="expired"):
            await operation
        api.started.clear()
        api.release.clear()
        current[0] = True
        operation = asyncio.create_task(adapter.storage_identity(request, KEY, 3, guard))
        await api.started.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        api.release.set()
        await adapter.close()
        with pytest.raises(HelmProblem, match="closed"):
            await adapter.storage_history(request, KEY, guard)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["surrogate", "remaining", "remaining-type"])
async def test_metadata_ignored_fields_cannot_bypass_complete_safe_parsing(tmp_path, fault):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        page = storage_list([storage(1)])
        if fault == "surrogate":
            page["items"][0]["metadata"]["annotations"] = {"arbitrary": "\ud800"}
        else:
            page["metadata"]["remainingItemCount"] = True if fault == "remaining-type" else 1
        api.pages = [page]
        with pytest.raises(HelmProblem) as problem:
            await adapter.storage_history(request, KEY, lambda: None)
        assert problem.value.kind == "invalid-output"


@pytest.mark.asyncio
async def test_storage_identity_limit_and_driver_mismatch_refuse_without_partial_result(
    tmp_path, monkeypatch
):
    async with adapter_source(tmp_path) as (adapter, _, api, request, *_):
        monkeypatch.setattr(helm_adapter, "MAX_STORAGE_IDENTITIES", 2)
        with pytest.raises(HelmProblem) as problem:
            await adapter.storage_history(request, KEY, lambda: None)
        assert problem.value.kind == "output-limit"
        adapter.settings = replace(adapter.settings, driver=HelmDriver.CONFIGMAP)
        before = len(api.requests)
        with pytest.raises(HelmProblem) as problem:
            await adapter.storage_history(request, KEY, lambda: None)
        assert problem.value.kind == "unsupported-driver" and len(api.requests) == before


@pytest.mark.asyncio
async def test_real_metadata_http_timeout_is_feature_local(tmp_path):
    async with adapter_source(tmp_path) as (adapter, client, api, request, *_):
        client.timeout = 0.01
        api.block = True
        with pytest.raises(HelmProblem) as problem:
            await adapter.storage_history(request, KEY, lambda: None)
        assert problem.value.kind == "timeout"
