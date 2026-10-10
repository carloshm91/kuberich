"""Independently require normal backend timing controls and covered functional evidence."""

import gc
import hashlib
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from coverage import __version__ as coverage_version

from scripts.merge_runtime_coverage import document, measured_gap, require
from tests.support.backend_runtime import DEADLINE, NODE, OUTPUT_LIMIT

ARTIFACTS = {
    "cases.xml",
    "heartbeat.json",
    "source-receipt.json",
    "request.json",
    "stdout.log",
    "stderr.log",
}


def verify_backend_runtime(
    directory: Path, expected: dict[str, Any], *, require_parent_coverage: bool = True
) -> dict[str, Any]:
    outer = document(directory / "runtime-receipt.json")
    require(
        outer.get("source") == expected
        and isinstance(outer.get("children"), dict)
        and set(outer["children"]) == {"positive", "negative"},
        "Missing or stale backend runtime controls",
    )
    nonces = set()
    for mode in ("positive", "negative"):
        result = outer["children"][mode]
        require(isinstance(result, dict), "Backend child result must be an object")
        nonce = result.get("nonce")
        require(
            isinstance(nonce, str)
            and re.fullmatch("[0-9a-f]{32}", nonce) is not None
            and nonce not in nonces,
            "Backend runtime nonce must be valid and unique",
        )
        nonces.add(nonce)
        child = directory / "runtime" / mode
        require(
            isinstance(result.get("artifacts"), dict) and set(result["artifacts"]) == ARTIFACTS,
            "Incomplete backend runtime artifact inventory",
        )
        for name, checksum in result["artifacts"].items():
            require(
                hashlib.sha256((child / name).read_bytes()).hexdigest() == checksum,
                "Backend runtime artifact checksum mismatch",
            )
        receipt, request, heartbeat = (
            document(child / name)
            for name in ("source-receipt.json", "request.json", "heartbeat.json")
        )
        require(
            receipt.get("nonce") == request.get("nonce") == nonce
            and receipt.get("mode") == request.get("mode") == mode
            and receipt.get("node") == request.get("node") == NODE
            and request.get("source")
            == receipt.get("source_before")
            == receipt.get("source_after")
            == expected
            and receipt.get("source_unchanged") is True,
            "Backend runtime source/request identity mismatch",
        )
        modules = receipt.get("module_inventory")
        require(
            isinstance(modules, list)
            and all(isinstance(name, str) for name in modules)
            and not any(
                name == root or name.startswith(root + ".")
                for name in modules
                for root in ("rfc3987_syntax", "lark")
            )
            and receipt.get("instrumentation")
            == {
                "coverage_version": coverage_version,
                "coverage_active": False,
                "trace_type": None,
                "profile_type": None,
            },
            "Backend runtime must use ordinary imports and no coverage/trace/profile",
        )
        pid = receipt.get("pid")
        require(
            type(pid) is int
            and pid > 0
            and receipt.get("process_group") == pid
            and result.get("process_owner_drained") is True
            and result.get("deadline_seconds") == DEADLINE
            and result.get("output_limit_bytes") == OUTPUT_LIMIT,
            "Backend runtime process ownership/deadline/output contract mismatch",
        )
        verify_workload(heartbeat, expected)
        require(heartbeat.get("timing_qualifying") is True, "Backend runtime was not measured")
        gap = measured_gap(heartbeat.get("max_gap_seconds"))
        cases = ElementTree.parse(child / "cases.xml").getroot().findall(".//testcase")
        require(
            len(cases) == 1
            and cases[0].get("name") == NODE.split("::")[1]
            and not any(cases[0].find(name) is not None for name in ("error", "skipped")),
            "Backend runtime XML did not execute the required case",
        )
        failures = cases[0].findall("failure")
        if mode == "positive":
            require(
                result.get("returncode") == 0
                and result.get("status") == "SUCCEEDED"
                and not failures
                and heartbeat.get("negative_callback_executed") is False
                and gap < 0.15,
                "Backend runtime exceeded 150 ms or failed its functional workload",
            )
        else:
            require(
                result.get("returncode") == 1
                and result.get("status") == "FAILED"
                and len(failures) == 1
                and "Backend runtime heartbeat exceeded 150 ms" in failures[0].get("message", "")
                and heartbeat.get("negative_callback_executed") is True
                and gap >= 0.2,
                "Backend negative control did not fail specifically for a blocking heartbeat",
            )
    parent = document(directory / "aggregate-tiny-lines-heartbeat.json")
    verify_workload(parent, expected)
    require(parent.get("timing_qualifying") is False, "Covered backend timing cannot qualify")
    require(parent.get("negative_callback_executed") is False, "Covered workload was interrupted")
    if require_parent_coverage:
        instrumentation = parent.get("instrumentation", {})
        require(
            instrumentation.get("coverage_active") is True
            and instrumentation.get("coverage_core") in {"CTracer", "SysMonitor"},
            "Original backend functional workload must retain parent branch coverage",
        )
    return outer


def verify_workload(heartbeat: dict[str, Any], expected: dict[str, Any]) -> None:
    inputs = heartbeat.get("source_inputs")
    require(
        isinstance(inputs, dict)
        and set(name for name in inputs if name.startswith("src/kuberich/"))
        == set(
            name
            for name in expected["files"]
            if name.startswith("src/kuberich/") and name.endswith(".py")
        )
        and all(expected["files"].get(name) == checksum for name, checksum in inputs.items()),
        "Backend workload source inputs mismatch",
    )
    require(
        heartbeat.get("gc_before")
        == heartbeat.get("gc_after")
        == {"enabled": True, "thresholds": list(gc.get_threshold())}
        and heartbeat.get("gc_listener_removed") is True
        and heartbeat.get("limit_seconds") == 0.15
        and type(heartbeat.get("samples")) is int
        and heartbeat["samples"] > 3,
        "Backend workload lost normal GC or heartbeat sampling",
    )
    require(
        type(heartbeat.get("received_lines")) is int
        and 32770 <= heartbeat["received_lines"] <= 32771
        and heartbeat.get("slow_source_received") is True
        and type(heartbeat.get("retained_lines")) is int
        and 0 < heartbeat["retained_lines"] <= 600
        and type(heartbeat.get("retained_bytes")) is int
        and 0 < heartbeat["retained_bytes"] <= 262144
        and isinstance(heartbeat.get("per_source_lines"), list)
        and len(heartbeat["per_source_lines"]) == 2
        and all(type(n) is int and 0 < n <= 300 for n in heartbeat["per_source_lines"])
        and isinstance(heartbeat.get("per_source_bytes"), list)
        and len(heartbeat["per_source_bytes"]) == 2
        and all(type(n) is int and 0 < n <= 65536 for n in heartbeat["per_source_bytes"])
        and sum(heartbeat["per_source_lines"]) == heartbeat["retained_lines"]
        and sum(heartbeat["per_source_bytes"]) == heartbeat["retained_bytes"]
        and heartbeat.get("after_close")
        == {"owner_tasks": 0, "api_log_streams": 0, "api_watches": 0},
        "Backend workload/retention/final owner cleanup mismatch",
    )
