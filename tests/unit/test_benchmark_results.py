"""Known external schema, nanosecond semantics and hostile saved-record refusal."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from kuberich.domain.benchmark_results import (
    BenchmarkProvenance,
    BenchmarkResult,
    decode_result,
    encode_result,
    parse_vegeta_report,
)
from kuberich.domain.benchmarks import LoadOptions
from kuberich.errors import AppError

# The coordinator executed pinned Vegeta against an owned local HTTP server.
# Preserve its nine-digit timestamps and the tool's first-to-last-start denominator.
OBSERVED = json.loads(
    (Path(__file__).parents[1] / "fixtures/benchmarks/vegeta-12.13.0-http200.json").read_bytes()
)


def report_data(raw=None):
    return json.dumps(OBSERVED if raw is None else raw).encode()


def result(metrics=True):
    stamp = datetime(2026, 11, 10, tzinfo=UTC)
    return BenchmarkResult(
        UUID("64fb938b-0897-4204-ac9c-01f5d3723d42"),
        stamp,
        stamp + timedelta(seconds=2),
        "12.13.0",
        BenchmarkProvenance("local", "demo", "web", "pod-uid", 8080, "web", "service-uid", 80),
        "GET",
        LoadOptions(),
        "complete" if metrics else "cancelled",
        parse_vegeta_report(report_data(), LoadOptions()) if metrics else None,
    )


def test_observed_schema_preserves_exact_ns_and_explains_rate_semantics():
    metrics = parse_vegeta_report(report_data(), LoadOptions(duration_seconds=2, timeout_seconds=1))
    assert metrics.attempts == 2 and metrics.status_counts == ((200, 2),)
    assert metrics.latency_p99_ns == 1458412 and metrics.duration_ns == 1000016353
    assert metrics.wait_ns == 773308 and metrics.actual_rate == OBSERVED["rate"]
    assert metrics.throughput == OBSERVED["throughput"] and metrics.errors_present is False


def test_status_counts_distinguish_transport_http_redirects_and_discard_private_messages():
    raw = deepcopy(OBSERVED)
    raw.update(
        requests=6,
        status_codes={"0": 1, "101": 1, "200": 2, "302": 1, "503": 1},
        errors=["dial token=private", "body credential=secret"],
        success=0.5,
        rate=6e9 / raw["duration"],
        throughput=3e9 / (raw["duration"] + raw["wait"]),
    )
    raw["latencies"]["total"] = raw["latencies"]["mean"] * 6
    metrics = parse_vegeta_report(report_data(raw), LoadOptions())
    assert metrics.transport_failures == 1 and metrics.http_failures == 1 and metrics.redirects == 1
    assert metrics.successful_requests == 3 and metrics.errors_present
    assert "private" not in repr(metrics) and "secret" not in repr(metrics)


def test_single_sample_has_no_meaningful_tool_rate_denominator():
    raw = deepcopy(OBSERVED)
    raw.update(
        requests=1,
        status_codes={"200": 1},
        earliest="2026-11-10T20:35:22Z",
        latest="2026-11-10T20:35:22Z",
        end="2026-11-10T20:35:22.001Z",
        duration=0,
        wait=1000000,
        rate=1,
        throughput=1,
    )
    raw["latencies"] = dict.fromkeys(raw["latencies"], 1000000)
    metrics = parse_vegeta_report(report_data(raw), LoadOptions())
    assert metrics.actual_rate is None and metrics.throughput is None and metrics.attempts == 1
    assert decode_result(encode_result(replace(result(), metrics=metrics))).metrics == metrics


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x" * 65537,
        b"\xff",
        b"{",
        b"[]",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_bounded_json_duplicate_nonfinite_and_structural_refusal(data):
    with pytest.raises(AppError):
        parse_vegeta_report(data, LoadOptions())


@pytest.mark.parametrize(
    "path,value",
    [
        (("requests",), 0),
        (("requests",), 7),
        (("requests",), True),
        (("requests",), 2.0),
        (("unknown",), "private"),
        (("latencies",), []),
        (("latencies", "max"), -1),
        (("latencies", "max"), 9 * 10**9),
        (("latencies", "mean"), 0),
        (("latencies", "total"), 1),
        (("latencies", "95th"), 0),
        (("bytes_in", "total"), -1),
        (("bytes_out", "mean"), 2),
        (("bytes_in", "mean"), 10**1000),
        (("rate",), 1e309),
        (("throughput",), False),
        (("success",), 0),
        (("rate",), 3),
        (("status_codes",), []),
        (("status_codes",), {}),
        (("status_codes",), {"0200": 2}),
        (("status_codes",), {"600": 2}),
        (("status_codes",), {"200": 1}),
        (("status_codes",), {"200": 0}),
        (("status_codes",), {"200": 2, "201": 1}),
        (("errors",), "private"),
        (("errors",), [1]),
        (("errors",), ["a", "b", "c"]),
        (("duration",), 40 * 10**9),
        (("wait",), -1),
        (("earliest",), False),
        (("earliest",), "wrong"),
        (("earliest",), "2026-99-10T20:35:22Z"),
        (("end",), "2026-11-10T20:35:23Z"),
        (("latest",), "2026-11-10T20:35:20Z"),
    ],
)
def test_report_rejects_inconsistent_or_unknown_fields(path, value):
    raw = deepcopy(OBSERVED)
    destination = raw
    for key in path[:-1]:
        destination = destination[key]
    destination[path[-1]] = value
    with pytest.raises(AppError):
        parse_vegeta_report(report_data(raw), LoadOptions())


def test_unknown_producer_and_missing_field_refused():
    with pytest.raises(AppError):
        parse_vegeta_report(report_data(), LoadOptions(), version="12.14.0")
    raw = deepcopy(OBSERVED)
    del raw["bytes_out"]
    with pytest.raises(AppError):
        parse_vegeta_report(report_data(raw), LoadOptions())


def test_result_roundtrip_has_no_replayable_endpoint_or_request_secrets():
    original = result()
    data = encode_result(original)
    assert decode_result(data) == original
    assert all(
        key not in data
        for key in (b"headers", b"body", b"url", b"kubeconfig", b"generation", b"connection_id")
    )
    assert decode_result(encode_result(result(False))) == result(False)
    no_tool = replace(result(False), tool_version=None, completion="tool_failed")
    assert decode_result(encode_result(no_tool)) == no_tool
    pod_only = replace(original, target=BenchmarkProvenance("local", "demo", "web", "uid", 80))
    assert decode_result(encode_result(pod_only)) == pod_only
    offset = original.started_at.astimezone(
        datetime.fromisoformat("2026-01-01T00:00:00+05:00").tzinfo
    )
    assert decode_result(encode_result(replace(original, started_at=offset))) == original


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("schema_version",), 2),
        (("parser_id",), "unknown"),
        (("tool_version",), "unknown"),
        (("tool_version",), None),
        (("run_id",), None),
        (("run_id",), {}),
        (("run_id",), "bad"),
        (("run_id",), str(uuid4()).upper()),
        (("finished_at",), "2026-11-09T00:00:00Z"),
        (("target", "context"), "bad\n"),
        (("target", "context"), "\ud800"),
        (("target", "namespace"), False),
        (("target", "pod_name"), ""),
        (("target", "pod_uid"), "a" * 254),
        (("target", "pod_port"), 0),
        (("target", "service_uid"), None),
        (("method",), "TRACE"),
        (("method",), []),
        (("completion",), "unknown"),
        (("completion",), []),
        (("load", "rate"), 51),
        (("load", "body"), "private"),
        (("metrics",), None),
        (("metrics", "attempts"), 0),
        (("metrics", "status_counts"), None),
        (("metrics", "status_counts"), [[200]]),
        (("metrics", "status_counts"), [["200", 2]]),
        (("metrics", "status_counts"), [[200, 1], [200, 1]]),
        (("metrics", "transport_failures"), 1),
        (("metrics", "errors_present"), 0),
        (("metrics", "latency_p95_ns"), 0),
        (("metrics", "latency_mean_ns"), 0),
        (("metrics", "actual_rate"), 0),
        (("metrics", "throughput"), 0),
    ],
)
def test_saved_record_allowlist_validation(path, value):
    raw = json.loads(encode_result(result()))
    destination = raw
    for key in path[:-1]:
        destination = destination[key]
    destination[path[-1]] = value
    with pytest.raises(AppError):
        decode_result(json.dumps(raw).encode())


def test_single_request_saved_rates_cannot_be_invented():
    metrics = replace(result().metrics, duration_ns=0, actual_rate=1.0, throughput=None)
    with pytest.raises(AppError):
        encode_result(replace(result(), metrics=metrics))


def test_missing_tool_may_not_claim_metrics_and_naive_dates_cannot_serialize():
    with pytest.raises(AppError):
        encode_result(replace(result(), tool_version=None, completion="tool_failed"))
    with pytest.raises(AppError):
        encode_result(replace(result(False), started_at=datetime(2026, 11, 10)))
    with pytest.raises(AppError):
        encode_result(replace(result(), method=object()))
    with pytest.raises(AppError):
        decode_result(b" " * 32769)
