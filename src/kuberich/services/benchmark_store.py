"""Owned local benchmark records; browsing never creates, prunes or connects."""

import asyncio
import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar

from platformdirs import user_state_path

from kuberich.adapters.artifact_files import ArtifactDirectoryMissing, ArtifactFiles
from kuberich.domain.benchmark_results import (
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    MAX_STORE_BYTES,
    RETENTION_DAYS,
    BenchmarkResult,
    decode_result,
    encode_result,
)
from kuberich.domain.exports import (
    ArtifactMetadata,
    ArtifactRef,
    DirectoryRef,
    ExportScope,
    PreparedArtifact,
)
from kuberich.errors import AppError, ExitCode

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SavedBenchmark:
    ref: ArtifactRef
    result: BenchmarkResult


def _refused() -> AppError:
    return AppError(
        "Benchmark storage is unsafe, changed or exceeds its limits; inspect the local directory.",
        ExitCode.LOCAL_IO,
    )


class BenchmarkStore:
    """Serialize this application's writers; refuse foreign or ambiguous entries.

    ArtifactFiles revalidates descriptors and named identities on each operation.
    A final named unlink/link is not an interprocess filesystem compare-and-swap.
    """

    def __init__(self, root: Path | None = None, *, files: ArtifactFiles | None = None) -> None:
        self._root = (
            root
            if root is not None
            else user_state_path("kuberich", appauthor=False) / "benchmarks"
        )
        self._files = files or ArtifactFiles()
        self._lock = asyncio.Lock()

    @property
    def default_root(self) -> Path:
        return self._root

    async def _work(self, operation: Callable[[threading.Event], _T]) -> _T:
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(operation, cancel))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            raise

    def _read(self, ref: ArtifactRef, cancel: threading.Event) -> SavedBenchmark:
        if (
            ref.directory.path != self._root
            or ref.identity.size > MAX_RECORD_BYTES
            or ref.identity.mode & 0o077
        ):
            raise _refused()
        data = self._files.read(ref, cancel=cancel)
        result = decode_result(data)
        if ref.name != str(result.run_id) + ".json":
            raise _refused()
        return SavedBenchmark(replace(ref, sha256=hashlib.sha256(data).hexdigest()), result)

    def _scan(self, root: DirectoryRef, cancel: threading.Event) -> tuple[SavedBenchmark, ...]:
        scanned = self._files.scan(root, cancel=cancel, max_entries=MAX_RECORDS + 1)
        if (
            scanned.limited
            or scanned.skipped
            or len(scanned.refs) > MAX_RECORDS
            or sum(ref.identity.size for ref in scanned.refs) > MAX_STORE_BYTES
        ):
            raise _refused()
        return tuple(
            sorted(
                (self._read(ref, cancel) for ref in scanned.refs),
                key=lambda saved: (saved.result.finished_at, saved.ref.name),
                reverse=True,
            )
        )

    async def scan(self) -> tuple[SavedBenchmark, ...]:
        def scan(cancel: threading.Event) -> tuple[SavedBenchmark, ...]:
            try:
                root = self._files.directory(self._root, create=False, cancel=cancel)
            except ArtifactDirectoryMissing:
                return ()
            return self._scan(root, cancel)

        async with self._lock:
            return await self._work(scan)

    async def read(self, ref: ArtifactRef) -> BenchmarkResult:
        async with self._lock:
            return (await self._work(lambda cancel: self._read(ref, cancel))).result

    async def save(self, result: BenchmarkResult) -> SavedBenchmark:
        def save(cancel: threading.Event) -> SavedBenchmark:
            data = encode_result(result)
            root = self._files.directory(self._root, create=True, cancel=cancel)
            records = self._scan(root, cancel)
            name = str(result.run_id) + ".json"
            if any(saved.ref.name == name for saved in records):
                raise _refused()
            cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
            retained = list(records)
            for saved in reversed(records):
                expired = saved.result.finished_at < cutoff
                full = (
                    len(retained) >= MAX_RECORDS
                    or sum(item.ref.identity.size for item in retained) + len(data)
                    > MAX_STORE_BYTES
                )
                if expired or full:
                    # Revalidate schema and immutable entry identity immediately before deletion.
                    self._read(saved.ref, cancel)
                    outcome = self._files.delete(saved.ref, cancel=cancel)
                    if (
                        not outcome.durable
                        or not outcome.cleanup_complete
                        or outcome.effect != "deleted"
                    ):
                        raise _refused()
                    retained.remove(saved)
            review = self._files.review(root, name, replace=False, cancel=cancel)
            # PreparedArtifact is only the adapter's byte/hash transaction carrier.
            # Its export metadata is neither persisted nor exposed as benchmark metadata.
            prepared = PreparedArtifact(
                id=result.run_id,
                metadata=ArtifactMetadata(
                    schema_version=1,
                    format="screen",
                    sensitive=False,
                    presentation=None,
                    notices=(),
                    scope=ExportScope(
                        export_at=None,
                        source_at=None,
                        context=None,
                        header_namespace=None,
                        collection_namespace=None,
                        namespace_mode="local",
                    ),
                ),
                payload=data,
                preview="",
                sha256=hashlib.sha256(data).hexdigest(),
            )
            outcome = self._files.publish(prepared, review, cancel=cancel)
            if (
                outcome.ref is None
                or outcome.effect != "published"
                or not outcome.durable
                or not outcome.cleanup_complete
            ):
                raise _refused()
            return SavedBenchmark(outcome.ref, decode_result(data))

        async with self._lock:
            return await self._work(save)

    async def delete(self, ref: ArtifactRef, *, confirmed: bool) -> None:
        if confirmed is not True:
            raise AppError("Confirm deletion of the exact saved benchmark record.")

        def delete(cancel: threading.Event) -> None:
            self._read(ref, cancel)
            outcome = self._files.delete(ref, cancel=cancel)
            if outcome.effect != "deleted" or not outcome.durable or not outcome.cleanup_complete:
                raise _refused()

        async with self._lock:
            await self._work(delete)
