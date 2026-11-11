"""Actual public lifecycle controls against an owned chart repository and kind API."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from aiohttp import web
from kubernetes_asyncio import client
from textual.app import App
from textual.widgets import Button, Checkbox

from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.helm import (
    HelmDriver,
    HelmOutcome,
    HelmReleaseKey,
    HelmRequest,
    HelmScope,
    HelmSettings,
)
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.helm_lifecycle import HelmLifecycleKind, fingerprint
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from kuberich.services.sessions import SessionService
from kuberich.ui.helm_lifecycle import HelmLifecycleScreen
from scripts.helm_lifecycle_catalog_cases import finish_oci_catalog_case, prepare_oci_catalog_case
from scripts.helm_lifecycle_fault_cases import verify_uncertain_lifecycle
from scripts.helm_registry import OwnedHelmRegistry
from scripts.helm_tools import HelmPin
from scripts.owned_kind import OwnedCluster
from tests.support.helm_catalog import chart_package, repository_index


class HelmProofApp(App[None]):
    def __init__(self, screen: HelmLifecycleScreen) -> None:
        super().__init__()
        self.review = screen

    async def on_mount(self) -> None:
        await self.push_screen(self.review)


async def verify_lifecycle_case(
    cluster: OwnedCluster,
    binary: Path,
    pin: HelmPin,
    driver: HelmDriver,
    directory: Path,
    registry: OwnedHelmRegistry,
) -> dict[str, Any]:
    directory = directory.absolute()
    namespace = f"owned-lifecycle-{pin.version[1]}-{driver.value}"
    directory.mkdir(parents=True, mode=0o700)
    packages = {
        ("owned-chart", "1.0.0"): chart_package(),
        ("owned-chart", "2.0.0"): chart_package(
            version="2.0.0",
            values=b"message: synthetic-upgraded\npassword: synthetic-private-upgraded\n",
        ),
        ("owned-retained", "1.0.0"): chart_package(
            name="owned-retained",
            files={
                "templates/configmap.yaml": b"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}-settings\n  annotations:\n    helm.sh/resource-policy: keep\ndata:\n  message: {{ .Values.message | quote }}\n",
                "templates/hook.yaml": b"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}-hook\n  annotations:\n    helm.sh/hook: post-install,post-delete\n    helm.sh/hook-delete-policy: before-hook-creation\ndata:\n  owned: hook\n",
            },
        ),
    }
    index = repository_index(packages)

    async def serve(request: web.Request) -> web.Response:
        if request.path == "/index.yaml":
            return web.Response(body=index)
        for (name, version), package in packages.items():
            if request.path == f"/{name}-{version}.tgz":
                return web.Response(body=package)
        return web.Response(status=404)

    repo = web.Application()
    repo.router.add_get("/{path:.*}", serve)
    listener = web.AppRunner(repo, shutdown_timeout=0.1)
    await listener.setup()
    site = web.TCPSite(listener, "127.0.0.1", 0)
    await site.start()
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    sessions = SessionService(load_catalog(request, {}), request)
    service: HelmService | None = None
    checks = []
    operations: list[dict[str, Any]] = []
    try:
        await sessions.connect(cluster.context)
        connection, identity = sessions.client, sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        core = client.CoreV1Api(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        captured = HelmRequest(HelmScope(identity, namespace, driver), 1)
        environment = {
            "PATH": os.defpath,
            "HOME": str(directory),
            "HELM_DEBUG": "true",
            "HELM_REPOSITORY_CONFIG": str(directory / "caller-repositories"),
            "HELM_REGISTRY_CONFIG": str(directory / "caller-registry"),
            "DOCKER_CONFIG": str(directory / "caller-docker"),
        }
        service = HelmService(
            connection,
            AccessPolicy(False),
            HelmSettings(str(binary), driver),
            environment,
            directory,
            lambda candidate: candidate == captured and sessions.client is connection,
            catalog_directory=directory / "catalog",
        )
        await service.catalog.load()
        url = f"http://127.0.0.1:{listener.addresses[0][1]}"
        await service.catalog.add("owned", url, allow_loopback_http=True)
        charts = service.catalog.search("owned-chart")
        assert {chart.version for chart in charts} == {"1.0.0", "2.0.0"}
        snapshots = {chart.version: await service.catalog.select(chart) for chart in charts}
        retained_chart = await service.catalog.select(service.catalog.search("owned-retained")[0])
        checks.append("production-owned-http-add-search-version-select")
        storage_plural = "secrets" if driver is HelmDriver.SECRET else "configmaps"

        async def storage(name: str) -> tuple[tuple[str, str, str], ...]:
            data = await connection.get_json(
                f"/api/v1/namespaces/{namespace}/{storage_plural}",
                params={"labelSelector": f"owner=helm,name={name}"},
                accept="application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1",
            )
            assert data.get("apiVersion") == "meta.k8s.io/v1"
            assert data.get("kind") == "PartialObjectMetadataList"
            assert isinstance(data.get("metadata"), dict)
            assert data["metadata"].get("resourceVersion")
            assert not data["metadata"].get("continue")
            items = data["items"]
            if items is None:
                items = []
            assert isinstance(items, list)
            return tuple(
                sorted(
                    (
                        item["metadata"]["name"],
                        item["metadata"]["uid"],
                        item["metadata"]["resourceVersion"],
                    )
                    for item in items
                )
            )

        async def resource(name: str) -> dict[str, Any] | None:
            try:
                return await connection.get_json(
                    f"/api/v1/namespaces/{namespace}/configmaps/{name}-settings"
                )
            except HttpProblem as error:
                if error.status != 404:
                    raise
                return None

        async def operation(
            name: str,
            kind: HelmLifecycleKind,
            chart: ChartSnapshot | None = None,
            *,
            keep: bool = True,
            retained: bool = False,
            hooks: bool = False,
        ) -> None:
            assert service is not None
            before_storage, before_resource = await storage(name), await resource(name)
            screen = HelmLifecycleScreen(
                service=service,
                request=captured,
                address=HelmReleaseKey(namespace, name),
                operation=kind,
                chart=chart,
            )
            app = HelmProofApp(screen)
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                if kind is HelmLifecycleKind.UNINSTALL and not keep:
                    screen.query_one("#helm-lifecycle-history", Checkbox).value = False
                    await pilot.pause()
                if hooks:
                    screen.query_one("#helm-lifecycle-hooks", Checkbox).value = True
                    await pilot.pause()
                assert await pilot.click("#helm-lifecycle-prepare")
                async with asyncio.timeout(120):
                    while screen.operation_count:
                        await pilot.pause(0.05)
                assert screen.intent is not None, str(screen.status.render())
                intent = screen.intent
                assert not screen.query_one("#helm-lifecycle-confirm", Button).disabled
                assert "synthetic-private" not in screen.intent.preview_text
                assert (
                    await storage(name) == before_storage
                    and await resource(name) == before_resource
                )
                assert await pilot.click("#helm-lifecycle-confirm")
                async with asyncio.timeout(120):
                    while screen.operation_count:
                        await pilot.pause(0.05)
                assert screen.observation is not None, str(screen.status.render())
                assert screen.observation.outcome is HelmOutcome.SUCCEEDED, (
                    screen.observation.message
                )
                assert screen.query_one("#helm-lifecycle-confirm", Button).disabled
                observed = screen.observation
            observed_storage, observed_resource = await storage(name), await resource(name)
            if kind is HelmLifecycleKind.UNINSTALL:
                assert (observed_resource is not None) is retained
                assert bool(observed_storage) is keep
                if retained:
                    assert any(
                        "retained by resource-policy keep" in fact for fact in observed.resources
                    )
            else:
                assert observed_resource is not None and observed_storage != before_storage
                expected = (
                    "synthetic-first" if kind is HelmLifecycleKind.INSTALL else "synthetic-upgraded"
                )
                assert observed_resource["data"]["message"] == expected
            receipt = {
                "operation": kind.value,
                "address": f"{namespace}/{name}",
                "version": pin.version,
                "binary_sha256": pin.binary_sha256,
                "driver": driver.value,
                "chart_sha256": chart.sha256 if chart is not None else None,
                "chart_version": chart.version if chart is not None else None,
                "public_controls": ["helm-lifecycle-prepare", "helm-lifecycle-confirm"],
                "native_dry_run": intent.dry_run,
                "preview_sha256": fingerprint(intent.preview_text.encode()),
                "before_storage": before_storage,
                "after_storage": observed_storage,
                "no_preconfirm_storage_or_resource_write": True,
                "observed_outcome": observed.outcome.value,
                "observed_revision": observed.observed.revision
                if observed.observed is not None
                else None,
                "observed_status": observed.observed.status
                if observed.observed is not None
                else None,
                "resources": observed.resources,
                "keep_history": keep if kind is HelmLifecycleKind.UNINSTALL else None,
                "resource_absent": observed_resource is None,
                "resource_uid": observed_resource["metadata"]["uid"]
                if observed_resource is not None
                else None,
                "resource_version": observed_resource["metadata"]["resourceVersion"]
                if observed_resource is not None
                else None,
                "independent_resource_data_matches": True,
            }
            operations.append(receipt)
            with (directory / f"operation-{len(operations):02d}.json").open("x") as output:
                json.dump(receipt, output, indent=2)
                output.write("\n")
            checks.append(
                "public-"
                + kind.value
                + (
                    "-keep-history"
                    if kind is HelmLifecycleKind.UNINSTALL and keep
                    else "-purge-history"
                    if kind is HelmLifecycleKind.UNINSTALL
                    else ""
                )
                + "-native-dryrun-live-diff-no-preconfirm-write-effects"
            )

        await operation("owned-release", HelmLifecycleKind.INSTALL, snapshots["1.0.0"])
        await operation("owned-release", HelmLifecycleKind.UPGRADE, snapshots["2.0.0"])
        await operation("owned-release", HelmLifecycleKind.UNINSTALL)
        await operation("owned-purge", HelmLifecycleKind.INSTALL, snapshots["1.0.0"])
        await operation("owned-purge", HelmLifecycleKind.UNINSTALL, keep=False)
        if pin.version == "v3.22.1" and driver is HelmDriver.SECRET:
            await operation("owned-retained", HelmLifecycleKind.INSTALL, retained_chart, hooks=True)
            first_hook = await connection.get_json(
                f"/api/v1/namespaces/{namespace}/configmaps/owned-retained-hook"
            )
            await operation(
                "owned-retained", HelmLifecycleKind.UNINSTALL, keep=False, retained=True, hooks=True
            )
            last_hook = await connection.get_json(
                f"/api/v1/namespaces/{namespace}/configmaps/owned-retained-hook"
            )
            assert first_hook["metadata"]["uid"] != last_hook["metadata"]["uid"]
            checks.append("actual-lifecycle-hook-effects-and-keep-resource-after-history-purge")
        oci = await prepare_oci_catalog_case(registry, service.catalog)
        await operation("owned-oci", HelmLifecycleKind.INSTALL, oci.initial)
        await operation("owned-oci", HelmLifecycleKind.UPGRADE, oci.upgraded)
        await operation("owned-oci", HelmLifecycleKind.UNINSTALL, keep=False)
        faults: dict[str, Any] = {}
        if pin.version == "v3.22.1" and driver is HelmDriver.SECRET:
            faults["uncertain_write"] = await verify_uncertain_lifecycle(
                cluster, binary, driver, namespace, oci.initial, directory
            )
            checks.append("actual-native-install-response-loss-partial-effects-unknown-no-replay")
            quota = await core.create_namespaced_resource_quota(
                namespace,
                client.V1ResourceQuota(
                    metadata=client.V1ObjectMeta(name="owned-create-denial"),
                    spec=client.V1ResourceQuotaSpec(hard={"count/configmaps": "0"}),
                ),
            )
            async with asyncio.timeout(30):
                while True:
                    observed_quota = await core.read_namespaced_resource_quota(
                        quota.metadata.name, namespace
                    )
                    if (
                        observed_quota.status is not None
                        and observed_quota.status.hard
                        and observed_quota.status.hard.get("count/configmaps") == "0"
                    ):
                        break
                    await asyncio.sleep(0.05)
            before_quota = await storage("owned-quota")
            try:
                await service.prepare_lifecycle(
                    captured,
                    HelmReleaseKey(namespace, "owned-quota"),
                    HelmLifecycleKind.INSTALL,
                    oci.initial,
                )
            except AppError as error:
                assert "named-create admission dry-run" in str(error)
            else:
                raise AssertionError("Actual quota denial incorrectly produced a Confirm review.")
            assert (
                await storage("owned-quota") == before_quota == ()
                and await resource("owned-quota") is None
            )
            assert service.operation_count == 0 and not list(
                Path(connection.directory.name).glob("helm-inputs-*")
            )
            faults["quota"] = {
                "native_helm_preparation_separate": True,
                "named_create_admission_denied_before_confirm": True,
                "release_storage_absent": True,
                "ordinary_resource_absent": True,
            }
            checks.append(
                "actual-quota-admission-refused-before-confirm-no-persistent-product-write"
            )
        oci_receipt = await finish_oci_catalog_case(service.catalog, oci)
        await service.catalog.update("owned")
        await service.catalog.remove("owned")
        assert not service.catalog.snapshot.repositories
        checks.append("production-catalog-update-remove")
        await service.close()
        assert service.operation_count == 0 and not list(
            Path(connection.directory.name).glob("helm-*")
        )
        checks.append("owned-process-private-files-service-drained")
        return {
            "version": pin.version,
            "driver": driver.value,
            "namespace": namespace,
            "checks": checks,
            "operations": operations,
            "oci": oci_receipt,
            "faults": faults,
            "scope": "Production catalog/service and lifecycle public controls with actual pinned native tools; root catalog/editor routes have separate source/installed/native terminal evidence.",
        }
    finally:
        if service is not None:
            await service.close()
        await sessions.close()
        await listener.cleanup()
