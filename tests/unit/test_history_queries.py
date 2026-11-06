"""Fixed query semantics and bounded history parsing never turn absence into zero."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from kuberich.domain.history import (
    BackendCandidate,
    BackendCandidates,
    EndpointIdentity,
    ExternalHistoryBackend,
    HistoryBackend,
    HistoryNotice,
    HistoryOptions,
    HistoryPoint,
    HistoryRequest,
    HistoryScope,
    MemberIdentity,
    MembershipEvidence,
    ParsedHistory,
    PointQuality,
    QuerySpec,
    build_history_plan,
    finalize_history_results,
    history_prefix,
    history_window,
    parse_history_matrix,
    parse_history_range,
)
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

NOW = datetime(2026, 1, 1, tzinfo=UTC)
START, END, STEP = history_window(NOW, 900)
SESSION = SessionIdentity("synthetic", 1)
BACKEND = HistoryBackend(
    "observability", "prometheus", cluster_label="cluster", cluster_value="owned"
)
PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list", "watch"}))
NODES = ApiResource("", "v1", "nodes", "Node", False, PODS.verbs)
DEPLOYMENTS = ApiResource("apps", "v1", "deployments", "Deployment", True, PODS.verbs)


def scope(kind="cluster", *, resource=None, **changes):
    if kind == "cluster":
        return HistoryScope(SESSION, kind, **changes)
    resource = resource or (
        NODES if kind == "node" else DEPLOYMENTS if kind == "workload" else PODS
    )
    namespace = None if kind == "node" else "team"
    target = ResourceTarget(
        SESSION,
        resource.group,
        resource.name,
        namespace,
        "example",
        "uid-1",
        "application" if kind == "container" else None,
    )
    return HistoryScope(
        SESSION,
        kind,
        namespace,
        target,
        resource,
        container_field="containers" if kind == "container" else None,
        **changes,
    )


def request(
    selected=None, *, options=None, families=("cpu", "memory", "network", "filesystem"), **changes
):
    return HistoryRequest(
        **{
            "id": uuid4(),
            "scope": selected or scope(),
            "options": options or HistoryOptions(BACKEND),
            "start": START,
            "end": END,
            "step_seconds": STEP,
            "families": families,
            "config_revision": 0,
            **changes,
        }
    )


def document(values=None, *, labels=None, results=None, **extra):
    if results is None:
        results = [
            {
                "metric": labels or {},
                "values": values
                if values is not None
                else [[START.timestamp() + index * STEP, "0"] for index in range(61)],
            }
        ]
    return {"status": "success", "data": {"resultType": "matrix", "result": results}, **extra}


def parse(doc, query=None, **kwargs):
    return parse_history_matrix(
        doc, query or QuerySpec("cpu", "synthetic", "cores"), START, END, STEP, **kwargs
    )


@pytest.mark.parametrize(
    "seconds,step,count",
    [
        (900, 15, 61),
        (1800, 15, 121),
        (3600, 15, 241),
        (10800, 30, 361),
        (21600, 60, 361),
        (43200, 60, 721),
        (86400, 120, 721),
    ],
)
def test_windows_align_utc_and_bound_every_range(seconds, step, count):
    start, end, actual = history_window(NOW + timedelta(seconds=13.75), seconds)
    assert actual == step and (end - start).total_seconds() == seconds
    assert end.timestamp() % step == 0 and end.tzinfo is UTC
    assert (end - start).total_seconds() // step + 1 == count
    assert replace(request(), start=start, end=end, step_seconds=step).end == end


@pytest.mark.parametrize(
    "now,seconds", [(NOW.replace(tzinfo=None), 900), (NOW, False), (NOW, 901), (NOW, 0)]
)
def test_window_rejects_unsupported_or_naive(now, seconds):
    with pytest.raises(AppError):
        history_window(now, seconds)


@pytest.mark.parametrize(
    "value,expected", [("", ""), ("/", ""), ("/select/0/prometheus/", "/select/0/prometheus")]
)
def test_prefix_is_a_literal_normalized_path(value, expected):
    assert history_prefix(value) == expected


@pytest.mark.parametrize(
    "value", [None, "x", "x" * 513, "/a/../b", "/./a", "/a//b", "/a%2fb", "/a?x", "/[x]"]
)
def test_prefix_refuses_escapes_and_normalization(value):
    with pytest.raises(AppError):
        history_prefix(value)


def test_external_options_are_offline_and_metadata_has_no_credential_paths(tmp_path):
    private = tmp_path / "does-not-exist"
    endpoint = ExternalHistoryBackend(
        "https://metrics.example:9443/select/0/prometheus/",
        (("job", "cadvisor"),),
        "cluster",
        "owned",
        private,
        private,
    )
    assert (
        endpoint.url.endswith("/select/0/prometheus") and endpoint.prefix == "/select/0/prometheus"
    )
    assert endpoint.origin == "https://metrics.example:9443"
    assert endpoint.labels("team") == (
        ("cluster", "owned"),
        ("job", "cadvisor"),
        ("namespace", "team"),
    )
    assert "Configured cluster" in endpoint.scope_label(None)
    assert str(private) not in repr(endpoint) and str(private) not in repr(HistoryOptions(endpoint))
    assert not private.exists()
    assert (
        HistoryOptions(HistoryBackend("observe", "history"), api_prefix="/prometheus/").api_prefix
        == "/prometheus"
    )
    assert BackendCandidates((BackendCandidate("observe", "history", "uid", 9090),)).complete
    assert "uid" in repr(EndpointIdentity("service", service_uid="uid"))


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://",
        "file:///x",
        "https://user:secret@metrics.example",
        "http://x?",
        "http://x#",
        "http://x?q=v",
        "http://x/#f",
        "http://x/a%2fb",
        "http://x/a/../b",
        "http://x:0",
        "http://x:65536",
        "http://[broken",
        "http://x:bad",
        "http://x/\\bad",
        "http://x/\n",
        "http://x/🚀",
        "http://x/" + "a" * 2048,
    ],
)
def test_external_refuses_untrusted_origins_and_paths(url):
    with pytest.raises(AppError):
        ExternalHistoryBackend(url)


@pytest.mark.parametrize(
    "changes",
    [
        {"ca_file": "private"},
        {"bearer_token_file": "private"},
        {"bearer_token_file": Path("private")},
        {"cluster_label": "cluster"},
        {"matchers": (("job", "a"), ("job", "b"))},
    ],
)
def test_external_reuses_matchers_and_requires_tls_for_tokens(changes):
    with pytest.raises(AppError):
        ExternalHistoryBackend("http://metrics.example", **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"endpoint": None},
        {"provider": "other"},
        {"profile": "raw"},
        {"node_matchers": []},
        {"state_matchers": (("bad label", "x"),)},
        {"rate_window_seconds": True},
        {"rate_window_seconds": 59},
        {"rate_window_seconds": 3601},
        {"endpoint": ExternalHistoryBackend("https://metrics.example"), "api_prefix": "/prom"},
    ],
)
def test_options_validate_fixed_profile_and_family_selectors(changes):
    with pytest.raises(AppError):
        HistoryOptions(**{"endpoint": BACKEND, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"session": None},
        {"kind": "other"},
        {"membership": "other"},
        {"namespace": "../other"},
        {"created_at": NOW.replace(tzinfo=None)},
        {"host_network": 1},
        {"target": ResourceTarget(SESSION, "", "pods", "team", "x", "u")},
        {"resource": PODS},
        {"container_field": "containers"},
    ],
)
def test_cluster_scope_rejects_mismatched_capture(changes):
    with pytest.raises(AppError):
        HistoryScope(**{"session": SESSION, "kind": "cluster", **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"target": None},
        {"resource": None},
        {"session": SessionIdentity("synthetic", 2)},
        {"namespace": "different"},
        {"resource": NODES},
        {"resource": replace(PODS, namespaced=False)},
        {"kind": "node"},
        {"container_field": "containers"},
        {"target": ResourceTarget(SESSION, "", "pods", "team", "example", "uid-1", "app")},
    ],
)
def test_resource_scope_requires_exact_session_resource_namespace_and_container(changes):
    with pytest.raises(AppError):
        replace(scope("pod"), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"target": ResourceTarget(SESSION, "", "pods", "team", "example", "uid")},
        {"container_field": None},
        {"container_field": "other"},
    ],
)
def test_container_requires_name_and_declaration_family(changes):
    with pytest.raises(AppError):
        replace(scope("container"), **changes)


@pytest.mark.parametrize("family", ["containers", "initContainers", "ephemeralContainers"])
def test_container_declaration_families_keep_source_availability_explicit(family):
    assert replace(scope("container"), container_field=family).container_field == family


@pytest.mark.parametrize(
    "changes",
    [
        {"namespace": "../bad"},
        {"pod": "../bad"},
        {"uid": 1},
        {"owner_uid": "bad\n"},
        {"created_at": NOW.replace(tzinfo=None)},
    ],
)
def test_member_identity_is_bounded_literal_api_evidence(changes):
    with pytest.raises(AppError):
        MemberIdentity(**{"namespace": "team", "pod": "example", **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "x"},
        {"start": START.replace(tzinfo=None)},
        {"end": END.replace(tzinfo=None)},
        {"end": END + timedelta(seconds=1)},
        {"start": START + timedelta(seconds=1), "end": END + timedelta(seconds=1)},
        {"step_seconds": True},
        {"step_seconds": 30},
        {"config_revision": True},
        {"config_revision": -1},
        {"families": []},
        {"families": ()},
        {"families": ("cpu", "cpu")},
        {"families": ("raw",)},
    ],
)
def test_request_rejects_unbounded_or_unaligned_work(changes):
    with pytest.raises(AppError):
        request(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"key": ""},
        {"key": "x" * 65},
        {"expression": "x" * 8193},
        {"maximum_series": 0},
        {"maximum_series": 33},
        {"allowed_labels": frozenset(f"x{i}" for i in range(33))},
        {"allowed_labels": frozenset({"bad label"})},
    ],
)
def test_query_specs_bound_expression_series_and_labels(changes):
    with pytest.raises(AppError):
        QuerySpec(**{"key": "cpu", "expression": "synthetic", **changes})


@pytest.mark.parametrize("kind", ["cluster", "node", "workload", "pod", "container"])
@pytest.mark.parametrize("provider", ["auto", "prometheus", "victoriametrics", "thanos"])
def test_every_entity_family_provider_has_fixed_source_semantics(kind, provider):
    selected = scope(kind)
    options = HistoryOptions(
        BACKEND, provider, node_matchers=(("job", "nodes"),), state_matchers=(("job", "state"),)
    )
    plan = build_history_plan(request(selected, options=options), MembershipEvidence())
    assert len(plan.queries) == 11 and all(
        len(query.expression.encode()) <= 8192 for query in plan.queries
    )
    values = {query.key: query for query in plan.queries if query.role == "value"}
    assert set(values) == {"cpu", "memory", "network.receive", "network.transmit", "filesystem"}
    assert all('cluster="owned"' in query.expression for query in plan.queries)
    assert (
        all('namespace="team"' in query.expression for query in plan.queries)
        if kind in {"workload", "pod", "container"}
        else True
    )
    assert (
        "rate_prometheus(" in values["cpu"].expression
        if provider == "victoriametrics"
        else "rate(" in values["cpu"].expression
    )
    assert "[300s]" in values["cpu"].expression and "rate(sum" not in values["cpu"].expression
    assert "count by(" in values["cpu"].expression and "== 1" in values["cpu"].expression
    assert bool(plan.provider_parameters) == (provider == "thanos")
    assert all(query.expression not in repr(query) for query in plan.queries)
    if kind == "node":
        assert 'mode=~"user|nice|system|irq|softirq|steal"' in values["cpu"].expression
        assert (
            "guest" not in values["cpu"].expression
            and 'nodename="example"' in values["memory"].expression
        )
        assert (
            "MemTotal" in values["memory"].expression
            and "MemAvailable" in values["memory"].expression
        )
        assert (
            "instance" in values["cpu"].expression and "node_uname_info" in values["cpu"].expression
        )
        assert values["filesystem"].allowed_labels == frozenset({"device", "mountpoint", "fstype"})
        assert (
            "device_error" in values["filesystem"].expression
            and "free_bytes" in values["filesystem"].expression
        )
        assert "namespace=" not in values["cpu"].expression
    else:
        assert (
            'container!="POD"' in values["cpu"].expression
            if kind != "container"
            else 'container="application"' in values["cpu"].expression
        )
        assert 'container="POD"' in values["network.receive"].expression
        assert 'container!="POD"' not in values["network.receive"].expression
        assert 'container="application"' not in values["network.receive"].expression
        assert "device" in values["filesystem"].allowed_labels
        if kind in {"pod", "container"}:
            assert values["network.receive"].allowed_labels == frozenset({"interface"})
    assert "[300s:]" not in values["cpu"].expression


@pytest.mark.parametrize(
    "resource",
    [
        DEPLOYMENTS,
        ApiResource("batch", "v1", "cronjobs", "CronJob", True, PODS.verbs),
        ApiResource("apps", "v1", "replicasets", "ReplicaSet", True, PODS.verbs),
        ApiResource("apps", "v1", "statefulsets", "StatefulSet", True, PODS.verbs),
        ApiResource("apps", "v1", "daemonsets", "DaemonSet", True, PODS.verbs),
        ApiResource("batch", "v1", "jobs", "Job", True, PODS.verbs),
        ApiResource("", "v1", "replicationcontrollers", "ReplicationController", True, PODS.verbs),
    ],
)
def test_historical_owner_chains_use_ksm_relations_without_name_patterns(resource):
    plan = build_history_plan(request(scope("workload", resource=resource)), MembershipEvidence())
    cpu = plan.queries[0].expression
    assert 'owner_is_controller="true"' in cpu and 'owner_name="example"' in cpu
    assert "max by(namespace,pod,uid)" in cpu and "count by(namespace,pod)" in cpu
    assert "=~" not in cpu and 'job="' not in cpu
    assert ("label_replace(" in cpu) == (resource.kind in {"Deployment", "CronJob"})
    assert "owner UID" in next(
        notice.message for notice in plan.notices if notice.code == "membership-basis"
    )


def test_current_projection_is_explicit_bounded_and_does_not_need_ksm():
    selected = scope("workload", membership="current-members")
    member = MemberIdentity("team", "current-pod", "uid", START, "owner")
    evidence = MembershipEvidence("current-members", "current-only", NOW, (member,), "fingerprint")
    plan = build_history_plan(request(selected), evidence)
    assert (
        '"current-pod"' in plan.queries[0].expression
        and "kube_pod_info" not in plan.queries[0].expression
    )
    assert "vector(time()) >=" in plan.queries[0].expression
    assert plan.queries[-1].expression == "vector(1)"
    assert "removed historical" in next(
        n.message for n in plan.notices if n.code == "membership-basis"
    )
    assert (
        "vector(0) < 0"
        in build_history_plan(request(selected), replace(evidence, members=()))
        .queries[0]
        .expression
    )
    assert (
        "vector(0) < 0"
        in build_history_plan(request(selected), MembershipEvidence()).queries[0].expression
    )
    assert (
        "vector(time())"
        not in build_history_plan(
            request(selected), replace(evidence, members=(replace(member, created_at=None),))
        )
        .queries[0]
        .expression
    )
    with pytest.raises(AppError, match="namespace"):
        build_history_plan(
            request(selected), replace(evidence, members=(replace(member, namespace="other"),))
        )
    with pytest.raises(AppError, match="bound"):
        build_history_plan(request(selected), replace(evidence, members=(member,) * 257))
    with pytest.raises(AppError, match="expression"):
        build_history_plan(
            request(selected),
            replace(
                evidence, members=tuple(MemberIdentity("team", f"pod-{n}", "u") for n in range(256))
            ),
        )


def test_literal_injection_cluster_namespace_conflicts_and_host_network_labels():
    unsafe = 'one"} or vector(0) #\\tail'
    options = HistoryOptions(replace(BACKEND, matchers=(("job", unsafe),)))
    plan = build_history_plan(request(scope("pod"), options=options), MembershipEvidence())
    assert 'job="one\\"} or vector(0) #\\\\tail"' in plan.queries[0].expression
    for option, selected in [
        (HistoryOptions(replace(BACKEND, matchers=(("namespace", "other"),))), scope("pod")),
        (HistoryOptions(replace(BACKEND, matchers=(("pod", "other"),))), scope("pod")),
        (HistoryOptions(replace(BACKEND, matchers=(("container", "POD"),))), scope()),
    ]:
        with pytest.raises(AppError, match="conflict"):
            build_history_plan(request(selected, options=option), MembershipEvidence())
    unbound = build_history_plan(
        request(options=HistoryOptions(HistoryBackend("observe", "prom"))), MembershipEvidence()
    )
    assert any(notice.code == "cluster-unverified" for notice in unbound.notices)
    shared = build_history_plan(
        request(scope("container", host_network=True)), MembershipEvidence()
    )
    assert (
        next(query for query in shared.queries if query.key == "network.receive").measurement
        == "Shared host network"
    )


def test_matrix_retains_zero_quality_device_identity_and_sanitized_notices():
    query = QuerySpec(
        "filesystem", "synthetic", "bytes", allowed_labels=frozenset({"device"}), maximum_series=2
    )
    parsed = parse(document(labels={"device": "/dev/synthetic"}), query)
    assert parsed.source_status == "available" and parsed.accounted_bytes > 0
    assert parsed.series[0].points[-1].value == 0 and set(parsed.series[0].quality) == {
        PointQuality.OBSERVED
    }
    assert parsed.series[0].labels == (("device", "/dev/synthetic"),)
    partial = parse(
        document(
            [[START.timestamp(), "NaN"], [END.timestamp(), "0"]],
            warnings=["private"],
            infos=["private"],
        )
    )
    assert partial.source_status == "partial" and partial.series[0].quality[:2] == (
        PointQuality.NONFINITE,
        PointQuality.MISSING,
    )
    assert "private" not in repr(partial) and len(partial.notices) == 2
    assert parse(document(results=[])).source_status == "no-data"
    assert parse(document(results=[], warnings=["private"])).source_status == "partial"


@pytest.mark.parametrize(
    "raw", ["1e-999999999", "0e-999999999", "1e999999999", "-1", "1e31", "bad", "1" * 65]
)
def test_numeric_values_have_finite_bounded_formatter_work(raw):
    with pytest.raises(AppError):
        parse(document([[START.timestamp(), raw]]))
    with pytest.raises(AppError):
        parse_history_range(document([[START.timestamp(), raw]]), START, END, STEP)


def test_creation_and_rate_overlap_are_identity_gaps_not_predecessor_values():
    query = QuerySpec("cpu", "synthetic", "cores", created_after=START, rate_window_seconds=300)
    parsed = parse(document(), query)
    assert all(point.value is None for point in parsed.series[0].points[:20])
    assert set(parsed.series[0].quality[:20]) == {PointQuality.IDENTITY_UNCERTAIN}
    assert parsed.series[0].points[20].value == 0 and parsed.source_status == "partial"
    with pytest.raises(AppError, match="timezone"):
        parse(document(), replace(query, created_after=START.replace(tzinfo=None)))


@pytest.mark.parametrize(
    "doc",
    [
        None,
        [],
        {"status": "error"},
        {"status": "success"},
        {"status": "success", "data": []},
        {"status": "success", "data": {"resultType": "vector", "result": []}},
        {"status": "success", "data": {"resultType": "matrix", "result": {}}},
        document(results=[None]),
        document(results=[{"histograms": []}]),
        document(results=[{"metric": []}]),
        document(labels={f"x{i}": "v" for i in range(33)}),
        document(labels={"unexpected": "value"}),
        document(labels={"bad label": "v"}),
        document(labels={"job": "x" * 257}),
        document(labels={"job": "x\n"}),
        document(results=[{"values": []}] * 2),
        document(warnings="wrong"),
        document(warnings=["x"] * 17),
        document(infos=[None]),
        document(infos=["x" * 513]),
        {"nested": [[[[[[[[[[]]]]]]]]]]},
        {str(n): n for n in range(65)},
        {1: "value"},
        [0] * 16385,
        {"padding": "x" * 1048577},
        {"number": 10**1000},
        {"unsupported": object()},
    ],
)
def test_matrix_refuses_malformed_oversized_or_ambiguous_response(doc):
    with pytest.raises(AppError):
        parse(doc)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"remaining_series": True},
        {"remaining_series": -1},
        {"remaining_series": 33},
        {"remaining_points": True},
        {"remaining_points": -1},
        {"remaining_points": 16385},
        {"remaining_series": 0},
        {"remaining_points": 60},
    ],
)
def test_matrix_charges_remaining_global_series_and_grid_samples(kwargs):
    with pytest.raises(AppError):
        parse(document(), **kwargs)


def test_matrix_rejects_duplicate_device_identity_and_overlong_grid():
    query = QuerySpec(
        "filesystem", "synthetic", allowed_labels=frozenset({"device"}), maximum_series=2
    )
    with pytest.raises(AppError, match="duplicate"):
        parse(document(results=[{"metric": {"device": "same"}, "values": []}] * 2), query)
    with pytest.raises(AppError, match="budget"):
        parse_history_matrix(document(), query, START, END, 1)
    with pytest.raises(AppError):
        parse_history_matrix(document(), query, START.replace(tzinfo=None), END, STEP)


def collected_plan(*, values="2", coverage="1", members="1", missing=None):
    plan = build_history_plan(request(families=("cpu",)), MembershipEvidence())
    results = []
    for query in plan.queries:
        raw = values if query.role == "value" else coverage if query.role == "coverage" else members
        parsed = (
            ParsedHistory((), (), "unavailable", 0)
            if query.key == missing
            else parse(
                document([[START.timestamp() + index * STEP, raw] for index in range(61)]), query
            )
        )
        results.append((query, parsed))
    return plan, tuple(results)


def test_finalization_excludes_probe_series_preserves_zero_and_checks_known_coverage():
    plan, results = collected_plan(values="0")
    final = finalize_history_results(plan, results)
    assert (
        final.source_status == "available"
        and len(final.series) == 1
        and final.series[0].points[-1].value == 0
    )
    for changes in ({"coverage": "0"}, {"members": "0"}, {"members": "NaN"}, {"coverage": "2"}):
        plan, results = collected_plan(**changes)
        final = finalize_history_results(plan, results)
        assert final.source_status == "partial"
        if changes.get("members") != "NaN":
            assert all(point.value is None for point in final.series[0].points)
            assert set(final.series[0].quality) == {PointQuality.MEMBERSHIP_PARTIAL}
    for missing in ("membership", "cpu.coverage", "cpu"):
        plan, results = collected_plan(missing=missing)
        final = finalize_history_results(plan, results)
        assert final.source_status == "partial"
        if missing != "cpu":
            assert final.series[0].points[-1].value == 2
    with pytest.raises(AppError, match="every planned"):
        finalize_history_results(plan, results[:-1])


def test_finalization_bounds_normalized_notices_series_and_samples():
    plan, results = collected_plan()
    noisy = replace(
        results[0][1], notices=tuple(HistoryNotice(str(n), "Authored") for n in range(17))
    )
    with pytest.raises(AppError, match="notices"):
        finalize_history_results(plan, ((results[0][0], noisy), *results[1:]))
    for series in (
        (results[0][1].series[0],) * 33,
        (
            replace(
                results[0][1].series[0],
                points=(HistoryPoint(START, Decimal(1)),) * 16385,
                quality=(PointQuality.OBSERVED,) * 16385,
            ),
        ),
    ):
        # Unknown coverage retains useful values, but cannot bypass final output bounds.
        altered = replace(results[0][1], series=series)
        empty = ParsedHistory((), (), "unavailable", 0)
        with pytest.raises(AppError, match="snapshot"):
            finalize_history_results(
                plan, ((results[0][0], altered), (results[1][0], empty), (results[2][0], empty))
            )


def test_selected_pod_uid_evidence_rejects_predecessor_and_overlapping_uids():
    plan = build_history_plan(request(scope("pod"), families=("cpu",)), MembershipEvidence())
    probe = plan.queries[-1]
    assert probe.allowed_labels == frozenset({"namespace", "pod", "uid"})

    def collected(uids):
        results = []
        for query in plan.queries:
            if query.role == "membership":
                doc = document(
                    results=[
                        {
                            "metric": {"namespace": "team", "pod": "example", "uid": uid},
                            "values": [[START.timestamp() + i * STEP, "1"] for i in range(61)],
                        }
                        for uid in uids
                    ]
                )
            else:
                doc = document(
                    [
                        [START.timestamp() + i * STEP, "2" if query.role == "value" else "1"]
                        for i in range(61)
                    ]
                )
            results.append((query, parse(doc, query)))
        return finalize_history_results(plan, tuple(results))

    assert collected(("uid-1",)).series[0].points[-1].value == 2
    for uids in (("predecessor",), ("uid-1", "predecessor")):
        final = collected(uids)
        assert final.source_status == "partial" and all(
            point.value is None for point in final.series[0].points
        )
        assert set(final.series[0].quality) == {PointQuality.IDENTITY_UNCERTAIN}
    absent = collected(())
    assert absent.source_status == "partial" and absent.series[0].points[-1].value == 2


def test_known_coverage_mismatch_preserves_an_existing_nonfinite_gap():
    plan, results = collected_plan(values="NaN", members="2")
    final = finalize_history_results(plan, results)
    assert final.source_status == "partial"
    assert all(point.value is None for point in final.series[0].points)
    assert set(final.series[0].quality) == {PointQuality.NONFINITE}


def test_history_owner_creation_mask_precedes_aggregation():
    plan = build_history_plan(request(scope("workload")), MembershipEvidence())
    value = plan.queries[0].expression
    assert "kube_pod_created" in value and "<= time() - 300" in value
    assert "on(namespace,pod,uid)" in value
    assert 'cluster="owned"' in value.split("kube_pod_created", 1)[1]


def test_matrix_validates_empty_windows_and_structural_node_work():
    for start, end, step in (
        (END, START, 15),
        (START, END, 0),
        (START, END, True),
        (START, END, 3601),
    ):
        with pytest.raises(AppError):
            parse_history_matrix(
                document(results=[]), QuerySpec("cpu", "synthetic"), start, end, step
            )
    with pytest.raises(AppError, match="structure"):
        parse({"nodes": [[""] * 16000 for _ in range(7)]})


def test_family_selectors_cannot_contradict_the_configured_cluster_binding():
    for field in ("node_matchers", "state_matchers"):
        with pytest.raises(AppError, match="cluster binding"):
            HistoryOptions(BACKEND, **{field: (("cluster", "other"),)})
        assert HistoryOptions(BACKEND, **{field: (("cluster", "owned"),)}).endpoint is BACKEND


def test_retained_accounting_charges_all_materialized_missing_grid_points():
    parsed = parse(document(values=[]))
    assert len(parsed.series[0].points) == 61
    assert parsed.accounted_bytes > 61 * 30
    empty = parse(document(results=[]))
    assert parsed.accounted_bytes > empty.accounted_bytes
    for window in (60, 3600):
        plan = build_history_plan(
            request(options=HistoryOptions(BACKEND, rate_window_seconds=window)),
            MembershipEvidence(),
        )
        assert f"[{window}s]" in plan.queries[0].expression
    pod = build_history_plan(request(scope("pod", created_at=START)), MembershipEvidence())
    assert not any(notice.code == "creation-unknown" for notice in pod.notices)
    uncreated = build_history_plan(request(scope("pod")), MembershipEvidence())
    assert any(notice.code == "creation-unknown" for notice in uncreated.notices)


def test_stale_values_drop_observed_quality_but_preserve_original_gap_reasons():
    from kuberich.domain.history import HistorySnapshot, HistoryStatus

    series = parse(document([[START.timestamp(), "0"], [END.timestamp(), "NaN"]])).series[0]
    snapshot = HistorySnapshot(HistoryStatus.PARTIAL, NOW, series=(series,))
    stale = snapshot.fresh(NOW + timedelta(seconds=60))
    assert all(point.value is None for point in stale.series[0].points)
    assert stale.series[0].quality[0] is PointQuality.MISSING
    assert stale.series[0].quality[-1] is PointQuality.NONFINITE


def test_server_expression_also_excludes_selected_predecessor_and_rate_overlap():
    selected = scope("pod", created_at=START + timedelta(microseconds=500000))
    plan = build_history_plan(request(selected), MembershipEvidence())
    for query in plan.queries:
        if query.role == "value":
            boundary = (
                int(START.timestamp()) + 1 + (300 if query.family in {"cpu", "network"} else 0)
            )
            assert f"vector(time()) >= {boundary}" in query.expression
