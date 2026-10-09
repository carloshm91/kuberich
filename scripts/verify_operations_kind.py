"""M04 actual deletion/finalizers, mixed RBAC batches and batch/v1 Job operations."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client
from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.mutations import MutationState
from kuberich.domain.operations import DeleteOptions, ResourceAction
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.operations import BatchDeleteService, ResourceOperationService
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    namespace = "kuberich-owned-operations"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    sessions = SessionService(load_catalog(request, {}), request)
    before = cluster.path.read_bytes()
    delegated: KubernetesSession | None = None
    checks: list[str] = []
    try:
        await sessions.connect(cluster.context)
        connection, identity = sessions.client, sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        core, batch = client.CoreV1Api(connection.api), client.BatchV1Api(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        discovery = await ResourceReader(connection).discover()

        def source(
            family: str,
            name: str,
            uid: str,
            action: ResourceAction,
            *,
            owner: KubernetesSession | None = None,
            readonly: bool = False,
        ) -> ResourceOperationService:
            group = "batch" if family in {"jobs", "cronjobs"} else ""
            return ResourceOperationService(
                owner or connection,
                discovery.find(family, group=group),
                ResourceTarget(identity, group, family, namespace, name, uid),
                AccessPolicy(readonly),
                lambda: sessions.client is connection,
                action,
            )

        async def configmap(name: str, *, finalizer: bool = False) -> Any:
            return await core.create_namespaced_config_map(
                namespace,
                client.V1ConfigMap(
                    metadata=client.V1ObjectMeta(
                        name=name, finalizers=["example.io/owned-cleanup"] if finalizer else None
                    ),
                    data={"owned": "synthetic-private-value"},
                ),
            )

        async def absent(name: str) -> None:
            async with asyncio.timeout(30):
                while True:
                    try:
                        await core.read_namespaced_config_map(name, namespace)
                    except ApiException as error:
                        assert error.status == 404
                        return
                    await asyncio.sleep(0.1)

        for propagation, grace in (("Foreground", None), ("Background", 0), ("Orphan", 30)):
            name = "owned-" + propagation.lower()
            value = await configmap(name)
            owner = source("configmaps", name, value.metadata.uid, ResourceAction.DELETE)
            intent = await owner.prepare(DeleteOptions(propagation, grace))
            proof = owner.confirm(intent)
            result = await owner.execute(proof)
            assert result.state in {MutationState.SUCCEEDED, MutationState.ACCEPTED}, result
            await absent(name)
            assert (await owner.execute(proof)).state is MutationState.BLOCKED
            checks.append("actual-delete-" + propagation.lower())

        value = await configmap("owned-finalizer", finalizer=True)
        owner = source("configmaps", value.metadata.name, value.metadata.uid, ResourceAction.DELETE)
        intent = await owner.prepare()
        result = await owner.execute(owner.confirm(intent))
        assert (
            result.state is MutationState.ACCEPTED and "example.io/owned-cleanup" in result.message
        )
        retained = await core.read_namespaced_config_map("owned-finalizer", namespace)
        assert retained.metadata.deletion_timestamp
        assert "example.io/owned-cleanup" in retained.metadata.finalizers
        await core.patch_namespaced_config_map(
            "owned-finalizer", namespace, {"metadata": {"finalizers": None}}
        )
        await absent("owned-finalizer")
        checks.append("actual-finalizer-pending-without-removal")

        value = await configmap("owned-stale")
        owner = source("configmaps", value.metadata.name, value.metadata.uid, ResourceAction.DELETE)
        intent = await owner.prepare()
        await core.delete_namespaced_config_map("owned-stale", namespace)
        await absent("owned-stale")
        replacement = await configmap("owned-stale")
        result = await owner.execute(owner.confirm(intent))
        assert result.state is MutationState.STALE
        assert (
            await core.read_namespaced_config_map("owned-stale", namespace)
        ).metadata.uid == replacement.metadata.uid
        checks.append("actual-same-name-replacement-refused")

        value = await configmap("owned-version")
        owner = source("configmaps", value.metadata.name, value.metadata.uid, ResourceAction.DELETE)
        intent = await owner.prepare()
        proof = owner.confirm(intent)
        await core.patch_namespaced_config_map(
            "owned-version", namespace, {"metadata": {"annotations": {"changed": "yes"}}}
        )
        assert (await owner.execute(proof)).state is MutationState.CONFLICT
        checks.append("actual-version-change-refused")

        for name in ("owned-allowed", "owned-denied", "owned-batch-finalizer"):
            await configmap(name, finalizer=name.endswith("finalizer"))
        reader = "kuberich-owned-operation-user"
        rbac = client.RbacAuthorizationV1Api(connection.api)
        await rbac.create_namespaced_role(
            namespace,
            client.V1Role(
                metadata=client.V1ObjectMeta(name="owned-operations"),
                rules=[
                    client.V1PolicyRule(api_groups=[""], resources=["configmaps"], verbs=["get"]),
                    client.V1PolicyRule(
                        api_groups=[""],
                        resources=["configmaps"],
                        verbs=["delete"],
                        resource_names=["owned-allowed", "owned-batch-finalizer"],
                    ),
                    client.V1PolicyRule(
                        api_groups=["batch"], resources=["cronjobs"], verbs=["get", "patch"]
                    ),
                ],
            ),
        )
        await rbac.create_namespaced_role_binding(
            namespace,
            client.V1RoleBinding(
                metadata=client.V1ObjectMeta(name="owned-operations"),
                role_ref=client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="Role", name="owned-operations"
                ),
                subjects=[
                    client.RbacV1Subject(
                        kind="User", name=reader, api_group="rbac.authorization.k8s.io"
                    )
                ],
            ),
        )
        delegated = KubernetesSession(
            sessions.catalog.select(cluster.context, ConnectionOverrides(as_user=reader)), 15
        )
        await delegated.open()
        sources = []
        for name in ("owned-allowed", "owned-denied", "owned-batch-finalizer"):
            value = await core.read_namespaced_config_map(name, namespace)
            sources.append(
                source(
                    "configmaps", name, value.metadata.uid, ResourceAction.DELETE, owner=delegated
                )
            )
        deletion = BatchDeleteService(tuple(sources))
        prepared = await deletion.prepare(DeleteOptions("Background"))
        result = await deletion.execute(deletion.confirm(prepared))
        assert result.state is MutationState.REJECTED
        assert deletion.results[0][1].state in {MutationState.SUCCEEDED, MutationState.ACCEPTED}
        assert deletion.results[1][1].state is MutationState.DENIED
        assert deletion.results[2][1].state is MutationState.ACCEPTED
        await absent("owned-allowed")
        assert (
            await core.read_namespaced_config_map("owned-denied", namespace)
        ).metadata.deletion_timestamp is None
        pending = await core.read_namespaced_config_map("owned-batch-finalizer", namespace)
        assert pending.metadata.finalizers == ["example.io/owned-cleanup"]
        checks.append("actual-mixed-batch-rbac-finalizers-independent-results")

        template = client.V1PodTemplateSpec(
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="app", image=SHELL_IMAGE, command=["sh", "-c", "exit 0"]
                    )
                ],
                tolerations=[client.V1Toleration(operator="Exists")],
            )
        )
        value = await batch.create_namespaced_cron_job(
            namespace,
            client.V1CronJob(
                metadata=client.V1ObjectMeta(name="owned-cronjob"),
                spec=client.V1CronJobSpec(
                    schedule="0 0 1 1 *",
                    suspend=True,
                    job_template=client.V1JobTemplateSpec(
                        metadata=client.V1ObjectMeta(labels={"owned": "manual"}),
                        spec=client.V1JobSpec(template=template),
                    ),
                ),
            ),
        )
        cron = source("cronjobs", value.metadata.name, value.metadata.uid, ResourceAction.RESUME)
        intent = await cron.prepare()
        assert (await cron.execute(cron.confirm(intent))).state is MutationState.SUCCEEDED
        assert (
            await batch.read_namespaced_cron_job("owned-cronjob", namespace)
        ).spec.suspend is False
        cron.action = ResourceAction.SUSPEND
        intent = await cron.prepare()
        assert (await cron.execute(cron.confirm(intent))).state is MutationState.SUCCEEDED
        assert (
            await batch.read_namespaced_cron_job("owned-cronjob", namespace)
        ).spec.suspend is True
        checks.append("actual-cronjob-resume-suspend")

        cron.action = ResourceAction.TRIGGER
        intent = await cron.prepare()
        result = await cron.execute(cron.confirm(intent))
        assert result.state is MutationState.SUCCEEDED
        name = json.loads(intent.body)["metadata"]["name"]
        job = await batch.read_namespaced_job(name, namespace)
        assert job.metadata.uid in result.message and name in result.message
        assert job.metadata.labels == {"owned": "manual"}
        async with asyncio.timeout(180):
            while not (await batch.read_namespaced_job(name, namespace)).status.succeeded:
                await asyncio.sleep(0.2)
        again = await cron.prepare()
        assert json.loads(again.body)["metadata"]["name"] == name
        assert (await cron.execute(cron.confirm(again))).state is MutationState.CONFLICT
        assert len((await batch.list_namespaced_job(namespace)).items) == 1
        checks.append("actual-suspended-cronjob-manual-job-completion-and-duplicate-prevention")

        denied = source(
            "cronjobs", "owned-cronjob", value.metadata.uid, ResourceAction.TRIGGER, owner=delegated
        )
        intent = await denied.prepare()
        assert (await denied.execute(denied.confirm(intent))).state is MutationState.DENIED
        assert len((await batch.list_namespaced_job(namespace)).items) == 1
        checks.append("actual-job-create-rbac-denied")

        running_template = client.V1PodTemplateSpec(
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(name="app", image=SHELL_IMAGE, command=["sleep", "3600"])
                ],
                tolerations=[client.V1Toleration(operator="Exists")],
            )
        )
        value = await batch.create_namespaced_job(
            namespace,
            client.V1Job(
                metadata=client.V1ObjectMeta(name="owned-job"),
                spec=client.V1JobSpec(suspend=True, template=running_template),
            ),
        )
        async with asyncio.timeout(60):
            while not any(
                condition.type == "Suspended" and condition.status == "True"
                for condition in (
                    await batch.read_namespaced_job("owned-job", namespace)
                ).status.conditions
                or []
            ):
                await asyncio.sleep(0.1)
        job_owner = source("jobs", "owned-job", value.metadata.uid, ResourceAction.RESUME)
        intent = await job_owner.prepare()
        result = await job_owner.execute(job_owner.confirm(intent))
        assert result.state is MutationState.SUCCEEDED, result
        assert (await batch.read_namespaced_job("owned-job", namespace)).spec.suspend is False
        async with asyncio.timeout(180):
            while (await batch.read_namespaced_job("owned-job", namespace)).status.ready != 1:
                await asyncio.sleep(0.1)
        job_owner.action = ResourceAction.SUSPEND
        intent = await job_owner.prepare()
        result = await job_owner.execute(job_owner.confirm(intent))
        assert result.state is MutationState.SUCCEEDED, result
        assert (await batch.read_namespaced_job("owned-job", namespace)).spec.suspend is True
        checks.append("actual-job-resume-suspend")

        readonly = source(
            "configmaps",
            "owned-version",
            (await core.read_namespaced_config_map("owned-version", namespace)).metadata.uid,
            ResourceAction.DELETE,
            readonly=True,
        )
        try:
            await readonly.prepare()
            raise AssertionError("Read-only delete was accepted")
        except AppError:
            pass
        assert cluster.path.read_bytes() == before
        checks.extend(("readonly-refused", "caller-config-unchanged"))
        return {"node_image": NODE_IMAGE, "shell_image": SHELL_IMAGE, "checks": checks}
    finally:
        if delegated is not None:
            await delegated.close()
        await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", type=Path, default="artifacts/cluster/operations.json")
    args = parser.parse_args()
    with owned_cluster(args.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind resource operation checks passed.", flush=True)


if __name__ == "__main__":
    main()
