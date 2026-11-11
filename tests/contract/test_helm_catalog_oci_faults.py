"""Malformed OCI bytes, pagination and identity drift fail before publishing authority."""

import json

import pytest
from aiohttp import web

from kuberich.domain.helm_catalog import MAX_INDEX_BYTES
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm_catalog import HelmCatalogService
from tests.support.helm_catalog import chart_package
from tests.support.helm_oci import MANIFEST_MEDIA, content_digest, oci_artifact, oci_handler
from tests.support.history import history_http


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "media",
        "schema",
        "boolean-schema",
        "subject",
        "config-type",
        "config-size",
        "config-digest",
        "config-urls",
        "layers-type",
        "empty-layers",
        "many-layers",
        "duplicate-layer",
        "unknown-layer",
        "provenance-only",
        "layer-size",
        "layer-digest",
        "header-digest",
        "config-content",
        "wrong-name",
        "wrong-version",
        "missing-version",
        "config-list",
    ],
)
async def test_bad_manifest_or_config_never_creates_a_catalog(tmp_path, fault):
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())
    document = json.loads(artifact.manifest)
    config = artifact.config
    if fault == "media":
        document["mediaType"] = "application/vnd.oci.image.index.v1+json"
    elif fault == "schema":
        document["schemaVersion"] = 1
    elif fault == "boolean-schema":
        document["schemaVersion"] = True
    elif fault == "subject":
        document["subject"] = {}
    elif fault == "config-type":
        document["config"]["mediaType"] = "application/json"
    elif fault == "config-size":
        document["config"]["size"] = 1024 * 1024 + 1
    elif fault == "config-digest":
        document["config"]["digest"] = None
    elif fault == "config-urls":
        document["config"]["urls"] = ["https://trap.invalid/config"]
    elif fault == "layers-type":
        document["layers"] = {}
    elif fault == "empty-layers":
        document["layers"] = []
    elif fault == "many-layers":
        document["layers"] *= 3
    elif fault == "duplicate-layer":
        document["layers"] *= 2
    elif fault == "unknown-layer":
        document["layers"][0]["mediaType"] = "application/foreign"
    elif fault == "provenance-only":
        document["layers"][0]["mediaType"] = "application/vnd.cncf.helm.chart.provenance.v1.prov"
    elif fault == "layer-size":
        document["layers"][0]["size"] = True
    elif fault == "layer-digest":
        document["layers"][0]["digest"] = "sha512:unsupported"
    elif fault in {"wrong-name", "wrong-version", "missing-version", "config-list"}:
        metadata = json.loads(config)
        if fault == "wrong-name":
            metadata["name"] = "other"
        elif fault == "wrong-version":
            metadata["version"] = "2.0.0"
        elif fault == "missing-version":
            metadata.pop("version")
        else:
            metadata = []
        config = json.dumps(metadata).encode()
        document["config"]["digest"] = content_digest(config)
        document["config"]["size"] = len(config)
    manifest = json.dumps(document).encode()

    async def handler(request):
        if request.path.endswith("tags/list"):
            return web.json_response({"name": "owned/owned-chart", "tags": ["1.0.0"]})
        if "/manifests/" in request.path:
            return web.Response(
                body=manifest,
                content_type=MANIFEST_MEDIA,
                headers={"Docker-Content-Digest": "sha256:" + "0" * 64}
                if fault == "header-digest"
                else {},
            )
        if "/blobs/" in request.path:
            return web.Response(body=b"changed" if fault == "config-content" else config)
        return web.Response(status=404)

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            with pytest.raises(AppError):
                await service.add(
                    "owned",
                    "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                    oci=True,
                    allow_loopback_http=True,
                )
            assert not service.snapshot.repositories and not (tmp_path / "catalog").exists()
        finally:
            await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "name",
        "type",
        "duplicate",
        "reverse",
        "bad-tag",
        "too-many",
        "bad-link",
        "empty-link",
        "foreign-link",
        "wrong-path",
        "duplicate-query",
        "wrong-last",
        "bad-page-size",
        "pagination-limit",
        "byte-limit",
    ],
)
async def test_tag_discovery_bounds_and_continuations_do_not_become_complete_authority(
    tmp_path, fault
):
    calls = []

    async def handler(request):
        calls.append(request.path_qs)
        page = len(calls)
        value = {"name": "owned/owned-chart", "tags": [f"tag-{page:03}"]}
        link = None
        if fault == "name":
            value["name"] = "foreign/chart"
        elif fault == "type":
            value["tags"] = {}
        elif fault == "duplicate":
            value["tags"] = ["tag", "tag"]
        elif fault == "reverse":
            value["tags"] = ["z-tag", "a-tag"]
        elif fault == "bad-tag":
            value["tags"] = ["../escape"]
        elif fault == "too-many":
            value["tags"] = [f"tag-{index:04}" for index in range(501)]
        else:
            query = f"n=500&last=tag-{page:03}"
            if fault == "bad-link":
                link = "unsupported"
            elif fault == "empty-link":
                value["tags"] = []
            elif fault == "foreign-link":
                link = (
                    f'<https://foreign.invalid/v2/owned/owned-chart/tags/list?{query}>; rel="next"'
                )
            elif fault == "wrong-path":
                link = f'</v2/foreign/chart/tags/list?{query}>; rel="next"'
            elif fault == "duplicate-query":
                query += f"&last=tag-{page:03}"
            elif fault == "wrong-last":
                query = "n=500&last=foreign"
            elif fault == "bad-page-size":
                query = f"n=501&last=tag-{page:03}"
            if link is None:
                link = f'</v2/owned/owned-chart/tags/list?{query}>; rel="next"'
        if fault == "byte-limit":
            value["padding"] = ""
            value["padding"] = "x" * (MAX_INDEX_BYTES - len(json.dumps(value).encode()))
        return web.Response(
            body=json.dumps(value).encode(),
            content_type="application/json",
            headers={"Link": link} if link else {},
        )

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            with pytest.raises(AppError):
                await service.add(
                    "owned",
                    "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                    oci=True,
                    allow_loopback_http=True,
                )
            assert not service.snapshot.repositories and not (tmp_path / "catalog").exists()
            if fault == "pagination-limit":
                assert len(calls) == 20
            elif fault == "byte-limit":
                assert len(calls) == 1
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_real_multi_page_tag_listing_and_nil_tags_are_bounded_snapshots(tmp_path):
    artifacts = {
        version: oci_artifact("owned-chart", version, chart_package(version=version))
        for version in ("1.0.0", "2.0.0")
    }
    calls = []

    async def handler(request):
        calls.append(dict(request.query))
        if request.path.endswith("tags/list"):
            if "last" not in request.query:
                return web.json_response(
                    {"name": "owned/owned-chart", "tags": ["1.0.0"]},
                    headers={
                        "Link": '</v2/owned/owned-chart/tags/list?n=500&last=1.0.0>; rel="next"'
                    },
                )
            return web.json_response({"name": "owned/owned-chart", "tags": ["2.0.0"]})
        return await oci_handler(artifacts)(request)

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add(
                "owned",
                "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                oci=True,
                allow_loopback_http=True,
            )
            assert [item.version for item in service.search()] == ["2.0.0", "1.0.0"]
            assert calls[:2] == [{"n": "500"}, {"n": "500", "last": "1.0.0"}]
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_generation_is_captured_before_queued_update_or_removal(tmp_path):
    requests = []
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())
    async with history_http(oci_handler({"one": artifact}, requests)) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add(
                "owned",
                "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                oci=True,
                allow_loopback_http=True,
            )
            queued = service.update("owned")
            await service.update("owned", expected_generation=1)
            count = len(requests)
            with pytest.raises(AppError, match="generation changed"):
                await queued
            removal = service.remove("owned")
            await service.update("owned", expected_generation=2)
            count = len(requests)
            with pytest.raises(AppError, match="generation changed"):
                await removal
            assert len(requests) == count
            for operation in (
                service.update("owned", expected_generation=True),
                service.remove("owned", expected_generation=True),
            ):
                with pytest.raises(AppError):
                    await operation
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_nil_tags_remain_an_empty_registered_catalog_without_manifest_reads(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response({"name": "owned/owned-chart", "tags": None})

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add(
                "owned",
                "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                oci=True,
                allow_loopback_http=True,
            )
            assert service.snapshot.repositories and service.search() == ()
            assert len(calls) == 1
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_blob_digest_header_disagreement_blocks_selection_before_native_consumption(tmp_path):
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())

    async def handler(request):
        response = await oci_handler({"one": artifact})(request)
        if request.path.endswith("/blobs/" + content_digest(artifact.package)):
            response.headers["Docker-Content-Digest"] = "sha256:" + "a" * 64
        return response

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add(
                "owned",
                "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                oci=True,
                allow_loopback_http=True,
            )
            with pytest.raises(AppError):
                await service.select(service.search()[0])
        finally:
            await service.close()
