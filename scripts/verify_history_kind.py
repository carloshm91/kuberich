"""O08: real native metrics and provider contracts in an explicitly owned kind cluster."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import tarfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from yaml.nodes import ScalarNode

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest, HttpProblem
from kuberich.domain.history import (
    HistoryBackend,
    HistoryOptions,
    HistoryRequest,
    HistoryScope,
    HistorySnapshot,
    HistoryStatus,
    Provider,
    ScopeKind,
    history_window,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.history import HistoryReader, ServiceHistoryTransport
from kuberich.services.history_workspace import HistoryWorkspace
from kuberich.services.resources import ResourceReader, parse_owned
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster, run_owned

NAMESPACE = "kuberich-owned-history"
IMAGES = {
    "operator": "quay.io/prometheus-operator/prometheus-operator:v0.94.2@sha256:c7edf0379b7271ef1705dce258d2bb73820e299cc95559369e9f6fc3321639ec",
    "reloader": "quay.io/prometheus-operator/prometheus-config-reloader:v0.94.2@sha256:a1897c67478bc23434534e91ad3855280771196b1daf17144db9dbcb655bef71",
    "prometheus": "quay.io/prometheus/prometheus:v3.16.0-distroless@sha256:9764044e09eb2c9e1abdb12d0f0188d4efb7384b0262d3c080f0fc59045c89ba",
    "node-exporter": "quay.io/prometheus/node-exporter:v1.12.1@sha256:1b4e4438faca4dd7e001dd445d161a4a2091b0fededa84093b3a8dfeae1f1be0",
    "ksm": "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.20.0@sha256:42cfe3723a5f058171c627537fb57a3ea0f26e4380fa18555a95cb1a1b4cfc5b",
    "thanos": "quay.io/thanos/thanos:v0.42.5@sha256:0a546b98a8dd47735456ab389983675ee363d68127e334937a9fceeea10da5e7",
    "victoriametrics": "docker.io/victoriametrics/victoria-metrics:v1.155.0@sha256:f60dc268b54ecf87f6e09d740c2b732838aa9193090cc741417c9f6386a130df",
}


@dataclass(frozen=True)
class ChartPin:
    name: str
    version: str
    url: str
    sha256: str
    source: str
    lock_digest: str


CHARTS = (
    ChartPin(
        "kube-prometheus-stack",
        "92.21.1",
        "https://github.com/prometheus-community/helm-charts/releases/download/kube-prometheus-stack-92.21.1/kube-prometheus-stack-92.21.1.tgz",
        "c8ce205551f2df69d473ae77e6e0c7ca410445831648b509a330053ebc788159",
        "965f15f4bea826974b904a87ddae156142762af6",
        "sha256:badea2b3825eeab3c9461026f7307ea54f874f9239a81756853a477e1630d0e2",
    ),
    ChartPin(
        "victoria-metrics-single",
        "0.50.0",
        "https://github.com/VictoriaMetrics/helm-charts/releases/download/victoria-metrics-single-0.50.0/victoria-metrics-single-0.50.0.tgz",
        "051d1b19cdc05e80cf67faa7d5bb1b393353780256d1f7cd5cadb3c77e67b1dd",
        "7da049e274aae4126a113520324c8a61d899e673",
        "sha256:61bb97a374214a9397ce847746b372a92c03869d5d89e12dff2efcd09bab01ad",
    ),
)


class _ChartLoader(yaml.SafeLoader):
    """Kubernetes YAML uses plain '=' enum scalars, not YAML 1.1 value objects."""


_ChartLoader.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(cast(ScalarNode, node))
)


def _image_settings(key: str) -> dict[str, str]:
    name, digest = IMAGES[key].split("@", 1)
    registry, rest = name.split("/", 1)
    repository, tag = rest.rsplit(":", 1)
    return {
        "registry": registry,
        "repository": repository,
        "tag": tag,
        "digest" if key == "node-exporter" else "sha": digest.removeprefix("sha256:")
        if key in {"operator", "reloader", "prometheus", "thanos"}
        else digest,
    }


def stack_values() -> dict[str, Any]:
    """Minimal actual operator/Prometheus/KSM/node-exporter, no dashboards or alerts."""
    return {
        "fullnameOverride": "owned-stack",
        "cleanPrometheusOperatorObjectNames": True,
        "defaultRules": {"create": False},
        "grafana": {"enabled": False},
        "alertmanager": {"enabled": False},
        "kubeEtcd": {"enabled": False},
        "kubeControllerManager": {"enabled": False},
        "kubeScheduler": {"enabled": False},
        "kubeProxy": {"enabled": False},
        "prometheusOperator": {
            "image": _image_settings("operator"),
            "admissionWebhooks": {"enabled": False},
            "tls": {"enabled": False},
            "thanosImage": _image_settings("thanos"),
            "prometheusConfigReloader": {"image": _image_settings("reloader")},
        },
        "kube-state-metrics": {"image": _image_settings("ksm")},
        "prometheus-node-exporter": {
            "image": {**_image_settings("node-exporter"), "distroless": False}
        },
        "kubelet": {"serviceMonitor": {"interval": "5s", "cAdvisorInterval": "5s"}},
        "prometheus": {
            "thanosService": {"enabled": True},
            "prometheusSpec": {
                "image": _image_settings("prometheus"),
                "version": "v3.16.0",
                "scrapeInterval": "5s",
                "evaluationInterval": "5s",
                "serviceMonitorSelectorNilUsesHelmValues": False,
                "serviceMonitorSelector": {"matchLabels": {"release": "owned-history"}},
                "retention": "1d",
                "externalLabels": {"cluster": "owned-history-fixture"},
                "resources": {
                    "requests": {"cpu": "100m", "memory": "256Mi"},
                    "limits": {"memory": "768Mi"},
                },
                "thanos": {"image": IMAGES["thanos"], "version": "v0.42.5"},
                "remoteWrite": [
                    {"url": f"http://owned-vm-server.{NAMESPACE}.svc:8428/api/v1/write"}
                ],
            },
        },
    }


def vm_values() -> dict[str, Any]:
    image = _image_settings("victoriametrics")
    return {
        "fullnameOverride": "owned-vm",
        "server": {
            "image": {
                "registry": image["registry"],
                "repository": image["repository"],
                "tag": image["tag"] + "@" + image["sha"],
            },
            "persistentVolume": {"enabled": False},
            "mode": "deployment",
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"memory": "512Mi"},
            },
            "retentionPeriod": "1d",
            "scrape": {"enabled": False},
        },
    }


def rendered_images(documents: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """Include ordinary Pods and operator-owned image fields before execution."""
    images: set[str] = set()

    def inspect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "image" and isinstance(item, str):
                    images.add(item)
                elif key in {"args", "command"} and isinstance(item, list):
                    for argument in item:
                        if isinstance(argument, str) and (
                            "-image=" in argument
                            or argument.startswith("--prometheus-config-reloader=")
                        ):
                            images.add(argument.split("=", 1)[1])
                else:
                    inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(list(documents))
    for image in images:
        if re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image) is None:
            raise ValueError("Rendered provider image is not digest-pinned.")
    return tuple(sorted(images))


def prepare_charts(directory: Path, helm: str) -> tuple[dict[str, Any], ...]:
    """Download checksum-pinned packages, verify dependency locks and render offline."""
    documents: list[dict[str, Any]] = []
    directory.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for pin, values in zip(CHARTS, (stack_values(), vm_values()), strict=True):
        archive = directory / f"{pin.name}-{pin.version}.tgz"
        if not archive.exists():
            with urllib.request.urlopen(pin.url, timeout=45) as response:
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("Provider chart package exceeded its bound.")
            archive.write_bytes(content)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != pin.sha256:
            raise ValueError("Provider chart package checksum changed.")
        with tarfile.open(archive, "r:gz") as package:
            member = package.extractfile(pin.name + "/Chart.lock")
            if member is None:
                raise ValueError("Provider chart has no dependency lock.")
            lock = member.read(65537)
            if len(lock) > 65536 or yaml.safe_load(lock).get("digest") != pin.lock_digest:
                raise ValueError("Provider chart dependency lock changed.")
            (directory / (pin.name + "-Chart.lock")).write_bytes(lock)
        values_path = directory / (pin.name + "-values.yaml")
        values_path.write_text(yaml.safe_dump(values))
        rendered = run_owned(
            [
                helm,
                "template",
                "owned-history",
                str(archive),
                "--namespace",
                NAMESPACE,
                "--include-crds",
                "--values",
                str(values_path),
            ],
            environment,
            timeout=60,
        )
        (directory / (pin.name + "-rendered.yaml")).write_text(rendered)
        documents.extend(
            item for item in yaml.load_all(rendered, Loader=_ChartLoader) if isinstance(item, dict)
        )
    result = tuple(documents)
    inventory = rendered_images(result)
    (directory / "prepared-inventory.json").write_text(
        json.dumps(
            {
                "charts": [asdict(pin) for pin in CHARTS],
                "rendered_images": inventory,
                "manifest_count": len(result),
                "qualification": "prepared; actual runtime not yet qualified",
            },
            indent=2,
        )
        + "\n"
    )
    return result


def fixture_manifests() -> tuple[dict[str, Any], ...]:
    template = {
        "metadata": {"labels": {"owned-history": "workload"}},
        "spec": {
            "automountServiceAccountToken": False,
            "terminationGracePeriodSeconds": 0,
            "containers": [
                {
                    "name": "app",
                    "image": SHELL_IMAGE,
                    "command": [
                        "sh",
                        "-c",
                        "while true; do dd if=/dev/zero of=/tmp/owned bs=4096 count=32 2>/dev/null; sleep 1; done",
                    ],
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "8Mi"},
                        "limits": {"cpu": "100m", "memory": "32Mi"},
                    },
                }
            ],
        },
    }
    return (
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "owned-workload"},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"owned-history": "workload"}},
                "template": template,
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "owned-recreated"},
            "spec": template["spec"],
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "owned-thanos", "labels": {"app": "thanos"}},
            "spec": {
                "selector": {"owned-history": "thanos"},
                "ports": [{"name": "http-query", "port": 10902}],
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "owned-thanos"},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"owned-history": "thanos"}},
                "template": {
                    "metadata": {"labels": {"owned-history": "thanos"}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "containers": [
                            {
                                "name": "query",
                                "image": IMAGES["thanos"],
                                "args": [
                                    "query",
                                    "--http-address=0.0.0.0:10902",
                                    "--grpc-address=0.0.0.0:10901",
                                    f"--endpoint=dnssrv+_grpc._tcp.owned-stack-thanos-discovery.{NAMESPACE}.svc.cluster.local",
                                ],
                                "resources": {
                                    "requests": {"cpu": "50m", "memory": "64Mi"},
                                    "limits": {"memory": "256Mi"},
                                },
                            }
                        ],
                    },
                },
            },
        },
    )


CAPTURE_RESPONDER = r"""#!/bin/sh
set -eu
IFS= read -r request
authorization=0
impersonation=0
while IFS= read -r line; do
  line=$(printf '%s' "$line" | tr -d '\r')
  [ -n "$line" ] || break
  name=$(printf '%s' "${line%%:*}" | tr '[:upper:]' '[:lower:]')
  case "$name" in
    authorization) authorization=1 ;;
    impersonate-*) impersonation=$((impersonation + 1)) ;;
  esac
done
endpoint=0
case "$request" in *'/api/v1/query_range?'*) endpoint=1 ;; esac
end=$(printf '%s' "$request" | sed -n 's/.*[?&]end=\([0-9][0-9]*\).*/\1/p')
[ -n "$end" ] || end=0
body=$(printf '{"status":"success","data":{"resultType":"matrix","result":[{"metric":{},"values":[[%s,"1"]]}]}}' "$end")
printf '{"authorization_present":%s,"impersonation_count":%s,"query_range":%s}\n' "$authorization" "$impersonation" "$endpoint" >&2
printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\n\r\n%s' "${#body}" "$body"
"""


RESET_RESPONDER = r"""#!/bin/sh
set -eu
IFS= read -r request
while IFS= read -r line; do
  line=$(printf '%s' "$line" | tr -d '\r')
  [ -n "$line" ] || break
done
counter=$(date +%s)
counter=$((counter % 20))
body=$(printf '# TYPE kuberich_fixture_counter_total counter\nkuberich_fixture_counter_total{fixture="synthetic-reset"} %s\n# TYPE kuberich_fixture_gauge gauge\nkuberich_fixture_gauge{fixture="synthetic-reset"} 42\n' "$counter")
printf 'HTTP/1.1 200 OK\r\nContent-Type: text/plain; version=0.0.4\r\nContent-Length: %s\r\nConnection: close\r\n\r\n%s\n' "$((${#body} + 1))" "$body"
"""


def reset_manifests() -> tuple[dict[str, Any], ...]:
    """Separately labeled synthetic reset source, never native-family evidence."""
    return (
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "owned-reset"},
            "data": {"respond": RESET_RESPONDER},
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "owned-reset"},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"owned-history": "reset"}},
                "template": {
                    "metadata": {"labels": {"owned-history": "reset"}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "terminationGracePeriodSeconds": 0,
                        "volumes": [
                            {
                                "name": "responder",
                                "configMap": {"name": "owned-reset", "defaultMode": 0o700},
                            }
                        ],
                        "containers": [
                            {
                                "name": "exporter",
                                "image": SHELL_IMAGE,
                                "command": ["sh", "-c", "exec nc -lk -p 9101 -e /owned/respond"],
                                "ports": [{"name": "metrics", "containerPort": 9101}],
                                "readinessProbe": {
                                    "httpGet": {"path": "/metrics", "port": "metrics"},
                                    "periodSeconds": 2,
                                    "timeoutSeconds": 1,
                                },
                                "volumeMounts": [
                                    {"name": "responder", "mountPath": "/owned", "readOnly": True}
                                ],
                            }
                        ],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "owned-reset", "labels": {"owned-history": "reset"}},
            "spec": {
                "selector": {"owned-history": "reset"},
                "ports": [{"name": "metrics", "port": 9101, "targetPort": "metrics"}],
            },
        },
        {
            "apiVersion": "monitoring.coreos.com/v1",
            "kind": "ServiceMonitor",
            "metadata": {"name": "owned-reset", "labels": {"release": "owned-history"}},
            "spec": {
                "selector": {"matchLabels": {"owned-history": "reset"}},
                "namespaceSelector": {"matchNames": [NAMESPACE]},
                "endpoints": [
                    {"port": "metrics", "path": "/metrics", "interval": "2s", "scrapeTimeout": "1s"}
                ],
            },
        },
    )


def capture_manifests() -> tuple[dict[str, Any], ...]:
    """The receiver persists only header-presence counters, never header values."""
    return (
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "owned-capture"},
            "data": {"respond": CAPTURE_RESPONDER},
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "owned-capture", "labels": {"owned-history": "capture"}},
            "spec": {
                "automountServiceAccountToken": False,
                "terminationGracePeriodSeconds": 0,
                "volumes": [
                    {
                        "name": "receiver",
                        "configMap": {"name": "owned-capture", "defaultMode": 0o700},
                    }
                ],
                "containers": [
                    {
                        "name": "receiver",
                        "image": SHELL_IMAGE,
                        "command": ["sh", "-c", "exec nc -lk -p 9100 -e /owned/respond"],
                        "volumeMounts": [
                            {"name": "receiver", "mountPath": "/owned", "readOnly": True}
                        ],
                    }
                ],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "owned-capture"},
            "spec": {
                "selector": {"owned-history": "capture"},
                "ports": [{"port": 9100, "targetPort": 9100}],
            },
        },
        *(
            {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": name}}
            for name in ("owned-capture-requestor", "owned-capture-denied")
        ),
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": {"name": "owned-capture"},
            "rules": [{"apiGroups": [""], "resources": ["services/proxy"], "verbs": ["get"]}],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": "owned-capture"},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "Role",
                "name": "owned-capture",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": "owned-capture-requestor",
                    "namespace": NAMESPACE,
                },
                {
                    "kind": "User",
                    "name": "owned-history-subject",
                    "apiGroup": "rbac.authorization.k8s.io",
                },
            ],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "kuberich-owned-history-impersonation"},
            "rules": [
                {
                    "apiGroups": [""],
                    "resources": ["users"],
                    "verbs": ["impersonate"],
                    "resourceNames": ["owned-history-subject"],
                },
                {
                    "apiGroups": [""],
                    "resources": ["groups"],
                    "verbs": ["impersonate"],
                    "resourceNames": ["owned-history-group"],
                },
                {
                    "apiGroups": ["authentication.k8s.io"],
                    "resources": ["uids"],
                    "verbs": ["impersonate"],
                    "resourceNames": ["owned-history-uid"],
                },
                {
                    "apiGroups": ["authentication.k8s.io"],
                    "resources": ["userextras/scope"],
                    "verbs": ["impersonate"],
                    "resourceNames": ["owned-history-extra"],
                },
            ],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": "kuberich-owned-history-impersonation"},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "kuberich-owned-history-impersonation",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": "owned-capture-requestor",
                    "namespace": NAMESPACE,
                }
            ],
        },
    )


def assert_backend_isolation(records: tuple[dict[str, Any], ...]) -> None:
    if not records or any(
        record.get("authorization_present")
        or record.get("impersonation_count")
        or not record.get("query_range")
        for record in records
    ):
        raise AssertionError(
            "Actual backend received identity headers or no matching production read."
        )


async def verify_proxy_headers(
    cluster: OwnedCluster, kubectl: str, directory: Path
) -> dict[str, Any]:
    await _apply(cluster, kubectl, "capture", capture_manifests())
    await _command(
        cluster,
        kubectl,
        "wait",
        "--for=condition=Ready",
        "pod/owned-capture",
        "--timeout=120s",
        timeout=130,
    )

    async def captures() -> tuple[dict[str, Any], ...]:
        text = await _command(cluster, kubectl, "logs", "pod/owned-capture", "--container=receiver")
        lines = text.splitlines()
        if len(lines) > 32:
            raise AssertionError("Header receiver exceeded its request bound.")
        return tuple(json.loads(line) for line in lines)

    # Deliberate direct noncredential sentinel proves that absence assertions fail.
    await _command(
        cluster,
        kubectl,
        "exec",
        "pod/owned-capture",
        "--",
        "wget",
        "-qO-",
        "--header=Authorization: synthetic-noncredential-control",
        "--header=Impersonate-User: synthetic-control",
        "http://127.0.0.1:9100/api/v1/query_range?end=0",
    )
    control = await captures()
    try:
        assert_backend_isolation(control)
    except AssertionError:
        (directory / "header-control-original-failure.json").write_text(
            json.dumps(
                {
                    "status": "expected assertion failure",
                    "synthetic_noncredential_control": True,
                    "assertion": "actual backend header absence",
                    "observed_presence": control,
                },
                indent=2,
            )
            + "\n"
        )
    else:
        raise AssertionError("Credential-isolation negative control did not fail.")
    requestor_token = (
        await _command(
            cluster, kubectl, "create", "token", "owned-capture-requestor", "--duration=10m"
        )
    ).strip()
    denied_token = (
        await _command(
            cluster, kubectl, "create", "token", "owned-capture-denied", "--duration=10m"
        )
    ).strip()
    baseline = len(control)
    observations = []
    for name, token, impersonated, expected in (
        ("bearer", requestor_token, None, None),
        ("impersonation", requestor_token, "owned-history-subject", None),
        ("invalid-bearer", "synthetic-invalid-bearer", None, 401),
        ("denied-impersonation", requestor_token, "owned-history-denied", 403),
        ("denied-proxy", denied_token, None, 403),
    ):
        data = yaml.safe_load(cluster.path.read_bytes())
        user: dict[str, Any] = {"token": token}
        if impersonated is not None:
            user.update(
                {
                    "as": impersonated,
                    "as-groups": ["owned-history-group"],
                    "as-uid": "owned-history-uid",
                    "as-user-extra": {"scope": ["owned-history-extra"]},
                }
            )
        data["users"][0]["user"] = user
        path = cluster.directory / ("capture-" + name + ".kubeconfig")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(yaml.safe_dump(data))
        catalog = load_catalog(ConnectionRequest(kubeconfig=str(path), context=cluster.context), {})
        client = KubernetesSession(catalog.select(cluster.context), 10)
        try:
            await client.open()
            backend = HistoryBackend(NAMESPACE, "owned-capture", 9100)
            if expected is None:
                snapshot = await HistoryReader().read(client, backend, NAMESPACE)
                assert snapshot.status in {HistoryStatus.VALID, HistoryStatus.PARTIAL}
                assert any(
                    point.value is not None for series in snapshot.series for point in series.points
                )
                current = await captures()
                delta = current[baseline:]
                assert len(delta) == 2
                assert_backend_isolation(delta)
            else:
                try:
                    await client.get_json(backend.path, params={"query": "vector(1)", "end": "0"})
                except HttpProblem as error:
                    assert error.status == expected
                else:
                    raise AssertionError("Expected API authentication/authorization denial.")
                current = await captures()
                assert len(current) == baseline
            observations.append(
                {
                    "identity": name,
                    "expected_http_status": expected,
                    "backend_requests": len(current) - baseline,
                }
            )
            baseline = len(current)
        finally:
            await client.close()
            path.unlink(missing_ok=True)
    # Source-derived TLS statement is deliberately separate from this HTTP capture.
    return {
        "actual_api_server_http_capture": observations,
        "negative_control_retained": True,
        "backend_client_certificate": "source-derived only; receiver lane uses HTTP",
        "backend_https_identity_verification": "default upstream source disables verification; not claimed by this fixture",
    }


def reset_numbers(document: object) -> tuple[str, ...]:
    """Retain only bounded numeric values from the separately labeled reset fixture."""
    if not isinstance(document, dict) or document.get("status") != "success":
        raise AssertionError("Synthetic reset query did not succeed.")
    results = document.get("data", {}).get("result", [])
    if not isinstance(results, list) or len(results) > 8:
        raise AssertionError("Synthetic reset query exceeded its series bound.")
    values = []
    for item in results:
        pair = item.get("value") if isinstance(item, dict) else None
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not isinstance(pair[1], str)
            or len(pair[1]) > 64
        ):
            raise AssertionError("Synthetic reset query did not return bounded numeric samples.")
        if item.get("metric", {}).get("fixture") != "synthetic-reset":
            raise AssertionError("Synthetic reset query returned another fixture identity.")
        numeric = Decimal(pair[1])
        if not numeric.is_finite() or not 0 <= numeric <= Decimal("1e20"):
            raise AssertionError("Synthetic reset query returned an invalid value.")
        values.append(pair[1])
    return tuple(values)


def scrape_error_kind(message: object) -> str:
    """Classify an owned target error without exporting its response, URL or paths."""
    if not isinstance(message, str) or not message:
        return "none"
    lowered = message.lower()
    for fragment, category in (
        ("connection refused", "connection-refused"),
        ("no such host", "dns"),
        ("timeout", "timeout"),
        ("deadline exceeded", "timeout"),
        ("content-type", "content-type"),
        ("text format parsing", "exposition-format"),
        ("expected", "exposition-format"),
        ("server returned http", "http-status"),
        ("eof", "connection-eof"),
    ):
        if fragment in lowered:
            return category
    return "other"


async def reset_diagnostics(
    client: KubernetesSession,
    cluster: OwnedCluster,
    kubectl: str,
    directory: Path,
    provider: Provider,
    stage: str,
) -> None:
    """Keep bounded object, target and actual responder evidence before owned cleanup."""
    evidence: dict[str, Any] = {
        "provider": provider,
        "stage": stage,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    try:
        async with asyncio.timeout(20):
            for name, path in {
                "service": f"/api/v1/namespaces/{NAMESPACE}/services/owned-reset",
                "deployment": f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/owned-reset",
                "monitor": f"/apis/monitoring.coreos.com/v1/namespaces/{NAMESPACE}/servicemonitors/owned-reset",
                "prometheus": f"/apis/monitoring.coreos.com/v1/namespaces/{NAMESPACE}/prometheuses/owned-stack",
            }.items():
                document = await client.get_json(path, max_bytes=1024 * 1024)
                spec = document.get("spec", {})
                evidence[name] = {
                    "labels": document.get("metadata", {}).get("labels", {}),
                    "spec": {
                        key: spec[key]
                        for key in (
                            "ports",
                            "selector",
                            "endpoints",
                            "namespaceSelector",
                            "serviceMonitorSelector",
                            "serviceMonitorNamespaceSelector",
                        )
                        if key in spec
                    },
                }
                if name == "deployment":
                    evidence[name]["status"] = {
                        key: document.get("status", {}).get(key)
                        for key in (
                            "replicas",
                            "readyReplicas",
                            "availableReplicas",
                            "updatedReplicas",
                        )
                    }
            endpoint_slices = await client.get_json(
                f"/apis/discovery.k8s.io/v1/namespaces/{NAMESPACE}/endpointslices",
                params={"labelSelector": "kubernetes.io/service-name=owned-reset", "limit": "8"},
                max_bytes=1024 * 1024,
            )
            evidence["endpoint_slices"] = [
                {
                    "ports": item.get("ports", []),
                    "endpoint_count": len(item.get("endpoints", [])),
                    "ready_count": sum(
                        endpoint.get("conditions", {}).get("ready") is True
                        for endpoint in item.get("endpoints", [])
                    ),
                }
                for item in endpoint_slices.get("items", [])[:8]
            ]
            pods = await client.get_json(
                f"/api/v1/namespaces/{NAMESPACE}/pods",
                params={"labelSelector": "owned-history=reset", "limit": "8"},
                max_bytes=1024 * 1024,
            )
            evidence["source_pods"] = [
                {
                    "name": pod.get("metadata", {}).get("name"),
                    "phase": pod.get("status", {}).get("phase"),
                    "conditions": [
                        {key: condition.get(key) for key in ("type", "status", "reason")}
                        for condition in pod.get("status", {}).get("conditions", [])[:8]
                    ],
                    "containers": [
                        {
                            "name": container.get("name"),
                            "ready": container.get("ready"),
                            "restart_count": container.get("restartCount"),
                            "state": {
                                state: {
                                    key: value.get(key)
                                    for key in ("reason", "exitCode", "startedAt", "finishedAt")
                                    if key in value
                                }
                                for state, value in container.get("state", {}).items()
                                if state in {"waiting", "running", "terminated"}
                            },
                        }
                        for container in pod.get("status", {}).get("containerStatuses", [])[:4]
                    ],
                }
                for pod in pods.get("items", [])[:8]
            ]
            targets = await client.get_json(
                HistoryBackend(NAMESPACE, "owned-stack-prometheus").path.removesuffix("query_range")
                + "targets",
                params={"state": "active"},
                max_bytes=1024 * 1024,
            )
            active = targets.get("data", {}).get("activeTargets", [])
            evidence["scrape_targets"] = [
                {
                    "health": target.get("health"),
                    "last_scrape": target.get("lastScrape"),
                    "scrape_interval": target.get("scrapeInterval"),
                    "scrape_timeout": target.get("scrapeTimeout"),
                    "last_error_kind": scrape_error_kind(target.get("lastError")),
                    "last_error_sha256": hashlib.sha256(
                        str(target.get("lastError", "")).encode()
                    ).hexdigest(),
                }
                for target in active[:128]
                if target.get("labels", {}).get("service") == "owned-reset"
                or target.get("discoveredLabels", {}).get("__meta_kubernetes_service_name")
                == "owned-reset"
            ][:8]
            log = await _command(
                cluster,
                kubectl,
                "logs",
                "deployment/owned-reset",
                "--container=exporter",
                "--tail=20",
                "--limit-bytes=4096",
                timeout=5,
            )
            evidence["source_log"] = "".join(
                character
                for character in log[:4096]
                if character in "\n\t" or 32 <= ord(character) <= 126
            )
            for name, url in (
                ("loopback", "http://127.0.0.1:9101/metrics"),
                ("service_dns", f"http://owned-reset.{NAMESPACE}.svc:9101/metrics"),
            ):
                output = await _command(
                    cluster,
                    kubectl,
                    "exec",
                    "deployment/owned-reset",
                    "--container=exporter",
                    "--",
                    "wget",
                    "-qO-",
                    "-T",
                    "3",
                    url,
                    timeout=5,
                )
                evidence[name] = {
                    "body_sha256": hashlib.sha256(output.encode()).hexdigest(),
                    "synthetic_samples": [
                        line
                        for line in output.splitlines()[:8]
                        if re.fullmatch(
                            r'kuberich_fixture_(?:counter_total|gauge)\{fixture="synthetic-reset"\} [0-9]+',
                            line,
                        )
                    ],
                }
    except Exception as error:
        evidence["diagnostic_failure_type"] = type(error).__name__
    finally:
        (directory / f"{provider}-reset-{stage}.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )


async def verify_reset(
    transport: ServiceHistoryTransport,
    provider: Provider,
    client: KubernetesSession,
    cluster: OwnedCluster,
    kubectl: str,
    directory: Path,
) -> dict[str, Any]:
    """Check real scrape/reset readiness before any long native creation warmup."""
    await reset_diagnostics(client, cluster, kubectl, directory, provider, "before")
    attempts = 0

    async def query(key: str, expression: str) -> tuple[str, ...]:
        record: dict[str, Any] = {"query": expression}
        parameters = {"query": expression, "timeout": "8s"}
        if provider == "thanos":
            parameters.update(dedup="true", partial_response="false", max_source_resolution="0s")
        try:
            values = reset_numbers(
                await transport.get_json("query", parameters, max_bytes=1024 * 1024)
            )
            record.update(result_count=len(values), values=values)
            return values
        except BaseException as error:
            record.update(
                error_type=type(error).__name__,
                http_status=error.status if isinstance(error, HttpProblem) else None,
            )
            raise
        finally:
            with (directory / "reset-query-observations.jsonl").open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "provider": provider,
                            "attempt": attempts,
                            "observed_at": datetime.now(UTC).isoformat(),
                            "queries": {key: record},
                        }
                    )
                    + "\n"
                )

    try:

        async def observed() -> bool:
            nonlocal attempts
            attempts += 1
            values = {}
            for key, expression in {
                "counter": 'kuberich_fixture_counter_total{fixture="synthetic-reset"}',
                "gauge": 'kuberich_fixture_gauge{fixture="synthetic-reset"}',
                "resets": 'resets(kuberich_fixture_counter_total{fixture="synthetic-reset"}[1m])',
            }.items():
                values[key] = await query(key, expression)
            return bool(values["gauge"]) and any(Decimal(value) >= 1 for value in values["resets"])

        await until(observed, timeout=180)
        rate = "rate_prometheus" if provider == "victoriametrics" else "rate"
        rates = await query(
            "rate", f'{rate}(kuberich_fixture_counter_total{{fixture="synthetic-reset"}}[1m])'
        )
        assert rates and all(0 < Decimal(value) < 10 for value in rates)
        await reset_diagnostics(client, cluster, kubectl, directory, provider, "ready")
        return {
            "fixture": "separate synthetic reset exporter; not native availability evidence",
            "function": rate,
            "observed_rates": rates,
            "actual_reset_observed": True,
        }
    except BaseException:
        await reset_diagnostics(client, cluster, kubectl, directory, provider, "failure")
        raise


async def _command(
    cluster: OwnedCluster,
    kubectl: str,
    *arguments: str,
    timeout: float = 60,
    namespace: str | None = NAMESPACE,
) -> str:
    if namespace != NAMESPACE and (
        namespace is not None or not arguments or arguments[0] != "apply"
    ):
        raise ValueError(
            "Only explicitly namespaced manifest application can omit the fixture namespace."
        )
    environment = dict(os.environ)
    environment["KUBECONFIG"] = str(cluster.path)
    return await parse_owned(
        lambda: run_owned(
            [
                kubectl,
                "--kubeconfig",
                str(cluster.path),
                "--context",
                cluster.context,
                *(["--namespace", namespace] if namespace is not None else []),
                *arguments,
            ],
            environment,
            timeout=timeout,
        )
    )


async def _apply(
    cluster: OwnedCluster, kubectl: str, name: str, documents: tuple[dict[str, Any], ...]
) -> None:
    path = cluster.directory / (name + ".yaml")
    explicit = []
    for document in documents:
        metadata = dict(document.get("metadata", {}))
        if document.get("kind") not in {
            "CustomResourceDefinition",
            "ClusterRole",
            "ClusterRoleBinding",
            "Namespace",
        }:
            metadata.setdefault("namespace", NAMESPACE)
            if metadata["namespace"] not in {NAMESPACE, "kube-system"}:
                raise ValueError(
                    "Provider manifests must use an explicit owned fixture or system namespace."
                )
        explicit.append({**document, "metadata": metadata})
    path.write_text(yaml.safe_dump_all(explicit))
    await _command(
        cluster,
        kubectl,
        "apply",
        "--server-side",
        "--field-manager=kuberich-history-verifier",
        "-f",
        str(path),
        timeout=120,
        namespace=None,
    )


async def until(operation: Callable[[], Any], *, timeout: float = 180) -> Any:
    async with asyncio.timeout(timeout):
        while True:
            result = await operation()
            if result:
                return result
            await asyncio.sleep(2)


def _samples(document: object) -> tuple[dict[str, str], ...]:
    if not isinstance(document, dict) or document.get("status") != "success":
        raise AssertionError("Provider query was not successful.")
    result = document.get("data", {}).get("result")
    if not isinstance(result, list) or len(result) > 128:
        raise AssertionError("Provider observation exceeded its sample bound.")
    return tuple(item.get("metric", {}) for item in result if isinstance(item, dict))


def native_value_summary(snapshot: HistorySnapshot) -> dict[str, dict[str, int | str | None]]:
    """Require actual parsed values independently of successful empty HTTP queries."""
    summary: dict[str, dict[str, int | str | None]] = {}
    for family in ("cpu", "memory"):
        values = [
            point.value
            for series in snapshot.series
            if series.key == family
            for point in series.points
            if point.value is not None
        ]
        summary[family] = {
            "observed_points": len(values),
            "positive_points": sum(value > 0 for value in values),
            "minimum": str(min(values)) if values else None,
            "maximum": str(max(values)) if values else None,
        }
    return summary


def rollout_comparison(
    historical: HistorySnapshot,
    projected: HistorySnapshot,
    old_uids: frozenset[str],
) -> dict[str, Any]:
    """Historical names retain old observations; young current UIDs cannot inherit them."""
    historical_membership, current = historical.membership_evidence, projected.membership_evidence
    assert historical_membership is not None and historical_membership.mode == "backend-history"
    assert historical_membership.status == "name-inferred"
    numbers = native_value_summary(historical)
    assert all(int(numbers[family]["positive_points"] or 0) > 0 for family in ("cpu", "memory"))
    assert (
        current is not None
        and current.mode == "current-members"
        and current.status == "current-only"
    )
    assert current.observed_at is not None and current.members
    assert all(member.uid is not None and member.uid not in old_uids for member in current.members)
    assert projected.end is not None and all(
        member.created_at is not None and (projected.end - member.created_at).total_seconds() < 300
        for member in current.members
    )
    assert not any(
        point.value is not None for series in projected.series for point in series.points
    )
    return {
        "historical_native_values": numbers,
        "historical_membership_status": historical_membership.status,
        "historical_limit": "Historical owner names are not parent-owner UID proof",
        "current_capture_time": current.observed_at.isoformat(),
        "current_member_uids": [member.uid for member in current.members],
        "replaced_current_uids": sorted(old_uids),
        "young_current_projection": "Explicit creation/rate gaps; removed historical members excluded",
    }


async def verify(
    cluster: OwnedCluster, documents: tuple[dict[str, Any], ...], directory: Path, kubectl: str
) -> dict[str, Any]:
    before = cluster.path.read_bytes()
    await _command(cluster, kubectl, "create", "namespace", NAMESPACE)
    crds = tuple(item for item in documents if item.get("kind") == "CustomResourceDefinition")
    await _apply(cluster, kubectl, "provider-crds", crds)
    for crd in crds:
        await _command(
            cluster,
            kubectl,
            "wait",
            "--for=condition=Established",
            "crd/" + crd["metadata"]["name"],
            "--timeout=90s",
            timeout=100,
        )
    await _apply(
        cluster, kubectl, "providers", tuple(item for item in documents if item not in crds)
    )
    await _apply(cluster, kubectl, "workloads", fixture_manifests())
    await _apply(cluster, kubectl, "synthetic-reset-source", reset_manifests())
    header_evidence = await verify_proxy_headers(cluster, kubectl, directory)
    (directory / "actual-header-evidence.json").write_text(
        json.dumps(header_evidence, indent=2) + "\n"
    )
    await _command(
        cluster,
        kubectl,
        "rollout",
        "status",
        "deployment/owned-stack-operator",
        "--timeout=180s",
        timeout=190,
    )
    await _command(
        cluster,
        kubectl,
        "rollout",
        "status",
        "deployment/owned-workload",
        "--timeout=120s",
        timeout=130,
    )
    await _command(
        cluster,
        kubectl,
        "wait",
        "--for=condition=Ready",
        "pod/owned-recreated",
        "--timeout=120s",
        timeout=130,
    )
    catalog = load_catalog(
        ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context), {}
    )
    client = KubernetesSession(catalog.select(cluster.context), 10)
    await client.open()
    workspaces: list[HistoryWorkspace] = []
    reset_transports: list[tuple[Provider, ServiceHistoryTransport]] = []
    try:
        reader = ResourceReader(client)
        discovery = await reader.discover()
        identity = SessionIdentity(cluster.context, 1)
        providers: tuple[tuple[Provider, str, int], ...] = (
            ("prometheus", "owned-stack-prometheus", 9090),
            ("victoriametrics", "owned-vm-server", 8428),
            ("thanos", "owned-thanos", 10902),
        )
        observations: dict[str, Any] = {}
        reset_evidence: dict[str, Any] = {}
        for provider, service_name, port in providers:
            backend = HistoryBackend(NAMESPACE, service_name, port)
            selected = await reader.get(discovery.find("services"), service_name, NAMESPACE)
            assert selected.uid is not None
            transport = ServiceHistoryTransport(client, backend, selected.uid)
            reset_transports.append((provider, transport))

            async def ready(transport: ServiceHistoryTransport = transport) -> bool:
                try:
                    result = await transport.get_json(
                        "query",
                        {
                            "query": 'topk(1,container_memory_working_set_bytes{pod!="",container!="",container!="POD"})',
                            "timeout": "8s",
                        },
                        max_bytes=1024 * 1024,
                    )
                    return bool(_samples(result))
                except (ConnectionProblem, AssertionError):
                    return False

            await until(ready, timeout=240)
            reset_evidence[provider] = await verify_reset(
                transport, provider, client, cluster, kubectl, directory
            )
        for (provider, service_name, port), (_, transport) in zip(
            providers, reset_transports, strict=True
        ):
            backend = HistoryBackend(NAMESPACE, service_name, port)
            probes = {}
            for key, expression in {
                "cadvisor-cpu": 'topk(4,container_cpu_usage_seconds_total{pod!="",container!="",container!="POD"})',
                "cadvisor-memory": 'topk(4,container_memory_working_set_bytes{pod!="",container!="",container!="POD"})',
                "cadvisor-network": 'topk(4,container_network_receive_bytes_total{pod!="",container="POD"})',
                "cadvisor-filesystem": 'topk(4,container_fs_usage_bytes{pod!="",container!="",container!="POD"})',
                "node-mapping": "topk(4,node_uname_info)",
                "node-filesystem": "topk(4,node_filesystem_size_bytes)",
                "ksm-pod": "topk(4,kube_pod_info)",
                "ksm-owner": "topk(4,kube_pod_owner)",
            }.items():
                probes[key] = _samples(
                    await transport.get_json(
                        "query", {"query": expression, "timeout": "8s"}, max_bytes=1024 * 1024
                    )
                )
            assert (
                probes["cadvisor-cpu"]
                and probes["cadvisor-memory"]
                and probes["node-mapping"]
                and probes["ksm-pod"]
            )
            (directory / (provider + "-native-probes.json")).write_text(
                json.dumps(probes, indent=2) + "\n"
            )
            workspace = HistoryWorkspace(
                client,
                discovery,
                identity,
                AccessPolicy(False),
                lambda: True,
                observed_session=lambda: identity,
            )
            workspaces.append(workspace)
            options = HistoryOptions(backend, provider=provider)
            node = (await reader.list(discovery.find("nodes"), max_items=2)).items[0]
            pod = await reader.get(discovery.find("pods"), "owned-recreated", NAMESPACE)
            workload = await reader.get(
                discovery.find("deployments", group="apps"), "owned-workload", NAMESPACE
            )
            scopes = [HistoryScope(identity, "cluster", NAMESPACE)]
            for kind, record, resource_name, group in (
                ("node", node, "nodes", ""),
                ("pod", pod, "pods", ""),
                ("workload", workload, "deployments", "apps"),
                ("container", pod, "pods", ""),
            ):
                resource = discovery.find(resource_name, group=group)
                assert record.uid is not None
                target = ResourceTarget(
                    identity,
                    group,
                    resource_name,
                    record.namespace,
                    record.name,
                    record.uid,
                    "app" if kind == "container" else None,
                )
                scopes.append(
                    HistoryScope(
                        identity,
                        cast(ScopeKind, kind),
                        record.namespace,
                        target,
                        resource,
                        record.created_at,
                        "containers" if kind == "container" else None,
                    )
                )
            snapshots = []
            for scope in scopes:

                async def native_ready(
                    scope: HistoryScope = scope,
                    workspace: HistoryWorkspace = workspace,
                    options: HistoryOptions = options,
                    provider: Provider = provider,
                ) -> bool:
                    start, end, step = history_window(datetime.now(UTC), 900)
                    snapshot = await workspace.collect(
                        HistoryRequest(
                            uuid4(),
                            scope,
                            options,
                            start,
                            end,
                            step,
                            ("cpu", "memory"),
                            workspace.config_revision,
                        )
                    )
                    summary = native_value_summary(snapshot)
                    with (directory / "native-value-warmup.jsonl").open("a") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "provider": provider,
                                    "scope": scope.kind,
                                    "captured_creation": scope.created_at.isoformat()
                                    if scope.created_at
                                    else None,
                                    "observed_at": snapshot.observed_at.isoformat()
                                    if snapshot.observed_at
                                    else None,
                                    "status": str(snapshot.status),
                                    "numeric_values": summary,
                                    "source_status": snapshot.source_status,
                                }
                            )
                            + "\n"
                        )
                    if snapshot.status not in {
                        HistoryStatus.VALID,
                        HistoryStatus.PARTIAL,
                        HistoryStatus.NO_DATA,
                    }:
                        raise AssertionError(
                            "Actual native value query failed before availability qualification."
                        )
                    return all(
                        int(summary[family]["positive_points"] or 0) > 0
                        for family in ("cpu", "memory")
                    )

                await until(native_ready, timeout=360)
                for seconds in (900, 1800, 3600, 10800, 21600, 43200, 86400):
                    start, end, step = history_window(datetime.now(UTC), seconds)
                    request = HistoryRequest(
                        uuid4(),
                        scope,
                        options,
                        start,
                        end,
                        step,
                        ("cpu", "memory", "network", "filesystem"),
                        workspace.config_revision,
                    )
                    snapshot = await workspace.collect(request)
                    with (directory / "collection-observations.jsonl").open("a") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "provider": provider,
                                    "scope": scope.kind,
                                    "range_seconds": seconds,
                                    "status": str(snapshot.status),
                                    "source_status": snapshot.source_status,
                                    "notices": [notice.code for notice in snapshot.notices],
                                }
                            )
                            + "\n"
                        )
                    if snapshot.status not in {
                        HistoryStatus.VALID,
                        HistoryStatus.PARTIAL,
                        HistoryStatus.NO_DATA,
                    }:
                        raise AssertionError(
                            f"Actual {provider}/{scope.kind}/{seconds} collection failed: {snapshot.status}"
                        )
                    snapshots.append(
                        {
                            "scope": scope.kind,
                            "range_seconds": seconds,
                            "status": str(snapshot.status),
                            "series": len(snapshot.series),
                            "points": sum(len(series.points) for series in snapshot.series),
                            "nonempty": sum(
                                point.value is not None
                                for series in snapshot.series
                                for point in series.points
                            ),
                            "source_status": snapshot.source_status,
                            "notices": [notice.code for notice in snapshot.notices],
                        }
                    )
            observations[provider] = {
                "native_source_labels": probes,
                "collections": snapshots,
                "measurement_scope": "Native cAdvisor/node-exporter/KSM; absent metric families remain absent",
                "provider_hint": provider,
            }
            try:
                build = await transport.get_json("status/buildinfo", {}, max_bytes=1024 * 1024)
            except HttpProblem as problem:
                if problem.status != 404:
                    raise
                build = {}
            observations[provider]["compatibility_build_info"] = (
                {
                    key: value
                    for key, value in build.get("data", {}).items()
                    if key in {"version", "revision", "goVersion"} and isinstance(value, str)
                }
                if isinstance(build, dict)
                else {}
            )
        old_pod = await reader.get(discovery.find("pods"), "owned-recreated", NAMESPACE)
        previous_members = await reader.list(
            discovery.find("pods"),
            NAMESPACE,
            query=ResourceQuery(label_selector="owned-history=workload"),
            max_items=8,
        )
        previous_uids = frozenset(pod.uid for pod in previous_members.items if pod.uid is not None)
        assert previous_uids
        await _command(cluster, kubectl, "rollout", "restart", "deployment/owned-workload")
        await _command(
            cluster,
            kubectl,
            "rollout",
            "status",
            "deployment/owned-workload",
            "--timeout=120s",
            timeout=130,
        )
        rollout_evidence: dict[str, Any] = {}
        for (provider, service_name, port), workspace in zip(providers, workspaces, strict=True):
            root_resource = discovery.find("deployments", group="apps")
            root_record = await reader.get(root_resource, "owned-workload", NAMESPACE)
            assert root_record.uid is not None
            historical_scope = HistoryScope(
                identity,
                "workload",
                NAMESPACE,
                ResourceTarget(
                    identity, "apps", "deployments", NAMESPACE, root_record.name, root_record.uid
                ),
                root_resource,
                root_record.created_at,
            )
            options = HistoryOptions(
                HistoryBackend(NAMESPACE, service_name, port), provider=provider
            )
            start, end, step = history_window(datetime.now(UTC), 900)
            historical = await workspace.collect(
                HistoryRequest(
                    uuid4(),
                    historical_scope,
                    options,
                    start,
                    end,
                    step,
                    ("cpu", "memory"),
                    workspace.config_revision,
                )
            )
            projected: HistorySnapshot | None = None

            async def new_members_only(
                workspace: HistoryWorkspace = workspace,
                scope: HistoryScope = historical_scope,
                options: HistoryOptions = options,
            ) -> bool:
                nonlocal projected
                start, end, step = history_window(datetime.now(UTC), 900)
                projected = await workspace.collect(
                    HistoryRequest(
                        uuid4(),
                        replace(scope, membership="current-members"),
                        options,
                        start,
                        end,
                        step,
                        ("cpu", "memory"),
                        workspace.config_revision,
                    )
                )
                current = projected.membership_evidence
                return (
                    current is not None
                    and bool(current.members)
                    and all(member.uid not in previous_uids for member in current.members)
                )

            await until(new_members_only, timeout=30)
            assert projected is not None
            rollout_evidence[provider] = rollout_comparison(historical, projected, previous_uids)
            (directory / "rollout-membership-comparison.json").write_text(
                json.dumps(rollout_evidence, indent=2) + "\n"
            )
        await _command(
            cluster, kubectl, "delete", "pod/owned-recreated", "--wait=true", "--timeout=60s"
        )
        await _apply(cluster, kubectl, "recreated-pod", (fixture_manifests()[1],))
        await _command(
            cluster,
            kubectl,
            "wait",
            "--for=condition=Ready",
            "pod/owned-recreated",
            "--timeout=120s",
            timeout=130,
        )
        new_pod = await reader.get(discovery.find("pods"), "owned-recreated", NAMESPACE)
        assert old_pod.uid != new_pod.uid
        assert old_pod.uid is not None
        pod_resource = discovery.find("pods")
        old_scope = HistoryScope(
            identity,
            "pod",
            NAMESPACE,
            ResourceTarget(identity, "", "pods", NAMESPACE, old_pod.name, old_pod.uid),
            pod_resource,
            old_pod.created_at,
        )
        start, end, step = history_window(datetime.now(UTC), 900)
        rejected = await workspaces[0].collect(
            HistoryRequest(
                uuid4(),
                old_scope,
                HistoryOptions(HistoryBackend(NAMESPACE, "owned-stack-prometheus")),
                start,
                end,
                step,
                ("cpu", "memory"),
                workspaces[0].config_revision,
            )
        )
        assert rejected.status is HistoryStatus.CONFIGURATION_CONFLICT and not rejected.series
        await _command(cluster, kubectl, "scale", "deployment/owned-reset", "--replicas=0")
        for provider, transport in reset_transports:

            async def absent(transport: ServiceHistoryTransport = transport) -> bool:
                response = await transport.get_json(
                    "query",
                    {
                        "query": 'absent(kuberich_fixture_gauge{fixture="synthetic-reset"})',
                        "timeout": "8s",
                    },
                    max_bytes=1024 * 1024,
                )
                return bool(_samples(response))

            await until(absent, timeout=180)
            reset_evidence[provider]["source_outage_observed"] = True
            await transport.close()
        missing = await HistoryReader().read(
            client, HistoryBackend(NAMESPACE, "owned-absent-backend"), NAMESPACE
        )
        assert missing.status is HistoryStatus.UNAVAILABLE
        version = await client.get_json("/version")
        api_pods = await reader.list(discovery.find("pods"), "kube-system", max_items=64)
        api_arguments = [
            argument
            for pod in api_pods.items
            for container in pod.manifest.get("spec", {}).get("containers", [])
            if container.get("name") == "kube-apiserver"
            for argument in container.get("command", [])
            if isinstance(argument, str) and argument.startswith("--feature-gates=")
        ]
        assert cluster.path.read_bytes() == before
        inventory = await _command(cluster, kubectl, "get", "pods", "-o", "json")
        observed_pods = json.loads(inventory)["items"]
        observed_images = sorted(
            {
                container["image"]
                for pod in observed_pods
                for container in pod["spec"].get("containers", [])
            }
        )
        assert all("@sha256:" in image for image in observed_images)
        return {
            "node_image": NODE_IMAGE,
            "node_ids": cluster.node_ids,
            "provider_images": IMAGES,
            "runtime_images": observed_images,
            "provider_observations": observations,
            "synthetic_reset_and_outage": reset_evidence,
            "actual_service_proxy_headers": header_evidence,
            "api_server_version": version.get("gitVersion"),
            "api_server_feature_gate_arguments": api_arguments,
            "replaced_pod_request_rejected": True,
            "absent_backend": str(missing.status),
            "same_name_pod_recreated": True,
            "workload_rollout": True,
            "rollout_membership_comparison": rollout_evidence,
            "caller_kubeconfig_unchanged": True,
        }
    finally:
        for workspace in workspaces:
            await workspace.close()
        for _, transport in reset_transports:
            await transport.close()
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.evidence.exists():
        raise ValueError("Use a fresh evidence path; earlier outcomes must be preserved.")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"status": "failed", "owned_cluster_deleted": False}
    source_root = Path(__file__).resolve().parent.parent
    source_paths = (
        *sorted((source_root / "src/kuberich").rglob("*.py")),
        source_root / "scripts/verify_history_kind.py",
        source_root / "scripts/owned_kind.py",
        source_root / "pyproject.toml",
        source_root / "uv.lock",
    )

    def input_hashes() -> dict[str, str]:
        return {
            str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        }

    result["input_hashes"] = input_hashes()
    started = time.monotonic()
    try:
        documents = prepare_charts(args.evidence.parent / "charts", args.helm)
        rendered_images(
            (*documents, *fixture_manifests(), *capture_manifests(), *reset_manifests())
        )
        if args.prepare_only:
            result["status"] = "prepared"
            result["qualification"] = "No Kubernetes or Docker operations executed"
            return
        failure: BaseException | None = None
        with owned_cluster(args.kind, docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(
                    asyncio.run(verify(cluster, documents, args.evidence.parent, args.kubectl))
                )
            except BaseException as problem:
                failure = problem
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes() == result["input_hashes"]
        if failure is not None:
            raise failure
        if not result["private_directory_deleted"] or not result["inputs_unchanged"]:
            raise AssertionError("Owned fixture cleanup or frozen source validation failed.")
        result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
