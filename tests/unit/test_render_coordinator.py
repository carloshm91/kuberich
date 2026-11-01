"""One render owner coalesces modal updates and drains real coroutine callers."""

import asyncio
from dataclasses import replace

import pytest

from kuberich.domain.navigation import Viewport
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.ui.controllers.base import RenderOutcome, RenderRequest
from kuberich.ui.controllers.registry import ViewEntry, ViewRegistry
from kuberich.ui.controllers.rendering import RenderCoordinator
from kuberich.ui.foreground import ForegroundGate
from tests.support.workspace import wait_for


class Driver:
    def __init__(self):
        self.requests = []
        self.viewport = Viewport(None, 0, 0, 0, None)

    async def render(self, request):
        self.requests.append(request)
        return RenderOutcome(2, 1, None, 0, request.current())

    def capture_viewport(self):
        return self.viewport

    def restore_viewport(self, viewport):
        self.viewport = viewport

    def available_actions(self, request):
        return frozenset()


@pytest.mark.asyncio
async def test_registry_constructs_only_active_views_and_retires_only_owned_inactive_projections():
    built, retired = [], []
    drivers = {kind: Driver() for kind in ViewKind}

    def factory(kind, retain=False):
        built.append(kind)

        async def retire():
            retired.append(kind)

        return ViewEntry(drivers[kind], None if retain else retire)

    factories = {
        kind: lambda kind=kind: factory(kind, kind is ViewKind.CONTEXTS) for kind in ViewKind
    }
    registry = ViewRegistry(factories)
    factories.clear()
    assert registry.resolve(ViewRoute.pods()) is drivers[ViewKind.PODS]
    assert registry.resolve(ViewRoute.pods()) is drivers[ViewKind.PODS]
    assert built == [ViewKind.PODS]
    await registry.retire_inactive(ViewRoute.pods())
    assert retired == []
    assert registry.resolve(ViewRoute.contexts()) is drivers[ViewKind.CONTEXTS]
    await registry.retire_inactive(ViewRoute.contexts())
    assert retired == [ViewKind.PODS]
    await registry.retire_inactive(ViewRoute.pods())
    assert retired == [ViewKind.PODS]


@pytest.mark.asyncio
async def test_render_owner_coalesces_modal_requests_and_reads_the_latest_state_on_resume():
    driver, published, failures = Driver(), [], []
    owner = None
    foreground = ForegroundGate(lambda: owner.request())
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(driver)})
    request = RenderRequest(
        ViewObservation(revision=1), "first", lambda: foreground.active, ViewRoute.pods()
    )
    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *result: published.append(result),
        failures.append,
    )
    assert owner.active_count == 0
    owner.start()
    owner.start()
    assert owner.active_count == 1
    owner.request()
    await asyncio.sleep(0)
    assert driver.requests == []
    request = replace(request, query="latest", observation=ViewObservation(revision=2))
    owner.request()
    owner.request()
    foreground.resume()
    await wait_for(lambda: len(published) == 1)
    assert driver.requests == [request]
    foreground.suspend()
    owner.request()
    await asyncio.sleep(0)
    request = replace(request, query="last", observation=ViewObservation(revision=3))
    owner.request()
    foreground.resume()
    await wait_for(lambda: len(published) == 2)
    assert [item[0].query for item in published] == ["latest", "last"] and failures == []
    await owner.close()
    assert owner.active_count == 0
    owner.start()
    owner.request()
    await owner.close()
    assert len(published) == 2


@pytest.mark.asyncio
async def test_repeated_close_cancellation_waits_for_the_actual_render_coroutine_cleanup():
    entered, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    actual_tasks, failures = [], []

    class HeldDriver(Driver):
        async def render(self, request):
            actual_tasks.append(asyncio.current_task())
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                draining.set()
                await release.wait()

    foreground = ForegroundGate(lambda: None)
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(HeldDriver())})
    request = RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.pods())
    owner = RenderCoordinator(
        foreground, registry, lambda: request, lambda *_: None, failures.append
    )
    foreground.resume()
    owner.request()
    owner.start()
    await entered.wait()
    closing = asyncio.create_task(owner.close())
    await draining.wait()
    try:
        for _ in range(3):
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done() and owner.active_count == 1
            assert not actual_tasks[0].done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert actual_tasks[0].done() and owner.active_count == 0 and failures == []
    await owner.close()


@pytest.mark.asyncio
async def test_render_failure_is_reported_and_close_without_start_is_idempotent():
    failures = []

    class BrokenDriver(Driver):
        async def render(self, request):
            raise RuntimeError("owned-render-failure")

    foreground = ForegroundGate(lambda: None)
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(BrokenDriver())})
    request = RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.pods())
    owner = RenderCoordinator(
        foreground, registry, lambda: request, lambda *_: None, failures.append
    )
    foreground.resume()
    owner.request()
    owner.start()
    await wait_for(lambda: bool(failures))
    assert isinstance(failures[0], RuntimeError) and str(failures[0]) == "owned-render-failure"
    await owner.close()
    unopened = RenderCoordinator(
        foreground, registry, lambda: request, lambda *_: None, failures.append
    )
    await unopened.close()
    unopened.start()
    assert unopened.active_count == 0


@pytest.mark.asyncio
async def test_closed_root_releases_a_waiting_renderer_without_polling_or_publishing():
    driver, published = Driver(), []
    foreground = ForegroundGate(lambda: None)
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(driver)})
    request = RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.pods())
    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *result: published.append(result),
        lambda error: None,
    )
    owner.request()
    owner.start()
    await asyncio.sleep(0)
    foreground.close()
    await wait_for(lambda: owner.active_count == 0)
    assert driver.requests == published == []
    await owner.close()


@pytest.mark.asyncio
async def test_a_stale_apply_is_not_published_and_a_later_request_still_renders():
    entered, release, returned = asyncio.Event(), asyncio.Event(), asyncio.Event()
    published, live = [], True

    class HeldDriver(Driver):
        async def render(self, request):
            if not self.requests:
                entered.set()
                await release.wait()
            result = await super().render(request)
            returned.set()
            return result

    driver = HeldDriver()
    foreground = ForegroundGate(lambda: None)
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(driver)})
    request = RenderRequest(ViewObservation(), "old", lambda: live, ViewRoute.pods())
    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *result: published.append(result),
        lambda error: None,
    )
    foreground.resume()
    owner.start()
    owner.request()
    await entered.wait()
    live = False
    release.set()
    await returned.wait()
    assert published == []
    request = replace(request, query="new", current=lambda: True)
    owner.request()
    await wait_for(lambda: bool(published))
    assert [result[0].query for result in published] == ["new"]
    await owner.close()
