"""M08 :cleanup through the real UI on an owned kind cluster.

Running pods are never listed, and a pod replaced after review keeps its new UID.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client
from kubernetes_asyncio.client.exceptions import ApiException
from textual.widgets import Input, SelectionList, Static

from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.ui.app import KubeRichApp
from kuberich.ui.operations import ResourceOperationScreen
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

NAMESPACE = "kuberich-owned-cleanup"
PHASES = {
    "owned-running": "Running",
    "owned-done": "Succeeded",
    "owned-failed": "Failed",
    "owned-replaced": "Succeeded",
}
# Feedback that ends a confirmation: a refused batch, or per-pod results.
DONE = ("no write started", "owned-failed:")
COMMANDS = {"Running": "sleep 3600", "Succeeded": "true", "Failed": "false"}


async def until(predicate: Any, seconds: float = 30) -> None:
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.1)


async def create_pod(core: client.CoreV1Api, name: str) -> None:
    await core.create_namespaced_pod(
        NAMESPACE,
        client.V1Pod(
            metadata=client.V1ObjectMeta(name=name),
            spec=client.V1PodSpec(
                restart_policy="Never",
                termination_grace_period_seconds=0,
                containers=[
                    client.V1Container(
                        name="main",
                        image=SHELL_IMAGE,
                        command=["sh", "-c", COMMANDS[PHASES[name]]],
                    )
                ],
            ),
        ),
    )


async def phase(core: client.CoreV1Api, name: str) -> str:
    async with asyncio.timeout(180):
        while True:
            pod = await core.read_namespaced_pod(name, NAMESPACE)
            if pod.status.phase == PHASES[name]:
                return str(pod.metadata.uid)
            await asyncio.sleep(0.2)


async def absent(core: client.CoreV1Api, name: str) -> None:
    async with asyncio.timeout(60):
        while True:
            try:
                await core.read_namespaced_pod(name, NAMESPACE)
            except ApiException as error:
                if error.status == 404:
                    return
                raise
            await asyncio.sleep(0.2)


async def command(pilot: Any, text: str) -> None:
    await pilot.press("colon", *text, "enter")
    await pilot.pause()


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    before = cluster.path.read_bytes()
    checks: list[str] = []
    app = KubeRichApp(
        Settings(),
        logging.getLogger("owned-cleanup"),
        catalog=load_catalog(request, {}),
        connection=request,
    )
    async with app.run_test(size=(140, 40)) as pilot:
        await until(lambda: app.sessions.client is not None and app.sessions.client.api)
        connection = app.sessions.client
        assert connection is not None and connection.api is not None
        core = client.CoreV1Api(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
        )
        for name in PHASES:
            await create_pod(core, name)
        uids = {name: await phase(core, name) for name in PHASES}
        await until(lambda: app.resources.row_count == len(PHASES), 60)

        async def review() -> tuple[ResourceOperationScreen, list[str]]:
            await command(pilot, "cleanup")
            await until(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            assert isinstance(screen, ResourceOperationScreen)
            targets = screen.query_one(SelectionList)
            labels = [
                str(targets.get_option_at_index(i).prompt) for i in range(targets.option_count)
            ]
            assert len(labels) == 3 and len(targets.selected) == 3, labels
            assert not any("owned-running" in label for label in labels), labels
            return screen, labels

        async def confirm(screen: ResourceOperationScreen, count: int) -> str:
            screen.query_one("#operation-count", Input).value = f"DELETE {count}"
            await pilot.click("#operation-confirm")
            feedback = screen.query_one("#operation-feedback", Static)
            await until(lambda: any(x in str(feedback.content) for x in DONE), 60)
            return str(feedback.content)

        # A reviewed pod replaced before Confirm (new UID) refuses the whole batch.
        screen, labels = await review()
        assert any(f"owned-failed · Failed · UID {uids['owned-failed']}" in x for x in labels)
        checks.append("running-pod-excluded")
        await pilot.click("#operation-review")
        await until(lambda: screen.intent is not None)
        await core.delete_namespaced_pod("owned-replaced", NAMESPACE, grace_period_seconds=0)
        await absent(core, "owned-replaced")
        await create_pod(core, "owned-replaced")
        replacement = await phase(core, "owned-replaced")
        assert replacement != uids["owned-replaced"]
        await until(lambda: app.resources.row_count == len(PHASES), 60)
        refused = await confirm(screen, 3)
        assert "no write started" in refused, refused
        pods = await core.list_namespaced_pod(NAMESPACE)
        assert len(pods.items) == len(PHASES)
        checks.append("replaced-uid-refuses-batch")
        await pilot.click("#operation-cancel")
        await until(lambda: not isinstance(app.screen, ResourceOperationScreen))

        # A new review lists the replacement's UID; deselect it and change one pod.
        screen, labels = await review()
        assert any(f"owned-replaced · Completed · UID {replacement}" in x for x in labels)
        targets = screen.query_one(SelectionList)
        index = next(i for i, label in enumerate(labels) if replacement in label)
        targets.deselect(targets.get_option_at_index(index).value)
        await pilot.click("#operation-review")
        await until(lambda: screen.intent is not None)
        await core.patch_namespaced_pod(
            "owned-failed", NAMESPACE, {"metadata": {"labels": {"kuberich-owned": "changed"}}}
        )
        outcome = await confirm(screen, 2)
        assert "owned-done: Succeeded" in outcome or "owned-done: Accepted" in outcome, outcome
        assert "owned-failed: Conflict" in outcome, outcome
        await absent(core, "owned-done")
        for name, uid in (
            ("owned-failed", uids["owned-failed"]),
            ("owned-replaced", replacement),
            ("owned-running", uids["owned-running"]),
        ):
            kept = await core.read_namespaced_pod(name, NAMESPACE)
            assert kept.metadata.uid == uid and kept.metadata.deletion_timestamp is None, name
        checks.extend(("finished-pod-deleted", "changed-version-conflict", "unselected-kept"))
        checks.append("running-pod-kept")
    readonly = KubeRichApp(
        Settings(read_only=True),
        logging.getLogger("owned-cleanup-readonly"),
        catalog=load_catalog(request, {}),
        connection=request,
    )
    async with readonly.run_test(size=(140, 40)) as pilot:
        await until(lambda: readonly.resources.row_count == 3, 60)
        await command(pilot, "cleanup")
        assert not isinstance(readonly.screen, ResourceOperationScreen)
        assert "read-only" in str(readonly.status.content).lower()
    checks.append("readonly-refused")
    assert cluster.path.read_bytes() == before
    checks.append("caller-config-unchanged")
    return {
        "node_image": NODE_IMAGE,
        "shell_image": SHELL_IMAGE,
        "conflict_result": outcome,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", type=Path, default="artifacts/cluster/cleanup.json")
    args = parser.parse_args()
    with owned_cluster(args.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind finished-pod cleanup checks passed.", flush=True)


if __name__ == "__main__":
    main()
