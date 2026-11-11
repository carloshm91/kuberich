"""One owned, bounded explicit navigation request over an injected client."""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.authorization import AuthorizationIntent
from kuberich.domain.connections import ConnectionProblem, HttpProblem, namespace_name
from kuberich.domain.curated_navigation import (
    AllResources,
    AuthorizationDestination,
    CollectionDestination,
    CuratedLink,
    CuratedPredicate,
    DeclaredObjectReference,
    IngressClassName,
    LabelsMatch,
    PodRuntimeClass,
    PolicyBindingMatch,
    ReferenceDestination,
    RelationshipDestination,
)
from kuberich.domain.events import EventGroupMembers
from kuberich.domain.read_budget import ReadBudget
from kuberich.domain.relationships import RelationshipMode, RelationshipRef
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import (
    ApiResource,
    Discovery,
    ResourceRecord,
    api_segment,
    resource_name,
    split_api_version,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import MAX_GET_RESPONSE_BYTES, ResourceReader


@dataclass(frozen=True, slots=True)
class CuratedOrigin:
    session: SessionIdentity
    revision: int
    resource: ApiResource
    record_name: str
    record_uid: str
    namespace: str | None
    resource_version: str | None
    observed_resource_version: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session, SessionIdentity)
            or type(self.revision) is not int
            or self.revision < 0
        ):
            raise AppError("Curated navigation requires a captured session and revision.")
        resource_name(self.record_name)
        validate_argument(self.record_uid)
        if self.namespace is not None:
            namespace_name(self.namespace)
        if self.resource_version is not None:
            validate_argument(self.resource_version)
        if self.observed_resource_version is not None:
            validate_argument(self.observed_resource_version)


@dataclass(frozen=True, slots=True)
class ResolvedCollection:
    resource: ApiResource
    namespace: str | None
    predicate: CuratedPredicate
    query: ResourceQuery


@dataclass(frozen=True, slots=True)
class ResolvedObject:
    resource: ApiResource
    record: ResourceRecord


type ResolvedCuratedDestination = (
    ResolvedCollection | ResolvedObject | RelationshipDestination | AuthorizationDestination
)


def _descriptor(resource: ApiResource) -> None:
    if resource.group:
        api_segment(resource.group)
    for value in (resource.version, resource.name):
        api_segment(value)
    if (
        type(resource.namespaced) is not bool
        or not isinstance(resource.kind, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", resource.kind)
    ):
        raise AppError("Curated navigation requires a valid discovered descriptor.")


def _discovered(
    discovery: Discovery,
    group: str,
    version: str | None,
    *,
    kind: str | None = None,
    name: str | None = None,
) -> ApiResource:
    if group:
        api_segment(group)
    if version is not None:
        api_segment(version)
    candidates = tuple(
        item
        for item in discovery.resources
        if item.group == group
        and (kind is None or item.kind == kind)
        and (name is None or item.name == name)
        and (version is None or item.version == version)
    )
    if not candidates:
        if discovery.partial:
            raise AppError("Curated destination is unavailable in incomplete discovery.")
        raise AppError("Curated destination API group, kind or exact version is unavailable.")
    if len({item.name for item in candidates}) != 1:
        raise AppError("Curated destination kind is ambiguous in discovery.")
    resource = candidates[0]  # Discovery preserves the advertised preferred-version order.
    if version is None:
        discovery.require_preferred(resource)
    _descriptor(resource)
    return resource


def _reference(
    discovery: Discovery, destination: ReferenceDestination
) -> tuple[ApiResource, str, str | None, str | None]:
    ref = destination.ref
    if (
        not isinstance(ref, (RelationshipRef, DeclaredObjectReference))
        or type(destination.require_uid) is not bool
    ):
        raise AppError("Curated destination reference is invalid.")
    if not isinstance(ref.kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", ref.kind):
        raise AppError("Curated destination reference kind is invalid.")
    name = resource_name(ref.name)
    if ref.uid is not None:
        validate_argument(ref.uid)
    if destination.require_uid and ref.uid is None:
        raise AppError("Curated destination requires an explicit object UID.")
    version: str | None
    if isinstance(ref, RelationshipRef):
        group, version = split_api_version(ref.api_version)
    else:
        group, version = ref.group, ref.version
    resource = _discovered(discovery, group, version, kind=ref.kind)
    namespace = ref.namespace
    if namespace is not None:
        namespace_name(namespace)
    if isinstance(ref, RelationshipRef) and not resource.namespaced:
        namespace = None  # Existing reference namespace supplies declaring-object context.
    if resource.namespaced != (namespace is not None):
        raise AppError("Curated destination declared namespace does not match discovered scope.")
    if "get" not in resource.verbs:
        raise AppError("Curated destination does not advertise object reads.")
    return resource, name, namespace, ref.uid


def _collection(
    discovery: Discovery,
    origin: CuratedOrigin,
    destination: CollectionDestination,
    selected_namespace: str | None,
) -> ResolvedCollection:
    if not isinstance(
        destination.predicate,
        (
            AllResources,
            LabelsMatch,
            PodRuntimeClass,
            IngressClassName,
            PolicyBindingMatch,
            EventGroupMembers,
        ),
    ):
        raise AppError("Curated collection requires a supported literal predicate.")
    api_segment(destination.resource)
    resource = _discovered(
        discovery, destination.group, destination.version, name=destination.resource
    )
    if "list" not in resource.verbs:
        raise AppError("Curated destination does not advertise collection reads.")
    if destination.scope == "object-namespace":
        namespace = origin.namespace
        if (
            namespace is None
            or destination.namespace not in (None, namespace)
            or not resource.namespaced
        ):
            raise AppError("Curated collection requires the declaring object's namespace.")
    elif destination.scope == "selected-namespace":
        if destination.namespace is not None or not resource.namespaced:
            raise AppError("Curated collection selected scope is invalid.")
        namespace = selected_namespace
    elif destination.scope == "cluster":
        if destination.namespace is not None or resource.namespaced:
            raise AppError("Curated collection cluster scope is invalid.")
        namespace = None
    else:
        raise AppError("Curated collection scope is unsupported.")
    return ResolvedCollection(resource, namespace, destination.predicate, ResourceQuery())


class CuratedNavigator:
    """Cancel and drain previous intent; never close the injected Kubernetes session."""

    def __init__(
        self,
        client: KubernetesSession,
        discovery: Discovery,
        policy: AccessPolicy,
        current: Callable[[CuratedOrigin], bool],
        *,
        selected_namespace: Callable[[], str | None],
    ) -> None:
        self._client, self._discovery, self._policy = client, discovery, policy
        self._context = client.context
        self._current, self._selected_namespace = current, selected_namespace
        self._active: asyncio.Task[ResolvedCuratedDestination] | None = None
        self._stopping: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._intent = 0
        self._closed = False

    @property
    def operation_count(self) -> int:
        return int(self._active is not None and not self._active.done())

    def _guard(self, origin: CuratedOrigin, intent: int | None = None) -> None:
        self._policy.require(Action.READ)
        if (
            self._closed
            or not self._current(origin)
            or self._client.context is not self._context
            or self._context.name != origin.session.context
            or self._client.api is None
        ):
            raise AppError("Curated navigation source belongs to an obsolete session or revision.")
        if intent is not None and intent != self._intent:
            raise asyncio.CancelledError

    async def _drain(self) -> None:
        task = self._active
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            if self._active is task:
                self._active = None

    async def resolve(self, origin: CuratedOrigin, link: CuratedLink) -> ResolvedCuratedDestination:
        self._guard(origin)
        selected_namespace = self._selected_namespace()
        if selected_namespace is not None:
            namespace_name(selected_namespace)
        self._intent += 1
        intent = self._intent
        if self._active is not None:
            self._active.cancel()
        async with self._lock:
            await self._drain()
            caller = asyncio.current_task()
            if caller is not None and caller.cancelling():
                raise asyncio.CancelledError
            self._guard(origin, intent)
            task = asyncio.create_task(
                self._resolve(origin, link, selected_namespace, intent),
                name="kuberich-curated-navigation",
            )
            self._active = task
        try:
            return await task
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            if self._active is task and task.done():
                self._active = None

    async def _resolve(
        self,
        origin: CuratedOrigin,
        link: CuratedLink,
        selected_namespace: str | None,
        intent: int,
    ) -> ResolvedCuratedDestination:
        self._guard(origin, intent)
        destination = link.destination
        if destination is None or link.unavailable_reason is not None:
            raise AppError("Curated link is unavailable; refresh the source details.")
        if isinstance(destination, (RelationshipDestination, AuthorizationDestination)):
            if isinstance(destination, RelationshipDestination) and not isinstance(
                destination.mode, RelationshipMode
            ):
                raise AppError("Curated relationship intent is invalid.")
            if isinstance(destination, AuthorizationDestination) and not isinstance(
                destination.intent, AuthorizationIntent
            ):
                raise AppError("Curated authorization intent is invalid.")
            self._guard(origin, intent)
            return destination
        if origin.resource not in self._discovery.resources:
            raise AppError("Curated source descriptor is no longer discovered.")
        _descriptor(origin.resource)
        if (
            origin.resource.namespaced != (origin.namespace is not None)
            or origin.resource_version is None
        ):
            raise AppError("Curated source scope or resource version is unavailable.")
        if isinstance(destination, ReferenceDestination):
            resource, name, namespace, uid = _reference(self._discovery, destination)
            resolved: ResolvedCuratedDestination | None = None
        elif isinstance(destination, CollectionDestination):
            resolved = _collection(self._discovery, origin, destination, selected_namespace)
        else:
            raise AppError("Curated destination type is unsupported.")
        reader = ResourceReader(self._client, budget=ReadBudget(2))
        try:
            source = await reader.get(
                origin.resource,
                origin.record_name,
                origin.namespace,
                max_bytes=MAX_GET_RESPONSE_BYTES,
            )
            self._guard(origin, intent)
            if (source.name, source.uid, source.namespace, source.resource_version) != (
                origin.record_name,
                origin.record_uid,
                origin.namespace,
                origin.resource_version,
            ):
                raise AppError("Curated source changed; refresh its details before navigating.")
            if isinstance(destination, ReferenceDestination):
                target = await reader.get(
                    resource, name, namespace, max_bytes=MAX_GET_RESPONSE_BYTES
                )
                self._guard(origin, intent)
                if (
                    target.uid is None
                    or target.resource_version is None
                    or target.namespace != namespace
                    or (uid is not None and target.uid != uid)
                ):
                    raise AppError(
                        "Curated target changed or was replaced; refresh the source details."
                    )
                resolved = ResolvedObject(resource, target)
        except HttpProblem as problem:
            if problem.status == 403:
                raise AppError("Curated navigation read was forbidden by the API server.") from None
            if problem.status == 404:
                raise AppError("Curated navigation object was not found.") from None
            raise AppError("Curated navigation API read failed; server response omitted.") from None
        except ConnectionProblem:
            raise AppError(
                "Curated navigation received an invalid, oversized or unavailable object."
            ) from None
        self._guard(origin, intent)
        assert resolved is not None
        return resolved

    async def _stop(self) -> None:
        async with self._lock:
            await self._drain()

    async def stop(self) -> None:
        self._closed = True
        self._intent += 1
        if self._active is not None:
            self._active.cancel()
        if self._stopping is None:
            self._stopping = asyncio.create_task(
                self._stop(), name="kuberich-curated-navigation-stop"
            )
        try:
            await asyncio.shield(self._stopping)
        except asyncio.CancelledError:
            await finish_owned(asyncio.gather(self._stopping, return_exceptions=True))
            raise
