"""An owned local draft whose exact conditional intent must pass server dry-run."""

import asyncio
from dataclasses import replace
from pathlib import Path

from kubetrol.adapters.editing import ManifestFile, file_worker
from kubetrol.adapters.mutations import conditional_patch
from kubetrol.domain.connections import ConnectionProblem, HttpProblem
from kubetrol.domain.editing import edit_preview, edited_intent, editor_arguments, manifest_text
from kubetrol.domain.mutations import MutationIntent, MutationResult, MutationState
from kubetrol.domain.processes import ProcessCommand, editor_command
from kubetrol.domain.resources import ResourceRecord
from kubetrol.errors import AppError, ExitCode
from kubetrol.services.mutations import Confirmation, MutationService
from kubetrol.services.processes import _finish_owned


class EditingService(MutationService):
    file: ManifestFile | None = None
    snapshot: ResourceRecord | None = None
    validated: MutationIntent | None = None
    _file_closing: asyncio.Task[None] | None = None

    async def open(self) -> ManifestFile:
        self.require_current()
        if self.resource.kind == "Secret":
            raise AppError("Secret editing is unavailable in this preview.")
        if self.file is None:
            if self._file_closing is not None and not self._file_closing.done():
                raise AppError("The previous edit draft is still closing.")
            self._file_closing = None
            self.snapshot = await self._read()
            snapshot = self.snapshot
            data = await file_worker(lambda: manifest_text(snapshot, self.target))
            self.require_current()
            try:
                self.file = await file_worker(
                    lambda: ManifestFile(data), discard=lambda f: f.close()
                )
            except OSError:
                raise AppError(
                    "Cannot create the private editor file.", ExitCode.LOCAL_IO
                ) from None
            # Ownership is recorded before checking a changed context.
            self.require_current()
        return self.file

    def command(self, environment: dict[str, str], directory: Path) -> ProcessCommand:
        self.require_current()
        if self.file is None:
            raise AppError("Open an owned edit draft first.")
        self.intent = self.validated = None
        self._confirmation = self._approved_intent = None
        return replace(
            editor_command(
                editor_arguments(environment),
                self.file.path,
                environment=environment,
                directory=directory,
            ),
            target=self.target,
        )

    async def prepare(self) -> tuple[MutationIntent | None, str]:
        self.require_current()
        self.intent = self.validated = None
        self._confirmation = self._approved_intent = None
        if self.file is None or self.snapshot is None:
            raise AppError("Open an owned edit draft first.")
        snapshot = self.snapshot
        try:
            data = await file_worker(self.file.read)
            intent, preview = await file_worker(
                lambda: (
                    edited_intent(self.resource, self.target, snapshot, data),
                    edit_preview(snapshot, data),
                )
            )
        except OSError:
            raise AppError("Cannot read the private editor output.", ExitCode.LOCAL_IO) from None
        self.require_current()
        self.intent = intent
        return intent, preview

    async def validate(self) -> MutationResult:
        self.validated = None
        self._confirmation = self._approved_intent = None
        intent = self.intent
        if intent is None:
            return MutationResult(MutationState.BLOCKED, "Review a changed manifest first.")
        try:
            self.require_current()
            record = await self._read()
            if record.resource_version != intent.resource_version:
                return MutationResult(
                    MutationState.CONFLICT,
                    "Object changed while editing. Close and open a fresh edit; no apply was sent.",
                )
            result = await conditional_patch(
                self.client, intent, self.require_current, dry_run=True
            )
            self.require_current()
            if result.state is MutationState.SUCCEEDED and self.intent is intent:
                self.validated = intent
            return result
        except asyncio.CancelledError:
            return MutationResult(
                MutationState.CANCELLED, "Validation cancelled; no apply was sent."
            )
        except HttpProblem as error:
            return MutationResult(
                MutationState.DENIED if error.status == 403 else MutationState.REJECTED,
                "Target revalidation was refused; no apply was sent.",
            )
        except ConnectionProblem:
            return MutationResult(MutationState.UNREACHABLE, "Revalidation failed; no apply sent.")
        except AppError:
            return MutationResult(MutationState.STALE, "Target/policy changed; no apply was sent.")

    def confirm(self, intent: MutationIntent) -> Confirmation:
        if intent is not self.validated:
            raise AppError("This exact edit must pass server dry-run before confirmation.")
        return super().confirm(intent)

    async def execute(self, confirmation: Confirmation) -> MutationResult:
        if self.intent is None or self.intent is not self.validated:
            return MutationResult(
                MutationState.BLOCKED, "This edit needs a fresh server validation."
            )
        result = await super().execute(confirmation)
        self.validated = None
        return result

    async def close_file(self) -> None:
        if self._file_closing is None:
            owned, self.file = self.file, None
            if owned is None:
                return

            async def cleanup() -> None:
                try:
                    await file_worker(owned.close)
                except OSError:
                    raise AppError(
                        "Private editor cleanup could not be confirmed.", ExitCode.LOCAL_IO
                    ) from None

            self._file_closing = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(self._file_closing)
        except asyncio.CancelledError:
            await _finish_owned(self._file_closing)
            raise
