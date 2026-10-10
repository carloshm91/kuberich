"""Verify required runtime controls and merge successful child coverage only."""

import argparse
import asyncio
import gc
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from coverage import Coverage, CoverageData
from coverage import __version__ as coverage_version
from coverage.exceptions import CoverageException

from tests.support.aggregate_runtime import DEADLINE, NODE, OUTPUT_LIMIT, ROOT, source_stamp

RUNTIME_ARTIFACTS = {
    "cases.xml",
    "heartbeat.json",
    "source-receipt.json",
    "request.json",
    "stdout.log",
    "stderr.log",
}
ARTIFACTS = RUNTIME_ARTIFACTS | {"coverage.data", "coverage.json", "coverage.xml"}
CLEANUP = {"app_running": False, "aggregate_registry": 0, "api_log_streams": 0, "api_watches": 0}
VIEWER_CLEANUP = {
    "viewer_closed": True,
    "owner_closed": True,
    "owner_tasks": 0,
    "active_readers": 0,
    "registry_size": 0,
    "api_log_streams": 0,
    "api_watches": 1,
    "background_watches": 1,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def measured_gap(value: Any) -> float:
    if type(value) not in (float, int):
        raise ValueError("Runtime gap must be a finite positive measurement")
    gap = float(value)
    require(math.isfinite(gap) and gap > 0, "Runtime gap must be a finite positive measurement")
    return gap


def verify_runtime(directory: Path, expected: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    outer = document(directory / "aggregate-runtime-receipt.json")
    children = outer.get("children")
    require(
        outer.get("source") == expected
        and isinstance(children, dict)
        and set(children) == {"positive", "negative", "coverage"},
        "Missing or stale required runtime controls/coverage replay receipt",
    )
    nonces = set()
    for mode in ("positive", "negative", "coverage"):
        result = outer["children"][mode]
        nonce = result.get("nonce")
        require(
            isinstance(nonce, str)
            and re.fullmatch("[0-9a-f]{32}", nonce) is not None
            and nonce not in nonces,
            "Runtime nonce must be valid and unique",
        )
        nonces.add(nonce)
        child = directory / "aggregate-runtime" / mode
        inventory = result.get("artifacts")
        require(
            isinstance(inventory, dict)
            and set(inventory) == (ARTIFACTS if mode == "coverage" else RUNTIME_ARTIFACTS),
            "Incomplete runtime artifact inventory",
        )
        for name, checksum in inventory.items():
            require(
                Path(name).name == name and digest(child / name) == checksum,
                "Runtime artifact path or checksum mismatch",
            )
        source, request, heartbeat = (
            document(child / name)
            for name in ("source-receipt.json", "request.json", "heartbeat.json")
        )
        require(
            source.get("nonce") == request.get("nonce") == nonce
            and source.get("mode") == request.get("mode") == mode
            and request.get("source")
            == source.get("source_before")
            == source.get("source_after")
            == expected
            and source.get("source_unchanged") is True
            and source.get("node") == request.get("node") == NODE,
            "Runtime result/source identity is invalid",
        )
        modules = source.get("module_inventory")
        require(
            isinstance(modules, list)
            and all(isinstance(name, str) for name in modules)
            and source.get("development_iri_grammar_absent") is True
            and not any(
                name == root or name.startswith(root + ".")
                for name in modules
                for root in ("rfc3987_syntax", "lark")
            ),
            "Runtime import inventory contains the development-only IRI grammar",
        )
        pid = source.get("pid")
        require(
            type(pid) is int
            and pid > 0
            and source.get("process_group") == pid
            and result.get("process_owner_drained") is True
            and result.get("deadline_seconds") == DEADLINE
            and result.get("output_limit_bytes") == OUTPUT_LIMIT
            and source.get("after_app_close") == CLEANUP,
            "Runtime process/App/API did not drain",
        )
        instrumentation = source.get("instrumentation")
        if not isinstance(instrumentation, dict):
            raise ValueError("Runtime instrumentation facts are absent or invalid")
        require(
            set(instrumentation)
            == {
                "coverage_version",
                "coverage_active",
                "coverage_core",
                "trace_type",
                "profile_type",
            }
            and instrumentation.get("coverage_version") == coverage_version
            and instrumentation.get("profile_type") is None,
            "Runtime instrumentation facts are absent or invalid",
        )
        if mode == "coverage":
            require(
                instrumentation.get("coverage_active") is True
                and (
                    (
                        instrumentation.get("coverage_core") == "CTracer"
                        and instrumentation.get("trace_type") == "coverage.CTracer"
                    )
                    or (
                        instrumentation.get("coverage_core") == "SysMonitor"
                        and instrumentation.get("trace_type") is None
                    )
                ),
                "Functional replay must retain actual branch coverage instrumentation",
            )
        else:
            require(
                instrumentation
                == {
                    "coverage_version": coverage_version,
                    "coverage_active": False,
                    "coverage_core": None,
                    "trace_type": None,
                    "profile_type": None,
                },
                "Runtime timing must be measured without coverage/profile instrumentation",
            )
        require(
            heartbeat.get("gc_enabled") is True
            and heartbeat.get("gc_thresholds") == list(gc.get_threshold())
            and heartbeat.get("limit_seconds") == 0.15
            and heartbeat.get("timing_qualifying") is (mode != "coverage")
            and heartbeat.get("maximum_simultaneously_prepared_records") == 5000
            and type(heartbeat.get("maximum_retained_plus_prepared_records")) is int
            and 5000 <= heartbeat["maximum_retained_plus_prepared_records"] <= 5001
            and heartbeat.get("warm_sizes") == [[40, 12], [100, 30]]
            and heartbeat.get("warm_resources") == ["replicasets", "pods"]
            and heartbeat.get("warm_reopens")
            == heartbeat.get("warm_picker_cycles")
            == heartbeat.get("warm_theme_changes")
            == 4,
            "Runtime warm/retention/GC contract is invalid",
        )
        gap = measured_gap(heartbeat.get("max_gap_seconds"))
        cases = ElementTree.parse(child / "cases.xml").getroot().findall(".//testcase")
        require(
            len(cases) == 1
            and cases[0].attrib.get("name") == NODE.split("::")[1]
            and not any(cases[0].find(name) is not None for name in ("error", "skipped")),
            "Runtime XML does not prove the required case executed",
        )
        failures = cases[0].findall("failure")
        if mode != "negative":
            require(
                result.get("returncode") == 0
                and result.get("status") == "SUCCEEDED"
                and not failures
                and heartbeat.get("negative_callback_executed") is False
                and (mode == "coverage" or gap < 0.15)
                and heartbeat.get("maximum_retained_plus_prepared_records") == 5001
                and heartbeat.get("completed_full_history_rounds") == 2
                and heartbeat.get("after_close") == VIEWER_CLEANUP,
                "Successful runtime/replay result/heartbeat/cleanup is invalid",
            )
        else:
            require(
                result.get("returncode") == 1
                and result.get("status") == "FAILED"
                and len(failures) == 1
                and "Aggregate runtime heartbeat exceeded 150 ms"
                in failures[0].attrib.get("message", "")
                and heartbeat.get("negative_callback_executed") is True
                and gap >= 0.2,
                "Negative control did not fail specifically for the blocking heartbeat",
            )
    return outer, directory / "aggregate-runtime/coverage"


async def merge(
    parent_data: Path, parent_json: Path, parent_xml: Path, directory: Path
) -> dict[str, Any]:
    expected = await source_stamp()
    outer, child = verify_runtime(directory, expected)
    outer_hash = digest(directory / "aggregate-runtime-receipt.json")
    package_files = {
        name
        for name in expected["files"]
        if name.startswith("src/kuberich/") and name.endswith(".py")
    }
    for report in (parent_json, child / "coverage.json"):
        data = document(report)
        require(
            data.get("meta", {}).get("branch_coverage") is True
            and set(data.get("files", {})) == package_files,
            "Parent/replay report lost branch data or production inventory",
        )
    parent = CoverageData(basename=str(parent_data))
    replay = CoverageData(basename=str(child / "coverage.data"))
    parent.read()
    replay.read()
    require(
        parent.has_arcs() and replay.has_arcs(),
        "Parent/replay coverage data must contain measured branches",
    )
    require(
        set(parent.measured_files()) == set(replay.measured_files()) == package_files,
        "Parent/replay data lost exact production inventory",
    )
    union = {
        name: set(parent.arcs(name) or ()) | set(replay.arcs(name) or ()) for name in package_files
    }
    before = directory / "parent-before-merge" / outer["children"]["coverage"]["nonce"]
    before.mkdir(parents=True)
    for name, path in (
        ("coverage.data", parent_data),
        ("coverage.json", parent_json),
        ("coverage.xml", parent_xml),
    ):
        shutil.copyfile(path, before / name)
    inputs = {
        name: digest(before / name) for name in ("coverage.data", "coverage.json", "coverage.xml")
    }
    replay_hash = digest(child / "coverage.data")
    parent.update(replay)
    parent.write()
    require(
        all(set(parent.arcs(name) or ()) == arcs for name, arcs in union.items()),
        "Merged arcs differ from the parent/replay union",
    )
    coverage = Coverage(data_file=str(parent_data), config_file=str(ROOT / "pyproject.toml"))
    coverage.load()
    coverage.json_report(outfile=str(parent_json))
    coverage.xml_report(outfile=str(parent_xml))
    require(await source_stamp() == expected, "Source changed during runtime coverage merge")
    require(
        digest(directory / "aggregate-runtime-receipt.json") == outer_hash
        and digest(child / "coverage.data") == replay_hash
        and verify_runtime(directory, expected)[0] == outer,
        "Runtime evidence changed during coverage merge",
    )
    merged = document(parent_json)
    require(
        set(merged["files"]) == package_files and merged["meta"]["branch_coverage"] is True,
        "Merged report lost production inventory or branch data",
    )
    shutil.copyfile(parent_data, directory / "merged-coverage.data")
    receipt = {
        "source": expected,
        "outer_receipt_sha256": outer_hash,
        "coverage_nonce": outer["children"]["coverage"]["nonce"],
        "before_directory": before.relative_to(directory).as_posix(),
        "parent_before": inputs,
        "replay_coverage_data_sha256": replay_hash,
        "runtime_coverage_merged": False,
        "negative_coverage_merged": False,
        "production_modules": len(package_files),
        "arcs_union_verified": True,
        "union_arc_counts": {name: len(arcs) for name, arcs in sorted(union.items())},
        "merged": {
            "coverage.data": digest(parent_data),
            "coverage.json": digest(parent_json),
            "coverage.xml": digest(parent_xml),
        },
    }
    (directory / "coverage-merge-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    from scripts.check_backend_runtime import verify_backend_runtime
    from tests.support.backend_runtime import backend_source

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-data", type=Path, default=Path(".coverage"))
    parser.add_argument("--parent-json", type=Path, default=Path("coverage.json"))
    parser.add_argument("--parent-xml", type=Path, default=Path("coverage.xml"))
    args = parser.parse_args()
    try:
        backend_expected = asyncio.run(backend_source())
        backend_directory = ROOT / "artifacts/backend"
        backend = verify_backend_runtime(backend_directory, backend_expected)
        backend_hash = digest(backend_directory / "runtime-receipt.json")
        receipt = asyncio.run(
            merge(args.parent_data, args.parent_json, args.parent_xml, ROOT / "artifacts/ui")
        )
        require(
            asyncio.run(backend_source()) == backend_expected
            and digest(backend_directory / "runtime-receipt.json") == backend_hash
            and verify_backend_runtime(backend_directory, backend_expected) == backend,
            "Backend runtime evidence changed during coverage merge",
        )
        receipt["backend_controls_verified"] = True
        receipt["backend_runtime_receipt_sha256"] = backend_hash
        (ROOT / "artifacts/ui/coverage-merge-receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        ElementTree.ParseError,
        CoverageException,
    ) as error:
        print(f"Runtime coverage merge failed: {error}")
        return 1
    print(
        f"Verified successful replay-only runtime coverage merge: {receipt['production_modules']} modules"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
