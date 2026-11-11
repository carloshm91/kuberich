"""Fresh Helm inspection and one-use disclosure/rollback authorization."""

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from kuberich.adapters.helm import (
    HelmAdapter,
    HelmAdapterPort,
    HelmExecutionCancelled,
    HelmExecutionProblem,
)
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.helm import (
    HelmApproval,
    HelmDisclosureIntent,
    HelmDocument,
    HelmDocumentKind,
    HelmInspection,
    HelmList,
    HelmOutcome,
    HelmProblem,
    HelmRelease,
    HelmReleaseKey,
    HelmRequest,
    HelmRollbackIntent,
    HelmRollbackOptions,
    HelmRollbackResult,
    HelmSettings,
    HelmStorageIdentity,
    HelmTarget,
)
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.helm_lifecycle import (
    HelmLifecycleIntent,
    HelmLifecycleKind,
    HelmLifecycleOptions,
    HelmOperationObservation,
    HelmValuesDisclosureIntent,
    HelmValuesLease,
)
from kuberich.domain.processes import ProcessCommand
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.helm_catalog import HelmCatalogService
from kuberich.services.ownership import finish_owned

MAX_OPERATION_SECONDS = 120.0
STALE_MESSAGE = "Helm release identity changed; refresh and select it again."
INTENT_MESSAGE = "Helm review expired; prepare and confirm the action again."
type HelmIntent = HelmDisclosureIntent | HelmRollbackIntent


class HelmService:
    """Own every viewer task until its process/parser is drained before client teardown."""

    def __init__(
        self,
        client: KubernetesSession,
        policy: AccessPolicy,
        settings: HelmSettings,
        environment: Mapping[str, str],
        directory: Path,
        current: Callable[[HelmRequest], bool],
        *,
        adapter: HelmAdapterPort | None = None,
        catalog_directory: Path | None = None,
    ) -> None:
        from kuberich.services.helm_lifecycle import HelmLifecycle

        self.client, self.policy, self.settings, self.current = client, policy, settings, current
        self._client = client
        self._adapter = adapter or HelmAdapter(client, policy, settings, environment, directory)
        self._generation = 0
        self._intent_generation = 0
        self._intent: HelmIntent | None = None
        self._approval: HelmApproval | None = None
        self._inspections: dict[HelmTarget, HelmInspection] = {}
        self._operations: set[asyncio.Task[Any]] = set()
        self._cleanup_failures: list[BaseException] = []
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._last_rollback: HelmRollbackResult | None = None
        self._admitted: asyncio.Task[Any] | None = None
        self.catalog = HelmCatalogService(policy, catalog_directory)
        self._lifecycle = HelmLifecycle(self, dict(environment), directory.absolute())

    def require_helm_idle(self) -> None:
        if self._admitted is not None and not self._admitted.done():
            raise AppError(
                "Another Helm operation is already admitted; observe it before preparing another."
            )

    def start_helm_owned[T](self, operation: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        task = asyncio.create_task(operation)
        self._operations.add(task)
        task.add_done_callback(self._operations.discard)
        return task

    def admit_helm_write[T](self, operation: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        self.require_helm_idle()
        task = self.start_helm_owned(operation)
        self._admitted = task

        def retired(completed: asyncio.Task[T]) -> None:
            if self._admitted is completed:
                self._admitted = None

        task.add_done_callback(retired)
        return task

    def start_helm_cleanup(self, operation: Coroutine[Any, Any, None]) -> None:
        task = self.start_helm_owned(operation)

        def retired(completed: asyncio.Task[None]) -> None:
            if not completed.cancelled() and (failure := completed.exception()) is not None:
                self._cleanup_failures.append(failure)

        task.add_done_callback(retired)

    @property
    def last_operation(self) -> HelmOperationObservation | None:
        return self._lifecycle.last

    async def prepare_lifecycle(
        self,
        request: HelmRequest,
        address: HelmReleaseKey,
        operation: HelmLifecycleKind,
        chart: ChartSnapshot | None = None,
        values: HelmValuesLease | None = None,
        options: HelmLifecycleOptions | None = None,
    ) -> HelmLifecycleIntent:
        return await self._lifecycle.prepare(
            request, address, operation, chart, values, options or HelmLifecycleOptions()
        )

    def confirm_lifecycle(self, intent: HelmLifecycleIntent) -> HelmApproval:
        return self._lifecycle.confirm(intent)

    def execute_lifecycle(self, approval: HelmApproval) -> asyncio.Task[HelmOperationObservation]:
        return self._lifecycle.execute(approval)

    async def create_values(
        self,
        request: HelmRequest,
        address: HelmReleaseKey,
        chart: ChartSnapshot,
        *,
        source: str = "defaults",
    ) -> HelmValuesLease:
        return await self._lifecycle.create_values(request, address, chart, source=source)

    async def prepare_values_editor(self, lease: HelmValuesLease) -> HelmValuesDisclosureIntent:
        return await self._lifecycle.prepare_editor(lease)

    def confirm_values_editor(self, intent: HelmValuesDisclosureIntent) -> HelmApproval:
        return self._lifecycle.confirm_editor(intent)

    def open_values_editor(self, approval: HelmApproval) -> asyncio.Task[ProcessCommand]:
        return self._lifecycle.open_editor(approval)

    def require_values_editor_current(self) -> None:
        self._lifecycle.require_editor_current()

    async def finish_values_editor(self) -> HelmValuesLease:
        return await self._lifecycle.finish_editor()

    async def close_values_editor(self) -> None:
        await self._own(self._lifecycle.close_editor())

    @property
    def operation_count(self) -> int:
        return len(self._operations)

    @property
    def last_rollback(self) -> HelmRollbackResult | None:
        """Safe write evidence survives cancellation; cancellation does not undo Helm."""
        return self._last_rollback

    def _check(
        self,
        request: HelmRequest,
        generation: int | None = None,
        intent_generation: int | None = None,
        *,
        mutate: bool = False,
    ) -> None:
        self.policy.require(Action.MUTATE if mutate else Action.READ)
        if (
            self._closed
            or self.client is not self._client
            or not self.current(request)
            or request.scope.session.context != self.client.context.name
            or (generation is not None and generation != self._generation)
        ):
            raise HelmProblem("stale", STALE_MESSAGE)
        if request.scope.driver is not self.settings.driver:
            raise HelmProblem(
                "unsupported-driver",
                "Helm request storage driver differs from the captured settings.",
            )
        if intent_generation is not None and intent_generation != self._intent_generation:
            raise HelmProblem("stale", INTENT_MESSAGE)

    def _guard(
        self,
        request: HelmRequest,
        *,
        intent_generation: int | None = None,
        mutate: bool = False,
    ) -> Callable[[], None]:
        generation = self._generation
        return lambda: self._check(request, generation, intent_generation, mutate=mutate)

    async def _own[T](self, operation: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(operation)
        self._operations.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            self._operations.discard(task)

    async def _bounded[T](self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        try:
            async with asyncio.timeout(MAX_OPERATION_SECONDS):
                return await operation()
        except TimeoutError:
            raise HelmProblem(
                "timeout", "Helm preparation timed out; refresh before retrying."
            ) from None

    def _target(self, target: HelmTarget, revision: int) -> HelmInspection:
        self._check(target.request)
        if type(revision) is not int or revision < 1:
            raise HelmProblem("invalid-output", "Select a positive Helm revision.")
        inspection = self._inspections.get(target)
        if inspection is None or not any(
            row.revision == revision for row in inspection.history.revisions
        ):
            raise HelmProblem(
                "stale", "Helm revision is not in the current inspection; refresh it."
            )
        return inspection

    async def list(self, request: HelmRequest) -> HelmList:
        self._check(request)
        guard = self._guard(request)

        async def run() -> HelmList:
            result = await self._adapter.list(request, guard)
            guard()
            return result

        return await self._own(self._bounded(run))

    async def inspect(self, request: HelmRequest, release: HelmRelease) -> HelmInspection:
        self._check(request)
        if request.scope.namespace not in {None, release.key.namespace}:
            raise HelmProblem("stale", STALE_MESSAGE)
        guard = self._guard(request)

        async def run() -> HelmInspection:
            identities = await self._adapter.storage_history(request, release.key, guard)
            guard()
            if not identities or identities[-1].revision != release.revision:
                raise HelmProblem("stale", STALE_MESSAGE)
            head = identities[-1]
            status = await self._adapter.status(request, release.key, head.revision, guard)
            guard()
            history = await self._adapter.history(request, release.key, guard)
            guard()
            final = await self._adapter.storage_identity(request, release.key, head.revision, guard)
            guard()
            if final != head or status.status != head.status or release.status != head.status:
                raise HelmProblem("stale", STALE_MESSAGE)
            if not any(
                row.revision == head.revision and row.status == head.status
                for row in history.revisions
            ):
                raise HelmProblem("stale", STALE_MESSAGE)
            target = HelmTarget(request, head)
            result = HelmInspection(target, release, status, history)
            # An inspector holds metadata only. Bound detached inspector authority per connection.
            if target not in self._inspections and len(self._inspections) >= 32:
                raise HelmProblem(
                    "unavailable", "Too many Helm inspections; refresh the Helm view."
                )
            self._inspections[target] = result
            return result

        return await self._own(self._bounded(run))

    async def _identities(
        self, target: HelmTarget, revision: int, guard: Callable[[], None]
    ) -> HelmStorageIdentity:
        request, key = target.request, target.head.key
        identities = await self._adapter.storage_history(request, key, guard)
        guard()
        if not identities or identities[-1] != target.head:
            raise HelmProblem("stale", STALE_MESSAGE)
        selected = next((item for item in identities if item.revision == revision), None)
        if selected is None:
            raise HelmProblem("stale", STALE_MESSAGE)
        head = await self._adapter.storage_identity(request, key, target.head.revision, guard)
        guard()
        exact = await self._adapter.storage_identity(request, key, revision, guard)
        guard()
        if head != target.head or exact != selected:
            raise HelmProblem("stale", STALE_MESSAGE)
        return exact

    async def document(
        self, target: HelmTarget, revision: int, kind: HelmDocumentKind
    ) -> HelmDocument:
        self._target(target, revision)
        guard = self._guard(target.request)

        async def run() -> HelmDocument:
            selected = await self._identities(target, revision, guard)
            text = await self._adapter.document(
                target.request, target.head.key, revision, kind, False, guard
            )
            guard()
            final = await self._adapter.storage_identity(
                target.request, target.head.key, revision, guard
            )
            guard()
            if final != selected:
                raise HelmProblem("stale", STALE_MESSAGE)
            return HelmDocument(target, revision, kind, text, False)

        return await self._own(self._bounded(run))

    def _new_intent(self) -> int:
        self._intent_generation += 1
        self._retire_intent()
        return self._intent_generation

    def _retire_intent(self) -> None:
        self._intent, self._approval = None, None
        self._lifecycle.retire()

    def cancel_review(self) -> None:
        """Expire a nested review without retiring its parent inspection."""
        self._new_intent()

    async def prepare_disclosure(
        self, target: HelmTarget, revision: int, kind: HelmDocumentKind
    ) -> HelmDisclosureIntent:
        self._target(target, revision)
        generation = self._new_intent()
        guard = self._guard(target.request, intent_generation=generation)

        async def run() -> HelmDisclosureIntent:
            selected = await self._identities(target, revision, guard)
            guard()
            result = HelmDisclosureIntent(uuid4(), target, selected, kind)
            self._intent = result
            return result

        return await self._own(self._bounded(run))

    async def prepare_rollback(
        self, target: HelmTarget, revision: int, options: HelmRollbackOptions
    ) -> HelmRollbackIntent:
        self.policy.require(Action.MUTATE)
        self.require_helm_idle()
        self._target(target, revision)
        generation = self._new_intent()
        guard = self._guard(target.request, intent_generation=generation, mutate=True)

        async def run() -> HelmRollbackIntent:
            selected = await self._identities(target, revision, guard)
            history = await self._adapter.history(target.request, target.head.key, guard)
            guard()
            row = next((item for item in history.revisions if item.revision == revision), None)
            if row is None or row.status != selected.status:
                raise HelmProblem("stale", STALE_MESSAGE)
            status = await self._adapter.status(target.request, target.head.key, revision, guard)
            guard()
            if status.status != selected.status:
                raise HelmProblem("stale", STALE_MESSAGE)
            result = HelmRollbackIntent(uuid4(), target, selected, options, status.hooks)
            # Status may contain hook metadata, never bodies; verify after that read as well.
            if await self._identities(target, revision, guard) != selected:
                raise HelmProblem("stale", STALE_MESSAGE)
            guard()
            self._intent = result
            return result

        return await self._own(self._bounded(run))

    def confirm(self, intent: HelmIntent) -> HelmApproval:
        self._check(
            intent.target.request,
            intent_generation=self._intent_generation,
            mutate=isinstance(intent, HelmRollbackIntent),
        )
        if intent is not self._intent or self._approval is not None:
            raise HelmProblem("stale", INTENT_MESSAGE)
        self._approval = HelmApproval(intent.identity, uuid4())
        return self._approval

    def _consume(
        self, approval: HelmApproval, kind: type[HelmDisclosureIntent] | type[HelmRollbackIntent]
    ) -> HelmIntent:
        intent = self._intent
        expected = self._approval
        # A rejected cross-operation token cannot preserve another pending review.
        self._retire_intent()
        if approval is not expected or intent is None:
            raise HelmProblem("stale", INTENT_MESSAGE)
        # No await precedes consuming the exact token, including rejected attempts.
        if not isinstance(intent, kind) or approval.intent != intent.identity:
            raise HelmProblem("stale", INTENT_MESSAGE)
        self._check(intent.target.request, mutate=isinstance(intent, HelmRollbackIntent))
        return intent

    async def disclose(self, approval: HelmApproval) -> HelmDocument:
        intent = self._consume(approval, HelmDisclosureIntent)
        assert isinstance(intent, HelmDisclosureIntent)
        generation = self._intent_generation
        guard = self._guard(intent.target.request, intent_generation=generation)

        async def run() -> HelmDocument:
            target, selected = intent.target, intent.selected
            if await self._identities(target, selected.revision, guard) != selected:
                raise HelmProblem("stale", STALE_MESSAGE)
            guard()
            text = await self._adapter.document(
                target.request, target.head.key, selected.revision, intent.kind, True, guard
            )
            guard()
            if await self._identities(target, selected.revision, guard) != selected:
                raise HelmProblem("stale", STALE_MESSAGE)
            guard()
            return HelmDocument(target, selected.revision, intent.kind, text, True)

        return await self._own(self._bounded(run))

    def rollback(self, approval: HelmApproval) -> Coroutine[Any, Any, HelmRollbackResult]:
        intent = self._consume(approval, HelmRollbackIntent)
        self.require_helm_idle()
        assert isinstance(intent, HelmRollbackIntent)
        self._last_rollback = None
        generation = self._intent_generation
        guard = self._guard(intent.target.request, intent_generation=generation, mutate=True)

        async def run() -> HelmRollbackResult:
            started = False
            completed_failure = False
            failure: HelmProblem | None = None
            try:
                async with asyncio.timeout(MAX_OPERATION_SECONDS):
                    if (
                        await self._identities(intent.target, intent.selected.revision, guard)
                        != intent.selected
                    ):
                        raise HelmProblem("stale", STALE_MESSAGE)
                    guard()
                # Helm's own per-operation timeout is distinct from the process deadline.
                started = True
                self._last_rollback = HelmRollbackResult(
                    HelmOutcome.UNKNOWN,
                    "Helm rollback may have started; cancellation does not undo it. Refresh history before another review.",
                    None,
                    True,
                )
                await self._adapter.rollback(intent, guard)
                guard()
            except HelmExecutionCancelled as problem:
                if not problem.may_have_started:
                    self._last_rollback = HelmRollbackResult(
                        HelmOutcome.BLOCKED,
                        "Helm rollback was cancelled before the write started.",
                        None,
                        False,
                    )
                raise
            except HelmExecutionProblem as problem:
                started = problem.may_have_started
                if not started:
                    return HelmRollbackResult(HelmOutcome.BLOCKED, str(problem), None, False)
                completed_failure = problem.completed and problem.kind not in {
                    "timeout",
                    "output-limit",
                }
                failure = problem
            except HelmProblem as problem:
                return HelmRollbackResult(
                    HelmOutcome.UNKNOWN
                    if started
                    else HelmOutcome.STALE
                    if problem.kind == "stale"
                    else HelmOutcome.BLOCKED,
                    "Helm rollback outcome is uncertain; refresh history before another review."
                    if started
                    else str(problem),
                    None,
                    started,
                )
            except TimeoutError:
                return HelmRollbackResult(
                    HelmOutcome.BLOCKED,
                    "Helm rollback preparation timed out; refresh before retrying.",
                    None,
                    False,
                )
            except AppError:
                return HelmRollbackResult(
                    HelmOutcome.UNKNOWN if started else HelmOutcome.DENIED,
                    "Helm rollback outcome is uncertain; refresh history before another review."
                    if started
                    else "Helm rollback was refused by the current access policy.",
                    None,
                    started,
                )
            # A completed nonzero command can create a failed release revision. Observe once,
            # without replaying the write or claiming that all resources were restored.
            expected_status = "failed" if failure is not None else "deployed"
            if failure is not None and not completed_failure:
                self._inspections.pop(intent.target, None)
                return HelmRollbackResult(
                    HelmOutcome.UNKNOWN,
                    "Helm rollback outcome is uncertain; refresh history before another review.",
                    None,
                    True,
                )
            try:
                async with asyncio.timeout(MAX_OPERATION_SECONDS):
                    identities = await self._adapter.storage_history(
                        intent.target.request, intent.target.head.key, guard
                    )
                    guard()
                    listing = await self._adapter.list(intent.target.request, guard)
                    guard()
                    observed = next(
                        (item for item in listing.releases if item.key == intent.target.head.key),
                        None,
                    )
                    if (
                        not identities
                        or observed is None
                        or identities[-1].revision != intent.target.head.revision + 1
                        or observed.revision != identities[-1].revision
                        or observed.status != expected_status
                        or identities[-1].status != expected_status
                    ):
                        raise HelmProblem("stale", STALE_MESSAGE)
                    final = await self._adapter.storage_identity(
                        intent.target.request, intent.target.head.key, observed.revision, guard
                    )
                    guard()
                    if final != identities[-1]:
                        raise HelmProblem("stale", STALE_MESSAGE)
            except (HelmProblem, AppError, TimeoutError):
                self._inspections.pop(intent.target, None)
                return HelmRollbackResult(
                    HelmOutcome.UNKNOWN,
                    "Helm rollback completed, but its resulting revision was not verified; refresh history.",
                    None,
                    True,
                )
            self._new_intent()
            self._inspections.pop(intent.target, None)
            return HelmRollbackResult(
                HelmOutcome.FAILED if failure is not None else HelmOutcome.SUCCEEDED,
                "Helm rollback failed and a new failed revision was observed; resources may have changed. Refresh history before another review."
                if failure is not None
                else "Helm rollback completed and a new deployed revision was observed. Refresh the release inspection.",
                observed,
                True,
            )

        admitted = self.admit_helm_write(run())

        async def receive() -> HelmRollbackResult:
            try:
                result = await asyncio.shield(admitted)
            except asyncio.CancelledError:
                admitted.cancel()
                await finish_owned(asyncio.gather(admitted, return_exceptions=True))
                raise
            self._last_rollback = result
            return result

        return receive()

    def invalidate(self) -> None:
        self._generation += 1
        self._new_intent()
        self._inspections.clear()
        for task in tuple(self._operations):
            if not task.cancelling():
                task.cancel()

    async def _shutdown(self) -> None:
        # Completed operation callbacks may enqueue their final input cleanup.
        while self._operations:
            await asyncio.gather(*tuple(self._operations), return_exceptions=True)
            await asyncio.sleep(0)
        failures: list[BaseException] = []
        for close in (self._lifecycle.close, self.catalog.close, self._adapter.close):
            try:
                await close()
            except BaseException as error:
                failures.append(error)
        failures.extend(self._cleanup_failures)
        self._cleanup_failures.clear()
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup(
                "Helm owner shutdown could not be completely verified.", failures
            )

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self.invalidate()
            self._closing = asyncio.create_task(self._shutdown())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await finish_owned(self._closing)
            raise
