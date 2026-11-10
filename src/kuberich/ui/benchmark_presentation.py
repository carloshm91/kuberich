"""Safe benchmark summaries shared by the active run and offline result viewer."""

from rich.text import Text

from kuberich.domain.benchmark_results import BenchmarkResult
from kuberich.domain.benchmark_targets import BenchmarkBackend
from kuberich.security.presentation import safe_text


def backend_label(backend: BenchmarkBackend) -> str:
    pod = backend.pod
    service = f"Service {backend.service.name}:{backend.service_port} → " if backend.service else ""
    return f"{service}Pod {pod.name}:{backend.pod_port} · UID {pod.uid}"


def _rate(value: float | None) -> str:
    return "N/A (no measured interval)" if value is None else f"{value:.3f} requests/s"


def result_text(result: BenchmarkResult) -> Text:
    target, load, metrics = result.target, result.load, result.metrics
    lines = [
        f"Result: {result.completion.replace('_', ' ')} · run {result.run_id}",
        f"Context: {target.context} · namespace: {target.namespace}",
    ]
    if target.service_name is not None:
        lines.append(
            f"Service: {target.service_name}:{target.service_port} · UID {target.service_uid}"
        )
    lines.extend(
        (
            f"Single backend Pod: {target.pod_name}:{target.pod_port} · UID {target.pod_uid}",
            f"Method: {result.method} · requested rate: {load.rate} requests/s · concurrency: {load.concurrency}",
            f"Configured duration: {load.duration_seconds}s · request timeout: {load.timeout_seconds}s · nominal request budget: {load.nominal_requests}",
            f"Started: {result.started_at.isoformat()} · finished: {result.finished_at.isoformat()}",
            f"Vegeta version: {result.tool_version or 'unavailable'}",
            "HTTP/1.1 · fresh connections · redirects disabled · one captured backend",
        )
    )
    if metrics is None:
        lines.append("No trustworthy metrics are available for this run.")
    else:
        lines.extend(
            (
                f"Recorded attempts: {metrics.attempts} · tool success (2xx/3xx): {metrics.successful_requests}",
                f"Transport failures (status 0): {metrics.transport_failures} · HTTP failures (4xx/5xx): {metrics.http_failures} · redirects (3xx): {metrics.redirects}",
                "Tool reported errors: " + ("present" if metrics.errors_present else "none"),
                "Status counts: "
                + ", ".join(f"{code}: {count}" for code, count in metrics.status_counts),
                f"Measured start rate: {_rate(metrics.actual_rate)}",
                f"Successful throughput (2xx/3xx): {_rate(metrics.throughput)}",
                f"Attack interval: {metrics.duration_ns / 1e9:.3f}s · final response wait: {metrics.wait_ns / 1e9:.3f}s",
                f"Latency ms · min {metrics.latency_min_ns / 1e6:.3f} · mean {metrics.latency_mean_ns / 1e6:.3f} · max {metrics.latency_max_ns / 1e6:.3f}",
                f"Estimated latency percentiles ms · p50 {metrics.latency_p50_ns / 1e6:.3f} · p90 {metrics.latency_p90_ns / 1e6:.3f} · p95 {metrics.latency_p95_ns / 1e6:.3f} · p99 {metrics.latency_p99_ns / 1e6:.3f}",
                "Latency samples include recorded failures. Requested pacing may catch up; it is not an exact per-second ceiling.",
            )
        )
    lines.append("Saved records omit request path, query, header values and body.")
    return safe_text("\n".join(lines), multiline=True)
