"""Offline immutable creation drafts and explicitly disclosed private editor leases."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from kuberich.adapters.editing import ManifestFile, file_worker
from kuberich.adapters.manifest_files import ManifestFiles
from kuberich.domain.editing import editor_arguments
from kuberich.domain.manifests import (
    DraftSourceKind,
    FrozenDraftSource,
    manifest_documents,
)
from kuberich.domain.processes import ProcessCommand, editor_command
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation
from kuberich.services.ownership import finish_owned

if TYPE_CHECKING:
    from kuberich.domain.resource_templates import TemplateCatalogEntry
    from kuberich.services.resource_templates import TemplateCatalogService


@dataclass(frozen=True, kw_only=True, slots=True)
class DraftDisclosureIntent:
    identity: UUID
    source: FrozenDraftSource = field(repr=False)


class ResourceCreationService:
    """No connection, schema claim, automatic save, or clipboard reads on capture."""

    def __init__(
        self, policy: AccessPolicy, environment: Mapping[str, str], directory: Path
    ) -> None:
        self.policy, self.environment, self.directory = (
            policy,
            dict(environment),
            directory.absolute(),
        )
        self.current_source: FrozenDraftSource | None = None
        self._require_origin: Callable[[], Awaitable[None]] | None = None
        self._generation = 0
        self._closed = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closing: asyncio.Task[None] | None = None
        self._draft: ManifestFile | None = None
        self._draft_closing: asyncio.Task[None] | None = None
        self._disclosure: DraftDisclosureIntent | None = None
        self._proof: Confirmation | None = None
        self._editor: FrozenDraftSource | None = None

    @property
    def operation_count(self) -> int:
        return len(self._tasks) + int(
            self._draft_closing is not None and not self._draft_closing.done()
        )

    def _require(self, generation: int | None = None, *, mutate: bool = False) -> None:
        self.policy.require(Action.MUTATE if mutate else Action.READ)
        if self._closed or (generation is not None and generation != self._generation):
            raise AppError("Creation draft changed or closed; capture a fresh source.")

    async def _operate[T](self, operation: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(operation)
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        except OSError:
            raise AppError("Creation source operation failed; private details withheld.") from None
        finally:
            self._tasks.discard(task)

    async def _worker[T](self, operation: Callable[[threading.Event], T]) -> T:
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(operation, cancel))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise

    def invalidate(self) -> None:
        self._generation += 1
        self.current_source = None
        self._require_origin = None
        self._disclosure = self._proof = None

    async def capture_bytes(
        self,
        data: bytes,
        kind: DraftSourceKind,
        title: str,
        *,
        require_origin: Callable[[], Awaitable[None]] | None = None,
    ) -> FrozenDraftSource:
        return await self._operate(self._capture(data, kind, title, require_origin))

    async def _capture(
        self,
        data: bytes,
        kind: DraftSourceKind,
        title: str,
        require_origin: Callable[[], Awaitable[None]] | None,
    ) -> FrozenDraftSource:
        self._require()
        self.invalidate()
        generation = self._generation
        await self.close_draft()
        if require_origin is not None:
            await require_origin()
        source = await file_worker(lambda: self._freeze(data, kind, title, generation))
        if require_origin is not None:
            await require_origin()
        self._require(generation)
        self._require_origin, self.current_source = require_origin, source
        return source

    def _freeze(
        self, data: bytes, kind: DraftSourceKind, title: str, generation: int
    ) -> FrozenDraftSource:
        if kind not in {"template", "clipboard", "paste", "file"}:
            raise AppError("Choose an explicit template, file, clipboard or paste source.")
        documents = manifest_documents(data, source_path="creation draft")
        rendered = b"\n".join(item.body for item in documents)
        return FrozenDraftSource(
            identity=uuid4(),
            kind=kind,
            title=title,
            generation=generation,
            documents=documents,
            source_sha256=hashlib.sha256(data).hexdigest(),
            rendered_sha256=hashlib.sha256(rendered).hexdigest(),
            body=data,
        )

    async def capture_file(self, path: Path) -> FrozenDraftSource:
        return await self._operate(self._capture_file(path))

    async def _capture_file(self, path: Path) -> FrozenDraftSource:
        self._require()
        self.invalidate()
        generation = self._generation
        files = ManifestFiles(cwd=self.directory)
        selected = path.expanduser()
        selected = selected if selected.is_absolute() else self.directory / selected
        root = await self._worker(lambda cancel: files.root(selected.parent, cancel=cancel))
        snapshot = await self._worker(lambda cancel: files.read(root, selected.name, cancel=cancel))
        self._require(generation)

        async def current() -> None:
            await self._worker(
                lambda cancel: files.require_unchanged(root, (snapshot,), cancel=cancel)
            )

        return await self._capture(snapshot.data, "file", selected.name, current)

    async def capture_template(
        self,
        entry: TemplateCatalogEntry,
        values: Mapping[str, object],
        catalog: TemplateCatalogService,
    ) -> FrozenDraftSource:
        return await self._operate(self._capture_template(entry, values, catalog))

    async def _capture_template(
        self,
        entry: TemplateCatalogEntry,
        values: Mapping[str, object],
        catalog: TemplateCatalogService,
    ) -> FrozenDraftSource:
        from kuberich.domain.resource_templates import render_resource_template

        self._require()
        await catalog.require_current(entry)
        template = entry.template
        if template is None or not entry.enabled:
            raise AppError("Choose an available unambiguous resource template.")
        data = await file_worker(lambda: render_resource_template(template, values))
        return await self._capture(
            data, "template", template.title, lambda: catalog.require_current(entry)
        )

    async def require_source(self, source: FrozenDraftSource) -> None:
        await self._operate(self._require_source(source))

    async def _require_source(self, source: FrozenDraftSource) -> None:
        self._require(source.generation)
        if self.current_source is not source:
            raise AppError("Creation source review is obsolete; capture it again.")
        current = self._require_origin
        if current is not None:
            await current()
        self._require(source.generation)
        if self.current_source is not source:
            raise AppError("Creation source review is obsolete; capture it again.")

    async def prepare_editor(self) -> DraftDisclosureIntent:
        return await self._operate(self._prepare_editor())

    async def _prepare_editor(self) -> DraftDisclosureIntent:
        self._require(mutate=True)
        self._disclosure = self._proof = None
        source = self.current_source
        if source is None:
            raise AppError("Capture a valid creation draft before editing.")
        await self._require_source(source)
        self._require(source.generation, mutate=True)
        intent = DraftDisclosureIntent(identity=uuid4(), source=source)
        self._disclosure = intent
        return intent

    def confirm_disclosure(self, intent: DraftDisclosureIntent) -> Confirmation:
        self._require(mutate=True)
        if intent is not self._disclosure or intent.source is not self.current_source:
            raise AppError("Review a fresh exact creation editor disclosure first.")
        proof = Confirmation(intent.identity, uuid4())
        self._proof = proof
        return proof

    def open_editor(self, approval: Confirmation) -> Coroutine[Any, Any, ProcessCommand]:
        intent, proof = self._disclosure, self._proof
        self._disclosure = self._proof = None
        self._require(mutate=True)
        if intent is None or proof is not approval or approval.intent != intent.identity:
            raise AppError("Creation editor disclosure is invalid or already consumed.")
        return self._operate(self._open_editor(intent))

    async def _open_editor(self, intent: DraftDisclosureIntent) -> ProcessCommand:
        await self.close_draft()
        await self._require_source(intent.source)
        self._require(intent.source.generation, mutate=True)
        draft = await file_worker(
            lambda: ManifestFile(intent.source.body), discard=lambda value: value.close()
        )
        self._draft, self._editor = draft, intent.source
        self.require_editor_current()
        return editor_command(
            editor_arguments(self.environment),
            draft.path,
            environment=self.environment,
            directory=self.directory,
        )

    def require_editor_current(self) -> None:
        source = self._editor
        self._require(source.generation if source is not None else -1, mutate=True)
        if self.current_source is not source:
            raise AppError("Creation editor source changed; discard this draft.")

    async def finish_editor(self, *, succeeded: bool) -> FrozenDraftSource | None:
        return await self._operate(self._finish_editor(succeeded))

    async def _finish_editor(self, succeeded: bool) -> FrozenDraftSource | None:
        try:
            self.require_editor_current()
            if not succeeded:
                return None
            draft, original = self._draft, self._editor
            assert draft is not None and original is not None
            data = await file_worker(draft.read)
            await self._require_source(original)
            self.require_editor_current()
            if data == original.body:
                return None
            generation = self._generation + 1
            source = await file_worker(
                lambda: self._freeze(data, original.kind, original.title, generation)
            )
            await self._require_source(original)
            self.require_editor_current()
            self._generation = generation
            self.current_source = source
            self._disclosure = self._proof = None
            return source
        finally:
            await self.close_draft()

    async def close_draft(self) -> None:
        self._editor = None
        if self._draft_closing is None:
            draft = self._draft
            if draft is None:
                return

            async def cleanup() -> None:
                try:
                    await file_worker(draft.close)
                except OSError:
                    raise AppError(
                        "Private creation editor cleanup could not be confirmed."
                    ) from None
                self._draft = None

            self._draft_closing = asyncio.create_task(cleanup())
        closing = self._draft_closing
        try:
            await finish_owned(closing)
        finally:
            self._draft_closing = None

    async def _shutdown(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        await self.close_draft()

    async def close(self) -> None:
        if self._closing is None or (
            self._closing.done()
            and not self._closing.cancelled()
            and self._closing.exception() is not None
        ):
            self._closed = True
            self.invalidate()
            self._closing = asyncio.create_task(self._shutdown())
        await finish_owned(self._closing)
