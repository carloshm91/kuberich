"""One-use resource operations, revalidation and conservative deletion observation."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.mutations import conditional_patch
from kuberich.adapters.operations import resource_write
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.mutations import MutationIntent, MutationResult, MutationState
from kuberich.domain.operations import (
    MAX_BATCH,
    DeleteOptions,
    ResourceAction,
    ResourceIntent,
    delete_intent,
    operation_path,
    snapshot_version,
    suspension_intent,
    trigger_intent,
)
from kuberich.domain.resources import (
    ApiResource,
    ResourceRecord,
    resource_object,
    resource_record,
    string_list,
)
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation


class ResourceOperationService:
    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        action: ResourceAction,
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.policy, self.current, self.action = policy, current, action
        self.intent: ResourceIntent | MutationIntent | None = None
        self._confirmation: Confirmation | None = None
        self._approved: ResourceIntent | MutationIntent | None = None
        self._request_identity = uuid4()
        self._prepared_action: ResourceAction | None = None

    def require_current(self) -> None:
        self.policy.require(Action.MUTATE)
        operation_path(self.resource, self.target, self.action)
        if not self.current() or self.client.context.name != self.target.session.context:
            raise AppError("Operation target/connection changed. Select and review again.")

    async def _read(self) -> ResourceRecord:
        self.require_current()
        data = await self.client.get_json(operation_path(self.resource, self.target, self.action))
        self.require_current()
        record = resource_record(self.resource, data, self.target.namespace)
        snapshot_version(self.target, record)
        return record

    async def prepare(
        self, options: DeleteOptions | None = None
    ) -> ResourceIntent | MutationIntent:
        self.intent = self._approved = self._confirmation = None
        self._prepared_action = None
        action = self.action
        record = await self._read()
        if self.action is not action:
            raise AppError("Operation changed during preparation; review again.")
        if self.action is ResourceAction.DELETE:
            self.intent = delete_intent(
                self.resource, self.target, record, options or DeleteOptions()
            )
        elif self.action is ResourceAction.TRIGGER:
            self.intent = trigger_intent(self.resource, self.target, record, self._request_identity)
        else:
            self.intent = suspension_intent(self.resource, self.target, record, self.action)
        self._prepared_action = action
        return self.intent

    def confirm(self, intent: ResourceIntent | MutationIntent) -> Confirmation:
        self.require_current()
        if (
            not isinstance(intent, (ResourceIntent, MutationIntent))
            or self._prepared_action is not self.action
            or intent is not self.intent
            or intent.target != self.target
            or intent.resource != self.resource
        ):
            raise AppError("Confirmation must match this exact prepared operation.")
        self._confirmation = Confirmation(intent.identity, uuid4())
        self._approved = intent
        return self._confirmation

    async def execute(self, confirmation: Confirmation) -> MutationResult:
        intent = self.intent
        if (
            not isinstance(confirmation, Confirmation)
            or confirmation is not self._confirmation
            or intent is None
            or intent is not self._approved
            or intent.target != self.target
            or intent.resource != self.resource
            or self._prepared_action is not self.action
        ):
            return MutationResult(
                MutationState.BLOCKED, "An unused exact confirmation is required."
            )
        self._confirmation = self._approved = None
        try:
            record = await self._read()
            if record.resource_version != intent.resource_version:
                return MutationResult(
                    MutationState.CONFLICT,
                    "Object version changed. Read and review again; no write started.",
                )
            self.require_current()
        except asyncio.CancelledError:
            return MutationResult(
                MutationState.CANCELLED, "Cancelled before write during revalidation."
            )
        except HttpProblem as error:
            state = {
                401: MutationState.AUTH_ERROR,
                403: MutationState.DENIED,
                404: MutationState.NOT_FOUND,
            }.get(error.status, MutationState.REJECTED)
            return MutationResult(
                state, f"Revalidation refused (HTTP {error.status}); no write started."
            )
        except ConnectionProblem as error:
            return MutationResult(
                MutationState.TIMEOUT
                if error.state is ConnectionState.TIMEOUT
                else MutationState.UNREACHABLE,
                "Revalidation connection failed; no write started.",
            )
        except AppError:
            return MutationResult(
                MutationState.BLOCKED if self.policy.read_only else MutationState.STALE,
                "Captured identity/policy changed; no write started.",
            )
        if isinstance(intent, MutationIntent):
            return await conditional_patch(self.client, intent, self.require_current)
        result = await resource_write(self.client, intent, self.require_current)
        if result.state is MutationState.ACCEPTED:
            return await self._observe_deletion()
        return result

    async def _observe_deletion(self) -> MutationResult:
        try:
            self.require_current()
            data = await self.client.get_json(
                operation_path(self.resource, self.target, self.action)
            )
            self.require_current()
            record = resource_record(self.resource, data, self.target.namespace)
            if record.name != self.target.name:
                raise AppError("Observation returned an unexpected resource name.")
            if record.uid != self.target.uid:
                return MutationResult(
                    MutationState.SUCCEEDED,
                    "Captured UID is gone; a replacement exists and was left untouched. Dependent cleanup is not verified.",
                )
            metadata = resource_object(record.manifest["metadata"])
            finalizers = string_list(metadata.get("finalizers"))
            return MutationResult(
                MutationState.ACCEPTED,
                "Deletion accepted; captured UID still exists. Finalizers: "
                + (", ".join(finalizers) or "none observed")
                + ". Grace/dependent cleanup may remain; finalizers were not removed.",
            )
        except HttpProblem as error:
            if error.status == 404:
                return MutationResult(
                    MutationState.SUCCEEDED,
                    "Captured resource is absent after accepted deletion. Dependent cleanup is not verified.",
                )
        except (asyncio.CancelledError, ConnectionProblem, AppError):
            pass
        return MutationResult(
            MutationState.ACCEPTED,
            "Deletion was accepted; completion could not be observed. Inspect current state/finalizers; no retry was sent.",
        )


@dataclass(frozen=True)
class BatchIntent:
    items: tuple[ResourceIntent, ...]
    identity: UUID = field(default_factory=uuid4)

    @property
    def effects(self) -> tuple[str, ...]:
        return (
            f"Delete batch: {len(self.items)} explicitly selected targets; independent outcomes.",
            *(
                f"{item.target.namespace or '(cluster)'}/{item.target.name}; UID {item.target.uid}; "
                + " ".join(item.effects)
                for item in self.items
            ),
        )


class BatchDeleteService:
    """Bounded sequential writes; cancellation retains every completed/unsent result."""

    def __init__(self, sources: tuple[ResourceOperationService, ...]) -> None:
        if not 1 <= len(sources) <= MAX_BATCH:
            raise AppError("Select between one and 100 targets for a delete batch.")
        self.sources = sources
        self.client, self.target = sources[0].client, sources[0].target
        if len({source.target for source in sources}) != len(sources) or any(
            source.client is not self.client
            or source.target.session != self.target.session
            or source.resource != sources[0].resource
            or source.action is not ResourceAction.DELETE
            for source in sources
        ):
            raise AppError(
                "Batch requires unique DELETE targets from one captured API/client session."
            )
        self.intent: BatchIntent | None = None
        self.results: tuple[tuple[ResourceTarget, MutationResult], ...] = ()
        self._confirmation: Confirmation | None = None
        self._approved: BatchIntent | None = None
        self._proofs: tuple[Confirmation, ...] = ()

    def require_current(self) -> None:
        for source in self.sources:
            source.policy.require(Action.MUTATE)
        if self.client.context.name != self.target.session.context:
            raise AppError("Batch captured connection changed.")

    async def prepare(self, options: DeleteOptions) -> BatchIntent:
        self.intent = self._approved = self._confirmation = None
        self._proofs = ()
        self.require_current()
        items = []
        for source in self.sources:
            intent = await source.prepare(options)
            assert isinstance(intent, ResourceIntent)
            items.append(intent)
        self.intent = BatchIntent(tuple(items))
        return self.intent

    def confirm(self, intent: BatchIntent) -> Confirmation:
        self.require_current()
        self._confirmation = self._approved = None
        self._proofs = ()
        if not isinstance(intent, BatchIntent) or intent is not self.intent:
            raise AppError("Confirm this exact prepared batch.")
        self._proofs = tuple(
            source.confirm(item) for source, item in zip(self.sources, intent.items, strict=True)
        )
        self._confirmation = Confirmation(intent.identity, uuid4())
        self._approved = intent
        return self._confirmation

    async def execute(self, confirmation: Confirmation) -> MutationResult:
        if (
            not isinstance(confirmation, Confirmation)
            or confirmation is not self._confirmation
            or self.intent is None
            or self.intent is not self._approved
        ):
            return MutationResult(
                MutationState.BLOCKED, "An unused confirmation for this exact batch is required."
            )
        proofs = self._proofs
        self._proofs = ()
        self._confirmation = self._approved = None
        results = []
        for source, proof in zip(self.sources, proofs, strict=True):
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                result = MutationResult(
                    MutationState.CANCELLED, "Unsent batch item: operation was cancelled."
                )
            else:
                result = await source.execute(proof)
            results.append((source.target, result))
            self.results = tuple(results)
        states = {result.state for _, result in results}
        state = (
            MutationState.SUCCEEDED
            if states == {MutationState.SUCCEEDED}
            else MutationState.ACCEPTED
            if states <= {MutationState.SUCCEEDED, MutationState.ACCEPTED}
            else MutationState.UNCERTAIN
            if MutationState.UNCERTAIN in states
            else MutationState.REJECTED
        )
        return MutationResult(
            state,
            f"Batch finished: {len(results)} independent results; no rollback or automatic retry.\n"
            + "\n".join(
                f"{target.namespace or '(cluster)'}/{target.name}: {result.state.value} — {result.message}"
                for target, result in results
            ),
            items=self.results,
        )
