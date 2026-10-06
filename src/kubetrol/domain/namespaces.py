"""Namespace table values preserve real UID identity and explicit lifecycle state."""

from dataclasses import dataclass
from datetime import datetime

from kubetrol.domain.pods import age
from kubetrol.domain.resources import ResourceRecord, resource_object
from kubetrol.errors import AppError


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
