"""Incremental manifest projection off the terminal event loop, with owned completion."""

import asyncio
from collections.abc import Callable

from kubetrol.domain.namespaces import NamespaceRow, namespace_row
from kubetrol.domain.pods import PodRow, pod_row
from kubetrol.domain.registry import ResourceDefinition, ResourceRow, resource_row
from kubetrol.domain.resources import ResourceRecord, ResourceSnapshot


class ResourceProjection[T: PodRow | NamespaceRow | ResourceRow]:
    def __init__(
        self, resource: str, project: Callable[[ResourceRecord], T], group: str = ""
    ) -> None:
        self._resource, self._project_record = resource, project
        self._group = group
        self._cache: dict[str, tuple[ResourceRecord, T]] = {}

    def _project(self, snapshot: ResourceSnapshot) -> tuple[T, ...]:
        cache: dict[str, tuple[ResourceRecord, T]] = {}
        for record in snapshot.items:
            previous = self._cache.get(record.uid or "")
            row = (
                previous[1]
                if previous is not None and previous[0] is record
                else self._project_record(record)
            )
            cache[row.uid] = (record, row)
        self._cache = cache
        return tuple(value[1] for value in cache.values())

    async def project(self, snapshot: ResourceSnapshot | None) -> tuple[T, ...]:
        if (
            snapshot is None
            or snapshot.resource.group != self._group
            or snapshot.resource.name != self._resource
        ):
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


class PodProjection(ResourceProjection[PodRow]):
    def __init__(self) -> None:
        super().__init__("pods", pod_row)


class NamespaceProjection(ResourceProjection[NamespaceRow]):
    def __init__(self) -> None:
        super().__init__("namespaces", namespace_row)


class StandardProjection(ResourceProjection[ResourceRow]):
    def __init__(self, definition: ResourceDefinition) -> None:
        super().__init__(
            definition.name, lambda record: resource_row(record, definition), definition.group
        )
