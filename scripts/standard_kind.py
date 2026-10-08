"""B05 real API/Pilot qualification, invoked only inside the owned-kind verifier."""

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import ResourceCommand
from kuberich.services.resources import ResourceReader
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from scripts.owned_kind import SHELL_IMAGE


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
    reader: ResourceReader, catalog: KubeCatalog, path: Path, context: str
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
        STANDARD_RESOURCES, fixtures(namespace, volume, storage), strict=True
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

    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-standard-views"),
        catalog=catalog,
        connection=ConnectionRequest(
            kubeconfig=str(path), context=context, namespace=namespace, timeout=15
        ),
        initial_command=ResourceCommand(STANDARD_RESOURCES[0]),
    )
    evidence = []
    async with app.run_test(size=(120, 35)) as pilot:
        for definition in STANDARD_RESOURCES:
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
    assert app._render_task is not None and app._render_task.done()
    assert app._view_task is not None and app._view_task.done()
    return {
        "standard_resources": evidence,
        "standard_secret_payload_hidden": True,
        "standard_owned_ui_closed": True,
    }
