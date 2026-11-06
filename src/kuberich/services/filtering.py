"""Local pod filtering with a total regex time budget and owned worker cleanup."""

import asyncio
import time
from dataclasses import dataclass

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.authorization_rows import AuthorizationRow
from kuberich.domain.diagnostic_rows import DiagnosticRow
from kuberich.domain.events import EventGroupRow, EventObjectRow
from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.navigation import ContextRow
from kuberich.domain.pods import PodRow
from kuberich.domain.pulse import PulseRow
from kuberich.domain.registry import ResourceRow
from kuberich.domain.relationships import RelationshipRow

REGEX_SECONDS = 0.05


@dataclass(frozen=True)
class FilterResult[
    T: PodRow
    | NamespaceRow
    | ContextRow
    | ResourceRow
    | PulseRow
    | RelationshipRow
    | AuthorizationRow
    | DiagnosticRow
    | EventObjectRow
    | EventGroupRow
]:
    rows: tuple[T, ...]
    problem: str | None = None
    unknown: int = 0


def search_text(
    row: PodRow
    | NamespaceRow
    | ContextRow
    | ResourceRow
    | PulseRow
    | RelationshipRow
    | AuthorizationRow
    | DiagnosticRow
    | EventObjectRow
    | EventGroupRow,
) -> str:
    if isinstance(row, EventObjectRow):
        return " ".join(
            (
                row.fact.namespace,
                sanitize_text(row.fact.name),
                *(value.text for value in row.values),
            )
        )
    if isinstance(row, EventGroupRow):
        return " ".join((row.group.key.namespace, *(value.text for value in row.values)))
    if isinstance(row, DiagnosticRow):
        return " ".join(
            (
                row.severity,
                row.category,
                row.resource,
                row.container,
                row.summary,
                row.source,
                row.age,
                *row.details,
            )
        )
    if isinstance(row, AuthorizationRow):
        return " ".join((row.label, row.scope, row.status, *row.details))
    if isinstance(row, RelationshipRow):
        ref = row.ref
        return " ".join(
            (
                ref.api_version,
                ref.kind,
                ref.resource.name if ref.resource is not None else "",
                ref.namespace or "",
                ref.name,
                ref.uid or "",
                row.observed_uid or "",
                str(row.relation or ""),
                str(row.direction or ""),
                str(row.evidence or ""),
                row.status.value,
                *row.details,
            )
        )
    if isinstance(row, PulseRow):
        return f"{row.label} {row.detail} {row.source}"
    if isinstance(row, ResourceRow):
        return " ".join(value.text for value in row.values[:-1])
    if isinstance(row, ContextRow):
        return " ".join(row.cells()[1:])
    if isinstance(row, NamespaceRow):
        return f"{row.name} {row.status}"
    return f"{row.namespace} {row.name} {row.ready}/{row.containers} {row.status} {row.restarts}"


def filter_rows[
    T: PodRow
    | NamespaceRow
    | ContextRow
    | ResourceRow
    | PulseRow
    | RelationshipRow
    | AuthorizationRow
    | DiagnosticRow
    | EventObjectRow
    | EventGroupRow
](rows: tuple[T, ...], query: str, kind: str = "pods") -> FilterResult[T]:
    if not query:
        return FilterResult(rows)
    if len(query) > 256:
        return FilterResult(rows, f"Filter is too long. Showing all {kind}.")
    if query.startswith("fuzzy:"):
        needle = query[6:].casefold()

        def match(row: T) -> bool:
            letters = iter(search_text(row).casefold())
            return all(any(letter == wanted for letter in letters) for wanted in needle)

        deadline = time.monotonic() + REGEX_SECONDS
        fuzzy_matches: list[T] = []
        for row in rows:
            if time.monotonic() >= deadline:
                return FilterResult(
                    rows, f"Fuzzy filter exceeded its time budget. Showing all {kind}."
                )
            if match(row):
                fuzzy_matches.append(row)
        return FilterResult(tuple(fuzzy_matches))
    inverse = query.startswith("!re:")
    if inverse:
        query = query[1:]
    if not query.startswith("re:"):
        needle = query.casefold()
        return FilterResult(tuple(row for row in rows if needle in search_text(row).casefold()))
    import regex

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
            if (
                pattern.search(search_text(row), timeout=remaining, concurrent=True) is not None
            ) != inverse:
                matches.append(row)
    except TimeoutError:
        return FilterResult(
            rows, f"Regex exceeded its time budget. Showing all {kind}; simplify the pattern."
        )
    return FilterResult(tuple(matches))


async def apply_filter[
    T: PodRow
    | NamespaceRow
    | ContextRow
    | ResourceRow
    | PulseRow
    | RelationshipRow
    | AuthorizationRow
    | DiagnosticRow
    | EventObjectRow
    | EventGroupRow
](rows: tuple[T, ...], query: str, kind: str = "pods") -> FilterResult[T]:
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
