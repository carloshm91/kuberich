"""View faults are isolated, explicit retries recover, and fatal ownership still exits."""

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
        self.broken = True
        self.calls = 0

    async def render(self, request):
        self.calls += 1
        if self.broken:
            raise ValueError("private-fault-value")
        return RenderOutcome(1, 1, None, 0, request.current())

    def capture_viewport(self):
        return Viewport(None, 0, 0, 0, None)

    def restore_viewport(self, viewport):
        pass

    def available_actions(self, request):
        return frozenset()


@pytest.mark.asyncio
async def test_view_failure_stays_blocked_until_retry_other_views_continue_and_exit_drains():
    broken, healthy = Driver(), Driver()
    healthy.broken = False
    foreground = ForegroundGate(lambda: None)
    foreground.resume()
    registry = ViewRegistry(
        {
            ViewKind.PODS: lambda: ViewEntry(broken),
            ViewKind.CONTEXTS: lambda: ViewEntry(healthy),
        }
    )
    request = RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.pods())
    states, faults, published, fatal = [], [], [], []

    def recovered(value, error):
        states.append(owner.is_failed(value))
        if error is not None:
            faults.append(error)

    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *args: published.append(args),
        fatal.append,
        recover=recovered,
    )
    owner.start()
    owner.request()
    await wait_for(lambda: bool(faults))
    assert owner.active_count == 1 and owner.is_failed(request) and broken.calls == 1
    owner.request()
    await asyncio.sleep(0)
    assert broken.calls == 1
    request = replace(request, route=ViewRoute.contexts())
    owner.request()
    await wait_for(lambda: bool(published))
    assert not states[-1] and healthy.calls == 1
    request = replace(request, route=ViewRoute.pods())
    owner.request()
    await wait_for(lambda: states[-1])
    assert broken.calls == 1 and len(faults) == 1
    broken.broken = False
    owner.retry()
    await wait_for(lambda: len(published) == 2)
    assert not owner.is_failed(request) and broken.calls == 2 and not states[-1]
    assert fatal == []
    await owner.close()
    assert owner.active_count == 0
    owner.retry()
    assert owner.active_count == 0


@pytest.mark.asyncio
async def test_a_late_failed_projection_does_not_block_or_publish_a_new_context():
    entered, release = asyncio.Event(), asyncio.Event()
    live, state_changes, fatal, published = True, [], [], []

    class Held(Driver):
        async def render(self, request):
            if not self.calls:
                self.calls += 1
                entered.set()
                await release.wait()
                raise ValueError("old-private-failure")
            return await super().render(request)

    driver = Held()
    driver.broken = False
    foreground = ForegroundGate(lambda: None)
    foreground.resume()
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(driver)})
    request = RenderRequest(ViewObservation(context="old"), "", lambda: live, ViewRoute.pods())
    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *args: published.append(args),
        fatal.append,
        recover=lambda *args: state_changes.append(args),
    )
    owner.start()
    owner.request()
    await entered.wait()
    live = False
    request = replace(request, observation=ViewObservation(context="new"), current=lambda: True)
    owner.request()
    release.set()
    await wait_for(lambda: bool(published))
    assert fatal == [] and not owner.is_failed(request)
    assert all(error is None for _, error in state_changes)
    await owner.close()


@pytest.mark.asyncio
async def test_context_replacement_recovers_a_previous_view_fault_without_reusing_its_state():
    driver, fatal, recovered = Driver(), [], []
    request = RenderRequest(ViewObservation(context="old"), "", lambda: True, ViewRoute.pods())
    foreground = ForegroundGate(lambda: None)
    foreground.resume()
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(driver)})
    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *_: None,
        fatal.append,
        recover=lambda *args: recovered.append(args),
    )
    owner.start()
    owner.request()
    await wait_for(lambda: owner.is_failed(request))
    driver.broken = False
    request = replace(request, observation=ViewObservation(context="new"))
    owner.request()
    await wait_for(lambda: driver.calls == 2)
    assert not owner.is_failed(request) and fatal == []
    await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["capture", "retirement"])
async def test_workspace_capture_and_projection_cleanup_failures_remain_fatal(fault):
    fatal, recovered = [], []
    request = RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.contexts())
    foreground = ForegroundGate(lambda: None)
    foreground.resume()

    async def retire():
        if fault == "retirement":
            raise RuntimeError("owned-cleanup-failure")

    registry = ViewRegistry(
        {
            ViewKind.PODS: lambda: ViewEntry(Driver(), retire),
            ViewKind.CONTEXTS: lambda: ViewEntry(Driver()),
        }
    )
    registry.resolve(ViewRoute.pods())

    def capture():
        if fault == "capture":
            raise RuntimeError("owned-capture-failure")
        return request

    owner = RenderCoordinator(
        foreground,
        registry,
        capture,
        lambda *_: None,
        fatal.append,
        recover=lambda *args: recovered.append(args),
    )
    owner.start()
    owner.request()
    await wait_for(lambda: bool(fatal))
    assert owner.active_count == 0
    assert not owner.is_failed(request)
    assert all(error is None for _, error in recovered)
    await owner.close()


@pytest.mark.asyncio
async def test_closed_or_obsolete_presentation_faults_are_ignored_and_legacy_faults_are_fatal():
    request = RenderRequest(ViewObservation(), "", lambda: True, ViewRoute.pods())
    foreground = ForegroundGate(lambda: None)
    registry = ViewRegistry({ViewKind.PODS: lambda: ViewEntry(Driver())})
    fatal, recovered = [], []
    owner = RenderCoordinator(
        foreground,
        registry,
        lambda: request,
        lambda *_: None,
        fatal.append,
        recover=lambda *args: recovered.append(args),
    )
    owner.fail(replace(request, current=lambda: False), ValueError("old"))
    assert not owner.is_failed(request) and recovered == []
    await owner.close()
    owner.fail(request, ValueError("closed"))
    assert not owner.is_failed(request) and recovered == []
    legacy = RenderCoordinator(foreground, registry, lambda: request, lambda *_: None, fatal.append)
    legacy.fail(request, ValueError("fatal"))
    assert len(fatal) == 1 and isinstance(fatal[0], ValueError)
    await legacy.close()
