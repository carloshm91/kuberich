"""Untraced, exclusively scheduled execution of the unchanged pacing contract."""

import asyncio
import gc
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path

from coverage import Coverage

ROOT = Path(__file__).resolve().parents[2]
DEADLINE = 15
OUTPUT_LIMIT = 256 * 1024
INPUTS = (
    "tests/contract/test_performance_workload.py",
    "tests/support/pacing_runtime.py",
    "tests/support/performance_workload.py",
    "tests/support/connections.py",
    "tests/support/pods.py",
    "tests/support/resources.py",
    "tests/support/watches.py",
    "tests/support/workspace.py",
    "pyproject.toml",
    "uv.lock",
)


def source_inputs():
    return {
        name: {
            "path": str((ROOT / name).resolve()),
            "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
        }
        for name in INPUTS
    }


def instrumentation():
    return {
        "coverage_active": Coverage.current() is not None,
        "trace_active": sys.gettrace() is not None,
        "profile_active": sys.getprofile() is not None,
    }


def verify_receipt(receipt, request, returncode):
    assert receipt["request"] == request, "Pacing child request binding changed"
    assert receipt["source_after"] == request["source"] == source_inputs()
    assert receipt["python"] == request["python"] == str(Path(sys.executable).resolve())
    assert not any(receipt["instrumentation"].values()), "Pacing child was instrumented"
    assert receipt["gc"]["before"] == receipt["gc"]["after"]
    assert receipt["gc"]["before"]["enabled"], "Pacing child disabled normal GC"
    assert receipt["cleanup"] == {
        "source_closed": True,
        "workers_done": True,
        "consumers_done": True,
        "fault_tasks_done": True,
        "active_watches": 0,
        "active_logs": 0,
    }, "Pacing child owners did not drain"
    source = receipt["source"]
    duration = source["paused_monotonic"] - source["started_monotonic"]
    resource_error = abs(source["resource_produced"] - 100 * duration)
    log_error = abs(source["log_produced"] - 2000 * duration)
    if request["mode"] == "positive":
        assert returncode == 0 and receipt["outcome"] == "passed"
        assert receipt["error"] is None and receipt["fault"] is None
        assert resource_error <= 3 and log_error <= 40
    else:
        assert request["mode"] == "late-stall"
        assert returncode == 1 and receipt["outcome"] == "failed"
        assert receipt["error"] == {"type": "AssertionError", "message": "resource-rate"}
        assert resource_error > 3, "Late-stall control did not fail the original rate bound"
        fault = receipt["fault"]
        assert source["started_monotonic"] < fault["entered"] < source["paused_monotonic"]
        assert source["paused_monotonic"] < fault["released"]
        assert fault["enabled_at_entry"] and fault["serial_before"] == fault["serial_after"]


async def require_pacing_child(directory, *, mode):
    from kuberich.domain.processes import ProcessStatus
    from tests.support.aggregate_runtime import command

    assert mode in {"positive", "late-stall"}
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    request_path = directory / "request.json"
    request = {
        "nonce": uuid.uuid4().hex,
        "mode": mode,
        "root": str(ROOT),
        "python": str(Path(sys.executable).resolve()),
        "source": source_inputs(),
    }
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    request_path.chmod(0o600)
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("COVERAGE_", "COV_CORE_"))
        and name not in {"PYTHONPATH", "PYTHONHOME"}
    }
    retained = ROOT / "artifacts/backend/pacing-runtime" / request["nonce"]
    try:
        result = await command(
            (sys.executable, "-m", "tests.support.pacing_runtime", str(request_path)),
            environment,
            deadline=DEADLINE,
        )
        for name, data in (("stdout.log", result.stdout), ("stderr.log", result.stderr)):
            path = directory / name
            path.write_bytes(data)
            path.chmod(0o600)
        assert result.status in {ProcessStatus.SUCCEEDED, ProcessStatus.FAILED}, (
            "Pacing child timeout/output/transport failure",
            result.status,
            retained,
        )
        path = directory / "receipt.json"
        assert path.stat().st_size <= OUTPUT_LIMIT
        receipt = json.loads(path.read_text())
        verify_receipt(receipt, request, result.returncode)
        return receipt
    finally:
        retained.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        retained.parent.chmod(0o700)
        retained.mkdir(mode=0o700, parents=True)
        for name in ("request.json", "receipt.json", "stdout.log", "stderr.log"):
            path = directory / name
            if path.is_file():
                shutil.copyfile(path, retained / name)
                (retained / name).chmod(0o600)
        print(f"Pacing evidence: {retained}")


async def run_child(request):
    from tests.contract.test_performance_workload import paced_stream_contract

    assert request["mode"] in {"positive", "late-stall"}
    assert request["root"] == str(ROOT) and request["source"] == source_inputs()
    assert request["python"] == str(Path(sys.executable).resolve())
    assert len(request["nonce"]) == 32
    assert not any(instrumentation().values()), "Pacing child was instrumented"
    gc_before = {"enabled": gc.isenabled(), "thresholds": list(gc.get_threshold())}
    observed, tasks = {}, []
    fault = None

    async def stall_source():
        nonlocal fault
        # A declared real publication stall, not a changed clock or fake event count.
        while "source" not in observed:
            await asyncio.sleep(0)
        source = observed["source"]
        await source.enabled.wait()
        await asyncio.sleep(0.8)
        async with source.changed:
            fault = {
                "entered": time.monotonic(),
                "enabled_at_entry": source.enabled.is_set(),
                "serial_before": source.serial,
            }
            await asyncio.sleep(0.4)
            fault.update(released=time.monotonic(), serial_after=source.serial)

    if request["mode"] == "late-stall":
        tasks.append(asyncio.create_task(stall_source()))
    error = None
    try:
        await paced_stream_contract(observed)
    except BaseException as failure:
        error = {"type": type(failure).__name__, "message": str(failure)}
        traceback.print_exc()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    source = observed["source"]
    return {
        "request": request,
        "source_after": source_inputs(),
        "python": str(Path(sys.executable).resolve()),
        "instrumentation": instrumentation(),
        "gc": {
            "before": gc_before,
            "after": {"enabled": gc.isenabled(), "thresholds": list(gc.get_threshold())},
        },
        "outcome": "passed" if error is None else "failed",
        "error": error,
        "source": source.receipt(),
        "fault": fault,
        "cleanup": {
            "source_closed": source.closed.is_set(),
            "workers_done": all(task.done() for task in source.workers),
            "consumers_done": all(task.done() for task in observed["consumers"]),
            "fault_tasks_done": all(task.done() for task in tasks),
            "active_watches": source.stats["active_watches"],
            "active_logs": source.stats["active_logs"],
        },
    }


def main():
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text())
    receipt = asyncio.run(run_child(request))
    path = request_path.parent / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    return 0 if receipt["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
