"""Preserve a failed child's actual cause before checking unfinished workload counters."""

import gc
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from kuberich.domain.processes import ProcessResult, ProcessStatus
from tests.support import aggregate_runtime
from tests.support.runtime_budget import VERSION


@pytest.fixture
def incomplete_child(monkeypatch, tmp_path):
    monkeypatch.setattr(aggregate_runtime, "ROOT", tmp_path)
    source = {"tested_checkout_commit": "owned-fixture", "files": {}}

    async def source_stamp():
        return source

    monkeypatch.setattr(aggregate_runtime, "source_stamp", source_stamp)

    def configure(status, returncode, *, failure):
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
                "max_gap_seconds": 0.05,
                "runtime_budget": {"version": VERSION, "enforced": True, "met": True},
                "maximum_simultaneously_prepared_records": 5000,
                "maximum_retained_plus_prepared_records": 5000,
                "input_refill": {"byte_budget": 8192, "records": 0},
            }
            (directory / "source-receipt.json").write_text(json.dumps(receipt))
            (directory / "heartbeat.json").write_text(json.dumps(heartbeat))
            suite = ElementTree.Element("testsuite")
            case = ElementTree.SubElement(
                suite, "testcase", name=aggregate_runtime.NODE.split("::")[1]
            )
            if failure:
                ElementTree.SubElement(
                    case, "failure", message="Aggregate runtime heartbeat exceeded 150 ms"
                )
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
