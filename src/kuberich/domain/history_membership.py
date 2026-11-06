"""Current API membership is a projection, never a historical ownership claim."""

import hashlib
import json

from kuberich.domain.aggregate_logs import intermediate_resource, owned_by, workload_kind
from kuberich.domain.history import MAX_HISTORY_MEMBERS, MemberIdentity, MembershipEvidence
from kuberich.domain.resources import ApiResource, ResourceRecord, ResourceSnapshot
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError


def _controller(record: ResourceRecord) -> str | None:
    references = record.manifest.get("metadata", {}).get("ownerReferences", [])
    if not isinstance(references, list) or len(references) > 128:
        raise AppError("Invalid history membership owner references.")
    values = [
        entry["uid"]
        for entry in references
        if isinstance(entry, dict)
        and entry.get("controller") is True
        and isinstance(entry.get("uid"), str)
    ]
    if len(values) > 1:
        raise AppError("Ambiguous history membership controller references.")
    return values[0] if values else None


def current_members(
    target: ResourceTarget,
    resource: ApiResource,
    pods: ResourceSnapshot,
    intermediates: ResourceSnapshot | None,
    after: ResourceSnapshot,
) -> MembershipEvidence:
    """Recheck Pod UID and an exact controller chain within bounded API captures."""
    if (target.group, target.resource) != (resource.group, resource.name) or (
        pods.resource.group != ""
        or pods.resource.name != "pods"
        or after.resource != pods.resource
        or pods.namespace != target.namespace
        or after.namespace != target.namespace
    ):
        raise AppError("History membership captures do not match the selected scope.")
    kind = workload_kind(target)
    intermediate = intermediate_resource(target)
    complete = pods.collection.complete and after.collection.complete
    if len(pods.items) > MAX_HISTORY_MEMBERS or len(after.items) > MAX_HISTORY_MEMBERS:
        return MembershipEvidence("current-members", "unavailable", detail_code="member-limit")
    owners: dict[str, ResourceTarget] = {}
    if intermediate is not None:
        if intermediates is None:
            return MembershipEvidence(
                "current-members", "unavailable", detail_code="owners-missing"
            )
        if (
            intermediates.resource.group,
            intermediates.resource.name,
            intermediates.resource.kind,
        ) != (
            intermediate.group,
            intermediate.name,
            intermediate.kind,
        ) or intermediates.namespace != target.namespace:
            raise AppError("History intermediate capture does not match the selected workload.")
        if len(intermediates.items) > MAX_HISTORY_MEMBERS:
            return MembershipEvidence("current-members", "unavailable", detail_code="owner-limit")
        complete &= intermediates.collection.complete
        for record in intermediates.items:
            if record.uid is not None and owned_by(record, target, kind):
                owners[record.uid] = ResourceTarget(
                    target.session,
                    intermediate.group,
                    intermediate.name,
                    record.namespace,
                    record.name,
                    record.uid,
                )
    verified: dict[tuple[str | None, str], ResourceRecord | None] = {}
    for record in after.items:
        key = record.namespace, record.name
        if key in verified:
            complete = False
            verified[key] = None
        else:
            verified[key] = record
    members: list[MemberIdentity] = []
    seen: set[tuple[str | None, str]] = set()
    for pod in pods.items:
        key = pod.namespace, pod.name
        if key in seen:
            raise AppError("History membership contains duplicate Pod identities.")
        seen.add(key)
        rechecked = verified.get(key)
        if not pod.uid or rechecked is None or rechecked.uid != pod.uid:
            complete = False
            continue
        owner_uid = _controller(pod)
        if kind == "Pod":
            selected = pod.name == target.name and pod.uid == target.uid
        elif intermediate is not None:
            owner = owners.get(owner_uid or "")
            selected = owner is not None and owned_by(pod, owner, intermediate.kind)
            if (
                owner is not None
                and selected
                and (
                    _controller(rechecked) != owner_uid
                    or not owned_by(rechecked, owner, intermediate.kind)
                )
            ):
                complete = False
                selected = False
        else:
            selected = owner_uid == target.uid and owned_by(pod, target, kind)
            if selected and (
                _controller(rechecked) != owner_uid or not owned_by(rechecked, target, kind)
            ):
                complete = False
                selected = False
        if selected and pod.namespace == target.namespace:
            members.append(
                MemberIdentity(pod.namespace or "", pod.name, pod.uid, pod.created_at, owner_uid)
            )
    complete &= len(pods.items) == len(after.items)
    ordered = tuple(
        sorted(members, key=lambda member: (member.namespace, member.pod, member.uid or ""))
    )
    payload = [
        [
            member.namespace,
            member.pod,
            member.uid,
            member.created_at.isoformat() if member.created_at is not None else None,
            member.owner_uid,
        ]
        for member in ordered
    ]
    fingerprint = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    # Capture times belong to the service's clock; this deterministic function has no clock I/O.
    return MembershipEvidence(
        "current-members",
        "current-only" if complete else "partial",
        None,
        ordered,
        fingerprint,
        "current-members-projection",
    )
