"""Incremental manifest projection off the terminal event loop, with owned completion."""

import asyncio

from kubetrol.domain.pods import PodRow, pod_row
from kubetrol.domain.resources import ResourceRecord, ResourceSnapshot


class PodProjection:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[ResourceRecord, PodRow]] = {}

    def _project(self, snapshot: ResourceSnapshot) -> tuple[PodRow, ...]:
        cache: dict[str, tuple[ResourceRecord, PodRow]] = {}
        for record in snapshot.items:
            previous = self._cache.get(record.uid or "")
            row = previous[1] if previous is not None and previous[0] is record else pod_row(record)
            cache[row.uid] = (record, row)
        self._cache = cache
        return tuple(value[1] for value in cache.values())

    async def project(self, snapshot: ResourceSnapshot | None) -> tuple[PodRow, ...]:
        if snapshot is None or snapshot.resource.group or snapshot.resource.name != "pods":
            self._cache.clear()
            return ()
        worker = asyncio.create_task(asyncio.to_thread(self._project, snapshot))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Cancelling an await cannot kill a decoding thread. Drain the owned
            # job before another projection or exit can reuse its cache.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            # Retrieve a decoding failure; a cancelled future likewise propagates
            # cancellation, so both states preserve the caller's cancellation.
            worker.exception()
            raise
