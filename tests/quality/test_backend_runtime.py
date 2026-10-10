"""Reject stale, incomplete or misleading runtime controls before the quality gate."""

import copy
import gc
import hashlib
import json
from xml.etree import ElementTree

import pytest

from scripts import check_backend_runtime as verifier
from scripts import merge_runtime_coverage
from tests.support import backend_runtime
from tests.support.aggregate_runtime import ROOT


def write(path, value):
    path.write_text(json.dumps(value) + "\n")


@pytest.fixture
def backend_bundle(tmp_path):
    files = {
        path.relative_to(ROOT).as_posix(): "fixture"
        for path in (ROOT / "src/kuberich").rglob("*.py")
    }
    expected = {"files": files, "tested_checkout_commit": "fixture"}
    directory = tmp_path / "artifacts/backend"
    directory.mkdir(parents=True)
    outer = {"source": expected, "children": {}}
    functional = {
        "source_inputs": files,
        "gc_before": {"enabled": True, "thresholds": list(gc.get_threshold())},
        "gc_after": {"enabled": True, "thresholds": list(gc.get_threshold())},
        "gc_listener_removed": True,
        "limit_seconds": 0.15,
        "samples": 150,
        "received_lines": 32771,
        "slow_source_received": True,
        "retained_lines": 302,
        "retained_bytes": 41116,
        "per_source_lines": [300, 2],
        "per_source_bytes": [40800, 316],
        "after_close": {"owner_tasks": 0, "api_log_streams": 0, "api_watches": 0},
    }
    for mode in ("positive", "negative"):
        child = directory / "runtime" / mode
        child.mkdir(parents=True)
        nonce = ("a" if mode == "positive" else "b") * 32
        request = {"nonce": nonce, "mode": mode, "node": verifier.NODE, "source": expected}
        write(child / "request.json", request)
        write(
            child / "source-receipt.json",
            {
                "nonce": nonce,
                "mode": mode,
                "node": verifier.NODE,
                "source_before": expected,
                "source_after": expected,
                "source_unchanged": True,
                "module_inventory": ["asyncio", "kuberich"],
                "pid": 123,
                "process_group": 123,
                "instrumentation": {
                    "coverage_version": verifier.coverage_version,
                    "coverage_active": False,
                    "trace_type": None,
                    "profile_type": None,
                },
            },
        )
        write(
            child / "heartbeat.json",
            {
                **functional,
                "timing_qualifying": True,
                "negative_callback_executed": mode == "negative",
                "max_gap_seconds": 0.02 if mode == "positive" else 0.21,
            },
        )
        suite = ElementTree.Element("testsuite")
        case = ElementTree.SubElement(suite, "testcase", name=verifier.NODE.split("::")[1])
        if mode == "negative":
            ElementTree.SubElement(
                case, "failure", message="Backend runtime heartbeat exceeded 150 ms"
            )
        ElementTree.ElementTree(suite).write(child / "cases.xml")
        (child / "stdout.log").write_text(mode)
        (child / "stderr.log").write_text("")
        outer["children"][mode] = {
            "nonce": nonce,
            "returncode": 0 if mode == "positive" else 1,
            "status": "SUCCEEDED" if mode == "positive" else "FAILED",
            "process_owner_drained": True,
            "deadline_seconds": verifier.DEADLINE,
            "output_limit_bytes": verifier.OUTPUT_LIMIT,
            "artifacts": {
                name: hashlib.sha256((child / name).read_bytes()).hexdigest()
                for name in verifier.ARTIFACTS
            },
        }
    write(directory / "runtime-receipt.json", outer)
    write(
        directory / "aggregate-tiny-lines-heartbeat.json",
        {
            **functional,
            "timing_qualifying": False,
            "negative_callback_executed": False,
            "max_gap_seconds": 0.7,
            "instrumentation": {"coverage_active": True, "coverage_core": "CTracer"},
        },
    )
    return directory, expected, outer


def change(bundle, mode, name, field, value):
    directory, _, outer = bundle
    path = directory / "runtime" / mode / name
    content = json.loads(path.read_text())
    content[field] = value
    write(path, content)
    outer["children"][mode]["artifacts"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(directory / "runtime-receipt.json", outer)


def test_normal_controls_qualify_timing_while_original_covered_workload_remains_required(
    backend_bundle,
):
    directory, expected, outer = backend_bundle
    assert verifier.verify_backend_runtime(directory, expected) == outer
    path = directory / "aggregate-tiny-lines-heartbeat.json"
    parent = json.loads(path.read_text())
    parent["instrumentation"] = {"coverage_active": False}
    write(path, parent)
    with pytest.raises(ValueError, match="parent branch coverage"):
        verifier.verify_backend_runtime(directory, expected)
    assert (
        verifier.verify_backend_runtime(directory, expected, require_parent_coverage=False) == outer
    )


@pytest.mark.parametrize(
    "mode,name,field,value",
    [
        ("positive", "heartbeat.json", "max_gap_seconds", 0.15),
        ("positive", "heartbeat.json", "max_gap_seconds", True),
        ("positive", "heartbeat.json", "max_gap_seconds", float("nan")),
        ("positive", "heartbeat.json", "samples", 3),
        ("positive", "heartbeat.json", "received_lines", 32769),
        ("positive", "heartbeat.json", "slow_source_received", False),
        ("positive", "heartbeat.json", "retained_lines", 601),
        ("positive", "heartbeat.json", "retained_bytes", 262145),
        ("positive", "heartbeat.json", "per_source_lines", [301, 1]),
        ("positive", "heartbeat.json", "per_source_bytes", [41115, 2]),
        ("positive", "heartbeat.json", "after_close", {"owner_tasks": 1}),
        ("positive", "heartbeat.json", "gc_after", {"enabled": False, "thresholds": [700, 10, 10]}),
        ("positive", "heartbeat.json", "source_inputs", {}),
        ("positive", "heartbeat.json", "timing_qualifying", False),
        ("positive", "source-receipt.json", "source_after", {}),
        ("positive", "source-receipt.json", "module_inventory", ["lark.parser"]),
        ("positive", "source-receipt.json", "module_inventory", ["rfc3987_syntax"]),
        ("positive", "source-receipt.json", "module_inventory", [123]),
        ("positive", "source-receipt.json", "process_group", 456),
        ("positive", "source-receipt.json", "pid", True),
        ("negative", "heartbeat.json", "max_gap_seconds", 0.199),
        ("negative", "heartbeat.json", "negative_callback_executed", False),
    ],
)
def test_controls_reject_rehashed_false_measurement_or_cleanup_claims(
    backend_bundle, mode, name, field, value
):
    change(backend_bundle, mode, name, field, value)
    directory, expected, _ = backend_bundle
    with pytest.raises(ValueError):
        verifier.verify_backend_runtime(directory, expected)


@pytest.mark.parametrize(
    "field,value",
    [("coverage_active", True), ("trace_type", "CTracer"), ("profile_type", "profiler")],
)
def test_actual_instrumentation_cannot_masquerade_as_runtime(backend_bundle, field, value):
    directory, expected, _ = backend_bundle
    path = directory / "runtime/positive/source-receipt.json"
    instrumentation = json.loads(path.read_text())["instrumentation"]
    instrumentation[field] = value
    change(backend_bundle, "positive", "source-receipt.json", "instrumentation", instrumentation)
    with pytest.raises(ValueError, match="no coverage/trace/profile"):
        verifier.verify_backend_runtime(directory, expected)


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "tampered",
        "stale",
        "duplicate-nonce",
        "extra-child",
        "drain",
        "deadline",
        "output",
    ],
)
def test_original_binding_and_process_ownership_fail_closed(backend_bundle, failure):
    directory, expected, outer = backend_bundle
    if failure == "missing":
        (directory / "runtime/positive/heartbeat.json").unlink()
    elif failure == "tampered":
        (directory / "runtime/positive/heartbeat.json").write_text("{}")
    elif failure == "stale":
        expected = {**expected, "tested_checkout_commit": "replacement"}
    elif failure == "duplicate-nonce":
        outer["children"]["negative"]["nonce"] = outer["children"]["positive"]["nonce"]
    elif failure == "extra-child":
        outer["children"]["replacement"] = copy.deepcopy(outer["children"]["positive"])
    else:
        field = {
            "drain": "process_owner_drained",
            "deadline": "deadline_seconds",
            "output": "output_limit_bytes",
        }[failure]
        outer["children"]["positive"][field] = False if failure == "drain" else 999
    write(directory / "runtime-receipt.json", outer)
    with pytest.raises((ValueError, OSError)):
        verifier.verify_backend_runtime(directory, expected)


@pytest.mark.parametrize("replacement", ["unrelated failure", "skipped", "error"])
def test_negative_must_reject_the_actual_heartbeat(backend_bundle, replacement):
    directory, expected, outer = backend_bundle
    path = directory / "runtime/negative/cases.xml"
    xml = ElementTree.parse(path)
    case = xml.getroot().find("testcase")
    case.remove(case.find("failure"))
    ElementTree.SubElement(
        case, "failure" if replacement == "unrelated failure" else replacement, message=replacement
    )
    xml.write(path)
    outer["children"]["negative"]["artifacts"]["cases.xml"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    write(directory / "runtime-receipt.json", outer)
    with pytest.raises(ValueError):
        verifier.verify_backend_runtime(directory, expected)


def test_required_gate_rejects_missing_backend_controls_before_touching_coverage(
    backend_bundle, monkeypatch, capsys
):
    directory, expected, _ = backend_bundle
    (directory / "runtime-receipt.json").unlink()
    parent_data = directory.parent.parent / ".coverage"
    parent_data.write_bytes(b"preserved parent coverage")

    async def source():
        return expected

    monkeypatch.setattr(backend_runtime, "backend_source", source)
    monkeypatch.setattr(merge_runtime_coverage, "ROOT", directory.parent.parent)
    monkeypatch.setattr("sys.argv", ["merge_runtime_coverage"])
    assert merge_runtime_coverage.main() == 1
    assert "Runtime coverage merge failed" in capsys.readouterr().out
    assert parent_data.read_bytes() == b"preserved parent coverage"
