"""Receipt budgets, owned process observations and failure cleanup for Q03."""

import copy
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.support.performance_terminal import (
    StreamingTerminal,
    memory_plateau,
    p95,
    process_facts,
)
from tests.terminal.pty_support import TerminalSession

ROOT = Path(__file__).resolve().parents[2]


def samples():
    return [
        {
            "elapsed_seconds": elapsed,
            **{
                process: {"rss_kib": 150000, "descriptors": 11, "threads": 13}
                for process in ("application", "source", "observer")
            },
        }
        for elapsed in range(0, 1801, 5)
    ]


def test_quantile_uses_the_upper_observed_order_statistic_and_preserves_raw_values():
    values = [0.01] * 94 + [0.2] * 6
    original = values.copy()
    assert p95(values) == 0.2 and values == original
    assert p95([0.07]) == 0.07 and p95([]) is None


def test_stable_windows_accept_after_warmup_but_a_short_observation_cannot():
    values = samples()
    for sample in values:
        if sample["elapsed_seconds"] < 600:
            sample["application"]["rss_kib"] = 999999
    report = memory_plateau(values)
    assert report["passed"]
    assert all(len(process["windows"]) == 4 for process in report["processes"].values())
    assert not memory_plateau(values[:7])["passed"]
    assert not memory_plateau([])["passed"]
    assert not memory_plateau(values[:350])["passed"]


@pytest.mark.parametrize("process", ["application", "source", "observer"])
@pytest.mark.parametrize("leak", ["rss_kib", "descriptors", "threads"])
def test_sustained_rss_descriptor_or_thread_growth_rejects_the_plateau(process, leak):
    values = samples()
    for sample in values:
        if sample["elapsed_seconds"] >= 600:
            window = (sample["elapsed_seconds"] - 600) // 300
            sample[process][leak] += window * (20000 if leak == "rss_kib" else 1)
    original = copy.deepcopy(values)
    report = memory_plateau(values)
    assert not report["passed"] and not report["processes"][process]["passed"]
    assert values == original


def test_rss_tail_growth_rejects_even_when_the_median_is_stable():
    values = samples()
    for sample in values:
        if sample["elapsed_seconds"] >= 1500 and sample["elapsed_seconds"] % 25 == 0:
            sample["application"]["rss_kib"] += 20000
    report = memory_plateau(values)
    process = report["processes"]["application"]
    assert len({window["median_rss_kib"] for window in process["windows"]}) == 1
    assert not report["passed"] and not process["passed"]


def test_failed_terminal_constructor_closes_the_original_transcript(tmp_path, monkeypatch):
    captured = []

    def fail(self, *args, **kwargs):
        captured.append(self)
        raise OSError("Owned constructor failure")

    monkeypatch.setattr(TerminalSession, "__init__", fail)
    with pytest.raises(OSError, match="Owned constructor failure"):
        StreamingTerminal([sys.executable, "-c", "pass"], tmp_path, tmp_path)
    assert captured[0].raw_output.closed
    assert (tmp_path / "original.ansi").read_bytes() == b""


@pytest.mark.skipif(sys.platform != "linux", reason="The RSS observer requires Linux /proc.")
def test_live_process_identity_and_descriptor_measurement(tmp_path):
    before = process_facts(os.getpid())
    with (tmp_path / "owned-fd").open("wb"):
        during = process_facts(os.getpid())
        assert during["descriptors"] == before["descriptors"] + 1
    after = process_facts(os.getpid())
    assert after["descriptors"] == before["descriptors"]
    assert before["start_ticks"] == during["start_ticks"] == after["start_ticks"]
    assert during["rss_kib"] > 0 and during["peak_rss_kib"] >= during["rss_kib"]


@pytest.mark.skipif(sys.platform != "linux", reason="The RSS observer requires Linux /proc.")
def test_signal_interruption_preserves_evidence_and_drains_owned_source(tmp_path):
    output = tmp_path / "signal-original"
    with (
        (tmp_path / "stdout.log").open("wb") as stdout,
        (tmp_path / "stderr.log").open("wb") as stderr,
    ):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.support.performance_terminal",
                "--seconds",
                "30",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
        )
        try:
            deadline = time.monotonic() + 30
            while not (output / "owned-processes.json").exists():
                assert process.poll() is None, (tmp_path / "stderr.log").read_text()
                assert time.monotonic() < deadline, "Owned source/terminal did not start"
                time.sleep(0.01)
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=20) != 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["error"].startswith("KeyboardInterrupt:")
    assert receipt["source_unchanged"] and receipt["source_owner_drained"]
    assert receipt["cli_session_owner_drained"]
    assert receipt["source_exit"] == 0 and not receipt["runtime_qualified"]
    assert all(
        receipt["source_final"][key] == 0
        for key in ("active_logs", "active_watches", "workers_running")
    )


@pytest.mark.skipif(sys.platform != "linux", reason="The RSS observer requires Linux /proc.")
def test_existing_output_is_rejected_without_replacing_original_evidence(tmp_path):
    sentinel = tmp_path / "original.ansi"
    sentinel.write_bytes(b"retain this original")
    result = subprocess.run(
        [sys.executable, "-m", "tests.support.performance_terminal", "--output", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode != 0 and b"FileExistsError" in result.stderr
    assert (
        sentinel.read_bytes() == b"retain this original"
        and not (tmp_path / "receipt.json").exists()
    )
