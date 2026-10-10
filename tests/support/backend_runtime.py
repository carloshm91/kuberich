"""Owned normal-runtime controls for the exact covered tiny-line HTTP contract."""

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from coverage import Coverage
from coverage import __version__ as coverage_version

from kuberich.domain.processes import ProcessStatus
from tests.support.aggregate_runtime import ROOT, command, source_stamp

NODE = (
    "tests/contract/test_aggregate_logs.py::"
    "test_many_tiny_lines_slow_source_heartbeat_and_two_levels_of_retention"
)
MODE = "KUBERICH_TEST_BACKEND_RUNTIME"
REQUEST = "KUBERICH_TEST_BACKEND_REQUEST"
DEADLINE = 60
OUTPUT_LIMIT = 256 * 1024
DIRECTORY = ROOT / "artifacts/backend"


async def backend_source() -> dict[str, Any]:
    source = await source_stamp()
    for name in (
        "tests/contract/test_aggregate_logs.py",
        "tests/support/backend_runtime.py",
        "scripts/check_backend_runtime.py",
    ):
        source["files"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    return source


async def child_request() -> dict[str, Any]:
    mode = os.environ[MODE]
    assert mode in {"positive", "negative"}
    path = Path(os.environ[REQUEST]).resolve()
    assert path == (DIRECTORY / "runtime" / mode / "request.json").resolve()
    request: dict[str, Any] = json.loads(path.read_text())
    assert isinstance(request, dict)
    assert request["mode"] == mode and request["node"] == NODE
    assert request["directory"] == str(path.parent)
    assert request["source"] == await backend_source()
    return request


async def finish_child(request: dict[str, Any]) -> None:
    source = await backend_source()
    coverage = Coverage.current()
    modules = sorted(sys.modules)
    receipt = {
        "nonce": request["nonce"],
        "mode": request["mode"],
        "node": NODE,
        "source_before": request["source"],
        "source_after": source,
        "source_unchanged": source == request["source"],
        "module_inventory": modules,
        "instrumentation": {
            "coverage_version": coverage_version,
            "coverage_active": coverage is not None,
            "trace_type": type(sys.gettrace()).__name__ if sys.gettrace() is not None else None,
            "profile_type": type(sys.getprofile()).__name__
            if sys.getprofile() is not None
            else None,
        },
        "interpreter": sys.version,
        "pid": os.getpid(),
        "process_group": os.getpgrp(),
    }
    path = Path(request["directory"]) / "source-receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    assert source == request["source"]
    assert coverage is None and sys.gettrace() is None and sys.getprofile() is None
    assert not any(
        name == root or name.startswith(root + ".")
        for name in modules
        for root in ("rfc3987_syntax", "lark")
    ), "Development-only IRI grammar contaminated backend runtime measurement"


async def require_backend_children() -> None:
    source = await backend_source()
    receipts = {}
    for mode in ("positive", "negative"):
        directory = DIRECTORY / "runtime" / mode
        directory.mkdir(parents=True, exist_ok=True)
        for name in (
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
            "PYTEST_ADDOPTS": "",
        }
        result = await command(
            (
                sys.executable,
                "-m",
                "pytest",
                NODE,
                "-q",
                "--tb=short",
                "--no-cov",
                f"--junitxml={directory / 'cases.xml'}",
            ),
            environment,
            deadline=DEADLINE,
        )
        (directory / "stdout.log").write_bytes(result.stdout)
        (directory / "stderr.log").write_bytes(result.stderr)
        assert result.status in {ProcessStatus.SUCCEEDED, ProcessStatus.FAILED}, (
            mode,
            result.status,
            "Backend runtime timeout/output/transport failure",
        )
        assert source == await backend_source()
        receipts[mode] = {
            "nonce": request["nonce"],
            "returncode": result.returncode,
            "status": result.status.name,
            "deadline_seconds": DEADLINE,
            "output_limit_bytes": OUTPUT_LIMIT,
            "process_owner_drained": True,
            "artifacts": {
                file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                for file in directory.iterdir()
                if file.is_file()
            },
        }
    (DIRECTORY / "runtime-receipt.json").write_text(
        json.dumps({"source": source, "children": receipts}, indent=2) + "\n"
    )
    from scripts.check_backend_runtime import verify_backend_runtime

    verify_backend_runtime(DIRECTORY, source, require_parent_coverage=False)
