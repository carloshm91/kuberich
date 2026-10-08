"""Read-only inspection bound to a captured client, session and object UID."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.inspection import InspectionDocuments, inspection_documents
from kuberich.domain.resources import ApiResource, ResourceRecord, api_segment, resource_record
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.resources import ResourceReader

EVENTS = ApiResource("", "v1", "events", "Event", True, frozenset({"list"}))


@dataclass(frozen=True)
class InspectionResult:
    documents: InspectionDocuments
    events_error: str | None = None


def read_error(error: AppError | ConnectionProblem) -> str:
    if isinstance(error, HttpProblem) and error.status == 403:
        return "Permission denied (403): this view requires API read access."
    if isinstance(error, HttpProblem) and error.status == 404:
        return "Resource or API unavailable (404); select the resource again."
    return str(error)


class InspectionService:
    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        self.client = client
        self.resource = resource
        self.target = target
        self.policy = policy
        self.current = current

    def require_current(self) -> None:
        if not self.current():
            raise AppError("The selected target is stale; select the resource again.")

    async def load(self) -> InspectionResult:
        self.policy.require(Action.READ)
        self.require_current()
        if self.client.context.name != self.target.session.context:
            raise AppError("Inspection client does not match the captured context.")
        if self.resource.namespaced and self.target.namespace is None:
            raise AppError("Namespaced inspection requires a captured namespace.")
        if self.target.group != self.resource.group or self.target.resource != self.resource.name:
            raise AppError("Inspection target does not match the captured resource API.")
        if "get" not in self.resource.verbs:
            raise AppError("Resource API does not support individual reads.")
        payload = await self.client.get_json(
            self.resource.path(self.target.namespace) + "/" + api_segment(self.target.name)
        )
        self.require_current()
        record = resource_record(self.resource, payload, self.target.namespace)
        self.target.require_current(self.target.session, uid=record.uid or "")
        if record.name != self.target.name:
            raise AppError("API response does not match the selected resource name.")
        events: tuple[ResourceRecord, ...] = ()
        events_error = None
        try:
            snapshot = await ResourceReader(self.client).list(EVENTS, self.target.namespace)
            events = snapshot.items
        except (AppError, ConnectionProblem) as error:
            events_error = read_error(error)
        self.require_current()
        # Cancelling the await cannot kill a serializer thread; own and drain it.
        worker = asyncio.create_task(
            asyncio.to_thread(inspection_documents, record.manifest, events, self.target)
        )
        try:
            documents = await asyncio.shield(worker)
        except asyncio.CancelledError:
            await asyncio.gather(worker, return_exceptions=True)
            raise
        self.require_current()
        return InspectionResult(documents, events_error)
