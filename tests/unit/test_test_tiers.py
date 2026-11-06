"""Exercise real pytest selection and shared-fixture ownership across workers."""

import json
import os
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARKERS = ("unit", "contract", "ui", "terminal", "packaging", "quality", "kind", "fast")


def project(tmp_path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = --strict-markers\nmarkers =\n"
        + "".join(
            f"    {name}: fixture layer\n" for name in (*MARKERS, "performance", "runtime_control")
        )
    )
    return tmp_path


def module(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run(root, *arguments):
    environment = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(ROOT),
        "PYTHONUTF8": "1",
        "COVERAGE_FILE": str(root / ".coverage"),
    }
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.support.tiers",
            f"--basetemp={root / 'nested-tmp'}",
            *arguments,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=40,
    )


@pytest.mark.parametrize("selection", ["fast", "unit or contract or ui"])
def test_fast_selects_every_fast_layer_and_never_the_heavy_layers(tmp_path, selection):
    root = project(tmp_path)
    for layer in MARKERS[:-1]:
        expected = layer in {"unit", "contract", "ui"}
        module(root, f"tests/{layer}/test_{layer}.py", f"def test_layer(): assert {expected}\n")
    result = run(root, "-m", selection, "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed, 4 deselected" in result.stdout


def test_parallel_full_selection_runs_all_layers_and_preserves_shared_session_fixture(tmp_path):
    root = project(tmp_path)
    record = root / "owners.jsonl"
    module(
        root,
        "conftest.py",
        "import json,os,pytest\n"
        "@pytest.fixture(scope='session')\n"
        "def shared():\n"
        f"    with open({str(record)!r}, 'a') as f:\n"
        "        f.write(json.dumps(os.getpid())+'\\n')\n"
        "    return os.getpid()\n",
    )
    for layer in MARKERS[:-1]:
        module(root, f"tests/{layer}/test_{layer}.py", "def test_layer(): assert True\n")
    for name in ("test_homebrew_formula", "test_release_candidate", "test_supply_chain"):
        module(
            root,
            f"tests/packaging/{name}.py",
            "import os\ndef test_owner(shared): assert shared == os.getpid()\n",
        )
    result = run(root, "-n", "2", "--dist", "loadgroup", "--max-worker-restart=0", "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "10 passed" in result.stdout
    assert len(record.read_text().splitlines()) == 1


@pytest.mark.parametrize("crash", [False, True])
def test_parallel_workers_report_a_real_failure_without_retrying_or_skipping(tmp_path, crash):
    root = project(tmp_path)
    code = (
        "import os\ndef test_failure(): os._exit(7)\n"
        if crash
        else "def test_failure(): assert False, 'owned failure'\n"
    )
    module(root, "tests/unit/test_failure.py", code)
    result = run(root, "-n", "2", "--dist", "loadgroup", "--max-worker-restart=0", "-q")
    assert result.returncode == 1
    assert ("crashed while running" if crash else "owned failure") in result.stdout
    assert "1 failed" in result.stdout and "replacing crashed worker" not in result.stdout


def test_parallel_coverage_combines_disjoint_branches_and_keeps_unimported_modules(tmp_path):
    root = project(tmp_path)
    module(
        root, "demo_package/__init__.py", "def choose(left):\n    if left: return 1\n    return 2\n"
    )
    module(root, "demo_package/unused.py", "def unused(): return 'unimported'\n")
    for name, argument, expected in (("left", True, 1), ("right", False, 2)):
        module(
            root,
            f"tests/unit/test_{name}.py",
            f"from demo_package import choose\ndef test_branch(): assert choose({argument}) == {expected}\n",
        )
    result = run(
        root,
        "-n",
        "2",
        "--dist",
        "loadgroup",
        "--cov=demo_package",
        "--cov-branch",
        "--cov-report=json:coverage.json",
        "-q",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((root / "coverage.json").read_text())
    selected = report["files"]["demo_package/__init__.py"]["summary"]
    assert selected["num_branches"] == selected["covered_branches"] == 2
    unused = report["files"]["demo_package/unused.py"]["summary"]
    assert unused["num_statements"] > 0 and unused["covered_lines"] == 0


def test_timing_control_drains_other_workers_without_losing_tests(tmp_path):
    root = project(tmp_path)
    record = root / "intervals.jsonl"
    for name in ("ordinary_one", "ordinary_two", "reference"):
        module(
            root,
            f"tests/unit/test_{name}.py",
            "import json,time,pytest\n"
            + ("@pytest.mark.performance\n" if name == "reference" else "")
            + "def test_window():\n"
            + f"    with open({str(record)!r}, 'a') as f:\n"
            + f"        f.write(json.dumps(['start',{name!r},time.monotonic()])+'\\n')\n"
            + "    time.sleep(0.15)\n"
            + f"    with open({str(record)!r}, 'a') as f:\n"
            + f"        f.write(json.dumps(['end',{name!r},time.monotonic()])+'\\n')\n",
        )
    result = run(root, "-n", "3", "--dist", "loadgroup", "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout
    intervals = {}
    for line in record.read_text().splitlines():
        event, name, stamp = json.loads(line)
        intervals.setdefault(name, {})[event] = stamp
    reference = intervals.pop("reference")
    assert len(intervals) == 2
    for ordinary in intervals.values():
        assert ordinary["end"] <= reference["start"] or ordinary["start"] >= reference["end"]


@contextmanager
def ordinary_runtime_reader(directory):
    """Probe real reader admission without relying on a short scheduling timeout."""
    program = """
import fcntl
import sys

with open(sys.argv[1], "a") as entrance, open(sys.argv[2], "a") as active:
    print("ready", flush=True)
    for command in sys.stdin:
        if command.strip() == "quit":
            break
        assert command.strip() == "probe"
        try:
            fcntl.flock(entrance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            reply = "blocked"
        else:
            try:
                fcntl.flock(active, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                reply = "blocked"
            else:
                reply = "admitted"
            finally:
                fcntl.flock(entrance, fcntl.LOCK_UN)
        print(reply, flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(directory / "entrance"), str(directory / "active")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None

    def reply():
        assert select.select([process.stdout], [], [], 5)[0], "Owned lock reader did not answer"
        return process.stdout.readline().strip()

    def probe():
        process.stdin.write("probe\n")
        process.stdin.flush()
        return reply()

    try:
        assert reply() == "ready"
        yield probe, process
    finally:
        try:
            stdout, stderr = process.communicate("quit\n", timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            raise
        assert process.returncode == 0, stdout + stderr


def write_runtime_child_result(request, source):
    """Synthetic validation artifacts, never actual runtime qualification evidence."""
    import gc
    from xml.etree import ElementTree

    from kuberich.domain.processes import ProcessResult, ProcessStatus
    from tests.support import aggregate_runtime as runtime
    from tests.support.runtime_budget import budget_observation

    mode = request["mode"]
    directory = Path(request["directory"])
    negative = mode == "negative"
    gap = 0.21 if negative else 0.05
    receipt = {
        "nonce": request["nonce"],
        "mode": mode,
        "source_before": source,
        "source_after": source,
        "source_unchanged": True,
        "development_iri_grammar_absent": True,
        "instrumentation": {
            "coverage_version": runtime.coverage_version,
            "coverage_active": mode == "coverage",
            "coverage_core": "CTracer" if mode == "coverage" else None,
            "trace_type": "coverage.CTracer" if mode == "coverage" else None,
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
        "gc_thresholds": list(gc.get_threshold()),
        "limit_seconds": 0.15,
        "timing_qualifying": mode != "coverage",
        "runtime_budget": budget_observation(gap, mode=mode),
        "max_gap_seconds": gap,
        "maximum_simultaneously_prepared_records": 5000,
        "maximum_retained_plus_prepared_records": 5001,
        "input_refill": {
            "byte_budget": 8192,
            "records": 5000,
            "batches": 230,
            "maximum_batch_records": 22,
            "maximum_batch_bytes": 8184,
        },
        "negative_callback_executed": negative,
        "completed_full_history_rounds": 0 if negative else 2,
        "warm_sizes": [[40, 12], [100, 30]],
        "warm_resources": ["replicasets", "pods"],
        "warm_reopens": 4,
        "warm_picker_cycles": 4,
        "warm_theme_changes": 4,
        "after_close": {
            "viewer_closed": True,
            "owner_closed": True,
            "owner_tasks": 0,
            "active_readers": 0,
            "registry_size": 0,
            "api_log_streams": 0,
            "api_watches": 1,
            "background_watches": 1,
        },
    }
    (directory / "source-receipt.json").write_text(json.dumps(receipt))
    (directory / "heartbeat.json").write_text(json.dumps(heartbeat))
    suite = ElementTree.Element("testsuite")
    case = ElementTree.SubElement(suite, "testcase", name=runtime.NODE.split("::")[1])
    if negative:
        ElementTree.SubElement(
            case, "failure", message="Aggregate runtime heartbeat exceeded 150 ms"
        )
    ElementTree.ElementTree(suite).write(directory / "cases.xml")
    return ProcessResult(
        ProcessStatus.FAILED if negative else ProcessStatus.SUCCEEDED,
        1 if negative else 0,
        stdout=b"Synthetic runtime child result",
    )


@pytest.mark.parametrize("fail_coverage", [False, True], ids=["complete", "coverage-exception"])
def test_actual_runtime_cohort_blocks_readers_through_coverage_and_releases_after_cleanup(
    tmp_path, monkeypatch, fail_coverage
):
    sentinel = "synthetic-secret-must-not-reach-runtime-children"
    monkeypatch.setenv("KUBERICH_FIXTURE_SECRET_SENTINEL", sentinel)
    root = project(tmp_path)
    record, cleanup = root / "admission.jsonl", root / "reader-cleanup.json"
    module(
        root,
        "tests/unit/test_cohort.py",
        f"""
import json
import os
from pathlib import Path

import pytest

from tests.support import aggregate_runtime as runtime
from tests.support.tiers import HELD, ORCHESTRATOR, WINDOW
from tests.unit.test_test_tiers import ordinary_runtime_reader, write_runtime_child_result

RECORD = Path({str(record)!r})
CLEANUP = Path({str(cleanup)!r})
SOURCE = {{"tested_checkout_commit": "synthetic", "files": {{}}}}


def retain(mode, reply):
    with RECORD.open("a") as output:
        output.write(json.dumps([mode, reply]) + "\\n")


@pytest.fixture(scope="module")
def reader():
    with ordinary_runtime_reader(Path(os.environ[WINDOW])) as (probe, process):
        yield probe
    CLEANUP.write_text(json.dumps({{
        "returncode": process.returncode,
        "pipes_closed": all(stream is None or stream.closed for stream in
                            (process.stdin, process.stdout, process.stderr)),
    }}))


@pytest.mark.runtime_control
@pytest.mark.asyncio
async def test_runtime_cohort(reader, monkeypatch, tmp_path):
    assert os.environ[ORCHESTRATOR] == os.environ[WINDOW]
    assert "KUBERICH_FIXTURE_SECRET_SENTINEL" not in os.environ
    monkeypatch.setattr(runtime, "ROOT", tmp_path)

    async def stamp():
        return SOURCE

    async def child(argv, environment):
        secret_absent = "KUBERICH_FIXTURE_SECRET_SENTINEL" not in environment
        environment = {{runtime.REQUEST: environment.get(runtime.REQUEST), HELD: environment.get(HELD)}}
        assert secret_absent
        assert runtime.NODE in argv and environment[HELD] == "1"
        request = json.loads(Path(environment[runtime.REQUEST]).read_text())
        mode = request["mode"]
        reply = reader()
        retain(mode, reply)
        assert reply == "blocked", mode + " admitted a reader inside the runtime cohort"
        if mode == "coverage" and {fail_coverage!r}:
            raise RuntimeError("Owned coverage child exception")
        return write_runtime_child_result(request, SOURCE)

    monkeypatch.setattr(runtime, "source_stamp", stamp)
    monkeypatch.setattr(runtime, "command", child)
    await runtime.require_runtime_children(measure_coverage=True)


def test_reader_is_admitted_after_real_pytest_owner_cleanup(reader):
    reply = reader()
    retain("after", reply)
    assert reply == "admitted"
""",
    )
    result = run(root, "-q", "--tb=short")
    expected = 1 if fail_coverage else 0
    assert sentinel not in result.stdout + result.stderr
    assert result.returncode == expected, result.stdout + result.stderr
    assert json.loads(cleanup.read_text()) == {"returncode": 0, "pipes_closed": True}
    assert [json.loads(line) for line in record.read_text().splitlines()] == [
        ["positive", "blocked"],
        ["negative", "blocked"],
        ["coverage", "blocked"],
        ["after", "admitted"],
    ]
    if fail_coverage:
        assert "Owned coverage child exception" in result.stdout
        assert "1 failed, 1 passed" in result.stdout
    else:
        assert "2 passed" in result.stdout
