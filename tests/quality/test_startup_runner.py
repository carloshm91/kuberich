"""Fresh-process instrumentation owns and reaps its direct child on timeout."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_startup
from scripts.startup_policy import Measurement


def test_actual_child_output_and_kernel_rss_are_retained_without_a_timing_claim(tmp_path):
    result = check_startup.run_plain(
        [sys.executable, "-c", "print('owned startup child')"], tmp_path, dict(os.environ), "owned"
    )
    assert result.exit_code == 0 and result.stdout == "owned startup child\n"
    assert result.stderr == "" and result.rss_bytes > 0 and result.elapsed_ns > 0
    assert (tmp_path / "owned.stdout").read_text() == result.stdout


def test_expired_owned_child_is_reaped_instead_of_becoming_a_background_process(
    tmp_path, monkeypatch
):
    created = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        created.append(process.pid)
        return process

    monkeypatch.setattr(check_startup.subprocess, "Popen", start)
    monkeypatch.setattr(check_startup, "TIMEOUT", 0.05)
    with pytest.raises(TimeoutError):
        check_startup.run_plain(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            dict(os.environ),
            "owned-timeout",
        )
    assert len(created) == 1
    with pytest.raises(ChildProcessError):
        os.waitpid(created[0], os.WNOHANG)


def test_failed_budget_keeps_the_original_failure_and_adds_a_diagnostic_profile(
    tmp_path, monkeypatch
):
    calls = []
    root = Path(__file__).resolve().parents[2]

    def run(argv, output, environment, name, *, cancellation=None):
        calls.append((argv, name))
        if name == "installed-source":
            return Measurement(0, 1, 1, str(root / "src/kuberich/__init__.py") + "\n", "")
        if "failure-importtime" in name:
            return Measurement(0, 200_000_000, 1, "kuberich 0.2.0\n", "owned diagnostic capture")
        return Measurement(0, 200_000_000, 1, "kuberich 0.2.0\n", "")

    monkeypatch.setattr(check_startup, "run_plain", run)
    result = {}
    with pytest.raises(ValueError, match="150 ms"):
        check_startup.qualify(tmp_path, 5, result)
    assert [name for _, name in calls] == [
        "installed-source",
        "version-0",
        "version-failure-importtime",
    ]
    assert "-X" in calls[-1][0] and "importtime" in calls[-1][0]
    assert result["failed_case_importtime"]["stderr"] == "owned diagnostic capture"
    assert result["offline"][0]["elapsed_ns"] == 200_000_000


def test_repeated_cancellation_during_process_creation_still_reaps_the_owned_child(
    tmp_path, monkeypatch
):
    created = []
    original = subprocess.Popen
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        created.append(process.pid)
        # Simulate cancellation in the Popen-return/assignment window. Repeated
        # delivery must not interrupt the cleanup of a process already created.
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGINT)
        return process

    monkeypatch.setattr(check_startup.subprocess, "Popen", start)
    with (
        check_startup.interruptible() as cancellation,
        pytest.raises(InterruptedError, match="signal 15"),
    ):
        check_startup.run_plain(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            dict(os.environ),
            "cancelled-owned",
            cancellation=cancellation,
        )
    assert len(created) == 1
    with pytest.raises(ChildProcessError):
        os.waitpid(created[0], os.WNOHANG)
    assert {number: signal.getsignal(number) for number in previous} == previous


def test_pending_cancellation_never_starts_another_owned_process(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("A cancelled qualification started another process.")

    monkeypatch.setattr(check_startup.subprocess, "Popen", unexpected)
    with pytest.raises(InterruptedError):
        check_startup.run_plain(
            [sys.executable, "-c", "pass"],
            tmp_path,
            dict(os.environ),
            "already-cancelled",
            cancellation=check_startup.Cancellation(signal.SIGTERM),
        )


def test_git_failure_is_reported_without_escaping_the_owned_failure_path(tmp_path, monkeypatch):
    output = tmp_path / "qualification"
    monkeypatch.setattr(sys, "argv", ["check_startup", "--output", str(output)])

    def run(argv, directory, environment, name, *, cancellation=None):
        assert name == "source-commit"
        raise OSError("controlled git failure")

    monkeypatch.setattr(check_startup, "run_plain", run)
    assert check_startup.main() == 1
    import json

    result = json.loads((output / "report.json").read_text())
    assert result["passed"] is False
    assert result["error"] == "controlled git failure"
    assert result["source_commit"] is None
