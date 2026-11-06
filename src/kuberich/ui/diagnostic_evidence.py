"""Read-only diagnostic provenance with explicit, captured action callbacks."""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static, TextArea
from textual.worker import Worker, WorkerCancelled

from kuberich.domain.cluster_diagnostics import (
    DiagnosticFinding,
    DiagnosticIdentity,
    DiagnosticLogMode,
    DiagnosticRequest,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
)
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.relationships import RelationshipRef
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.ui.chrome import (
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.read_only_text import ReadOnlyText
from kuberich.ui.text_navigation import text_bindings

if TYPE_CHECKING:
    from kuberich.services.exports import ExportChoices

_SHORTCUTS = (
    ("o", "Open resource"),
    ("e/n", "Open / next Event"),
    ("l/p", "Current / previous logs"),
    ("r", "Refresh evidence"),
    ("j/k", "Down / up"),
    ("Right", "Scroll right"),
    (":", "Command"),
    ("Esc", "Back"),
)


class _EvidenceText(ReadOnlyText, inherit_bindings=False):
    # Keep configurable document navigation while reserving l for the captured
    # current-log action. The global text.right key map must not reclaim it.
    BINDINGS: ClassVar[list[BindingType]] = [
        *TextArea.BINDINGS,
        *(
            binding
            for binding in text_bindings()
            if not isinstance(binding, Binding) or binding.id != "text.right"
        ),
        Binding("right", "scroll_right", "Scroll right", show=False, priority=True),
    ]


def _time(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else "unavailable"


def _reference(ref: RelationshipRef) -> str:
    return (
        f"{ref.kind}/{ref.name} · {('namespace ' + ref.namespace) if ref.namespace else 'cluster'}"
        f" · API {ref.api_version} · UID {ref.uid or 'unavailable'}"
    )


def available_log_modes(finding: DiagnosticFinding) -> frozenset[DiagnosticLogMode]:
    """External container provenance permits only an explicitly verified current read."""
    ref = finding.subject
    if (
        finding.identity is DiagnosticIdentity.NAME_ONLY
        and ref is not None
        and ref.resource is not None
        and ref.resource.group == ""
        and ref.resource.name == "pods"
        and ref.resource.kind == "Pod"
        and ref.namespace is not None
        and finding.container
    ):
        return finding.log_modes | {DiagnosticLogMode.CURRENT}
    return finding.log_modes


def evidence_text(
    request: DiagnosticRequest,
    finding: DiagnosticFinding,
    sources: tuple[DiagnosticSource, ...],
) -> str:
    """Keep acquisition, reported time and identity separate in literal evidence."""
    lines = [
        f"Severity: {finding.severity.value} · source: {finding.source.value}",
        f"Category: {finding.category.value} · container: {finding.container or 'none'}",
        f"Collection namespace: {request.scope.namespace or 'all namespaces'}",
        "Subject: " + (_reference(finding.subject) if finding.subject else "unresolved"),
        "Identity: " + finding.identity.value,
        finding.summary,
        finding.explanation,
    ]
    if finding.identity is DiagnosticIdentity.NAME_ONLY:
        lines.append(
            "Current object by name; report has no UID. Historical identity is unverified."
        )
    if finding.tool_version is not None:
        lines.append(f"Producer version: {finding.tool_version}")
    if finding.source_code is not None:
        lines.append(f"Source code: {finding.source_code}")
    for source in sources:
        lines.extend(
            (
                "",
                f"Source {source.key}: {source.kind.value} · {source.status.value}",
                f"Locally observed: {_time(source.observed_at)}",
                f"Collection resource version: {source.resource_version or 'unavailable'}",
                f"Omitted findings: {source.omitted_findings}",
                source.detail,
            )
        )
    for index, item in enumerate(finding.evidence, 1):
        lines.extend(
            (
                "",
                f"Evidence {index}: {item.source.value} · {_reference(item.ref)}",
                f"Field path: {item.field_path}",
                f"Reason: {item.reason or 'unavailable'}",
                f"Locally observed: {_time(item.observed_at)}",
                f"Server reported: {_time(item.reported_at)}",
                "Historical evidence; does not establish a current failure."
                if item.historical
                else "Reported time alone does not establish collection freshness or cause.",
                item.message,
            )
        )
    if not finding.evidence:
        lines.append("No individual evidence items were retained; source limitations still apply.")
    return "\n".join(safe_text(line, multiline=True).plain for line in lines)


class DiagnosticEvidenceScreen(CommandWorkspace):
    AUTO_FOCUS = "#diagnostic-evidence-text"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("o", "open_object", "Open resource"),
        Binding("e", "open_event", "Open Event"),
        Binding("n", "next_event", "Next Event"),
        Binding("l", "logs('current')", "Current logs", priority=True),
        Binding("p", "logs('previous')", "Previous logs"),
        Binding("r", "refresh", "Refresh evidence"),
        Binding("escape", "back", "Back"),
    ]
    DEFAULT_CSS = """
    DiagnosticEvidenceScreen { layout: vertical; background: $background; }
    #diagnostic-evidence-title, #diagnostic-evidence-status { height: 1; padding: 0 1; }
    #diagnostic-evidence-title { color: $accent; text-overflow: ellipsis; }
    #diagnostic-evidence-frame { height: 1fr; min-height: 2; }
    #diagnostic-evidence-text { height: 1fr; min-height: 1; border: none; }
    #diagnostic-evidence-buttons { height: 1; }
    #diagnostic-evidence-buttons Button { height: 1; min-width: 5; width: 1fr; border: none; }
    #diagnostic-evidence-status { text-overflow: ellipsis; color: $text-muted; }
    DiagnosticEvidenceScreen.short #diagnostic-evidence-title { display: none; }
    """

    def __init__(
        self,
        request: DiagnosticRequest,
        finding: DiagnosticFinding,
        *,
        sources: tuple[DiagnosticSource, ...] = (),
        current: Callable[[], bool],
        open_object: Callable[[RelationshipRef], Awaitable[None]],
        open_logs: Callable[[DiagnosticLogMode], Awaitable[None]],
        refresh: Callable[[], None],
        snapshot: Callable[[DiagnosticRequest], DiagnosticSnapshot | None] | None = None,
        header_namespace: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__()
        self.request, self.finding, self.sources = request, finding, sources
        self.current = current
        self.open_object, self.open_logs, self.refresh_evidence = open_object, open_logs, refresh
        self.invalidated = False
        self._export_snapshot = snapshot
        self._export_namespace = header_namespace
        self._action_worker: Worker[None] | None = None
        self.events = tuple(
            item
            for item in finding.evidence
            if item.source is DiagnosticSourceKind.EVENT
            and item.ref.resource is not None
            and item.ref.resource.kind == "Event"
            and item.ref.uid is not None
        )
        self.event_index = 0
        self.viewer = _EvidenceText(
            evidence_text(request, finding, sources),
            read_only=True,
            soft_wrap=False,
            highlight_cursor_line=False,
            show_line_numbers=False,
            id="diagnostic-evidence-text",
        )
        self.status = Static(
            "Observed evidence is not proof of cause. No logs are read until requested.",
            markup=False,
            id="diagnostic-evidence-status",
        )

    def capture_export(self, at: datetime) -> "ExportChoices":
        """Capture rendered evidence and, when available, its exact retained request."""
        from dataclasses import replace

        from kuberich.domain.exports import (
            DiagnosticsSource,
            DocumentSource,
            ExportPresentation,
            ExportScope,
        )
        from kuberich.ui.export_captures import captured_lease

        if not self.is_mounted or self.invalidated or not self.current():
            return ()
        request, finding = self.request, self.finding
        header = self._export_namespace() if self._export_namespace is not None else None
        snapshot = self._export_snapshot(request) if self._export_snapshot is not None else None
        if snapshot is not None and snapshot.request != request:
            snapshot = None
        times = tuple(item.observed_at for item in finding.evidence) + tuple(
            source.observed_at for source in self.sources if source.observed_at is not None
        )
        scope = ExportScope(
            export_at=at,
            source_at=snapshot.observed_at if snapshot is not None else max(times, default=None),
            context=request.scope.session.context,
            header_namespace=header,
            collection_namespace=request.scope.namespace,
            namespace_mode="one" if request.scope.namespace is not None else "all",
            api_version=finding.subject.api_version if finding.subject is not None else None,
            resource=finding.subject.resource.name
            if finding.subject is not None and finding.subject.resource is not None
            else None,
            kind=finding.subject.kind if finding.subject is not None else None,
            name=finding.subject.name if finding.subject is not None else None,
            uid=finding.subject.uid if finding.subject is not None else None,
            container=finding.container,
        )

        def current() -> bool:
            return (
                self.is_mounted
                and not self.invalidated
                and self.current()
                and self.request == request
                and self.finding is finding
                and (self._export_namespace() if self._export_namespace is not None else None)
                == header
            )

        document = captured_lease(
            scope,
            DocumentSource(page="evidence", text=self.viewer.text),
            current,
            presentation=ExportPresentation(view="diagnostic-evidence"),
        )
        choices: ExportChoices = (("screen", replace(document, session=request.scope.session)),)
        if snapshot is not None:
            root = request.scope.root
            diagnostic_scope = replace(
                scope,
                api_version=root.api_version if root is not None else None,
                resource=root.resource.name
                if root is not None and root.resource is not None
                else None,
                kind=root.kind if root is not None else None,
                name=root.name if root is not None else None,
                uid=root.uid if root is not None else None,
                container=None,
            )

            snapshot_reader = cast(
                Callable[[DiagnosticRequest], DiagnosticSnapshot | None], self._export_snapshot
            )

            def diagnostics_current() -> bool:
                if not current():
                    return False
                retained = snapshot_reader(request)
                return retained is not None and retained.request == request

            diagnostic = captured_lease(
                diagnostic_scope,
                DiagnosticsSource(snapshot=snapshot),
                diagnostics_current,
                presentation=ExportPresentation(view="diagnostics"),
            )
            choices += (("diagnostics", replace(diagnostic, session=request.scope.session)),)
        return choices

    def compose(self) -> ComposeResult:
        if hasattr(self.app, "chrome"):
            yield WorkspaceHeader(self.app.chrome, _SHORTCUTS, binding_profile="text")
        with WorkspaceBars():
            yield Static(
                safe_text(
                    f"{self.finding.severity.value} · {self.finding.source.value} · {self.finding.summary}"
                ),
                markup=False,
                id="diagnostic-evidence-title",
            )
            yield from self.command_bar()
        with WorkspaceFrame(id="diagnostic-evidence-frame"):
            yield self.viewer
            with Horizontal(id="diagnostic-evidence-buttons"):
                yield Button("Resource", id="diagnostic-open", compact=True)
                yield Button("Event", id="diagnostic-event", compact=True)
                yield Button("Next Event", id="diagnostic-next-event", compact=True)
                yield Button("Logs", id="diagnostic-current", compact=True)
                yield Button("Previous", id="diagnostic-previous", compact=True)
                yield Button("Refresh", id="diagnostic-refresh", compact=True)
                yield Button("Back", id="diagnostic-back", compact=True)
            yield self.status
        yield Breadcrumbs(("diagnostics", "evidence"), "Diagnostics")

    def on_mount(self) -> None:
        self.validate_target()

    def validate_target(self) -> None:
        if not self.current():
            self.invalidated = True
            self.status.update("Diagnostic evidence changed; return and select a current finding.")
        actions = {
            "diagnostic-open": self.finding.subject is not None
            and self.finding.subject.resource is not None,
            "diagnostic-event": bool(self.events),
            "diagnostic-next-event": len(self.events) > 1,
            "diagnostic-current": DiagnosticLogMode.CURRENT in available_log_modes(self.finding),
            "diagnostic-previous": DiagnosticLogMode.PREVIOUS in available_log_modes(self.finding),
            "diagnostic-refresh": True,
        }
        for identifier, available in actions.items():
            self.query_one("#" + identifier, Button).disabled = self.invalidated or not available

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "back":
            return True
        return not self.invalidated and not isinstance(self.focused, Input)

    async def _perform(self, callback: Callable[[], Awaitable[None]], dismiss: bool) -> None:
        try:
            await callback()
        except (AppError, ConnectionProblem) as error:
            if not self.invalidated:
                self.status.update(safe_text(str(error)))
        else:
            if dismiss and self.app.screen is self:
                self.dismiss()

    def _start(self, callback: Callable[[], Awaitable[None]], *, dismiss: bool = False) -> None:
        self.validate_target()
        if self.invalidated:
            return
        if self._action_worker is not None and not self._action_worker.is_finished:
            self.status.update("A diagnostic action is already pending.")
            return
        self._action_worker = self.run_worker(self._perform(callback, dismiss), exit_on_error=True)

    def action_open_object(self) -> None:
        ref = self.finding.subject
        if ref is not None and ref.resource is not None:
            self._start(lambda: self.open_object(ref), dismiss=True)

    def action_open_event(self) -> None:
        if self.events:
            item = self.events[self.event_index]
            self._start(lambda: self.open_object(item.ref), dismiss=True)

    def action_next_event(self) -> None:
        if self.events:
            self.event_index = (self.event_index + 1) % len(self.events)
            item = self.events[self.event_index]
            self.status.update(
                safe_text(
                    f"Event {self.event_index + 1}/{len(self.events)} · {_reference(item.ref)}"
                )
            )

    def action_logs(self, mode: str) -> None:
        selected = DiagnosticLogMode(mode)
        if selected in available_log_modes(self.finding):
            self._start(lambda: self.open_logs(selected))

    def action_refresh(self) -> None:
        self.validate_target()
        if not self.invalidated:
            self.refresh_evidence()
            self.dismiss()

    def action_back(self) -> None:
        if not self.leave_command():
            self.dismiss()

    def back(self) -> None:
        self.action_back()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        actions = {
            "diagnostic-open": self.action_open_object,
            "diagnostic-event": self.action_open_event,
            "diagnostic-next-event": self.action_next_event,
            "diagnostic-current": lambda: self.action_logs("current"),
            "diagnostic-previous": lambda: self.action_logs("previous"),
            "diagnostic-refresh": self.action_refresh,
            "diagnostic-back": self.action_back,
        }
        action = actions.get(event.button.id or "")
        if action is not None:
            action()

    async def stop_owned(self) -> None:
        self.invalidated = True
        if self._action_worker is not None:
            self._action_worker.cancel()
            with suppress(WorkerCancelled):
                await self._action_worker.wait()

    async def on_unmount(self) -> None:
        await self.stop_owned()
