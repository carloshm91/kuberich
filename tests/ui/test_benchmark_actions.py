"""Entry refusals remain visible and never manufacture a benchmark owner."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from textual.app import App

from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ResourceSelection
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.ui.benchmark_actions import BenchmarkActions
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.resource_operations import OperationContext
from kuberich.ui.target_capture import CapturedResource
from tests.ui.test_benchmark_forwards import forward


class RefusalManager:
    def __init__(self):
        self.closed_clients = []
        self.closed = False

    def create(self, *args, **kwargs):
        raise AssertionError("A refused entry must not create a benchmark owner")

    async def close_for_client(self, client):
        self.closed_clients.append(client)

    async def close(self):
        self.closed = True


def actions_for(tmp_path, *, readonly=False):
    manager, notices = RefusalManager(), []
    identity = SessionIdentity("synthetic", 1)
    client = SimpleNamespace()
    target = ResourceTarget(identity, "", "services", "team", "web", "uid")
    context = OperationContext(
        WorkspaceChrome(lambda: ("synthetic", "synthetic", "synthetic", "team", "Ready"), "test"),
        ("synthetic", "services"),
        ("sh",),
        {},
        tmp_path,
        ViewRoute.standard(RESOURCE_ALIASES["svc"]),
        False,
    )
    ports = SimpleNamespace(
        selection=CapturedResource(client, None, None, target, lambda: True),
        context=context,
        connection=(client, identity),
    )
    actions = BenchmarkActions(
        App(),
        manager,
        BenchmarkStore(tmp_path / "results"),
        lambda _uid: ports.selection,
        lambda: ports.context,
        AccessPolicy(readonly),
        lambda _context: BenchmarkSettings(),
        lambda: ports.connection,
        lambda _client, _identity: True,
        notices.append,
    )
    return actions, ports, manager, notices


def test_readonly_generic_stale_absent_and_wrong_resource_refusals(tmp_path):
    actions, ports, _, notices = actions_for(tmp_path, readonly=True)
    actions.open()
    actions.open_forward(forward())
    assert len(notices) == 2 and all("Read-only" in notice for notice in notices)
    actions, ports, _, notices = actions_for(tmp_path)
    ports.context = replace(
        ports.context,
        route=ViewRoute.custom(ResourceSelection("services", server_columns=True)),
    )
    actions.open()
    assert "native Service" in notices[-1]
    ports.context = replace(ports.context, route=ViewRoute.pods(), live=False)
    actions.open()
    assert "stale or loading" in notices[-1]
    ports.context = replace(ports.context, live=True)
    ports.selection = None
    actions.open()
    assert len(notices) == 2
    ports.selection = CapturedResource(
        ports.connection[0],
        None,
        None,
        ResourceTarget(ports.connection[1], "", "pods", "team", "web", "pod-uid"),
        lambda: True,
    )
    actions.open()
    assert "Select a Service" in notices[-1]
    actions.observe()


@pytest.mark.asyncio
async def test_forward_connection_attempt_state_and_closed_entries_do_not_create(tmp_path):
    actions, ports, manager, notices = actions_for(tmp_path)
    info = forward()
    actions.open_forward(info)
    assert "connection changed" in notices[-1]
    ports.connection = None
    actions.open_forward(info)
    assert "connection changed" in notices[-1]
    ports.connection = (SimpleNamespace(), info.target.session)
    actions.open_forward(replace(info, state=ForwardState.RECONNECTING))
    assert "READY" in notices[-1]
    await actions.close_for_client(ports.connection[0])
    assert manager.closed_clients == [ports.connection[0]]
    await actions.close()
    assert manager.closed
    actions.open()
    actions.open_forward(info)
    actions.open_browser()
    assert len(notices) == 3
