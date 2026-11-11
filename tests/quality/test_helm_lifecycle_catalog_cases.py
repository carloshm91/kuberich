"""Controlled wire proof of reusable OCI catalog orchestration, without Docker."""

from pathlib import Path

import pytest

from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm_catalog import HelmCatalogService
from scripts.helm_lifecycle_catalog_cases import (
    finish_oci_catalog_case,
    prepare_oci_catalog_case,
)
from scripts.helm_registry import OwnedHelmRegistry
from tests.support.helm_oci import oci_handler
from tests.support.history import history_http


@pytest.mark.asyncio
async def test_reusable_catalog_case_uses_real_production_transport_and_current_generations(
    tmp_path, monkeypatch
):
    artifacts, requests, seeds = {}, [], []
    registry = OwnedHelmRegistry(Path("/owned/docker"), "unix:///owned/docker.sock", tmp_path)

    async def seed(artifact, repository):
        assert repository == "owned/owned-chart"
        artifacts[artifact.version] = artifact
        seeds.append(artifact.manifest_digest)

    monkeypatch.setattr(registry, "seed", seed)
    catalog = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
    try:
        async with history_http(oci_handler(artifacts, requests)) as origin:
            registry.origin, registry.container_id = origin, "a" * 64
            case = await prepare_oci_catalog_case(registry, catalog)
            assert len(seeds) == 2
            assert case.initial.version == "1.0.0"
            assert case.upgraded.version == "2.0.0+owned"
            assert case.generation == case.initial.catalog_generation == 4
            assert case.generation == case.upgraded.catalog_generation
            assert [item.name for item in catalog.snapshot.repositories] == ["owned-oci"]
            receipt = await finish_oci_catalog_case(catalog, case)
            assert receipt["final_catalog_generation"] == 6
            assert receipt["production_final_update_remove"]
            assert not catalog.snapshot.repositories
            assert "synthetic-private" not in str(receipt)
            assert "synthetic-private" not in repr(case)
            assert all(path.startswith("/v2/owned/owned-chart/") for path, _, _ in requests)
    finally:
        # This test supplies a controlled wire seed seam; it never starts a container.
        registry.container_id = None
        await registry.close()
        await catalog.close()


@pytest.mark.asyncio
async def test_reusable_catalog_case_refuses_stale_finish_without_replacing_authority(
    tmp_path, monkeypatch
):
    artifacts, requests = {}, []
    registry = OwnedHelmRegistry(Path("/owned/docker"), "unix:///owned/docker.sock", tmp_path)

    async def seed(artifact, repository):
        artifacts[artifact.version] = artifact

    monkeypatch.setattr(registry, "seed", seed)
    catalog = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
    try:
        async with history_http(oci_handler(artifacts, requests)) as origin:
            registry.origin, registry.container_id = origin, "a" * 64
            case = await prepare_oci_catalog_case(registry, catalog)
            await catalog.update(case.name, expected_generation=case.generation)
            previous = len(requests)
            with pytest.raises(AppError):
                await finish_oci_catalog_case(catalog, case)
            assert len(requests) == previous
            assert [item.name for item in catalog.snapshot.repositories] == [case.name]
    finally:
        registry.container_id = None
        await registry.close()
        await catalog.close()


@pytest.mark.asyncio
async def test_reusable_catalog_case_requires_running_owned_loopback_before_effects(tmp_path):
    registry = OwnedHelmRegistry(Path("/owned/docker"), "unix:///owned/docker.sock", tmp_path)
    catalog = HelmCatalogService(AccessPolicy(False), tmp_path / "catalog")
    try:
        with pytest.raises(ValueError, match="already running"):
            await prepare_oci_catalog_case(registry, catalog)
        assert not (tmp_path / "catalog").exists()
    finally:
        await registry.close()
        await catalog.close()
