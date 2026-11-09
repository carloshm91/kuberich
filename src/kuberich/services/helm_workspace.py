"""A generation-bound Helm collection with retained rows on read failure."""

import asyncio
from collections.abc import Awaitable, Callable

from kuberich.domain.helm import HelmList, HelmProblem, HelmRequest, HelmScope, HelmSnapshot
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned

type HelmCollect = Callable[[HelmRequest], Awaitable[HelmList]]


class HelmWorkspace:
    """Invalidate before draining; only the current producer can publish."""

    def __init__(self) -> None:
        self.request: HelmRequest | None = None
        self.task: asyncio.Task[None] | None = None
        self._generation = 0
        self._snapshot: HelmSnapshot | None = None

    @property
    def snapshot(self) -> HelmSnapshot | None:
        return self._snapshot

    @property
    def collecting(self) -> bool:
        return self.task is not None and not self.task.done()

    def current(self, request: HelmRequest) -> bool:
        return self.request == request

    def prepare(self, scope: HelmScope) -> HelmRequest:
        previous = self._snapshot
        self.invalidate()
        self._generation += 1
        self.request = HelmRequest(scope, self._generation)
        listing = (
            previous.listing if previous is not None and previous.request.scope == scope else None
        )
        self._snapshot = HelmSnapshot(self.request, listing, False, None)
        return self.request

    def invalidate(self) -> None:
        self.request = None
        self._cancel_task()

    def _cancel_task(self) -> None:
        if self.task is not None and not self.task.done() and not self.task.cancelling():
            self.task.cancel()

    async def stop(self) -> None:
        task = self.task
        if task is None:
            return
        self._cancel_task()
        completion = asyncio.gather(task, return_exceptions=True)
        try:
            await asyncio.shield(completion)
        except asyncio.CancelledError:
            await finish_owned(completion)
            raise
        finally:
            if self.task is task:
                self.task = None

    def start(
        self,
        request: HelmRequest,
        collect: HelmCollect,
        publish: Callable[[HelmSnapshot], None],
    ) -> None:
        if self.task is not None:
            raise AppError("Drain the previous Helm collection before starting another.")
        if not self.current(request):
            raise AppError("Helm request is stale.")
        listing = self._snapshot.listing if self._snapshot is not None else None

        def receive(result: HelmList | None, collecting: bool, problem: HelmProblem | None) -> None:
            if self.current(request):
                self._snapshot = HelmSnapshot(request, result, collecting, problem)
                publish(self._snapshot)

        async def run() -> None:
            try:
                result = await collect(request)
            except HelmProblem as problem:
                # Exception tracebacks can own process/parser frames with private output.
                receive(listing, False, HelmProblem(problem.kind, str(problem)))
            except AppError:
                receive(
                    listing, False, HelmProblem("unavailable", "Helm collection failed; retry.")
                )
            else:
                receive(result, False, None)

        receive(listing, True, None)
        self.task = asyncio.create_task(run(), name="kuberich-helm-list")
