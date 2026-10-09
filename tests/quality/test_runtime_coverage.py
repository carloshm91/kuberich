"""Coverage storage and fail-closed runtime receipt regressions, not performance evidence."""

import copy
import gc
import json
from xml.etree import ElementTree

import pytest
from coverage import CoverageData

from scripts import merge_runtime_coverage as runtime
from tests.support.aggregate_runtime import DEADLINE, NODE, OUTPUT_LIMIT, ROOT


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n")


@pytest.fixture
def runtime_bundle(tmp_path, monkeypatch):
    files = sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "src/kuberich").rglob("*.py")
    )
    expected = {"files": dict.fromkeys(files, "fixture"), "tested_checkout_commit": "fixture"}
    directory = tmp_path / "ui"
    directory.mkdir()
    outer = {"source": expected, "children": {}}
    file = "src/kuberich/domain/logs.py"
    for mode in ("positive", "negative", "coverage"):
        child = directory / "aggregate-runtime" / mode
        child.mkdir(parents=True)
        nonce = {"positive": "a", "negative": "b", "coverage": "c"}[mode] * 32
        request = {"nonce": nonce, "mode": mode, "node": NODE, "source": expected}
        write_json(child / "request.json", request)
        write_json(
            child / "source-receipt.json",
            {
                "nonce": nonce,
                "mode": mode,
                "node": NODE,
                "source_before": expected,
                "source_after": expected,
                "source_unchanged": True,
                "module_inventory": ["kuberich", "textual"],
                "development_iri_grammar_absent": True,
                "pid": 123,
                "process_group": 123,
                "after_app_close": runtime.CLEANUP,
                "instrumentation": {
                    "coverage_version": runtime.coverage_version,
                    "coverage_active": mode == "coverage",
                    "coverage_core": "CTracer" if mode == "coverage" else None,
                    "trace_type": "coverage.CTracer" if mode == "coverage" else None,
                    "profile_type": None,
                },
            },
        )
        write_json(
            child / "heartbeat.json",
            {
                "gc_enabled": True,
                "gc_thresholds": list(gc.get_threshold()),
                "limit_seconds": 0.15,
                "maximum_simultaneously_prepared_records": 5000,
                "maximum_retained_plus_prepared_records": 5000 if mode == "negative" else 5001,
                "warm_sizes": [[40, 12], [100, 30]],
                "warm_resources": ["replicasets", "pods"],
                "warm_reopens": 4,
                "warm_picker_cycles": 4,
                "warm_theme_changes": 4,
                "max_gap_seconds": 0.05 if mode == "positive" else 0.21,
                "negative_callback_executed": mode == "negative",
                "timing_qualifying": mode != "coverage",
                "completed_full_history_rounds": 0 if mode == "negative" else 2,
                "after_close": None if mode == "negative" else runtime.VIEWER_CLEANUP,
            },
        )
        xml = ElementTree.Element("testsuite")
        case = ElementTree.SubElement(xml, "testcase", name=NODE.split("::")[1])
        if mode == "negative":
            ElementTree.SubElement(
                case, "failure", message="Aggregate runtime heartbeat exceeded 150 ms"
            )
        ElementTree.ElementTree(xml).write(child / "cases.xml")
        if mode == "coverage":
            data = CoverageData(basename=str(child / "coverage.data"))
            data.add_arcs({name: [] for name in files})
            data.add_arcs({file: [(2, 3)]})
            data.touch_files(files)
            data.write()
            write_json(
                child / "coverage.json",
                {"meta": {"branch_coverage": True}, "files": {name: {} for name in files}},
            )
            (child / "coverage.xml").write_text("<coverage/>\n")
        (child / "stdout.log").write_text(mode)
        (child / "stderr.log").write_text("")
        outer["children"][mode] = {
            "nonce": nonce,
            "returncode": 1 if mode == "negative" else 0,
            "status": "FAILED" if mode == "negative" else "SUCCEEDED",
            "deadline_seconds": DEADLINE,
            "output_limit_bytes": OUTPUT_LIMIT,
            "process_owner_drained": True,
            "artifacts": {
                name: runtime.digest(child / name)
                for name in (runtime.ARTIFACTS if mode == "coverage" else runtime.RUNTIME_ARTIFACTS)
            },
        }
    write_json(directory / "aggregate-runtime-receipt.json", outer)
    parent = tmp_path / "parent.coverage"
    data = CoverageData(basename=str(parent))
    data.add_arcs({name: [] for name in files})
    data.add_arcs({file: [(1, 2)]})
    data.touch_files(files)
    data.write()
    report, xml = tmp_path / "parent.json", tmp_path / "parent.xml"
    write_json(report, {"meta": {"branch_coverage": True}, "files": {name: {} for name in files}})
    xml.write_text("<coverage/>\n")

    async def stamp():
        return copy.deepcopy(expected)

    monkeypatch.setattr(runtime, "source_stamp", stamp)
    return directory, expected, outer, parent, report, xml, file


def change_child(bundle, mode, name, field, value):
    directory, _, outer, *_ = bundle
    path = directory / "aggregate-runtime" / mode / name
    content = json.loads(path.read_text())
    content[field] = value
    write_json(path, content)
    outer["children"][mode]["artifacts"][name] = runtime.digest(path)
    write_json(directory / "aggregate-runtime-receipt.json", outer)


@pytest.mark.asyncio
async def test_merge_uses_actual_branch_union_preserves_parent_and_never_reads_negative(
    runtime_bundle, monkeypatch
):
    directory, _, _, parent, report, xml, file = runtime_bundle
    originals = {
        name: runtime.digest(path)
        for name, path in (
            ("coverage.data", parent),
            ("coverage.json", report),
            ("coverage.xml", xml),
        )
    }
    read = CoverageData.read

    def forbid_runtime_database(data):
        assert data.data_filename() in {
            str(parent),
            str(directory / "aggregate-runtime/coverage/coverage.data"),
        }
        return read(data)

    monkeypatch.setattr(CoverageData, "read", forbid_runtime_database)
    receipt = await runtime.merge(parent, report, xml, directory)
    data = CoverageData(basename=str(parent))
    data.read()
    assert set(data.arcs(file)) == {(1, 2), (2, 3)}
    assert receipt["negative_coverage_merged"] is False and receipt["arcs_union_verified"] is True
    assert receipt["parent_before"] == originals
    before = directory / receipt["before_directory"]
    assert {name: runtime.digest(before / name) for name in originals} == originals
    assert receipt["outer_receipt_sha256"] == runtime.digest(
        directory / "aggregate-runtime-receipt.json"
    )
    assert receipt["merged"]["coverage.data"] == runtime.digest(parent)
    assert runtime.digest(directory / "merged-coverage.data") == runtime.digest(parent)
    assert set(json.loads(report.read_text())["files"]) == set(data.measured_files())
    assert json.loads(report.read_text())["meta"]["branch_coverage"] is True
    assert ElementTree.parse(xml).getroot().tag == "coverage"
    # A repeated merge cannot overwrite the original nonce-bound parent archive.
    with pytest.raises(FileExistsError):
        await runtime.merge(parent, report, xml, directory)
    assert {name: runtime.digest(before / name) for name in originals} == originals


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "stale",
        "tampered",
        "negative-only",
        "missing-replay",
        "duplicate-nonce",
        "no-branches",
        "missing-file",
        "changed-during-merge",
    ],
)
async def test_merge_rejects_missing_stale_tampered_or_incomplete_evidence(
    runtime_bundle, monkeypatch, failure
):
    directory, expected, outer, parent, report, xml, _ = runtime_bundle
    original = runtime.digest(parent)
    if failure == "missing":
        (directory / "aggregate-runtime/positive/heartbeat.json").unlink()
    elif failure == "tampered":
        (directory / "aggregate-runtime/positive/heartbeat.json").write_text("{}")
    elif failure == "stale":
        expected["tested_checkout_commit"] = "replacement"
    elif failure == "negative-only":
        del outer["children"]["positive"]
        write_json(directory / "aggregate-runtime-receipt.json", outer)
    elif failure == "missing-replay":
        del outer["children"]["coverage"]
        write_json(directory / "aggregate-runtime-receipt.json", outer)
    elif failure == "duplicate-nonce":
        outer["children"]["negative"]["nonce"] = outer["children"]["positive"]["nonce"]
        write_json(directory / "aggregate-runtime-receipt.json", outer)
    elif failure == "no-branches":
        value = json.loads(report.read_text())
        value["meta"]["branch_coverage"] = False
        write_json(report, value)
    elif failure == "missing-file":
        value = json.loads(report.read_text())
        value["files"].pop(next(iter(value["files"])))
        write_json(report, value)
    else:
        calls = 0

        async def changing_stamp():
            nonlocal calls
            calls += 1
            return expected if calls == 1 else {}

        monkeypatch.setattr(runtime, "source_stamp", changing_stamp)
    with pytest.raises((ValueError, OSError)):
        await runtime.merge(parent, report, xml, directory)
    if failure != "changed-during-merge":
        assert runtime.digest(parent) == original
        assert not (directory / "parent-before-merge").exists()
    assert not (directory / "coverage-merge-receipt.json").exists()


@pytest.mark.parametrize(
    "mode,name,field,value",
    [
        ("positive", "heartbeat.json", "negative_callback_executed", True),
        ("positive", "heartbeat.json", "max_gap_seconds", 0.15),
        ("positive", "heartbeat.json", "max_gap_seconds", None),
        ("positive", "heartbeat.json", "max_gap_seconds", True),
        ("positive", "heartbeat.json", "max_gap_seconds", float("nan")),
        ("positive", "heartbeat.json", "completed_full_history_rounds", 1),
        ("positive", "heartbeat.json", "maximum_retained_plus_prepared_records", 5000),
        ("positive", "heartbeat.json", "warm_picker_cycles", 3),
        ("positive", "heartbeat.json", "gc_enabled", False),
        ("positive", "source-receipt.json", "module_inventory", ["lark"]),
        ("positive", "source-receipt.json", "after_app_close", None),
        ("positive", "source-receipt.json", "process_group", 456),
        ("negative", "heartbeat.json", "negative_callback_executed", False),
        ("negative", "heartbeat.json", "max_gap_seconds", 0.199),
        ("negative", "source-receipt.json", "source_after", {}),
        ("positive", "heartbeat.json", "timing_qualifying", False),
        ("coverage", "heartbeat.json", "timing_qualifying", True),
        ("coverage", "heartbeat.json", "completed_full_history_rounds", 1),
        ("coverage", "source-receipt.json", "instrumentation", None),
    ],
)
def test_runtime_controls_fail_closed_even_when_tampered_payload_is_rehashed(
    runtime_bundle, mode, name, field, value
):
    change_child(runtime_bundle, mode, name, field, value)
    directory, expected, *_ = runtime_bundle
    with pytest.raises(ValueError):
        runtime.verify_runtime(directory, expected)


@pytest.mark.parametrize(
    "mode,field,value",
    [
        ("positive", "coverage_active", True),
        ("negative", "trace_type", "coverage.CTracer"),
        ("positive", "profile_type", "profiler.Callback"),
        ("coverage", "coverage_active", False),
        ("coverage", "coverage_core", None),
        ("coverage", "trace_type", None),
    ],
)
def test_runtime_and_replay_require_distinct_verified_instrumentation(
    runtime_bundle, mode, field, value
):
    directory, expected, *_ = runtime_bundle
    path = directory / "aggregate-runtime" / mode / "source-receipt.json"
    instrumentation = json.loads(path.read_text())["instrumentation"]
    instrumentation[field] = value
    change_child(runtime_bundle, mode, "source-receipt.json", "instrumentation", instrumentation)
    with pytest.raises(ValueError):
        runtime.verify_runtime(directory, expected)


@pytest.mark.asyncio
async def test_runtime_coverage_database_cannot_enter_the_merge_inputs(runtime_bundle):
    directory, _, outer, parent, report, xml, _ = runtime_bundle
    negative = directory / "aggregate-runtime/negative/coverage.data"
    negative.write_bytes(b"invalid runtime coverage input")
    outer["children"]["negative"]["artifacts"]["coverage.data"] = runtime.digest(negative)
    write_json(directory / "aggregate-runtime-receipt.json", outer)
    original = runtime.digest(parent)
    with pytest.raises(ValueError, match="artifact inventory"):
        await runtime.merge(parent, report, xml, directory)
    assert runtime.digest(parent) == original
    assert not (directory / "coverage-merge-receipt.json").exists()


@pytest.mark.parametrize("replacement", ["unrelated failure", "skipped", "error"])
def test_negative_control_must_fail_specifically_the_heartbeat(runtime_bundle, replacement):
    directory, expected, outer, *_ = runtime_bundle
    path = directory / "aggregate-runtime/negative/cases.xml"
    xml = ElementTree.parse(path)
    case = xml.getroot().find("testcase")
    case.remove(case.find("failure"))
    ElementTree.SubElement(
        case, replacement if replacement != "unrelated failure" else "failure", message=replacement
    )
    xml.write(path)
    outer["children"]["negative"]["artifacts"]["cases.xml"] = runtime.digest(path)
    write_json(directory / "aggregate-runtime-receipt.json", outer)
    with pytest.raises(ValueError):
        runtime.verify_runtime(directory, expected)
