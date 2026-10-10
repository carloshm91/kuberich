"""Failure attribution cannot alter GC policy or leave a listener behind."""

import gc
from itertools import count

import pytest

from tests.support.backend_heartbeat import HeartbeatDiagnostic


@pytest.mark.parametrize("fails", [False, True])
def test_diagnostic_listener_drains_on_success_and_exception_without_gc_changes(fails):
    callbacks = list(gc.callbacks)
    policy = gc.isenabled(), gc.get_threshold()
    diagnostic = HeartbeatDiagnostic(lambda: float(next(clock)))
    clock = count()

    def exercise():
        with diagnostic:
            assert gc.callbacks == [*callbacks, diagnostic.listener]
            if fails:
                raise RuntimeError("owned injected failure")

    if fails:
        with pytest.raises(RuntimeError, match="owned injected failure"):
            exercise()
    else:
        exercise()
    assert list(gc.callbacks) == callbacks
    assert (gc.isenabled(), gc.get_threshold()) == policy
    report = diagnostic.report([0, 0.005, 0.205, 0.21], limit=0.15)
    assert report["runtime_qualified"] is False and report["diagnostic_only"] is True
    assert report["gc_listener_removed"] is True
    assert report["max_gap_seconds"] == pytest.approx(0.2)
    assert report["limit_seconds"] == 0.15


def test_generation_two_overlap_is_attributed_and_retained_evidence_is_bounded():
    times = iter([0.0, 0.001, 0.19, 0.3])
    diagnostic = HeartbeatDiagnostic(lambda: next(times))
    info = {"generation": 2, "collected": 7, "uncollectable": 0}
    with diagnostic:
        diagnostic._observe("start", info)
        diagnostic._observe("stop", info)
    report = diagnostic.report([0, 0.2, 0.21], limit=0.15)
    assert len(report["generation_two_events_overlapping_largest_gap"]) == 1
    event = report["generation_two_events"][0]
    assert event["duration_seconds"] == pytest.approx(0.189)
    assert event["collected"] == 7 and event["uncollectable"] == 0


def test_excess_diagnostics_remain_bounded_and_report_dropped_observations():
    diagnostic = HeartbeatDiagnostic(lambda: 0.0)
    info = {"generation": 2, "collected": 0, "uncollectable": 0}
    for _ in range(1000):
        diagnostic._observe("start", info)
        diagnostic._observe("stop", info)
    report = diagnostic.report([], limit=0.15)
    assert len(report["generation_two_events"]) == 64
    assert report["generation_two_events_dropped"] == 936
    assert not diagnostic.starts


def test_no_samples_do_not_invent_a_successful_measurement():
    diagnostic = HeartbeatDiagnostic(lambda: 0.0)
    report = diagnostic.report([], limit=0.15)
    assert report["max_gap_seconds"] is None and report["largest_gap"] is None
    assert report["samples"] == 0 and report["runtime_qualified"] is False
