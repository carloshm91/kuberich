"""Qualify twenty-three curated families on one verified disposable kind."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader
from scripts.curated_kind import (
    CASES,
    SOURCE_PINS,
    evidence_json,
    fixture_manifests,
    persist,
    verify_curated_resources,
    vpa_crd,
)
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster


def input_hashes(root: Path) -> dict[str, str]:
    paths = (
        *sorted((root / "src/kuberich").rglob("*.py")),
        *sorted((root / "src/kuberich").rglob("*.tcss")),
        root / "scripts/curated_kind.py",
        root / "scripts/verify_curated_resources_kind.py",
        root / "scripts/owned_kind.py",
        root / "pyproject.toml",
        root / "uv.lock",
    )
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def prepare(directory: Path) -> dict[str, object]:
    manifests = (
        vpa_crd(),
        *fixture_manifests("kuberich-curated-prepared", "kuberich-curated-empty"),
    )
    persist(directory, "prepared-manifests.json", manifests)
    images = {
        container["image"]
        for document in manifests
        for spec in (
            document.get("spec", {}),
            document.get("spec", {}).get("template", {}).get("spec", {}),
        )
        for container in spec.get("containers", [])
    }
    if images != {SHELL_IMAGE} or any("@sha256:" not in image for image in images):
        raise AssertionError("Every executable fixture image must use the inherited digest pin.")
    return {
        "family_count": len(CASES) + 1,
        "ordinary_families": [case.resource for case in CASES],
        "events": "events.k8s.io/v1 and core/v1 are actual API representations, not two families",
        "static_manifest_count": len(manifests),
        "deferred": "Two EndpointSlices and three Events require the actual created Pod UID.",
        "kind": "v0.33.0, enforced by owned_cluster before creation",
        "node_image": NODE_IMAGE,
        "fixture_images": sorted(images),
        "source_pins": SOURCE_PINS,
        "vpa": "Minimal owned CRD only; no controller or native availability claim.",
        "webhooks": "Only unserved synthetic API rules, excluding all created namespaces.",
        "publication": "No package, tag, remote cluster or provider operation.",
    }


async def verify(cluster: OwnedCluster, directory: Path) -> dict[str, object]:
    before = cluster.path.read_bytes()
    request = ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context, timeout=15)
    catalog = load_catalog(request, {})
    client = KubernetesSession(catalog.select(cluster.context), 15)
    try:
        await client.open()
        result = await verify_curated_resources(
            ResourceReader(client), catalog, cluster, evidence_dir=directory
        )
    finally:
        await finish_owned(asyncio.create_task(client.close()))
    if cluster.path.read_bytes() != before:
        raise AssertionError("Generated owned kubeconfig changed during qualification.")
    return {
        **result,
        "owned_kubeconfig_unchanged": True,
        "owned_session_closed": client.api is None,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, help="Verified local kind v0.33.0 executable.")
    parser.add_argument("--docker", default="docker", help="Local Docker executable.")
    parser.add_argument(
        "--evidence", type=Path, required=True, help="New evidence JSON in a fresh directory."
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write source/manifest pins; execute no Kubernetes or Docker operations.",
    )
    args = parser.parse_args(argv)
    directory = args.evidence.parent
    if args.evidence.exists() or (directory.exists() and any(directory.iterdir())):
        raise ValueError("Use a fresh evidence directory; earlier outcomes must be preserved.")
    directory.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    before = input_hashes(root)
    started = time.monotonic()
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": before,
        "executed_family_count": 0,
        "owned_cluster_deleted": False,
        "private_directory_deleted": False,
    }
    cluster: OwnedCluster | None = None
    try:
        result["prepared"] = prepare(directory)
        if args.prepare_only:
            result["status"] = "prepared"
            result["qualification"] = "No Kubernetes, Docker or kind operations executed."
            return
        failure: BaseException | None = None
        # owned_cluster verifies actual Docker node identity, generated context,
        # TLS endpoint and private certificate-only kubeconfig before yielding.
        with owned_cluster(args.kind, docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            result["owned_node_ids"] = cluster.node_ids
            try:
                result.update(asyncio.run(verify(cluster, directory)))
                result["executed_family_count"] = int(result["ordinary_count"]) + int(
                    result["events_count"]
                )
            except BaseException as error:
                failure = error
                result["qualification_failure_type"] = type(error).__name__
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        if failure is not None:
            raise failure
        if result["executed_family_count"] != 23 or not result["private_directory_deleted"]:
            raise AssertionError("Required family coverage or owned private cleanup failed.")
        if input_hashes(root) != before:
            raise AssertionError("Qualification source inputs changed during the actual trial.")
        result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        result["inputs_unchanged"] = input_hashes(root) == before
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        args.evidence.write_text(evidence_json(result))


if __name__ == "__main__":
    main()
