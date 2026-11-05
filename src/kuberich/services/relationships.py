"""Owned, finite relationship collection over one captured Kubernetes session."""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial

from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.reference_fields import REFERENCE_SOURCE_FAMILIES, declared_references
from kuberich.domain.relationships import (
    MAX_RELATIONSHIP_BYTES,
    MAX_RELATIONSHIP_DEPTH,
    MAX_RELATIONSHIP_EDGES,
    MAX_RELATIONSHIP_ITEMS,
    MAX_RELATIONSHIP_NODES,
    DeclaredReference,
    EndpointReference,
    OwnerReference,
    RelationDirection,
    RelationKind,
    RelationshipEvidence,
    RelationshipMode,
    RelationshipPath,
    RelationshipRef,
    RelationshipRequest,
    RelationshipRow,
    RelationshipScope,
    RelationshipSelector,
    RelationshipSnapshot,
    RelationshipSource,
    RelationshipStatus,
    endpoint_references,
    endpoint_service_names,
    native_selector,
    node_reference,
    owner_references,
    reference_for,
    relationship_cycle,
    relationship_identity,
    relationship_object_key,
    resolve_reference,
    resource_labels,
    selector_matches,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import (
    ApiResource,
    Discovery,
    ResourceRecord,
    ResourceSnapshot,
)
from kuberich.errors import AppError
from kuberich.services.resources import ResourceReader, parse_owned

# Every supported declaring family is included, including declarations on PVs and SAs.
DECLARING_FAMILIES = tuple(sorted(REFERENCE_SOURCE_FAMILIES))
_CHILDREN = {
    ("apps", "deployments"): ("apps", "replicasets"),
    ("batch", "cronjobs"): ("batch", "jobs"),
    ("apps", "replicasets"): ("", "pods"),
    ("apps", "statefulsets"): ("", "pods"),
    ("apps", "daemonsets"): ("", "pods"),
    ("batch", "jobs"): ("", "pods"),
    ("", "replicationcontrollers"): ("", "pods"),
}
MAX_COLLECTION_SECONDS = 30.0
MAX_COMPARISONS = 100000


class _CollectionLimit(Exception):
    """Shared extracted-data or deterministic comparison work bound reached."""


@dataclass(frozen=True, slots=True)
class _Fact:
    ref: RelationshipRef
    resource_version: str | None
    owners: tuple[OwnerReference, ...]
    references: tuple[DeclaredReference, ...]
    selector: RelationshipSelector | None
    labels: tuple[tuple[str, str], ...]
    node: DeclaredReference | None
    endpoints: tuple[EndpointReference, ...]
    services: tuple[str, ...]
    observed_at: datetime
    retained_bytes: int = 0


@dataclass(frozen=True, slots=True)
class _Edge:
    ref: RelationshipRef
    relation: RelationKind
    direction: RelationDirection
    evidence: RelationshipEvidence
    details: tuple[str, ...]
    status: RelationshipStatus = RelationshipStatus.READY
    # List observations are already identity-checked; declared targets require GET.
    fact: _Fact | None = None


def _extract(resource: ApiResource, record: ResourceRecord, discovery: Discovery) -> _Fact:
    fact = _Fact(
        reference_for(resource, record),
        record.resource_version,
        owner_references(resource, record, discovery),
        declared_references(resource, record),
        native_selector(resource, record),
        resource_labels(record),
        node_reference(resource, record),
        endpoint_references(resource, record),
        endpoint_service_names(resource, record),
        datetime.now(UTC),
    )
    return replace(fact, retained_bytes=len(repr(fact).encode()))


def _selector_query(selector: RelationshipSelector) -> ResourceQuery:
    terms = []
    for item in selector.requirements:
        if item.operator == "Exists":
            terms.append(item.key)
        elif item.operator == "DoesNotExist":
            terms.append("!" + item.key)
        else:
            operator = "in" if item.operator == "In" else "notin"
            terms.append(f"{item.key} {operator} ({','.join(item.values)})")
    try:
        return ResourceQuery(label_selector=",".join(terms)) if terms else ResourceQuery()
    except AppError:
        # The native selector remains authoritative after this bounded broad scan.
        return ResourceQuery()


def _problem(
    problem: ConnectionProblem | AppError | ReadBudgetExceeded | _CollectionLimit,
) -> tuple[RelationshipStatus, str]:
    if isinstance(problem, ReadBudgetExceeded):
        return RelationshipStatus.TRUNCATED, "Shared logical read budget exhausted."
    if isinstance(problem, _CollectionLimit):
        return (
            RelationshipStatus.TRUNCATED,
            "Shared relationship work or extracted-data bound exhausted.",
        )
    if isinstance(problem, HttpProblem):
        status = {
            403: RelationshipStatus.FORBIDDEN,
            404: RelationshipStatus.MISSING,
        }.get(problem.status, RelationshipStatus.FAILED)
        return status, f"Read HTTP {problem.status}; server message omitted."
    return RelationshipStatus.FAILED, "Relationship read or supported declaration was invalid."


class RelationshipService:
    """A graph-root cache; the Workspace owns and drains each collect invocation."""

    def __init__(
        self,
        reader: ResourceReader,
        discovery: Discovery,
        scope: RelationshipScope,
        current: Callable[[RelationshipRequest], bool],
    ) -> None:
        if (scope.root.group, scope.root.resource) != (scope.resource.group, scope.resource.name):
            raise AppError("Relationship root does not match its discovered resource.")
        if scope.resource.namespaced != (scope.root.namespace is not None):
            raise AppError("Relationship root has an invalid namespace scope.")
        self.budget = ReadBudget()
        self.reader = ResourceReader(reader.session, tables=False, budget=self.budget)
        self._session = reader.session
        self.discovery, self.scope, self.current = discovery, scope, current
        self._facts: dict[tuple[str, str, str | None, str], _Fact] = {}
        self._lists: dict[tuple[str, str, str | None, ResourceQuery], tuple[_Fact, ...]] = {}
        self._sources: dict[str, RelationshipSource] = {}
        self._input_count = 0
        self._input_bytes = 0
        self._rows: list[RelationshipRow] = []
        self._request: RelationshipRequest | None = None
        self._publish: Callable[[RelationshipSnapshot], None] = lambda _: None
        self._running = False
        self._comparisons = 0

    def _check(self, request: RelationshipRequest) -> None:
        if (
            request.scope != self.scope
            or self.reader.session is not self._session
            or self._request != request
            or not self.current(request)
        ):
            raise asyncio.CancelledError

    def _emit(self, request: RelationshipRequest) -> RelationshipSnapshot:
        self._check(request)
        snapshot = RelationshipSnapshot(
            request,
            tuple(self._rows),
            tuple(self._sources.values()),
            self.budget.used,
            datetime.now(UTC),
        )
        self._publish(snapshot)
        self._check(request)
        return snapshot

    def _resource(self, group: str, name: str) -> ApiResource | None:
        try:
            return self.discovery.find(name, group=group)
        except AppError:
            return None

    def _missing_status(self, group: str) -> RelationshipStatus:
        return (
            RelationshipStatus.FORBIDDEN
            if any(
                issue.reason == "forbidden"
                and (
                    issue.source == ("/apis" if group else "/api")
                    or issue.source.partition("/")[0] == (group or "v1")
                )
                for issue in self.discovery.issues
            )
            else RelationshipStatus.UNAVAILABLE
        )

    def _store(self, facts: tuple[_Fact, ...], count: int, size: int) -> None:
        size = max(size, sum(fact.retained_bytes for fact in facts))
        if (
            self._input_count + count > MAX_RELATIONSHIP_ITEMS
            or self._input_bytes + size > MAX_RELATIONSHIP_BYTES
        ):
            raise _CollectionLimit
        self._input_count += count
        self._input_bytes += size
        for fact in facts:
            self._facts[relationship_object_key(fact.ref)] = fact

    async def _get(
        self, request: RelationshipRequest, ref: RelationshipRef, *, fresh: bool = False
    ) -> tuple[_Fact | None, RelationshipStatus, tuple[str, ...]]:
        self._check(request)
        try:
            ref = resolve_reference(self.discovery, ref)
            resource = ref.resource
            if resource is None:
                return (
                    None,
                    RelationshipStatus.UNAVAILABLE,
                    ("Kind was not discovered; no plural guessed.",),
                )
            if resource.namespaced != (ref.namespace is not None):
                return (
                    None,
                    RelationshipStatus.INVALID,
                    ("Reference namespace is invalid for this kind.",),
                )
            fact = None if fresh else self._facts.get(relationship_object_key(ref))
            if fact is None:
                if (
                    self._input_count >= MAX_RELATIONSHIP_ITEMS
                    or self._input_bytes >= MAX_RELATIONSHIP_BYTES
                ):
                    raise _CollectionLimit
                record = await self.reader.get(resource, ref.name, ref.namespace)
                self._check(request)
                received_at = datetime.now(UTC)
                fact = await parse_owned(partial(_extract, resource, record, self.discovery))
                self._check(request)
                fact = replace(fact, observed_at=received_at)
                self._store((fact,), 1, record.size_bytes)
                key = "get:" + "/".join(str(part) for part in relationship_object_key(ref))
                self._sources[key] = RelationshipSource(
                    key,
                    ref.namespace,
                    RelationshipStatus.READY,
                    None,
                    fact.resource_version,
                    "Observed exact discovered resource path.",
                    fact.observed_at,
                )
            if ref.uid is not None and fact.ref.uid != ref.uid:
                return (
                    fact,
                    RelationshipStatus.REPLACED,
                    ("Expected UID differs from the current object; replacement not followed.",),
                )
            return fact, RelationshipStatus.READY, ()
        except (ConnectionProblem, AppError, ReadBudgetExceeded, _CollectionLimit) as problem:
            self._check(request)
            status, detail = _problem(problem)
            key = "get:" + "/".join(str(part) for part in relationship_object_key(ref))
            previous = self._sources.get(key)
            self._sources[key] = RelationshipSource(
                key,
                ref.namespace,
                status,
                None,
                previous.resource_version if previous else None,
                detail,
                previous.observed_at if previous else None,
            )
            return None, status, (detail,)

    async def _list(
        self,
        request: RelationshipRequest,
        group: str,
        name: str,
        namespace: str | None,
        query: ResourceQuery | None = None,
    ) -> tuple[_Fact, ...]:
        self._check(request)
        query = query or ResourceQuery()
        resource = self._resource(group, name)
        key = f"list:{group}/{name}:{namespace}:{query.label_selector or ''}:{query.field_selector or ''}"
        cache_key = group, name, namespace, query
        if cache_key in self._lists:
            return self._lists[cache_key]
        if resource is None:
            self._sources[key] = RelationshipSource(
                f"{group}/{name}",
                namespace,
                self._missing_status(group),
                None,
                None,
                "Source kind was not discovered; scan is incomplete.",
            )
            self._lists[cache_key] = ()
            return ()
        namespace = namespace if resource.namespaced else None
        self._sources[key] = RelationshipSource(
            f"{group}/{name}",
            namespace,
            RelationshipStatus.LOADING,
            None,
            None,
            "Collecting supported source family.",
        )
        self._emit(request)
        facts: tuple[_Fact, ...] = ()
        latest: ResourceSnapshot | None = None
        try:

            async def receive(snapshot: ResourceSnapshot) -> None:
                nonlocal facts, latest
                self._check(request)
                changed = latest is None or (
                    snapshot.resource_version != latest.resource_version
                    or snapshot.items != latest.items
                )
                received_at = (
                    datetime.now(UTC) if changed else self._sources[key].observed_at
                ) or datetime.now(UTC)
                if changed:

                    def extract() -> tuple[_Fact, ...]:
                        return tuple(
                            replace(
                                _extract(resource, record, self.discovery), observed_at=received_at
                            )
                            for record in snapshot.items
                        )

                    facts = await parse_owned(extract)
                    self._check(request)
                latest = snapshot
                self._sources[key] = RelationshipSource(
                    f"{group}/{name}",
                    namespace,
                    RelationshipStatus.READY
                    if snapshot.collection.complete
                    else RelationshipStatus.TRUNCATED
                    if snapshot.collection.limited
                    else RelationshipStatus.LOADING,
                    snapshot.collection,
                    snapshot.resource_version,
                    "Complete supported source scan."
                    if snapshot.collection.complete
                    else "Shared logical read budget exhausted; retained source scan is incomplete."
                    if snapshot.collection.limited and self.budget.used >= 64
                    else "Partial supported source scan; absence is unproven.",
                    received_at,
                )
                self._emit(request)

            snapshot = await self.reader.list(
                resource,
                namespace,
                query=query,
                progress=receive,
                max_items=MAX_RELATIONSHIP_ITEMS - self._input_count,
                max_retained_bytes=MAX_RELATIONSHIP_BYTES - self._input_bytes,
            )
            self._check(request)
            await receive(snapshot)
        except (ConnectionProblem, AppError, ReadBudgetExceeded, _CollectionLimit) as problem:
            self._check(request)
            status, detail = _problem(problem)
            self._sources[key] = replace(self._sources[key], status=status, detail=detail)
        if latest is not None:
            try:
                self._store(facts, len(latest.items), latest.collection.retained_bytes)
            except _CollectionLimit:
                self._sources[key] = replace(
                    self._sources[key],
                    status=RelationshipStatus.TRUNCATED,
                    detail="Shared extracted-fact retention bound reached; source is incomplete.",
                )
                raise
        self._lists[cache_key] = facts
        return facts

    def _resolved(self, ref: RelationshipRef) -> RelationshipRef:
        try:
            return resolve_reference(self.discovery, ref)
        except AppError:
            return replace(ref, resource=None)

    async def _used_by(self, request: RelationshipRequest, fact: _Fact) -> list[_Edge]:
        edges = []
        namespace = (
            fact.ref.namespace
            if fact.ref.resource and fact.ref.resource.namespaced
            else self.scope.namespace
        )
        for group, name in DECLARING_FAMILIES:
            sources = await self._list(request, group, name, namespace)

            def match(sources: tuple[_Fact, ...] = sources) -> list[_Edge]:
                found = []
                for source in sources:
                    for declaration in source.references:
                        self._comparisons += 1
                        if self._comparisons > MAX_COMPARISONS:
                            raise _CollectionLimit
                        target = self._resolved(declaration.target)
                        if relationship_object_key(target) != relationship_object_key(fact.ref):
                            continue
                        status = RelationshipStatus.READY
                        if target.uid is not None and target.uid != fact.ref.uid:
                            status = RelationshipStatus.REPLACED
                        details = (
                            declaration.path,
                            "Static supported declaration; optional="
                            + str(declaration.optional).lower(),
                            "Declared target UID differs from the selected root; earlier object reference."
                            if status is RelationshipStatus.REPLACED
                            else "Supported declaration matches the selected object name and scope.",
                            "Default ServiceAccount declaration."
                            if declaration.defaulted
                            else "Explicit object reference.",
                        )
                        found.append(
                            _Edge(
                                source.ref,
                                RelationKind.REFERENCE,
                                RelationDirection.INCOMING,
                                RelationshipEvidence.DECLARED,
                                details,
                                status,
                                source,
                            )
                        )
                        if len(found) >= MAX_RELATIONSHIP_EDGES:
                            return found
                return found

            edges.extend(await parse_owned(match))
            self._check(request)
            if len(edges) >= MAX_RELATIONSHIP_EDGES:
                self._truncate(
                    (), "Supported declarations exceed the edge bound; source scan is incomplete."
                )
                return edges[:MAX_RELATIONSHIP_EDGES]
        return edges

    async def _edges(self, request: RelationshipRequest, fact: _Fact) -> list[_Edge]:
        if self.scope.mode is RelationshipMode.USED_BY:
            return await self._used_by(request, fact)
        edges = []
        for owner in fact.owners:
            edges.append(
                _Edge(
                    owner.target,
                    RelationKind.CONTROLLER_OWNER if owner.controller else RelationKind.OWNER,
                    RelationDirection.OUTGOING,
                    RelationshipEvidence.DECLARED,
                    (owner.path, owner.detail),
                    owner.status,
                )
            )
        for declaration in fact.references:
            edges.append(
                _Edge(
                    declaration.target,
                    RelationKind.REFERENCE,
                    RelationDirection.OUTGOING,
                    RelationshipEvidence.DECLARED,
                    (
                        declaration.path,
                        "Static declaration; optional=" + str(declaration.optional).lower(),
                        "Default ServiceAccount declaration."
                        if declaration.defaulted
                        else "Explicit object reference.",
                    ),
                )
            )
        if fact.node is not None:
            edges.append(
                _Edge(
                    fact.node.target,
                    RelationKind.NODE,
                    RelationDirection.OUTGOING,
                    RelationshipEvidence.DECLARED,
                    (fact.node.path, "Declared Pod placement."),
                )
            )
        resource = fact.ref.resource
        assert resource is not None
        family = resource.group, resource.name
        child_family = _CHILDREN.get(family)
        if child_family is not None:
            for child in await self._list(request, *child_family, fact.ref.namespace):
                for owner in child.owners:
                    if owner.status is RelationshipStatus.READY and relationship_identity(
                        owner.target
                    ) == relationship_identity(fact.ref):
                        edges.append(
                            _Edge(
                                child.ref,
                                RelationKind.CONTROLLER_OWNER
                                if owner.controller
                                else RelationKind.OWNER,
                                RelationDirection.INCOMING,
                                RelationshipEvidence.DECLARED,
                                (owner.path, "Owner UID matches this object."),
                                fact=child,
                            )
                        )
        if fact.selector is not None:
            for child in await self._list(
                request, "", "pods", fact.ref.namespace, _selector_query(fact.selector)
            ):
                if selector_matches(fact.selector, dict(child.labels)):
                    edges.append(
                        _Edge(
                            child.ref,
                            RelationKind.SELECTOR,
                            RelationDirection.INCOMING,
                            RelationshipEvidence.INFERRED,
                            ("Native label selector match; ownership is separate.",),
                            fact=child,
                        )
                    )
        if family == ("", "nodes"):
            for pod in await self._list(
                request,
                "",
                "pods",
                self.scope.namespace,
                ResourceQuery(field_selector=f"spec.nodeName={fact.ref.name}"),
            ):
                if pod.node is not None and pod.node.target.name == fact.ref.name:
                    edges.append(
                        _Edge(
                            pod.ref,
                            RelationKind.NODE,
                            RelationDirection.INCOMING,
                            RelationshipEvidence.DECLARED,
                            (pod.node.path, "Declared Pod placement."),
                            fact=pod,
                        )
                    )
        if family == ("", "services"):
            slices = await self._list(
                request,
                "discovery.k8s.io",
                "endpointslices",
                fact.ref.namespace,
                ResourceQuery(label_selector="kubernetes.io/service-name=" + fact.ref.name),
            )
            for slice_fact in slices:
                if fact.ref.name in slice_fact.services:
                    edges.append(
                        _Edge(
                            slice_fact.ref,
                            RelationKind.ENDPOINT,
                            RelationDirection.OUTGOING,
                            RelationshipEvidence.OBSERVED,
                            ("kubernetes.io/service-name label associates this EndpointSlice.",),
                            fact=slice_fact,
                        )
                    )
            # Legacy evidence is kept separate. Denied/missing slices stay in sources.
            if not slices or any(
                source.status is not RelationshipStatus.READY
                for source in self._sources.values()
                if source.family == "discovery.k8s.io/endpointslices"
            ):
                for legacy in await self._list(
                    request,
                    "",
                    "endpoints",
                    fact.ref.namespace,
                    ResourceQuery(field_selector="metadata.name=" + fact.ref.name),
                ):
                    if fact.ref.name in legacy.services:
                        edges.append(
                            _Edge(
                                legacy.ref,
                                RelationKind.ENDPOINT,
                                RelationDirection.OUTGOING,
                                RelationshipEvidence.OBSERVED,
                                (
                                    "Legacy Endpoints fallback; EndpointSlice completeness is separate.",
                                ),
                                fact=legacy,
                            )
                        )
        for index, endpoint in enumerate(fact.endpoints):
            target = endpoint.target
            status = RelationshipStatus.READY
            if target is None:
                target = RelationshipRef(
                    "v1", "EndpointAddress", fact.ref.namespace, f"address-only-{index}", None, None
                )
                status = RelationshipStatus.UNAVAILABLE
            edges.append(
                _Edge(
                    target,
                    RelationKind.ENDPOINT,
                    RelationDirection.OUTGOING,
                    RelationshipEvidence.OBSERVED,
                    (
                        endpoint.path,
                        "ready=" + str(endpoint.ready).lower(),
                        *endpoint.ports,
                        *endpoint.details,
                        "Target reference has no UID; name lookup does not prove declared UID identity."
                        if endpoint.target is not None and endpoint.target.uid is None
                        else "Endpoint target UID retained when declared.",
                    ),
                    status,
                )
            )
        return edges

    async def _walk(
        self,
        request: RelationshipRequest,
        fact: _Fact,
        path: RelationshipPath,
        ancestors: tuple[RelationshipRef, ...],
    ) -> None:
        if len(path) >= MAX_RELATIONSHIP_DEPTH:
            self._truncate(path, "Expansion depth limit reached.")
            return
        edges = await self._edges(request, fact)
        self._check(request)
        duplicates: dict[str, int] = {}
        for edge in sorted(
            edges,
            key=lambda item: (
                item.relation,
                item.direction,
                repr(relationship_identity(item.ref)),
                item.details[:1],
            ),
        ):
            if len(self._rows) >= min(MAX_RELATIONSHIP_NODES, MAX_RELATIONSHIP_EDGES + 1):
                self._truncate(path, "Graph node or edge limit reached.")
                return
            ref = self._resolved(edge.ref)
            digest = hashlib.sha256(
                repr(
                    (edge.relation, edge.direction, relationship_identity(ref), edge.details[:1])
                ).encode()
            ).hexdigest()[:24]
            ordinal = duplicates.get(digest, 0)
            duplicates[digest] = ordinal + 1
            child_path = (*path, f"{digest}:{ordinal}")
            status, details, observed = edge.status, edge.details, None
            child = edge.fact
            if status is RelationshipStatus.READY:
                if relationship_cycle(ref, ancestors):
                    status = RelationshipStatus.CYCLE
                    details += ("Cycle on this ancestor path; shared branches remain independent.",)
                elif child is None:
                    child, status, extra = await self._get(request, ref)
                    details += extra
            if child is not None:
                observed = child.ref.uid
                ref = replace(ref, resource=child.ref.resource)
            self._rows.append(
                RelationshipRow(
                    child_path,
                    ref,
                    edge.relation,
                    edge.direction,
                    edge.evidence,
                    status,
                    observed,
                    details,
                    status is RelationshipStatus.READY,
                )
            )
            self._emit(request)
            if (
                child is not None
                and status is RelationshipStatus.READY
                and child_path in request.expanded
            ):
                await self._walk(request, child, child_path, (*ancestors, ref))

    def _truncate(self, path: RelationshipPath, detail: str) -> None:
        for index, row in enumerate(self._rows):
            if row.path == path:
                self._rows[index] = replace(
                    row, status=RelationshipStatus.TRUNCATED, details=(*row.details, detail)
                )
                return

    async def collect(
        self, request: RelationshipRequest, publish: Callable[[RelationshipSnapshot], None]
    ) -> RelationshipSnapshot:
        if self._running:
            raise AppError("A relationship collector is already owned by this root.")
        self._running = True
        self._request, self._publish = request, publish
        self._rows = []
        self._comparisons = 0
        try:
            self._check(request)
            root = self.scope.root
            ref = RelationshipRef(
                self.scope.resource.api_version,
                self.scope.resource.kind,
                root.namespace,
                root.name,
                root.uid,
                self.scope.resource,
            )
            self._rows.append(
                RelationshipRow(
                    (),
                    ref,
                    None,
                    None,
                    None,
                    RelationshipStatus.LOADING,
                    None,
                    ("Revalidating captured root UID.",),
                    False,
                )
            )
            self._emit(request)
            try:
                async with asyncio.timeout(MAX_COLLECTION_SECONDS):
                    fact, status, details = await self._get(request, ref, fresh=True)
                    self._rows[0] = RelationshipRow(
                        (),
                        ref,
                        None,
                        None,
                        None,
                        status,
                        fact.ref.uid if fact is not None else None,
                        details,
                        status is RelationshipStatus.READY,
                    )
                    self._emit(request)
                    if (
                        fact is not None
                        and status is RelationshipStatus.READY
                        and () in request.expanded
                    ):
                        await self._walk(request, fact, (), (ref,))
                    if (
                        self.scope.mode is RelationshipMode.USED_BY
                        and len(self._rows) == 1
                        and () in request.expanded
                        and status is RelationshipStatus.READY
                    ):
                        complete = bool(self._sources) and all(
                            source.status is RelationshipStatus.READY
                            for source in self._sources.values()
                        )
                        self._rows[0] = replace(
                            self._rows[0],
                            details=(
                                "No supported declarations found in the completely scanned scope."
                                if complete
                                else "No supported declarations found in retained results; incomplete scans cannot establish unused.",
                            ),
                        )
            except (TimeoutError, _CollectionLimit):
                self._check(request)
                self._truncate(
                    (),
                    "Collection deadline or shared retention/read bound reached; results are incomplete.",
                )
                for key, source in tuple(self._sources.items()):
                    if source.status is RelationshipStatus.LOADING:
                        self._sources[key] = replace(
                            source,
                            status=RelationshipStatus.TRUNCATED,
                            detail="Collector deadline or shared bound reached; scan is incomplete.",
                        )
            return self._emit(request)
        finally:
            self._running = False
            self._publish = lambda _: None
