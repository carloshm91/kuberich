"""Explicit diagnostic collection and independently captured log-viewer actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from kuberich.domain.cluster_diagnostics import (
    DiagnosticFinding,
    DiagnosticIdentity,
    DiagnosticLogMode,
    DiagnosticRequest,
    DiagnosticScope,
)
from kuberich.domain.relationships import reference_for
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.views import USABLE_CONNECTIONS
from kuberich.errors import AppError
from kuberich.services.access import Action
from kuberich.ui.diagnostic_evidence import available_log_modes

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp


class DiagnosticActions:
    def __init__(self, app: KubeRichApp) -> None:
        self.app = app

    def overview(self) -> None:
        self.app.diagnostic_navigation.overview()

    def diagnose(self) -> None:
        from kuberich.domain.aggregate_logs import workload_kind

        selection = self.app.targets.capture()
        if selection is None:
            return
        client, resource, record, target, current = selection
        connection = self.app.sessions.observation
        if (
            not current()
            or self.app.sessions.client is not client
            or target.session != connection.identity
            or connection.state not in USABLE_CONNECTIONS
        ):
            raise AppError("The diagnostic target changed; select a current Pod or workload.")
        workload_kind(target)
        ref = reference_for(resource, record)
        self.app.diagnostic_navigation.open(DiagnosticScope(target.session, ref.namespace, ref))

    def _replace(self, action: Callable[[], object]) -> None:
        state = self.app.navigator.capture()
        action()
        self.app.navigator.clear_rows()
        if state is not None:
            self.app.navigator.restore_pending(state)
        self.app.views.request()

    def popeye(self) -> None:
        if not self.app.diagnostic_navigation.active:
            self.app.diagnostic_navigation.overview(after_open=self.popeye)
            return
        if self.app.workspace.diagnostic_request is None:
            self.app.diagnostic_navigation.overview(after_open=self.popeye)
            return
        self._replace(self.app.workspace.run_popeye)

    def cancel(self) -> None:
        self._replace(self.app.workspace.cancel_diagnostics)

    async def open_logs(
        self, request: DiagnosticRequest, finding: DiagnosticFinding, mode: DiagnosticLogMode
    ) -> None:
        from kuberich.domain.logs import log_containers
        from kuberich.services.logs import LogStream
        from kuberich.ui.logs import LogScreen

        app = self.app
        client, identity = app.sessions.client, app.sessions.observation.identity
        view = app.workspace.store.observation
        header, revision = view.connection.namespace, view.revision
        ref = finding.subject
        if (
            client is None
            or identity is None
            or request.scope.session != identity
            or ref is None
            or ref.resource is None
            or ref.resource.group != ""
            or ref.resource.name != "pods"
            or ref.resource.kind != "Pod"
            or ref.namespace is None
            or finding.container is None
            or mode not in available_log_modes(finding)
        ):
            raise AppError(
                "Logs require a current captured Pod/container and an evidenced log mode."
            )
        app.commands.policy.require(Action.READ)

        def resolving() -> bool:
            observation = app.workspace.store.observation
            return (
                app.sessions.client is client
                and app.sessions.observation.identity == identity
                and app.sessions.observation.state in USABLE_CONNECTIONS
                and observation.revision == revision
                and observation.connection.namespace == header
                and app.workspace.diagnostic_request == request
                and observation.diagnostics is not None
                and observation.diagnostics.request == request
                and finding in observation.diagnostics.findings
            )

        if not resolving():
            raise AppError("Diagnostic evidence changed before opening logs.")
        record = await app.workspace.resolve_diagnostic(request, ref)
        if not resolving():
            raise AppError("Diagnostic evidence changed while resolving its log target.")
        if (
            record.uid is None
            or record.name != ref.name
            or record.namespace != ref.namespace
            or (ref.uid is not None and ref.uid != record.uid)
        ):
            raise AppError("The diagnostic Pod is missing or replaced; refresh its evidence.")
        if finding.identity is DiagnosticIdentity.NAME_ONLY:
            reported = tuple(
                item.reported_at for item in finding.evidence if item.reported_at is not None
            )
            if record.created_at is not None and reported and record.created_at > min(reported):
                raise AppError(
                    "The current Pod was created after the report; rerun Popeye before linking logs."
                )
        containers = log_containers(record.manifest)
        if finding.container not in containers:
            raise AppError("The captured container is unavailable in the current Pod.")
        target = ResourceTarget(
            identity, "", "pods", record.namespace, record.name, record.uid, finding.container
        )

        def current() -> bool:
            observation = app.workspace.store.observation
            return (
                app.sessions.client is client
                and app.sessions.observation.state in USABLE_CONNECTIONS
                and app.sessions.observation.identity == identity
                and observation.connection.identity == identity
                and observation.connection.namespace == header
            )

        stream = LogStream(client, target, app.commands.policy, current)
        app.push_screen(
            LogScreen(
                stream,
                containers,
                selected=finding.container,
                chrome=app.chrome,
                trail=("diagnostics", "evidence"),
                initial_previous=mode is DiagnosticLogMode.PREVIOUS,
            )
        )
