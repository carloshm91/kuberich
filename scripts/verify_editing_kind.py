"""M02: real strict dry-run, conditional edit, validation/conflict/RBAC on owned kind."""

import argparse
import asyncio
import json
import stat
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.editing import editable_manifest
from kuberich.domain.mutations import MutationState
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.editing import EditingService
from kuberich.services.mutations import MutationManager
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from scripts.owned_kind import NODE_IMAGE, OwnedCluster, owned_cluster


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    namespace = "kuberich-owned-editor"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    catalog = load_catalog(request, {})
    sessions = SessionService(catalog, request)
    manager = MutationManager()
    sessions.before_close = manager.stop_for_client
    before = cluster.path.read_bytes()
    editors: list[EditingService] = []
    denied: KubernetesSession | None = None
    paths: list[Path] = []
    try:
        await sessions.connect(cluster.context)
        connection, identity = sessions.client, sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        api = client.CoreV1Api(connection.api)
        await api.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace)))
        obj = await api.create_namespaced_config_map(
            namespace,
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(
                    name="owned-one", annotations={"preserved": "original"}
                ),
                data={"original": "owned-original"},
            ),
        )
        resource = (await ResourceReader(connection).discover()).find("configmaps")
        target = ResourceTarget(
            identity, "", "configmaps", namespace, "owned-one", obj.metadata.uid
        )
        source = EditingService(
            connection, resource, target, AccessPolicy(False), lambda: sessions.client is connection
        )
        editors.append(source)
        file = await source.open()
        paths.append(file.path)
        assert stat.S_IMODE(file.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(file.path.parent.stat().st_mode) == 0o700
        assert (await source.prepare())[0] is None
        assert (
            await api.read_namespaced_config_map("owned-one", namespace)
        ).metadata.resource_version == obj.metadata.resource_version
        assert source.snapshot is not None
        data = editable_manifest(source.snapshot)
        data["data"]["edited"] = "owned-edit"
        file.path.write_text(json.dumps(data))
        intent, preview = await source.prepare()
        assert intent is not None and "owned-edit" not in preview
        try:
            source.confirm(intent)
        except AppError:
            pass
        else:
            raise AssertionError("Edit was confirmed before server validation")
        assert (await source.validate()).state is MutationState.SUCCEEDED
        dry = await api.read_namespaced_config_map("owned-one", namespace)
        assert (
            dry.data == obj.data and dry.metadata.resource_version == obj.metadata.resource_version
        )
        proof = source.confirm(intent)
        result = await manager.wait(manager.start(source, proof))
        assert result.state is MutationState.SUCCEEDED
        changed = await api.read_namespaced_config_map("owned-one", namespace)
        assert changed.data == {"original": "owned-original", "edited": "owned-edit"}
        assert changed.metadata.annotations == {"preserved": "original"}
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert (
            await api.read_namespaced_config_map("owned-one", namespace)
        ).metadata.resource_version == changed.metadata.resource_version

        conflict = EditingService(connection, resource, target, AccessPolicy(False), lambda: True)
        editors.append(conflict)
        conflict_file = await conflict.open()
        paths.append(conflict_file.path)
        assert conflict.snapshot is not None
        data = editable_manifest(conflict.snapshot)
        data["data"]["edited"] = "must-not-overwrite"
        conflict_file.path.write_text(json.dumps(data))
        assert (await conflict.prepare())[0] is not None
        await api.patch_namespaced_config_map(
            "owned-one", namespace, {"metadata": {"annotations": {"concurrent": "change"}}}
        )
        assert (await conflict.validate()).state is MutationState.CONFLICT
        assert (await api.read_namespaced_config_map("owned-one", namespace)).data[
            "edited"
        ] == "owned-edit"

        invalid = EditingService(connection, resource, target, AccessPolicy(False), lambda: True)
        editors.append(invalid)
        invalid_file = await invalid.open()
        paths.append(invalid_file.path)
        assert invalid.snapshot is not None
        data = editable_manifest(invalid.snapshot)
        data["notARealField"] = "strict-rejection"
        invalid_file.path.write_text(json.dumps(data))
        assert (await invalid.prepare())[0] is not None
        assert (await invalid.validate()).state is MutationState.REJECTED
        assert (await api.read_namespaced_config_map("owned-one", namespace)).data[
            "edited"
        ] == "owned-edit"

        rbac = client.RbacAuthorizationV1Api(connection.api)
        await rbac.create_namespaced_role(
            namespace,
            client.V1Role(
                metadata=client.V1ObjectMeta(name="get-only"),
                rules=[
                    client.V1PolicyRule(api_groups=[""], resources=["configmaps"], verbs=["get"])
                ],
            ),
        )
        await rbac.create_namespaced_role_binding(
            namespace,
            client.V1RoleBinding(
                metadata=client.V1ObjectMeta(name="get-only"),
                role_ref=client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="Role", name="get-only"
                ),
                subjects=[client.RbacV1Subject(kind="User", name="owned-editor-reader")],
            ),
        )
        denied = KubernetesSession(
            catalog.select(cluster.context, ConnectionOverrides(as_user="owned-editor-reader")), 15
        )
        await denied.open()
        restricted = EditingService(denied, resource, target, AccessPolicy(False), lambda: True)
        editors.append(restricted)
        denied_file = await restricted.open()
        paths.append(denied_file.path)
        assert restricted.snapshot is not None
        data = editable_manifest(restricted.snapshot)
        data["data"]["denied"] = "must-not-apply"
        denied_file.path.write_text(json.dumps(data))
        assert (await restricted.prepare())[0] is not None
        assert (await restricted.validate()).state is MutationState.DENIED
        assert "denied" not in (await api.read_namespaced_config_map("owned-one", namespace)).data

        await api.delete_namespaced_config_map("owned-one", namespace)
        replacement = await api.create_namespaced_config_map(
            namespace,
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name="owned-one"), data={"replacement": "preserved"}
            ),
        )
        assert replacement.metadata.uid != target.uid
        assert (await conflict.validate()).state is MutationState.STALE
        assert (await api.read_namespaced_config_map("owned-one", namespace)).data == {
            "replacement": "preserved"
        }
        for editor in editors:
            await editor.close_file()
        assert all(not path.parent.exists() for path in paths)
        await manager.close()
        assert not manager._live and cluster.path.read_bytes() == before
        return {
            "node_image": NODE_IMAGE,
            "checks": [
                "private-draft-permissions",
                "no-op-no-version-change",
                "dry-run-no-persistence",
                "exact-confirmed-edit",
                "payload-preserved",
                "single-use-confirmation",
                "concurrent-version-refused",
                "strict-unknown-field-rejection",
                "actual-dry-run-rbac-denial",
                "same-name-replacement-refused",
                "private-files-cleaned",
                "caller-config-unchanged",
            ],
        }
    finally:
        try:
            for editor in editors:
                await editor.close_file()
        finally:
            await manager.close()
            if denied is not None:
                await denied.close()
            await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", type=Path, default=Path("artifacts/cluster/editing.json"))
    arguments = parser.parse_args()
    with owned_cluster(arguments.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
    arguments.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Real owned-kind manifest editing trials passed.", flush=True)


if __name__ == "__main__":
    main()
