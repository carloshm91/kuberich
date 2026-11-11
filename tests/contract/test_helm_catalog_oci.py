"""Actual owned OCI HTTP contracts: registered paths, immutable digests and pull auth."""

import json

import pytest
from aiohttp import web

from kuberich.domain.helm_catalog import RepositoryCredentials
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm_catalog import HelmCatalogService
from tests.support.helm_catalog import chart_package
from tests.support.helm_oci import MANIFEST_MEDIA, content_digest, oci_artifact, oci_handler
from tests.support.history import history_http

registry_handler = oci_handler


def registered(origin):
    return "oci://" + origin.removeprefix("http://") + "/owned/owned-chart"


@pytest.mark.asyncio
@pytest.mark.parametrize("header_digest", [True, False])
async def test_registered_chart_versions_build_metadata_digest_freeze_and_real_removal(
    tmp_path, header_digest
):
    first = oci_artifact(
        "owned-chart",
        "1.0.0",
        chart_package(),
        provenance=b"original unverified synthetic provenance",
    )
    build = oci_artifact("owned-chart", "1.1.0+build.2", chart_package(version="1.1.0+build.2"))
    artifacts = {first.version: first, build.version: build}
    requests = []
    async with history_http(
        registry_handler(artifacts, requests, header_digest=header_digest)
    ) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            catalog = await service.add(
                "owned", registered(origin), oci=True, allow_loopback_http=True
            )
            assert catalog.generation == 1
            assert [item.version for item in service.search()] == ["1.1.0+build.2", "1.0.0"]
            assert all(item.manifest_digest is not None for item in service.search())
            count = len(requests)
            assert service.search("build")[0].version == build.version and len(requests) == count
            selected = await service.select(service.search()[0])
            assert selected.package == build.package
            assert selected.manifest_digest == build.manifest_digest
            assert (
                selected.layer_digest
                == "sha256:" + selected.sha256
                == content_digest(build.package)
            )
            assert selected.catalog_revision == catalog.repositories[0].revision
            assert selected.catalog_generation == 1
            assert "synthetic-private" not in repr(selected)
            recent_paths = [path for path, _, _ in requests[count:]]
            assert recent_paths[0].endswith("/manifests/" + build.manifest_digest)
            assert not any(path.endswith("/manifests/" + build.tag) for path in recent_paths)
            await service.revalidate(1)
            assert not (await service.remove("owned", expected_generation=1)).repositories
            assert (
                json.loads(next((tmp_path / "catalog").glob("credentials-*.json")).read_bytes())
                == {}
            )
        finally:
            await service.close()
    assert all(path.startswith("/v2/owned/owned-chart/") for path, _, _ in requests)
    assert not any("_catalog" in path for path, _, _ in requests)


@pytest.mark.asyncio
async def test_mutable_tag_replacement_cannot_substitute_bytes_until_explicit_update(tmp_path):
    first = oci_artifact("owned-chart", "1.0.0", chart_package())
    replacement = oci_artifact("owned-chart", "1.0.0", chart_package(values=b"message: replaced\n"))
    artifacts = {"current": first, "retained": first}
    requests = []

    async def handler(request):
        if request.path.endswith("tags/list"):
            requests.append((request.path, dict(request.query), None))
            return web.json_response({"name": "owned/owned-chart", "tags": ["1.0.0"]})
        if request.path.endswith("manifests/1.0.0"):
            item = artifacts["current"]
            requests.append((request.path, {}, None))
            return web.Response(body=item.manifest, content_type=MANIFEST_MEDIA)
        return await registry_handler(artifacts, requests)(request)

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add("owned", registered(origin), oci=True, allow_loopback_http=True)
            chosen = service.search()[0]
            artifacts["current"] = replacement
            assert (await service.select(chosen)).package == first.package
            await service.update("owned", expected_generation=1)
            with pytest.raises(AppError, match="identity changed"):
                await service.select(chosen)
            assert (await service.select(service.search()[0])).package == replacement.package
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_denied_tag_enumeration_stays_denied_and_explicit_digest_registration_is_separate(
    tmp_path,
):
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())
    requests = []
    async with history_http(
        registry_handler({"one": artifact}, requests, denied_listing=True)
    ) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            with pytest.raises(AppError, match="HTTP 403"):
                await service.add("denied", registered(origin), oci=True, allow_loopback_http=True)
            assert not service.snapshot.repositories and not (tmp_path / "catalog").exists()
            await service.add(
                "pinned",
                registered(origin) + "@" + artifact.manifest_digest,
                oci=True,
                allow_loopback_http=True,
            )
            assert service.search()[0].version == "1.0.0"
            assert (await service.select(service.search()[0])).package == artifact.package
            assert sum(path.endswith("tags/list") for path, _, _ in requests) == 1
        finally:
            await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_token_origin", [True, False])
async def test_bearer_tokens_are_bound_to_explicit_origin_repository_and_pull_scope(
    tmp_path, allow_token_origin
):
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())
    token_seen, registry_seen = [], []

    async def token_handler(request):
        token_seen.append((request.headers.get("Authorization"), dict(request.query)))
        return web.json_response({"token": "synthetic-pull-token"})

    async with history_http(token_handler) as token_origin:

        async def handler(request):
            registry_seen.append(request.headers.get("Authorization"))
            if request.headers.get("Authorization") != "Bearer synthetic-pull-token":
                return web.Response(
                    status=401,
                    headers={
                        "WWW-Authenticate": f'Bearer realm="{token_origin}/token",service="owned-registry",scope="repository:owned/owned-chart:pull"'
                    },
                )
            return await registry_handler({"one": artifact}, [])(request)

        async with history_http(handler) as origin:
            service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
            try:
                operation = service.add(
                    "owned",
                    registered(origin),
                    oci=True,
                    allow_loopback_http=True,
                    credentials=RepositoryCredentials(
                        username="explicit", password="synthetic-private"
                    ),
                    token_origins=(token_origin,) if allow_token_origin else (),
                )
                if allow_token_origin:
                    await operation
                    assert (await service.select(service.search()[0])).package == artifact.package
                else:
                    with pytest.raises(AppError):
                        await operation
                    assert not token_seen
            finally:
                await service.close()
    if allow_token_origin:
        assert token_seen and all(
            params == {"scope": "repository:owned/owned-chart:pull", "service": "owned-registry"}
            for _, params in token_seen
        )
        assert all(auth.startswith("Basic ") for auth, _ in token_seen)
        assert "Bearer synthetic-pull-token" in registry_seen
