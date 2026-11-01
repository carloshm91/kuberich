"""Startup qualification rejects omitted evidence, heavyweight imports and late frames."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from scripts.startup_policy import (
    Measurement,
    check_cli,
    check_importtime,
    check_paint,
    enforce_paint_budget,
    enforce_startup_budget,
    observe_paint,
    rss_bytes,
)

PROFILE = (
    "import time: self [us] | cumulative | imported package\n"
    "import time:        10 |         10 |   owned_dependency\n"
    "import time:         5 |         15 | kuberich.cli\n"
)


def sample(case):
    information = {
        "version": "0.2.0",
        "terminal_ui_available": True,
        "cluster_connected": False,
        "preferences": {"theme": "k9s"},
        "dependencies": dict.fromkeys(
            ("textual", "kubernetes-asyncio", "platformdirs", "pyyaml"), "owned"
        ),
    }
    stdout = {
        "version": "kuberich 0.2.0\n",
        "help": "usage: kuberich --context --readonly",
        "info": json.dumps(information),
        "config-check": "KubeRich preferences are valid. No files were changed.\n",
    }[case]
    return Measurement(0, 50_000_000, 30_000_000, stdout, "")


def frame():
    return {
        "painted": True,
        "first_paint_ns": 300_000_000,
        "exit": 0,
        "client_closed": True,
        "viewport": [120, 36],
        "shown_tables": ["resources"],
        "table_frames": {"resources": {"mounted": True, "columns": 9, "region": [1, 9, 118, 23]}},
        "sdk_before_paint": [],
        "sdk_models_at_exit": 0,
        "violations": [],
        "events": [{"kind": "paint", "painted": True}],
    }


@pytest.mark.parametrize("case", ["version", "help", "info", "config-check"])
def test_each_required_offline_contract_has_its_own_valid_observation(case):
    check_cli(case, sample(case), "0.2.0")


@pytest.mark.parametrize(
    "change",
    [
        {"exit_code": 1},
        {"exit_code": False},
        {"elapsed_ns": 0},
        {"elapsed_ns": True},
        {"elapsed_ns": 150_000_000},
        {"rss_bytes": 0},
        {"rss_bytes": True},
        {"rss_bytes": 40_000_000},
        {"stderr": "unexpected warning"},
        {"stdout": ""},
    ],
)
def test_offline_failures_and_exact_budget_boundaries_cannot_pass(change):
    with pytest.raises(ValueError):
        check_cli("version", replace(sample("version"), **change), "0.2.0")


@pytest.mark.parametrize("case", ["help", "info", "config-check"])
def test_fast_empty_or_stub_output_does_not_qualify_an_offline_command(case):
    with pytest.raises(ValueError):
        check_cli(case, replace(sample(case), stdout="{}"), "0.2.0")


@pytest.mark.parametrize("stdout", ["[]", "null", '{"preferences": []}', "not JSON"])
def test_malformed_or_incomplete_info_cannot_replace_real_diagnostics(stdout):
    with pytest.raises(ValueError):
        check_cli("info", replace(sample("info"), stdout=stdout), "0.2.0")


def test_unknown_case_cannot_qualify_in_place_of_a_required_command():
    with pytest.raises(ValueError):
        check_cli("unknown", sample("version"), "0.2.0")


def test_linux_and_modern_darwin_peak_rss_use_their_actual_kernel_units():
    assert rss_bytes(1024, "linux") == 1_048_576
    assert rss_bytes(1_048_576, "darwin") == 1_048_576


@pytest.mark.parametrize(
    "value,system", [(0, "linux"), (-1, "darwin"), (True, "linux"), (100, "win32")]
)
def test_missing_or_unsupported_rss_observations_fail_closed(value, system):
    with pytest.raises(ValueError):
        rss_bytes(value, system)


def test_import_profile_aggregates_self_time_without_counting_nested_imports_twice():
    parsed = check_importtime(PROFILE)
    assert parsed["self_us"] == 15
    assert parsed["modules"][-1]["module"] == "kuberich.cli"


@pytest.mark.parametrize(
    "profile",
    [
        "",
        "unexpected diagnostic",
        "import time: incomplete",
        "import time: -1 | 1 | kuberich.cli",
        "import time: 20 | 10 | kuberich.cli",
        "import time: 0 | 0 | ",
        "import time: 1 | 1 | owned_only",
        "import time: 150000 | 150000 | kuberich.cli",
        "import time: 5 | 150000 | kuberich.cli",
        PROFILE + "import time: 1 | 1 | kuberich.cli\n",
        PROFILE + "import time: 1 | 1 | textual\n",
        PROFILE + "import time: 1 | 1 | textual.widgets\n",
        PROFILE + "import time: 1 | 1 | kubernetes_asyncio.client.models.v1_pod\n",
    ],
)
def test_incomplete_slow_or_forbidden_import_profiles_fail_closed(profile):
    with pytest.raises(ValueError):
        check_importtime(profile)


def test_first_paint_includes_both_actual_refresh_and_visible_pty_delivery():
    assert check_paint(frame(), 100_000_000, 400_000_000) == 300_000_000


@pytest.mark.parametrize(
    "version,strict,enforced",
    [
        ("0.3.0", False, False),
        ("0.9.0rc1", False, False),
        ("0.3.0", True, True),
        ("1.0.0.dev0", False, True),
        ("1.0.0rc1", False, True),
        ("1.0.0", False, True),
        ("2.0.0", False, True),
    ],
)
def test_only_pre_stable_ui_latency_is_advisory_unless_explicitly_strict(version, strict, enforced):
    assert enforce_paint_budget(version, strict=strict) is enforced
    assert enforce_startup_budget(version, strict=strict) is enforced


@pytest.mark.parametrize("strict", [False, True])
def test_invalid_version_cannot_select_an_advisory_mode(strict):
    with pytest.raises(ValueError):
        enforce_paint_budget("invalid-owned-version", strict=strict)
    with pytest.raises(ValueError):
        enforce_startup_budget("invalid-owned-version", strict=strict)


@pytest.mark.parametrize("case", ["version", "help", "info", "config-check"])
@pytest.mark.parametrize("elapsed", [150_000_000, 161_144_125, 300_000_000])
def test_only_valid_offline_latency_can_be_advisory_and_the_strict_limit_is_unchanged(
    case, elapsed
):
    measured = replace(sample(case), elapsed_ns=elapsed)
    check_cli(case, measured, "0.2.0", enforce_latency=False)
    with pytest.raises(ValueError, match="150 ms"):
        check_cli(case, measured, "0.2.0", enforce_latency=True)


@pytest.mark.parametrize(
    "change",
    [
        {"exit_code": 1},
        {"exit_code": False},
        {"stderr": "unexpected warning"},
        {"elapsed_ns": 0},
        {"elapsed_ns": True},
        {"elapsed_ns": -1},
        {"rss_bytes": 0},
        {"rss_bytes": True},
        {"rss_bytes": 40_000_000},
        {"stdout": "not the installed CLI"},
    ],
)
def test_advisory_clock_never_relaxes_memory_output_or_valid_measurements(change):
    with pytest.raises(ValueError):
        check_cli("version", replace(sample("version"), **change), "0.2.0", enforce_latency=False)


@pytest.mark.parametrize(
    "profile",
    [
        "import time: 150000 | 150000 | kuberich.cli\n",
        "import time: 5 | 150000 | kuberich.cli\n",
    ],
)
def test_advisory_import_reports_original_targets_and_strict_mode_rejects_them(profile):
    result = check_importtime(profile, enforce_latency=False)
    assert result["budget_met"] is False and result["budget_enforced"] is False
    assert result["budget_us"] == 150_000 and result["max_cumulative_us"] == 150_000
    with pytest.raises(ValueError, match="150 ms"):
        check_importtime(profile, enforce_latency=True)


@pytest.mark.parametrize(
    "profile",
    [
        "",
        "unexpected diagnostic",
        "import time: -1 | 1 | kuberich.cli",
        "import time: 20 | 10 | kuberich.cli",
        "import time: 1 | 1 | owned_only",
        PROFILE + "import time: 1 | 1 | kuberich.cli\n",
        PROFILE + "import time: 1 | 1 | textual.widgets\n",
        PROFILE + "import time: 1 | 1 | kubernetes_asyncio.client.models.v1_pod\n",
    ],
)
def test_advisory_import_clock_cannot_relax_presence_or_profile_validity(profile):
    with pytest.raises(ValueError):
        check_importtime(profile, enforce_latency=False)


def test_observation_records_slow_real_frame_while_strict_check_still_rejects_600ms():
    observed = {**frame(), "first_paint_ns": 800_000_000}
    assert observe_paint(observed, 100_000_000, 700_000_000) == 700_000_000
    with pytest.raises(ValueError, match="600 ms"):
        check_paint(observed, 100_000_000, 700_000_000)


@pytest.mark.parametrize(
    "change",
    [
        {"sdk_before_paint": ["kubernetes_asyncio"]},
        {"sdk_models_at_exit": 1},
        {"client_closed": False},
        {"exit": 1},
        {"viewport": [40, 12]},
        {"shown_tables": []},
        {"violations": ["unowned-network"]},
        {"table_frames": {}},
        {"first_paint_ns": None},
    ],
)
def test_advisory_latency_cannot_relax_actual_frame_or_ownership_contracts(change):
    with pytest.raises(ValueError):
        observe_paint({**frame(), **change}, 100_000_000, 700_000_000)


@pytest.mark.parametrize(
    "change",
    [
        {"painted": False},
        {"first_paint_ns": None},
        {"first_paint_ns": True},
        {"first_paint_ns": 100_000_000},
        {"shown_tables": []},
        {"shown_tables": ["contexts"]},
        {"shown_tables": "resources"},
        {"table_frames": None},
        {"table_frames": {}},
        {"table_frames": {"resources": None}},
        {"first_paint_ns": 700_000_000},
        {"exit": 1},
        {"client_closed": False},
        {"viewport": [1, 1]},
        {"sdk_before_paint": ["kubernetes_asyncio"]},
        {"sdk_models_at_exit": 1},
        {"violations": ["network"]},
        {"events": []},
    ],
)
def test_missing_late_headless_or_unsafe_frame_evidence_is_rejected(change):
    with pytest.raises(ValueError):
        check_paint({**frame(), **change}, 100_000_000, 400_000_000)


@pytest.mark.parametrize(
    "change",
    [
        {"mounted": False},
        {"columns": 0},
        {"columns": True},
        {"region": None},
        {"region": [1, 2, 3]},
        {"region": [1, 2, True, 4]},
        {"region": [-1, 2, 3, 4]},
        {"region": [1, -1, 3, 4]},
        {"region": [1, 2, 0, 4]},
        {"region": [1, 2, 3, 0]},
        {"region": [1, 2, 120, 4]},
        {"region": [1, 2, 3, 36]},
    ],
)
def test_unmounted_or_incomplete_selected_resource_table_is_rejected(change):
    observation = frame()
    observation["table_frames"]["resources"].update(change)
    with pytest.raises(ValueError):
        check_paint(observation, 100_000_000, 400_000_000)


@pytest.mark.parametrize("visible", [None, True, 0, 99_999_999, 100_000_000, 700_000_000])
def test_a_callback_without_timely_real_terminal_delivery_does_not_pass(visible):
    with pytest.raises(ValueError):
        check_paint(frame(), 100_000_000, visible)


def test_required_platform_job_runs_the_serial_gate_and_retains_failed_observations():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())
    application = workflow["jobs"]["application"]
    steps = application["steps"]
    startup = [step for step in steps if "python -m scripts.check_startup" in step.get("run", "")]
    assert len(startup) == 1
    assert startup[0]["run"] == (
        "uv run python -m scripts.check_startup --output artifacts/startup/qualification"
    )
    assert "if" not in startup[0] and not startup[0].get("continue-on-error")
    assert not application.get("continue-on-error")
    assert any(
        "mypy --strict scripts/check_startup.py scripts/startup_policy.py scripts/startup_probe.py"
        in step.get("run", "")
        for step in steps
    )
    evidence = [
        step for step in steps if "artifacts/startup/**" in step.get("with", {}).get("path", "")
    ]
    assert len(evidence) == 1 and "always()" in str(evidence[0]["if"])


@pytest.mark.parametrize("launched", [None, True, 0, -1, 300_000_000])
def test_frame_timestamps_must_both_follow_a_real_positive_launch(launched):
    with pytest.raises(ValueError):
        check_paint(frame(), launched, 400_000_000)
