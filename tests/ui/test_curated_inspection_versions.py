"""Actual root WATCH updates invalidate declared-link reads without ordering opaque RVs."""

import asyncio
import copy

import pytest

from kuberich.services.curated_navigation import CuratedOrigin
from kuberich.ui.inspection import InspectionScreen
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, loaded, started


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["unchanged-baseline", "held-target-watch-change", "queued-watch-change"]
)
async def test_fresh_inspector_get_can_lead_root_snapshot_but_observed_new_source_version_revokes_link(
    tmp_path, monkeypatch, change
):
    async with curated_resources_api(tmp_path) as (url, api):
        source_resource = api.resource(
            "horizontalpodautoscalers", group="autoscaling", version="v2"
        )
        target_resource = api.resource("deployments", group="apps")
        source = api.objects(source_resource)[0]
        target = api.objects(target_resource)[0]
        source["spec"]["scaleTargetRef"] = {
            "apiVersion": target_resource.api_version,
            "kind": target_resource.kind,
            "name": target["metadata"]["name"],
        }
        api.put(source_resource, source)
        target_path = target_resource.path("team") + "/" + target["metadata"]["name"]
        collection_path = source_resource.path("team")
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("hpa team")
            await loaded(app, pilot, source_resource)
            await asyncio.wait_for(api.watch(collection_path).entered.wait(), 2)
            app.standard_table.move_cursor(row=0)
            baseline = source["metadata"]["resourceVersion"]
            source["metadata"]["resourceVersion"] = "opaque-fresh-get"
            api.put(
                source_resource, source
            )  # The server GET leads an unchanged root WATCH snapshot.
            app.action_inspect_details()
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            screen = app.screen
            assert screen.observed_resource_version == baseline
            assert screen.result.resource_version == "opaque-fresh-get"
            assert (
                next(
                    item
                    for item in app.workspace.store.observation.snapshot.items
                    if item.uid == source["metadata"]["uid"]
                ).resource_version
                == baseline
            )
            queued = []
            if change == "queued-watch-change":
                original = screen.call_later

                def defer_handoff(callback, *args, **kwargs):
                    if args and isinstance(args[0], CuratedOrigin):
                        queued.append((callback, args))
                        return True
                    return original(callback, *args, **kwargs)

                monkeypatch.setattr(screen, "call_later", defer_handoff)
                barrier = None
            else:
                barrier = api.hold(target_path)
            try:
                await pilot.press("L", "enter")
                if barrier is None:
                    await wait_for(lambda: len(queued) == 1)
                    assert screen.operation_count == 0
                    assert queued[0][1][0].observed_resource_version == baseline
                else:
                    await asyncio.wait_for(barrier.entered.wait(), 2)
                if change != "unchanged-baseline":
                    changed = copy.deepcopy(source)
                    changed["metadata"]["resourceVersion"] = "opaque-watch-third-value"
                    changed["spec"]["scaleTargetRef"]["name"] = "owned-b"
                    api.emit(collection_path, changed)
                    await wait_for(
                        lambda: any(
                            item.uid == source["metadata"]["uid"]
                            and item.resource_version == "opaque-watch-third-value"
                            for item in app.workspace.store.observation.snapshot.items
                        )
                    )
                if barrier is not None:
                    barrier.release.set()
                else:
                    queued[0][0](*queued[0][1])
                if change == "unchanged-baseline":
                    try:
                        await loaded(app, pilot, target_resource, count=1)
                    except TimeoutError:
                        raise AssertionError(
                            f"Fresh link did not open: scope={app.state.scope}, target={target_resource}, rows={app.standard_table.row_count}, screen={type(app.screen).__name__}, inspector_status={screen.status.content}"
                        ) from None
                    await wait_for(lambda: app.operations.retained_general_inspection_count == 0)
                    assert screen not in app.screen_stack
                else:
                    await wait_for(lambda: screen.operation_count == 0)
                    assert app.screen is screen
                    assert app.state.scope.resource == source_resource
                    assert "changed" in str(screen.status.content) or "obsolete" in str(
                        screen.status.content
                    )
                    await screen.stop_owned()
                assert all(entry.method == "GET" for entry in api.requests)
            finally:
                if barrier is not None:
                    barrier.release.set()
                await screen.stop_owned()
