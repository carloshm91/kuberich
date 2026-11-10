"""Owned local roots, frozen sources, one-use editor disclosure and local saves."""

import asyncio
import hashlib
import threading
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from kuberich.adapters.editing import ManifestFile, file_worker
from kuberich.adapters.kustomize import KustomizeRenderer
from kuberich.adapters.manifest_files import ManifestFiles
from kuberich.domain.editing import editor_arguments, parse_manifest_documents
from kuberich.domain.exports import DirectoryRef, FileOutcome
from kuberich.domain.kustomize import KUSTOMIZATION_NAMES
from kuberich.domain.manifests import (
    MAX_MANIFEST_BYTES,
    MAX_MANIFEST_RESOURCES,
    FrozenManifestSource,
    ManifestDisclosureIntent,
    ManifestDocument,
    ManifestListing,
    ManifestSaveIntent,
    ManifestSourceKind,
    manifest_config_preview,
    manifest_documents,
    manifest_preview,
    manifest_source_digest,
)
from kuberich.domain.processes import ProcessCommand, editor_command
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation
from kuberich.services.ownership import finish_owned


class LocalManifestService:
    def __init__(
        self,
        policy: AccessPolicy,
        environment: Mapping[str, str],
        directory: Path,
        *,
        files: ManifestFiles | None = None,
        renderer: KustomizeRenderer | None = None,
    ) -> None:
        self.policy, self.environment, self.directory = (
            policy,
            dict(environment),
            directory.absolute(),
        )
        self.files = files if files is not None else ManifestFiles(cwd=self.directory)
        self.renderer = (
            renderer
            if renderer is not None
            else KustomizeRenderer(policy, environment, self.directory)
        )
        self.root: DirectoryRef | None = None
        self.current_source: FrozenManifestSource | None = None
        self.last_file_outcome: FileOutcome | None = None
        self._generation = 0
        self._closed = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closing: asyncio.Task[None] | None = None
        self._draft: ManifestFile | None = None
        self._draft_closing: asyncio.Task[None] | None = None
        self._editor: ManifestDisclosureIntent | None = None
        self._editor_generation = -1
        self._disclosure: ManifestDisclosureIntent | None = None
        self._disclosure_approval: Confirmation | None = None
        self._save: ManifestSaveIntent | None = None
        self._save_approval: Confirmation | None = None

    @property
    def operation_count(self) -> int:
        return (
            len(self._tasks)
            + self.renderer.operation_count
            + int(self._draft_closing is not None and not self._draft_closing.done())
        )

    def _require(self, *, generation: int | None = None, mutate: bool = False) -> DirectoryRef:
        self.policy.require(Action.MUTATE if mutate else Action.READ)
        if (
            self._closed
            or self.root is None
            or (generation is not None and generation != self._generation)
        ):
            raise AppError("Local root/source changed or closed; open a fresh local review.")
        return self.root

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
            raise AppError(
                "Local manifest file operation failed; private details withheld."
            ) from None
        finally:
            self._tasks.discard(task)

    async def _worker[T](
        self,
        operation: Callable[[threading.Event], T],
        *,
        completed: Callable[[T], None] | None = None,
    ) -> T:
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(operation, cancel))
        try:
            result = await asyncio.shield(task)
            if completed is not None:
                completed(result)
            return result
        except asyncio.CancelledError:
            cancel.set()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            if completed is not None and not task.cancelled() and task.exception() is None:
                completed(task.result())
            raise

    def invalidate(self) -> None:
        self._generation += 1
        self.current_source = None
        self._disclosure = self._disclosure_approval = None
        self._save = self._save_approval = None

    async def open_root(self, path: Path) -> ManifestListing:
        return await self._operate(self._open_root(path))

    async def _open_root(self, path: Path) -> ManifestListing:
        self.policy.require(Action.READ)
        if self._closed:
            raise AppError("Local manifest browser is closed.")
        self.invalidate()
        self.root = None
        generation = self._generation
        await self.close_draft()
        root = await self._worker(lambda cancel: self.files.root(path, cancel=cancel))
        if self._closed or generation != self._generation:
            raise AppError("The requested local root is obsolete.")
        self.root = root
        return await self._list("")

    async def list(self, relative_directory: str) -> ManifestListing:
        return await self._operate(self._list(relative_directory))

    async def inspect_file(self, relative: str) -> tuple[str, ...]:
        return await self._operate(self._inspect_file(relative))

    async def _inspect_file(self, relative: str) -> tuple[str, ...]:
        root, generation = self._require(), self._generation
        snapshot = await self._worker(lambda cancel: self.files.read(root, relative, cancel=cancel))
        pages = await file_worker(lambda: self._file_preview(relative, snapshot.data))
        self._require(generation=generation)
        return pages

    def _file_preview(
        self, relative: str, data: bytes, before: bytes | None = None
    ) -> tuple[str, ...]:
        if Path(relative).name not in KUSTOMIZATION_NAMES:
            try:
                manifest_documents(data, source_path=relative)
            except AppError:
                pass
            else:
                try:
                    return manifest_preview(before, data)
                except AppError:
                    return manifest_preview(None, data)
        return (
            "Configuration structure only; scalar values and inline patches are hidden.\n",
            *manifest_config_preview(data),
        )

    async def _list(self, relative: str) -> ManifestListing:
        root, generation = self._require(), self._generation
        listing = await self._worker(lambda cancel: self.files.list(root, relative, cancel=cancel))
        self._require(generation=generation)
        return listing

    async def capture(self, relative: str, kind: ManifestSourceKind) -> FrozenManifestSource:
        return await self._operate(self._capture(relative, kind))

    async def _capture(self, relative: str, kind: ManifestSourceKind) -> FrozenManifestSource:
        root = self._require()
        self.invalidate()
        generation = self._generation
        files = await self._worker(
            lambda cancel: self.files.capture(root, relative, kind, cancel=cancel)
        )
        self._require(generation=generation)
        if kind == "kustomize":

            def current() -> None:
                self._require(generation=generation)

            rendered = await self.renderer.render(files, relative, guard=current)
            documents = await file_worker(
                lambda: manifest_documents(rendered, source_path=relative)
            )
        else:

            def parse() -> tuple[ManifestDocument, ...]:
                result: list[ManifestDocument] = []
                for item in files:
                    result.extend(manifest_documents(item.data, source_path=item.relative_path))
                    if len(result) > MAX_MANIFEST_RESOURCES:
                        raise AppError("Manifest source exceeds 100 resources; split the input.")
                return tuple(replace(item, ordinal=index) for index, item in enumerate(result, 1))

            documents = await file_worker(parse)
            rendered = b"\n".join(document.body for document in documents)
        await self._worker(lambda cancel: self.files.require_unchanged(root, files, cancel=cancel))
        self._require(generation=generation)
        source = FrozenManifestSource(
            identity=uuid4(),
            root=root,
            kind=kind,
            relative_path=relative,
            files=files,
            documents=documents,
            source_sha256=manifest_source_digest(files),
            rendered_sha256=hashlib.sha256(rendered).hexdigest(),
        )
        self.current_source = source
        return source

    async def require_source(self, source: FrozenManifestSource) -> None:
        await self._operate(self._require_source(source))

    async def _require_source(self, source: FrozenManifestSource) -> None:
        root, generation = self._require(), self._generation
        if self.current_source is not source or source.root != root:
            raise AppError("Manifest source review is obsolete; capture it again.")
        try:
            files = await self._worker(
                lambda cancel: self.files.capture(
                    root, source.relative_path, source.kind, cancel=cancel
                )
            )
        except AppError:
            if self.current_source is source and generation == self._generation:
                self.invalidate()
            raise
        self._require(generation=generation)
        if files != source.files or manifest_source_digest(files) != source.source_sha256:
            self.invalidate()
            raise AppError("Manifest source changed; refresh and validate a new review.")

    async def prepare_editor(self, relative: str) -> ManifestDisclosureIntent:
        return await self._operate(self._prepare_editor(relative))

    async def _prepare_editor(self, relative: str) -> ManifestDisclosureIntent:
        root, generation = self._require(mutate=True), self._generation
        self._disclosure = self._disclosure_approval = None
        snapshot = await self._worker(lambda cancel: self.files.read(root, relative, cancel=cancel))
        self._require(generation=generation, mutate=True)
        intent = ManifestDisclosureIntent(identity=uuid4(), source=snapshot, root=root)
        self._disclosure = intent
        return intent

    def confirm_disclosure(self, intent: ManifestDisclosureIntent) -> Confirmation:
        root = self._require(mutate=True)
        if intent is not self._disclosure or intent.root != root:
            raise AppError("Review a fresh exact editor disclosure first.")
        proof = Confirmation(intent.identity, uuid4())
        self._disclosure_approval = proof
        return proof

    async def open_editor(self, approval: Confirmation) -> ProcessCommand:
        # Consume synchronously, even if a forged attempt or cancellation follows.
        intent, proof = self._disclosure, self._disclosure_approval
        self._disclosure = self._disclosure_approval = None
        self._require(mutate=True)
        if intent is None or proof is not approval or approval.intent != intent.identity:
            raise AppError("Editor disclosure is invalid or already consumed.")
        return await self._operate(self._open_editor(intent))

    async def _open_editor(self, intent: ManifestDisclosureIntent) -> ProcessCommand:
        generation = self._generation
        await self.close_draft()
        await self._worker(
            lambda cancel: self.files.require_unchanged(
                intent.root, (intent.source,), cancel=cancel
            )
        )
        self._require(generation=generation, mutate=True)
        draft = await file_worker(
            lambda: ManifestFile(intent.source.data), discard=lambda value: value.close()
        )
        self._draft, self._editor, self._editor_generation = draft, intent, generation
        self.require_editor_current()
        return editor_command(
            editor_arguments(self.environment),
            draft.path,
            environment=self.environment,
            directory=self.directory,
        )

    def require_editor_current(self) -> None:
        # An absent or closing draft has generation -1; invalidation advances
        # the root generation, so this same guard rejects both states.
        self._require(generation=self._editor_generation, mutate=True)

    async def prepare_save(self) -> ManifestSaveIntent | None:
        return await self._operate(self._prepare_save())

    async def _prepare_save(self) -> ManifestSaveIntent | None:
        self.require_editor_current()
        self._save = self._save_approval = None
        draft, editor = self._draft, self._editor
        assert draft is not None and editor is not None
        data = await file_worker(draft.read)
        self.require_editor_current()
        if data == editor.source.data:
            return None

        def review() -> tuple[str, ...]:
            if not parse_manifest_documents(
                data, max_bytes=MAX_MANIFEST_BYTES, max_documents=MAX_MANIFEST_RESOURCES
            ):
                raise AppError("Edited source contains no YAML mappings.")
            return self._file_preview(editor.source.relative_path, data, editor.source.data)

        pages = await file_worker(review)
        self.require_editor_current()
        await self._worker(
            lambda cancel: self.files.require_unchanged(
                editor.root, (editor.source,), cancel=cancel
            )
        )
        intent = ManifestSaveIntent(
            identity=uuid4(),
            original=editor.source,
            root=editor.root,
            body=data,
            preview_pages=pages,
        )
        self._save = intent
        return intent

    def confirm_save(self, intent: ManifestSaveIntent) -> Confirmation:
        self.require_editor_current()
        if intent is not self._save:
            raise AppError("Review the exact current local save first.")
        proof = Confirmation(intent.identity, uuid4())
        self._save_approval = proof
        return proof

    async def save(self, approval: Confirmation) -> FileOutcome:
        intent, proof = self._save, self._save_approval
        self._save = self._save_approval = None
        self.require_editor_current()
        if intent is None or proof is not approval or approval.intent != intent.identity:
            raise AppError("Local save approval is invalid or already consumed.")
        return await self._operate(self._save_local(intent))

    async def _save_local(self, intent: ManifestSaveIntent) -> FileOutcome:
        self.require_editor_current()
        self.last_file_outcome = None

        def completed(outcome: FileOutcome) -> None:
            self.last_file_outcome = outcome

        try:
            return await self._worker(
                lambda cancel: self.files.save(intent, cancel=cancel), completed=completed
            )
        finally:
            if self.last_file_outcome is not None:
                self.invalidate()
                try:
                    await self.close_draft()
                except AppError:
                    self.last_file_outcome = replace(
                        self.last_file_outcome,
                        cleanup_complete=False,
                        notice="Local save outcome retained; private editor cleanup could not be confirmed.",
                    )
                    raise

    async def close_draft(self) -> None:
        self._editor = self._save = self._save_approval = None
        self._editor_generation = -1
        if self._draft_closing is None:
            draft = self._draft
            if draft is None:
                return

            async def cleanup() -> None:
                try:
                    await file_worker(draft.close)
                except OSError:
                    raise AppError("Private local editor cleanup could not be confirmed.") from None
                self._draft = None

            self._draft_closing = asyncio.create_task(cleanup())
        closing = self._draft_closing
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await finish_owned(closing)
            raise
        finally:
            # A failed cleanup retains the actual draft for an explicit retry.
            self._draft_closing = None

    async def _shutdown(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.renderer.close()
        await self.close_draft()
        self.root = None

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
