"""Normalized summaries preserve the pinned tool's rate and status semantics."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from kuberich.domain.benchmark_results import (
    BenchmarkMetrics,
    BenchmarkProvenance,
    BenchmarkResult,
)
from kuberich.domain.benchmark_targets import BenchmarkBackend
from kuberich.domain.benchmarks import LoadOptions
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.ui.benchmark_presentation import backend_label, result_text


def result():
    return BenchmarkResult(
        uuid4(),
        datetime(2026, 11, 10, tzinfo=UTC),
        datetime(2026, 11, 10, 0, 0, 5, tzinfo=UTC),
        "12.13.0",
        BenchmarkProvenance("synthetic", "team", "web", "pod-uid", 8080, "web", "svc-uid", 80),
        "POST",
        LoadOptions(),
        "complete",
        BenchmarkMetrics(
            5,
            ((0, 1), (200, 1), (302, 1), (404, 1), (503, 1)),
            1,
            2,
            1,
            2,
            True,
            1_000_000,
            3_000_000,
            2_000_000,
            3_000_000,
            4_000_000,
            5_000_000,
            6_000_000,
            4_000_000_000,
            1_000_000_000,
            1.25,
            0.4,
        ),
    )


def test_summary_distinguishes_requested_and_measured_rate_statuses_and_latency():
    text = result_text(result()).plain
    assert "requested rate: 1 requests/s" in text
    assert "Measured start rate: 1.250 requests/s" in text
    assert "Successful throughput (2xx/3xx): 0.400 requests/s" in text
    assert "tool success (2xx/3xx): 2" in text
    assert "Transport failures (status 0): 1" in text
    assert "HTTP failures (4xx/5xx): 2 · redirects (3xx): 1" in text
    assert "Tool reported errors: present" in text
    assert "p50 2.000 · p90 3.000 · p95 4.000 · p99 5.000" in text
    assert "Service: web:80 · UID svc-uid" in text
    assert "not an exact per-second ceiling" in text


def test_missing_metrics_zero_interval_and_hostile_metadata_remain_explicit_and_literal():
    value = result()
    unavailable = result_text(
        replace(value, tool_version=None, metrics=None, completion="tool_failed")
    ).plain
    assert "tool failed" in unavailable and "version: unavailable" in unavailable
    assert "No trustworthy metrics" in unavailable
    metrics = replace(
        value.metrics, duration_ns=0, actual_rate=None, throughput=None, errors_present=False
    )
    hostile = replace(value.target, context="[red]synthetic[/red]\x1b", service_name=None)
    rendered = result_text(replace(value, target=hostile, metrics=metrics))
    assert "N/A (no measured interval)" in rendered.plain
    assert "Tool reported errors: none" in rendered.plain and "Service:" not in rendered.plain
    assert "[red]synthetic[/red]" in rendered.plain and "\x1b" not in rendered.plain
    assert not rendered.spans


def test_backend_labels_identify_selected_service_and_pod_port_and_uid():
    identity = SessionIdentity("synthetic", 1)
    pod = ResourceTarget(identity, "", "pods", "team", "web", "pod-uid")
    service = ResourceTarget(identity, "", "services", "team", "web", "svc-uid")
    assert backend_label(BenchmarkBackend(service, pod, 80, 8080)) == (
        "Service web:80 → Pod web:8080 · UID pod-uid"
    )
    assert backend_label(BenchmarkBackend(None, pod, None, 8080)) == "Pod web:8080 · UID pod-uid"
