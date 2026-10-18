"""Owned, time-bounded local metadata and observable-failure projection."""

import asyncio
import threading
import time
from dataclasses import dataclass

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.navigation import ContextRow
from kuberich.domain.pods import PodRow
from kuberich.domain.registry import ResourceRow
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.selectors import metadata_fields, object_fields, selectors, unhealthy
from kuberich.errors import AppError
from kuberich.services.filtering import FilterResult, apply_filter, filter_rows
from kuberich.services.processes import _finish_owned

METADATA_SECONDS = 0.25


def metadata_filter[T: PodRow | NamespaceRow | ContextRow | ResourceRow](
    rows: tuple[T, ...],
    records: tuple[ResourceRecord, ...],
    query: str,
    kind: str,
    errors: bool,
    cancelled: threading.Event,
) -> FilterResult[T]:
    deadline = time.monotonic() + METADATA_SECONDS
    mode, _, expression = query.partition(":")
    try:
        terms = selectors(expression, field=mode == "field") if mode in {"label", "field"} else ()
        if len(query) > 256:
            raise AppError("Filter is too long.")
        by_uid = {record.uid: record for record in records}
        result, unknown = [], 0
        for row in rows:
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise AppError("Metadata filter exceeded its time budget; simplify the filter.")
            record = by_uid.get(row.uid) if not isinstance(row, ContextRow) else None
            if record is None:
                raise AppError("Metadata filters require an API resource view.")
            manifest = record.manifest
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise AppError("Metadata filter exceeded its time budget; simplify the filter.")
            # A CRD may reuse a core plural. Built-in defaults/outcomes require
            # the actual API version and kind, not just its command/table name.
            known = {"pods": ("v1", "Pod"), "nodes": ("v1", "Node"), "jobs": ("batch/v1", "Job")}
            profile = (
                kind
                if known.get(kind) == (manifest.get("apiVersion"), manifest.get("kind"))
                else ""
            )
            if terms:
                fields = (
                    metadata_fields(manifest, profile)
                    if mode == "field"
                    else {
                        key: value
                        for key, value in object_fields(
                            object_fields(manifest.get("metadata")).get("labels")
                        ).items()
                        if isinstance(value, str)
                    }
                )
                if mode == "field" and any(
                    term.key not in set(fields) | {"metadata.name", "metadata.namespace"}
                    for term in terms
                ):
                    raise AppError("This local field is unavailable for the selected resource API.")
                if not all(term.matches(fields) for term in terms):
                    continue
            if errors:
                health = unhealthy(manifest, profile)
                unknown += health is None
                if health is not True:
                    continue
            result.append(row)
        filtered = filter_rows(tuple(result), "" if terms else query, kind)
        return FilterResult(filtered.rows, filtered.problem, unknown)
    except AppError as error:
        return FilterResult(rows, str(error) + f" Showing all {kind}.")


@dataclass
class MetadataFilter:
    """One held snapshot/query cache; ordinary filters never decode manifests."""

    _key: tuple[tuple[ResourceRecord, ...], tuple[int, str, str, bool]] | None = None
    _result: object = None
    _rows: tuple[object, ...] = ()

    async def apply[T: PodRow | NamespaceRow | ContextRow | ResourceRow](
        self,
        rows: tuple[T, ...],
        records: tuple[ResourceRecord, ...],
        query: str,
        kind: str,
        *,
        errors: bool = False,
    ) -> FilterResult[T]:
        if not errors and not query.startswith(("label:", "field:")):
            return await apply_filter(rows, query, kind)
        # Identity, not equality, avoids comparing/decoding large manifests.
        key = (id(records), query, kind, errors)
        if self._key is not None and self._key[0] is records and self._key[1] == key:
            from typing import cast

            cached = cast(FilterResult[T], self._result)
            if rows == self._rows:
                return cached
            # A new column projection may reuse the same API snapshot. Reuse
            # only its match identities, never stale displayed cell values.
            if cached.problem is not None:
                return FilterResult(rows, cached.problem, cached.unknown)
            uids = {row.uid for row in cached.rows if not isinstance(row, ContextRow)}
            return FilterResult(
                tuple(row for row in rows if not isinstance(row, ContextRow) and row.uid in uids),
                unknown=cached.unknown,
            )
        cancelled = threading.Event()
        worker = asyncio.create_task(
            asyncio.to_thread(metadata_filter, rows, records, query, kind, errors, cancelled)
        )
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled.set()
            await _finish_owned(asyncio.gather(worker, return_exceptions=True))
            raise
        self._key, self._result, self._rows = (records, key), result, rows
        return result
