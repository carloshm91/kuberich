"""Open captured resource operations and drain their per-client ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from textual.app import App

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.forwarding import ForwardPreferences
from kuberich.domain.forward_presets import annotation_preset, resolve_mappings
from kuberich.domain.interactions import RangeSelection
from kuberich.domain.operations import MAX_BATCH, ResourceAction
from kuberich.domain.port_forwards import suggested_port
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.workloads import WorkloadAction, applicable
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import MutationManager, MutationService
from kuberich.services.ownership import finish_owned
from kuberich.services.port_forwards import ForwardManager, ForwardService
from kuberich.services.processes import ProcessRunner
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.target_capture import CapturedResource

if TYPE_CHECKING:
    from kuberich.ui.aggregate_logs import AggregateLogScreen
    from kuberich.ui.inspection import Page


@dataclass(frozen=True)
class OperationContext:
    chrome: WorkspaceChrome
    trail: tuple[str, ...]
    shell: tuple[str, ...]
    environment: Mapping[str, str]
    directory: Path
    route: ViewRoute
    modal: bool


class ResourceOperations:
    """Own operation viewers without reaching into the root application's state."""

    def __init__(
        self,
        host: App[None],
        capture: Callable[[str | None], CapturedResource[KubernetesSession] | None],
        context: Callable[[], OperationContext],
        policy: AccessPolicy,
        mutations: MutationManager,
        forwards: ForwardManager,
        processes: ProcessRunner,
        status: Callable[[str], None],
        *,
        session_current: Callable[[KubernetesSession, SessionIdentity], bool],
        forwarding: Callable[[], ForwardPreferences],
        delete_context: Callable[[], None],
        stop_plugins: Callable[[KubernetesSession], Awaitable[None]],
    ) -> None:
        self.host, self.capture, self.context = host, capture, context
        self.policy, self.mutations, self.forwards = policy, mutations, forwards
        self.processes, self.status = processes, status
        self.session_current, self.forwarding = session_current, forwarding
        self.delete_context, self.stop_plugins = delete_context, stop_plugins
        self._aggregate_screens: set[AggregateLogScreen] = set()
        self._auto_forward_contexts: set[str] = set()

    @property
    def retained_aggregate_count(self) -> int:
        """Retain viewers through asynchronous cleanup even after DOM removal."""
        return len(self._aggregate_screens)

    def inspect(self, page: Page) -> None:
        from kuberich.services.inspection import InspectionService
        from kuberich.ui.inspection import InspectionScreen

        selection = self.capture(None)
        if selection is not None:
            client, resource, _, target, current = selection
            self.host.push_screen(
                InspectionScreen(
                    InspectionService(client, resource, target, self.policy, current),
                    page,
                )
            )

    def annotate(self) -> None:
        from kuberich.ui.mutations import AnnotationScreen

        try:
            self.policy.require(Action.MUTATE)
        except AppError as error:
            self.status(str(error))
            return
        selection = self.capture(None)
        if selection is not None:
            client, resource, _, target, current = selection
            source = MutationService(client, resource, target, self.policy, current)
            try:
                source.require_current()
            except AppError:
                self.status(
                    "This captured resource API cannot be modified here. Select a patchable resource."
                )
                return
            self.host.push_screen(AnnotationScreen(source, self.mutations))

    def writes(self) -> None:
        from kuberich.ui.mutations import MutationHistoryScreen

        if not self.context().modal:
            self.host.push_screen(MutationHistoryScreen(self.mutations))

    def operate(
        self,
        action: ResourceAction,
        *,
        batch: bool = False,
        uids: tuple[str, ...] | None = None,
        labels: tuple[str, ...] | None = None,
        visible_uids: tuple[str, ...] = (),
        all_uids: tuple[str, ...] = (),
        selection: RangeSelection | None = None,
    ) -> None:
        from kuberich.services.operations import ResourceOperationService
        from kuberich.ui.operations import ResourceOperationScreen

        if self.context().route.kind is ViewKind.CONTEXTS and action is ResourceAction.DELETE:
            self.delete_context()
            return
        try:
            self.policy.require(Action.MUTATE)
        except AppError as error:
            self.status(str(error))
            return
        captured_selection = self.capture(None)
        if captured_selection is None:
            return
        selections = [captured_selection]
        if batch:
            if selection is not None:
                selection.prune(visible_uids)
            marked = selection.marked if selection is not None else frozenset()
            if uids is None:
                uids = tuple(uid for uid in visible_uids if uid in marked) if marked else all_uids
            if len(uids) > MAX_BATCH:
                self.status("Filter this view to at most 100 rows before choosing a delete batch.")
                return
            selections = []
            for uid in uids:
                captured = self.capture(uid)
                if captured is None:
                    return
                selections.append(captured)
        sources = []
        try:
            for client, resource, _, target, current in selections:
                source = ResourceOperationService(
                    client, resource, target, self.policy, current, action
                )
                source.require_current()
                sources.append(source)
        except AppError as error:
            self.status(str(error))
            return
        self.host.push_screen(
            ResourceOperationScreen(tuple(sources), self.mutations, batch=batch, labels=labels)
        )

    def workload(self, operation: WorkloadAction, argument: str = "") -> None:
        from kuberich.services.workloads import WorkloadService
        from kuberich.ui.workloads import WorkloadScreen

        try:
            self.policy.require(
                Action.READ if operation is WorkloadAction.STATUS else Action.MUTATE
            )
        except AppError as error:
            self.status(str(error))
            return
        selection = self.capture(None)
        if selection is not None:
            client, resource, _, target, current = selection
            try:
                applicable(resource, operation)
            except AppError as error:
                self.status(str(error))
                return
            self.host.push_screen(
                WorkloadScreen(
                    WorkloadService(client, resource, target, self.policy, current),
                    self.mutations,
                    operation,
                    argument,
                )
            )

    def edit(self) -> None:
        from kuberich.services.editing import EditingService
        from kuberich.ui.editing import EditingScreen

        try:
            self.policy.require(Action.MUTATE)
        except AppError as error:
            self.status(str(error))
            return
        context = self.context()
        selection = self.capture(None)
        if selection is not None:
            client, resource, _, target, current = selection
            source = EditingService(client, resource, target, self.policy, current)
            try:
                source.require_current()
            except AppError:
                self.status("Select a readable, patchable resource before editing.")
                return
            self.host.push_screen(
                EditingScreen(
                    source,
                    self.mutations,
                    self.processes,
                    dict(context.environment),
                    context.directory,
                )
            )

    def port_forward(self) -> None:
        from kuberich.ui.port_forwards import ForwardPrompt

        try:
            self.policy.require(Action.PORT_FORWARD)
        except AppError as error:
            self.status(str(error))
            return
        context = self.context()
        selection = self.capture(None)
        if selection is None:
            return
        client, _, record, target, selected = selection

        def current_connection() -> bool:
            return self.session_current(client, target.session)

        source = ForwardService(
            client,
            target,
            self.policy,
            current_connection,
            environment=context.environment,
            directory=context.directory,
        )
        try:
            source.require_current()
        except AppError as error:
            self.status(str(error))
            return
        remote = suggested_port(target.resource, record.manifest)
        try:
            options = self.forwarding().for_context(target.session.context)
            annotated = annotation_preset(record.manifest, target.resource)
            presets = options.presets
            initial = f"0:{remote}"
            if annotated is not None:
                preset, automatic = annotated
                if automatic and (
                    options.auto_annotations
                    or target.session.context in self._auto_forward_contexts
                ):
                    identity = self.forwards.start(
                        source,
                        resolve_mappings(preset.ports, target.resource, record.manifest),
                        intent=preset.intent,
                    )
                    self._forward_started(identity)
                    return
                presets = (preset, *presets)
                initial = preset.ports
        except AppError as error:
            self.status(str(error))
            return
        self.host.push_screen(
            ForwardPrompt(
                self.forwards,
                source,
                selected,
                initial=initial,
                manifest=record.manifest,
                initial_intent=annotated[0].intent if annotated is not None else None,
                presets=presets,
                trust_annotations=lambda: self._auto_forward_contexts.add(target.session.context),
            ),
            self._forward_started,
        )

    def open_logs(self, *, containers_first: bool = False, uid: str | None = None) -> None:
        from kuberich.domain.logs import log_containers
        from kuberich.services.attach import AttachService
        from kuberich.services.logs import LogStream
        from kuberich.services.shell import ShellService
        from kuberich.services.transfers import TransferService
        from kuberich.ui.containers import ContainerScreen
        from kuberich.ui.logs import LogScreen

        context = self.context()
        selection = self.capture(uid)
        if selection is None:
            return
        client, resource, record, target, current = selection
        try:
            if resource.group or resource.name != "pods" or not record.namespace:
                raise AppError("Select a namespaced pod to open container logs.")
            containers = log_containers(record.manifest)
            if not containers:
                raise AppError("The selected pod has no regular/init/ephemeral containers.")
        except AppError as error:
            self.status(str(error))
            return
        stream = LogStream(client, target, self.policy, current)
        self.host.push_screen(
            ContainerScreen(
                stream,
                record.manifest,
                shell=ShellService(
                    client,
                    target,
                    self.policy,
                    current,
                    shell=context.shell,
                    environment=context.environment,
                    directory=context.directory,
                ),
                processes=self.processes,
                attach=AttachService(
                    client,
                    target,
                    self.policy,
                    current,
                    environment=context.environment,
                    directory=context.directory,
                ),
                transfers=TransferService(
                    client,
                    target,
                    self.policy,
                    current,
                    environment=context.environment,
                    directory=context.directory,
                ),
                chrome=context.chrome,
                trail=context.trail,
            )
            if containers_first
            else LogScreen(stream, containers, chrome=context.chrome, trail=context.trail)
        )

    def logs_all(self) -> None:
        from kuberich.domain.aggregate_logs import workload_kind
        from kuberich.services.aggregate_logs import AggregateLogs
        from kuberich.ui.aggregate_logs import AggregateLogScreen

        if self._aggregate_screens:
            self.status("Previous aggregate logs are closing; wait for owned cleanup to finish.")
            return
        if self.context().route.kind is ViewKind.CUSTOM:
            self.status(
                "Generic resources retain read-only inspection; use an ordinary Pod/workload view for aggregate logs."
            )
            return
        context = self.context()
        selection = self.capture(None)
        if selection is None:
            return
        client, resource, _, target, current = selection
        try:
            workload_kind(target)
            owner = AggregateLogs(client, resource, target, self.policy, current)
        except AppError as error:
            self.status(str(error))
            return
        screen = AggregateLogScreen(
            owner,
            chrome=context.chrome,
            trail=context.trail,
            stopped=lambda: self._aggregate_screens.discard(screen),
        )
        self._aggregate_screens.add(screen)
        self.host.push_screen(screen)

    def port_forwards(self, selected: UUID | None = None) -> None:
        from kuberich.ui.port_forwards import ForwardScreen

        context = self.context()
        if not context.modal:
            self.host.push_screen(
                ForwardScreen(self.forwards, context.chrome, context.trail, selected=selected)
            )

    def _forward_started(self, identity: UUID | None) -> None:
        if identity is not None:
            self.port_forwards(identity)

    async def close_for_client(self, client: KubernetesSession) -> None:
        from kuberich.ui.configuration_data import ConfigurationScreen
        from kuberich.ui.containers import ContainerScreen
        from kuberich.ui.editing import EditingScreen
        from kuberich.ui.inspection import InspectionScreen
        from kuberich.ui.logs import LogScreen
        from kuberich.ui.mutations import AnnotationScreen
        from kuberich.ui.operations import ResourceOperationScreen
        from kuberich.ui.plugins import PluginScreen
        from kuberich.ui.terminal import ShellScreen
        from kuberich.ui.transfers import TransferScreen
        from kuberich.ui.workloads import WorkloadScreen

        closing = asyncio.gather(
            *(
                screen.stop_owned()
                for screen in tuple(self.host.screen_stack)
                if isinstance(screen, (InspectionScreen, ContainerScreen, LogScreen, ShellScreen))
                and (
                    screen.service.client
                    if isinstance(screen, InspectionScreen)
                    else screen.shell.client
                    if isinstance(screen, ShellScreen)
                    else screen.stream.client
                )
                is client
            ),
            self.stop_plugins(client),
            self.mutations.stop_for_client(client),
            self.forwards.stop_for_client(client),
            *(
                screen.stop_owned()
                for screen in tuple(self.host.screen_stack)
                if isinstance(screen, ConfigurationScreen) and screen.service.client is client
            ),
            *(
                screen.stop_owned()
                for screen in tuple(self._aggregate_screens)
                if screen.owner.client is client
            ),
            *(
                screen.stop_owned()
                for screen in tuple(self.host.screen_stack)
                if isinstance(
                    screen,
                    (AnnotationScreen, EditingScreen, WorkloadScreen, TransferScreen, PluginScreen),
                )
                and screen.source.client is client
            ),
            *(
                screen.stop_owned()
                for screen in tuple(self.host.screen_stack)
                if isinstance(screen, ResourceOperationScreen)
                and screen.sources[0].client is client
            ),
        )
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await finish_owned(closing)
            raise
