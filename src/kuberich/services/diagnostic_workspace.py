"""One owned diagnostic producer and one combined, bounded immutable publication."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Literal

from kuberich.domain.cluster_diagnostics import (
    MAX_DIAGNOSTIC_FINDINGS,
    MAX_DIAGNOSTIC_TEXT_BYTES,
    SOURCE_TEXT_RESERVE,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
    bounded_diagnostic_snapshot,
    diagnostic_key,
    diagnostic_text_bytes,
)
from kuberich.domain.resources import CollectionState
from kuberich.errors import AppError

type DiagnosticCollect = Callable[
    [DiagnosticRequest, Callable[[DiagnosticSnapshot], None]], Awaitable[DiagnosticSnapshot]
]


def _incomplete(
    snapshot: DiagnosticSnapshot, kind: DiagnosticSourceKind = DiagnosticSourceKind.CONDITION
) -> DiagnosticSnapshot:
    if snapshot.collecting and not any(
        source.status is DiagnosticStatus.LOADING for source in snapshot.sources
    ):
        snapshot = replace(
            snapshot,
            sources=(
                *snapshot.sources,
                DiagnosticSource(
                    diagnostic_key("cancelled", kind, snapshot.request.revision),
                    kind,
                    None,
                    snapshot.request.scope.namespace,
                    DiagnosticStatus.LOADING,
                    None,
                    None,
                    None,
                    "Producer interrupted after the retained source observations.",
                ),
            ),
        )
    return replace(
        snapshot,
        collecting=False,
        sources=tuple(
            replace(
                source,
                status=DiagnosticStatus.CANCELLED,
                collection=CollectionState(
                    False,
                    True,
                    source.collection.pages if source.collection is not None else 0,
                    source.collection.retained_bytes if source.collection is not None else 0,
                ),
                detail=source.detail + " Collection cancelled; evidence is incomplete.",
            )
            if source.status is DiagnosticStatus.LOADING
            else source
            for source in snapshot.sources
        ),
    )


class DiagnosticWorkspace:
    """Preparation invalidates callbacks synchronously; stop drains before start."""

    def __init__(self) -> None:
        self.request: DiagnosticRequest | None = None
        self.task: asyncio.Task[None] | None = None
        self._revision = 0
        self._snapshot: DiagnosticSnapshot | None = None
        self._carried: DiagnosticSnapshot | None = None
        self._producer: Literal["native", "popeye"] = "native"

    @property
    def snapshot(self) -> DiagnosticSnapshot | None:
        return self._snapshot

    @property
    def collecting(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def remaining_source_text_bytes(self) -> int:
        return SOURCE_TEXT_RESERVE // 2

    @property
    def remaining_findings(self) -> int:
        return MAX_DIAGNOSTIC_FINDINGS - len(self._carried.findings if self._carried else ())

    @property
    def remaining_text_bytes(self) -> int:
        if self._snapshot is None:
            return MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE
        carried = diagnostic_text_bytes(self._carried.findings) if self._carried else 0
        return max(0, MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE - carried)

    def _cancel_task(self) -> None:
        if self.task is not None and not self.task.done() and not self.task.cancelling():
            self.task.cancel()

    def prepare(
        self, scope: DiagnosticScope, producer: Literal["native", "popeye"] = "native"
    ) -> DiagnosticRequest:
        if producer not in {"native", "popeye"}:
            raise AppError("Unknown diagnostic producer.")
        previous, previous_producer = self._snapshot, self._producer
        self.invalidate()
        self._revision += 1
        request = DiagnosticRequest(scope, self._revision)
        self.request, self._producer = request, producer
        self._carried = None
        if producer == "popeye" and previous is not None and previous.request.scope == scope:
            previous = _incomplete(
                previous,
                DiagnosticSourceKind.POPEYE
                if previous_producer == "popeye"
                else DiagnosticSourceKind.CONDITION,
            )
            self._carried = replace(
                previous,
                request=request,
                findings=tuple(
                    f for f in previous.findings if f.source is not DiagnosticSourceKind.POPEYE
                ),
                sources=tuple(
                    s for s in previous.sources if s.kind is not DiagnosticSourceKind.POPEYE
                ),
            )
        self._snapshot = self._carried or DiagnosticSnapshot(request, (), (), False, 0, None)
        return request

    def invalidate(self) -> None:
        self.request = None
        self._cancel_task()

    async def stop(self) -> None:
        task = self.task
        if task is None:
            return
        self._cancel_task()
        completion = asyncio.gather(task, return_exceptions=True)
        cancelled = False
        try:
            while not completion.done():
                try:
                    await asyncio.shield(completion)
                except asyncio.CancelledError:
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        finally:
            self.task = None

    async def cancel(self) -> DiagnosticSnapshot | None:
        """Invalidate, drain and return retained evidence under a new idle request.

        The caller binds/publishes the returned request and snapshot. Old producer
        callbacks remain invalid even if they suppress cancellation. Scope departure
        uses invalidate/stop instead and cannot republish retained evidence.
        """
        previous, request, revision = self._snapshot, self.request, self._revision
        if previous is not None and self.collecting:
            previous = replace(previous, collecting=True)
        self.invalidate()
        await self.stop()
        if (
            previous is None
            or request is None
            or self.request is not None
            or revision != self._revision
        ):
            return None
        self._revision += 1
        self.request = DiagnosticRequest(request.scope, self._revision)
        self._snapshot = bounded_diagnostic_snapshot(
            replace(
                _incomplete(
                    previous,
                    DiagnosticSourceKind.POPEYE
                    if self._producer == "popeye"
                    else DiagnosticSourceKind.CONDITION,
                ),
                request=self.request,
            )
        )
        return self._snapshot

    def start(
        self,
        request: DiagnosticRequest,
        collect: DiagnosticCollect,
        publish: Callable[[DiagnosticSnapshot], None],
    ) -> None:
        if self.task is not None:
            raise AppError("Drain the previous diagnostic producer before starting another.")
        if request != self.request:
            raise AppError("Diagnostic request is stale.")

        def receive(snapshot: DiagnosticSnapshot) -> None:
            if request != self.request or snapshot.request != request:
                return
            if self._carried is not None:
                snapshot = replace(
                    snapshot,
                    findings=(*self._carried.findings, *snapshot.findings),
                    sources=(*self._carried.sources, *snapshot.sources),
                    native_requests_used=self._carried.native_requests_used,
                )
            self._snapshot = bounded_diagnostic_snapshot(snapshot)
            publish(self._snapshot)

        async def run() -> None:
            receive(await collect(request, receive))

        self.task = asyncio.create_task(run(), name="kuberich-diagnostic-" + self._producer)
