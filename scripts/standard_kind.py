"""B05 real API/Pilot qualification, invoked only inside the owned-kind verifier."""

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.metrics import MetricStatus
from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import ResourceCommand
from kuberich.services.resources import ResourceReader
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from scripts.owned_kind import SHELL_IMAGE
from tests.support.workers import CoroutineCalls

BASELINE_RESOURCES = tuple(resource for resource in STANDARD_RESOURCES if not resource.curated)


@contextmanager
def presentation_owners(app: KubeRichApp) -> Iterator[tuple[CoroutineCalls, CoroutineCalls]]:
    """Observe the actual subscription/render callers at their public I/O ports."""
    observations, renders = CoroutineCalls(), CoroutineCalls()
    with (
        patch.object(app.presenter, "observe", observations.observe(app.presenter.observe)),
        patch.object(app.views.foreground, "wait", renders.observe(app.views.foreground.wait)),
    ):
        yield observations, renders


def fixtures(namespace: str, volume: str, storage: str) -> tuple[dict[str, Any], ...]:
    template: dict[str, Any] = {
        "metadata": {"labels": {"owned": "standard"}},
        "spec": {"containers": [{"name": "app", "image": SHELL_IMAGE}]},
    }
    selector = {"matchLabels": {"owned": "standard"}}
    return (
        {"spec": {"replicas": 0, "selector": selector, "template": template}},
        {"spec": {"replicas": 0, "selector": selector, "template": template}},
        {
            "spec": {
                "replicas": 0,
                "serviceName": "owned",
                "selector": selector,
                "template": template,
            }
        },
        {
            "spec": {
                "selector": selector,
                "template": {
                    **template,
                    "spec": {**template["spec"], "nodeSelector": {"kuberich-test-absent": "true"}},
                },
            }
        },
        {
            "spec": {
                "suspend": True,
                "completions": 1,
                "template": {**template, "spec": {**template["spec"], "restartPolicy": "Never"}},
            }
        },
        {
            "spec": {
                "schedule": "0 * * * *",
                "suspend": True,
                "jobTemplate": {
                    "spec": {
                        "template": {
                            **template,
                            "spec": {**template["spec"], "restartPolicy": "Never"},
                        }
                    }
                },
            }
        },
        {"spec": {"ports": [{"port": 8080}]}},
        {
            "subsets": [
                {
                    "addresses": [{"ip": "192.0.2.1"}],
                    "notReadyAddresses": [{"ip": "192.0.2.2"}],
                    "ports": [{"port": 8080}],
                }
            ]
        },
        {"spec": {"defaultBackend": {"service": {"name": "owned", "port": {"number": 8080}}}}},
        {"data": {"owned": "private-fixture-payload"}},
        {"type": "Opaque", "stringData": {"owned": "private-fixture-payload"}},
        {},  # Existing real owned node, rather than a synthetic Node object.
        {
            "spec": {
                "volumeName": volume,
                "storageClassName": "",
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "1Gi"}},
            }
        },
        {
            "spec": {
                "capacity": {"storage": "2Gi"},
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "",
                "persistentVolumeReclaimPolicy": "Retain",
                "hostPath": {"path": "/tmp/kuberich-owned-standard"},
                "claimRef": {"namespace": namespace, "name": "owned"},
            }
        },
        {
            "provisioner": "kubernetes.io/no-provisioner",
            "volumeBindingMode": "Immediate",
            "reclaimPolicy": "Retain",
            "allowVolumeExpansion": False,
        },
    )


async def verify_standard_resources(
    reader: ResourceReader,
    catalog: KubeCatalog,
    path: Path,
    context: str,
    *,
    evidence_dir: Path | None = None,
) -> dict[str, object]:
    namespace = "kuberich-test-standard-" + uuid4().hex[:10]
    volume, storage = namespace + "-pv", namespace + "-sc"
    sdk = reader.session.api
    assert sdk is not None

    async def write(endpoint: str, method: str, body: dict[str, Any]) -> Any:
        return await sdk.call_api(
            endpoint,
            method,
            body=body,
            response_types_map={200: "object", 201: "object"},
            auth_settings=["BearerToken"],
            header_params={
                "Content-Type": "application/merge-patch+json"
                if method == "PATCH"
                else "application/json"
            },
            _return_http_data_only=True,
            _request_timeout=15,
        )

    await write("/api/v1/namespaces", "POST", {"metadata": {"name": namespace}})
    discovery = await reader.discover()
    targets = {}
    resources = {}
    for definition, fixture in zip(
        BASELINE_RESOURCES, fixtures(namespace, volume, storage), strict=True
    ):
        resource = discovery.find(definition.name, group=definition.group)
        assert resource.namespaced == definition.namespaced
        resources[definition.name] = resource
        if definition.name == "nodes":
            node = (await reader.list(resource)).items[0]
            targets[definition.name] = (node.name, node.uid)
            continue
        name = (
            volume
            if definition.name == "persistentvolumes"
            else storage
            if definition.name == "storageclasses"
            else "owned"
        )
        created = await write(
            resource.path(namespace if resource.namespaced else None),
            "POST",
            {
                "apiVersion": resource.api_version,
                "kind": resource.kind,
                "metadata": {"name": name},
                **fixture,
            },
        )
        targets[definition.name] = (name, created["metadata"]["uid"])

    # Ordinary and independently uncertain budgets are controlled fixtures,
    # rather than accepting whatever completeness an existing system Pod has.
    pods = discovery.find("pods")
    budget = {
        "requests": {"cpu": "100m", "memory": "32Mi"},
        "limits": {"cpu": "1", "memory": "128Mi"},
    }
    controlled: dict[str, str] = {}
    for name in ("metrics-ordinary", "metrics-init"):
        spec: dict[str, Any] = {
            "terminationGracePeriodSeconds": 0,
            "containers": [
                {
                    "name": "app",
                    "image": SHELL_IMAGE,
                    "command": ["sh", "-c", "sleep 3600"],
                    "resources": budget,
                }
            ],
        }
        if name == "metrics-init":
            spec["initContainers"] = [
                {"name": "init", "image": SHELL_IMAGE, "command": ["sh", "-c", "true"]}
            ]
        created = await write(
            pods.path(namespace),
            "POST",
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": name},
                "spec": spec,
            },
        )
        controlled[name] = created["metadata"]["uid"]

    def retain_admitted(records: dict[str, Any]) -> None:
        if evidence_dir is None:
            return
        evidence_dir.mkdir(parents=True, exist_ok=True)
        admitted = {}
        for name in controlled:
            if name not in records:
                continue
            fixture = records[name]
            manifest = fixture.manifest
            admitted[name] = {
                "uid": fixture.uid,
                "namespace": fixture.namespace,
                "node": manifest["spec"].get("nodeName"),
                "phase": manifest.get("status", {}).get("phase"),
                "pod_allocated_resources": manifest.get("status", {}).get("allocatedResources"),
                "pod_enacted_resources": manifest.get("status", {}).get("resources"),
                "declared_resources": [
                    entry.get("resources") for entry in manifest["spec"]["containers"]
                ],
                "container_allocation_status": [
                    {key: entry.get(key) for key in ("name", "allocatedResources", "resources")}
                    for entry in manifest.get("status", {}).get("containerStatuses", [])
                ],
                "resize_conditions": [
                    entry
                    for entry in manifest.get("status", {}).get("conditions", [])
                    if entry.get("type") in {"PodResizePending", "PodResizeInProgress"}
                ],
                "has_init": bool(manifest["spec"].get("initContainers")),
            }
        (evidence_dir / "admitted-resource-status.json").write_text(
            json.dumps(admitted, indent=2) + "\n"
        )

    async with asyncio.timeout(180):
        while True:
            current = await reader.list(pods, namespace)
            records = {record.name: record for record in current.items}
            retain_admitted(records)
            if all(
                name in records
                and records[name].manifest.get("status", {}).get("phase") == "Running"
                for name in controlled
            ):
                break
            await asyncio.sleep(0.1)
    ordinary = records["metrics-ordinary"]
    uncertain = records["metrics-init"]
    assert ordinary.uid == controlled["metrics-ordinary"]
    assert uncertain.uid == controlled["metrics-init"]
    assert ordinary.manifest["spec"]["containers"][0]["resources"] == budget
    assert not any(
        ordinary.manifest["spec"].get(key) for key in ("initContainers", "overhead", "resources")
    )
    assert ordinary.manifest["status"]["containerStatuses"][0]["name"] == "app"
    assert ordinary.manifest["status"]["containerStatuses"][0]["allocatedResources"]
    assert ordinary.manifest["status"]["containerStatuses"][0]["resources"]
    assert uncertain.manifest["spec"]["initContainers"][0]["name"] == "init"
    assert (
        ordinary.manifest["spec"]["nodeName"]
        == uncertain.manifest["spec"]["nodeName"]
        == targets["nodes"][0]
    )

    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-standard-views"),
        catalog=catalog,
        connection=ConnectionRequest(
            kubeconfig=str(path), context=context, namespace=namespace, timeout=15
        ),
        initial_command=ResourceCommand(BASELINE_RESOURCES[0]),
    )
    evidence = []
    with presentation_owners(app) as (observations, renders):
        async with app.run_test(size=(120, 35)) as pilot:
            async with asyncio.timeout(30):
                while (
                    app.workspace.store.observation.status is not ViewStatus.LIVE
                    or targets["deployments"][1] not in app.standard_table.rows
                ):
                    await asyncio.sleep(0.01)
            await app.run_command("pods")
            async with asyncio.timeout(30):
                while (
                    app.state.view_kind != "pods"
                    or app.workspace.store.observation.metrics is None
                    or controlled["metrics-ordinary"] not in app.resources.rows
                    or controlled["metrics-init"] not in app.resources.rows
                ):
                    await asyncio.sleep(0.01)
            metrics = app.workspace.store.observation.metrics
            assert metrics is not None
            known_report = metrics.report(controlled["metrics-ordinary"])
            unknown_report = metrics.report(controlled["metrics-init"])
            if evidence_dir is not None:
                (evidence_dir / "observed-resource-budgets.json").write_text(
                    json.dumps(
                        {
                            "ordinary": {
                                "cpu_request": str(known_report.cpu.request),
                                "cpu_limit": str(known_report.cpu.limit),
                                "memory_request": str(known_report.memory.request),
                                "memory_limit": str(known_report.memory.limit),
                                "cpu_uncertain": known_report.cpu.uncertain,
                                "memory_uncertain": known_report.memory.uncertain,
                                "allocation_uncertain": known_report.allocation_uncertain,
                                "detail": known_report.detail,
                            },
                            "init": {
                                "cpu_uncertain": unknown_report.cpu.uncertain,
                                "detail": unknown_report.detail,
                            },
                        },
                        indent=2,
                    )
                    + "\n"
                )
            assert (
                known_report.status is MetricStatus.UNAVAILABLE and known_report.cpu.usage is None
            )
            assert not known_report.cpu.uncertain and not known_report.memory.uncertain
            assert not known_report.allocation_uncertain
            assert known_report.cpu.request == Decimal(".1") and known_report.cpu.limit == 1
            assert (
                known_report.memory.request == 32 * 2**20
                and known_report.memory.limit == 128 * 2**20
            )
            async with asyncio.timeout(30):
                while (
                    str(app.resources.get_cell(controlled["metrics-ordinary"], "cpu-req")) != "100"
                    or str(app.resources.get_cell(controlled["metrics-init"], "cpu-req"))
                    != "N/A (budget)"
                ):
                    await asyncio.sleep(0.01)
            for field, expected in (
                ("cpu-req", "100"),
                ("cpu-lim", "1000"),
                ("memory-req", "32"),
                ("memory-lim", "128"),
            ):
                assert (
                    str(app.resources.get_cell(controlled["metrics-ordinary"], field)) == expected
                )
            assert unknown_report.cpu.uncertain and "init" in unknown_report.detail
            assert (
                str(app.resources.get_cell(controlled["metrics-init"], "cpu-req")) == "N/A (budget)"
            )
            assert str(app.resources.get_cell(controlled["metrics-ordinary"], "cpu")) == "N/A"
            for definition in BASELINE_RESOURCES:
                name, uid = targets[definition.name]
                if app._resource_name != definition.name:
                    await pilot.press("colon")
                    app.command_input.value = definition.aliases[0]
                    await pilot.press("enter")
                async with asyncio.timeout(30):
                    while (
                        app.workspace.store.observation.status is not ViewStatus.LIVE
                        or uid not in app.standard_table._rows
                    ):
                        await asyncio.sleep(0.01)
                app.standard_table.move_cursor(row=app.standard_table.get_row_index(uid))
                await pilot.pause()
                assert app.standard_table.selected_uid == uid
                resource = resources[definition.name]
                if definition.name == "nodes":
                    async with asyncio.timeout(30):
                        while app.workspace.store.observation.metrics is None:
                            await asyncio.sleep(0.01)
                    metric_report = app.workspace.store.observation.metrics.report(uid)
                    assert metric_report.status is MetricStatus.UNAVAILABLE
                    assert (
                        metric_report.cpu.usage is None and metric_report.cpu.capacity is not None
                    )
                    assert metric_report.cpu.allocatable is not None
                    # The controlled init Pod on this exact Node establishes
                    # the uncertainty independently of the implementation result.
                    assert uncertain.manifest["spec"]["nodeName"] == name
                    assert metric_report.cpu.uncertain
                    async with asyncio.timeout(30):
                        while str(app.standard_table.get_cell(uid, "cpu-req")) != "N/A (budget)":
                            await asyncio.sleep(0.01)
                    assert str(app.standard_table.get_cell(uid, "cpu-req")) == "N/A (budget)"
                    assert str(app.standard_table.get_cell(uid, "cpu")) == "N/A"
                endpoint = resource.path(namespace if resource.namespaced else None) + "/" + name
                # A real metadata change must arrive over the active WATCH for every family.
                await write(
                    endpoint,
                    "PATCH",
                    {"metadata": {"annotations": {"kuberich-owned-standard": "watched"}}},
                )
                async with asyncio.timeout(30):
                    while app.workspace.store.observation.snapshot is None or not any(
                        item.uid == uid
                        and item.manifest["metadata"]
                        .get("annotations", {})
                        .get("kuberich-owned-standard")
                        == "watched"
                        for item in app.workspace.store.observation.snapshot.items
                    ):
                        await asyncio.sleep(0.01)
                assert app.standard_table.selected_uid == uid
                await pilot.press("y")
                async with asyncio.timeout(30):
                    while not isinstance(app.screen, InspectionScreen) or app.screen.result is None:
                        await asyncio.sleep(0.01)
                assert uid in app.screen.viewer.text
                assert "private-fixture-payload" not in app.screen.viewer.text
                await pilot.press("escape")
                evidence.append(
                    {
                        "resource": definition.name,
                        "api_version": resource.api_version,
                        "namespace_scoped": definition.namespaced,
                        "real_list_watch_get": True,
                        "uid_preserved": True,
                        "column_count": len(definition.columns),
                    }
                )
            output = Path("artifacts/ui")
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename="standard-owned-kind.svg", path=str(output.resolve()))
    assert app.sessions.client is None
    assert renders.tasks and all(task.done() for task in renders.tasks)
    assert observations.tasks and all(task.done() for task in observations.tasks)
    assert app.views.renderer.active_count == 0
    assert app.workspace.ownership.subscription_count == 0
    assert app.workspace.ownership.close_complete
    return {
        "standard_resources": evidence,
        "standard_secret_payload_hidden": True,
        "standard_owned_ui_closed": True,
        "ordinary_pod_budgets_known_without_metrics_api": True,
        "ordinary_cpu_request_cores": "0.1",
        "ordinary_cpu_limit_cores": "1",
        "ordinary_memory_request_bytes": 32 * 2**20,
        "ordinary_memory_limit_bytes": 128 * 2**20,
        "ordinary_actual_allocated_and_enacted_status_observed": True,
        "controlled_init_allocation_rendered_uncertain": True,
    }
