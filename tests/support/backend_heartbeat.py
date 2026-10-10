"""Bounded read-only attribution of backend heartbeat failures; not qualification."""

import gc
import hashlib
import json
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from coverage import Coverage
from coverage import __version__ as coverage_version

ROOT = Path(__file__).resolve().parents[2]


class HeartbeatDiagnostic:
    """Observe normal GC without collecting, disabling or changing thresholds."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.events: deque[dict[str, Any]] = deque(maxlen=64)
        self.dropped_events = 0
        self.starts: dict[tuple[int, int], float] = {}
        self.started: float | None = None
        self.finished: float | None = None
        self.before = {"enabled": gc.isenabled(), "thresholds": list(gc.get_threshold())}
        self.listener = self._observe

    def _observe(self, phase: str, info: dict[str, Any]) -> None:
        # Young-generation collection callbacks are not diagnostic allocations.
        if info["generation"] != 2:
            return
        now = self.clock()
        key = threading.get_ident(), info["generation"]
        if phase == "start":
            self.starts[key] = now
        else:
            started = self.starts.pop(key, now)
            if len(self.events) == self.events.maxlen:
                self.dropped_events += 1
            self.events.append(
                {
                    "thread": key[0],
                    "generation": key[1],
                    "start": started,
                    "stop": now,
                    "duration_seconds": now - started,
                    "collected": info["collected"],
                    "uncollectable": info["uncollectable"],
                }
            )

    def __enter__(self) -> "HeartbeatDiagnostic":
        self.started = self.clock()
        gc.callbacks.append(self.listener)
        return self

    def __exit__(self, *error: object) -> None:
        gc.callbacks.remove(self.listener)
        self.finished = self.clock()

    def report(self, samples: Sequence[float], *, limit: float) -> dict[str, Any]:
        intervals = tuple(pairwise(samples))
        largest = max(intervals, key=lambda pair: pair[1] - pair[0]) if intervals else None
        coverage = Coverage.current()
        trace, profile = sys.gettrace(), sys.getprofile()
        paths = (
            *sorted((ROOT / "src/kuberich").rglob("*.py")),
            ROOT / "tests/contract/test_aggregate_logs.py",
            ROOT / "tests/support/aggregate_logs.py",
            ROOT / "tests/support/resources.py",
            ROOT / "tests/support/watches.py",
            ROOT / "tests/support/workspace.py",
            ROOT / "tests/conftest.py",
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
            Path(__file__),
        )
        return {
            "schema_version": 1,
            "diagnostic_only": True,
            "runtime_qualified": False,
            "python": sys.version,
            "main_thread": threading.get_ident(),
            "source_inputs": {
                path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths
            },
            "development_iri_grammar_loaded": any(
                name == prefix or name.startswith(prefix + ".")
                for name in sys.modules
                for prefix in ("lark", "rfc3987_syntax")
            ),
            "instrumentation": {
                "coverage_version": coverage_version,
                "coverage_active": coverage is not None,
                "coverage_core": dict(coverage.sys_info())["core"]
                if coverage is not None
                else None,
                "trace_type": type(trace).__name__ if trace is not None else None,
                "profile_type": type(profile).__name__ if profile is not None else None,
            },
            "gc_before": self.before,
            "gc_after": {"enabled": gc.isenabled(), "thresholds": list(gc.get_threshold())},
            "gc_listener_removed": self.listener not in gc.callbacks,
            "started": self.started,
            "finished": self.finished,
            "samples": len(samples),
            "limit_seconds": limit,
            "max_gap_seconds": largest[1] - largest[0] if largest is not None else None,
            "largest_gap": largest,
            "generation_two_events": list(self.events),
            "generation_two_events_dropped": self.dropped_events,
            "generation_two_events_overlapping_largest_gap": [
                event
                for event in self.events
                if largest is not None
                and event["start"] < largest[1]
                and event["stop"] > largest[0]
            ],
        }


def write_heartbeat_diagnostic(
    diagnostic: HeartbeatDiagnostic,
    samples: Sequence[float],
    facts: dict[str, Any],
    *,
    path: Path | None = None,
) -> None:
    path = path or ROOT / "artifacts/backend/aggregate-tiny-lines-heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(diagnostic.report(samples, limit=0.15) | facts, indent=2) + "\n",
        encoding="utf-8",
    )
