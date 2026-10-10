"""Reproduce normal CLI/PTY combined-load observations against an owned loopback API.

Run as a module from the repository, with a fresh output directory. Short runs
are diagnoses; this observer never declares an issue or release qualified.
"""

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import select
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import Any
from urllib.request import Request, urlopen

import yaml
from coverage import Coverage

from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession

ROOT = Path(__file__).resolve().parents[2]
PROCESS_INTERVAL = 5.0
INPUT_IDLE = 0.2
OUTPUT_LIMIT = 512 * 1024 * 1024
SAMPLE_LIMIT = 12000
MEMORY_WARMUP = 600
MEMORY_WINDOW = 300
MIN_WINDOW_SAMPLES = 54
RSS_ALLOWANCE_KIB = 8192
RSS_ALLOWANCE_FRACTION = 0.05


def interpreter_gc_defaults() -> tuple[int, int, int]:
    """Read this executable's ordinary policy without site/package customization."""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", "import gc,json; print(json.dumps(gc.get_threshold()))"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert len(result.stdout.encode()) <= 1024
    values = json.loads(result.stdout)
    assert isinstance(values, list) and len(values) == 3
    assert all(type(value) is int and value >= 0 for value in values)
    return values[0], values[1], values[2]


def require_normal_gc() -> tuple[int, int, int]:
    expected = interpreter_gc_defaults()
    assert gc.isenabled() and gc.get_threshold() == expected, (
        "Observation requires the enabled, untuned interpreter GC policy",
        expected,
        gc.get_threshold(),
    )
    return expected


def p95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def memory_plateau(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the predeclared late-run windows; short observations cannot pass."""
    result: dict[str, Any] = {
        "warmup_seconds": MEMORY_WARMUP,
        "window_seconds": MEMORY_WINDOW,
        "minimum_samples_per_window": MIN_WINDOW_SAMPLES,
        "rss_allowance_kib": RSS_ALLOWANCE_KIB,
        "rss_allowance_fraction": RSS_ALLOWANCE_FRACTION,
        "descriptor_range_limit": 2,
        "thread_range_limit": 0,
        "processes": {},
        "passed": False,
    }
    windows = [
        [sample for sample in samples if start <= sample["elapsed_seconds"] < start + MEMORY_WINDOW]
        for start in range(MEMORY_WARMUP, 1800, MEMORY_WINDOW)
    ]
    if any(len(window) < MIN_WINDOW_SAMPLES for window in windows):
        result["incomplete_windows"] = [len(window) for window in windows]
        return result
    for process in ("application", "source", "observer"):
        distributions = []
        for window in windows:
            rss = [sample[process]["rss_kib"] for sample in window]
            distributions.append(
                {
                    "samples": len(rss),
                    "median_rss_kib": statistics.median(rss),
                    "p95_rss_kib": p95(rss),
                }
            )
        medians = [window["median_rss_kib"] for window in distributions]
        tails = [window["p95_rss_kib"] for window in distributions]
        allowance = max(RSS_ALLOWANCE_KIB, min(medians) * RSS_ALLOWANCE_FRACTION)
        retained = [sample[process] for window in windows for sample in window]
        descriptor_range = max(s["descriptors"] for s in retained) - min(
            s["descriptors"] for s in retained
        )
        thread_range = max(s["threads"] for s in retained) - min(s["threads"] for s in retained)
        result["processes"][process] = {
            "windows": distributions,
            "rss_allowance_kib": allowance,
            "descriptor_range": descriptor_range,
            "thread_range": thread_range,
            "passed": max(medians) - min(medians) <= allowance
            and max(tails) - min(tails) <= allowance
            and descriptor_range <= 2
            and thread_range == 0,
        }
    result["passed"] = all(process["passed"] for process in result["processes"].values())
    return result


def process_facts(pid: int) -> dict[str, int]:
    directory = Path("/proc") / str(pid)
    status = dict(
        line.split(":", 1)
        for line in (directory / "status").read_text().splitlines()
        if ":" in line
    )
    return {
        "pid": pid,
        "rss_kib": int(status["VmRSS"].split()[0]),
        "peak_rss_kib": int(status["VmHWM"].split()[0]),
        "threads": int(status["Threads"]),
        "descriptors": len(tuple((directory / "fd").iterdir())),
        "start_ticks": int((directory / "stat").read_text().rsplit(")", 1)[1].split()[19]),
    }


def reference_machine() -> dict[str, Any]:
    cpu = next(
        (
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
        platform.processor(),
    )
    memory = next(
        line.split(":", 1)[1].strip()
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemTotal:")
    )
    limits = {}
    for name in ("cpu.max", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            limits[name] = path.read_text().strip()
    return {
        "interpreter": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "cpu_model": cpu,
        "cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "physical_memory": memory,
        "cgroup_limits": limits,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("textual", "kubernetes-asyncio", "pyte", "PyYAML", "coverage")
        },
    }


class StreamingTerminal(TerminalSession):
    """Keep the observer's transcript bounded while preserving ordered raw bytes."""

    def __init__(self, command: list[str], directory: Path, output: Path) -> None:
        self.finishing = False
        self.streamed_bytes = 0
        self.raw_output = (output / "original.ansi").open("xb")
        try:
            super().__init__(command, directory, size=(100, 30))
        except BaseException:
            self.raw_output.close()
            raise

    @property
    def byte_count(self) -> int:
        return self.streamed_bytes + len(self.transcript)

    def flush_output(self) -> None:
        self.raw_output.write(self.transcript)
        self.streamed_bytes += len(self.transcript)
        self.transcript.clear()
        assert self.streamed_bytes <= OUTPUT_LIMIT, "Owned observation disk limit exceeded"

    def _read(self, timeout: float = 0.1) -> None:
        if not self.finishing and len(self.transcript) > 128 * 1024:
            self.flush_output()
        marker = len(self.transcript)
        super()._read(timeout)
        if self.finishing:
            new = self.transcript[marker:]
            self.raw_output.write(new)
            self.streamed_bytes += len(new)
            assert self.streamed_bytes <= OUTPUT_LIMIT

    def finish(self, *, expected: int = 0, timeout: float = 30) -> None:
        self.flush_output()
        self.raw_output.flush()
        # TerminalSession checks initial entry/restoration bytes. Retain only
        # that small prefix in memory; the full transcript stays on disk.
        with (Path(self.raw_output.name)).open("rb") as original:
            self.transcript = bytearray(original.read(8192))
        self.finishing = True
        super().finish(expected=expected, timeout=timeout)

    def __exit__(self, *args: Any) -> None:
        try:
            super().__exit__(*args)
        finally:
            if not self.finishing:
                self.flush_output()
            self.raw_output.close()


def tail_visible(terminal: TerminalSession) -> bool:
    return any(re.search(r"q03-tail-[0-9]{11}", line) for line in terminal.screen.display)


class Observation:
    def __init__(self, output: Path, seconds: int) -> None:
        self.output, self.seconds = output, seconds
        self.source: subprocess.Popen[str] | None = None
        self.url = ""
        self.samples: list[dict[str, Any]] = []
        self.process_samples: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {
            "short_observation": seconds < 1800,
            "diagnostic_only": True,
            "runtime_qualified": False,
            "actual_cli_pty": True,
            "combined_workload": True,
            "reference_machine": reference_machine(),
            "method": {
                "duration_seconds": seconds,
                "process_interval_seconds": PROCESS_INTERVAL,
                "input_idle_seconds": INPUT_IDLE,
                "retention_lines": 10000,
                "retention_bytes": 4194304,
                "source_rows": 10000,
                "resource_rate": 100,
                "log_rate": 2000,
                "artifact_byte_limit": OUTPUT_LIMIT,
                "paint_target_seconds": 0.1,
                "measurement": "public w input to observed wrapped-tail appearance/disappearance",
                "selected_pod": "q03-09999",
            },
        }

    def request(self, action: str, method: str = "POST") -> dict[str, Any]:
        with urlopen(Request(self.url + "/__q03/" + action, method=method), timeout=10) as response:
            value = json.load(response)
        assert isinstance(value, dict)
        return value

    def start_source(self, errors: Any) -> None:
        self.source = subprocess.Popen(
            [sys.executable, "-u", "-m", "tests.support.performance_workload"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            start_new_session=True,
        )
        assert self.source.stdout is not None
        assert select.select([self.source.stdout], [], [], 15)[0], (
            "Source startup deadline exceeded"
        )
        line = self.source.stdout.readline(1024)
        assert line.endswith("\n")
        self.url = json.loads(line)["url"]
        assert self.url.startswith("http://127.0.0.1:")

    def observe(self, terminal: StreamingTerminal) -> None:
        terminal.wait_for_screen("10000 pods", timeout=120)
        terminal.send(b"\x1b[1;5F")
        terminal.wait_for_screen("q03-09999", timeout=30)
        terminal.send(b"l")
        deadline = time.monotonic() + 30
        while True:
            facts = self.request("status", "GET")
            if facts["active_logs"] == facts["active_watches"] == 1:
                break
            terminal._read(0.01)
            assert time.monotonic() < deadline, facts
        terminal.wait_for_screen("q03-row-", timeout=30)
        terminal.wait_for_screen("q03-09999", timeout=30)
        assert not tail_visible(terminal)
        children = (
            (
                Path("/proc")
                / str(terminal.process.pid)
                / "task"
                / str(terminal.process.pid)
                / "children"
            )
            .read_text()
            .split()
        )
        assert len(children) == 1, "Expected the owned session owner to have exactly one CLI child"
        app_pid = int(children[0])
        self.result["application_pid"] = app_pid
        start_ticks = process_facts(app_pid)["start_ticks"]
        self.request("start")
        started = time.monotonic()
        next_process_sample, next_progress = started, started + 60
        while time.monotonic() - started < self.seconds:
            if time.monotonic() >= next_process_sample:
                assert self.source is not None
                application = process_facts(app_pid)
                assert application["start_ticks"] == start_ticks, "CLI process identity changed"
                self.process_samples.append(
                    {
                        "elapsed_seconds": time.monotonic() - started,
                        "application": application,
                        "source": process_facts(self.source.pid),
                        "observer": process_facts(os.getpid()),
                        "source_status": self.request("status", "GET"),
                    }
                )
                assert len(self.process_samples) <= 362
                next_process_sample = time.monotonic() + PROCESS_INTERVAL
            if time.monotonic() >= next_progress:
                print(
                    json.dumps(
                        {
                            "elapsed_seconds": time.monotonic() - started,
                            "process_samples": len(self.process_samples),
                            "paint_samples": len(self.samples),
                        }
                    ),
                    flush=True,
                )
                next_progress = time.monotonic() + 60
            expected = len(self.samples) % 2 == 0
            begin, byte_marker = time.monotonic(), terminal.byte_count
            terminal.send(b"w")
            deadline = begin + 5
            while tail_visible(terminal) is not expected:
                terminal._read(0.001)
                assert terminal.process.poll() is None and time.monotonic() < deadline
            painted = time.monotonic()
            assert terminal.byte_count > byte_marker and len(self.samples) < SAMPLE_LIMIT
            self.samples.append(
                {
                    "input_monotonic": begin,
                    "observed_paint_monotonic": painted,
                    "seconds": painted - begin,
                    "expected_wrapped_tail": expected,
                    "observed_wrapped_tail": tail_visible(terminal),
                    "before_bytes": byte_marker,
                    "after_bytes": terminal.byte_count,
                }
            )
            idle_until = time.monotonic() + INPUT_IDLE
            while time.monotonic() < idle_until:
                terminal._read(min(0.01, max(0, idle_until - time.monotonic())))
        self.result["duration_seconds"] = time.monotonic() - started
        assert self.source is not None
        self.process_samples.append(
            {
                "elapsed_seconds": time.monotonic() - started,
                "application": process_facts(app_pid),
                "source": process_facts(self.source.pid),
                "observer": process_facts(os.getpid()),
                "source_status": self.request("status", "GET"),
            }
        )
        assert len(self.process_samples) <= 362
        self.result["source_at_pause"] = self.request("pause")
        self.result["ten_thousand_retained_visible"] = any(
            "10000 retained" in line for line in terminal.screen.display
        )
        self.result["final_screen"] = terminal.screen.display
        self.result["transcript_bytes"] = terminal.byte_count
        terminal.send(b"\x11")
        terminal.finish()
        self.result["terminal_completion"] = terminal.completion
        self.result["session_exit"] = terminal.process.returncode

    def run(self) -> None:
        paths = [
            *sorted((ROOT / "src/kuberich").rglob("*.py")),
            *sorted((ROOT / "tests/support").glob("*.py")),
            ROOT / "tests/terminal/pty_support.py",
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
        ]

        def snapshot() -> dict[str, str]:
            return {
                p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in paths
            }

        before = snapshot()
        self.result["git_head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
        self.result["tracked_status_before"] = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            text=True,
        )
        self.result["module_file"] = str(Path(__file__).resolve())
        try:
            with (self.output / "source.stderr").open("xb") as errors:
                self.start_source(errors)
                with tempfile.TemporaryDirectory(prefix="kuberich-q03-owned-") as temporary:
                    directory = Path(temporary)
                    cfg = config(
                        directory / "owned-kubeconfig", self.url, {"token": "synthetic-pty"}
                    )
                    owned = yaml.safe_load(cfg.read_text())
                    owned["contexts"][0]["context"]["namespace"] = "team"
                    cfg.write_text(yaml.safe_dump(owned))
                    original_config = cfg.read_bytes()
                    (directory / "preferences.yaml").write_text("schema_version: 1\ntheme: k9s\n")
                    terminal: StreamingTerminal | None = None
                    try:
                        with StreamingTerminal(
                            [
                                sys.executable,
                                "-m",
                                "kuberich",
                                "--kubeconfig",
                                str(cfg),
                                "--context",
                                "kuberich-test-pty",
                                "--readonly",
                            ],
                            directory,
                            self.output,
                        ) as terminal:
                            assert self.source is not None
                            (self.output / "owned-processes.json").write_text(
                                json.dumps(
                                    {
                                        "source_pid": self.source.pid,
                                        "session_owner_pid": terminal.process.pid,
                                    }
                                )
                                + "\n"
                            )
                            self.observe(terminal)
                        assert cfg.read_bytes() == original_config
                        self.result["kubeconfig_unchanged"] = True
                    finally:
                        if terminal is not None:
                            self.result["cli_session_owner_drained"] = (
                                terminal.process.poll() is not None
                            )
                        diagnostic = directory / "kuberich.log"
                        if diagnostic.exists():
                            shutil.copyfile(diagnostic, self.output / "actual-cli-diagnostic.log")
                self.request("close")
                assert self.source is not None
                output, _ = self.source.communicate(timeout=15)
                assert self.source.returncode == 0 and len(output.encode()) < 8192
                self.result["source_final"] = json.loads(output)["final"]
                self.result["source_exit"] = self.source.returncode
                assert all(
                    self.result["source_final"][field] == 0
                    for field in ("active_watches", "active_logs", "workers_running")
                )
        except BaseException as error:
            self.result["error"] = type(error).__name__ + ": " + str(error)
            try:
                self.result["source_on_error"] = self.request("status", "GET")
            except Exception as observation_error:
                self.result["source_observation_error"] = type(observation_error).__name__
            raise
        finally:
            if self.source is not None and self.source.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(self.source.pid, signal.SIGTERM)
                try:
                    output, _ = self.source.communicate(timeout=10)
                    if output.strip():
                        try:
                            self.result["source_final"] = json.loads(output)["final"]
                        except (ValueError, KeyError, TypeError) as cleanup_error:
                            self.result["source_cleanup_error"] = type(cleanup_error).__name__
                    self.result["source_exit"] = self.source.returncode
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(self.source.pid, signal.SIGKILL)
                    self.source.communicate(timeout=10)
            if self.source is not None:
                if self.source.stdout is not None and not self.source.stdout.closed:
                    self.source.communicate(timeout=10)
                self.result["source_owner_drained"] = self.source.poll() is not None
                self.result["source_exit"] = self.source.returncode
            after = snapshot()
            self.result.update(
                {
                    "source_before": before,
                    "source_after": after,
                    "source_unchanged": before == after,
                    "raw_input_paint_samples": self.samples,
                    "process_samples": self.process_samples,
                    "terminal_size": [100, 30],
                    "coverage_active": Coverage.current() is not None,
                    "tracing": sys.gettrace() is not None,
                    "profiling": sys.getprofile() is not None,
                    "normal_gc_enabled": gc.isenabled(),
                    "gc_thresholds": gc.get_threshold(),
                    "p95_seconds": p95([sample["seconds"] for sample in self.samples]),
                    "memory_plateau": memory_plateau(self.process_samples),
                }
            )
            ansi = self.output / "original.ansi"
            if ansi.exists():
                with ansi.open("rb") as original:
                    self.result["original_ansi_sha256"] = hashlib.file_digest(
                        original,
                        "sha256",
                    ).hexdigest()
            (self.output / "receipt.json").write_text(json.dumps(self.result, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        key: self.result[key]
                        for key in (
                            "diagnostic_only",
                            "runtime_qualified",
                            "duration_seconds",
                            "p95_seconds",
                            "source_unchanged",
                            "source_exit",
                            "session_exit",
                            "error",
                        )
                        if key in self.result
                    }
                    | {"samples": len(self.samples)}
                ),
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", choices=(30, 1800), type=int, default=30)
    parser.add_argument("--output", type=Path, required=True, help="Fresh evidence directory.")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("The process-memory observer currently requires Linux /proc.")
    assert Coverage.current() is None and sys.gettrace() is None and sys.getprofile() is None
    default_thresholds = require_normal_gc()
    args.output.mkdir(parents=True, exist_ok=False)

    def interrupted(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt(f"Owned observation interrupted by signal {signum}.")

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        observation = Observation(args.output, args.seconds)
        observation.result["interpreter_default_gc_thresholds"] = default_thresholds
        observation.run()
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
