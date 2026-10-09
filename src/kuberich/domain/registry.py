"""Standard resource definitions and safe, typed table summaries, without SDK models."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import cast

from kuberich.domain.pods import age
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.views import ResourceSelection
from kuberich.errors import AppError

SortValue = str | int | float | Decimal | tuple[int, float]


@dataclass(frozen=True)
class Value:
    text: str
    sort: SortValue | None


@dataclass(frozen=True)
class Column:
    key: str
    numeric: bool = False


@dataclass(frozen=True)
class ResourceDefinition:
    name: str
    group: str
    namespaced: bool
    aliases: tuple[str, ...]
    fields: tuple[Column, ...]

    @property
    def columns(self) -> tuple[Column, ...]:
        return (
            *((Column("namespace"),) if self.namespaced else ()),
            Column("name"),
            *self.fields,
            Column("age", True),
        )

    @property
    def selection(self) -> ResourceSelection:
        # Discovery chooses the served/preferred version, never a guessed endpoint.
        return ResourceSelection(self.name, self.group)


def _definition(
    name: str, group: str, aliases: str, fields: str, *, namespaced: bool = True
) -> ResourceDefinition:
    return ResourceDefinition(
        name,
        group,
        namespaced,
        tuple(aliases.split()),
        tuple(Column(field.rstrip("#"), field.endswith("#")) for field in fields.split()),
    )


STANDARD_RESOURCES = (
    _definition("deployments", "apps", "deploy deployment", "ready# desired# updated# available#"),
    _definition("replicasets", "apps", "rs replicaset", "desired# current# ready#"),
    _definition("statefulsets", "apps", "sts statefulset", "ready# desired# current# updated#"),
    _definition("daemonsets", "apps", "ds daemonset", "desired# current# ready# available#"),
    _definition("jobs", "batch", "job", "status succeeded# completions# active# failed#"),
    _definition("cronjobs", "batch", "cj cronjob", "schedule suspend active# last-schedule"),
    _definition("services", "", "svc service", "type cluster-ip external-ip ports"),
    _definition("endpoints", "", "ep endpoint", "ready# not-ready# ports"),
    _definition("ingresses", "networking.k8s.io", "ing ingress", "class hosts address"),
    _definition("configmaps", "", "cm configmap", "data# binary#"),
    _definition("secrets", "", "sec secret", "type data#"),
    _definition("nodes", "", "no node", "status roles version", namespaced=False),
    _definition(
        "persistentvolumeclaims", "", "pvc", "status volume capacity# access-modes storage-class"
    ),
    _definition(
        "persistentvolumes",
        "",
        "pv",
        "capacity# access-modes reclaim status claim storage-class",
        namespaced=False,
    ),
    _definition(
        "storageclasses",
        "storage.k8s.io",
        "sc storageclass",
        "provisioner reclaim binding expansion",
        namespaced=False,
    ),
)
RESOURCE_ALIASES = {
    alias: definition
    for definition in STANDARD_RESOURCES
    for alias in (definition.name, *definition.aliases)
}


def resource_selection(name: str) -> ResourceSelection:
    definition = RESOURCE_ALIASES.get(name)
    return definition.selection if definition is not None else ResourceSelection(name)


@dataclass(frozen=True)
class ResourceRow:
    uid: str
    namespace: str
    name: str
    values: tuple[Value, ...]
    created_at: datetime | None

    def cells(self, now: datetime) -> tuple[str, ...]:
        return (*tuple(value.text for value in self.values[:-1]), age(self.created_at, now))


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _objects(value: object) -> tuple[dict[str, object], ...]:
    return tuple(_object(item) for item in value) if isinstance(value, list) else ()


def _text(value: object) -> Value:
    text = value[:256] if isinstance(value, str) and value else "—"
    return Value(text, text.casefold() if text != "—" else None)


def _number(value: object) -> Value:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63:
        return Value(str(value), value)
    return Value("—", None)


def _status_count(status: dict[str, object], name: str) -> Value:
    # Kubernetes omits zero counters. A completely missing status stays unknown.
    return _number(status.get(name, 0) if status else None)


def _boolean(value: object) -> Value:
    return Value(str(value).lower(), int(value)) if isinstance(value, bool) else Value("—", None)


def _joined(value: object) -> Value:
    if not isinstance(value, list):
        return _text(None)
    return _text(",".join(item[:256] for item in value[:32] if isinstance(item, str)))


def _ports(value: object) -> Value:
    return _text(
        ",".join(
            f"{_number(port.get('port')).text}/{_text(port.get('protocol', 'TCP')).text}"
            for port in _objects(value)[:32]
        )
    )


def _addresses(status: dict[str, object]) -> Value:
    return _joined(
        [
            entry.get("ip") or entry.get("hostname")
            for entry in _objects(_object(status.get("loadBalancer")).get("ingress"))
        ]
    )


def _external_addresses(spec: dict[str, object], status: dict[str, object]) -> Value:
    load_balancer = _addresses(status)
    external = spec.get("externalIPs")
    return _joined(
        [
            *((load_balancer.text,) if load_balancer.sort is not None else ()),
            *(external if isinstance(external, list) else ()),
        ]
    )


_QUANTITY = re.compile(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))([numkKMGTPE]|[KMGTPE]i|[eE][+-]?\d+)?")
_SCALES = {
    "": 0,
    "n": -9,
    "u": -6,
    "m": -3,
    "k": 3,
    "K": 3,
    "M": 6,
    "G": 9,
    "T": 12,
    "P": 15,
    "E": 18,
}


def quantity(value: object) -> Value:
    """Bound storage quantities before Decimal arithmetic; compare bytes, not spelling."""
    if not isinstance(value, str) or len(value) > 64:
        return Value("—", None)
    match = _QUANTITY.fullmatch(value)
    if match is None:
        return Value(value[:64] or "—", None)
    number, suffix = match.groups()
    suffix = suffix or ""
    if suffix.endswith("i"):
        scale = Decimal(1024) ** ("KMGTPE".index(suffix[0]) + 1)
    else:
        exponent = (
            int(suffix[1:])
            if suffix.startswith(("e", "E")) and len(suffix) > 1
            else _SCALES[suffix]
        )
        if abs(exponent) > 30:
            return Value(value, None)
        scale = Decimal(10) ** exponent
    with localcontext() as context:
        context.prec = 100
        return Value(value, Decimal(number) * scale)


def _timestamp(value: object) -> Value:
    text = _text(value)
    try:
        parsed = datetime.fromisoformat(text.text)
    except ValueError:
        return Value(text.text, None)
    return Value(text.text, parsed.timestamp() if parsed.tzinfo is not None else None)


def _specific(name: str, manifest: dict[str, object]) -> dict[str, Value]:
    spec, status = _object(manifest.get("spec")), _object(manifest.get("status"))
    if name in {"deployments", "replicasets", "statefulsets", "daemonsets"}:
        daemon = name == "daemonsets"
        return {
            "desired": _status_count(status, "desiredNumberScheduled")
            if daemon
            else _number(spec.get("replicas")),
            "current": _status_count(
                status,
                "currentNumberScheduled"
                if daemon
                else "currentReplicas"
                if name == "statefulsets"
                else "replicas",
            ),
            "ready": _status_count(status, "numberReady" if daemon else "readyReplicas"),
            "updated": _status_count(status, "updatedReplicas"),
            "available": _status_count(
                status, "numberAvailable" if daemon else "availableReplicas"
            ),
        }
    if name == "jobs":
        conditions = _objects(status.get("conditions"))
        outcome = next(
            (
                entry.get("type")
                for entry in conditions
                if entry.get("type") in {"Complete", "Failed"} and entry.get("status") == "True"
            ),
            None,
        )
        return {
            "status": _text(
                outcome
                or (
                    "Suspended"
                    if spec.get("suspend") is True
                    else "Active"
                    if status.get("active")
                    else "Pending"
                )
            ),
            "completions": _number(spec.get("completions")),
            **{key: _status_count(status, key) for key in ("succeeded", "active", "failed")},
        }
    if name == "cronjobs":
        return {
            "schedule": _text(spec.get("schedule")),
            "suspend": _boolean(spec.get("suspend")),
            "active": _number(len(_objects(status.get("active")))),
            "last-schedule": _timestamp(status.get("lastScheduleTime")),
        }
    if name == "services":
        return {
            "type": _text(spec.get("type")),
            "cluster-ip": _text(spec.get("clusterIP")),
            "external-ip": _text(spec.get("externalName"))
            if spec.get("type") == "ExternalName"
            else _external_addresses(spec, status),
            "ports": _ports(spec.get("ports")),
        }
    if name == "endpoints":
        subsets = _objects(manifest.get("subsets"))
        return {
            "ready": _number(sum(len(_objects(subset.get("addresses"))) for subset in subsets)),
            "not-ready": _number(
                sum(len(_objects(subset.get("notReadyAddresses"))) for subset in subsets)
            ),
            "ports": _ports([port for subset in subsets for port in _objects(subset.get("ports"))]),
        }
    if name == "ingresses":
        return {
            "class": _text(spec.get("ingressClassName")),
            "hosts": _joined([rule.get("host", "*") for rule in _objects(spec.get("rules"))]),
            "address": _addresses(status),
        }
    if name in {"configmaps", "secrets"}:
        # Payload values never enter rows, filtering, or cached display values.
        return {
            "data": _number(len(_object(manifest.get("data")))),
            "binary": _number(len(_object(manifest.get("binaryData")))),
            "type": _text(manifest.get("type")),
        }
    if name == "nodes":
        ready = next(
            (
                entry.get("status")
                for entry in _objects(status.get("conditions"))
                if entry.get("type") == "Ready"
            ),
            None,
        )
        labels = _object(_object(manifest.get("metadata")).get("labels"))
        roles = sorted(
            key.removeprefix("node-role.kubernetes.io/")
            for key in labels
            if key.startswith("node-role.kubernetes.io/")
        )
        return {
            "status": _text(
                ("Ready" if ready == "True" else "NotReady" if ready == "False" else "Unknown")
                + (",SchedulingDisabled" if spec.get("unschedulable") is True else "")
            ),
            "roles": _joined(roles),
            "version": _text(_object(status.get("nodeInfo")).get("kubeletVersion")),
        }
    if name in {"persistentvolumeclaims", "persistentvolumes"}:
        capacity = _object((status if name == "persistentvolumeclaims" else spec).get("capacity"))
        claim = _object(spec.get("claimRef"))
        return {
            "status": _text(status.get("phase")),
            "volume": _text(spec.get("volumeName")),
            "capacity": quantity(capacity.get("storage")),
            "access-modes": _joined(spec.get("accessModes")),
            "storage-class": _text(spec.get("storageClassName")),
            "reclaim": _text(spec.get("persistentVolumeReclaimPolicy")),
            "claim": _text(
                f"{claim.get('namespace')}/{claim.get('name')}"
                if claim.get("name") and claim.get("namespace")
                else None
            ),
        }
    return {
        "provisioner": _text(manifest.get("provisioner")),
        "reclaim": _text(manifest.get("reclaimPolicy")),
        "binding": _text(manifest.get("volumeBindingMode")),
        "expansion": _boolean(manifest.get("allowVolumeExpansion")),
    }


def resource_row(record: ResourceRecord, definition: ResourceDefinition) -> ResourceRow:
    if record.uid is None:
        raise AppError("Resource tables require Kubernetes UID identity.")
    specific = _specific(definition.name, record.manifest)
    fields = {
        "namespace": _text(record.namespace),
        "name": _text(record.name),
        **specific,
        "age": Value("—", -record.created_at.timestamp() if record.created_at else None),
    }
    return ResourceRow(
        record.uid,
        record.namespace or "—",
        record.name,
        tuple(fields[column.key] for column in definition.columns),
        record.created_at,
    )


def order_resources(
    rows: tuple[ResourceRow, ...], index: int, descending: bool = False
) -> tuple[ResourceRow, ...]:
    stable = sorted(rows, key=lambda row: (row.namespace, row.name, row.uid))
    known = [row for row in stable if row.values[index].sort is not None]
    unknown = [row for row in stable if row.values[index].sort is None]

    def key(row: ResourceRow) -> SortValue:
        return cast(SortValue, row.values[index].sort)

    return (*sorted(known, key=key, reverse=descending), *unknown)
