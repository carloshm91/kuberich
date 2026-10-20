"""Select finished pods for an explicit, reviewed cleanup batch."""

from collections.abc import Iterable
from dataclasses import dataclass

from kuberich.domain.operations import MAX_BATCH
from kuberich.domain.resources import ResourceRecord

FINISHED_PHASES = frozenset({"Succeeded", "Failed"})


@dataclass(frozen=True)
class CleanupCandidate:
    uid: str
    namespace: str
    name: str
    state: str

    @property
    def label(self) -> str:
        return f"{self.namespace}/{self.name} · {self.state} · UID {self.uid}"


@dataclass(frozen=True)
class CleanupSelection:
    candidates: tuple[CleanupCandidate, ...]
    remaining: int = 0


def finished_pods(records: Iterable[ResourceRecord]) -> CleanupSelection:
    """Completed (Succeeded) and failed pods that are not already terminating.

    Ordering is deterministic. At most one delete batch is returned; the count of
    further candidates is reported so the user can run the cleanup again.
    """
    found: list[CleanupCandidate] = []
    for record in records:
        manifest = record.manifest
        metadata = manifest.get("metadata")
        status = manifest.get("status")
        if (
            record.uid is None
            or not isinstance(metadata, dict)
            or not isinstance(status, dict)
            or status.get("phase") not in FINISHED_PHASES
            or metadata.get("deletionTimestamp")
        ):
            continue
        reason = status.get("reason")
        if status["phase"] == "Succeeded":
            state = "Completed"
        elif isinstance(reason, str) and reason:
            state = f"Failed ({reason})"
        else:
            state = "Failed"
        found.append(CleanupCandidate(record.uid, record.namespace or "", record.name, state))
    found.sort(key=lambda candidate: (candidate.namespace, candidate.name, candidate.uid))
    return CleanupSelection(tuple(found[:MAX_BATCH]), max(0, len(found) - MAX_BATCH))
