"""Measure production catalog actions against one explicitly owned pinned OCI registry."""

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kuberich.services.access import AccessPolicy
from kuberich.services.helm_catalog import HelmCatalogService
from scripts.helm_registry import owned_helm_registry
from scripts.owned_kind import capture_docker
from tests.support.helm_catalog import chart_package
from tests.support.helm_oci import oci_artifact


def input_hashes(root: Path) -> dict[str, str]:
    paths = {
        root / "scripts/verify_helm_registry.py",
        root / "scripts/helm_registry.py",
        root / "scripts/owned_kind.py",
        root / "tests/support/helm_catalog.py",
        root / "tests/support/helm_oci.py",
        root / "uv.lock",
        root / "pyproject.toml",
        *(root / "src/kuberich").rglob("*.py"),
    }
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


async def verify(docker: Path, endpoint: str, parent: Path, report: dict[str, Any]) -> None:
    package = chart_package()
    artifact = oci_artifact("owned-chart", "1.0.0", package)
    second_package = chart_package(
        version="2.0.0+owned", values=b"message: upgraded\npassword: owned-private\n"
    )
    second = oci_artifact("owned-chart", "2.0.0+owned", second_package)
    catalog = HelmCatalogService(AccessPolicy(False), parent / "catalog")
    registry_receipt = None
    try:
        async with owned_helm_registry(docker, endpoint, parent) as registry:
            registry_receipt = registry.receipt
            await registry.seed(artifact, "owned/owned-chart")
            await registry.seed(second, "owned/owned-chart")
            assert registry.origin is not None
            origin = urlsplit(registry.origin)
            location = f"oci://{origin.netloc}/owned/owned-chart"
            await catalog.add("owned", location, oci=True, allow_loopback_http=True)
            charts = catalog.search("owned-chart")
            assert {chart.version for chart in charts} == {"1.0.0", "2.0.0+owned"}
            snapshots = {chart.version: await catalog.select(chart) for chart in charts}
            for item in (artifact, second):
                snapshot = snapshots[item.version]
                assert snapshot.package == item.package
                assert snapshot.manifest_digest == item.manifest_digest
                assert snapshot.layer_digest == "sha256:" + hashlib.sha256(item.package).hexdigest()
                assert snapshot.catalog_revision
            report["catalog"] = {
                "versions": sorted(snapshots),
                "packages": {
                    version: {
                        "sha256": snapshot.sha256,
                        "manifest_digest": snapshot.manifest_digest,
                        "layer_digest": snapshot.layer_digest,
                        "catalog_revision": snapshot.catalog_revision,
                    }
                    for version, snapshot in snapshots.items()
                },
                "registered_chart_path_only": True,
                "semver_build_tag_translation": True,
                "production_http_and_private_store": True,
            }
            generation = catalog.snapshot.generation
            await catalog.revalidate(generation)
            await catalog.update("owned", expected_generation=generation)
            await catalog.add(
                "exact",
                location + "@" + artifact.manifest_digest,
                oci=True,
                allow_loopback_http=True,
            )
            exact = next(chart for chart in catalog.search() if chart.repository == "exact")
            assert (await catalog.select(exact)).package == artifact.package
            await catalog.remove("owned", expected_generation=catalog.snapshot.generation)
            await catalog.remove("exact", expected_generation=catalog.snapshot.generation)
            assert not catalog.snapshot.repositories
            report["catalog"]["update_remove_and_exact_digest_select"] = True
        report["registry"] = registry_receipt
        assert registry_receipt["cleanup_complete"]
    finally:
        await catalog.close()
        if registry_receipt is not None:
            report["registry"] = registry_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or platform.machine() != "x86_64" or not args.docker.is_absolute():
        raise ValueError(
            "Use an explicit local Linux amd64 Docker executable for this owned fixture."
        )
    evidence = args.evidence.absolute()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    if evidence.exists():
        raise ValueError("Use a fresh immutable registry evidence path.")
    root = Path(__file__).resolve().parent.parent
    hashes = input_hashes(root)
    report: dict[str, Any] = {
        "status": "in-progress",
        "inputs": hashes,
        "scope": "Owned local OCI registry and production catalog only; no Helm lifecycle, provider, installed, CI or release qualification.",
        "source_binding": "Exact working-tree inputs; not qualification of an unchanged base commit.",
    }
    try:
        environment = capture_docker(str(args.docker))
        with tempfile.TemporaryDirectory(prefix="kuberich-registry-proof-") as directory:
            temporary = Path(directory)
            asyncio.run(verify(args.docker, environment["DOCKER_HOST"], temporary, report))
        report["temporary_directory_absent"] = not temporary.exists()
        if input_hashes(root) != hashes:
            raise AssertionError("Registry proof inputs changed during measurement.")
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        with evidence.open("x") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    print(json.dumps({"status": report["status"], "evidence": str(evidence)}))


if __name__ == "__main__":
    main()
