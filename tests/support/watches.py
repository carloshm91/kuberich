"""Synthetic Kubernetes watch frames and a deterministic retry clock."""

import asyncio
import json

from kubetrol.domain.resources import ResourceSnapshot, resource_record
from tests.support.resources import item, pod_resource


def event(
    kind: str = "ADDED",
    name: str = "one",
    version: str = "opaque-event",
    *,
    uid: str | None = None,
    namespace: str | None = "team",
) -> dict:
    obj = item(name, uid=uid, namespace=namespace)
    obj["metadata"]["resourceVersion"] = version
    return {"type": kind, "object": obj}


def bookmark(version: str) -> dict:
    return {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": version}}}


def error_event(code: int, delay: int | None = None) -> dict:
    obj = {"kind": "Status", "code": code, "message": "opaque-sensitive-test-body"}
    if delay is not None:
        obj["details"] = {"retryAfterSeconds": delay}
    return {"type": "ERROR", "object": obj}


def frame(value: dict) -> bytes:
    return json.dumps(value).encode() + b"\n"


def snapshot(*values: dict, version: str = "opaque-snapshot") -> ResourceSnapshot:
    return ResourceSnapshot(
        pod_resource(),
        "team",
        version,
        tuple(resource_record(pod_resource(), value, "team") for value in values),
    )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay
        await asyncio.sleep(0)
