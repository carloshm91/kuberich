"""History preserves measurement gaps, query scope and declared numeric units."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kuberich.domain.history import (
    HistoryBackend,
    HistoryPoint,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    history_queries,
    parse_history_range,
)
from kuberich.errors import AppError

NOW = datetime(2026, 1, 1, tzinfo=UTC)
START = NOW - timedelta(seconds=30)


def matrix(values=None, **extra):
    values = (
        [
            [START.timestamp(), "0"],
            [(START + timedelta(seconds=15)).timestamp(), "1.5"],
            [NOW.timestamp(), "2"],
        ]
        if values is None
        else values
    )
    return {
        "status": "success",
        "data": {"resultType": "matrix", "result": [{"values": values}]},
        **extra,
    }


def test_backend_uses_only_a_validated_relative_service_proxy():
    backend = HistoryBackend("observability", "prometheus", 9443, "https")
    assert (
        backend.path
        == "/api/v1/namespaces/observability/services/https:prometheus:9443/proxy/api/v1/query_range"
    )
    assert "unverified" in backend.scope_label(None)
    assert "selectors: none" in backend.scope_label(None)
    assert backend.labels("team") == (("namespace", "team"),)


@pytest.mark.parametrize(
    "changes",
    [
        {"namespace": "../other"},
        {"service": "prometheus/proxy"},
        {"port": 0},
        {"port": 65536},
        {"port": True},
        {"scheme": "file"},
        {"matchers": []},
        {"matchers": tuple((f"label{i}", "x") for i in range(9))},
        {"matchers": (("job", "one"), ("job", "two"))},
        {"matchers": (("job",),)},
        {"matchers": (("bad label", "x"),)},
        {"matchers": ((3, "x"),)},
        {"matchers": (("job", 3),)},
        {"matchers": (("job", "x" * 257),)},
        {"matchers": (("job", "x\n"),)},
        {"cluster_label": "cluster"},
        {"cluster_value": "one"},
        {"cluster_label": "bad label", "cluster_value": "one"},
        {"cluster_label": "cluster", "cluster_value": ""},
        {"cluster_label": "cluster", "cluster_value": "one", "matchers": (("cluster", "other"),)},
    ],
)
def test_backend_rejects_untrusted_path_and_selector_inputs(changes):
    with pytest.raises(AppError):
        HistoryBackend(**{"namespace": "observability", "service": "prometheus", **changes})


def test_query_matchers_are_literal_and_do_not_invent_context_cluster_labels():
    unsafe = 'one"} or vector(0) #\\tail'
    backend = HistoryBackend("observability", "prometheus", matchers=(("job", unsafe),))
    queries = dict(history_queries(backend, "team"))
    assert "job=" + json.dumps(unsafe) in queries["cpu"]
    assert 'namespace="team"' in queries["memory"]
    assert queries["cpu"].startswith("sum(rate(container_cpu_usage_seconds_total{")
    assert queries["cpu"].endswith("}[5m]))")
    assert queries["memory"].startswith("sum(container_memory_working_set_bytes{")
    assert "cluster=" not in queries["cpu"]
    unicode_query = dict(history_queries(replace(backend, matchers=(("job", "owned-🚀"),)), None))[
        "cpu"
    ]
    assert 'job="owned-🚀"' in unicode_query and "\\ud83d" not in unicode_query
    backend = replace(
        backend,
        cluster_label="cluster",
        cluster_value="owned",
        matchers=(("cluster", "owned"), ("namespace", "team")),
    )
    assert backend.labels("team") == (("cluster", "owned"), ("namespace", "team"))
    assert "Configured cluster selector cluster=owned" in backend.scope_label("team")
    with pytest.raises(AppError, match="conflicts"):
        backend.labels("other")


def test_parse_complete_range_preserves_zero_and_decimal_units():
    points, partial = parse_history_range(matrix(), START, NOW)
    assert [point.value for point in points] == [Decimal(0), Decimal("1.5"), Decimal(2)]
    assert points[0].timestamp == START and points[-1].timestamp == NOW
    assert partial is False


def test_missing_points_and_nonfinite_results_are_gaps_not_zero():
    points, partial = parse_history_range(
        matrix([[START.timestamp(), "NaN"], [NOW.timestamp(), "0"]]), START, NOW
    )
    assert [point.value for point in points] == [None, None, Decimal(0)] and partial
    points, partial = parse_history_range(
        {"status": "success", "data": {"resultType": "matrix", "result": []}}, START, NOW
    )
    assert all(point.value is None for point in points) and not partial


@pytest.mark.parametrize("key", ["warnings", "infos"])
def test_backend_notices_remain_partial_without_retaining_server_messages(key):
    points, partial = parse_history_range(
        matrix(**{key: ["synthetic private response"]}), START, NOW
    )
    assert partial and len(points) == 3
    assert "private" not in repr(points)


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {"status": "error", "error": "synthetic private response"},
        {"status": "success"},
        {"status": "success", "data": []},
        {"status": "success", "data": {"resultType": "vector", "result": []}},
        {"status": "success", "data": {"resultType": "matrix", "result": {}}},
        {"status": "success", "data": {"resultType": "matrix", "result": [{}, {}]}},
        {"status": "success", "data": {"resultType": "matrix", "result": [None]}},
        {"status": "success", "data": {"resultType": "matrix", "result": [{}]}},
        matrix([[]]),
        matrix([[NOW.timestamp()]]),
        matrix(["bad"]),
        matrix([[True, "1"]]),
        matrix([[10**1000, "1"]]),
        matrix([[float("nan"), "1"]]),
        matrix([["0", "1"]]),
        matrix([[NOW.timestamp(), 1]]),
        matrix([[NOW.timestamp(), ""]]),
        matrix([[NOW.timestamp(), "1" * 65]]),
        matrix([[NOW.timestamp(), "wrong"]]),
        matrix([[NOW.timestamp(), "-1"]]),
        matrix([[NOW.timestamp(), "1e31"]]),
        matrix([[START.timestamp() - 15, "1"]]),
        matrix([[NOW.timestamp() + 15, "1"]]),
        matrix([[START.timestamp() + 1, "1"]]),
        matrix([[NOW.timestamp(), "1"], [NOW.timestamp(), "2"]]),
        matrix([[NOW.timestamp(), "1"], [START.timestamp(), "2"]]),
        matrix([[NOW.timestamp(), "1"]] * 4),
        matrix([], warnings="wrong"),
        matrix([], warnings=["x"] * 17),
        matrix([], warnings=[None]),
        matrix([], infos=["x" * 513]),
    ],
)
def test_invalid_responses_do_not_become_healthy_zero(document):
    with pytest.raises(AppError) as captured:
        parse_history_range(document, START, NOW)
    assert "synthetic private response" not in str(captured.value)


@pytest.mark.parametrize(
    "start,end,step",
    [
        (START.replace(tzinfo=None), NOW, 15),
        (START, NOW.replace(tzinfo=None), 15),
        (START, NOW, True),
        (START, NOW, 0),
        (START, NOW, 3601),
        (NOW, START, 15),
        (NOW - timedelta(days=2), NOW, 15),
        (NOW - timedelta(days=1), NOW, 1),
    ],
)
def test_query_windows_and_retained_points_are_bounded(start, end, step):
    with pytest.raises(AppError):
        parse_history_range(matrix(), start, end, step)


def test_history_expiry_preserves_scope_and_time_but_clears_usage():
    original = HistorySnapshot(
        HistoryStatus.VALID,
        NOW,
        START,
        NOW,
        series=(HistorySeries("cpu", "CPU", "cores", (HistoryPoint(NOW, Decimal(0)),)),),
        scope_label="Backend scope unverified",
    )
    assert original.fresh(NOW + timedelta(seconds=59)) is original
    for candidate in (original, replace(original, observed_at=None)):
        expired = candidate.fresh(NOW + timedelta(seconds=60))
        assert expired.status is HistoryStatus.STALE
        assert expired.series[0].points[0].value is None
        assert (expired.start, expired.end, expired.scope_label) == (
            START,
            NOW,
            original.scope_label,
        )
        assert expired.fresh(NOW + timedelta(days=1)) is expired
    assert original.fresh(NOW - timedelta(seconds=1)).status is HistoryStatus.STALE
    assert (
        replace(original, status=HistoryStatus.PARTIAL).fresh(NOW).status is HistoryStatus.PARTIAL
    )
