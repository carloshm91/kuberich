"""Fixed literal query profiles, bounded matrices and honest historical evidence."""

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

from kuberich.domain.history import (
    MAX_HISTORY_BODY_BYTES,
    MAX_HISTORY_LABELS,
    MAX_HISTORY_MEMBERS,
    MAX_HISTORY_NOTICES,
    MAX_SERIES_POINTS,
    MAX_SNAPSHOT_POINTS,
    MAX_SNAPSHOT_SERIES,
    HistoryNotice,
    HistoryQueryPlan,
    HistoryRequest,
    HistorySeries,
    MembershipEvidence,
    MetricFamily,
    ParsedHistory,
    PointQuality,
    QuerySpec,
    SourceStatus,
    _matcher,
    parse_history_range,
)
from kuberich.errors import AppError


def _selector(
    request: HistoryRequest,
    source: str,
    extra: tuple[tuple[str, str], ...] = (),
    predicates: tuple[str, ...] = (),
) -> str:
    endpoint = request.options.endpoint
    pairs = (
        endpoint.matchers
        if source == "container"
        else request.options.node_matchers
        if source == "node"
        else request.options.state_matchers
    )
    labels = dict(pairs)
    if endpoint.cluster_label is not None:
        extra = ((endpoint.cluster_label, cast(str, endpoint.cluster_value)), *extra)
    if source != "node" and request.scope.namespace is not None:
        extra = (("namespace", request.scope.namespace), *extra)
    for name, value in extra:
        _matcher(name, value)
        if name in labels and labels[name] != value:
            raise AppError("History scope conflicts with a configured source selector.")
        labels[name] = value
    for predicate in predicates:
        name = predicate.split("!", 1)[0].split("=", 1)[0]
        if name in labels and (
            "!=" not in predicate
            or predicate == f"{name}!={json.dumps(labels[name], ensure_ascii=False)}"
        ):
            raise AppError("History selector conflicts with a fixed measurement predicate.")
    values = [
        *predicates,
        *(
            f"{name}={json.dumps(value, ensure_ascii=False)}"
            for name, value in sorted(labels.items())
        ),
    ]
    return "{" + ",".join(values) + "}"


def _unique(expression: str, labels: str) -> str:
    return f"({expression} and on({labels}) (count by({labels}) ({expression}) == 1))"


def _state_members(request: HistoryRequest) -> str:
    scope, target = request.scope, request.scope.target
    if scope.kind == "workload":
        assert target is not None and scope.resource is not None
        kind = scope.resource.kind
        intermediate = {
            "Deployment": ("ReplicaSet", "replicaset", "kube_replicaset_owner"),
            "CronJob": ("Job", "job_name", "kube_job_owner"),
        }.get(kind)
        owner_kind = intermediate[0] if intermediate is not None else kind
        extra: tuple[tuple[str, str], ...] = (
            ("owner_kind", owner_kind),
            ("owner_is_controller", "true"),
        )
        if intermediate is None:
            extra += (("owner_name", target.name),)
        pods = "kube_pod_owner" + _selector(request, "state", extra)
        if intermediate is not None:
            _, label, metric = intermediate
            parents = metric + _selector(
                request,
                "state",
                (
                    ("owner_kind", kind),
                    ("owner_name", target.name),
                    ("owner_is_controller", "true"),
                ),
            )
            parent = f"max by(namespace,{label}) ({parents})"
            renamed = f'label_replace({parent},"owner_name","$1","{label}","(.*)")'
            pods = f"({pods} * on(namespace,owner_name) group_left() {renamed})"
        return f"max by(namespace,pod,uid) ({pods})"
    extra = (
        (("pod", target.name),) if scope.kind in {"pod", "container"} and target is not None else ()
    )
    return "max by(namespace,pod,uid) (kube_pod_info" + _selector(request, "state", extra) + ")"


def _member_mask(request: HistoryRequest, membership: MembershipEvidence) -> str | None:
    if request.scope.kind != "workload":
        return None
    if request.scope.membership == "backend-history":
        members = _state_members(request)
        created = "max by(namespace,pod,uid) (kube_pod_created" + _selector(request, "state") + ")"
        eligible = f"({members} and on(namespace,pod,uid) ({created} <= time() - {request.options.rate_window_seconds}))"
        return f"(max by(namespace,pod) ({eligible}) and on(namespace,pod) (count by(namespace,pod) ({members}) == 1))"
    if membership.mode != "current-members" or membership.status == "unavailable":
        return "vector(0) < 0"
    terms = []
    for member in membership.members:
        if member.namespace != request.scope.namespace:
            raise AppError("Current history members belong to another namespace.")
        # Explicit literal alternatives; no owner/name regular-expression inference.
        namespace, pod = json.dumps(member.namespace), json.dumps(member.pod)
        value = f'label_replace(label_replace(vector(1),"namespace",{namespace},"",""),"pod",{pod},"","")'
        if member.created_at is not None:
            boundary = (
                math.ceil(member.created_at.timestamp()) + request.options.rate_window_seconds
            )
            value = f"({value} and on() (vector(time()) >= {boundary}))"
        terms.append(value)
    return "(" + " or ".join(terms) + ")" if terms else "vector(0) < 0"


def _container_source(
    request: HistoryRequest, metric: str, *, network: bool = False, filesystem: bool = False
) -> str:
    target = request.scope.target
    extra: tuple[tuple[str, str], ...] = ()
    if request.scope.kind in {"pod", "container"}:
        assert target is not None
        extra = (("pod", target.name),)
    predicates: tuple[str, ...]
    if network:
        # This fixed profile accepts only the explicit sandbox identity. Absence is a gap.
        extra += (("container", "POD"),)
        predicates = ('pod!=""', 'interface!="lo"')
    else:
        predicates = ('container!=""', 'container!="POD"', 'pod!=""')
        if request.scope.kind == "container":
            assert target is not None and target.container is not None
            extra += (("container", target.container),)
            predicates = ('pod!=""',)
    selector = _selector(request, "container", extra, predicates)
    identity = "namespace,pod,interface" if network else "namespace,pod,container"
    if metric == "container_cpu_usage_seconds_total":
        identity += ",cpu"
    if filesystem:
        identity += ",device"
    raw = metric + selector
    value = _rate(request, raw) if metric.endswith("_total") else raw
    return _unique(value, identity)


def _node_mapping(request: HistoryRequest) -> str:
    assert request.scope.target is not None
    source = "node_uname_info" + _selector(
        request, "node", (("nodename", request.scope.target.name),)
    )
    identities = f"max by(job,instance) ({source})"
    return f"({identities} and on() (count({identities}) == 1))"


def _node_source(
    request: HistoryRequest, metric: str, labels: str, predicates: tuple[str, ...] = ()
) -> str:
    source = metric + _selector(request, "node", predicates=predicates)
    value = _rate(request, source) if metric.endswith("_total") else source
    return f"({_unique(value, 'job,instance' + (',' + labels if labels else ''))} and on(job,instance) {_node_mapping(request)})"


def _rate(request: HistoryRequest, expression: str) -> str:
    function = "rate_prometheus" if request.options.provider == "victoriametrics" else "rate"
    return f"{function}({expression}[{request.options.rate_window_seconds}s])"


def _value(
    request: HistoryRequest, family: MetricFamily, direction: str = ""
) -> tuple[str, str, frozenset[str], str, str]:
    node = request.scope.kind == "node"
    if node:
        if family == "cpu":
            source = _node_source(
                request,
                "node_cpu_seconds_total",
                "cpu,mode",
                ('mode=~"user|nice|system|irq|softirq|steal"',),
            )
            return (
                source,
                "cores",
                frozenset(),
                "Host CPU used cores",
                "Host CPU excluding idle, iowait and guest modes",
            )
        if family == "memory":
            total = _node_source(request, "node_memory_MemTotal_bytes", "")
            available = _node_source(request, "node_memory_MemAvailable_bytes", "")
            return (
                f"({total} - on(job,instance) {available})",
                "bytes",
                frozenset(),
                "Host memory",
                "Host total minus available memory",
            )
        if family == "network":
            metric = (
                f"node_network_{'receive' if direction == 'receive' else 'transmit'}_bytes_total"
            )
            return (
                _node_source(request, metric, "device", ('device!="lo"',)),
                "bytes/s",
                frozenset({"device"}),
                direction.title(),
                "Host interface traffic; virtual interfaces retained",
            )
        size = _node_source(request, "node_filesystem_size_bytes", "device,mountpoint,fstype")
        free = _node_source(request, "node_filesystem_free_bytes", "device,mountpoint,fstype")
        error = _node_source(request, "node_filesystem_device_error", "device,mountpoint,fstype")
        expression = f"(({size} - on(job,instance,device,mountpoint,fstype) {free}) and on(job,instance,device,mountpoint,fstype) ({error} == 0))"
        return (
            expression,
            "bytes",
            frozenset({"device", "mountpoint", "fstype"}),
            "Host filesystem",
            "Reported size minus free bytes per device and mount",
        )
    if family == "cpu":
        return (
            _container_source(request, "container_cpu_usage_seconds_total"),
            "cores",
            frozenset(),
            "Container CPU",
            "Sum of container CPU rates",
        )
    if family == "memory":
        return (
            _container_source(request, "container_memory_working_set_bytes"),
            "bytes",
            frozenset(),
            "Container memory",
            "Sum of container working sets",
        )
    if family == "network":
        source = _container_source(
            request, f"container_network_{direction}_bytes_total", network=True
        )
        detail = request.scope.kind in {"pod", "container"}
        measurement = (
            "Shared host network"
            if request.scope.host_network
            else "Pod network shared with this container"
            if request.scope.kind == "container"
            else "Pod sandbox endpoint traffic"
        )
        return (
            source,
            "bytes/s",
            frozenset({"interface"}) if detail else frozenset(),
            direction.title(),
            measurement,
        )
    source = _container_source(request, "container_fs_usage_bytes", filesystem=True)
    labels = (
        frozenset({"namespace", "pod", "container", "device"})
        if request.scope.kind in {"pod", "container"}
        else frozenset({"device"})
    )
    return (
        source,
        "bytes",
        labels,
        "Container filesystem",
        "Reported container usage by device; not unique capacity or PVC utilization",
    )


def compile_plan(request: HistoryRequest, membership: MembershipEvidence) -> HistoryQueryPlan:
    if len(membership.members) > MAX_HISTORY_MEMBERS:
        raise AppError("History current membership exceeds its bound.")
    mask = _member_mask(request, membership)
    notices = [
        HistoryNotice(
            "evaluation-not-scrape",
            "Evaluation timestamps do not prove source scrape freshness.",
            "info",
        ),
        HistoryNotice(
            "duplicate-source-policy",
            "Ambiguous duplicate source identities are excluded; no client replica summation.",
            "info",
        ),
    ]
    if request.scope.kind != "node" and any(
        family in {"cpu", "memory", "filesystem"} for family in request.families
    ):
        notices.append(
            HistoryNotice(
                "container-coverage-unknown",
                "Pod-level source counts do not establish every container or device contributor; aggregate completeness remains unknown.",
            )
        )
    if "network" in request.families and request.scope.kind != "node":
        notices.append(
            HistoryNotice(
                "sandbox-profile",
                "Network requires the explicit POD sandbox identity; unqualified or missing sandbox sources remain gaps.",
                "info",
            )
        )
    if "filesystem" in request.families and request.scope.kind == "node":
        notices.append(
            HistoryNotice(
                "filesystem-device-errors",
                "Filesystem sources with device errors are excluded; missing mounts remain unavailable.",
            )
        )
    if request.options.endpoint.cluster_label is None:
        notices.append(
            HistoryNotice("cluster-unverified", "Backend Kubernetes cluster binding is unverified.")
        )
    if request.scope.kind != "cluster" and request.scope.created_at is None:
        notices.append(
            HistoryNotice(
                "creation-unknown",
                "The captured creation boundary is unavailable; historical name identity remains uncertain.",
            )
        )
    if request.scope.kind == "workload":
        notices.append(
            HistoryNotice(
                "membership-basis",
                "Current members projected over this interval; removed historical members are excluded."
                if request.scope.membership == "current-members"
                else "Historical owner names link sources; owner UID and contributor completeness are not established.",
            )
        )
    elif request.scope.kind in {"pod", "container", "node"}:
        notices.append(
            HistoryNotice(
                "name-linkage", "Backend source names do not establish Kubernetes UID identity."
            )
        )
    if request.options.provider == "auto":
        notices.append(
            HistoryNotice(
                "provider-unverified",
                "Portable rate uses the selected engine's semantics; provider is unverified.",
                "info",
            )
        )
    queries = []
    for family in request.families:
        for direction in ("receive", "transmit") if family == "network" else ("",):
            source, unit, labels, label, measurement = _value(request, family, direction)
            if mask is not None:
                source = f"({source} and on(namespace,pod) {mask})"
            if request.scope.created_at is not None:
                boundary = math.ceil(request.scope.created_at.timestamp())
                if family in {"cpu", "network"}:
                    boundary += request.options.rate_window_seconds
                source = f"({source} and on() (vector(time()) >= {boundary}))"
            value = source
            group = ",".join(sorted(labels))
            expression = f"sum by({group}) ({value})" if labels else f"sum({value})"
            key = family + ("." + direction if direction else "")
            queries.append(
                QuerySpec(
                    key,
                    expression,
                    cast("LiteralUnit", unit),
                    "value",
                    labels,
                    MAX_SNAPSHOT_SERIES if labels else 1,
                    label,
                    measurement,
                    family,
                    request.scope.created_at,
                    request.options.rate_window_seconds if family in {"cpu", "network"} else 0,
                )
            )
            coverage = f"count(count by({'job,instance' if request.scope.kind == 'node' else 'namespace,pod'}) ({source}))"
            queries.append(
                QuerySpec(key + ".coverage", coverage, "count", "coverage", family=family)
            )
    if request.scope.kind == "node":
        members = f"count({_node_mapping(request)})"
    elif request.scope.membership == "current-members" and request.scope.kind == "workload":
        members = f"vector({len(membership.members)})"
    elif request.scope.kind in {"pod", "container"}:
        members = _state_members(request)
    else:
        members = f"count({_state_members(request)})"
    member_labels = (
        frozenset({"namespace", "pod", "uid"})
        if request.scope.kind in {"pod", "container"}
        else frozenset()
    )
    queries.append(
        QuerySpec(
            "membership",
            members,
            "count",
            "membership",
            member_labels,
            MAX_SNAPSHOT_SERIES if member_labels else 1,
        )
    )
    parameters = (
        (("dedup", "true"), ("partial_response", "false"), ("max_source_resolution", "0s"))
        if request.options.provider == "thanos"
        else ()
    )
    return HistoryQueryPlan(request, tuple(queries), parameters, membership, tuple(notices))


type LiteralUnit = Literal["cores", "bytes", "bytes/s", "count"]


def _structure(document: object) -> int:
    """Account untrusted decoded structures before recursive JSON/Decimal work."""
    stack = [(document, 0)]
    size = nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > 8 or nodes > 100000:
            raise AppError("History response structure exceeds its bound.")
        if isinstance(value, dict):
            if len(value) > 64 or any(not isinstance(key, str) for key in value):
                raise AppError("History response mapping exceeds its bound.")
            stack.extend((item, depth + 1) for pair in value.items() for item in pair)
            size += 2 + len(value)
        elif isinstance(value, list):
            if len(value) > MAX_SNAPSHOT_POINTS:
                raise AppError("History response sequence exceeds its bound.")
            stack.extend((item, depth + 1) for item in value)
            size += 2 + len(value)
        elif isinstance(value, str):
            size += len(value.encode()) + 2
        elif value is None or type(value) in {bool, float, int}:
            if type(value) is int and value.bit_length() > 64:
                raise AppError("History response number exceeds its bound.")
            size += 32
        else:
            raise AppError("History response contains unsupported data.")
        if size > MAX_HISTORY_BODY_BYTES:
            raise AppError("History response exceeds its retained body bound.")
    return size


def _accounted(series: tuple[HistorySeries, ...], notices: tuple[HistoryNotice, ...]) -> int:
    """Charge the normalized retained payload, including every materialized gap."""
    payload = {
        "series": [
            {
                "key": item.key,
                "label": item.label,
                "unit": item.unit,
                "labels": item.labels,
                "measurement": item.measurement,
                "points": [
                    [
                        point.timestamp.isoformat(),
                        str(point.value) if point.value is not None else None,
                        quality.value,
                    ]
                    for point, quality in zip(item.points, item.quality, strict=True)
                ],
            }
            for item in series
        ],
        "notices": [[notice.code, notice.message, notice.severity] for notice in notices],
    }
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def parse_matrix(
    document: object,
    query: QuerySpec,
    start: datetime,
    end: datetime,
    step_seconds: int,
    *,
    remaining_series: int,
    remaining_points: int,
) -> ParsedHistory:
    _structure(document)
    if (
        type(remaining_series) is not int
        or not 0 <= remaining_series <= MAX_SNAPSHOT_SERIES
        or (type(remaining_points) is not int or not 0 <= remaining_points <= MAX_SNAPSHOT_POINTS)
    ):
        raise AppError("History remaining snapshot budget is invalid.")
    if not isinstance(document, dict) or document.get("status") != "success":
        raise AppError("History backend did not return a successful query.")
    data = document.get("data")
    results = data.get("result") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("resultType") != "matrix"
        or not isinstance(results, list)
    ):
        raise AppError("History requires a bounded float matrix response.")
    grid, _ = parse_history_range(
        {"status": "success", "data": {"resultType": "matrix", "result": []}},
        start,
        end,
        step_seconds,
    )
    count = len(grid)
    if (
        count > MAX_SERIES_POINTS
        or len(results) > min(query.maximum_series, remaining_series)
        or (len(results) * count > remaining_points)
    ):
        raise AppError("History matrix exceeds its series or point budget.")
    notices = []
    for field in ("warnings", "infos"):
        items = document.get(field, [])
        if (
            not isinstance(items, list)
            or len(items) > MAX_HISTORY_NOTICES
            or any(not isinstance(item, str) or len(item) > 512 for item in items)
        ):
            raise AppError("History response notices exceed their bound.")
        if items:
            notices.append(
                HistoryNotice(
                    "backend-" + field,
                    "Backend reported query " + field + "; source completeness is uncertain.",
                )
            )
    series = []
    identities = set()
    partial = bool(notices)
    for result in results:
        if not isinstance(result, dict) or set(result) - {"metric", "values"}:
            raise AppError("History requires float samples; histogram results are unsupported.")
        labels = result.get("metric", {})
        if not isinstance(labels, dict) or len(labels) > MAX_HISTORY_LABELS:
            raise AppError("History series labels exceed their bound.")
        identity = tuple(sorted(_matcher(name, value) for name, value in labels.items()))
        if set(labels) != query.allowed_labels or identity in identities:
            raise AppError("History series has unexpected or duplicate source identity.")
        identities.add(identity)
        points, missing = parse_history_range(
            {
                "status": "success",
                "data": {"resultType": "matrix", "result": [{"values": result.get("values")}]},
            },
            start,
            end,
            step_seconds,
        )
        partial |= missing
        qualities = [
            PointQuality.OBSERVED if point.value is not None else PointQuality.MISSING
            for point in points
        ]
        values = cast(list[list[object]], result["values"])
        for timestamp, raw in values:
            numeric = Decimal(cast(str, raw))
            index = round((cast(float, timestamp) - start.timestamp()) / step_seconds)
            if not numeric.is_finite():
                qualities[index] = PointQuality.NONFINITE
        boundary = query.created_after
        if boundary is not None:
            if boundary.tzinfo is None:
                raise AppError("History creation boundary requires a timezone.")
            earliest = boundary + timedelta(seconds=query.rate_window_seconds)
            for index, point in enumerate(points):
                if point.timestamp < earliest:
                    points = (*points[:index], replace(point, value=None), *points[index + 1 :])
                    qualities[index] = PointQuality.IDENTITY_UNCERTAIN
                    partial = True
        series.append(
            HistorySeries(
                query.key,
                query.label or query.key,
                query.unit,
                points,
                identity,
                tuple(qualities),
                query.measurement,
            )
        )
    status: SourceStatus = "partial" if partial else "available" if series else "no-data"
    return ParsedHistory(
        tuple(series), tuple(notices), status, _accounted(tuple(series), tuple(notices))
    )


def finalize_results(
    plan: HistoryQueryPlan, results: tuple[tuple[QuerySpec, ParsedHistory], ...]
) -> ParsedHistory:
    """Apply independent membership/coverage evidence without making gaps into zero."""
    if tuple(query for query, _ in results) != plan.queries:
        raise AppError("History finalization requires every planned query in order.")
    by_key = {query.key: parsed for query, parsed in results}
    membership = by_key["membership"]
    expected = membership.series[0].points if membership.series else ()
    uid_probe = plan.request.scope.kind in {"pod", "container"}
    target = plan.request.scope.target
    selected_uid = target.uid if target is not None else None
    output = []
    notices = list(plan.notices)
    incomplete = (
        plan.membership_evidence.status in {"partial", "unavailable"}
        or plan.request.scope.membership == "current-members"
    )
    for query, parsed in results:
        notices.extend(parsed.notices)
        if query.role != "value":
            continue
        coverage = by_key[query.key + ".coverage"]
        observed = coverage.series[0].points if coverage.series else ()
        incomplete |= (
            membership.source_status != "available"
            or coverage.source_status != "available"
            or parsed.source_status != "available"
        )
        for series in parsed.series:
            points, quality = list(series.points), list(series.quality)
            for index, point in enumerate(points):
                want = expected[index].value if index < len(expected) else None
                have = observed[index].value if index < len(observed) else None
                uncertain = False
                if uid_probe:
                    active = [
                        dict(member.labels).get("uid")
                        for member in membership.series
                        if index < len(member.points)
                        and member.points[index].value is not None
                        and cast(Decimal, member.points[index].value) > 0
                    ]
                    uncertain = bool(active) and (len(active) != 1 or active[0] != selected_uid)
                    want = Decimal(1) if active else None
                known = want is not None and have is not None
                if not known:
                    incomplete = True
                elif want == have and cast(Decimal, want) > 0 and not uncertain:
                    continue
                if uncertain or known:
                    if point.value is not None:
                        points[index] = replace(point, value=None)
                        quality[index] = (
                            PointQuality.IDENTITY_UNCERTAIN
                            if uncertain
                            else PointQuality.MEMBERSHIP_PARTIAL
                        )
                    incomplete = True
            output.append(replace(series, points=tuple(points), quality=tuple(quality)))
    if incomplete:
        notices.append(
            HistoryNotice(
                "coverage-incomplete",
                "Contributor completeness is unavailable or partial; no healthy completeness claim is made.",
            )
        )
    unique = tuple(dict.fromkeys(notices))
    if len(unique) > MAX_HISTORY_NOTICES:
        raise AppError("History combined notices exceed their bound.")
    point_count = sum(len(series.points) for series in output)
    if len(output) > MAX_SNAPSHOT_SERIES or point_count > MAX_SNAPSHOT_POINTS:
        raise AppError("History finalized snapshot exceeds its bound.")
    status: SourceStatus = "partial" if incomplete else "available" if output else "no-data"
    return ParsedHistory(tuple(output), unique, status, _accounted(tuple(output), unique))
