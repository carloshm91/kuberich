"""Observe workspace owners at public projection, subscription and timer ports."""

from dataclasses import dataclass, field

import pytest
from textual.app import App

from kuberich.services.pods import ResourceProjection
from kuberich.services.workspace import ViewSubscription
from tests.support.workers import CoroutineCalls


@dataclass
class RootCalls:
    renders: CoroutineCalls = field(default_factory=CoroutineCalls)
    observations: CoroutineCalls = field(default_factory=CoroutineCalls)
    projections: list = field(default_factory=list)
    timers: list = field(default_factory=list)

    def tick(self, app):
        callbacks = [
            callback
            for owner, interval, callback in self.timers
            if owner is app
            and interval == app.live_preferences.refresh_seconds
            and getattr(callback, "__self__", None) is app.presenter
        ]
        assert len(callbacks) == 1
        callbacks[0]()


@pytest.fixture
def root_calls(monkeypatch):
    calls = RootCalls()
    original_project = ResourceProjection.project
    original_interval = App.set_interval

    async def project(owner, snapshot):
        if not any(owner is known for known in calls.projections):
            calls.projections.append(owner)
        if snapshot is not None:
            calls.renders.capture()
        return await original_project(owner, snapshot)

    def interval(owner, seconds, callback=None, **options):
        calls.timers.append((owner, seconds, callback))
        return original_interval(owner, seconds, callback, **options)

    monkeypatch.setattr(ResourceProjection, "project", project)
    monkeypatch.setattr(
        ViewSubscription, "__anext__", calls.observations.observe(ViewSubscription.__anext__)
    )
    monkeypatch.setattr(App, "set_interval", interval)
    return calls
