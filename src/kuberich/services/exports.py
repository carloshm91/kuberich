"""Owned export preparation, explicit one-use consent and local artifact operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from kuberich.adapters.artifact_files import ArtifactDirectoryMissing, ArtifactFiles
from kuberich.domain.exports import (
    ArtifactEntry,
    ArtifactListing,
    ArtifactMetadata,
    ArtifactRef,
    DestinationReview,
    ExportCapture,
    ExportIntent,
    ExportKind,
    ExportScope,
    FileOutcome,
    PreparedArtifact,
    ResourceSource,
    SensitiveApproval,
    SupportSource,
    TextPage,
    artifact_page,
    available_formats,
    inspect_metadata,
    prepare_capture,
    read_artifact,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, api_segment, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError, ExitCode
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.export_ports import ResourceExportClient


def _stale() -> AppError:
    return AppError("Export source changed; close this review and capture it again.")


def _consent_error() -> AppError:
    return AppError("Sensitive approval is missing, changed or already used; acknowledge again.")


def _local_error() -> AppError:
    return AppError(
        "Cannot access the selected local artifact; refresh and review the location.",
        ExitCode.LOCAL_IO,
    )


def _raw_hash(record: ResourceRecord) -> str:
    return hashlib.sha256(
        json.dumps(
            record.manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _legacy_hint(prefix: bytes) -> ArtifactMetadata | None:
    # A listing hint only: complete allowlist validation happens on every use.
    if re.match(rb'\s*\{\s*"schema_version"\s*:\s*1\s*,', prefix) is None or not all(
        b'"' + key + b'"' in prefix
        for key in (b"version", b"python", b"platform", b"terminal", b"config_check", b"recent_log")
    ):
        return None
    return ArtifactMetadata(
        schema_version=1,
        format="legacy-report",
        scope=ExportScope(
            export_at=None,
            source_at=None,
            context=None,
            header_namespace=None,
            collection_namespace=None,
            namespace_mode="unknown",
        ),
        sensitive=False,
        presentation=None,
        notices=("Legacy report candidate; complete content is validated when opened.",),
    )


class ResourceExportReader:
    """One exact served API read using the captured client, scope and UID."""

    def __init__(
        self,
        client: ResourceExportClient,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.policy, self.current = policy, current

    def _require(self) -> None:
        self.policy.require(Action.READ)
        if not self.current():
            raise _stale()
        if (
            self.client.context.name != self.target.session.context
            or self.resource.group != self.target.group
            or self.resource.name != self.target.resource
            or self.resource.namespaced != (self.target.namespace is not None)
            or "get" not in self.resource.verbs
        ):
            raise _stale()

    async def read(self, *, expected_version: str | None = None) -> ResourceRecord:
        from kuberich.services.resources import parse_owned

        self._require()
        payload = await self.client.get_json(
            self.resource.path(self.target.namespace) + "/" + api_segment(self.target.name)
        )
        self._require()

        def parse() -> ResourceRecord:
            if (
                payload.get("apiVersion") != self.resource.api_version
                or payload.get("kind") != self.resource.kind
            ):
                raise _stale()
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("namespace") != self.target.namespace:
                raise _stale()
            return resource_record(self.resource, payload, self.target.namespace)

        record = await parse_owned(parse)
        self._require()
        self.target.require_current(self.target.session, uid=record.uid or "")
        if (
            record.name != self.target.name
            or record.namespace != self.target.namespace
            or record.metadata_only
            or (expected_version is not None and record.resource_version != expected_version)
        ):
            raise _stale()
        return record


@dataclass(frozen=True, kw_only=True, slots=True)
class ExportLease:
    id: UUID
    capture: ExportCapture = field(repr=False)
    current: Callable[[], bool] = field(repr=False)
    session: SessionIdentity | None
    resource_reader: ResourceExportReader | None = field(default=None, repr=False)


type ExportChoices = tuple[tuple[ExportKind, ExportLease], ...]
type CapturePort = Callable[[datetime], ExportChoices]


@dataclass(slots=True)
class _Job:
    task: asyncio.Task[Any]
    cancel: threading.Event
    session: SessionIdentity | None
    api: bool = False


@dataclass(frozen=True, slots=True)
class _Consent:
    token: SensitiveApproval
    subject: ExportLease | ArtifactRef
    kind: ExportKind
    intent: ExportIntent
    destination: DestinationReview | None
    raw_hash: str


@dataclass(frozen=True, slots=True)
class _Preparation:
    artifact: PreparedArtifact
    intent: ExportIntent
    destination: DestinationReview | None
    lease: ExportLease | None
    sensitive: bool


async def _drain(task: asyncio.Future[Any]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            # The original caller is already cancelling; consume a late worker
            # error after ownership ends instead of replacing that cancellation.
            pass
    # Retrieve late failures without replacing cancellation in the caller.
    if not task.cancelled():
        task.exception()


class ExportService:
    def __init__(
        self,
        *,
        files: ArtifactFiles,
        default_root: Path,
        report_payload: Callable[[], bytes],
        clock: Callable[[], datetime],
        new_id: Callable[[], UUID],
    ) -> None:
        self._files, self._default_root = files, default_root
        self._report_payload, self._clock, self._new_id = report_payload, clock, new_id
        self._jobs: list[_Job] = []
        self._leases: dict[UUID, ExportLease] = {}
        self._approvals: dict[UUID, _Consent] = {}
        self._prepared: dict[UUID, _Preparation] = {}
        self._revoked: set[SessionIdentity] = set()
        self._revoked_connections: set[UUID] = set()
        self._closed = False
        self._last_outcome: FileOutcome | None = None
        self._mutation = asyncio.Lock()

    @property
    def default_root(self) -> Path:
        return self._default_root

    @property
    def operation_count(self) -> int:
        return sum(not job.task.done() for job in self._jobs)

    @property
    def last_outcome(self) -> FileOutcome | None:
        return self._last_outcome

    def _open(self) -> None:
        if self._closed:
            raise AppError("Export service is closed.")

    def _lease(self, lease: ExportLease, *, register: bool = True) -> None:
        self._open()
        if not lease.current() or self._session_revoked(lease.session):
            raise _stale()
        previous = self._leases.get(lease.id)
        if previous is not None and previous is not lease:
            raise _stale()
        if register:
            self._leases[lease.id] = lease
        elif previous is None:
            raise _stale()

    def _session_revoked(self, session: SessionIdentity | None) -> bool:
        return session is not None and (
            session in self._revoked or session.connection_id in self._revoked_connections
        )

    def _forget_unused(self, lease: ExportLease) -> None:
        if not any(item.lease is lease for item in self._prepared.values()) and not any(
            item.subject is lease for item in self._approvals.values()
        ):
            self._leases.pop(lease.id, None)

    def _outcome(self, task: asyncio.Task[Any]) -> None:
        if task.done() and not task.cancelled() and task.exception() is None:
            value = task.result()
            if isinstance(value, FileOutcome):
                self._last_outcome = value

    async def _worker[T](
        self, operation: Callable[[threading.Event], T], *, session: SessionIdentity | None = None
    ) -> T:
        self._open()
        if self._session_revoked(session):
            raise _stale()
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(operation, cancel))
        job = _Job(task, cancel, session)
        self._jobs.append(job)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                cancel.set()
                await _drain(task)
                raise
        finally:
            self._outcome(task)
            self._jobs.remove(job)

    async def _api[T](
        self, operation: Coroutine[Any, Any, T], session: SessionIdentity | None
    ) -> T:
        self._open()
        task = asyncio.create_task(operation)
        job = _Job(task, threading.Event(), session, True)
        self._jobs.append(job)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                task.cancel()
                await _drain(task)
                raise
        finally:
            self._jobs.remove(job)

    async def resolve(self, lease: ExportLease) -> ExportLease:
        self._lease(lease)
        try:
            source = lease.capture.source
            if not isinstance(source, ResourceSource) or not source.record.metadata_only:
                return lease
            if lease.resource_reader is None:
                raise _stale()
            record = await self._api(lease.resource_reader.read(), lease.session)
            self._lease(lease, register=False)
            scope = replace(
                lease.capture.scope,
                uid=record.uid,
                resource_version=record.resource_version,
                source_at=self._clock(),
            )
            resolved = replace(
                lease,
                id=self._new_id(),
                capture=replace(lease.capture, scope=scope, source=replace(source, record=record)),
            )
            self._leases.pop(lease.id, None)
            return resolved
        finally:
            self._forget_unused(lease)

    def _consume(
        self,
        approval: SensitiveApproval,
        subject: ExportLease | ArtifactRef,
        kind: ExportKind,
        intent: ExportIntent,
        destination: DestinationReview | None,
    ) -> _Consent:
        consent = self._approvals.pop(approval.nonce, None)
        if consent is not None and isinstance(consent.subject, ExportLease):
            self._forget_unused(consent.subject)
        if (
            consent is None
            or consent.token is not approval
            or consent.subject != subject
            or consent.kind != kind
            or consent.intent != intent
            or consent.destination != destination
        ):
            raise _consent_error()
        return consent

    async def prepare(
        self,
        lease: ExportLease,
        kind: ExportKind,
        *,
        approval: SensitiveApproval | None = None,
        destination: DestinationReview | None = None,
    ) -> PreparedArtifact:
        consent = (
            None if approval is None else self._consume(approval, lease, kind, "save", destination)
        )
        self._lease(lease)
        try:
            source = lease.capture.source
            if kind not in available_formats(lease.capture) or (
                isinstance(source, ResourceSource) and source.record.metadata_only
            ):
                raise _stale()
            sensitive = consent is not None
            if sensitive:
                # Only registered acknowledgement can enter this branch. Its lease
                # is immutable; issuance proved a full resource source and reader.
                live = cast(ResourceSource, source)
                reader = cast(ResourceExportReader, lease.resource_reader)
                record = await self._api(
                    reader.read(expected_version=live.record.resource_version),
                    lease.session,
                )
                digest = await self._worker(lambda _: _raw_hash(record), session=lease.session)
                self._lease(lease, register=False)
                assert consent is not None
                if digest != consent.raw_hash:
                    raise _consent_error()
            artifact_id = self._new_id()

            def build(cancel: threading.Event) -> PreparedArtifact:
                if cancel.is_set():
                    raise _stale()
                report = self._report_payload() if isinstance(source, SupportSource) else None
                value = prepare_capture(
                    lease.capture,
                    kind,
                    artifact_id=artifact_id,
                    sensitive=sensitive,
                    report_json=report,
                )
                if cancel.is_set():
                    raise _stale()
                return value

            prepared = await self._worker(build, session=lease.session)
            self._lease(lease, register=False)
            self._prepared[prepared.id] = _Preparation(
                prepared, "save", destination, lease, sensitive
            )
            return prepared
        finally:
            self._forget_unused(lease)

    async def review_destination(
        self, root: Path, name: str, *, replace: bool = False
    ) -> DestinationReview:
        def review(cancel: threading.Event) -> DestinationReview:
            directory = self._files.directory(
                root, create=root == self._default_root, cancel=cancel
            )
            return self._files.review(directory, name, replace=replace, cancel=cancel)

        return await self._worker(review)

    async def approve_sensitive(
        self,
        subject: ExportLease | ArtifactRef,
        kind: ExportKind,
        *,
        intent: ExportIntent,
        destination: DestinationReview | None = None,
    ) -> SensitiveApproval:
        try:
            if intent not in {"save", "view", "copy"} or (intent == "save") != (
                destination is not None
            ):
                raise _consent_error()
            if isinstance(subject, ExportLease):
                self._lease(subject)
                source = subject.capture.source
                if (
                    not isinstance(source, ResourceSource)
                    or kind != "resource-yaml"
                    or intent != "save"
                    or subject.resource_reader is None
                    or source.record.metadata_only
                    or not source.record.uid
                    or not source.record.resource_version
                    or source.record.uid != subject.capture.scope.uid
                    or source.record.resource_version != subject.capture.scope.resource_version
                    or subject.session is None
                    or subject.session != subject.resource_reader.target.session
                    or source.resource != subject.resource_reader.resource
                    or source.record.uid != subject.resource_reader.target.uid
                    or source.record.name != subject.resource_reader.target.name
                    or source.record.namespace != subject.resource_reader.target.namespace
                    or subject.capture.scope.context != subject.session.context
                    or subject.capture.scope.api_version != source.resource.api_version
                    or subject.capture.scope.resource != source.resource.name
                    or subject.capture.scope.kind != source.resource.kind
                    or subject.capture.scope.name != source.record.name
                    or subject.capture.scope.collection_namespace != source.record.namespace
                ):
                    raise _consent_error()
                digest = await self._worker(
                    lambda _: _raw_hash(source.record), session=subject.session
                )
                self._lease(subject, register=False)
                binding: object = (
                    str(subject.id),
                    str(subject.session),
                    source.record.uid,
                    source.record.resource_version,
                )
            else:

                def verify(cancel: threading.Event) -> tuple[str, PreparedArtifact]:
                    data = self._files.read(subject, cancel=cancel)
                    return hashlib.sha256(data).hexdigest(), read_artifact(
                        data, artifact_id=self._new_id()
                    )

                digest, prepared = await self._worker(verify)
                self._open()
                if (
                    prepared.metadata.format != kind
                    or kind != "resource-yaml"
                    or subject.identity.mode & 0o077
                ):
                    raise _consent_error()
                binding = (str(subject.directory), subject.name, str(subject.identity))
            token = SensitiveApproval(
                nonce=self._new_id(),
                binding_sha256=hashlib.sha256(
                    repr((binding, digest, kind, intent, destination)).encode()
                ).hexdigest(),
            )
            self._approvals[token.nonce] = _Consent(
                token, subject, kind, intent, destination, digest
            )
            return token
        finally:
            if isinstance(subject, ExportLease):
                self._forget_unused(subject)

    def _preparation(self, prepared: PreparedArtifact, intent: ExportIntent) -> _Preparation:
        self._open()
        state = self._prepared.get(prepared.id)
        if state is None or state.artifact is not prepared or state.intent != intent:
            raise AppError("Artifact preparation expired or does not authorize this action.")
        return state

    async def publish(self, prepared: PreparedArtifact, review: DestinationReview) -> FileOutcome:
        state = self._preparation(prepared, "save")
        self._prepared.pop(prepared.id, None)
        try:
            if state.destination != review:
                raise AppError("Export destination changed; prepare and review again.")
            if state.lease is not None:
                self._lease(state.lease, register=False)
            async with self._mutation:
                if state.lease is not None:
                    self._lease(state.lease, register=False)
                return await self._worker(
                    lambda cancel: self._files.publish(prepared, review, cancel=cancel),
                    session=None if state.lease is None else state.lease.session,
                )
        finally:
            if state.lease is not None:
                self._forget_unused(state.lease)

    async def scan(self, root: Path) -> ArtifactListing:
        def scan(cancel: threading.Event) -> ArtifactListing:
            try:
                directory = self._files.directory(root, create=False, cancel=cancel)
            except ArtifactDirectoryMissing:
                if root == self._default_root:
                    return ArtifactListing(
                        entries=(),
                        limited=False,
                        skipped=0,
                        notice="No saved exports yet; the default directory is created on Save.",
                    )
                raise
            listing = self._files.scan(directory, cancel=cancel)
            entries: list[ArtifactEntry] = []
            skipped = listing.skipped
            for ref in listing.refs:
                if cancel.is_set():
                    raise _local_error()
                try:
                    prefix = self._files.read(ref, prefix=True, cancel=cancel)
                    metadata = inspect_metadata(prefix) or _legacy_hint(prefix)
                    if metadata is None:
                        skipped += 1
                    else:
                        entries.append(ArtifactEntry(ref=ref, metadata=metadata))
                except AppError:
                    entries.append(
                        ArtifactEntry(
                            ref=ref,
                            metadata=None,
                            problem="Artifact could not be inspected; refresh before use.",
                        )
                    )
            return ArtifactListing(entries=tuple(entries), limited=listing.limited, skipped=skipped)

        return await self._worker(scan)

    async def read(
        self,
        ref: ArtifactRef,
        *,
        intent: ExportIntent = "view",
        approval: SensitiveApproval | None = None,
        destination: DestinationReview | None = None,
    ) -> PreparedArtifact:
        consent: _Consent | None = None
        if approval is not None:
            saved = self._approvals.get(approval.nonce)
            # Consume even a mismatched attempt, without trusting a caller's format.
            kind: ExportKind = "resource-yaml" if saved is None else saved.kind
            consent = self._consume(approval, ref, kind, intent, destination)
        if intent not in {"view", "copy", "save"} or (intent != "save" and destination is not None):
            raise _consent_error()

        def decode(cancel: threading.Event) -> PreparedArtifact:
            data = self._files.read(ref, cancel=cancel)
            if consent is not None and hashlib.sha256(data).hexdigest() != consent.raw_hash:
                raise _consent_error()
            value = read_artifact(data, artifact_id=self._new_id(), sensitive=consent is not None)
            if cancel.is_set():
                raise _local_error()
            return value

        prepared = await self._worker(decode)
        self._open()
        self._prepared[prepared.id] = _Preparation(
            prepared, intent, destination, None, consent is not None
        )
        return prepared

    async def page(self, prepared: PreparedArtifact, index: int) -> TextPage:
        self._preparation(prepared, "view")
        return await self._worker(lambda _: artifact_page(prepared, index))

    async def copy_text(self, prepared: PreparedArtifact) -> str:
        self._preparation(prepared, "copy")
        if len(prepared.payload) > 1024 * 1024:
            raise AppError("Artifact exceeds the 1 MiB clipboard limit; save a copy instead.")
        return await self._worker(lambda _: prepared.payload.decode("utf-8"))

    async def delete(self, ref: ArtifactRef, *, confirmed: bool) -> FileOutcome:
        self._open()
        if not confirmed:
            raise AppError("Artifact deletion requires explicit confirmation.")
        async with self._mutation:
            return await self._worker(lambda cancel: self._files.delete(ref, cancel=cancel))

    def discard(self, value: PreparedArtifact | SensitiveApproval) -> None:
        if isinstance(value, SensitiveApproval):
            consent = self._approvals.pop(value.nonce, None)
            if consent is not None and isinstance(consent.subject, ExportLease):
                self._forget_unused(consent.subject)
        else:
            state = self._prepared.pop(value.id, None)
            if state is not None and state.lease is not None:
                self._forget_unused(state.lease)

    async def close_for_session(self, session: SessionIdentity) -> None:
        self._revoked.add(session)
        for key, lease in tuple(self._leases.items()):
            if lease.session == session:
                self._leases.pop(key)
        for key, consent in tuple(self._approvals.items()):
            if isinstance(consent.subject, ExportLease) and consent.subject.session == session:
                self._approvals.pop(key)
        for key, state in tuple(self._prepared.items()):
            if state.sensitive and state.lease is not None and state.lease.session == session:
                self._prepared.pop(key)
        jobs = [job for job in self._jobs if job.session == session]
        for job in jobs:
            job.cancel.set()
            if job.api:
                job.task.cancel()
        await _drain(asyncio.gather(*(job.task for job in jobs), return_exceptions=True))
        for job in jobs:
            self._outcome(job.task)

    async def close_for_connection(self, connection_id: UUID) -> None:
        """Drain every namespace generation before its shared client is closed."""
        self._revoked_connections.add(connection_id)
        sessions = {
            job.session
            for job in self._jobs
            if job.session is not None and job.session.connection_id == connection_id
        }
        sessions.update(
            lease.session
            for lease in self._leases.values()
            if lease.session is not None and lease.session.connection_id == connection_id
        )
        for session in sessions:
            await self.close_for_session(session)

    async def close(self) -> None:
        self._closed = True
        self._leases.clear()
        self._approvals.clear()
        self._prepared.clear()
        jobs = tuple(self._jobs)
        for job in jobs:
            job.cancel.set()
            if job.api:
                job.task.cancel()
        await _drain(asyncio.gather(*(job.task for job in jobs), return_exceptions=True))
        for job in jobs:
            self._outcome(job.task)
