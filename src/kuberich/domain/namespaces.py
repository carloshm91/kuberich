"""Namespace table values preserve real UID identity and explicit lifecycle state."""

from dataclasses import dataclass
from datetime import datetime

from kuberich.domain.pods import age
from kuberich.domain.resources import ResourceRecord, resource_object
from kuberich.errors import AppError


@dataclass(frozen=True)
class NamespaceRow:
    uid: str
    name: str
    status: str
    created_at: datetime | None

    def cells(self, now: datetime) -> tuple[str, ...]:
        return self.name, self.status, age(self.created_at, now)


def namespace_row(record: ResourceRecord) -> NamespaceRow:
    if record.uid is None:
        raise AppError("Namespace table requires Kubernetes UID identity.")
    status = resource_object(record.manifest.get("status")).get("phase")
    phase = status if isinstance(status, str) and status else "Unknown"
    if resource_object(record.manifest.get("metadata")).get("deletionTimestamp"):
        phase = "Terminating"
    return NamespaceRow(record.uid, record.name, phase, record.created_at)


def order_namespaces(
    rows: tuple[NamespaceRow, ...], column: str, descending: bool
) -> tuple[NamespaceRow, ...]:
    if column not in {"name", "status", "age"}:
        raise AppError("Unknown namespace sort field.")
    values: dict[str, str | float | None] = {
        row.uid: row.name.casefold()
        if column == "name"
        else row.status.casefold()
        if column == "status"
        else -row.created_at.timestamp()
        if row.created_at is not None
        else None
        for row in rows
    }
    present = sorted(
        (row for row in rows if values[row.uid] is not None),
        key=lambda row: (values[row.uid], row.name.casefold(), row.uid),
        reverse=descending,
    )
    missing = sorted(
        (row for row in rows if values[row.uid] is None),
        key=lambda row: (row.name.casefold(), row.uid),
    )
    return tuple((*present, *missing))
