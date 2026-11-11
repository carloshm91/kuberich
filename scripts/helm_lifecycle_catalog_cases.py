"""Production OCI catalog fixtures for an already owned registry and lifecycle case."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from kuberich.domain.helm_catalog import ChartSnapshot, catalog_name
from kuberich.services.helm_catalog import HelmCatalogService
from kuberich.services.resources import parse_owned
from scripts.helm_registry import OwnedHelmRegistry
from tests.support.helm_catalog import chart_package
from tests.support.helm_oci import OciArtifact, content_digest, oci_artifact

_CHART_PATH = "owned/owned-chart"


@dataclass(frozen=True, slots=True, repr=False)
class OciCatalogCase:
    name: str
    generation: int
    initial: ChartSnapshot
    upgraded: ChartSnapshot
    receipt: dict[str, Any]


def _artifacts() -> tuple[OciArtifact, OciArtifact]:
    return (
        oci_artifact("owned-chart", "1.0.0", chart_package()),
        oci_artifact(
            "owned-chart",
            "2.0.0+owned",
            chart_package(
                version="2.0.0+owned",
                values=b"message: synthetic-upgraded\npassword: synthetic-private-upgraded\n",
            ),
        ),
    )


def _verify(snapshot: ChartSnapshot, artifact: OciArtifact, generation: int) -> None:
    assert snapshot.name == artifact.name
    assert snapshot.version == artifact.version
    assert snapshot.package == artifact.package
    assert snapshot.manifest_digest == artifact.manifest_digest
    assert snapshot.layer_digest == content_digest(artifact.package) == "sha256:" + snapshot.sha256
    assert snapshot.catalog_revision
    assert snapshot.catalog_generation == generation


async def prepare_oci_catalog_case(
    registry: OwnedHelmRegistry, catalog: HelmCatalogService, *, name: str = "owned-oci"
) -> OciCatalogCase:
    """Seed original fixtures and freeze two current-generation production selections.

    The caller owns registry/cluster creation, lifecycle operations and cleanup.
    All catalog mutations needed for setup precede the returned selections, so
    neither snapshot relies on a generation superseded by a temporary entry.
    """
    catalog_name(name)
    exact_name = catalog_name(name + "-digest")
    origin = urlsplit(registry.origin or "")
    if (
        registry.container_id is None
        or origin.scheme != "http"
        or origin.hostname != "127.0.0.1"
        or origin.port is None
        or origin.username is not None
        or origin.password is not None
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("Use an already running task-owned loopback Helm registry.")
    await catalog.load()
    if any(item.name in {name, exact_name} for item in catalog.snapshot.repositories):
        raise ValueError("Use fresh task-owned catalog repository names.")
    initial_artifact, upgraded_artifact = await parse_owned(_artifacts)
    for artifact in (initial_artifact, upgraded_artifact):
        await registry.seed(artifact, _CHART_PATH)
    location = f"oci://{origin.netloc}/{_CHART_PATH}"
    await catalog.add(name, location, oci=True, allow_loopback_http=True)
    await catalog.revalidate(catalog.snapshot.generation)
    await catalog.update(name, expected_generation=catalog.snapshot.generation)
    await catalog.add(
        exact_name,
        location + "@" + initial_artifact.manifest_digest,
        oci=True,
        allow_loopback_http=True,
    )
    exact_entries = [chart for chart in catalog.search() if chart.repository == exact_name]
    assert len(exact_entries) == 1
    _verify(await catalog.select(exact_entries[0]), initial_artifact, catalog.snapshot.generation)
    await catalog.remove(exact_name, expected_generation=catalog.snapshot.generation)
    generation = catalog.snapshot.generation
    charts = {
        chart.version: chart for chart in catalog.search("owned-chart") if chart.repository == name
    }
    assert set(charts) == {initial_artifact.version, upgraded_artifact.version}
    initial = await catalog.select(charts[initial_artifact.version])
    upgraded = await catalog.select(charts[upgraded_artifact.version])
    _verify(initial, initial_artifact, generation)
    _verify(upgraded, upgraded_artifact, generation)
    await catalog.revalidate(generation)
    receipt: dict[str, Any] = {
        "repository_name": name,
        "registered_chart_path": _CHART_PATH,
        "registry_container_id": registry.container_id,
        "catalog_generation": generation,
        "production_add_search_select_update_and_exact_digest": True,
        "temporary_digest_entry_removed": True,
        "packages": {
            item.version: {
                "sha256": item.sha256,
                "manifest_digest": item.manifest_digest,
                "layer_digest": item.layer_digest,
                "catalog_revision": item.catalog_revision,
            }
            for item in (initial, upgraded)
        },
    }
    return OciCatalogCase(name, generation, initial, upgraded, receipt)


async def finish_oci_catalog_case(
    catalog: HelmCatalogService, case: OciCatalogCase
) -> dict[str, Any]:
    """Exercise explicit update/removal after the caller finishes native lifecycle use."""
    await catalog.revalidate(case.generation)
    await catalog.update(case.name, expected_generation=case.generation)
    await catalog.remove(case.name, expected_generation=catalog.snapshot.generation)
    assert all(item.name != case.name for item in catalog.snapshot.repositories)
    return {
        **case.receipt,
        "final_catalog_generation": catalog.snapshot.generation,
        "production_final_update_remove": True,
    }
