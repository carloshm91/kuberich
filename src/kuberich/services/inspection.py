"""Read-only inspection bound to a captured client, session and object UID."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.curated import (
    MAX_CURATED_CELL_CHARACTERS,
    MAX_CURATED_DETAIL_BYTES,
    CuratedDetails,
    DetailSection,
    curated_details,
    known_family,
    supported_family,
)
from kuberich.domain.curated_navigation import CuratedLink, ReferenceDestination
from kuberich.domain.events import event_descriptor_supported, event_fact
from kuberich.domain.inspection import InspectionDocuments, inspection_documents
from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader

EVENTS = ApiResource("", "v1", "events", "Event", True, frozenset({"list"}))


@dataclass(frozen=True)
class InspectionResult:
    documents: InspectionDocuments
    events_error: str | None = None
    resource_version: str | None = None
    observed_at: datetime | None = None
    curated: CuratedDetails | None = None


def _documents(
    resource: ApiResource,
    record: ResourceRecord,
    events: tuple[ResourceRecord, ...],
    target: ResourceTarget,
) -> tuple[InspectionDocuments, CuratedDetails | None]:
    curated = curated_details(resource, record) if supported_family(resource) is not None else None
    if event_descriptor_supported(resource):
        fact = event_fact(resource, record)
        rows = (
            ("Type", fact.event_type or "—"),
            ("Reason", fact.reason or "—"),
            ("Reporter", fact.reporter or "—"),
            ("Occurrences", str(fact.count) if fact.count is not None else "—"),
            ("Count source", fact.count_origin),
            ("First seen", fact.first_at.isoformat() if fact.first_at else "—"),
            ("Last seen", fact.last_at.isoformat() if fact.last_at else "—"),
            ("Last seen source", fact.last_origin),
        )
        display_rows = tuple(
            tuple(sanitize_text(value)[:MAX_CURATED_CELL_CHARACTERS] for value in row)
            for row in rows
        )
        notices = list(fact.notices)
        if display_rows != rows:
            notices.append(
                "Event display cells were clipped; clipped text is not a complete identity."
            )
        destination = (
            ReferenceDestination(fact.regarding, True)
            if fact.regarding is not None and fact.regarding.uid is not None
            else None
        )
        curated = CuratedDetails(
            (DetailSection("Reported Event observation", ("Field", "Value"), display_rows),),
            (
                CuratedLink(
                    "regarding",
                    "Regarding object",
                    "Reported Event regarding UID",
                    destination,
                    None
                    if destination is not None
                    else "Regarding object UID is unavailable; no name-only identity inference.",
                ),
            ),
            tuple(notices),
        )
        # Full action identities are charged, never display-clipped into another lookup.
        if (
            len(json.dumps(asdict(curated), ensure_ascii=False, separators=(",", ":")).encode())
            + 512
            > MAX_CURATED_DETAIL_BYTES
        ):
            link = replace(
                curated.links[0],
                destination=None,
                unavailable_reason="Complete object identity exceeds the inspection presentation budget.",
            )
            curated = replace(
                curated,
                links=(link,),
                notices=(
                    *curated.notices,
                    "Regarding link omitted; complete action payload exceeds the UTF-8 budget.",
                ),
            )
    fallback = (
        known_family(resource.group, resource.name) is not None
        or (resource.group in {"", "events.k8s.io"} and resource.name == "events")
    ) and curated is None
    return inspection_documents(record.manifest, events, target, curated, fallback), curated


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
        self._context = client.context
        self.resource = resource
        self.target = target
        self.policy = policy
        self.current = current

    def require_current(self) -> None:
        if not self.current():
            raise AppError("The selected target is stale; select the resource again.")
        if (
            self.client.context is not self._context
            or self._context.name != self.target.session.context
            or self.client.api is None
        ):
            raise AppError(
                "Inspection client is unavailable or no longer matches the captured context."
            )

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
        try:
            record = await ResourceReader(self.client).get(
                self.resource, self.target.name, self.target.namespace, max_bytes=8 * 1024 * 1024
            )
        except ConnectionProblem as problem:
            if not isinstance(problem, HttpProblem) and problem.state is ConnectionState.API_ERROR:
                raise AppError(
                    "API response does not match the selected resource identity or bounds."
                ) from None
            raise
        self.require_current()
        self.target.require_current(self.target.session, uid=record.uid or "")
        if record.name != self.target.name:
            raise AppError("API response does not match the selected resource name.")
        observed_at = datetime.now(UTC)
        events: tuple[ResourceRecord, ...] = ()
        events_error = None
        try:
            snapshot = await ResourceReader(self.client).list(EVENTS, self.target.namespace)
            events = snapshot.items
            if not snapshot.collection.complete:
                events_error = "Events are INCOMPLETE; only retained events are shown."
        except (AppError, ConnectionProblem) as error:
            events_error = read_error(error)
        self.require_current()
        # Cancelling the await cannot kill a serializer thread; own and drain it.
        worker = asyncio.create_task(
            asyncio.to_thread(_documents, self.resource, record, events, self.target)
        )
        try:
            documents, curated = await asyncio.shield(worker)
        except asyncio.CancelledError:
            await finish_owned(asyncio.gather(worker, return_exceptions=True))
            raise
        self.require_current()
        return InspectionResult(
            documents, events_error, record.resource_version, observed_at, curated
        )
