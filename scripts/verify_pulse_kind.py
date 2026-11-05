"""O02: actual Pulse API drill-downs and scraped Prometheus history on owned kind."""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import parse_document
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.history import HistoryBackend, HistorySnapshot, HistoryStatus, history_queries
from kuberich.domain.pulse import PulsePredicate, PulseScope, PulseSnapshot, PulseStatus
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.targets import SessionIdentity
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command
from kuberich.services.history import HistoryReader
from kuberich.services.ownership import finish_owned
from kuberich.services.pulse import PulseService
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.ui.app import KubeRichApp
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

PROMETHEUS_IMAGE = (
    "docker.io/prom/prometheus:v3.15.1@sha256:"
    "fa3302279710be2f21a8301ec17a8b4f2301fd829bd113839b3b6b02b6f191a2"
)
NAMESPACE = "kuberich-owned-pulse"
PROMETHEUS = "owned-prometheus"
CLUSTER_LABEL_VALUE = "owned-pulse-fixture"
MEMORY_GAUGE = 2**20

# These are explicitly synthetic exporter values, not cAdvisor consumption.
# The fixture is trusted constant source; no resource name enters shell text.
EXPORTER_SCRIPT = r"""set -eu
command -v nc >/dev/null
mkdir -p /export
cat > /export/respond <<'RESPONDER'
#!/bin/sh
set -eu
counter=$(date +%s)
body=$(printf '# TYPE container_cpu_usage_seconds_total counter\ncontainer_cpu_usage_seconds_total{namespace="kuberich-owned-pulse",pod="owned-prometheus",container="exporter",cluster="owned-pulse-fixture"} %s\n# TYPE container_memory_working_set_bytes gauge\ncontainer_memory_working_set_bytes{namespace="kuberich-owned-pulse",pod="owned-prometheus",container="exporter",cluster="owned-pulse-fixture"} 1048576\n' "$counter")
length=$(printf '%s\n' "$body" | wc -c)
printf 'HTTP/1.1 200 OK\r\nContent-Type: text/plain; version=0.0.4\r\nContent-Length: %s\r\nConnection: close\r\n\r\n' "$length"
printf '%s\n' "$body"
RESPONDER
chmod 700 /export/respond
exec nc -lk -p 9100 -e /export/respond
"""


def resources(cpu: str = "100m", memory: str = "32Mi") -> dict[str, Any]:
    return {
        "requests": {"cpu": cpu, "memory": memory},
        "limits": {"cpu": "500m", "memory": "128Mi"},
    }


def template(name: str, *, pending: bool = False) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "terminationGracePeriodSeconds": 0,
        "automountServiceAccountToken": False,
        "tolerations": [{"operator": "Exists"}],
        "containers": [
            {
                "name": "app",
                "image": SHELL_IMAGE,
                "command": ["sh", "-c", "sleep 3600"],
                "resources": resources(),
            }
        ],
    }
    if pending:
        spec["nodeSelector"] = {"kuberich-owned-absent": "never"}
    return {"metadata": {"labels": {"owned-pulse": name}}, "spec": spec}


def fixture_manifests() -> tuple[dict[str, Any], ...]:
    """Only fixed, read-back qualified disposable fixtures; no ambient inputs."""
    manifests: list[dict[str, Any]] = []
    for name, pending in (("owned-healthy", False), ("owned-degraded", True)):
        manifests.append(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name},
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"owned-pulse": name}},
                    "template": template(name, pending=pending),
                },
            }
        )
    manifests.extend(
        (
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": "owned-pending"},
                "spec": template("owned-pending", pending=True)["spec"],
            },
            {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "metadata": {"name": "owned-stateful"},
                "spec": {
                    "replicas": 0,
                    "serviceName": "owned-stateful",
                    "selector": {"matchLabels": {"owned-pulse": "owned-stateful"}},
                    "template": template("owned-stateful"),
                },
            },
            {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet",
                "metadata": {"name": "owned-daemon"},
                "spec": {
                    "selector": {"matchLabels": {"owned-pulse": "owned-daemon"}},
                    "template": template("owned-daemon", pending=True),
                },
            },
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {"name": "owned-completed"},
                "spec": {
                    "template": {
                        "spec": {
                            **template("owned-completed")["spec"],
                            "restartPolicy": "Never",
                            "containers": [
                                {
                                    "name": "app",
                                    "image": SHELL_IMAGE,
                                    "command": ["true"],
                                    "resources": resources("50m", "8Mi"),
                                }
                            ],
                        }
                    }
                },
            },
            {
                "apiVersion": "batch/v1",
                "kind": "CronJob",
                "metadata": {"name": "owned-suspended"},
                "spec": {
                    "schedule": "0 * * * *",
                    "suspend": True,
                    "jobTemplate": {
                        "spec": {
                            "template": {
                                "spec": {
                                    **template("owned-suspended")["spec"],
                                    "restartPolicy": "Never",
                                }
                            }
                        }
                    },
                },
            },
        )
    )
    return tuple(manifests)


def prometheus_manifests() -> tuple[dict[str, Any], ...]:
    configuration = {
        "global": {"scrape_interval": "2s", "evaluation_interval": "2s"},
        "scrape_configs": [
            {
                "job_name": "owned-synthetic-container-metrics",
                "static_configs": [{"targets": ["127.0.0.1:9100"]}],
            }
        ],
    }
    return (
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "owned-prometheus-config"},
            "data": {
                "prometheus.yml": yaml.safe_dump(configuration),
                "exporter.sh": EXPORTER_SCRIPT,
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": PROMETHEUS},
            "spec": {
                "selector": {"owned-pulse": PROMETHEUS},
                "ports": [{"name": "http", "port": 9090, "targetPort": 9090}],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": PROMETHEUS, "labels": {"owned-pulse": PROMETHEUS}},
            "spec": {
                "automountServiceAccountToken": False,
                "terminationGracePeriodSeconds": 0,
                "securityContext": {"fsGroup": 65534},
                "tolerations": [{"operator": "Exists"}],
                "volumes": [
                    {"name": "configuration", "configMap": {"name": "owned-prometheus-config"}},
                    {"name": "database", "emptyDir": {}},
                ],
                "containers": [
                    {
                        "name": "prometheus",
                        "image": PROMETHEUS_IMAGE,
                        "args": [
                            "--config.file=/etc/owned/prometheus.yml",
                            "--storage.tsdb.path=/prometheus",
                            "--storage.tsdb.retention.time=30m",
                            "--web.listen-address=0.0.0.0:9090",
                        ],
                        "ports": [{"containerPort": 9090}],
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"cpu": "1", "memory": "256Mi"},
                        },
                        "volumeMounts": [
                            {"name": "configuration", "mountPath": "/etc/owned", "readOnly": True},
                            {"name": "database", "mountPath": "/prometheus"},
                        ],
                        "readinessProbe": {
                            "httpGet": {"path": "/-/ready", "port": 9090},
                            "periodSeconds": 2,
                        },
                    },
                    {
                        "name": "exporter",
                        "image": SHELL_IMAGE,
                        "command": ["sh", "/etc/owned/exporter.sh"],
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "16Mi"},
                            "limits": {"cpu": "100m", "memory": "64Mi"},
                        },
                        "volumeMounts": [
                            {"name": "configuration", "mountPath": "/etc/owned", "readOnly": True}
                        ],
                    },
                ],
            },
        },
    )


async def until(predicate: Callable[[], Awaitable[bool]], *, timeout: float = 180) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(1)


def history_evidence(history: HistorySnapshot) -> dict[str, Any]:
    return {
        "status": str(history.status),
        "scope": history.scope_label,
        "observed_at": history.observed_at.isoformat() if history.observed_at else None,
        "start": history.start.isoformat() if history.start else None,
        "end": history.end.isoformat() if history.end else None,
        "step_seconds": history.step_seconds,
        "series": {
            series.key: {
                "unit": series.unit,
                "points": [
                    {
                        "timestamp": point.timestamp.isoformat(),
                        "value": str(point.value) if point.value is not None else None,
                    }
                    for point in series.points
                ],
            }
            for series in history.series
        },
    }


def checkpoint(directory: Path, stage: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    entry = {"stage": stage, "observed_at": datetime.now(UTC).isoformat()}
    (directory / "pulse-stage.json").write_text(json.dumps(entry, indent=2) + "\n")
    with (directory / "pulse-stages.jsonl").open("a") as stream:
        stream.write(json.dumps(entry) + "\n")


def pod_status(record: ResourceRecord) -> dict[str, Any]:
    """Only owned identities and bounded status codes; omit messages, env and credentials."""

    def code(value: object) -> str | None:
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/@+-]{1,512}", value)
            else None
        )

    manifest = record.manifest
    status = manifest.get("status")
    status = status if isinstance(status, dict) else {}
    entries = status.get("containerStatuses")
    containers = []
    for entry in entries[:16] if isinstance(entries, list) else ():
        if not isinstance(entry, dict):
            continue
        state = entry.get("state")
        state = state if isinstance(state, dict) else {}
        waiting, terminated = state.get("waiting"), state.get("terminated")
        waiting = waiting if isinstance(waiting, dict) else {}
        terminated = terminated if isinstance(terminated, dict) else {}
        containers.append(
            {
                "name": code(entry.get("name")),
                "ready": entry.get("ready") is True,
                "restart_count": entry.get("restartCount")
                if type(entry.get("restartCount")) is int
                else None,
                "waiting_reason": code(waiting.get("reason")),
                "terminated_reason": code(terminated.get("reason")),
                "running": isinstance(state.get("running"), dict),
                "image_id": code(entry.get("imageID")),
            }
        )
    return {
        "name": record.name,
        "uid": code(record.uid),
        "phase": code(status.get("phase")),
        "containers": containers,
    }


async def preserve_failure_pods(connection: KubernetesSession | None, directory: Path) -> None:
    result: dict[str, Any] = {"status": "unavailable", "namespace": NAMESPACE, "pods": []}
    if connection is not None:
        try:
            async with asyncio.timeout(5):
                reader = ResourceReader(connection)
                discovery = await reader.discover()
                snapshot = await reader.list(
                    discovery.find("pods"), NAMESPACE, max_items=100, max_retained_bytes=1024 * 1024
                )
                result = {
                    "status": "observed",
                    "namespace": NAMESPACE,
                    "complete": snapshot.collection.complete,
                    "pods": [
                        pod_status(record)
                        for record in snapshot.items
                        if record.name.startswith("owned-")
                    ],
                }
        except (Exception, asyncio.CancelledError) as error:
            result["failure_type"] = type(error).__name__
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pulse-failure-pods.json").write_text(json.dumps(result, indent=2) + "\n")


async def verify(cluster: OwnedCluster, evidence_dir: Path) -> dict[str, Any]:
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    catalog = load_catalog(request, {})
    sessions = SessionService(catalog, request)
    before = cluster.path.read_bytes()
    delegated: KubernetesSession | None = None
    checks: list[str] = []
    try:
        checkpoint(evidence_dir, "connecting-to-owned-context")
        await sessions.connect(cluster.context)
        connection, identity = sessions.client, sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        sdk = connection.api

        async def create(path: str, body: dict[str, Any]) -> Any:
            return await sdk.call_api(
                path,
                "POST",
                body=body,
                response_types_map={200: "object", 201: "object"},
                auth_settings=["BearerToken"],
                header_params={"Content-Type": "application/json"},
                _return_http_data_only=True,
                _request_timeout=15,
            )

        checkpoint(evidence_dir, "creating-controlled-api-and-prometheus-fixtures")
        await create("/api/v1/namespaces", {"metadata": {"name": NAMESPACE}})
        reader = ResourceReader(connection)
        discovery = await reader.discover()
        for manifest in (*fixture_manifests(), *prometheus_manifests()):
            resource = next(
                resource
                for resource in discovery.resources
                if resource.kind == manifest["kind"]
                and resource.api_version == manifest["apiVersion"]
            )
            await create(resource.path(NAMESPACE), manifest)

        service = PulseService(
            reader,
            discovery,
            PulseScope(identity, NAMESPACE),
            lambda: sessions.client is connection,
        )
        overview: PulseSnapshot | None = None

        async def settled() -> bool:
            nonlocal overview
            overview = await service.collect(lambda _: None)
            counts = {row.key: row.count for row in overview.rows}
            return (
                counts.get("deployments:healthy") == 1
                and counts.get("deployments:degraded") == 1
                and counts.get("pods:pod-unscheduled") == 2
                and counts.get("jobs:completed") == 1
                and counts.get("pods:pod-running") == 2
            )

        checkpoint(evidence_dir, "waiting-for-controller-pod-health-and-budget-state")
        await until(settled)
        assert overview is not None
        sources = {source.key: source for source in overview.sources}
        assert all(
            source.status is PulseStatus.VALID and source.complete
            for source in overview.sources
            if source.key not in {"node_metrics", "pod_metrics"}
        )
        assert (
            overview.node_metrics.cpu.capacity is not None
            and overview.node_metrics.cpu.capacity > 0
        )
        assert (
            overview.node_metrics.memory.allocatable is not None
            and overview.node_metrics.memory.allocatable > 0
        )
        assert overview.pod_metrics.cpu.request == Decimal(".410")
        assert overview.pod_metrics.memory.request == 240 * 2**20
        assert overview.pod_metrics.cpu.limit == Decimal("2.6")
        assert overview.pod_metrics.memory.limit == 704 * 2**20
        assert (
            sources["node_metrics"].status
            is sources["pod_metrics"].status
            is PulseStatus.UNAVAILABLE
        )
        assert overview.node_metrics.cpu.usage is overview.pod_metrics.cpu.usage is None
        checks.extend(
            [
                "actual-healthy-degraded-completed-pending-resources",
                "actual-node-capacity-and-active-pod-requests-limits",
                "missing-metrics-api-never-fabricates-current-zero",
            ]
        )

        checkpoint(evidence_dir, "checking-all-exact-resource-drilldowns")
        drilldowns = []
        pending_uids: set[str | None] = set()
        for row in overview.rows:
            target = row.drilldown
            assert target is not None and sources[row.source].complete
            underlying = await reader.list(target.resource, target.namespace, query=target.query)
            matched = tuple(
                record for record in underlying.items if target.predicate.matches(record)
            )
            assert len(matched) == row.count, row.key
            drilldowns.append(
                {
                    "key": row.key,
                    "resource": target.resource.api_version + "/" + target.resource.name,
                    "namespace": target.namespace,
                    "predicate": str(target.predicate),
                    "query": target.query.parameters,
                    "count": len(matched),
                }
            )
            if row.key == "pods:pod-unscheduled":
                pending_uids = {record.uid for record in matched}
        checks.append("actual-api-selectors-and-shared-predicate-drilldowns-match-all-counts")

        backend = HistoryBackend(
            NAMESPACE, PROMETHEUS, cluster_label="cluster", cluster_value=CLUSTER_LABEL_VALUE
        )
        historical: HistorySnapshot | None = None

        async def scraped() -> bool:
            nonlocal historical
            historical = await HistoryReader().read(connection, backend, NAMESPACE)
            return (
                all(
                    sum(point.value is not None for point in series.points) >= 3
                    for series in historical.series
                )
                and len(historical.series) == 2
            )

        checkpoint(evidence_dir, "waiting-for-real-prometheus-scrape-and-query-range")
        await until(scraped)
        assert historical is not None
        (evidence_dir / "pulse-history-observed.json").write_text(
            json.dumps(history_evidence(historical), indent=2) + "\n"
        )
        checkpoint(evidence_dir, "checking-scraped-history-status")
        assert historical.status in {
            HistoryStatus.VALID,
            HistoryStatus.PARTIAL,
        }
        values = {
            series.key: tuple(point.value for point in series.points if point.value is not None)
            for series in historical.series
        }
        checkpoint(evidence_dir, "checking-fresh-counter-rate")
        # A fresh series covers only part of rate(...[5m]); Prometheus divides
        # its extrapolated increase by the whole window, so it can be below .5.
        assert all(Decimal(0) < value < Decimal(2) for value in values["cpu"])
        checkpoint(evidence_dir, "checking-exact-synthetic-memory-gauge")
        assert all(value == MEMORY_GAUGE for value in values["memory"])

        # Compare settled evaluations with the actual backend independently of
        # our matrix parser. Leave the newest point out to avoid racing ingestion.
        checkpoint(evidence_dir, "comparing-settled-history-with-raw-prometheus")
        assert historical.start is not None and historical.end is not None
        settled_end = int(historical.end.timestamp()) - historical.step_seconds
        raw_values: dict[str, dict[str, str]] = {}
        for key, query in history_queries(backend, NAMESPACE):
            async with asyncio.timeout(10):
                prometheus_document = await connection.get_json(
                    backend.path,
                    params={
                        "query": query,
                        "start": str(int(historical.start.timestamp())),
                        "end": str(settled_end),
                        "step": str(historical.step_seconds),
                        "timeout": "8s",
                    },
                    max_bytes=1024 * 1024,
                )
            assert prometheus_document["status"] == "success"
            matrix = prometheus_document["data"]["result"]
            assert len(matrix) == 1
            raw_values[key] = {str(int(point[0])): point[1] for point in matrix[0]["values"]}
        (evidence_dir / "pulse-history-backend-values.json").write_text(
            json.dumps(raw_values, indent=2) + "\n"
        )
        for series in historical.series:
            observed_values = {
                str(int(point.timestamp.timestamp())): point.value
                for point in series.points
                if point.value is not None and point.timestamp.timestamp() <= settled_end
            }
            expected_values = {
                timestamp: Decimal(value) for timestamp, value in raw_values[series.key].items()
            }
            assert len(observed_values) >= 2 and observed_values == expected_values
        checks.append("parsed-history-values-match-settled-actual-prometheus-evaluations")

        checkpoint(evidence_dir, "checking-pinned-prometheus-build-version")
        build = await connection.get_json(
            backend.path.removesuffix("/query_range") + "/status/buildinfo"
        )
        assert build["status"] == "success" and build["data"]["version"] == "3.15.1"
        checks.append("real-pinned-prometheus-scrapes-explicit-synthetic-counter-and-gauge")

        checkpoint(evidence_dir, "checking-real-empty-missing-and-forbidden-sources")
        empty = await HistoryReader().read(
            connection,
            HistoryBackend(
                NAMESPACE, PROMETHEUS, cluster_label="cluster", cluster_value="no-owned-series"
            ),
            NAMESPACE,
        )
        assert empty.status is HistoryStatus.NO_DATA
        missing = await HistoryReader().read(
            connection, HistoryBackend(NAMESPACE, "owned-missing-service"), NAMESPACE
        )
        assert missing.status is HistoryStatus.UNAVAILABLE
        checks.append("real-prometheus-empty-selector-and-missing-service-remain-unavailable")

        user = "kuberich-owned-pulse-reader"
        rbac_path = "/apis/rbac.authorization.k8s.io/v1"
        await create(
            rbac_path + "/clusterroles",
            {
                "metadata": {"name": "owned-pulse-discovery"},
                "rules": [
                    {"nonResourceURLs": ["/api", "/api/*", "/apis", "/apis/*"], "verbs": ["get"]}
                ],
            },
        )
        await create(
            rbac_path + "/clusterrolebindings",
            {
                "metadata": {"name": "owned-pulse-discovery"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": "owned-pulse-discovery",
                },
                "subjects": [
                    {"apiGroup": "rbac.authorization.k8s.io", "kind": "User", "name": user}
                ],
            },
        )
        await create(
            rbac_path + f"/namespaces/{NAMESPACE}/roles",
            {
                "metadata": {"name": "owned-pulse-reader"},
                "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}],
            },
        )
        await create(
            rbac_path + f"/namespaces/{NAMESPACE}/rolebindings",
            {
                "metadata": {"name": "owned-pulse-reader"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "owned-pulse-reader",
                },
                "subjects": [
                    {"apiGroup": "rbac.authorization.k8s.io", "kind": "User", "name": user}
                ],
            },
        )
        delegated = KubernetesSession(
            catalog.select(cluster.context, ConnectionOverrides(as_user=user)), 15
        )
        await delegated.open()
        limited_reader = ResourceReader(delegated)

        async def permitted() -> bool:
            try:
                await limited_reader.list(discovery.find("pods"), NAMESPACE)
                return True
            except HttpProblem as problem:
                if problem.status != 403:
                    raise
                return False

        await until(permitted, timeout=30)
        limited = await PulseService(
            limited_reader,
            await limited_reader.discover(),
            PulseScope(SessionIdentity(cluster.context, identity.generation + 1), NAMESPACE),
            lambda: delegated is not None,
        ).collect(lambda _: None)
        limited_sources = {source.key: source for source in limited.sources}
        assert limited_sources["pods"].status is PulseStatus.VALID
        assert (
            limited_sources["nodes"].status
            is limited_sources["deployments"].status
            is PulseStatus.FORBIDDEN
        )
        forbidden = await HistoryReader().read(delegated, backend, NAMESPACE)
        assert forbidden.status is HistoryStatus.FORBIDDEN
        checks.append("actual-independent-partial-rbac-and-service-proxy-forbidden")

        document = parse_document(
            {
                "schema_version": 1,
                "observability": {
                    "history": {
                        "namespace": NAMESPACE,
                        "service": PROMETHEUS,
                        "cluster_label": "cluster",
                        "cluster_value": CLUSTER_LABEL_VALUE,
                    }
                },
            }
        )
        preference_path = cluster.directory / "pulse-preferences.yaml"
        preference_path.write_text(yaml.safe_dump(document.to_mapping()))
        preferences = PreferenceSource(ConfigLocation(preference_path, True), document)
        app = KubeRichApp(
            document.settings,
            logging.Logger("owned-pulse", level=100),
            catalog=catalog,
            connection=request,
            preferences=preferences,
            initial_command=Command.PULSE,
        )
        checkpoint(evidence_dir, "rendering-real-history-and-keyboard-drilldowns")
        async with app.run_test(size=(120, 36)) as pilot:

            async def charts_ready() -> bool:
                return "history:2" in app.pulse_table.rows and any(
                    block in app.pulse_table.get_cell("history:1", "VALUE").plain
                    for block in "▁▂▃▄▅▆▇█"
                )

            await until(charts_ready, timeout=60)
            await pilot.pause()
            cpu_chart = app.pulse_table.get_cell("history:1", "VALUE").plain
            memory_chart = app.pulse_table.get_cell("history:2", "VALUE").plain
            assert "mCPU" in cpu_chart and "1 MiB" in memory_chart
            assert (
                "·" in cpu_chart
                and "Configured cluster selector"
                in app.pulse_table.get_cell("history:0", "DETAIL").plain
            )
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "pulse-real-prometheus.svg").write_text(app.export_screenshot())
            app.pulse_table.move_cursor(row=app.pulse_table.get_row_index("pods:pod-unscheduled"))
            await pilot.press("enter")

            async def pending_ready() -> bool:
                return (
                    app.state.view_kind == "pods"
                    and {row.key.value for row in app.resources.ordered_rows} == pending_uids
                )

            await until(pending_ready, timeout=30)
            pending_drilldown = app.views.drilldown
            assert (
                pending_drilldown is not None
                and pending_drilldown.predicate is PulsePredicate.POD_UNSCHEDULED
            )
            await pilot.press("escape")

            async def pulse_ready() -> bool:
                return app.state.view_kind == "pulse" and app.pulse_table.scope is not None

            await until(pulse_ready, timeout=30)
            app.pulse_table.move_cursor(row=app.pulse_table.get_row_index("metric:pod:cpu"))
            await pilot.press("enter")

            async def active_ready() -> bool:
                return app.state.view_kind == "pods" and app.resources.row_count == 4

            await until(active_ready, timeout=30)
            assert (
                app.views.drilldown is not None
                and app.views.drilldown.predicate is PulsePredicate.POD_ACTIVE
            )
            assert app.resources.sort_column == "cpu" and app.resources.descending
        assert app.workspace.ownership.pulse_count == app.workspace.ownership.watch_count == 0
        checks.append("real-service-proxy-history-charts-and-exact-keyboard-drilldowns")
        assert cluster.path.read_bytes() == before
        checks.append("caller-config-unchanged")
        checkpoint(evidence_dir, "verified-awaiting-owned-cluster-cleanup")
        return {
            "node_image": NODE_IMAGE,
            "shell_image": SHELL_IMAGE,
            "prometheus_image": PROMETHEUS_IMAGE,
            "prometheus_build": build["data"],
            "fixture_scope": "Explicit synthetic exporter metrics; no real-cAdvisor/provider certification",
            "synthetic_labels": {
                "namespace": NAMESPACE,
                "pod": PROMETHEUS,
                "container": "exporter",
                "cluster": CLUSTER_LABEL_VALUE,
            },
            "synthetic_counter_increment_per_second": 1,
            "synthetic_counter_source": "Unix seconds sampled by the fixed HTTP responder",
            "synthetic_memory_gauge_bytes": MEMORY_GAUGE,
            "checks": checks,
            "drilldowns": drilldowns,
            "history": history_evidence(historical),
            "charts": {"cpu": cpu_chart, "memory": memory_chart},
            "peak_retained_count": service.peak_retained_count,
            "peak_retained_bytes": service.peak_retained_bytes,
        }
    except BaseException:
        diagnostic = asyncio.create_task(preserve_failure_pods(sessions.client, evidence_dir))
        await finish_owned(asyncio.gather(diagnostic, return_exceptions=True))
        raise
    finally:
        if delegated is not None:
            await delegated.close()
        await sessions.close()


def input_hashes(root: Path) -> dict[str, str]:
    paths = [
        *sorted(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        root / "uv.lock",
        root / "pyproject.toml",
        root / "scripts/owned_kind.py",
        root / "scripts/verify_pulse_kind.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.evidence.exists() or (args.evidence.parent / "pulse-stages.jsonl").exists():
        raise ValueError("Use a fresh evidence path; earlier outcomes must be preserved.")
    root = Path(__file__).resolve().parent.parent
    captured = input_hashes(root)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": captured,
        "owned_cluster_deleted": False,
    }
    started = time.monotonic()
    problem: BaseException | None = None
    try:
        checkpoint(args.evidence.parent, "creating-owned-disposable-cluster")
        with owned_cluster(args.kind, docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(asyncio.run(verify(cluster, args.evidence.parent)))
            except BaseException as error:
                problem = error
                result["failure_type"] = type(error).__name__
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        if problem is not None:
            raise problem
        if not result["inputs_unchanged"] or not result["private_directory_deleted"]:
            raise AssertionError("Qualification input or cleanup changed.")
        result["status"] = "passed"
        checkpoint(args.evidence.parent, "passed-owned-cluster-absence-verified")
    except BaseException as error:
        result.setdefault("failure_type", type(error).__name__)
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind Pulse and real Prometheus checks passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned Pulse verification failed ({type(error).__name__}); inspect retained stage and Pod status evidence.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
