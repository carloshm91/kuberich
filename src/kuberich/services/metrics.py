"""One scope-owned serialized metrics poller using the existing per-context reader."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial

from kuberich.domain.aggregate_logs import intermediate_resource, owned_by
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.metrics import (
    MetricReport,
    MetricsSnapshot,
    MetricStatus,
    aggregate,
    node_sample,
    pod_budget,
    pod_sample,
)
from kuberich.domain.resources import CollectionState, Discovery, ResourceRecord, ResourceSnapshot
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.views import ResourceScope
from kuberich.errors import AppError
from kuberich.services.resources import ResourceReader, parse_owned

POLL_INTERVAL = 15.0
WORKLOADS = frozenset(
    {
        ("apps", "deployments"),
        ("apps", "replicasets"),
        ("apps", "statefulsets"),
        ("apps", "daemonsets"),
        ("batch", "jobs"),
        ("batch", "cronjobs"),
    }
)


def supports_metrics(scope: ResourceScope) -> bool:
    return (scope.resource.group, scope.resource.name) in WORKLOADS | {("", "pods"), ("", "nodes")}


def _target(scope: ResourceScope, record: ResourceRecord) -> ResourceTarget:
    return ResourceTarget(
        scope.session,
        scope.resource.group,
        scope.resource.name,
        record.namespace,
        record.name,
        record.uid or "",
    )


def _controller(record: ResourceRecord) -> str | None:
    references = record.manifest.get("metadata", {}).get("ownerReferences", [])
    if not isinstance(references, list) or len(references) > 128:
        raise AppError("Invalid metrics membership owners.")
    return next(
        (
            entry["uid"]
            for entry in references
            if isinstance(entry, dict)
            and entry.get("controller") is True
            and isinstance(entry.get("uid"), str)
        ),
        None,
    )


def reconcile(
    scope: ResourceScope,
    selected: ResourceSnapshot,
    pods: ResourceSnapshot,
    after: ResourceSnapshot,
    samples: ResourceSnapshot,
    intermediates: ResourceSnapshot | None,
    now: datetime,
) -> MetricsSnapshot:
    """Bind name-only samples to captured and reverified actual UIDs, never templates."""
    verified = {(record.namespace, record.name): record.uid for record in after.items}
    sample_index = {(record.namespace, record.name): record for record in samples.items}
    stable = tuple(
        record
        for record in pods.items
        if record.uid is not None and verified.get((record.namespace, record.name)) == record.uid
    )
    complete = (
        pods.collection.complete
        and after.collection.complete
        and samples.collection.complete
        and len(stable) == len(pods.items) == len(after.items)
    )
    reports = []
    if scope.resource.name == "nodes":
        groups: dict[str, list[MetricReport]] = {}
        for pod in stable:
            manifest = pod.manifest
            if manifest.get("status", {}).get("phase") not in {"Succeeded", "Failed"}:
                groups.setdefault(manifest.get("spec", {}).get("nodeName", ""), []).append(
                    pod_budget(pod)
                )
        for node in selected.items:
            sample = sample_index.get((None, node.name))
            reports.append(
                (
                    node.uid or "",
                    node_sample(
                        node, sample, tuple(groups.get(node.name, [])), now, complete=complete
                    ),
                )
            )
    else:
        observed = {
            pod.uid: pod_sample(pod, sample_index.get((pod.namespace, pod.name)), now)
            for pod in stable
        }
        if scope.resource.name == "pods":
            reports = [
                (pod.uid or "", observed.get(pod.uid, pod_budget(pod))) for pod in selected.items
            ]
        else:
            targets = {
                record.uid: _target(scope, record) for record in selected.items if record.uid
            }
            owners = dict(targets)
            parents: dict[str, str] = {}
            resource = intermediate_resource(next(iter(targets.values()))) if targets else None
            if resource is not None:
                complete = (
                    complete and intermediates is not None and intermediates.collection.complete
                )
                for record in intermediates.items if intermediates is not None else ():
                    parent = targets.get(_controller(record) or "")
                    if (
                        parent is not None
                        and record.uid
                        and owned_by(record, parent, scope.resource.kind)
                    ):
                        parents[record.uid] = parent.uid
                        owners[record.uid] = ResourceTarget(
                            scope.session,
                            resource.group,
                            resource.name,
                            record.namespace,
                            record.name,
                            record.uid,
                        )
            groups_by_uid: dict[str, list[MetricReport]] = {}
            for pod in stable:
                owner = owners.get(_controller(pod) or "")
                if owner is None or not owned_by(
                    pod, owner, resource.kind if resource is not None else scope.resource.kind
                ):
                    continue
                uid = parents.get(owner.uid, owner.uid)
                if uid in targets:
                    groups_by_uid.setdefault(uid, []).append(observed[pod.uid])
            reports = [
                (uid, aggregate(tuple(groups_by_uid.get(uid, [])), complete=complete))
                for uid in targets
            ]
    return MetricsSnapshot(
        tuple(reports), MetricStatus.NO_SAMPLE, "No sample for this resource identity"
    )


class MetricsPoller:
    """No per-row requests, overlap, global clients or historical sample cache."""

    def __init__(
        self,
        reader: ResourceReader,
        discovery: Discovery,
        scope: ResourceScope,
        snapshot: Callable[[], ResourceSnapshot | None],
        current: Callable[[], bool],
        *,
        interval: float = POLL_INTERVAL,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 0.01 <= interval <= 60:
            raise AppError("Metrics poll interval is outside its bounds.")
        self.reader, self.discovery, self.scope = reader, discovery, scope
        self.snapshot, self.current, self.interval, self.now = snapshot, current, interval, now
        self.ready = asyncio.Event()

    def wake(self) -> None:
        self.ready.set()

    def _missing(self, name: str) -> MetricsSnapshot:
        forbidden = any(
            issue.reason == "forbidden"
            and (issue.source == "/apis" or issue.source.partition("/")[0] == "metrics.k8s.io")
            for issue in self.discovery.issues
        )
        return MetricsSnapshot(
            status=MetricStatus.FORBIDDEN if forbidden else MetricStatus.UNAVAILABLE,
            detail=f"metrics.k8s.io/{name} was not discovered; check API availability and read access",
        )

    async def poll(self, selected: ResourceSnapshot) -> MetricsSnapshot:
        name = "nodes" if self.scope.resource.name == "nodes" else "pods"
        failure: MetricsSnapshot | None
        try:
            membership_failure: MetricsSnapshot | None = None
            try:
                if self.scope.resource.name == "pods":
                    pods, intermediates = selected, None
                else:
                    pods = await self.reader.list(self.discovery.find("pods"), self.scope.namespace)
                    intermediate = (
                        intermediate_resource(_target(self.scope, selected.items[0]))
                        if self.scope.resource.name != "nodes" and selected.items
                        else None
                    )
                    intermediates = (
                        await self.reader.list(
                            self.discovery.find(intermediate.name, group=intermediate.group),
                            self.scope.namespace,
                        )
                        if intermediate is not None
                        else None
                    )
            except (ConnectionProblem, AppError) as problem:
                membership_failure = self._failure(problem)
                pods = replace(selected, items=(), collection=CollectionState(complete=False))
                intermediates = None
            try:
                metrics = self.discovery.find(name, group="metrics.k8s.io")
            except AppError:
                failure = self._missing(name)
                samples = replace(pods, items=())
            else:
                try:
                    samples = await self.reader.list(metrics, self.scope.namespace)
                    failure = None
                except (ConnectionProblem, AppError) as problem:
                    failure = self._failure(problem)
                    samples = replace(pods, items=())
            if not self.current():
                raise asyncio.CancelledError
            if self.scope.resource.name == "pods":
                after = self.snapshot()
                if after is None:
                    raise asyncio.CancelledError
            elif membership_failure is None:
                after = await self.reader.list(self.discovery.find("pods"), self.scope.namespace)
            else:
                after = pods
            if not self.current():
                raise asyncio.CancelledError
            result = await parse_owned(
                partial(
                    reconcile, self.scope, selected, pods, after, samples, intermediates, self.now()
                )
            )
            if membership_failure is not None:
                result = replace(
                    result,
                    reports=tuple(
                        (
                            uid,
                            replace(
                                report,
                                status=membership_failure.status
                                if report.status is MetricStatus.NO_SAMPLE
                                else report.status,
                                detail=" · ".join(
                                    filter(
                                        None,
                                        (
                                            report.detail,
                                            "Pod membership " + membership_failure.detail,
                                        ),
                                    )
                                ),
                            ),
                        )
                        for uid, report in result.reports
                    ),
                )
            if failure is not None:
                result = replace(
                    failure,
                    reports=tuple(
                        (
                            uid,
                            replace(
                                report,
                                status=failure.status,
                                detail=" · ".join(filter(None, (failure.detail, report.detail))),
                            ),
                        )
                        for uid, report in result.reports
                    ),
                )
            return result
        except (ConnectionProblem, AppError) as problem:
            return self._failure(problem)

    @staticmethod
    def _failure(problem: ConnectionProblem | AppError) -> MetricsSnapshot:
        if isinstance(problem, HttpProblem):
            status = (
                MetricStatus.FORBIDDEN
                if problem.status == 403
                else MetricStatus.UNAVAILABLE
                if problem.status in {404, 503}
                else MetricStatus.ERROR
            )
            return MetricsSnapshot(
                status=status, detail=f"Metrics/membership read HTTP {problem.status}"
            )
        if isinstance(problem, ConnectionProblem):
            return MetricsSnapshot(
                status=MetricStatus.ERROR,
                detail=f"Metrics/membership read {problem.state.name.lower()}",
            )
        return MetricsSnapshot(
            status=MetricStatus.ERROR, detail="Invalid or excessive metrics/membership payload"
        )

    async def run(self, publish: Callable[[MetricsSnapshot], None]) -> None:
        while self.current():
            selected = self.snapshot()
            if selected is None:
                self.ready.clear()
                await self.ready.wait()
                continue
            result = await self.poll(selected)
            if self.current():
                publish(result)
            await asyncio.sleep(self.interval)
