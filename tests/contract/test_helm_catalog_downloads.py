"""Approved distribution origins never inherit repository authentication authority."""

import json

import pytest
from aiohttp import web

from kuberich.adapters.helm_catalog_http import CatalogHttp
from kuberich.domain.helm_catalog import HelmRepository, HelmRepositoryKind, RepositoryCredentials
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm_catalog import HelmCatalogService
from tests.support.helm_catalog import chart_package
from tests.support.helm_oci import content_digest, oci_artifact, oci_handler
from tests.support.history import history_http


def guard():
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["basic", "bearer"])
@pytest.mark.parametrize("redirect", [False, True])
@pytest.mark.parametrize("external_401", [False, True])
async def test_direct_and_redirected_downloads_never_send_or_retry_repository_credentials(
    mode, redirect, external_401
):
    seen, exchanges = [], []
    origin = ""

    async def external(request):
        seen.append(request.headers.get("Authorization"))
        if external_401:
            return web.Response(
                status=401,
                headers={
                    "WWW-Authenticate": f'Bearer realm="{origin}/token",scope="repository:charts:pull"'
                },
            )
        return web.Response(body=b"approved-public-bytes")

    async with history_http(external) as download:

        async def source(request):
            if request.path == "/token":
                exchanges.append(request.headers.get("Authorization"))
                return web.json_response({"token": "must-not-be-exchanged"})
            return web.Response(status=302, headers={"Location": download + "/package"})

        async with history_http(source) as address:
            origin = address
            repository = HelmRepository(
                "owned",
                origin + "/charts",
                HelmRepositoryKind.HTTP,
                "a" * 64,
                True,
                download_origins=(download,),
            )
            credentials = (
                RepositoryCredentials(username="explicit", password="private")
                if mode == "basic"
                else RepositoryCredentials(token="synthetic-repo-token")
            )
            transport = CatalogHttp(repository, credentials)
            try:
                operation = transport.get(
                    (origin if redirect else download) + "/package",
                    max_bytes=128,
                    accept="application/octet-stream",
                    guard=guard,
                )
                if external_401:
                    with pytest.raises(AppError, match="HTTP 401"):
                        await operation
                else:
                    assert (await operation).data == b"approved-public-bytes"
            finally:
                await transport.close()
    assert seen == [None] and not exchanges


@pytest.mark.asyncio
async def test_classic_index_external_package_requires_its_separate_explicit_origin(tmp_path):
    package = chart_package()
    downloads = []

    async def external(request):
        downloads.append(request.headers.get("Authorization"))
        return web.Response(body=package)

    async with history_http(external) as download:

        async def source(request):
            value = json.loads(
                json.dumps(
                    {
                        "apiVersion": "v1",
                        "entries": {
                            "owned-chart": [
                                {
                                    "name": "owned-chart",
                                    "version": "1.0.0",
                                    "urls": [download + "/chart.tgz"],
                                    "digest": content_digest(package)[7:],
                                }
                            ]
                        },
                    }
                )
            )
            return web.json_response(value)

        async with history_http(source) as origin:
            service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
            try:
                with pytest.raises(AppError):
                    await service.add(
                        "denied", origin, allow_loopback_http=True, token_origins=(download,)
                    )
                assert not downloads
                await service.add(
                    "owned",
                    origin,
                    allow_loopback_http=True,
                    download_origins=(download,),
                    credentials=RepositoryCredentials(token="synthetic-private"),
                )
                assert (await service.select(service.search()[0])).package == package
                assert downloads == [None]
                restarted = HelmCatalogService(AccessPolicy(True), tmp_path / "catalog")
                try:
                    assert (await restarted.load()).repositories[0].download_origins == (download,)
                finally:
                    await restarted.close()
            finally:
                await service.close()


@pytest.mark.asyncio
async def test_oci_blob_redirect_to_explicit_download_origin_is_digest_checked_and_anonymous(
    tmp_path,
):
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())
    seen = []

    async def external(request):
        seen.append(request.headers.get("Authorization"))
        return web.Response(body=artifact.package)

    async with history_http(external) as download:

        async def source(request):
            if request.path.endswith("/blobs/" + content_digest(artifact.package)):
                return web.Response(status=307, headers={"Location": download + "/layer"})
            return await oci_handler({"one": artifact})(request)

        async with history_http(source) as origin:
            service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
            try:
                await service.add(
                    "owned",
                    "oci://" + origin.removeprefix("http://") + "/owned/owned-chart",
                    oci=True,
                    allow_loopback_http=True,
                    download_origins=(download,),
                    credentials=RepositoryCredentials(username="explicit", password="private"),
                )
                assert (await service.select(service.search()[0])).package == artifact.package
                assert seen == [None]
            finally:
                await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["basic", "bearer"])
async def test_initial_external_download_cannot_mint_repo_token_by_redirecting_back_to_repo_401(
    mode,
):
    source_origin = ""
    external_seen, source_seen, exchanges = [], [], []

    async def external(request):
        external_seen.append(request.headers.get("Authorization"))
        return web.Response(status=302, headers={"Location": source_origin + "/auth-required"})

    async with history_http(external) as download:

        async def source(request):
            if request.path == "/token":
                exchanges.append(request.headers.get("Authorization"))
                return web.json_response({"token": "repo-only-must-not-escape"})
            source_seen.append(request.headers.get("Authorization"))
            return web.Response(
                status=401,
                headers={
                    "WWW-Authenticate": f'Bearer realm="{source_origin}/token",scope="repository:charts:pull"'
                },
            )

        async with history_http(source) as origin:
            source_origin = origin
            configured = HelmRepository(
                "owned",
                origin + "/charts",
                HelmRepositoryKind.HTTP,
                "a" * 64,
                True,
                download_origins=(download,),
            )
            credentials = (
                RepositoryCredentials(username="explicit", password="private")
                if mode == "basic"
                else RepositoryCredentials(token="synthetic-repo-token")
            )
            transport = CatalogHttp(configured, credentials)
            try:
                with pytest.raises(AppError, match="HTTP 401"):
                    await transport.get(
                        download + "/package",
                        max_bytes=128,
                        accept="application/octet-stream",
                        guard=guard,
                    )
            finally:
                await transport.close()
    assert external_seen == [None] and source_seen == [None] and exchanges == []
