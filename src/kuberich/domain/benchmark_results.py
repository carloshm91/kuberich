"""Strict pinned Vegeta metrics and privacy-preserving normalized result records."""

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from kuberich.domain.benchmarks import METHODS, VEGETA_PARSER_ID, VEGETA_VERSION, LoadOptions
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

MAX_RECORD_BYTES = 32 * 1024
MAX_RECORDS = 100
MAX_STORE_BYTES = 4 * 1024 * 1024
RETENTION_DAYS = 30
MAX_REPORT_BYTES = 64 * 1024
type BenchmarkCompletion = Literal[
    "complete", "cancelled", "target_lost", "tool_failed", "malformed_output", "cleanup_failed"
]
_COMPLETIONS = {
    "complete",
    "cancelled",
    "target_lost",
    "tool_failed",
    "malformed_output",
    "cleanup_failed",
}
_STAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})"
)


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    attempts: int
    status_counts: tuple[tuple[int, int], ...]
    transport_failures: int
    http_failures: int
    redirects: int
    successful_requests: int
    errors_present: bool
    latency_min_ns: int
    latency_mean_ns: int
    latency_p50_ns: int
    latency_p90_ns: int
    latency_p95_ns: int
    latency_p99_ns: int
    latency_max_ns: int
    duration_ns: int
    wait_ns: int
    actual_rate: float | None
    throughput: float | None


@dataclass(frozen=True, slots=True)
class BenchmarkProvenance:
    context: str
    namespace: str
    pod_name: str
    pod_uid: str
    pod_port: int
    service_name: str | None = None
    service_uid: str | None = None
    service_port: int | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    run_id: UUID
    started_at: datetime
    finished_at: datetime
    tool_version: str | None
    target: BenchmarkProvenance
    method: str
    load: LoadOptions
    completion: BenchmarkCompletion
    metrics: BenchmarkMetrics | None


def _invalid() -> AppError:
    return AppError("Invalid or unsupported benchmark result; no raw tool output was retained.")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise _invalid()


def _load(data: bytes, maximum: int) -> Any:
    if not data or len(data) > maximum:
        raise _invalid()
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid() from None


def _fields(value: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() != names:
        raise _invalid()
    return cast(dict[str, Any], value)


def _int(value: Any, maximum: int = 2**63 - 1, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid()
    return value


def _number(value: Any, maximum: float = 1e15) -> float:
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
        raise _invalid()
    return float(value)


def _text(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 253
        or escape_controls(value) != value
        or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise _invalid()
    return value


def _timestamp(value: Any) -> tuple[datetime, int]:
    if not isinstance(value, str) or (match := _STAMP.fullmatch(value)) is None:
        raise _invalid()
    try:
        base = datetime.fromisoformat(match[1] + match[3].replace("Z", "+00:00"))
        nanos = int((match[2] or "").ljust(9, "0"))
        stamp = int(base.timestamp()) * 1_000_000_000 + nanos
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC), stamp
    except (ValueError, OverflowError, OSError):
        raise _invalid() from None


def _counts(value: Any, attempts: int) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, dict) or not value or len(value) > 501:
        raise _invalid()
    counts = []
    for code, count in value.items():
        if not isinstance(code, str) or re.fullmatch(r"0|[1-5][0-9]{2}", code) is None:
            raise _invalid()
        counts.append((int(code), _int(count, attempts, 1)))
    if sum(count for _, count in counts) != attempts:
        raise _invalid()
    return tuple(sorted(counts))


def parse_vegeta_report(
    data: bytes, load: LoadOptions, *, version: str = VEGETA_VERSION
) -> BenchmarkMetrics:
    if version != VEGETA_VERSION:
        raise _invalid()
    raw = _fields(
        _load(data, MAX_REPORT_BYTES),
        {
            "latencies",
            "bytes_in",
            "bytes_out",
            "earliest",
            "latest",
            "end",
            "duration",
            "wait",
            "requests",
            "rate",
            "throughput",
            "success",
            "status_codes",
            "errors",
        },
    )
    attempts = _int(raw["requests"], load.nominal_requests + 1, 1)
    counts = _counts(raw["status_codes"], attempts)
    for name in ("bytes_in", "bytes_out"):
        byte = _fields(raw[name], {"total", "mean"})
        total = _int(byte["total"], 2**64 - 1)
        if not math.isclose(_number(byte["mean"], 2**64), total / attempts, rel_tol=1e-9):
            raise _invalid()
    errors = raw["errors"]
    if (
        not isinstance(errors, list)
        or len(errors) > attempts
        or any(not isinstance(item, str) for item in errors)
    ):
        raise _invalid()
    lat = _fields(raw["latencies"], {"total", "mean", "50th", "90th", "95th", "99th", "max", "min"})
    bound = (load.timeout_seconds + 2) * 1_000_000_000
    minimum, mean, p50, p90, p95, p99, maximum = (
        _int(lat[key], bound) for key in ("min", "mean", "50th", "90th", "95th", "99th", "max")
    )
    total_latency = _int(lat["total"], attempts * bound)
    if (
        not minimum <= p50 <= p90 <= p95 <= p99 <= maximum
        or not minimum <= mean <= maximum
        or mean != int(total_latency / attempts)
    ):
        raise _invalid()
    wall_bound = (load.duration_seconds + load.timeout_seconds + 2) * 1_000_000_000
    duration = _int(raw["duration"], wall_bound)
    wait = _int(raw["wait"], bound)
    if duration + wait > wall_bound:
        raise _invalid()
    _, earliest = _timestamp(raw["earliest"])
    _, latest = _timestamp(raw["latest"])
    _, end = _timestamp(raw["end"])
    if latest - earliest != duration or end - latest != wait:
        raise _invalid()
    successful = sum(count for code, count in counts if 200 <= code < 400)
    rate, throughput, success = (_number(raw[key]) for key in ("rate", "throughput", "success"))
    expected_rate = attempts * 1e9 / duration if duration else float(attempts)
    expected_throughput = successful * 1e9 / (duration + wait) if duration else float(successful)
    if not all(
        math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
        for actual, expected in (
            (rate, expected_rate),
            (throughput, expected_throughput),
            (success, successful / attempts),
        )
    ):
        raise _invalid()
    return BenchmarkMetrics(
        attempts,
        counts,
        dict(counts).get(0, 0),
        sum(count for code, count in counts if code >= 400),
        sum(count for code, count in counts if 300 <= code < 400),
        successful,
        bool(errors),
        minimum,
        mean,
        p50,
        p90,
        p95,
        p99,
        maximum,
        duration,
        wait,
        rate if duration else None,
        throughput if duration else None,
    )


def _read_metrics(value: Any, load: LoadOptions) -> BenchmarkMetrics:
    names = set(BenchmarkMetrics.__dataclass_fields__)
    raw = _fields(value, names)
    attempts = _int(raw["attempts"], load.nominal_requests + 1, 1)
    pairs = raw["status_counts"]
    if not isinstance(pairs, list) or any(
        not isinstance(pair, list) or len(pair) != 2 for pair in pairs
    ):
        raise _invalid()
    counts: dict[str, Any] = {}
    for code, count in pairs:
        if str(code) in counts or type(code) is not int:
            raise _invalid()
        counts[str(code)] = count
    checked = _counts(counts, attempts)
    expected = {
        "transport_failures": dict(checked).get(0, 0),
        "http_failures": sum(count for code, count in checked if code >= 400),
        "redirects": sum(count for code, count in checked if 300 <= code < 400),
        "successful_requests": sum(count for code, count in checked if 200 <= code < 400),
    }
    for key, count in expected.items():
        if _int(raw[key], attempts) != count:
            raise _invalid()
    if type(raw["errors_present"]) is not bool:
        raise _invalid()
    latency_keys = [
        "latency_min_ns",
        "latency_p50_ns",
        "latency_p90_ns",
        "latency_p95_ns",
        "latency_p99_ns",
        "latency_max_ns",
    ]
    values = [_int(raw[key], (load.timeout_seconds + 2) * 10**9) for key in latency_keys]
    if values != sorted(values) or not values[0] <= _int(raw["latency_mean_ns"]) <= values[-1]:
        raise _invalid()
    wall_bound = (load.duration_seconds + load.timeout_seconds + 2) * 10**9
    duration = _int(raw["duration_ns"], wall_bound)
    wait = _int(raw["wait_ns"], (load.timeout_seconds + 2) * 10**9)
    if duration + wait > wall_bound:
        raise _invalid()
    for key, numerator, denominator in (
        ("actual_rate", attempts, duration),
        ("throughput", expected["successful_requests"], duration + wait),
    ):
        value = raw[key]
        if not duration:
            if value is not None:
                raise _invalid()
        elif not math.isclose(_number(value), numerator * 1e9 / denominator, rel_tol=1e-9):
            raise _invalid()
    return BenchmarkMetrics(**{**raw, "status_counts": checked})


def decode_result(data: bytes) -> BenchmarkResult:
    raw = _fields(
        _load(data, MAX_RECORD_BYTES),
        {
            "schema_version",
            "parser_id",
            "run_id",
            "started_at",
            "finished_at",
            "tool_version",
            "target",
            "method",
            "load",
            "completion",
            "metrics",
        },
    )
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
        or raw["parser_id"] != VEGETA_PARSER_ID
        or raw["tool_version"] not in (None, VEGETA_VERSION)
    ):
        raise _invalid()
    try:
        run_id = UUID(raw["run_id"])
    except (ValueError, TypeError, AttributeError):
        raise _invalid() from None
    if str(run_id) != raw["run_id"]:
        raise _invalid()
    started, start_ns = _timestamp(raw["started_at"])
    finished, finish_ns = _timestamp(raw["finished_at"])
    if finish_ns < start_ns:
        raise _invalid()
    target = _fields(raw["target"], set(BenchmarkProvenance.__dataclass_fields__))
    for key in ("context", "namespace", "pod_name", "pod_uid"):
        _text(target[key])
    _int(target["pod_port"], 65535, 1)
    service = (target["service_name"], target["service_uid"], target["service_port"])
    if any(item is not None for item in service):
        _text(service[0])
        _text(service[1])
        _int(service[2], 65535, 1)
    if (
        not isinstance(raw["method"], str)
        or raw["method"] not in METHODS
        or not isinstance(raw["completion"], str)
        or raw["completion"] not in _COMPLETIONS
    ):
        raise _invalid()
    load = LoadOptions(**_fields(raw["load"], set(LoadOptions.__dataclass_fields__)))
    metrics = None if raw["metrics"] is None else _read_metrics(raw["metrics"], load)
    if (raw["completion"] == "complete" and metrics is None) or (
        raw["tool_version"] is None and (raw["completion"] == "complete" or metrics is not None)
    ):
        raise _invalid()
    return BenchmarkResult(
        run_id,
        started,
        finished,
        raw["tool_version"],
        BenchmarkProvenance(**target),
        raw["method"],
        load,
        cast(BenchmarkCompletion, raw["completion"]),
        metrics,
    )


def encode_result(result: BenchmarkResult) -> bytes:
    raw = asdict(result)
    raw.update(schema_version=1, parser_id=VEGETA_PARSER_ID, run_id=str(result.run_id))
    for key, stamp in (("started_at", result.started_at), ("finished_at", result.finished_at)):
        if stamp.tzinfo is None:
            raise _invalid()
        raw[key] = stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        data = (
            json.dumps(raw, allow_nan=False, ensure_ascii=True, separators=(",", ":")) + "\n"
        ).encode()
    except (ValueError, TypeError):
        raise _invalid() from None
    decode_result(data)
    return data
