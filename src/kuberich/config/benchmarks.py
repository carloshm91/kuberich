"""Offline global and context benchmark defaults; configuration never launches load."""

from dataclasses import dataclass, field
from pathlib import Path

from kuberich.config.schema import ConfigDocument
from kuberich.domain.benchmarks import LoadOptions
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls


@dataclass(frozen=True, slots=True)
class BenchmarkSettings:
    executable: Path | None = None
    load: LoadOptions = field(default_factory=LoadOptions)

    def __post_init__(self) -> None:
        path = self.executable
        if path is not None and (
            not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
            or len(str(path)) > 4096
            or escape_controls(str(path)) != str(path)
        ):
            raise AppError("Benchmark executable must be an explicit absolute path.")
        if not isinstance(self.load, LoadOptions):
            raise AppError("Benchmark load requires validated immutable options.")


def parse_benchmark_settings(
    value: object, *, defaults: BenchmarkSettings | None = None
) -> BenchmarkSettings:
    if not isinstance(value, dict) or value.keys() - {"executable", "load"}:
        raise AppError("Benchmark settings accept only executable and load.")
    base = defaults or BenchmarkSettings()
    path = value.get("executable", base.executable)
    if path is not None and not isinstance(path, (str, Path)):
        raise AppError("Benchmark executable must be an absolute path string.")
    raw = value.get("load", {})
    keys = {"rate", "concurrency", "duration_seconds", "timeout_seconds"}
    if not isinstance(raw, dict) or raw.keys() - keys:
        raise AppError(
            "Benchmark load accepts rate, concurrency, duration_seconds, timeout_seconds."
        )
    return BenchmarkSettings(
        None if path is None else Path(path),
        LoadOptions(**{key: raw.get(key, getattr(base.load, key)) for key in keys}),
    )


def serialize_benchmark_settings(settings: BenchmarkSettings) -> dict[str, object]:
    load = settings.load
    return {
        "executable": None if settings.executable is None else str(settings.executable),
        "load": {
            "rate": load.rate,
            "concurrency": load.concurrency,
            "duration_seconds": load.duration_seconds,
            "timeout_seconds": load.timeout_seconds,
        },
    }


def benchmarks_from(document: ConfigDocument, context: str | None = None) -> BenchmarkSettings:
    raw = document.extensions.get("benchmarks", {})
    if not isinstance(raw, dict) or raw.keys() - {"schema_version", "defaults", "contexts"}:
        raise AppError("benchmarks accepts schema_version, defaults and contexts.")
    if type(raw.get("schema_version", 1)) is not int or raw.get("schema_version", 1) != 1:
        raise AppError("benchmarks.schema_version must be 1.")
    base = parse_benchmark_settings(raw.get("defaults", {}))
    contexts = raw.get("contexts", {})
    if not isinstance(contexts, dict) or len(contexts) > 128:
        raise AppError("Benchmark configuration allows at most 128 contexts.")
    parsed: dict[str, BenchmarkSettings] = {}
    for name, settings in contexts.items():
        if not isinstance(name, str) or not 1 <= len(name) <= 253 or escape_controls(name) != name:
            raise AppError("Benchmark context names require bounded text without controls.")
        parsed[name] = parse_benchmark_settings(settings, defaults=base)
    return parsed.get(context or "", base)
