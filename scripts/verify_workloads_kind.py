"""M03: actual scale/restart/status/rollback and RBAC on an owned disposable kind cluster."""

import argparse
import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.config.catalog import load_catalog
from kubetrol.domain.connection_overrides import ConnectionOverrides
from kubetrol.domain.connections import ConnectionRequest
from kubetrol.domain.mutations import MutationState
from kubetrol.domain.targets import ResourceTarget
from kubetrol.domain.workloads import WorkloadAction
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.resources import ResourceReader
from kubetrol.services.sessions import SessionService
from kubetrol.services.workloads import WorkloadService
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    namespace = "kubetrol-owned-workload"
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
        core, apps = client.CoreV1Api(connection.api), client.AppsV1Api(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        discovery = await ResourceReader(connection).discover()

        def pod_template(labels: dict[str, str]) -> client.V1PodTemplateSpec:
            return client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="app", image=SHELL_IMAGE, command=["sh", "-c", "sleep 86400"]
                        )
                    ],
                    tolerations=[client.V1Toleration(operator="Exists")],
                ),
            )

        labels = {"app": "owned-workload"}
        deployment = await apps.create_namespaced_deployment(
            namespace,
            client.V1Deployment(
                metadata=client.V1ObjectMeta(name="owned-one"),
                spec=client.V1DeploymentSpec(
                    selector=client.V1LabelSelector(match_labels=labels),
                    template=pod_template(labels),
                    replicas=1,
                ),
            ),
        )
        resource = discovery.find("deployments", group="apps")
        target = ResourceTarget(
            identity, "apps", "deployments", namespace, "owned-one", deployment.metadata.uid
        )
        source = WorkloadService(
            connection, resource, target, AccessPolicy(False), lambda: sessions.client is connection
        )

        async def complete(owner: WorkloadService) -> None:
            result = await owner.monitor(lambda progress: None, timeout=180)
            assert result.state == "Complete", result

        async def apply(owner: WorkloadService, action: WorkloadAction, argument: str = "") -> None:
            intent = await owner.prepare(action, argument)
            proof = owner.confirm(intent)
            result = await owner.execute(proof)
            assert result.state is MutationState.SUCCEEDED, result
            assert (await owner.execute(proof)).state is MutationState.BLOCKED

        await complete(source)
        await apply(source, WorkloadAction.SCALE, "2")
        await complete(source)
        assert (await apps.read_namespaced_deployment("owned-one", namespace)).spec.replicas == 2
        checks.append("actual-deployment-scale-subresource")
        await apply(source, WorkloadAction.RESTART)
        await complete(source)
        assert (
            "kubectl.kubernetes.io/restartedAt"
            in (
                await apps.read_namespaced_deployment("owned-one", namespace)
            ).spec.template.metadata.annotations
        )
        checks.append("actual-restart-and-rollout-progress")
        await apply(source, WorkloadAction.ROLLBACK, "1")
        await complete(source)
        observed = await apps.read_namespaced_deployment("owned-one", namespace)
        assert observed.spec.replicas == 2 and not observed.spec.template.metadata.annotations
        checks.append("actual-explicit-replicaset-rollback")

        hpa = client.AutoscalingV2Api(connection.api)
        await hpa.create_namespaced_horizontal_pod_autoscaler(
            namespace,
            client.V2HorizontalPodAutoscaler(
                metadata=client.V1ObjectMeta(name="owned-hpa"),
                spec=client.V2HorizontalPodAutoscalerSpec(
                    scale_target_ref=client.V2CrossVersionObjectReference(
                        api_version="apps/v1", kind="Deployment", name="owned-one"
                    ),
                    min_replicas=1,
                    max_replicas=5,
                    metrics=[],
                ),
            ),
        )
        try:
            await source.prepare(WorkloadAction.SCALE, "3")
            raise AssertionError("HPA-controlled manual scale was accepted")
        except AppError as error:
            assert "HPA" in str(error)
        await hpa.delete_namespaced_horizontal_pod_autoscaler("owned-hpa", namespace)
        checks.append("actual-hpa-conflict-refusal")

        rbac = client.RbacAuthorizationV1Api(connection.api)
        reader = "kubetrol-owned-scale-user"
        role = client.V1Role(
            metadata=client.V1ObjectMeta(name="owned-scale"),
            rules=[
                client.V1PolicyRule(
                    api_groups=["apps"],
                    resources=["deployments", "deployments/scale"],
                    verbs=["get"],
                ),
                client.V1PolicyRule(
                    api_groups=["autoscaling"],
                    resources=["horizontalpodautoscalers"],
                    verbs=["list"],
                ),
            ],
        )
        await rbac.create_namespaced_role(namespace, role)
        await rbac.create_namespaced_role_binding(
            namespace,
            client.V1RoleBinding(
                metadata=client.V1ObjectMeta(name="owned-scale"),
                role_ref=client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="Role", name="owned-scale"
                ),
                subjects=[
                    client.RbacV1Subject(
                        api_group="rbac.authorization.k8s.io", kind="User", name=reader
                    )
                ],
            ),
        )
        delegated = KubernetesSession(
            sessions.catalog.select(cluster.context, ConnectionOverrides(as_user=reader)), 15
        )
        await delegated.open()
        narrow = WorkloadService(delegated, resource, target, AccessPolicy(False), lambda: True)
        intent = await narrow.prepare(WorkloadAction.SCALE, "3")
        assert (await narrow.execute(narrow.confirm(intent))).state is MutationState.DENIED
        role.rules.append(
            client.V1PolicyRule(
                api_groups=["apps"], resources=["deployments/scale"], verbs=["patch"]
            )
        )
        await rbac.replace_namespaced_role("owned-scale", namespace, role)
        await apply(narrow, WorkloadAction.SCALE, "1")
        await complete(source)
        checks.extend(
            ["actual-forbidden-scale-write", "scale-only-patch-rbac-without-parent-patch"]
        )

        await apps.patch_namespaced_deployment("owned-one", namespace, {"spec": {"paused": True}})
        try:
            await source.prepare(WorkloadAction.RESTART)
            raise AssertionError("Paused restart accepted")
        except AppError as error:
            assert "paused" in str(error)
        assert (await source.monitor(lambda progress: None)).state == "Paused"
        await apps.patch_namespaced_deployment(
            "owned-one",
            namespace,
            {
                "spec": {
                    "paused": False,
                    "progressDeadlineSeconds": 10,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "app",
                                    "image": "invalid.invalid/owned-missing-image:never",
                                }
                            ]
                        }
                    },
                }
            },
        )
        assert (await source.monitor(lambda progress: None, timeout=0.05)).state == "Timed out"
        ready = asyncio.Event()
        task = asyncio.create_task(source.monitor(lambda progress: ready.set(), timeout=120))
        await ready.wait()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert (
            await apps.read_namespaced_deployment("owned-one", namespace)
        ).spec.template.spec.containers[0].image == "invalid.invalid/owned-missing-image:never"
        assert (await source.monitor(lambda progress: None, timeout=90)).state == "Failed"
        checks.extend(
            [
                "actual-paused-refusal",
                "monitor-timeout-and-cancellation-do-not-undo",
                "actual-progress-deadline-failure",
            ]
        )

        # ControllerRevision-backed histories are also read from real controllers.
        for family in ("statefulsets", "daemonsets"):
            name = "owned-" + family
            labels = {"app": name}
            selector = client.V1LabelSelector(match_labels=labels)
            value: client.V1StatefulSet | client.V1DaemonSet
            if family == "statefulsets":
                value = await apps.create_namespaced_stateful_set(
                    namespace,
                    client.V1StatefulSet(
                        metadata=client.V1ObjectMeta(name=name),
                        spec=client.V1StatefulSetSpec(
                            selector=selector,
                            template=pod_template(labels),
                            replicas=1,
                            service_name=name,
                        ),
                    ),
                )
            else:
                value = await apps.create_namespaced_daemon_set(
                    namespace,
                    client.V1DaemonSet(
                        metadata=client.V1ObjectMeta(name=name),
                        spec=client.V1DaemonSetSpec(
                            selector=selector, template=pod_template(labels)
                        ),
                    ),
                )
            workload = WorkloadService(
                connection,
                discovery.find(family, group="apps"),
                ResourceTarget(identity, "apps", family, namespace, name, value.metadata.uid),
                AccessPolicy(False),
                lambda: True,
            )
            await complete(workload)
            await apply(workload, WorkloadAction.RESTART)
            await complete(workload)
            await apply(workload, WorkloadAction.ROLLBACK, "1")
            await complete(workload)
            checks.append("actual-" + family + "-controllerrevision-rollback")
        assert cluster.path.read_bytes() == before
        checks.append("caller-config-unchanged")
        return {"node_image": NODE_IMAGE, "shell_image": SHELL_IMAGE, "checks": checks}
    finally:
        if delegated is not None:
            await delegated.close()
        await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", type=Path, default="artifacts/cluster/workloads.json")
    args = parser.parse_args()
    with owned_cluster(args.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind workload operation checks passed.", flush=True)


if __name__ == "__main__":
    main()
