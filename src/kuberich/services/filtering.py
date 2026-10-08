"""Local pod filtering with a total regex time budget and owned worker cleanup."""

import asyncio
import time
from dataclasses import dataclass

import regex

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.navigation import ContextRow
from kuberich.domain.pods import PodRow
from kuberich.domain.registry import ResourceRow

REGEX_SECONDS = 0.05


@dataclass(frozen=True)
class FilterResult[T: PodRow | NamespaceRow | ContextRow | ResourceRow]:
    rows: tuple[T, ...]
    problem: str | None = None


def search_text(row: PodRow | NamespaceRow | ContextRow | ResourceRow) -> str:
    if isinstance(row, ResourceRow):
        return " ".join(value.text for value in row.values[:-1])
    if isinstance(row, ContextRow):
        return " ".join(row.cells()[1:])
    if isinstance(row, NamespaceRow):
        return f"{row.name} {row.status}"
    return f"{row.namespace} {row.name} {row.ready}/{row.containers} {row.status} {row.restarts}"


def filter_rows[T: PodRow | NamespaceRow | ContextRow | ResourceRow](
    rows: tuple[T, ...], query: str, kind: str = "pods"
) -> FilterResult[T]:
    if not query:
        return FilterResult(rows)
    if len(query) > 256:
        return FilterResult(rows, f"Filter is too long. Showing all {kind}.")
    if not query.startswith("re:"):
        needle = query.casefold()
        return FilterResult(tuple(row for row in rows if needle in search_text(row).casefold()))
    deadline = time.monotonic() + REGEX_SECONDS
    try:
        pattern = regex.compile(query[3:], regex.IGNORECASE | regex.VERSION1)
    except regex.error:
        return FilterResult(
            rows, f"Invalid regex. Showing all {kind}; correct re: or use plain text."
        )
    matches: list[T] = []
    try:
        for row in rows:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if pattern.search(search_text(row), timeout=remaining, concurrent=True) is not None:
                matches.append(row)
    except TimeoutError:
        return FilterResult(
            rows, f"Regex exceeded its time budget. Showing all {kind}; simplify the pattern."
        )
    return FilterResult(tuple(matches))


async def apply_filter[T: PodRow | NamespaceRow | ContextRow | ResourceRow](
    rows: tuple[T, ...], query: str, kind: str = "pods"
) -> FilterResult[T]:
    if not query:
        return FilterResult(rows)
    worker = asyncio.create_task(
        asyncio.to_thread(filter_rows, rows, query)
        if kind == "pods"
        else asyncio.to_thread(filter_rows, rows, query, kind)
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        worker.exception()
        raise
