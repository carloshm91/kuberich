"""Synthetic core/new Event API records with independent counts and object identities."""

from datetime import UTC, datetime

from kuberich.domain.events import EventSourceState
from kuberich.domain.resources import ApiResource, ResourceSnapshot, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewStatus

EVENT_CANARY = "PRIVATE_EVENT_NOTE_CANARY"
FIRST = "2026-11-06T12:00:00Z"
LAST = "2026-11-06T12:01:00Z"


def event_resource(*, modern=True):
    return ApiResource(
        "events.k8s.io" if modern else "",
        "v1",
        "events",
        "Event",
        True,
        frozenset({"get", "list", "watch"}),
    )


def event_manifest(
    *, modern=True, uid="event-a", namespace="team", object_uid="pod-uid", **changes
):
    resource = event_resource(modern=modern)
    ref = {"apiVersion": "v1", "kind": "Pod", "namespace": namespace, "name": "owned-pod"}
    if object_uid is not None:
        ref["uid"] = object_uid
    value = {
        "apiVersion": resource.api_version,
        "kind": "Event",
        "metadata": {
            "name": "owned-event",
            "uid": uid,
            "namespace": namespace,
            "resourceVersion": "1",
            "creationTimestamp": FIRST,
            "annotations": {"private": EVENT_CANARY},
        },
        "type": "Warning",
        "reason": "BackOff",
        "note": EVENT_CANARY,
        "message": EVENT_CANARY,
    }
    if modern:
        value.update(
            regarding=ref,
            eventTime=FIRST,
            reportingController="owned.example.test/controller",
            reportingInstance="worker-a",
        )
    else:
        value.update(
            involvedObject=ref,
            count=3,
            firstTimestamp=FIRST,
            lastTimestamp=LAST,
            source={"component": "owned-controller", "host": "worker-a"},
        )
    value.update(changes)
    return value


def event_record(**options):
    return resource_record(
        event_resource(modern=options.get("modern", True)), event_manifest(**options)
    )


def event_source(snapshot, *, generation=1, revision=7, status=ViewStatus.LIVE):
    return EventSourceState(
        ResourceScope(
            SessionIdentity("owned-events", generation), snapshot.resource, snapshot.namespace
        ),
        revision,
        snapshot.collection,
        status,
        datetime(2026, 11, 6, 12, 2, tzinfo=UTC),
    )


def event_snapshot(*records, modern=True, namespace="team"):
    return ResourceSnapshot(event_resource(modern=modern), namespace, "owned-rv", records)
