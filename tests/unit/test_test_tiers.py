"""Exercise real pytest selection and shared-fixture ownership across workers."""

import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.tiers import ACTIVE_BATCH, ORCHESTRATOR, ReferenceBatch, runtime_environment

ROOT = Path(__file__).resolve().parents[2]
MARKERS = ("unit", "contract", "ui", "terminal", "packaging", "quality", "kind", "fast")


def project(tmp_path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = --strict-markers\nmarkers =\n"
        + "".join(f"    {name}: fixture layer\n" for name in (*MARKERS, "performance"))
    )
    return tmp_path


def module(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run(root, *arguments):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST_", "KUBERICH_TEST_PART", "COV_CORE_", "COVERAGE_"))
    }
    environment["PYTHONPATH"] = str(ROOT)
    environment["COVERAGE_FILE"] = str(root / ".coverage")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.support.tiers", *arguments],
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


def test_adjacent_timing_children_keep_reader_out_until_coverage_phase(tmp_path, monkeypatch):
    monkeypatch.setenv(ORCHESTRATOR, str(tmp_path))
    batch = ReferenceBatch(tmp_path)
    token = ACTIVE_BATCH.set(batch)
    process = None
    try:
        with runtime_environment({}, exclusive=True):
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import fcntl,sys; print('waiting',flush=True); "
                    "f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_SH); "
                    "print('entered',flush=True)",
                    str(tmp_path / "active"),
                ],
                stdout=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            assert select.select([process.stdout], [], [], 5)[0]
            assert process.stdout.readline() == "waiting\n"
        with runtime_environment({}, exclusive=True):
            assert not select.select([process.stdout], [], [], 0.05)[0]
        with runtime_environment({}, exclusive=False):
            assert select.select([process.stdout], [], [], 5)[0]
            assert process.stdout.readline() == "entered\n"
        assert process.wait(timeout=5) == 0
    finally:
        batch.stack.close()
        ACTIVE_BATCH.reset(token)
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
