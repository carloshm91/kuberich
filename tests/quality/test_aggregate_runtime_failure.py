"""Preserve a failed child's actual cause before checking unfinished workload counters."""

import asyncio
import gc
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from kuberich.domain.processes import ProcessResult, ProcessStatus
from tests.support import aggregate_runtime


@pytest.fixture
def incomplete_child(monkeypatch, tmp_path):
    monkeypatch.setattr(aggregate_runtime, "ROOT", tmp_path)
    source = {"tested_checkout_commit": "owned-fixture", "files": {}}

    async def source_stamp():
        return source

    monkeypatch.setattr(aggregate_runtime, "source_stamp", source_stamp)

    def configure(
        status,
        returncode,
        *,
        failure,
        heartbeat_updates=None,
        receipt_updates=None,
        failure_message="Aggregate runtime heartbeat exceeded 150 ms",
    ):
        async def command(argv, environment):
            request = json.loads(Path(environment[aggregate_runtime.REQUEST]).read_text())
            directory = tmp_path / "artifacts/ui/aggregate-runtime/positive"
            receipt = {
                "nonce": request["nonce"],
                "mode": "positive",
                "source_before": source,
                "source_after": source,
                "source_unchanged": True,
                "development_iri_grammar_absent": True,
                "instrumentation": {
                    "coverage_version": aggregate_runtime.coverage_version,
                    "coverage_active": False,
                    "coverage_core": None,
                    "trace_type": None,
                    "profile_type": None,
                },
                "pid": 123,
                "process_group": 123,
                "after_app_close": {
                    "app_running": False,
                    "aggregate_registry": 0,
                    "api_log_streams": 0,
                    "api_watches": 0,
                },
            }
            heartbeat = {
                "gc_enabled": True,
                "limit_seconds": 0.15,
                "gc_thresholds": list(gc.get_threshold()),
                "timing_qualifying": True,
                "maximum_simultaneously_prepared_records": 5000,
                "maximum_retained_plus_prepared_records": 5000,
                "input_refill": {"byte_budget": 8192, "records": 0},
            }
            heartbeat.update(heartbeat_updates or {})
            receipt.update(receipt_updates or {})
            (directory / "source-receipt.json").write_text(json.dumps(receipt))
            (directory / "heartbeat.json").write_text(json.dumps(heartbeat))
            suite = ElementTree.Element("testsuite")
            case = ElementTree.SubElement(
                suite, "testcase", name=aggregate_runtime.NODE.split("::")[1]
            )
            if failure:
                ElementTree.SubElement(case, "failure", message=failure_message)
            ElementTree.ElementTree(suite).write(directory / "cases.xml")
            return ProcessResult(
                status,
                returncode,
                stdout=b"Aggregate runtime heartbeat exceeded 150 ms: 0.150267833",
            )

        monkeypatch.setattr(aggregate_runtime, "command", command)

    return configure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "returncode"),
    [(ProcessStatus.FAILED, 1), (ProcessStatus.SUCCEEDED, 0)],
)
async def test_failed_child_reports_its_original_cause_before_missing_refill(
    incomplete_child, status, returncode
):
    incomplete_child(status, returncode, failure=True)
    with pytest.raises(AssertionError, match="Aggregate runtime heartbeat exceeded 150 ms"):
        await aggregate_runtime.require_runtime_children()


@pytest.mark.asyncio
async def test_successful_child_still_requires_the_full_refill_workload(incomplete_child):
    incomplete_child(ProcessStatus.SUCCEEDED, 0, failure=False)
    with pytest.raises(AssertionError):
        await aggregate_runtime.require_runtime_children()


@pytest.mark.asyncio
@pytest.mark.parametrize("collection_error", [None, RuntimeError, asyncio.CancelledError])
async def test_verified_heartbeat_failure_remains_the_exact_original_after_diagnostics(
    incomplete_child, monkeypatch, tmp_path, collection_error
):
    incomplete_child(
        ProcessStatus.FAILED,
        1,
        failure=True,
        heartbeat_updates={"max_gap_seconds": 0.322, "negative_callback_executed": False},
    )
    monkeypatch.setenv(aggregate_runtime.DIAGNOSTIC, "on-failure")
    originals = []

    async def collect(request, environment):
        originals.append(sys.exception())
        assert request["mode"] == "positive"
        if collection_error is not None:
            raise collection_error("owned diagnostic collection failure")
        return tmp_path / "nonqualifying"

    monkeypatch.setattr(aggregate_runtime, "collect_diagnostic", collect)
    with pytest.raises(
        AssertionError, match="Aggregate runtime heartbeat exceeded 150 ms"
    ) as observed:
        await aggregate_runtime.require_runtime_children()
    assert originals == [observed.value]
    assert (
        observed.value.__traceback__.tb_next.tb_frame.f_code.co_name == "require_runtime_children"
    )
    assert any("Nonqualifying diagnostic" in note for note in observed.value.__notes__)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "disabled",
        "wrong-failure",
        "negative",
        "wrong-limit",
        "wrong-source",
        "successful-status",
        "under-limit",
    ],
)
async def test_unverified_or_unrelated_failure_never_starts_diagnostics(
    incomplete_child, monkeypatch, case
):
    updates = {"max_gap_seconds": 0.322, "negative_callback_executed": False}
    receipt = {}
    message = "Aggregate runtime heartbeat exceeded 150 ms"
    status, code = ProcessStatus.FAILED, 1
    if case == "negative":
        updates["negative_callback_executed"] = True
    elif case == "wrong-limit":
        updates["limit_seconds"] = 0.3
    elif case == "under-limit":
        updates["max_gap_seconds"] = 0.1
    elif case == "wrong-source":
        receipt["source_after"] = {"source": "different"}
    elif case == "wrong-failure":
        message = "owned unrelated behavioral failure"
    elif case == "successful-status":
        status, code = ProcessStatus.SUCCEEDED, 0
    incomplete_child(
        status,
        code,
        failure=True,
        heartbeat_updates=updates,
        receipt_updates=receipt,
        failure_message=message,
    )
    monkeypatch.setenv(
        aggregate_runtime.DIAGNOSTIC, "disabled" if case == "disabled" else "on-failure"
    )

    async def forbidden(*args):
        pytest.fail("Unverified failure must never collect a diagnostic child")

    monkeypatch.setattr(aggregate_runtime, "collect_diagnostic", forbidden)
    with pytest.raises(AssertionError):
        await aggregate_runtime.require_runtime_children()
