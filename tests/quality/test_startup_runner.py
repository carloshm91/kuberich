"""Fresh-process instrumentation owns and reaps its direct child on timeout."""

import json
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
        check_startup.qualify(tmp_path, 5, result, strict_startup=True)
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
    result = json.loads((output / "report.json").read_text())
    assert result["passed"] is False
    assert result["error"] == "controlled git failure"
    assert result["source_commit"] is None


@pytest.fixture
def startup_io(tmp_path, monkeypatch):
    source = tmp_path / "owned-source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n')
    monkeypatch.setattr(check_startup, "ROOT", source)
    state = {
        "terminal_calls": [],
        "unsafe_frame": False,
        "elapsed_ns": 1_000_000,
        "rss_bytes": 1_000_000,
        "profile": "import time: 1 | 1 | kuberich.cli\n",
        "invalid_output": False,
    }

    def run(argv, output, environment, name, *, cancellation=None):
        if name == "source-commit":
            return Measurement(0, 1, 1, "a" * 40 + "\n", "")
        if name == "installed-source":
            return Measurement(0, 1, 1, str(source / "src/kuberich/__init__.py") + "\n", "")
        if name.endswith("importtime") or name == "negative-textual-import":
            profile = state["profile"]
            if name == "negative-textual-import":
                profile = "import time: 1 | 1 | kuberich.cli\nimport time: 1 | 1 | textual\n"
            return Measurement(0, 1, 1, "", profile)
        version = check_startup.tomllib.loads((source / "pyproject.toml").read_text())["project"][
            "version"
        ]
        if name.startswith("version-"):
            text = f"kuberich {version}\n"
        elif name.startswith("help-"):
            text = "usage: kuberich --context --readonly\n"
        elif name.startswith("config-check-"):
            text = "KubeRich preferences are valid. No files were changed.\n"
        else:
            assert name.startswith("info-")
            text = json.dumps(
                {
                    "version": version,
                    "terminal_ui_available": True,
                    "cluster_connected": False,
                    "preferences": {"theme": "k9s"},
                    "dependencies": dict.fromkeys(
                        ("textual", "kubernetes-asyncio", "platformdirs", "pyyaml"), "owned"
                    ),
                }
            )
        return Measurement(
            0,
            state["elapsed_ns"],
            state["rss_bytes"],
            "{}" if state["invalid_output"] else text,
            "",
        )

    def terminal(output, environment, name, *, negative=False, cancellation=None):
        state["terminal_calls"].append((name, negative))
        return {
            "observation": {
                "painted": True,
                "first_paint_ns": 1_700_000_000,
                "exit": 0,
                "client_closed": True,
                "viewport": [120, 36],
                "shown_tables": ["resources"],
                "table_frames": {
                    "resources": {"mounted": True, "columns": 6, "region": [2, 11, 116, 2]}
                },
                "sdk_before_paint": ["kubernetes_asyncio"] if state["unsafe_frame"] else [],
                "sdk_models_at_exit": 0,
                "violations": [],
                "events": [{"kind": "paint", "painted": True}],
            },
            "launched_ns": 1_000_000_000,
            "visible_ns": 1_600_000_000,
        }

    monkeypatch.setattr(check_startup, "run_plain", run)
    monkeypatch.setattr(check_startup, "run_terminal", terminal)
    return state


def test_advisory_runner_keeps_all_five_ui_samples_and_both_strict_negative_controls(
    tmp_path, startup_io
):
    output = tmp_path / "advisory"
    output.mkdir()
    result = {}
    check_startup.qualify(output, 5, result)
    assert result["first_paint_budget_ns"] == 600_000_000
    assert result["first_paint_budget_met"] is False
    assert result["first_paint_budget_enforced"] is False
    assert len(result["first_paint"]) == 5
    assert all(
        paint["elapsed_ns"] == 700_000_000
        and paint["budget_met"] is False
        and paint["budget_enforced"] is False
        for paint in result["first_paint"]
    )
    assert startup_io["terminal_calls"] == [
        *((f"paint-{number}", False) for number in range(5)),
        ("negative-late-paint", True),
    ]
    assert result["negative_late_paint"]["rejected"] is True
    assert result["negative_import_rejected"] is True


@pytest.mark.parametrize("version,strict", [("0.3.0", True), ("1.0.0rc1", False), ("1.0.0", False)])
def test_strict_or_stable_runner_preserves_the_original_first_failure(
    tmp_path, startup_io, version, strict
):
    (check_startup.ROOT / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    output = tmp_path / "strict"
    output.mkdir()
    result = {}
    with pytest.raises(ValueError, match="600 ms"):
        check_startup.qualify(output, 5, result, strict_paint=strict)
    assert result["first_paint_budget_enforced"] is True
    assert result["first_paint_budget_met"] is False
    assert startup_io["terminal_calls"] == [("paint-0", False)]


def test_advisory_runner_still_rejects_prepaint_sdk_activity(tmp_path, startup_io):
    startup_io["unsafe_frame"] = True
    output = tmp_path / "unsafe"
    output.mkdir()
    with pytest.raises(ValueError, match="deferred-SDK"):
        check_startup.qualify(output, 5, {})


@pytest.mark.parametrize("strict,code", [(False, 0), (True, 1)])
def test_cli_reports_the_scope_without_labeling_a_missed_target_passed(
    tmp_path, monkeypatch, capsys, startup_io, strict, code
):
    output = tmp_path / "cli-policy"
    arguments = ["check_startup", "--output", str(output)]
    if strict:
        arguments.append("--strict-paint")
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(check_startup, "inputs", lambda: {"owned": "same-input"})
    assert check_startup.main() == code
    result = json.loads((output / "report.json").read_text())
    assert result["first_paint_budget_met"] is False
    assert result["first_paint_budget_enforced"] is strict
    assert result["passed"] is (not strict)
    assert "latency enforcement" in result["scope"] and "--strict-paint" in result["scope"]
    assert "--strict-startup" in result["scope"]
    captured = capsys.readouterr()
    if strict:
        assert "600 ms" in captured.err and captured.out == ""
    else:
        assert "600 ms UI target not met (advisory for 0.x)" in captured.out
        assert "UI target met" not in captured.out


def test_advisory_runner_records_every_slow_sample_and_profile_without_promoting_targets(
    tmp_path, startup_io
):
    startup_io["elapsed_ns"] = 161_144_125
    startup_io["rss_bytes"] = 27_738_112
    startup_io["profile"] = "import time: 150000 | 150000 | kuberich.cli\n"
    output = tmp_path / "all-advisory"
    output.mkdir()
    result = {}
    check_startup.qualify(output, 5, result)
    ordinary = [row for row in result["offline"] if "sample" in row]
    profiles = [row["importtime"] for row in result["offline"] if "importtime" in row]
    assert len(ordinary) == 20 and len(profiles) == 4 and len(result["first_paint"]) == 5
    assert all(
        row["elapsed_ns"] == 161_144_125
        and row["rss_bytes"] == 27_738_112
        and row["budget_ns"] == 150_000_000
        and row["budget_met"] is False
        and row["budget_enforced"] is False
        for row in ordinary
    )
    assert all(
        row["self_us"] == 150_000
        and row["max_cumulative_us"] == 150_000
        and row["budget_us"] == 150_000
        and row["budget_met"] is False
        and row["budget_enforced"] is False
        for row in profiles
    )
    assert result["source_version"] == "0.3.0"
    for target in ("offline", "import", "first_paint"):
        assert result[target + "_budget_met"] is False
        assert result[target + "_budget_enforced"] is False
    assert result["negative_late_paint"]["rejected"] is True
    assert result["negative_import_rejected"] is True


@pytest.mark.parametrize(
    "version,strict",
    [
        ("0.3.0", True),
        ("1.0.0.dev0", False),
        ("1.0.0rc1", False),
        ("1.0.0", False),
    ],
)
def test_strict_startup_or_stable_source_preserves_first_slow_offline_failure(
    tmp_path, startup_io, version, strict
):
    (check_startup.ROOT / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    startup_io["elapsed_ns"] = 161_144_125
    output = tmp_path / "strict-offline"
    output.mkdir()
    result = {}
    with pytest.raises(ValueError, match="150 ms"):
        check_startup.qualify(output, 5, result, strict_startup=strict)
    assert result["source_version"] == version
    assert result["offline_budget_enforced"] is True and result["offline_budget_met"] is False
    assert result["offline"][0]["elapsed_ns"] == 161_144_125
    assert len(result["offline"]) == 1 and startup_io["terminal_calls"] == []


def test_strict_import_failure_keeps_actual_profile_and_original_threshold(tmp_path, startup_io):
    startup_io["profile"] = "import time: 5 | 150000 | kuberich.cli\n"
    output = tmp_path / "strict-import"
    output.mkdir()
    result = {}
    with pytest.raises(ValueError, match="150 ms"):
        check_startup.qualify(output, 5, result, strict_startup=True)
    profile = result["offline"][-1]["importtime"]
    assert profile["self_us"] == 5 and profile["max_cumulative_us"] == 150_000
    assert profile["budget_met"] is False and profile["budget_enforced"] is True
    assert result["import_budget_met"] is False and startup_io["terminal_calls"] == []


def test_strict_paint_compatibility_does_not_silently_enable_other_pre_stable_clocks(
    tmp_path, startup_io
):
    startup_io["elapsed_ns"] = 200_000_000
    startup_io["profile"] = "import time: 150000 | 150000 | kuberich.cli\n"
    output = tmp_path / "paint-only"
    output.mkdir()
    result = {}
    with pytest.raises(ValueError, match="600 ms"):
        check_startup.qualify(output, 5, result, strict_paint=True)
    assert result["offline_budget_enforced"] is False
    assert result["import_budget_enforced"] is False
    assert result["first_paint_budget_enforced"] is True
    assert len(result["offline"]) == 24 and len(result["first_paint"]) == 1


@pytest.mark.parametrize(
    "change,error",
    [
        ({"rss_bytes": 40_000_000}, "RSS"),
        ({"invalid_output": True}, "installed CLI"),
        (
            {"profile": "import time: 1 | 1 | kuberich.cli\nimport time: 1 | 1 | textual\n"},
            "Textual",
        ),
    ],
)
def test_advisory_runner_still_rejects_memory_output_and_import_presence(
    tmp_path, startup_io, change, error
):
    startup_io.update(change)
    output = tmp_path / "hard-contract"
    output.mkdir()
    with pytest.raises(ValueError, match=error):
        check_startup.qualify(output, 5, {})
    assert startup_io["terminal_calls"] == []


@pytest.mark.parametrize("strict", [False, True])
def test_cli_strict_startup_and_report_keep_actual_unmet_offline_values(
    tmp_path, monkeypatch, capsys, startup_io, strict
):
    startup_io["elapsed_ns"] = 161_144_125
    startup_io["profile"] = "import time: 150000 | 150000 | kuberich.cli\n"
    output = tmp_path / "cli-all-latencies"
    argv = ["check_startup", "--output", str(output)]
    if strict:
        argv.append("--strict-startup")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(check_startup, "inputs", lambda: {"owned": "same-input"})
    assert check_startup.main() == int(strict)
    report = json.loads((output / "report.json").read_text())
    assert report["offline"][0]["elapsed_ns"] == 161_144_125
    assert report["offline_budget_met"] is False and report["offline_budget_enforced"] is strict
    assert report["passed"] is (not strict)
    captured = capsys.readouterr()
    if strict:
        assert "150 ms" in captured.err
    else:
        assert "offline latency target not met (advisory for 0.x)" in captured.out
        assert "import latency target not met (advisory for 0.x)" in captured.out
        assert len(report["offline"]) == 24 and len(report["first_paint"]) == 5
