"""Latency policy never downgrades stable gates or the real strict negative control."""

import pytest

from tests.support import runtime_budget as budget


@pytest.mark.parametrize("version", ["0.0.1", "0.2.0", "0.3.0rc1"])
def test_zero_major_observations_are_advisory_with_explicit_strict_opt_in(version):
    assert not budget.enforce_budget(version)
    assert budget.enforce_budget(version, strict=True)


@pytest.mark.parametrize("version", ["1.0.0a1", "1.0.0", "2.0.0.dev1"])
def test_stable_qualification_cannot_downgrade_with_an_explicit_zero_opt_in(monkeypatch, version):
    monkeypatch.setattr(budget, "VERSION", version)
    monkeypatch.setenv(budget.STRICT, "0")
    assert budget.budget_enforced("positive")
    assert budget.budget_enforced("negative")
    assert not budget.budget_enforced("coverage")
    with pytest.raises(ValueError):
        budget.verify_budget(
            {"version": version, "enforced": False, "met": False}, 0.162447845, mode="positive"
        )


@pytest.mark.parametrize("mode", ["positive", "negative", "coverage"])
@pytest.mark.parametrize("value", ["", "true", "report-only", "2"])
def test_invalid_opt_in_is_refused_instead_of_silently_disabling_enforcement(
    monkeypatch, mode, value
):
    monkeypatch.setenv(budget.STRICT, value)
    with pytest.raises(ValueError, match="must be 0 or 1"):
        budget.budget_enforced(mode)


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="Unknown"):
        budget.budget_enforced("omitted")


def test_exact_boundary_is_reported_unmet_but_not_a_strict_pass(monkeypatch):
    monkeypatch.setattr(budget, "VERSION", "0.3.0")
    monkeypatch.delenv(budget.STRICT, raising=False)
    observation = budget.budget_observation(0.15, mode="positive")
    assert observation == {"version": "0.3.0", "enforced": False, "met": False}
    budget.verify_budget(observation, 0.15, mode="positive")
    monkeypatch.setenv(budget.STRICT, "1")
    with pytest.raises(ValueError):
        budget.verify_budget(observation, 0.15, mode="positive")
    observation = budget.budget_observation(0.15, mode="positive")
    assert observation["enforced"] and not observation["met"]
    with pytest.raises(ValueError):
        budget.verify_budget(observation, 0.15, mode="positive")


def test_advisory_verifier_can_accept_stricter_successful_receipt(monkeypatch):
    monkeypatch.setattr(budget, "VERSION", "0.3.0")
    monkeypatch.setenv(budget.STRICT, "0")
    budget.verify_budget(
        {"version": "0.3.0", "enforced": True, "met": True}, 0.149, mode="positive"
    )


def test_covered_replay_and_deliberate_negative_have_distinct_semantics(monkeypatch):
    monkeypatch.setattr(budget, "VERSION", "0.3.0")
    monkeypatch.setenv(budget.STRICT, "0")
    for mode, enforced in (("coverage", False), ("negative", True)):
        observation = budget.budget_observation(0.21, mode=mode)
        assert observation == {"version": "0.3.0", "enforced": enforced, "met": False}
        budget.verify_budget(observation, 0.21, mode=mode)
        observation["enforced"] = not enforced
        with pytest.raises(ValueError):
            budget.verify_budget(observation, 0.21, mode=mode)


@pytest.mark.parametrize(
    "change",
    [
        {"version": "0.1.0"},
        {"enforced": 0},
        {"enforced": "false"},
        {"met": 1},
        {"met": False},
        {"extra": True},
    ],
)
def test_malformed_or_falsely_met_receipts_fail_closed(monkeypatch, change):
    monkeypatch.setenv(budget.STRICT, "0")
    observation = budget.budget_observation(0.1, mode="positive") | change
    with pytest.raises(ValueError):
        budget.verify_budget(observation, 0.1, mode="positive")


@pytest.mark.parametrize("observation", [None, [], {}, "report-only"])
def test_missing_policy_is_not_advisory_evidence(observation):
    with pytest.raises(ValueError):
        budget.verify_budget(observation, 0.1, mode="positive")


@pytest.mark.parametrize("gap", [None, True, 0, -1, float("nan"), float("inf")])
def test_missing_or_invalid_samples_remain_visible_but_never_validate(monkeypatch, gap):
    monkeypatch.setenv(budget.STRICT, "0")
    observation = budget.budget_observation(gap, mode="positive")
    assert not observation["met"]
    with pytest.raises(ValueError):
        budget.verify_budget(observation, gap, mode="positive")
