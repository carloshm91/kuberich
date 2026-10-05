"""C01-C03 qualification on a newly created, explicitly owned disposable kind cluster."""

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import yaml
from kubernetes_asyncio.client import CoreV1Api, V1Namespace, V1ObjectMeta

from kubetrol.config.catalog import load_catalog
from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.domain.watches import EventType, SyncStatus
from kubetrol.services.resources import ResourceReader
from kubetrol.services.sessions import SessionService
from kubetrol.services.watches import ListWatch

NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)


async def verify_watch(reader: ResourceReader, resource) -> dict[str, object]:
    """Mutate only fixtures inside this script's newly created local kind cluster."""
    api = CoreV1Api(reader.session.api)
    namespace = "kubetrol-watch-" + uuid4().hex[:12]
    created_namespace = await api.create_namespace(
        V1Namespace(metadata=V1ObjectMeta(name=namespace))
    )
    name = "owned-watch-example"
    finished = asyncio.Event()
    uid = None
    steps = []

    async def sink(update) -> None:
        nonlocal uid
        if update.status is SyncStatus.SNAPSHOT:
            assert all(record.name != name for record in update.snapshot.items)
            # This write happens between LIST and opening WATCH: it must not be lost.
            await api.create_namespaced_config_map(
                namespace,
                {"metadata": {"name": name}, "data": {"stage": "created"}},
            )
        if update.event is None or update.event.record is None:
            return
        record = update.event.record
        # Namespace controllers may also publish kube-root-ca.crt here.
        if record.name != name:
            return
        assert record.name == name and record.namespace == namespace and record.uid
        target_items = tuple(item for item in update.snapshot.items if item.name == name)
        if update.event.type is EventType.ADDED and uid is None:
            uid = record.uid
            steps.append("ADDED")
            assert len(target_items) == 1
            await api.replace_namespaced_config_map(
                name,
                namespace,
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": name, "resourceVersion": record.resource_version},
                    "data": {"stage": "modified"},
                },
            )
        elif update.event.type is EventType.MODIFIED:
            assert record.uid == uid and record.manifest["data"]["stage"] == "modified"
            steps.append("MODIFIED")
            await api.delete_namespaced_config_map(
                name,
                namespace,
                body={"preconditions": {"uid": uid}},
            )
        elif update.event.type is EventType.DELETED:
            assert record.uid == uid and not target_items
            steps.append("DELETED")
            await api.create_namespaced_config_map(
                namespace,
                {"metadata": {"name": name}, "data": {"stage": "recreated"}},
            )
        elif update.event.type is EventType.ADDED:
            assert record.uid != uid and len(target_items) == 1
            assert target_items[0].uid == record.uid
            steps.append("RECREATED")
            finished.set()

    task = asyncio.create_task(ListWatch(reader).run(resource, namespace, sink))
    completion = asyncio.create_task(finished.wait())
    try:
        done, _ = await asyncio.wait(
            {task, completion}, timeout=30, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            await task
        assert finished.is_set() and steps == ["ADDED", "MODIFIED", "DELETED", "RECREATED"]
    finally:
        completion.cancel()
        task.cancel()
        results = await asyncio.gather(task, completion, return_exceptions=True)
        await api.delete_namespace(
            namespace,
            body={"preconditions": {"uid": created_namespace.metadata.uid}},
        )
    assert isinstance(results[0], asyncio.CancelledError)
    return {
        "real_list_watch_gap": True,
        "real_added_modified_deleted": True,
        "real_same_name_new_uid": True,
        "watch_cancellation_awaited": True,
        "owned_watch_fixture_deleted": True,
    }


async def verify(path: Path, context: str) -> dict[str, object]:
    request = ConnectionRequest(kubeconfig=str(path), context=context, timeout=15)
    catalog = load_catalog(request, {})
    before = path.read_bytes()
    sessions = SessionService(catalog, request)
    try:
        first = await sessions.connect(context)
        assert first.state is ConnectionState.CONNECTED and not first.insecure
        assert {"default", "kube-system"} <= set(first.namespaces)
        api = sessions.client.api
        scoped = sessions.select_namespace("kube-system")
        assert scoped.identity.generation > first.identity.generation
        assert scoped.identity.connection_id == first.identity.connection_id
        second = await sessions.connect(context)
        assert second.state is ConnectionState.CONNECTED
        assert second.identity.connection_id != first.identity.connection_id
        assert second.namespace == "kube-system"
        assert api.rest_client.pool_manager.closed
        reader = ResourceReader(sessions.client)
        discovery = await reader.discover()
        assert not discovery.partial
        pods = discovery.find("po")
        assert pods.namespaced and {"list", "watch"} <= pods.verbs
        scoped_pods = await reader.list(pods, "kube-system", page_size=2)
        assert scoped_pods.namespace == "kube-system" and scoped_pods.resource_version
        assert len(scoped_pods.items) > 2
        assert all(record.uid and record.namespace == "kube-system" for record in scoped_pods.items)
        assert all(record.manifest["kind"] == "Pod" for record in scoped_pods.items)
        namespaces = discovery.find("namespaces")
        assert not namespaces.namespaced
        namespace_snapshot = await reader.list(namespaces, page_size=1)
        assert namespace_snapshot.resource_version and len(namespace_snapshot.items) > 1
        assert {"default", "kube-system"} <= {record.name for record in namespace_snapshot.items}
        assert all(record.uid and record.namespace is None for record in namespace_snapshot.items)
        deployments = discovery.find("deployments", group="apps")
        assert deployments.api_version == "apps/v1"
        deployment_snapshot = await reader.list(deployments, "kube-system", page_size=1)
        assert deployment_snapshot.resource_version and deployment_snapshot.items
        watch_evidence = await verify_watch(reader, discovery.find("configmaps"))
        assert path.read_bytes() == before
        active = sessions.client.api
    finally:
        await sessions.close()
    assert active.rest_client.pool_manager.closed
    return {
        "result": "passed",
        "tls_verified": True,
        "client_certificate_auth": True,
        "namespace_listing": True,
        "scope_generation_changed": True,
        "reopened_client_distinct": True,
        "prior_and_current_clients_closed": True,
        "kubeconfig_unchanged": True,
        "namespace_count": len(first.namespaces),
        "api_discovery": True,
        "discovery_complete": True,
        "core_and_named_groups": True,
        "resource_aliases": True,
        "namespaced_and_cluster_scoped_listing": True,
        "consistent_paginated_snapshots": True,
        "collection_versions_and_item_uids": True,
        "discovered_resource_count": len(discovery.resources),
        "scoped_pod_count": len(scoped_pods.items),
        **watch_evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, help="verified kind v0.33.0 binary")
    parser.add_argument("--evidence", default="artifacts/cluster/context-sessions.json")
    arguments = parser.parse_args()
    name = "kubetrol-test-" + uuid4().hex[:12]
    with TemporaryDirectory(prefix="kubetrol-kind-") as directory:
        path = Path(directory) / "owned-kubeconfig"
        environment = {**os.environ, "KUBECONFIG": str(path)}
        command = [
            arguments.kind,
            "create",
            "cluster",
            "--name",
            name,
            "--kubeconfig",
            str(path),
            "--image",
            NODE_IMAGE,
            "--wait",
            "180s",
        ]
        try:
            print("Creating owned disposable kind cluster.", flush=True)
            subprocess.run(command, env=environment, check=True, timeout=300)
            # Local kind output is never read through the ambient default path.
            data = yaml.safe_load(path.read_text())
            context = "kind-" + name
            assert data["current-context"] == context
            evidence = asyncio.run(verify(path, context))
            output = Path(arguments.evidence)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"kind": "0.33.0", "node_image": NODE_IMAGE, **evidence}, indent=2)
                + "\n"
            )
            print(
                "Real API, discovery, snapshots, list/watch changes, TLS, scope and cleanup passed.",
                flush=True,
            )
        finally:
            subprocess.run(
                [arguments.kind, "delete", "cluster", "--name", name],
                env=environment,
                check=True,
                timeout=90,
            )
            print("Owned disposable cluster deleted.", flush=True)


if __name__ == "__main__":
    main()
