"""M01: real guarded annotation writes, stale preconditions and RBAC on owned kind."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.mutations import conditional_patch
from kuberich.config.catalog import load_catalog
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.mutations import MutationState
from kuberich.domain.targets import ResourceTarget
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import MutationManager, MutationService
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from scripts.owned_kind import NODE_IMAGE, OwnedCluster, owned_cluster


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    namespace = "kuberich-owned-mutation"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    catalog = load_catalog(request, {})
    sessions = SessionService(catalog, request)
    manager = MutationManager()
    sessions.before_close = manager.stop_for_client
    before = cluster.path.read_bytes()
    denied: KubernetesSession | None = None
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
                    name="owned-one", annotations={"preserved": "owned-original"}
                ),
                data={"value": "owned-config-payload"},
            ),
        )
        resource = (await ResourceReader(connection).discover()).find("configmaps")
        target = ResourceTarget(
            identity, "", "configmaps", namespace, "owned-one", obj.metadata.uid
        )
        source = MutationService(
            connection, resource, target, AccessPolicy(False), lambda: sessions.client is connection
        )
        intent = await source.prepare_annotation("example.io/review", "owned-success")
        proof = source.confirm(intent)
        operation = manager.start(source, proof)
        assert (await manager.wait(operation)).state is MutationState.SUCCEEDED
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        observed = await api.read_namespaced_config_map("owned-one", namespace)
        assert observed.metadata.annotations == {
            "preserved": "owned-original",
            "example.io/review": "owned-success",
        }
        assert observed.data == {"value": "owned-config-payload"}

        # Execute an actual conditional PATCH against a server-changed version.
        # The low-level transport is explicitly guarded by the same source policy.
        stale = await source.prepare_annotation("example.io/review", "must-not-apply")
        await api.patch_namespaced_config_map(
            "owned-one", namespace, {"metadata": {"annotations": {"server-change": "owned"}}}
        )
        result = await conditional_patch(connection, stale, source.require_current)
        assert result.state is MutationState.REJECTED  # Kubernetes JSON Patch test failure: 422.
        observed = await api.read_namespaced_config_map("owned-one", namespace)
        assert observed.metadata.annotations["example.io/review"] == "owned-success"
        assert observed.metadata.annotations["server-change"] == "owned"

        stale_uid = await source.prepare_annotation(
            "example.io/review", "must-not-apply-replacement"
        )
        await api.delete_namespaced_config_map("owned-one", namespace)
        replacement = await api.create_namespaced_config_map(
            namespace,
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name="owned-one"), data={"replacement": "unchanged"}
            ),
        )
        assert replacement.metadata.uid != target.uid
        assert (
            await conditional_patch(connection, stale_uid, source.require_current)
        ).state is MutationState.REJECTED
        assert (
            await api.read_namespaced_config_map("owned-one", namespace)
        ).metadata.annotations is None
        assert (await source.execute(source.confirm(stale_uid))).state is MutationState.STALE

        rbac = client.RbacAuthorizationV1Api(connection.api)
        reader = "kuberich-owned-patch-reader"
        await rbac.create_namespaced_role(
            namespace,
            client.V1Role(
                metadata=client.V1ObjectMeta(name="owned-reader"),
                rules=[
                    client.V1PolicyRule(api_groups=[""], resources=["configmaps"], verbs=["get"])
                ],
            ),
        )
        await rbac.create_namespaced_role_binding(
            namespace,
            client.V1RoleBinding(
                metadata=client.V1ObjectMeta(name="owned-reader"),
                role_ref=client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="Role", name="owned-reader"
                ),
                subjects=[
                    client.RbacV1Subject(
                        api_group="rbac.authorization.k8s.io", kind="User", name=reader
                    )
                ],
            ),
        )
        denied = KubernetesSession(
            catalog.select(cluster.context, ConnectionOverrides(as_user=reader)), 15
        )
        await denied.open()
        current_target = ResourceTarget(
            identity, "", "configmaps", namespace, "owned-one", replacement.metadata.uid
        )
        denied_source = MutationService(
            denied, resource, current_target, AccessPolicy(False), lambda: True
        )
        denied_intent = await denied_source.prepare_annotation(
            "example.io/review", "must-not-apply-denied"
        )
        assert (
            await denied_source.execute(denied_source.confirm(denied_intent))
        ).state is MutationState.DENIED
        assert (
            await api.read_namespaced_config_map("owned-one", namespace)
        ).metadata.annotations is None
        await manager.close()
        assert not manager._live
        assert cluster.path.read_bytes() == before
        return {
            "node_image": NODE_IMAGE,
            "checks": [
                "real-annotation-write",
                "payload-preserved",
                "atomic-version-test",
                "atomic-uid-test",
                "replacement-refused",
                "actual-rbac-denial",
                "single-use-confirmation",
                "caller-config-unchanged",
            ],
        }
    finally:
        await manager.close()
        if denied is not None:
            await denied.close()
        await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", default="artifacts/cluster/mutations.json", type=Path)
    arguments = parser.parse_args()
    with owned_cluster(arguments.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
    arguments.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Real owned-kind guarded mutation trials passed.", flush=True)


if __name__ == "__main__":
    main()
