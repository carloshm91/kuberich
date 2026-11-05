"""Finite native Pod/workload diagnostics over an injected, owned session."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial

from kuberich.domain.aggregate_logs import intermediate_resource, owned_by, workload_kind
from kuberich.domain.cluster_diagnostics import (
    DIAGNOSTIC_DEADLINE,
    MAX_DIAGNOSTIC_FACT_BYTES,
    MAX_DIAGNOSTIC_ITEMS,
    MAX_DIAGNOSTIC_RAW_BYTES,
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticRequest,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
    bounded_diagnostic_snapshot,
    diagnose_claim,
    diagnose_event,
    diagnose_record,
    diagnostic_key,
    diagnostic_text,
    diagnostic_text_bytes,
    merge_native_findings,
)
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.reference_fields import declared_references
from kuberich.domain.relationships import (
    DeclaredReference,
    RelationshipRef,
    RelationshipStatus,
    reference_for,
    reference_status,
    relationship_identity,
    resolve_reference,
)
from kuberich.domain.resources import (
    ApiResource,
    Discovery,
    ResourceRecord,
    ResourceSnapshot,
)
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.resources import ResourceReader, parse_owned


@dataclass(frozen=True, slots=True)
class _Fact:
    ref: RelationshipRef
    findings: tuple[DiagnosticFinding, ...]
    claims: tuple[DeclaredReference, ...]
    scheduled: bool


def _project(
    resource: ApiResource, record: ResourceRecord, observed_at: datetime, claims: bool
) -> _Fact:
    return _Fact(
        reference_for(resource, record),
        diagnose_record(resource, record, observed_at),
        tuple(
            item
            for item in declared_references(resource, record)
            if item.target.kind == "PersistentVolumeClaim"
        )
        if claims
        else (),
        any(
            isinstance(item, dict)
            and item.get("type") == "PodScheduled"
            and item.get("status") == "True"
            for item in record.manifest.get("status", {}).get("conditions", [])
        ),
    )


def _member(record: ResourceRecord, targets: dict[str, ResourceTarget]) -> bool:
    references = record.manifest.get("metadata", {}).get("ownerReferences", [])
    if not isinstance(references, list) or len(references) > 128:
        raise AppError("Malformed or excessive controller ownership evidence.")
    for reference in references:
        if not isinstance(reference, dict):
            continue
        uid = reference.get("uid")
        target = targets.get(uid) if isinstance(uid, str) else None
        if target is not None and owned_by(record, target, workload_kind(target)):
            return True
    return False


def _event_fact(
    resource: ApiResource,
    record: ResourceRecord,
    subjects: dict[str, tuple[RelationshipRef, ...]],
    observed_at: datetime,
) -> tuple[DiagnosticFinding | None, bool]:
    data = record.manifest
    reference = data.get("regarding" if resource.group == "events.k8s.io" else "involvedObject")
    uid = reference.get("uid") if isinstance(reference, dict) else None
    candidates = subjects.get(uid, ()) if isinstance(uid, str) else ()
    return diagnose_event(resource, record, candidates, observed_at)


class _ObservedReadBudget(ReadBudget):
    """Publish charged attempts before transport can block or be cancelled."""

    def __init__(self) -> None:
        super().__init__(64)
        self.publish: Callable[[], None] | None = None

    def charge(self) -> None:
        super().charge()
        publish = self.publish
        if publish is not None:
            publish()


class DiagnosticService:
    def __init__(
        self,
        reader: ResourceReader,
        discovery: Discovery,
        policy: AccessPolicy,
        current: Callable[[DiagnosticRequest], bool],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self.budget = _ObservedReadBudget()
        self.reader = ResourceReader(reader.session, budget=self.budget)
        self.discovery, self.policy, self.current, self.now = discovery, policy, current, now
        self._sources: dict[str, DiagnosticSource] = {}
        self._findings: tuple[DiagnosticFinding, ...] = ()
        self._subjects: dict[tuple[str, str, str | None, str, str | None], RelationshipRef] = {}
        self._claims: list[tuple[RelationshipRef, DeclaredReference]] = []
        self._scheduled_uids: set[str] = set()
        self._objects = 0
        self._raw_bytes = 0
        self._fact_bytes = 0
        self._fact_items = 0
        self._publish: Callable[[DiagnosticSnapshot], None] = lambda snapshot: None

    def _check(self, request: DiagnosticRequest) -> None:
        if not self.current(request):
            raise AppError("Diagnostic request is stale; collect evidence again.")

    def _snapshot(self, request: DiagnosticRequest, collecting: bool) -> DiagnosticSnapshot:
        snapshot = bounded_diagnostic_snapshot(
            DiagnosticSnapshot(
                request,
                self._findings,
                tuple(self._sources.values()),
                collecting,
                self.budget.used,
                self.now(),
            )
        )
        self._findings = snapshot.findings
        self._sources = {source.key: source for source in snapshot.sources}
        return snapshot

    def _emit(self, request: DiagnosticRequest, collecting: bool = True) -> DiagnosticSnapshot:
        self._check(request)
        snapshot = self._snapshot(request, collecting)
        self._publish(snapshot)
        return snapshot

    def _source(
        self,
        resource: ApiResource | None,
        namespace: str | None,
        kind: DiagnosticSourceKind,
        suffix: str = "",
    ) -> str:
        key = diagnostic_key(
            "source",
            resource.group if resource else None,
            resource.name if resource else None,
            namespace,
            suffix,
        )
        self._sources[key] = DiagnosticSource(
            key,
            kind,
            resource,
            namespace,
            DiagnosticStatus.LOADING,
            None,
            None,
            None,
            "Collecting bounded evidence.",
        )
        return key

    def _limited(self, key: str, detail: str, omitted: int = 0) -> None:
        source = self._sources[key]
        self._sources[key] = replace(
            source,
            status=DiagnosticStatus.PARTIAL,
            detail=diagnostic_text(source.detail + " " + detail)
            if detail not in source.detail
            else source.detail,
            omitted_findings=source.omitted_findings + omitted,
        )

    def _add(self, key: str, findings: tuple[DiagnosticFinding, ...]) -> None:
        self._findings, omitted = merge_native_findings((*self._findings, *findings))
        if omitted:
            self._limited(
                key, f"Omitted {omitted} evidence entries at the per-finding evidence limit."
            )

    async def _list(
        self, request: DiagnosticRequest, resource: ApiResource, kind: DiagnosticSourceKind
    ) -> tuple[str, ResourceSnapshot | None]:
        self._check(request)
        namespace = request.scope.namespace
        key = self._source(resource, namespace, kind)
        self._emit(request)
        latest: ResourceSnapshot | None = None

        async def progress(snapshot: ResourceSnapshot) -> None:
            nonlocal latest
            self._check(request)
            latest = snapshot

        detail = "Observed bounded source; absence does not establish health."
        status = DiagnosticStatus.READY
        try:
            # Half the raw/object allowance remains available for UID-linked Events.
            cap = (
                MAX_DIAGNOSTIC_ITEMS // 2
                if kind is DiagnosticSourceKind.EVENT
                else MAX_DIAGNOSTIC_ITEMS // 2 - self._objects
            )
            byte_cap = (
                MAX_DIAGNOSTIC_RAW_BYTES // 2
                if kind is DiagnosticSourceKind.EVENT
                else MAX_DIAGNOSTIC_RAW_BYTES // 2 - self._raw_bytes
            )
            latest = await self.reader.list(
                resource,
                namespace,
                max_items=max(0, cap),
                max_retained_bytes=max(0, byte_cap),
                progress=progress,
            )
            self._check(request)
            if not latest.collection.complete:
                status, detail = (
                    DiagnosticStatus.PARTIAL,
                    "Source is incomplete: native read, object, payload or pagination limit.",
                )
        except (ConnectionProblem, AppError, ReadBudgetExceeded) as error:
            self._check(request)
            status = (
                DiagnosticStatus.FORBIDDEN
                if isinstance(error, HttpProblem) and error.status == 403
                else DiagnosticStatus.UNAVAILABLE
                if isinstance(error, HttpProblem) and error.status == 404
                else DiagnosticStatus.PARTIAL
                if isinstance(error, ReadBudgetExceeded)
                else DiagnosticStatus.FAILED
            )
            detail = (
                "Source read was denied (HTTP 403)."
                if status is DiagnosticStatus.FORBIDDEN
                else "Source unavailable or invalid; evidence is incomplete."
            )
            if latest is not None:
                status = DiagnosticStatus.PARTIAL
                detail += " Retaining completed pages."
        self._sources[key] = replace(
            self._sources[key],
            status=status,
            collection=latest.collection if latest is not None else None,
            resource_version=latest.resource_version if latest is not None else None,
            observed_at=self.now(),
            detail=detail,
        )
        if latest is not None:
            self._objects += len(latest.items)
            self._raw_bytes += sum(item.size_bytes for item in latest.items)
        return key, latest

    async def _get(
        self, request: DiagnosticRequest, resource: ApiResource, name: str, *, suffix: str
    ) -> tuple[str, ResourceRecord | None]:
        self._check(request)
        key = self._source(
            resource, request.scope.namespace, DiagnosticSourceKind.CONDITION, suffix
        )
        self._emit(request)
        record: ResourceRecord | None = None
        status, detail = DiagnosticStatus.READY, "Observed exact object identity."
        try:
            if (
                self._objects >= MAX_DIAGNOSTIC_ITEMS // 2
                or self._raw_bytes >= MAX_DIAGNOSTIC_RAW_BYTES // 2
            ):
                raise ReadBudgetExceeded
            record = await self.reader.get(resource, name, request.scope.namespace)
            self._check(request)
            if self._raw_bytes + record.size_bytes > MAX_DIAGNOSTIC_RAW_BYTES // 2:
                record = None
                raise ReadBudgetExceeded
            self._objects += 1
            self._raw_bytes += record.size_bytes
        except (ConnectionProblem, AppError, ReadBudgetExceeded) as error:
            self._check(request)
            status = (
                DiagnosticStatus.FORBIDDEN
                if isinstance(error, HttpProblem) and error.status == 403
                else DiagnosticStatus.PARTIAL
                if isinstance(error, ReadBudgetExceeded)
                else DiagnosticStatus.UNAVAILABLE
            )
            detail = (
                "Object read denied (HTTP 403)."
                if status is DiagnosticStatus.FORBIDDEN
                else "Object unavailable or collection budget exhausted; no cause is established."
            )
        self._sources[key] = replace(
            self._sources[key],
            status=status,
            observed_at=self.now(),
            resource_version=record.resource_version if record is not None else None,
            detail=detail,
        )
        return key, record

    async def _facts(
        self,
        request: DiagnosticRequest,
        key: str,
        resource: ApiResource,
        records: tuple[ResourceRecord, ...],
        *,
        targets: tuple[ResourceTarget, ...] | None = None,
    ) -> tuple[ResourceTarget, ...]:
        selected: list[ResourceTarget] = []
        owners = {target.uid: target for target in targets or ()}
        for record in records:
            self._check(request)
            try:
                if targets is not None and not await parse_owned(partial(_member, record, owners)):
                    continue
                fact = await parse_owned(
                    partial(_project, resource, record, self.now(), request.scope.root is not None)
                )
                self._check(request)
                size = diagnostic_text_bytes(fact)
                count = 1 + len(fact.claims) + sum(len(f.evidence) for f in fact.findings)
                if (
                    self._fact_bytes + size > MAX_DIAGNOSTIC_FACT_BYTES
                    or self._fact_items + count > MAX_DIAGNOSTIC_ITEMS
                ):
                    self._limited(
                        key,
                        "Compact fact retention limit; additional objects omitted.",
                        len(records) - len(selected),
                    )
                    break
                self._fact_bytes += size
                self._fact_items += count
                self._subjects[relationship_identity(fact.ref)] = fact.ref
                self._claims.extend((fact.ref, item) for item in fact.claims)
                if fact.scheduled and fact.ref.uid is not None:
                    self._scheduled_uids.add(fact.ref.uid)
                self._add(key, fact.findings)
                if record.uid is not None:
                    selected.append(
                        ResourceTarget(
                            request.scope.session,
                            resource.group,
                            resource.name,
                            record.namespace,
                            record.name,
                            record.uid,
                        )
                    )
                # Keep retained findings bounded while processing a large source.
                self._snapshot(request, True)
            except AppError:
                self._check(request)
                self._limited(key, "Malformed object evidence was omitted.", 1)
        self._emit(request)
        return tuple(selected)

    def _discovered(self, group: str, name: str) -> ApiResource | None:
        return next(
            (
                item
                for item in self.discovery.preferred_resources
                if item.group == group and item.name == name
            ),
            None,
        )

    async def _native(self, request: DiagnosticRequest) -> None:
        root = request.scope.root
        targets: tuple[ResourceTarget, ...] | None = None
        pod_resource = self._discovered("", "pods")
        if root is not None:
            assert root.resource is not None  # DiagnosticScope validates this boundary.
            if root.resource not in self.discovery.resources:
                key = self._source(
                    root.resource, request.scope.namespace, DiagnosticSourceKind.CONDITION, "root"
                )
                self._sources[key] = replace(
                    self._sources[key],
                    status=DiagnosticStatus.UNAVAILABLE,
                    detail="Captured root API is absent from current discovery; no root read was made.",
                )
                self._emit(request)
                return
            target = ResourceTarget(
                request.scope.session,
                root.resource.group,
                root.resource.name,
                root.namespace,
                root.name,
                root.uid or "",
            )
            workload_kind(target)
            key, record = await self._get(request, root.resource, root.name, suffix="root")
            if record is None:
                return
            if reference_status(root, record) is not RelationshipStatus.READY:
                self._limited(key, "Root UID changed; no replacement evidence was collected.")
                self._emit(request)
                return
            await self._facts(request, key, root.resource, (record,))
            if root.resource.group == "" and root.resource.name == "pods":
                pod_resource = None
            else:
                targets = (target,)
                intermediate = intermediate_resource(target)
                if intermediate is not None:
                    served = self._discovered(intermediate.group, intermediate.name)
                    if served is None:
                        key = self._source(
                            None,
                            request.scope.namespace,
                            DiagnosticSourceKind.CONDITION,
                            "controller",
                        )
                        self._limited(
                            key,
                            "Intermediate controller API was not discovered; Pod ownership is unknown.",
                        )
                        targets = ()
                    else:
                        key, snapshot = await self._list(
                            request, served, DiagnosticSourceKind.CONDITION
                        )
                        targets = (
                            await self._facts(request, key, served, snapshot.items, targets=targets)
                            if snapshot is not None
                            else ()
                        )
        if pod_resource is not None:
            key, snapshot = await self._list(request, pod_resource, DiagnosticSourceKind.CONDITION)
            if snapshot is not None:
                await self._facts(request, key, pod_resource, snapshot.items, targets=targets)
        elif root is None:
            key = self._source(
                None, request.scope.namespace, DiagnosticSourceKind.CONDITION, "pods"
            )
            self._sources[key] = replace(
                self._sources[key],
                status=DiagnosticStatus.UNAVAILABLE,
                detail="Pod API was not discovered; Pod evidence is unknown.",
            )
        if root is not None:
            await self._volumes(request)
        await self._events(request)

    async def _volumes(self, request: DiagnosticRequest) -> None:
        cache: dict[tuple[str | None, str], tuple[str, ResourceRecord | None]] = {}
        for subject, declaration in self._claims:
            self._check(request)
            ref = resolve_reference(self.discovery, declaration.target)
            identity = ref.namespace, ref.name
            if identity not in cache:
                if len(cache) >= 16:
                    key = self._source(
                        None, request.scope.namespace, DiagnosticSourceKind.CONDITION, "pvc-limit"
                    )
                    self._limited(
                        key,
                        "At most 16 distinct declared PVCs are read; remaining declarations omitted.",
                    )
                    break
                if ref.resource is None:
                    key = self._source(
                        None,
                        request.scope.namespace,
                        DiagnosticSourceKind.CONDITION,
                        "pvc:" + ref.name,
                    )
                    self._sources[key] = replace(
                        self._sources[key],
                        status=DiagnosticStatus.UNAVAILABLE,
                        detail="Declared PVC API is unavailable; no cause is established.",
                    )
                    cache[identity] = key, None
                else:
                    cache[identity] = await self._get(
                        request, ref.resource, ref.name, suffix="pvc:" + ref.name
                    )
            key, record = cache[identity]
            if record is None:
                continue
            try:
                if ref.resource is None:
                    continue
                findings = await parse_owned(
                    partial(diagnose_claim, subject, ref.resource, record, declaration, self.now())
                )
                self._check(request)
                self._add(key, findings)
                self._snapshot(request, True)
            except AppError:
                self._limited(key, "Malformed PVC evidence was omitted.", 1)
        self._emit(request)

    async def _events(self, request: DiagnosticRequest) -> None:
        resource = self._discovered("", "events") or self._discovered("events.k8s.io", "events")
        if resource is None:
            key = self._source(None, request.scope.namespace, DiagnosticSourceKind.EVENT)
            self._sources[key] = replace(
                self._sources[key],
                status=DiagnosticStatus.UNAVAILABLE,
                detail="Event API was not discovered; Events may also have expired.",
            )
            self._emit(request)
            return
        key, snapshot = await self._list(request, resource, DiagnosticSourceKind.EVENT)
        if snapshot is not None:
            subjects: dict[str, tuple[RelationshipRef, ...]] = {}
            for subject in self._subjects.values():
                if subject.uid is not None:
                    subjects[subject.uid] = (*subjects.get(subject.uid, ()), subject)
            unmatched = 0
            for record in snapshot.items:
                self._check(request)
                try:
                    finding, missing = await parse_owned(
                        partial(_event_fact, resource, record, subjects, self.now())
                    )
                    self._check(request)
                    unmatched += int(missing)
                    if finding is not None:
                        size = diagnostic_text_bytes(finding)
                        if (
                            self._fact_bytes + size > MAX_DIAGNOSTIC_FACT_BYTES
                            or self._fact_items + 1 > MAX_DIAGNOSTIC_ITEMS
                        ):
                            self._limited(
                                key, "Compact Event fact limit; remaining Events omitted.", 1
                            )
                            break
                        self._fact_bytes += size
                        self._fact_items += 1
                        if (
                            finding.category is DiagnosticCategory.SCHEDULING
                            and finding.subject is not None
                            and finding.subject.uid in self._scheduled_uids
                        ):
                            from kuberich.domain.cluster_diagnostics import DiagnosticSeverity

                            finding = replace(
                                finding,
                                severity=DiagnosticSeverity.INFO,
                                summary="Earlier scheduling event; Pod is now scheduled",
                                explanation="Current PodScheduled=True supersedes the reported scheduling failure; this event does not establish a current failure.",
                                evidence=tuple(
                                    replace(item, historical=True) for item in finding.evidence
                                ),
                            )
                        contexts = tuple(
                            replace(existing, evidence=finding.evidence)
                            for existing in self._findings
                            if finding.category is DiagnosticCategory.OTHER
                            and existing.subject is not None
                            and finding.subject is not None
                            and relationship_identity(existing.subject)
                            == relationship_identity(finding.subject)
                            and existing.source is DiagnosticSourceKind.CONDITION
                        )
                        # Generic Event reasons enrich an already observed condition;
                        # they never select image/crash/readiness categories themselves.
                        self._add(key, contexts or (finding,))
                        self._snapshot(request, True)
                except AppError:
                    unmatched += 1
            if unmatched:
                self._limited(
                    key,
                    f"{unmatched} unrelated, malformed or UID-unmatched Events were not attributed.",
                )
            if not snapshot.items:
                self._sources[key] = replace(
                    self._sources[key],
                    detail=self._sources[key].detail
                    + " No Events observed; Events may have expired.",
                )
        self._emit(request)

    async def collect(
        self, request: DiagnosticRequest, publish: Callable[[DiagnosticSnapshot], None]
    ) -> DiagnosticSnapshot:
        self.policy.require(Action.READ)
        self._check(request)
        self._publish = publish
        self._emit(request)

        def charged() -> None:
            self._emit(request)

        self.budget.publish = charged
        try:
            async with asyncio.timeout(DIAGNOSTIC_DEADLINE):
                await self._native(request)
        except TimeoutError:
            self._check(request)
            key = self._source(
                None, request.scope.namespace, DiagnosticSourceKind.CONDITION, "deadline"
            )
            self._limited(key, "Native collection deadline reached; completed evidence retained.")
            for source_key, source in tuple(self._sources.items()):
                if source.status is DiagnosticStatus.LOADING:
                    self._limited(source_key, "Source unfinished at the collection deadline.")
        finally:
            self.budget.publish = None
        return self._emit(request, False)

    async def resolve(self, request: DiagnosticRequest, ref: RelationshipRef) -> ResourceRecord:
        self.policy.require(Action.READ)
        self._check(request)
        resource = ref.resource
        if (
            resource is None
            or resource not in self.discovery.resources
            or ref.api_version != resource.api_version
            or ref.kind != resource.kind
            or resource.namespaced != (ref.namespace is not None)
            or (
                resource.namespaced
                and request.scope.namespace is not None
                and ref.namespace != request.scope.namespace
            )
        ):
            raise AppError("Diagnostic object has no exact served resource identity.")
        reader = ResourceReader(self.reader.session, budget=ReadBudget(4))
        record = await reader.get(resource, ref.name, ref.namespace)
        self._check(request)
        if reference_status(ref, record) is not RelationshipStatus.READY:
            raise AppError("Diagnostic object was replaced or became unavailable; collect again.")
        return record
