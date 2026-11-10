"""Actual optional Vegeta load cancels before Escape restores the terminal workspace."""

import os
import sys
from pathlib import Path

import pytest

from tests.support.benchmark_terminal import terminal_benchmark, terminal_benchmark_missing_tool


@pytest.mark.parametrize("stop", ["escape", "cancel", "complete", "ctrlc", "sigterm"])
def test_actual_terminal_benchmark_review_run_cancel_and_restoration(tmp_path, stop):
    configured = os.environ.get("KUBERICH_TEST_VEGETA")
    if configured is None:
        pytest.skip("Set KUBERICH_TEST_VEGETA to the explicit pinned Vegeta executable.")
    vegeta = Path(configured)
    assert vegeta.is_absolute() and vegeta.is_file()
    terminal_benchmark(
        [sys.executable, "-m", "kuberich"], tmp_path, "benchmarks-" + stop, vegeta=vegeta, stop=stop
    )


def test_missing_benchmark_tool_does_not_start_forward_or_load(tmp_path):
    prepared = []

    def prepare(command, environment):
        assert environment["OWNED_BENCHMARK_PORT"]
        assert "--benchmark-directory" in command
        prepared.append(command)
        return command

    result = terminal_benchmark_missing_tool(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "benchmarks-missing-tool",
        prepare_command=prepare,
    )
    assert result == {"http_requests": 0, "completion": "tool_failed", "forward_started": False}
    assert len(prepared) == 2
