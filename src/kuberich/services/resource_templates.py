"""Lazy template catalogs with frozen identities and owned filesystem workers."""

import asyncio
import threading
from collections import Counter
from collections.abc import Callable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

from kuberich.adapters.resource_templates import TemplateFiles, TemplateFilesCapture
from kuberich.domain.resource_templates import (
    TemplateCatalogEntry,
    builtin_templates,
    parse_resource_template,
)
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned


class TemplateCatalogService:
    def __init__(self, config_path: Path, directory: Path) -> None:
        self.files = TemplateFiles(config_path, directory)
        self.entries: tuple[TemplateCatalogEntry, ...] = ()
        self.capture: TemplateFilesCapture | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._generation = 0
        self._closing: asyncio.Task[None] | None = None

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    async def _worker[T](self, operation: Callable[[threading.Event], T]) -> T:
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(operation, cancel))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise

    async def _operate[T](self, operation: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(operation)
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            self._tasks.discard(task)

    def _require(self, generation: int) -> None:
        if self._closed or generation != self._generation:
            raise AppError("Template catalog changed or closed; select a fresh template.")

    async def load(self) -> tuple[TemplateCatalogEntry, ...]:
        return await self._operate(self._load())

    async def _load(self) -> tuple[TemplateCatalogEntry, ...]:
        self._require(self._generation)
        self._generation += 1
        generation = self._generation
        self.entries, self.capture = (), None
        capture = await self._worker(lambda cancel: self.files.capture(cancel=cancel))

        def parse(cancel: threading.Event) -> tuple[TemplateCatalogEntry, ...]:
            entries: list[TemplateCatalogEntry] = []
            for template in builtin_templates():
                entries.append(
                    TemplateCatalogEntry(
                        origin="builtin",
                        relative_path="",
                        identity=(
                            "builtin",
                            template.id,
                            template.revision,
                            template.source_sha256,
                        ),
                        template=template,
                    )
                )
            for snapshot in capture.snapshots:
                if cancel.is_set():
                    raise AppError("Template catalog parsing cancelled.")
                try:
                    template = parse_resource_template(snapshot.data)
                except AppError:
                    entries.append(
                        TemplateCatalogEntry(
                            origin="user",
                            relative_path=snapshot.relative_path,
                            identity=("user", snapshot.relative_path, 0, snapshot.sha256),
                            template=None,
                            problem="Invalid bounded data-only resource template.",
                        )
                    )
                else:
                    entries.append(
                        TemplateCatalogEntry(
                            origin="user",
                            relative_path=snapshot.relative_path,
                            identity=("user", template.id, template.revision, snapshot.sha256),
                            template=template,
                        )
                    )
            for path in capture.unavailable:
                entries.append(
                    TemplateCatalogEntry(
                        origin="user",
                        relative_path=path,
                        identity=("user", path, 0, ""),
                        template=None,
                        problem="Template is not an unchanged ordinary file of at most 1 MiB.",
                    )
                )
            counts = Counter(
                (entry.identity[1], entry.identity[2])
                for entry in entries
                if entry.origin == "user" and entry.template is not None
            )
            return tuple(
                replace(
                    entry,
                    problem="Duplicate user template ID and revision; choose unique identities.",
                )
                if entry.origin == "user"
                and entry.template is not None
                and counts[(entry.identity[1], entry.identity[2])] > 1
                else entry
                for entry in entries
            )

        entries = await self._worker(parse)
        self._require(generation)
        self.capture, self.entries = capture, entries
        return entries

    async def require_current(self, entry: TemplateCatalogEntry) -> None:
        return await self._operate(self._require_current(entry))

    async def _require_current(self, entry: TemplateCatalogEntry) -> None:
        generation = self._generation
        self._require(generation)
        if not entry.enabled or not any(item is entry for item in self.entries):
            raise AppError("Select an enabled template from this current catalog.")
        if entry.origin == "user":
            capture = self.capture
            assert capture is not None
            await self._worker(lambda cancel: self.files.require_current(capture, cancel=cancel))
            self._require(generation)

    async def _close(self) -> None:
        self._closed = True
        self._generation += 1
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self.entries, self.capture = (), None

    async def close(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        await finish_owned(self._closing)
