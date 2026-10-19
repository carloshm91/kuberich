"""Finished-pod cleanup selects exact, non-terminating candidates in one bounded batch."""

from kuberich.domain.cleanup import finished_pods
from tests.support.pods import pod, record


def finished(name, phase, *, reason=None, terminating=False, uid=None, namespace="team"):
    manifest = pod(name, uid=uid, namespace=namespace)
    manifest["status"]["phase"] = phase
    if reason is not None:
        manifest["status"]["reason"] = reason
    if terminating:
        manifest["metadata"]["deletionTimestamp"] = "2026-10-19T00:00:00Z"
    return record(manifest)


def test_completed_and_failed_pods_are_listed_with_their_state():
    records = [
        finished("running", "Running"),
        finished("pending", "Pending"),
        finished("done", "Succeeded"),
        finished("evicted", "Failed", reason="Evicted"),
        finished("crashed", "Failed"),
        finished("leaving", "Succeeded", terminating=True),
        finished("blank-reason", "Failed", reason=""),
    ]
    selection = finished_pods(records)
    assert [item.name for item in selection.candidates] == [
        "blank-reason",
        "crashed",
        "done",
        "evicted",
    ]
    states = {item.name: item.state for item in selection.candidates}
    assert states == {
        "blank-reason": "Failed",
        "crashed": "Failed",
        "done": "Completed",
        "evicted": "Failed (Evicted)",
    }
    assert selection.remaining == 0
    done = next(item for item in selection.candidates if item.name == "done")
    assert done.label == f"team/done · Completed · UID {done.uid}"


def test_malformed_or_unidentified_records_are_skipped():
    no_status = pod("no-status")
    no_status["status"] = "invalid"
    no_metadata = record(pod("no-metadata"))
    object.__setattr__(no_metadata, "uid", None)
    assert finished_pods([record(no_status), no_metadata]).candidates == ()


def test_more_than_one_batch_reports_the_remaining_count_deterministically():
    records = [finished(f"job-{i:03}", "Succeeded") for i in range(105)]
    selection = finished_pods(reversed(records))
    assert len(selection.candidates) == 100 and selection.remaining == 5
    assert selection.candidates[0].name == "job-000" and selection.candidates[-1].name == "job-099"
