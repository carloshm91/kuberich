"""Owned fresh-process runtime checks, independent of collected dev-tool roots."""

import gc
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from coverage import Coverage
from coverage import __version__ as coverage_version

from kuberich.domain.processes import (
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
)
from kuberich.services.access import AccessPolicy
from kuberich.services.processes import ProcessRunner

ROOT = Path(__file__).resolve().parents[2]
NODE = (
    "tests/ui/test_aggregate_logs.py::"
    "test_full_retained_history_format_heartbeat_clipboard_bound_save_failure_and_previous"
)
MODE = "KUBERICH_TEST_AGGREGATE_RUNTIME"
REQUEST = "KUBERICH_TEST_AGGREGATE_REQUEST"
DEADLINE = 120
OUTPUT_LIMIT = 256 * 1024


async def command(
    argv: Sequence[str], environment: Mapping[str, str] | None = None, *, deadline: float = DEADLINE
) -> ProcessResult:
    async with ProcessRunner(AccessPolicy(False), output_limit=OUTPUT_LIMIT) as runner:
        result = await runner.capture(
            capture_command(
                argv,
                environment=os.environ if environment is None else environment,
                directory=ROOT,
                mode=ProcessMode.CAPTURE,
                purpose=ProcessPurpose.PLUGIN,
            ),
            timeout=deadline,
        )
    assert runner.active_count == 0 and runner._closed, "Runtime process owner did not drain"
    return result


async def source_stamp() -> dict[str, Any]:
    head = await command(("git", "rev-parse", "HEAD", "HEAD^{tree}"), deadline=5)
    tracked = await command(
        (
            "git",
            "ls-files",
            "src/kuberich",
            "tests/support",
            "tests/conftest.py",
            "pyproject.toml",
            "uv.lock",
        ),
        deadline=5,
    )
    assert head.status is tracked.status is ProcessStatus.SUCCEEDED
    commit, tree = head.stdout.decode().splitlines()
    paths = tuple(
        dict.fromkeys(
            [
                *tracked.stdout.decode().splitlines(),
                "tests/support/aggregate_runtime.py",
                "tests/ui/test_aggregate_logs.py",
                "tests/ui/test_logs.py",
                "scripts/merge_runtime_coverage.py",
            ]
        )
    )
    return {
        "tested_checkout_commit": commit,
        "tested_checkout_tree": tree,
        "files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths},
    }


async def child_request() -> dict[str, Any]:
    mode = os.environ[MODE]
    assert mode in {"positive", "negative", "coverage"}, "Unexpected runtime child mode"
    request_path = Path(os.environ[REQUEST]).resolve()
    expected_directory = (ROOT / "artifacts/ui/aggregate-runtime" / mode).resolve()
    assert request_path.name == "request.json" and request_path.parent == expected_directory
    request = json.loads(request_path.read_text())
    assert isinstance(request, dict), "Runtime request must be an object"
    assert request["mode"] == mode and request["node"] == NODE
    assert request["source"] == await source_stamp(), (
        "Runtime child source changed before execution"
    )
    assert request["directory"] == str(request_path.parent)
    return request


async def finish_child(request: dict[str, Any]) -> None:
    source = await source_stamp()
    directory = Path(request["directory"])
    app, api = request.pop("_runtime_app", None), request.pop("_runtime_api", None)
    cleanup = (
        {
            "app_running": app.is_running,
            "aggregate_registry": len(app._aggregate_screens),
            "api_log_streams": api.active,
            "api_watches": api.watch_active,
        }
        if app is not None and api is not None
        else None
    )
    modules = sorted(sys.modules)
    grammar_absent = not any(
        name == root or name.startswith(root + ".")
        for name in modules
        for root in ("rfc3987_syntax", "lark")
    )
    coverage = Coverage.current()
    instrumentation = {
        "coverage_version": coverage_version,
        "coverage_active": coverage is not None,
        "coverage_core": dict(coverage.sys_info())["core"] if coverage is not None else None,
        "trace_type": (
            f"{type(sys.gettrace()).__module__}.{type(sys.gettrace()).__qualname__}"
            if sys.gettrace() is not None
            else None
        ),
        "profile_type": (
            f"{type(sys.getprofile()).__module__}.{type(sys.getprofile()).__qualname__}"
            if sys.getprofile() is not None
            else None
        ),
    }
    receipt = {
        "nonce": request["nonce"],
        "mode": request["mode"],
        "node": NODE,
        "source_before": request["source"],
        "source_after": source,
        "source_unchanged": source == request["source"],
        "module_inventory": modules,
        "development_iri_grammar_absent": grammar_absent,
        "interpreter": sys.version,
        "instrumentation": instrumentation,
        "pid": os.getpid(),
        "process_group": os.getpgrp(),
        "after_app_close": cleanup,
    }
    (directory / "source-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    assert source == request["source"], "Runtime child source changed during execution"
    assert grammar_absent, "Development-only IRI parser contaminated runtime measurement"
    assert cleanup is not None and not cleanup["app_running"]
    assert all(
        cleanup[key] == 0 for key in ("aggregate_registry", "api_log_streams", "api_watches")
    )


async def require_runtime_children() -> None:
    source = await source_stamp()
    receipts = {}
    for mode in ("positive", "negative", "coverage"):
        directory = ROOT / "artifacts/ui/aggregate-runtime" / mode
        directory.mkdir(parents=True, exist_ok=True)
        # Remove only this owner's fixed outputs; nonce and source checks also
        # reject surviving receipts from an earlier invocation.
        for name in (
            "coverage.data",
            "coverage.json",
            "coverage.xml",
            "cases.xml",
            "heartbeat.json",
            "source-receipt.json",
            "stdout.log",
            "stderr.log",
        ):
            (directory / name).unlink(missing_ok=True)
        request = {
            "nonce": uuid.uuid4().hex,
            "mode": mode,
            "node": NODE,
            "source": source,
            "directory": str(directory),
        }
        request_path = directory / "request.json"
        request_path.write_text(json.dumps(request, indent=2) + "\n")
        environment = {
            **{
                name: value
                for name, value in os.environ.items()
                if name not in {"COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG"}
                and not name.startswith("COV_CORE_")
            },
            MODE: mode,
            REQUEST: str(request_path),
            "COVERAGE_FILE": str(directory / "coverage.data"),
            "PYTEST_ADDOPTS": "",
        }
        coverage_arguments = (
            (
                "--cov=kuberich",
                "--cov-branch",
                "--cov-report=term",
                f"--cov-report=json:{directory / 'coverage.json'}",
                f"--cov-report=xml:{directory / 'coverage.xml'}",
            )
            if mode == "coverage"
            else ()
        )
        result = await command(
            (
                sys.executable,
                "-m",
                "pytest",
                NODE,
                "-q",
                "--tb=short",
                *coverage_arguments,
                f"--junitxml={directory / 'cases.xml'}",
            ),
            environment,
        )
        (directory / "stdout.log").write_bytes(result.stdout)
        (directory / "stderr.log").write_bytes(result.stderr)
        assert result.status in {ProcessStatus.SUCCEEDED, ProcessStatus.FAILED}, (
            mode,
            result.status,
            "Runtime child timeout/output/transport failure",
        )
        assert source == await source_stamp(), "Parent source changed during runtime child"
        receipt = json.loads((directory / "source-receipt.json").read_text())
        heartbeat = json.loads((directory / "heartbeat.json").read_text())
        assert receipt["nonce"] == request["nonce"] and receipt["mode"] == mode
        assert receipt["source_before"] == receipt["source_after"] == source
        assert receipt["source_unchanged"] and receipt["development_iri_grammar_absent"]
        instrumentation = receipt["instrumentation"]
        assert instrumentation["coverage_version"] == coverage_version
        assert instrumentation["profile_type"] is None
        if mode == "coverage":
            assert instrumentation["coverage_active"] is True
            assert instrumentation["coverage_core"] in {"CTracer", "SysMonitor"}
        else:
            assert instrumentation == {
                "coverage_version": coverage_version,
                "coverage_active": False,
                "coverage_core": None,
                "trace_type": None,
                "profile_type": None,
            }
        assert receipt["pid"] == receipt["process_group"]
        assert receipt["after_app_close"] == {
            "app_running": False,
            "aggregate_registry": 0,
            "api_log_streams": 0,
            "api_watches": 0,
        }
        assert heartbeat["gc_enabled"] and heartbeat["limit_seconds"] == 0.15
        assert heartbeat["gc_thresholds"] == list(gc.get_threshold())
        assert heartbeat["timing_qualifying"] is (mode != "coverage")
        assert heartbeat["maximum_simultaneously_prepared_records"] == 5000
        assert heartbeat["maximum_retained_plus_prepared_records"] <= 5001
        refill = heartbeat["input_refill"]
        if mode != "negative":
            assert refill["byte_budget"] == 8192 and refill["records"] == 5000
            assert refill["batches"] > 1 and refill["maximum_batch_records"] < 500
            assert 0 < refill["maximum_batch_bytes"] <= refill["byte_budget"]
        cases = ElementTree.parse(directory / "cases.xml").getroot().findall(".//testcase")
        assert len(cases) == 1 and cases[0].attrib["name"] == NODE.split("::")[1]
        assert cases[0].find("error") is None and cases[0].find("skipped") is None
        failures = cases[0].findall("failure")
        if mode != "negative":
            assert (
                result.status is ProcessStatus.SUCCEEDED and result.returncode == 0 and not failures
            ), result.stdout.decode()
            assert not heartbeat["negative_callback_executed"]
            if mode == "positive":
                assert heartbeat["max_gap_seconds"] < 0.15
            assert heartbeat["completed_full_history_rounds"] == 2
            assert heartbeat["warm_sizes"] == [[40, 12], [100, 30]]
            assert heartbeat["warm_resources"] == ["replicasets", "pods"]
            assert heartbeat["warm_reopens"] == 4 and heartbeat["warm_picker_cycles"] == 4
            assert heartbeat["warm_theme_changes"] == 4
            closed = heartbeat["after_close"]
            assert closed["viewer_closed"] and closed["owner_closed"]
            assert all(
                closed[key] == 0
                for key in ("owner_tasks", "active_readers", "registry_size", "api_log_streams")
            )
            assert closed["api_watches"] == closed["background_watches"] == 1
            if mode == "positive":
                # Keep the runtime performance receipt; tracing is separate.
                (ROOT / "artifacts/ui/aggregate-heartbeat.json").write_text(
                    json.dumps(heartbeat, indent=2) + "\n"
                )
        else:
            assert result.status is ProcessStatus.FAILED and result.returncode == 1
            assert len(failures) == 1
            assert "Aggregate runtime heartbeat exceeded 150 ms" in failures[0].attrib["message"]
            assert heartbeat["negative_callback_executed"]
            assert heartbeat["max_gap_seconds"] >= 0.2
        receipts[mode] = {
            "nonce": request["nonce"],
            "returncode": result.returncode,
            "status": result.status.name,
            "deadline_seconds": DEADLINE,
            "output_limit_bytes": OUTPUT_LIMIT,
            "process_owner_drained": True,
            "max_gap_seconds": heartbeat["max_gap_seconds"],
            "artifacts": {
                file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                for file in directory.iterdir()
                if file.is_file()
            },
        }
    (ROOT / "artifacts/ui/aggregate-runtime-receipt.json").write_text(
        json.dumps({"source": source, "children": receipts}, indent=2) + "\n"
    )
