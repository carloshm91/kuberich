"""Collection commands and captured log action validity without hidden table state."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from kuberich.domain.cluster_diagnostics import DiagnosticIdentity, DiagnosticLogMode
from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.navigation import NavigationState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.views import ViewObservation
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.diagnostic_actions import DiagnosticActions
from kuberich.ui.target_capture import CapturedResource
from tests.support.diagnostic_ui import NOW, POD, PODS, finding, snapshot
from tests.support.relationships import record


class Owner:
    def __init__(self, item=None):
        self.data = snapshot(findings=(item or finding(),))
        self.data = replace(
            self.data,
            request=replace(self.data.request, scope=replace(self.data.request.scope, root=POD)),
        )
        self.item = self.data.findings[0]
        self.identity = self.data.request.scope.session
        self.client = object()
        self.calls, self.screens = [], []
        self.connection = SessionObservation(
            ConnectionState.CONNECTED, "Connected", self.identity, "header-a"
        )
        self.observation = ViewObservation(
            context=self.identity.context, connection=self.connection, diagnostics=self.data
        )
        self.record = record(
            PODS,
            name=POD.name,
            uid=POD.uid,
            namespace=POD.namespace,
            spec={"containers": [{"name": "main"}]},
        )
        self.state = NavigationState(self.identity.context, "header-a", resource="diagnostics")
        self.workspace = SimpleNamespace(
            store=SimpleNamespace(observation=self.observation),
            diagnostic_request=self.data.request,
            resolve_diagnostic=self.resolve,
            run_popeye=lambda: self.calls.append(("popeye",)),
            cancel_diagnostics=lambda: self.calls.append(("cancel",)),
        )
        self.target = ResourceTarget(self.identity, "", "pods", "team", POD.name, POD.uid)
        self.captured = CapturedResource(self.client, PODS, self.record, self.target, lambda: True)
        self.app = SimpleNamespace(
            workspace=self.workspace,
            sessions=SimpleNamespace(client=self.client, observation=self.connection),
            commands=SimpleNamespace(policy=AccessPolicy(True)),
            diagnostic_navigation=SimpleNamespace(
                active=True,
                overview=lambda **kwargs: self.calls.append(("overview", kwargs)),
                open=lambda scope: self.calls.append(("open", scope)),
            ),
            targets=SimpleNamespace(capture=lambda: self.captured),
            navigator=SimpleNamespace(
                capture=lambda: self.state,
                clear_rows=lambda: self.calls.append(("clear",)),
                restore_pending=lambda state: self.calls.append(("restore", state)),
            ),
            views=SimpleNamespace(request=lambda: self.calls.append(("render",))),
            push_screen=self.screens.append,
            chrome=WorkspaceChrome(
                lambda: ("owned", "owned", "fixture", "header-a", "Connected"), "test"
            ),
        )
        self.actions = DiagnosticActions(self.app)

    async def resolve(self, request, ref):
        self.calls.append(("resolve", request, ref))
        return self.record


def test_collection_commands_preserve_scope_ports_and_explicit_popeye_intent():
    owner = Owner()
    owner.actions.overview()
    assert owner.calls == [("overview", {})]
    owner.actions.diagnose()
    assert owner.calls[-1][0] == "open" and owner.calls[-1][1].root.uid == POD.uid
    assert owner.calls[-1][1].namespace == "team"
    owner.actions.popeye()
    owner.actions.cancel()
    assert ("popeye",) in owner.calls and ("cancel",) in owner.calls
    assert owner.calls.count(("restore", owner.state)) == 2
    owner.app.diagnostic_navigation.active = False
    owner.actions.popeye()
    assert (
        owner.calls[-1][0] == "overview"
        and owner.calls[-1][1]["after_open"] == owner.actions.popeye
    )
    owner.app.diagnostic_navigation.active = True
    owner.workspace.diagnostic_request = None
    owner.actions.popeye()
    assert owner.calls[-1][0] == "overview"
    owner.state = None
    owner.actions.cancel()


@pytest.mark.parametrize(
    "invalid", ["missing", "current", "client", "session", "connection", "unsupported"]
)
def test_diagnose_requires_actual_current_namespaced_pod_or_supported_workload(invalid):
    owner = Owner()
    if invalid == "missing":
        owner.captured = None
        owner.actions.diagnose()
        assert not owner.calls
        return
    if invalid == "current":
        owner.captured = CapturedResource(
            owner.client, PODS, owner.record, owner.target, lambda: False
        )
    elif invalid == "client":
        owner.app.sessions.client = object()
    elif invalid == "session":
        owner.app.sessions.observation = replace(
            owner.connection, identity=SessionIdentity("replacement", 1)
        )
    elif invalid == "connection":
        owner.app.sessions.observation = SessionObservation()
    else:
        owner.captured = CapturedResource(
            owner.client,
            PODS,
            owner.record,
            replace(owner.target, resource="services"),
            lambda: True,
        )
    with pytest.raises(AppError):
        owner.actions.diagnose()
    assert not owner.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [DiagnosticLogMode.CURRENT, DiagnosticLogMode.PREVIOUS])
async def test_log_target_preserves_namespace_and_full_session_across_independent_native_refresh(
    mode,
):
    owner = Owner()
    await owner.actions.open_logs(owner.data.request, owner.item, mode)
    screen = owner.screens[0]
    assert screen.previous is (mode is DiagnosticLogMode.PREVIOUS)
    assert screen.stream.target == replace(owner.target, container="main")
    assert screen.stream.client is owner.client
    owner.workspace.diagnostic_request = replace(owner.data.request, revision=2)
    owner.workspace.store.observation = replace(owner.observation, revision=99, diagnostics=None)
    screen.stream.require_current()
    assert not screen.closed and not screen.stale


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["client", "session", "connection", "view-session", "header"])
async def test_open_log_current_callback_rejects_context_and_namespace_changes(changed):
    owner = Owner()
    await owner.actions.open_logs(owner.data.request, owner.item, DiagnosticLogMode.CURRENT)
    screen = owner.screens[0]
    if changed == "client":
        owner.app.sessions.client = object()
    elif changed == "session":
        owner.app.sessions.observation = replace(
            owner.connection, identity=replace(owner.identity, generation=2)
        )
    elif changed == "connection":
        owner.app.sessions.observation = SessionObservation()
    elif changed == "view-session":
        owner.workspace.store.observation = replace(
            owner.observation,
            connection=replace(owner.connection, identity=SessionIdentity("replacement", 1)),
        )
    else:
        owner.workspace.store.observation = replace(
            owner.observation, connection=replace(owner.connection, namespace="other")
        )
    with pytest.raises(AppError, match="stale"):
        screen.stream.require_current()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "client",
        "identity",
        "session",
        "subject",
        "resource",
        "group",
        "plural",
        "kind",
        "namespace",
        "container",
        "mode",
    ],
)
async def test_log_candidate_guard_rejects_invalid_identity_before_any_get(invalid):
    owner = Owner()
    item = owner.item
    if invalid == "client":
        owner.app.sessions.client = None
    elif invalid == "identity":
        owner.app.sessions.observation = SessionObservation()
    elif invalid == "session":
        owner.app.sessions.observation = replace(
            owner.connection, identity=replace(owner.identity, generation=3)
        )
    elif invalid == "subject":
        item = replace(item, subject=None)
    elif invalid == "resource":
        item = replace(item, subject=replace(POD, resource=None))
    elif invalid in {"group", "plural", "kind"}:
        change = {
            "group": {"group": "apps"},
            "plural": {"name": "deployments"},
            "kind": {"kind": "Deployment"},
        }[invalid]
        item = replace(item, subject=replace(POD, resource=replace(PODS, **change)))
    elif invalid == "namespace":
        item = replace(item, subject=replace(POD, namespace=None))
    elif invalid == "container":
        item = replace(item, container=None)
    else:
        item = replace(item, log_modes=frozenset())
    with pytest.raises(AppError, match="Logs require"):
        await owner.actions.open_logs(owner.data.request, item, DiagnosticLogMode.CURRENT)
    assert not owner.calls and not owner.screens


@pytest.mark.asyncio
async def test_resolve_cannot_publish_a_log_screen_after_request_changes():
    owner = Owner()

    async def replaced(request, ref):
        owner.workspace.diagnostic_request = replace(request, revision=2)
        return owner.record

    owner.workspace.resolve_diagnostic = replaced
    with pytest.raises(AppError, match="changed while resolving"):
        await owner.actions.open_logs(owner.data.request, owner.item, DiagnosticLogMode.CURRENT)
    assert not owner.screens
    with pytest.raises(AppError, match="changed before opening"):
        await owner.actions.open_logs(owner.data.request, owner.item, DiagnosticLogMode.CURRENT)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["uid", "missing", "name", "namespace", "container"])
async def test_fresh_pod_and_container_checks_reject_replacements_and_removed_containers(invalid):
    owner = Owner()
    changes = {
        "uid": {"uid": "replacement"},
        "missing": {"uid": None},
        "name": {"name": "other"},
        "namespace": {"namespace": "other"},
    }
    if invalid == "container":
        owner.record = record(
            PODS,
            name=POD.name,
            uid=POD.uid,
            namespace=POD.namespace,
            spec={"containers": [{"name": "different"}]},
        )
    else:
        owner.record = replace(owner.record, **changes[invalid])
    with pytest.raises(AppError, match=r"unavailable|missing or replaced"):
        await owner.actions.open_logs(owner.data.request, owner.item, DiagnosticLogMode.CURRENT)
    assert not owner.screens


@pytest.mark.asyncio
@pytest.mark.parametrize("created_after", [True, False, None])
async def test_name_only_popeye_logs_compare_report_time_before_binding_current_uid(created_after):
    item = replace(
        finding(),
        identity=DiagnosticIdentity.NAME_ONLY,
        subject=replace(POD, uid=None),
        log_modes=frozenset(),
    )
    item = replace(item, evidence=(replace(item.evidence[0], reported_at=NOW),))
    owner = Owner(item)
    owner.record = replace(
        owner.record,
        created_at=None
        if created_after is None
        else NOW + timedelta(seconds=1 if created_after else -1),
    )
    if created_after:
        with pytest.raises(AppError, match="created after the report"):
            await owner.actions.open_logs(owner.data.request, owner.item, DiagnosticLogMode.CURRENT)
        assert not owner.screens
    else:
        await owner.actions.open_logs(owner.data.request, owner.item, DiagnosticLogMode.CURRENT)
        assert owner.screens[0].stream.target.uid == POD.uid
