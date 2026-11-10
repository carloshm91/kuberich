"""Open captured resource operations and drain their per-client ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from textual.app import App

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.forwarding import ForwardPreferences
from kuberich.domain.forward_presets import annotation_preset, resolve_mappings
from kuberich.domain.interactions import RangeSelection
from kuberich.domain.metrics import MetricsSnapshot
from kuberich.domain.node_maintenance import MaintenanceMode
from kuberich.domain.operations import MAX_BATCH, ResourceAction
from kuberich.domain.port_forwards import suggested_port
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.workloads import WorkloadAction, applicable
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import MutationManager, MutationService
from kuberich.services.ownership import finish_owned
from kuberich.services.port_forwards import ForwardInfo, ForwardManager, ForwardService
from kuberich.services.processes import ProcessRunner
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.target_capture import CapturedResource

if TYPE_CHECKING:
    from kuberich.config.node_shell import NodeShellSettings
    from kuberich.domain.container_inspection import ContainerIdentity
    from kuberich.domain.resources import Discovery
    from kuberich.services.curated_navigation import CuratedOrigin, ResolvedCuratedDestination
    from kuberich.services.exports import ExportChoices
    from kuberich.services.log_reads import LogReadLease
    from kuberich.services.node_shell import NodeShellManager
    from kuberich.ui.aggregate_logs import AggregateLogScreen
    from kuberich.ui.container_inspection import ContainerInspectionScreen
    from kuberich.ui.containers import ContainerScreen
    from kuberich.ui.inspection import InspectionScreen, Page
    from kuberich.ui.logs import LogScreen


@dataclass(frozen=True)
class OperationContext:
    chrome: WorkspaceChrome
    trail: tuple[str, ...]
    shell: tuple[str, ...]
    environment: Mapping[str, str]
    directory: Path
    route: ViewRoute
    modal: bool
    metrics: MetricsSnapshot | None = None
    discovery: Discovery | None = None
    revision: int = 0
    live: bool = True


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
        stop_benchmarks: Callable[[KubernetesSession], Awaitable[None]] | None = None,
        benchmark_forward: Callable[[ForwardInfo], None] | None = None,
        metric_history: Callable[[CapturedResource[KubernetesSession], ContainerIdentity], None]
        | None = None,
        navigate_curated: Callable[[CuratedOrigin, ResolvedCuratedDestination], None] | None = None,
        current_curated: Callable[[CuratedOrigin], bool] | None = None,
        log_read: Callable[[CapturedResource[KubernetesSession]], LogReadLease] | None = None,
        notice: Callable[[str], None] | None = None,
        node_shell_manager: NodeShellManager | None = None,
        node_shell_settings: Callable[[], NodeShellSettings] | None = None,
        node_shell_generation: Callable[[], int] | None = None,
        connection: Callable[[], tuple[KubernetesSession, SessionIdentity] | None] | None = None,
    ) -> None:
        self.host, self.capture, self.context = host, capture, context
        self.policy, self.mutations, self.forwards = policy, mutations, forwards
        self.processes, self.status = processes, status
        self.notice = status if notice is None else notice
        self.session_current, self.forwarding = session_current, forwarding
        self.delete_context, self.stop_plugins = delete_context, stop_plugins
        self.stop_benchmarks, self.benchmark_forward = stop_benchmarks, benchmark_forward
        self.metric_history = metric_history
        self.navigate_curated = navigate_curated
        self.current_curated = current_curated
        self.log_read = log_read
        self._log_screens: set[ContainerScreen | LogScreen] = set()
        self._aggregate_screens: set[AggregateLogScreen] = set()
        self._inspection_screens: set[ContainerInspectionScreen] = set()
        self._general_inspection_screens: set[InspectionScreen] = set()
        self._auto_forward_contexts: set[str] = set()
        from kuberich.config.node_shell import NodeShellSettings
        from kuberich.services.node_shell import NodeShellManager
        from kuberich.ui.ephemeral_debug_actions import EphemeralDebugActions
        from kuberich.ui.node_maintenance_actions import NodeMaintenanceActions
        from kuberich.ui.node_shell_actions import NodeShellActions

        self.node_maintenance = NodeMaintenanceActions(
            host, capture, context, policy, mutations, self.notice
        )
        self.ephemeral_debug = EphemeralDebugActions(
            host, capture, context, policy, mutations, processes, self.notice
        )

        self.node_shells = NodeShellActions(
            host,
            node_shell_manager if node_shell_manager is not None else NodeShellManager(),
            policy,
            mutations,
            processes,
            capture,
            context,
            node_shell_settings if node_shell_settings is not None else NodeShellSettings,
            node_shell_generation if node_shell_generation is not None else lambda: 0,
            self.notice,
            connection if connection is not None else lambda: None,
            session_current,
        )

    def open_node_maintenance(self, mode: MaintenanceMode) -> None:
        self.node_maintenance.open(mode)

    def open_ephemeral_debug(self) -> None:
        self.ephemeral_debug.open()

    def observe_node_operations(self) -> None:
        self.node_shells.observe()
        self.node_maintenance.observe()

    def open_node_shell(self) -> None:
        self.node_shells.open()

    def open_node_shell_recovery(self) -> None:
        self.node_shells.open_recovery()

    @property
    def retained_log_count(self) -> int:
        return len(self._log_screens)

    @property
    def retained_aggregate_count(self) -> int:
        """Retain viewers through asynchronous cleanup even after DOM removal."""
        return len(self._aggregate_screens)

    @property
    def retained_inspection_count(self) -> int:
        """Keep captured inspectors owned until their asynchronous cleanup finishes."""
        return len(self._inspection_screens)

    @property
    def retained_general_inspection_count(self) -> int:
        return len(self._general_inspection_screens)

    def capture_export(self, at: datetime) -> ExportChoices:
        from uuid import uuid4

        from kuberich.domain.exports import ExportCapture, ResourceSource
        from kuberich.services.exports import ExportLease, ResourceExportReader
        from kuberich.ui.export_captures import header_namespace, target_scope

        selection = self.capture(None)
        if selection is None:
            return ()
        client, resource, record, target, current = selection
        if not current():
            return ()
        scope = target_scope(
            at,
            target,
            resource=resource,
            resource_version=record.resource_version,
            header=header_namespace(self.context().chrome),
        )
        lease = ExportLease(
            id=uuid4(),
            capture=ExportCapture(
                scope=scope, source=ResourceSource(resource=resource, record=record)
            ),
            current=current,
            session=target.session,
            resource_reader=ResourceExportReader(client, resource, target, self.policy, current),
        )
        return (("resource-yaml", lease),)

    def inspect(self, page: Page) -> None:
        from kuberich.domain.resources import Discovery
        from kuberich.services.curated_navigation import CuratedNavigator
        from kuberich.services.inspection import InspectionService
        from kuberich.ui.export_captures import header_namespace
        from kuberich.ui.inspection import InspectionScreen

        if self._general_inspection_screens:
            self.status("Previous inspection is closing; wait for owned cleanup to finish.")
            return
        context = self.context()
        selection = self.capture(None)
        if selection is not None:
            client, resource, record, target, captured_current = selection
            revision = context.revision

            def current() -> bool:
                return (
                    captured_current()
                    and self.session_current(client, target.session)
                    and self.context().revision == revision
                )

            def origin_current(origin: CuratedOrigin) -> bool:
                return (
                    current()
                    and (self.current_curated is None or self.current_curated(origin))
                    and (
                        origin.session,
                        origin.revision,
                        origin.resource,
                        origin.record_name,
                        origin.record_uid,
                        origin.namespace,
                    )
                    == (
                        target.session,
                        revision,
                        resource,
                        target.name,
                        target.uid,
                        target.namespace,
                    )
                )

            navigator = CuratedNavigator(
                client,
                context.discovery or Discovery((resource,)),
                self.policy,
                origin_current,
                selected_namespace=lambda: header_namespace(self.context().chrome),
            )
            screen = InspectionScreen(
                InspectionService(client, resource, target, self.policy, current),
                page,
                chrome=context.chrome,
                navigator=navigator,
                revision=revision,
                observed_resource_version=record.resource_version,
                current_curated=origin_current,
                navigate_curated=self.navigate_curated,
                stopped=lambda: self._general_inspection_screens.discard(screen),
            )
            self._general_inspection_screens.add(screen)
            self.host.push_screen(screen)

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
            self.notice(str(error))
            return
        try:
            lease = self.log_read(selection) if self.log_read is not None else None
        except AppError as error:
            self.status(str(error))
            return
        stream = LogStream(client, target, self.policy, lease.read_current if lease else current)
        screen: ContainerScreen | LogScreen | None = None

        def stopped() -> None:
            if screen is not None:
                self._log_screens.discard(screen)

        try:
            screen = (
                ContainerScreen(
                    stream,
                    record.manifest,
                    metrics=context.metrics.report(record.uid or "")
                    if context.metrics is not None
                    else None,
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
                    inspect_container=lambda identity: self.open_container_inspection(
                        selection, identity
                    ),
                    metric_history=(
                        partial(self.metric_history, selection)
                        if self.metric_history is not None
                        else None
                    ),
                    release_read=lease.release if lease else None,
                    stopped=stopped,
                )
                if containers_first
                else LogScreen(
                    stream,
                    containers,
                    chrome=context.chrome,
                    trail=context.trail,
                    release_read=lease.release if lease else None,
                    stopped=stopped,
                )
            )
            self._log_screens.add(screen)
            self.host.push_screen(screen)
        except BaseException:
            if lease is not None:
                lease.release()
            if screen is not None:
                self._log_screens.discard(screen)
            raise

    def open_container_inspection(
        self, selection: CapturedResource[KubernetesSession], identity: ContainerIdentity
    ) -> None:
        from kuberich.services.container_inspection import ContainerInspectionService
        from kuberich.ui.container_inspection import ContainerInspectionScreen

        context = self.context()
        client, resource, _, target, current = selection
        if context.discovery is None:
            self.status("Container inspection needs current resource discovery; reconnect first.")
            return
        service = ContainerInspectionService(
            client,
            resource,
            replace(target, container=identity.name),
            identity,
            context.discovery,
            self.policy,
            current,
            now=lambda: datetime.now(UTC),
        )
        try:
            service.require_current()
        except AppError as error:
            self.status(str(error))
            return
        screen = ContainerInspectionScreen(
            service,
            chrome=context.chrome,
            trail=(*context.trail, "containers"),
            stopped=lambda: self._inspection_screens.discard(screen),
        )
        self._inspection_screens.add(screen)
        self.host.push_screen(screen)

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
                ForwardScreen(
                    self.forwards,
                    context.chrome,
                    context.trail,
                    selected=selected,
                    benchmark=self.benchmark_forward,
                )
            )

    def _forward_started(self, identity: UUID | None) -> None:
        if identity is not None:
            self.port_forwards(identity)

    async def close_for_client(self, client: KubernetesSession) -> None:
        if self.stop_benchmarks is not None:
            await self.stop_benchmarks(client)
        await self.ephemeral_debug.close_for_client(client)
        await self.node_maintenance.close_for_client(client)
        await self.node_shells.close_for_client(client)
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
                for screen in {*self.host.screen_stack, *self._log_screens}
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
                for screen in tuple(self._inspection_screens)
                if screen.service.client is client
            ),
            *(
                screen.stop_owned()
                for screen in tuple(self._general_inspection_screens)
                if screen.service.client is client
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
