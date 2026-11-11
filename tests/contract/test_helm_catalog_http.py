"""Real bounded repository HTTP and private catalog transactions."""

import asyncio
import hashlib
import json

import pytest
from aiohttp import web

from kuberich.domain.helm_catalog import RepositoryCredentials
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm_catalog import HelmCatalogService
from tests.support.helm_catalog import chart_package, repository_index
from tests.support.history import history_http


@pytest.mark.asyncio
async def test_real_repository_add_cached_search_select_update_remove_and_private_restart(
    tmp_path, monkeypatch
):
    packages = {("owned-chart", "1.0.0"): chart_package()}
    requests = []

    async def handler(request):
        requests.append((request.path, dict(request.headers)))
        if request.path == "/charts/index.yaml":
            return web.Response(body=repository_index(packages))
        for (name, version), data in packages.items():
            if request.path == f"/charts/{name}-{version}.tgz":
                return web.Response(body=data)
        return web.Response(status=404)

    async def trap(request):
        raise AssertionError("Caller proxy credentials escaped")

    async with history_http(handler) as origin, history_http(trap) as proxy:
        monkeypatch.setenv("HTTP_PROXY", proxy)
        monkeypatch.setenv("ALL_PROXY", proxy)
        monkeypatch.setenv("NETRC", str(tmp_path / "ambient-netrc"))
        root = tmp_path / "catalog"
        service = HelmCatalogService(AccessPolicy(False), root)
        try:
            assert not (await service.load()).repositories
            assert not root.exists()
            first = await service.add(
                "owned",
                origin + "/charts",
                allow_loopback_http=True,
                credentials=RepositoryCredentials(username="synthetic", password="private"),
            )
            assert first.generation == 1
            assert len(service.search("OWNED")) == 1 and len(requests) == 1
            chart = service.search()[0]
            selected = await service.select(chart)
            assert selected.package == packages[("owned-chart", "1.0.0")]
            assert selected.sha256 == hashlib.sha256(selected.package).hexdigest()
            assert selected.default_values.startswith(b"message:")
            assert "private" not in repr(selected) and "private" not in repr(first)
            assert len(requests) == 2
            assert root.stat().st_mode & 0o777 == 0o700
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
            assert "private" not in (root / "catalog.json").read_text()
            assert len(list(root.glob("credentials-*.json"))) == 1
            readonly = HelmCatalogService(AccessPolicy(True), root)
            try:
                assert await readonly.load() == first
                assert readonly.search() == service.search()
                for operation in (
                    readonly.add("blocked", origin, allow_loopback_http=True),
                    readonly.update("owned"),
                    readonly.remove("owned"),
                    readonly.select(chart),
                ):
                    with pytest.raises(AppError, match="Read-only"):
                        await operation
                assert len(requests) == 2
            finally:
                await readonly.close()
            packages[("owned-chart", "2.0.0")] = chart_package(version="2.0.0")
            updated = await service.update("owned")
            assert updated.generation == 2 and service.search()[0].version == "2.0.0"
            with pytest.raises(AppError, match="identity changed"):
                await service.select(chart)
            assert len(list(root.glob("credentials-*.json"))) == 1
            assert not (await service.remove("owned")).repositories
            assert service.search() == ()
            current_credentials = next(root.glob("credentials-*.json"))
            assert json.loads(current_credentials.read_bytes()) == {}
            assert len(requests) == 3
        finally:
            await service.close()
    assert all(headers.get("Authorization", "").startswith("Basic ") for _, headers in requests)
    assert all("Cookie" not in headers for _, headers in requests)
    assert service.operation_count == 0


@pytest.mark.asyncio
async def test_digest_replacement_never_changes_frozen_bytes_and_refresh_is_explicit(tmp_path):
    original = chart_package()
    changed = chart_package(values=b"message: replaced\n")
    served = original

    async def handler(request):
        return web.Response(
            body=repository_index({("owned-chart", "1.0.0"): original})
            if request.path.endswith("index.yaml")
            else served
        )

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add("owned", origin, allow_loopback_http=True)
            chart = service.search()[0]
            frozen = await service.select(chart)
            served = changed
            with pytest.raises(AppError, match="frozen digest"):
                await service.select(chart)
            assert frozen.package == original
        finally:
            await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "remote",
        "digest",
        "version",
        "wrong-name",
        "non-mapping",
        "redirect",
        "encoding",
        "denied",
    ],
)
async def test_invalid_index_or_transport_cannot_publish_catalog(tmp_path, fault):
    document = {
        "apiVersion": "v1",
        "entries": {
            "owned-chart": [
                {
                    "name": "owned-chart",
                    "version": "1.0.0",
                    "urls": ["owned.tgz"],
                    "digest": "a" * 64,
                }
            ]
        },
    }
    if fault == "remote":
        document["entries"]["owned-chart"][0]["urls"] = ["https://elsewhere.invalid/private.tgz"]
    elif fault in {"digest", "version"}:
        document["entries"]["owned-chart"][0][fault] = "invalid"
    elif fault == "wrong-name":
        document["entries"]["owned-chart"][0]["name"] = "other"
    elif fault == "non-mapping":
        document["entries"] = []

    async def handler(request):
        if fault == "redirect":
            return web.Response(
                status=302, headers={"Location": "https://elsewhere.invalid/private"}
            )
        if fault == "denied":
            return web.Response(status=403)
        if fault == "encoding":
            return web.Response(body=b"untrusted", headers={"Content-Encoding": "gzip"})
        data = (
            json.dumps(document).encode()
            if fault != "duplicate"
            else b'{"apiVersion":"v1","apiVersion":"v1","entries":{}}'
        )
        return web.Response(body=data)

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            with pytest.raises(AppError):
                await service.add("owned", origin, allow_loopback_http=True)
            assert not service.snapshot.repositories
            assert not (tmp_path / "catalog").exists()
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_cancelled_transfer_and_policy_tightening_leave_no_catalog_or_owned_http(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        started.set()
        await release.wait()
        return web.Response(body=repository_index({("owned-chart", "1.0.0"): chart_package()}))

    async with history_http(handler) as origin:
        policy = AccessPolicy(False)
        service = HelmCatalogService(policy, tmp_path / "catalog")
        task = asyncio.create_task(service.add("owned", origin, allow_loopback_http=True))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert not (tmp_path / "catalog").exists()
        policy.tighten()
        with pytest.raises(AppError, match="Read-only"):
            await service.add("owned", origin, allow_loopback_http=True)
        await service.close()
        assert service.operation_count == 0


@pytest.mark.asyncio
async def test_external_catalog_generation_change_refuses_stale_writer(tmp_path):
    async def handler(request):
        return web.Response(body=repository_index({}))

    async with history_http(handler) as origin:
        root = tmp_path / "catalog"
        first, second = (
            HelmCatalogService(AccessPolicy(False), root),
            HelmCatalogService(AccessPolicy(False), root),
        )
        try:
            await first.add("first", origin, allow_loopback_http=True)
            await second.load()
            await first.add("second", origin, allow_loopback_http=True)
            with pytest.raises(AppError, match="storage"):
                await second.remove("first")
            assert len((await second.load()).repositories) == 2
        finally:
            await first.close()
            await second.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "wrong-generation",
        "boolean-generation",
        "metadata",
        "credentials",
        "same-byte-credential-replacement",
        "root",
    ],
)
async def test_revalidation_rereads_exact_private_inputs_without_network_or_new_authority(
    tmp_path, fault
):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return web.Response(body=repository_index({}))

    async with history_http(handler) as origin:
        root = tmp_path / "catalog"
        service = HelmCatalogService(AccessPolicy(False), root)
        try:
            await service.add(
                "owned",
                origin,
                allow_loopback_http=True,
                credentials=RepositoryCredentials(token="synthetic-private"),
            )
            captured = service.snapshot
            generation = captured.generation
            if fault == "wrong-generation":
                generation += 1
            elif fault == "boolean-generation":
                generation = True
            elif fault == "metadata":
                metadata = root / "catalog.json"
                metadata.write_bytes(metadata.read_bytes() + b" ")
            elif fault in {"credentials", "same-byte-credential-replacement"}:
                secret = next(root.glob("credentials-*.json"))
                if fault == "credentials":
                    secret.write_bytes(b"unreviewed")
                else:
                    replacement = tmp_path / "replacement"
                    replacement.write_bytes(secret.read_bytes())
                    replacement.chmod(0o600)
                    replacement.replace(secret)
            elif fault == "root":
                root.rename(tmp_path / "retired")
                root.mkdir(mode=0o700)
            if fault == "none":
                await service.revalidate(generation)
            else:
                with pytest.raises(AppError):
                    await service.revalidate(generation)
                assert service.snapshot is captured
                if fault in {"metadata", "same-byte-credential-replacement", "root"}:
                    with pytest.raises(AppError):
                        await service.load()
            assert requests == ["/index.yaml"]
        finally:
            await service.close()
        with pytest.raises(AppError, match="closed"):
            await service.revalidate(captured.generation)


@pytest.mark.asyncio
async def test_empty_catalog_revalidation_is_offline_and_does_not_create_storage(tmp_path):
    root = tmp_path / "catalog"
    service = HelmCatalogService(AccessPolicy(True), root)
    try:
        await service.revalidate(0)
        assert not root.exists()
        await service.load()
        await service.revalidate(0)
        assert not root.exists()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_public_catalog_errors_never_implicitly_replace_or_create_entries(tmp_path):
    async def handler(request):
        return web.Response(body=repository_index({}))

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add("owned", origin, allow_loopback_http=True)
            captured = service.snapshot
            for operation in (
                service.add("owned", origin, allow_loopback_http=True),
                service.add("other", origin, allow_loopback_http=True, credentials={}),
                service.update("missing"),
                service.remove("missing"),
            ):
                with pytest.raises(AppError):
                    await operation
            for text in (None, "x" * 4097):
                with pytest.raises(AppError):
                    service.search(text)
            assert service.snapshot is captured
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_explicit_sha256_index_prefix_selects_the_exact_real_package(tmp_path):
    package = chart_package()

    async def handler(request):
        if request.path.endswith("index.yaml"):
            index = repository_index({("owned-chart", "1.0.0"): package}).replace(
                b"digest: ", b"digest: sha256:"
            )
            return web.Response(body=index)
        return web.Response(body=package)

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            await service.add("owned", origin, allow_loopback_http=True)
            assert (await service.select(service.search()[0])).package == package
        finally:
            await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    ["api-version", "versions-type", "urls-empty", "url-type", "digest-type", "version-type"],
)
async def test_index_shape_fields_are_validated_before_persistence(tmp_path, fault):
    value = {
        "apiVersion": "v1",
        "entries": {
            "owned-chart": [
                {
                    "name": "owned-chart",
                    "version": "1.0.0",
                    "urls": ["chart.tgz"],
                    "digest": "a" * 64,
                }
            ]
        },
    }
    if fault == "api-version":
        value["apiVersion"] = "unsupported"
    elif fault == "versions-type":
        value["entries"]["owned-chart"] = {}
    else:
        row = value["entries"]["owned-chart"][0]
        key = {
            "urls-empty": "urls",
            "url-type": "urls",
            "digest-type": "digest",
            "version-type": "version",
        }[fault]
        row[key] = [] if fault == "urls-empty" else [4] if fault == "url-type" else None

    async def handler(request):
        return web.json_response(value)

    async with history_http(handler) as origin:
        service = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
        try:
            with pytest.raises(AppError):
                await service.add("owned", origin, allow_loopback_http=True)
            assert not (tmp_path / "catalog").exists()
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_explicit_auth_rotation_creates_a_new_generation_and_retires_old_private_bytes(
    tmp_path,
):
    seen = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        return web.Response(body=repository_index({}))

    async with history_http(handler) as origin:
        root = tmp_path / "catalog"
        service = HelmCatalogService(AccessPolicy(False), root)
        try:
            await service.add(
                "owned",
                origin,
                allow_loopback_http=True,
                credentials=RepositoryCredentials(token="synthetic-first"),
            )
            with pytest.raises(AppError):
                await service.update("owned", credentials={})
            await service.update(
                "owned",
                expected_generation=1,
                credentials=RepositoryCredentials(token="synthetic-second"),
            )
            assert service.snapshot.generation == 2
            assert seen == ["Bearer synthetic-first", "Bearer synthetic-second"]
            assert b"synthetic-first" not in b"".join(path.read_bytes() for path in root.iterdir())
            with pytest.raises(AppError, match="generation"):
                await service.revalidate(1)
            await service.revalidate(2)
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_cancelled_private_file_worker_is_drained_without_publishing_late_catalog(
    tmp_path, monkeypatch
):
    import os
    import threading

    async def handler(request):
        return web.Response(body=repository_index({}))

    async with history_http(handler) as origin:
        root = tmp_path / "catalog"
        service = HelmCatalogService(AccessPolicy(False), root)
        await service.add("owned", origin, allow_loopback_http=True)
        captured = service.snapshot
        inode = (root / "catalog.json").stat().st_ino
        entered, release = threading.Event(), threading.Event()
        original = os.read

        def held(descriptor, size):
            if os.fstat(descriptor).st_ino == inode:
                entered.set()
                if not release.wait(5):
                    raise OSError("owned worker deadline")
            return original(descriptor, size)

        monkeypatch.setattr(os, "read", held)
        task = asyncio.create_task(service.load())
        try:
            await asyncio.wait_for(asyncio.to_thread(entered.wait), 2)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert service.snapshot is captured and service.operation_count == 0
        finally:
            release.set()
            await service.close()
