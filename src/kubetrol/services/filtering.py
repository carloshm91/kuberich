"""Local pod filtering with a total regex time budget and owned worker cleanup."""

import asyncio
import time
from dataclasses import dataclass

import regex

from kubetrol.domain.pods import PodRow

REGEX_SECONDS = 0.05


@dataclass(frozen=True)
class FilterResult:
    rows: tuple[PodRow, ...]
    problem: str | None = None


def search_text(row: PodRow) -> str:
    return f"{row.namespace} {row.name} {row.ready}/{row.containers} {row.status} {row.restarts}"


def filter_rows(rows: tuple[PodRow, ...], query: str) -> FilterResult:
    if not query:
        return FilterResult(rows)
    if len(query) > 256:
        return FilterResult(rows, "Filter is too long. Showing all pods.")
    if not query.startswith("re:"):
        needle = query.casefold()
        return FilterResult(tuple(row for row in rows if needle in search_text(row).casefold()))
    deadline = time.monotonic() + REGEX_SECONDS
    try:
        pattern = regex.compile(query[3:], regex.IGNORECASE | regex.VERSION1)
    except regex.error:
        return FilterResult(rows, "Invalid regex. Showing all pods; correct re: or use plain text.")
    matches: list[PodRow] = []
    try:
        for row in rows:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if pattern.search(search_text(row), timeout=remaining, concurrent=True) is not None:
                matches.append(row)
    except TimeoutError:
        return FilterResult(
            rows, "Regex exceeded its time budget. Showing all pods; simplify the pattern."
        )
    return FilterResult(tuple(matches))


async def apply_filter(rows: tuple[PodRow, ...], query: str) -> FilterResult:
    if not query:
        return FilterResult(rows)
    worker = asyncio.create_task(asyncio.to_thread(filter_rows, rows, query))
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
