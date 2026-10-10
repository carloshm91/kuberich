"""S06: real controller membership, container changes and drained logs on owned kind."""

import argparse
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.aggregate_logs import AggregateHistory
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.logs import LogLine, LogOptions
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.targets import ResourceTarget
from kuberich.services.access import AccessPolicy
from kuberich.services.aggregate_logs import AggregateLogs
from kuberich.services.commands import ResourceCommand
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.ui.aggregate_logs import AggregateLogScreen
from kuberich.ui.app import KubeRichApp
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster


async def wait_for(predicate: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(120):
        while not await predicate():
            await asyncio.sleep(0.05)


def crash_status(pod: client.V1Pod) -> dict[str, Any]:
    """Bounded synthetic fixture status, without retaining manifests or log payloads."""
    entries = pod.status.container_statuses or [] if pod.status is not None else []
    return {
        "uid": pod.metadata.uid if pod.metadata is not None else None,
        "containers": [
            {
                "name": sanitize_text(entry.name)[:128],
                "restart_count": entry.restart_count,
                "ready": entry.ready,
                "started": entry.started,
                "container_id": sanitize_text(entry.container_id or "")[:512],
                "waiting_reason": sanitize_text(entry.state.waiting.reason or "")[:128]
                if entry.state is not None and entry.state.waiting is not None
                else None,
                "running": entry.state is not None and entry.state.running is not None,
                "terminated": entry.state is not None and entry.state.terminated is not None,
                "last_container_id": sanitize_text(entry.last_state.terminated.container_id or "")[
                    :512
                ]
                if entry.last_state is not None and entry.last_state.terminated is not None
                else None,
            }
            for entry in entries[:8]
        ],
    }


def task_status(task: asyncio.Task[None] | None) -> dict[str, Any]:
    error = task.exception() if task is not None and task.done() and not task.cancelled() else None
    return {
        "done": task is not None and task.done(),
        "cancelled": task is not None and task.cancelled(),
        "exception": type(error).__name__ if error is not None else None,
    }


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    namespace = "kuberich-owned-aggregate"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    catalog = load_catalog(request, {})
    sessions = SessionService(catalog, request)
    before = cluster.path.read_bytes()
    owners: list[tuple[AggregateLogs, asyncio.Task[None]]] = []
    checks: list[str] = []
    try:
        await sessions.connect(cluster.context)
        connection, identity = sessions.client, sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        core = client.CoreV1Api(connection.api)
        apps = client.AppsV1Api(connection.api)
        batch = client.BatchV1Api(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        reader = ResourceReader(connection)
        discovery = await reader.discover()

        def spec(*, multiple: bool = False, slow_init: bool = False) -> client.V1PodSpec:
            containers = [
                client.V1Container(
                    name="app",
                    image=SHELL_IMAGE,
                    command=[
                        "sh",
                        "-c",
                        'printf "[INFO] owned-app\\n"; printf \'{"message":"owned-json","token":"owned-private","count":3}\\n\'; while true; do echo owned-live; sleep 1; done',
                    ],
                )
            ]
            if multiple:
                containers.append(
                    client.V1Container(
                        name="sidecar",
                        image=SHELL_IMAGE,
                        command=["sh", "-c", "echo owned-sidecar; sleep 86400"],
                    )
                )
            return client.V1PodSpec(
                restart_policy="Never" if not multiple else "Always",
                containers=containers,
                init_containers=[
                    client.V1Container(
                        name="init",
                        image=SHELL_IMAGE,
                        command=[
                            "sh",
                            "-c",
                            "echo owned-init; sleep 8" if slow_init else "echo owned-init",
                        ],
                    )
                ],
                tolerations=[client.V1Toleration(operator="Exists")],
            )

        cronjob = await batch.create_namespaced_cron_job(
            namespace,
            client.V1CronJob(
                metadata=client.V1ObjectMeta(name="owned-cron"),
                spec=client.V1CronJobSpec(
                    schedule="0 * * * *",
                    suspend=True,
                    job_template=client.V1JobTemplateSpec(
                        spec=client.V1JobSpec(template=client.V1PodTemplateSpec(spec=spec()))
                    ),
                ),
            ),
        )
        deployment = await apps.create_namespaced_deployment(
            namespace,
            client.V1Deployment(
                metadata=client.V1ObjectMeta(name="owned-deploy"),
                spec=client.V1DeploymentSpec(
                    replicas=2,
                    selector=client.V1LabelSelector(match_labels={"owned": "aggregate"}),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels={"owned": "aggregate"}),
                        spec=spec(multiple=True),
                    ),
                ),
            ),
        )
        rogue = await core.create_namespaced_pod(
            namespace,
            client.V1Pod(
                metadata=client.V1ObjectMeta(
                    name="matching-label-wrong-owner",
                    labels={"owned": "aggregate"},
                    owner_references=[
                        client.V1OwnerReference(
                            api_version="batch/v1",
                            kind="CronJob",
                            name="owned-cron",
                            uid=cronjob.metadata.uid,
                            controller=True,
                        )
                    ],
                ),
                spec=spec(),
            ),
        )

        async def ready() -> bool:
            value = await apps.read_namespaced_deployment("owned-deploy", namespace)
            return value.status.ready_replicas == 2

        await wait_for(ready)
        resource = discovery.find("deployments", group="apps")
        target = ResourceTarget(
            identity, "apps", "deployments", namespace, "owned-deploy", deployment.metadata.uid
        )
        owner = AggregateLogs(
            connection, resource, target, AccessPolicy(True), lambda: sessions.client is connection
        )
        history = AggregateHistory()

        async def retain(source: Any, number: int, line: LogLine) -> None:
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        owners.append((owner, task))

        async def output() -> bool:
            return len(owner.states) == 6 and {"app", "sidecar", "init"} <= {
                record.source.container for record in history.records.values()
            }

        await wait_for(output)
        assert all(state.source.uid != rogue.metadata.uid for state in owner.states.values())
        assert "matching-label-wrong-owner" not in history.export()
        assert "[INFO] owned-app" in history.export() and "owned-private" not in history.export()
        history.json_mode = True
        records = [json.loads(line) for line in history.export().splitlines()]
        payloads = [record["payload"] for record in records if isinstance(record["payload"], dict)]
        assert any(
            payload.get("message") == "owned-json"
            and payload.get("count") == 3
            and payload.get("token") == "[REDACTED]"
            for payload in payloads
        )
        checks.extend(
            [
                "actual-deployment-replicaset-pod-membership-excludes-matching-label-other-owner",
                "actual-regular-init-and-multiple-pod-log-sources",
                "actual-decoder-json-shape-redaction-and-bracket-plain-output",
            ]
        )
        member = next(
            state.source for state in owner.states.values() if state.source.container == "app"
        )
        await core.patch_namespaced_pod_ephemeralcontainers(
            member.pod,
            namespace,
            {
                "spec": {
                    "ephemeralContainers": [
                        {
                            "name": "debug",
                            "image": SHELL_IMAGE,
                            "command": ["sh", "-c", "echo owned-ephemeral; sleep 86400"],
                            "targetContainerName": "app",
                        }
                    ]
                }
            },
        )

        async def debug_ready() -> bool:
            value = await core.read_namespaced_pod(member.pod, namespace)
            return bool(
                value.status.ephemeral_container_statuses
                and value.status.ephemeral_container_statuses[0].state.running
            )

        await wait_for(debug_ready)

        async def debug_listed() -> bool:
            return (member.uid, "debug") in owner.states

        await wait_for(debug_listed)
        owner.choose(frozenset({(member.uid, "debug")}), reopen=True)

        async def debug_output() -> bool:
            return "owned-ephemeral" in history.export()

        await wait_for(debug_output)
        owner.choose(None)
        checks.append("actual-live-ephemeral-admission-and-explicit-source-selection")
        old_uids = {state.source.uid for state in owner.states.values()}
        await core.delete_namespaced_pod(member.pod, namespace, grace_period_seconds=0)

        async def replacement() -> bool:
            return any(state.source.uid not in old_uids for state in owner.states.values()) and all(
                state.source.uid != member.uid for state in owner.states.values()
            )

        await wait_for(replacement)
        assert any(
            state.source.uid == member.uid and state.status == "removed" for state in owner.retired
        )
        assert all(state.task is None or state.task.done() for state in owner.retired)
        checks.append("actual-workload-pod-delete-replacement-closes-old-source-generation")

        job = await batch.create_namespaced_job(
            namespace,
            client.V1Job(
                metadata=client.V1ObjectMeta(
                    name="owned-child-job",
                    owner_references=[
                        client.V1OwnerReference(
                            api_version="batch/v1",
                            kind="CronJob",
                            name="owned-cron",
                            uid=cronjob.metadata.uid,
                            controller=True,
                        )
                    ],
                ),
                spec=client.V1JobSpec(template=client.V1PodTemplateSpec(spec=spec(slow_init=True))),
            ),
        )
        cron_target = ResourceTarget(
            identity, "batch", "cronjobs", namespace, "owned-cron", cronjob.metadata.uid
        )
        cron_owner = AggregateLogs(
            connection,
            discovery.find("cronjobs", group="batch"),
            cron_target,
            AccessPolicy(True),
            lambda: sessions.client is connection,
        )
        cron_lines: list[str] = []

        async def retain_cron(source: Any, number: int, line: LogLine) -> None:
            cron_owner.require_source(source, number)
            cron_lines.append(line.text)
            del cron_lines[:-100]

        cron_task = asyncio.create_task(
            cron_owner.run(LogOptions(), retain_cron, lambda message: None)
        )
        owners.append((cron_owner, cron_task))

        async def job_starting() -> bool:
            return any(
                state.source.container == "app" and state.status == "starting"
                for state in cron_owner.states.values()
            )

        await wait_for(job_starting)
        assert not any("owned-app" in line for line in cron_lines)

        async def cron_output() -> bool:
            return bool(cron_owner.states) and any("owned-app" in line for line in cron_lines)

        await wait_for(cron_output)
        pods = await core.list_namespaced_pod(namespace)
        job_uids = {
            pod.metadata.uid
            for pod in pods.items
            if any(
                reference.uid == job.metadata.uid
                for reference in pod.metadata.owner_references or []
            )
        }
        assert job_uids and all(
            state.source.uid in job_uids for state in cron_owner.states.values()
        )
        checks.append("actual-cronjob-job-pod-controller-chain")
        checks.append("actual-pending-init-starting-to-app-log-enrollment-without-reopen")

        crash = await core.create_namespaced_pod(
            namespace,
            client.V1Pod(
                metadata=client.V1ObjectMeta(name="owned-crash"),
                spec=client.V1PodSpec(
                    restart_policy="Always",
                    containers=[
                        client.V1Container(
                            name="app",
                            image=SHELL_IMAGE,
                            command=["sh", "-c", "echo owned-crash-output; exit 1"],
                        )
                    ],
                    tolerations=[client.V1Toleration(operator="Exists")],
                ),
            ),
        )

        async def crash_waiting() -> bool:
            value = await core.read_namespaced_pod("owned-crash", namespace)
            return any(
                status.state.waiting is not None
                and status.state.waiting.reason == "CrashLoopBackOff"
                and status.last_state.terminated is not None
                and bool(status.last_state.terminated.container_id)
                for status in value.status.container_statuses or []
            )

        crash_modes: list[dict[str, Any]] = []

        async def retain_crash_failure(
            stage: str,
            previous: bool,
            error: Exception,
            owner: AggregateLogs | None = None,
            task: asyncio.Task[None] | None = None,
            lines: list[str] | None = None,
        ) -> None:
            try:
                value = await core.read_namespaced_pod(
                    "owned-crash", namespace, _request_timeout=15
                )
                status = crash_status(value)
            except Exception as observation_error:
                status = {"observation_error": type(observation_error).__name__}
            path = Path("artifacts/cluster") / f"aggregate-logs-kind-failure-{cluster.name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "cluster": cluster.name,
                        "stage": stage,
                        "previous": previous,
                        "error": type(error).__name__,
                        "http_status": getattr(error, "status", None),
                        "pod": status,
                        "successful_modes": crash_modes,
                        "line_count": len(lines or []),
                        "expected_output_seen": any(
                            "owned-crash-output" in line for line in lines or []
                        ),
                        "owner_task": task_status(task),
                        "sources": [
                            {
                                "number": state.number,
                                "uid": state.source.uid,
                                "container": state.source.container,
                                "status": state.status,
                                "message": sanitize_text(state.message)[:512],
                                "start_token": state.source.start_token,
                                "retry_after_start": state.retry_after_start,
                                "task": task_status(state.task),
                            }
                            for state in tuple(owner.states.values())[:8]
                        ]
                        if owner is not None
                        else [],
                    },
                    indent=2,
                )
                + "\n"
            )

        for previous in (False, True):
            # Each reader must enroll from its own observed waiting instance;
            # the second mode may otherwise coincide with a real restart.
            try:
                await wait_for(crash_waiting)
                available = await core.read_namespaced_pod(
                    "owned-crash", namespace, _request_timeout=15
                )
                direct = await core.read_namespaced_pod_log(
                    "owned-crash",
                    namespace,
                    container="app",
                    previous=previous,
                    follow=False,
                    tail_lines=10,
                    _request_timeout=15,
                )
                assert "owned-crash-output" in direct
            except Exception as error:
                await retain_crash_failure("available-instance-precondition", previous, error)
                raise
            crash_owner = AggregateLogs(
                connection,
                discovery.find("pods", group=""),
                ResourceTarget(identity, "", "pods", namespace, "owned-crash", crash.metadata.uid),
                AccessPolicy(True),
                lambda: sessions.client is connection,
            )
            crash_lines: list[str] = []
            first_start: list[str | None] = []

            async def retain_crash(
                source: Any,
                number: int,
                line: LogLine,
                crash_owner: AggregateLogs = crash_owner,
                crash_lines: list[str] = crash_lines,
                first_start: list[str | None] = first_start,
            ) -> None:
                crash_owner.require_source(source, number)
                if not first_start:
                    first_start.append(source.start_token)
                crash_lines.append(line.text)
                del crash_lines[:-100]

            crash_task = asyncio.create_task(
                crash_owner.run(
                    LogOptions(previous=previous, follow=False), retain_crash, lambda message: None
                )
            )
            owners.append((crash_owner, crash_task))

            async def crash_output(
                crash_owner: AggregateLogs = crash_owner, crash_lines: list[str] = crash_lines
            ) -> bool:
                return any("owned-crash-output" in line for line in crash_lines) and all(
                    state.status == "ended" for state in crash_owner.states.values()
                )

            try:
                await wait_for(crash_output)
                assert crash_owner.selected is None
                assert (
                    first_start
                    and first_start[0] is not None
                    and first_start[0].startswith("('last-terminated',")
                )
            except Exception as error:
                await retain_crash_failure(
                    "initial-enrollment", previous, error, crash_owner, crash_task, crash_lines
                )
                raise
            crash_modes.append(
                {
                    "previous": previous,
                    "waiting_observation": crash_status(available),
                    "direct_log_available": True,
                    "first_start": first_start[0],
                    "line_count": len(crash_lines),
                    "ended": all(state.status == "ended" for state in crash_owner.states.values()),
                }
            )
        checks.append(
            "actual-crashloop-waiting-last-instance-current-and-previous-initial-enrollment"
        )

        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("owned-aggregate-kind", level=100),
            catalog=catalog,
            connection=request,
            initial_command=ResourceCommand(RESOURCE_ALIASES["deploy"], namespace),
        )
        async with app.run_test(size=(100, 30)) as pilot:

            async def app_ready() -> bool:
                return app.standard_table.row_count == 1

            await wait_for(app_ready)
            await pilot.press("L")

            async def app_logs() -> bool:
                return isinstance(app.screen, AggregateLogScreen) and bool(app.screen.body.rows)

            await wait_for(app_logs)
            screen = app.screen
            assert isinstance(screen, AggregateLogScreen)
            await pilot.press("J", "t", "p", "g", "G")
            await pilot.pause()
            evidence = Path("artifacts/cluster")
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename="aggregate-logs-kind.svg", path=str(evidence.resolve()))
            await pilot.press("escape")
            assert screen._read_task is not None and screen._read_task.done()
            assert not screen.owner._owned
        checks.append("actual-workload-aggregate-pilot-controls-and-leave-drain")
        for log_owner, log_task in owners:
            log_task.cancel()
            with suppress(asyncio.CancelledError):
                await log_task
            await log_owner.close()
            assert not log_owner._owned and all(
                state.task is None or state.task.done() for state in log_owner.states.values()
            )
        checks.append("actual-all-membership-watch-and-log-reader-cancellation-before-client-close")
        assert cluster.path.read_bytes() == before
        checks.append("caller-config-unchanged")
        return {
            "node_image": NODE_IMAGE,
            "shell_image": SHELL_IMAGE,
            "checks": checks,
            "reader_limit": 8,
            "source_limit": 256,
            "retired_limit": 64,
            "crash_modes": crash_modes,
        }
    finally:
        for log_owner, log_task in owners:
            log_task.cancel()
            await asyncio.gather(log_task, return_exceptions=True)
            await log_owner.close()
        await sessions.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument(
        "--evidence", type=Path, default="artifacts/cluster/aggregate-logs-kind.json"
    )
    args = parser.parse_args()
    with owned_cluster(args.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind aggregate log checks passed.", flush=True)


if __name__ == "__main__":
    main()
