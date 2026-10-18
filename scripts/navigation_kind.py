"""Live captured-container navigation on an explicitly owned API-status fixture."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from kubernetes_asyncio.client import (
    CoreV1Api,
    V1Container,
    V1DeleteOptions,
    V1Namespace,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
    V1Preconditions,
)

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.logs import LogScreen


async def _until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(30):
        while not predicate():
            await asyncio.sleep(0.01)


async def verify_container_navigation(
    core: CoreV1Api, catalog: KubeCatalog, path: Path, context: str
) -> dict[str, object]:
    namespace = "kuberich-navigation-" + uuid4().hex[:12]
    await core.create_namespace(V1Namespace(metadata=V1ObjectMeta(name=namespace)))
    # No scheduler owns this Pod. Status is patched deliberately, so no image
    # pull, kubelet/controller race or fabricated running-container claim exists.
    body = V1Pod(
        metadata=V1ObjectMeta(name="navigation-fixture", namespace=namespace),
        spec=V1PodSpec(
            scheduler_name="kuberich-owned-status-fixture",
            containers=[
                V1Container(name=name, image="registry.k8s.io/pause:3.10.2")
                for name in ("app-a", "app-b")
            ],
        ),
    )
    try:
        initial = await core.create_namespaced_pod(namespace, body)
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("owned-navigation"),
            catalog=catalog,
            connection=ConnectionRequest(
                kubeconfig=str(path), context=context, namespace=namespace, timeout=15
            ),
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.resources.row_count == 1
                )
            )
            await pilot.press("enter")
            containers = app.screen
            assert isinstance(containers, ContainerScreen)
            containers.table.move_cursor(row=containers.table.get_row_index("app-b"))
            containers.table.scroll_to(x=20, animate=False, immediate=True, force=True)
            x = containers.table.scroll_x
            for state, ready, restarts in (
                ("waiting", False, 2),
                ("running", True, 3),
                ("terminated", False, 4),
            ):
                payload: dict[str, object] = {"running": None, "waiting": None, "terminated": None}
                payload[state] = (
                    {"reason": "CrashLoopBackOff"}
                    if state == "waiting"
                    else {"exitCode": 9}
                    if state == "terminated"
                    else {}
                )
                await core.patch_namespaced_pod_status(
                    "navigation-fixture",
                    namespace,
                    {
                        "status": {
                            "phase": "Running",
                            "containerStatuses": [
                                {
                                    "name": "app-b",
                                    "image": "registry.k8s.io/pause:3.10.2",
                                    "ready": ready,
                                    "restartCount": restarts,
                                    "state": payload,
                                }
                            ],
                        }
                    },
                )
                async with asyncio.timeout(30):
                    while containers.table.get_row("app-b")[4].plain != str(restarts):
                        await asyncio.sleep(0.01)
                assert containers._selected_name() == "app-b" and containers.table.scroll_x == x
                assert containers.table.get_row("app-b")[2].plain == str(ready).lower()
            await pilot.press("enter")
            logs = app.screen
            assert isinstance(logs, LogScreen)
            await core.delete_namespaced_pod(
                "navigation-fixture",
                namespace,
                body=V1DeleteOptions(
                    grace_period_seconds=0, preconditions=V1Preconditions(uid=initial.metadata.uid)
                ),
            )
            await _until(
                lambda: (
                    containers.invalidated
                    and logs.stale
                    and logs._controller is not None
                    and logs._controller.done()
                )
            )
            replacement = await core.create_namespaced_pod(namespace, body)
            assert replacement.metadata.uid != initial.metadata.uid
            await _until(
                lambda: (
                    app.workspace.store.observation.snapshot is not None
                    and any(
                        record.uid == replacement.metadata.uid
                        for record in app.workspace.store.observation.snapshot.items
                    )
                )
            )
            assert containers.table.row_count == 0 and not logs.history.entries
            await pilot.press("escape", "escape")
            await _until(lambda: app.resources.selected_uid == replacement.metadata.uid)
            await pilot.press("enter")
            second = app.screen
            assert isinstance(second, ContainerScreen)
            await pilot.press("colon", *"ns kube-system", "enter")
            await _until(
                lambda: (
                    len(app.screen_stack) == 1
                    and app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.sessions.observation.namespace == "kube-system"
                )
            )
            assert second.invalidated and second.table.row_count == 0
            app._submit_command("po " + namespace)
            await _until(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.resources.selected_uid == replacement.metadata.uid
                )
            )
            await pilot.press("enter")
            third = app.screen
            assert isinstance(third, ContainerScreen)
            assert app.sessions.client is not None and app.sessions.client.api is not None
            old = app.sessions.client.api
            await pilot.press("colon", *("ctx " + context), "enter")
            await _until(
                lambda: (
                    len(app.screen_stack) == 1
                    and app.workspace.store.observation.status is ViewStatus.LIVE
                )
            )
            assert third.invalidated and old.rest_client.pool_manager.closed
            app._submit_command("po " + namespace)
            await _until(lambda: app.resources.selected_uid == replacement.metadata.uid)
            await pilot.press("enter", "escape")
            assert len(app.screen_stack) == 1
        assert app.sessions.client is None
        return {
            "container_status_fixture": "owned API patches; deliberately unscheduled Pod",
            "live_container_readiness_restarts_states": True,
            "container_uid_recreation_sticky": True,
            "nested_namespace_context_drain": True,
            "container_escape_cleanup": True,
        }
    finally:
        await core.delete_namespace(namespace)
