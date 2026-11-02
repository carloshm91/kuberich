"""A report cannot turn incomplete work or a failed owned process into qualification."""

import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

from scripts import qualification as catalog
from scripts import qualification_runner as driver
from scripts.release_policy import APPLICATION_JOBS, QUALITY_WORKFLOW, REPOSITORY

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value,issue", [("0.1.0", 51), ("0.3.0", 230), ("1.0.0", 88)])
def test_phase_uses_the_existing_reviewed_mapping(value, issue):
    assert catalog.phase(value) == (value, issue)


@pytest.mark.parametrize("value", ["0.10.0", "1.1.0", "0.3", "0.3.1", "0.3.0rc1", "invalid"])
def test_unreviewed_or_ambiguous_phase_is_refused(value):
    with pytest.raises(ValueError):
        catalog.phase(value)


def test_default_command_runs_all_layers_once_with_existing_independent_coverage_gates(tmp_path):
    stages = catalog.local_stages(ROOT, tmp_path / "out", tmp_path / "external", 6, "a" * 40)
    tests = [stage for stage in stages if "pytest" in stage.command]
    assert len(tests) == 1
    command = tests[0].command
    assert "--cov=kuberich" in command and "--cov-branch" in command
    assert not any(item in command for item in ("-m", "-k", "fast", "tests/unit"))
    assert f"--basetemp={tmp_path / 'external/tests-pytest'}" in command
    by_name = {stage.name: stage.command for stage in stages}
    assert by_name["private-access"] == (
        "uv",
        "run",
        "python",
        "scripts/check_private_access.py",
    )
    assert by_name["startup"] == (
        "uv",
        "run",
        "python",
        "-m",
        "scripts.check_startup",
        "--output",
        str(tmp_path / "out/startup"),
    )
    names = [stage.name for stage in stages]
    assert names.index("private-access") < names.index("tests")
    assert names.index("startup") < names.index("tests")
    assert by_name["types"] == catalog.type_command(ROOT)
    assert by_name["runtime-controls"][-1] == "scripts.merge_runtime_coverage"
    assert by_name["coverage"][-2:] == ("scripts/check_coverage.py", "coverage.json")
    assert "--fail-under" in by_name["changed-coverage"]
    assert "90" in by_name["changed-coverage"]
    assert by_name["supply-chain"][-1] == "--verify"


@pytest.mark.parametrize("workers", [-1, 65])
def test_unbounded_or_invalid_worker_count_is_refused(tmp_path, workers):
    with pytest.raises(ValueError, match="Workers"):
        catalog.local_stages(ROOT, tmp_path, tmp_path, workers, "a" * 40)


def test_kind_catalog_has_every_actual_workflow_rehearsal_and_no_ambient_tools(tmp_path):
    workflow = yaml.safe_load((ROOT / QUALITY_WORKFLOW).read_text())
    body = "\n".join(step.get("run", "") for step in workflow["jobs"]["application"]["steps"])
    first = catalog.cluster_stages(
        tmp_path, Path("/owned/kind"), Path("/owned/kubectl"), Path("/owned/app.whl"), 1
    )
    second = catalog.cluster_stages(
        tmp_path, Path("/owned/kind"), Path("/owned/kubectl"), Path("/owned/app.whl"), 2
    )
    assert len(first) == len(second) == 14
    for stage in first:
        module = stage.command[4]
        assert module in body
        assert stage.command[stage.command.index("--kind") + 1] == "/owned/kind"
        if "--kubectl" in stage.command:
            assert stage.command[stage.command.index("--kubectl") + 1] == "/owned/kubectl"
    assert {stage.name for stage in first}.isdisjoint(stage.name for stage in second)
    assert "--wheel" in first[-1].command and "/owned/app.whl" in first[-1].command


def hosted():
    return (
        {
            "id": 42,
            "head_sha": "a" * 40,
            "path": QUALITY_WORKFLOW,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": REPOSITORY},
        },
        {
            "total_count": len(APPLICATION_JOBS),
            "jobs": [
                {"name": name, "status": "completed", "conclusion": "success", "labels": [runner]}
                for name, runner in APPLICATION_JOBS.items()
            ],
        },
    )


def test_complete_current_full_matrix_uses_existing_release_validators():
    run, jobs = hosted()
    assert catalog.validate_hosted(run, jobs, "a" * 40).endswith("/actions/runs/42")


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("path", ".github/workflows/other.yml"),
        ("head_branch", "feature"),
        ("event", "pull_request"),
        ("status", "queued"),
        ("conclusion", "cancelled"),
        ("head_repository", {"full_name": "other/project"}),
    ],
)
def test_development_queued_stale_or_foreign_runs_never_count_as_full_success(field, value):
    run, jobs = hosted()
    run[field] = value
    with pytest.raises(ValueError):
        catalog.validate_hosted(run, jobs, "a" * 40)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "runner", "skipped", "truncated"])
def test_platform_job_omission_and_incomplete_job_inventories_are_refused(fault):
    run, jobs = hosted()
    if fault == "missing":
        jobs["jobs"].pop()
        jobs["total_count"] -= 1
    elif fault == "duplicate":
        jobs["jobs"].append(copy.deepcopy(jobs["jobs"][0]))
        jobs["total_count"] += 1
    elif fault == "runner":
        jobs["jobs"][0]["labels"] = ["unqualified-runner"]
    elif fault == "skipped":
        jobs["jobs"][0]["conclusion"] = "skipped"
    else:
        jobs["total_count"] += 1
    with pytest.raises(ValueError):
        catalog.validate_hosted(run, jobs, "a" * 40)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".gitignore").write_text("artifacts/\n")
    (root / "pyproject.toml").write_text('[project]\nname="kuberich"\nversion="0.3.0"\n')
    (root / "README.md").write_text("original\n")
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Qualification Fixture"],
        ["git", "config", "user.email", "fixture@example.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "Fixture baseline"],
    ]
    for command in commands:
        subprocess.run(command, cwd=root, check=True)
    (root / "README.md").write_text("candidate\n")
    subprocess.run(["git", "commit", "-qam", "Fixture candidate"], cwd=root, check=True)
    return root


def owned_runner(root, tmp_path, stages):
    out = root / "artifacts/run"
    out.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    report = {
        "phase": "0.3.0",
        "phase_gate": 230,
        "source": driver.snapshot(root),
        "status": "running",
        "external_temp_owner": {"physical_parent": str(external)},
        "gates": [driver.pending(stage.name) for stage in stages],
    }
    return driver.Runner(root, out, report)


def test_real_owned_command_retains_original_failure_and_reaps(checkout, tmp_path):
    stage = catalog.Stage(
        "fault", (sys.executable, "-c", "print('original cause'); raise SystemExit(7)")
    )
    runner = owned_runner(checkout, tmp_path, [stage])
    with pytest.raises(RuntimeError, match="Stopped at fault"):
        runner.run(stage)
    gate = runner.report["gates"][0]
    assert gate["returncode"] == 7 and gate["process_reaped"]
    assert (
        gate["status"] == "failed" and "original cause" in (runner.output / "fault.log").read_text()
    )
    assert runner.current is None


def test_successful_command_cannot_hide_mutation_of_frozen_source(checkout, tmp_path):
    stage = catalog.Stage(
        "mutate",
        (sys.executable, "-c", "from pathlib import Path; Path('README.md').write_text('changed')"),
    )
    runner = owned_runner(checkout, tmp_path, [stage])
    with pytest.raises(ValueError, match="inputs changed"):
        runner.run(stage)
    assert runner.report["gates"][0]["status"] == "failed"


def test_deadline_drains_real_child_even_when_it_exits_zero_on_interrupt(checkout, tmp_path):
    stage = catalog.Stage(
        "deadline",
        (
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGINT, lambda *args: exit(0)); print('ready',flush=True); time.sleep(30)",
        ),
        timeout=1,
    )
    runner = owned_runner(checkout, tmp_path, [stage])
    with pytest.raises(RuntimeError):
        runner.run(stage)
    gate = runner.report["gates"][0]
    assert gate["timed_out"] and gate["process_reaped"] and gate["status"] == "failed"
    assert gate["returncode"] == 0


def test_repeated_cancellation_preserves_actual_child_cleanup_and_refuses_success(
    checkout, tmp_path
):
    ready, cleaned = tmp_path / "ready", tmp_path / "cleaned"
    script = (
        "import signal,time; from pathlib import Path\n"
        "def stop(*args):\n"
        f" time.sleep(.2); Path({str(cleaned)!r}).write_text('drained'); raise SystemExit(0)\n"
        "signal.signal(signal.SIGINT,stop)\n"
        f"Path({str(ready)!r}).write_text('ready')\n"
        "time.sleep(30)\n"
    )
    stage = catalog.Stage("cancel", (sys.executable, "-c", script))
    runner = owned_runner(checkout, tmp_path, [stage])

    def cancel():
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        runner.stop(signal.SIGTERM, None)
        runner.stop(signal.SIGINT, None)

    thread = threading.Thread(target=cancel)
    thread.start()
    try:
        with pytest.raises(RuntimeError):
            runner.run(stage)
    finally:
        thread.join(timeout=4)
    gate = runner.report["gates"][0]
    assert not thread.is_alive() and cleaned.read_text() == "drained"
    assert gate["process_reaped"] and gate["returncode"] == 0 and gate["status"] == "failed"
    assert runner.cancelled == signal.SIGTERM


def test_collect_only_creates_real_external_temps_and_honest_pending_report(checkout, monkeypatch):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    monkeypatch.setattr(
        driver, "local_stages", lambda *args: [catalog.Stage("tests", ("forbidden",))]
    )
    output = checkout / "artifacts/qualification"
    assert driver.main(["0.3.0", "--collect-only", "--base", "HEAD^", "--output", str(output)]) == 2
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "pending" and not report["publication_authorized"]
    assert report["source_unchanged"] and all(
        gate["status"] == "pending" for gate in report["gates"]
    )
    parent = Path(report["external_temp_owner"]["physical_parent"])
    assert parent.is_dir() and parent.stat().st_mode & 0o777 == 0o700
    assert not parent.is_relative_to(checkout) and not (parent / "tests-pytest").exists()
    assert "**pending**" in (output / "summary.md").read_text()
    before = (output / "report.json").read_bytes()
    assert driver.main(["0.3.0", "--collect-only", "--base", "HEAD^", "--output", str(output)]) == 1
    assert (output / "report.json").read_bytes() == before


def test_main_failure_stops_later_work_and_keeps_before_after_originals(checkout, monkeypatch):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    stages = [
        catalog.Stage("first", (sys.executable, "-c", "print('first failure'); exit(3)")),
        catalog.Stage("later", ("forbidden",)),
    ]
    monkeypatch.setattr(driver, "local_stages", lambda *args: stages)
    (checkout / ".coverage").write_bytes(b"earlier original")
    # Real coverage storage is ignored in the source repository too.
    (checkout / ".git/info/exclude").write_text(".coverage\n")
    output = checkout / "artifacts/qualification"
    assert driver.main(["0.3.0", "--base", "HEAD^", "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed" and report["source_unchanged"]
    assert report["gates"][1]["status"] == "pending" and not (output / "later.log").exists()
    assert (output / "before/.coverage").read_bytes() == b"earlier original"
    assert (output / "after/.coverage").read_bytes() == b"earlier original"


@pytest.mark.parametrize("argument", ["HEAD", "missing-ref"])
def test_changed_coverage_cannot_use_a_missing_or_same_commit_baseline(
    checkout, monkeypatch, argument
):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    assert driver.main(["0.3.0", "--collect-only", "--base", argument]) == 1


def test_skip_details_preserve_the_actual_case_and_platform_reason(tmp_path):
    path = tmp_path / "cases.xml"
    path.write_text(
        '<testsuite><testcase classname="tests.packaging" name="native"><skipped message="requires native macOS"/></testcase></testsuite>'
    )
    assert driver.skips(path) == [
        {"case": "tests.packaging::native", "reason": "requires native macOS"}
    ]


@pytest.mark.parametrize("state", ["queued", "in_progress", "waiting"])
def test_waiting_workflow_is_explicitly_pending_and_not_accepted_as_complete(state):
    run, jobs = hosted()
    run["status"] = state
    assert catalog.waiting(run, "a" * 40, QUALITY_WORKFLOW)
    with pytest.raises(ValueError):
        catalog.validate_hosted(run, jobs, "a" * 40)
    run["head_sha"] = "b" * 40
    with pytest.raises(ValueError):
        catalog.waiting(run, "a" * 40, QUALITY_WORKFLOW)


def test_latest_failed_run_cannot_be_replaced_with_an_earlier_success():
    runs = {
        "workflow_runs": [
            {
                "id": 42,
                "head_sha": "a" * 40,
                "run_number": 10,
                "run_attempt": 1,
                "conclusion": "success",
            },
            {
                "id": 43,
                "head_sha": "a" * 40,
                "run_number": 11,
                "run_attempt": 1,
                "conclusion": "failure",
            },
        ]
    }
    with pytest.raises(ValueError, match="latest exact-source"):
        catalog.latest_run(runs, 42, "a" * 40)
    catalog.latest_run(runs, 43, "a" * 40)
    with pytest.raises(ValueError, match="Missing current"):
        catalog.latest_run(runs, 42, "b" * 40)


def test_queued_quality_collection_does_not_prevent_independent_repository_collection(monkeypatch):
    run, _ = hosted()
    run["status"] = "queued"
    repository = {
        **run,
        "id": 43,
        "path": ".github/workflows/repository.yml",
        "event": "push",
        "status": "completed",
    }
    report = {
        "source": {"commit": "a" * 40},
        "gates": [
            driver.pending(name)
            for name in (
                "private-access",
                "startup",
                "tests",
                "native-platforms",
                "plan",
                "repository",
                "repetitions",
            )
        ],
    }

    def api(route):
        if "workflows/" in route:
            identifier = 42 if "quality.yml" in route else 43
            return {
                "workflow_runs": [
                    {"id": identifier, "head_sha": "a" * 40, "run_number": 10, "run_attempt": 1}
                ]
            }
        if route == "actions/runs/42":
            return run
        if route == "actions/runs/43":
            return repository
        assert route == "actions/runs/43/jobs?filter=latest&per_page=100"
        return {
            "total_count": 1,
            "jobs": [
                {
                    "name": "Repository checks",
                    "labels": [driver.LINUX_RUNNER],
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }

    monkeypatch.setattr(driver, "api", api)
    driver.collect(report, 42, 43)
    assert report["hosted"]["quality"]["status"] == "queued"
    statuses = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert statuses == {
        "private-access": "pending",
        "startup": "pending",
        "tests": "pending",
        "native-platforms": "pending",
        "plan": "passed",
        "repository": "passed",
        "repetitions": "pending",
    }


def test_collector_uses_full_matrix_without_inventing_publication_repetitions(monkeypatch):
    run, jobs = hosted()
    report = {
        "source": {"commit": "a" * 40},
        "gates": [
            driver.pending(name)
            for name in (
                "private-access",
                "startup",
                "tests",
                "native-platforms",
                "owned-kind",
                "plan",
                "repository",
                "repetitions",
            )
        ],
    }

    def api(route):
        if "workflows/" in route:
            return {
                "workflow_runs": [
                    {"id": 42, "head_sha": "a" * 40, "run_number": 10, "run_attempt": 1}
                ]
            }
        return run if route == "actions/runs/42" else jobs

    monkeypatch.setattr(driver, "api", api)
    driver.collect(report, 42, None)
    statuses = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert statuses == {
        "private-access": "passed",
        "startup": "passed",
        "tests": "passed",
        "native-platforms": "passed",
        "owned-kind": "passed",
        "plan": "pending",
        "repository": "pending",
        "repetitions": "pending",
    }


def test_stable_phase_cannot_qualify_an_advisory_zero_major_source(checkout, monkeypatch):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    assert driver.main(["1.0.0", "--collect-only", "--base", "HEAD^"]) == 1


def test_direct_documented_entry_point_works_outside_checkout_with_isolated_python(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts/qualify.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "--collect-only" in result.stdout and "--repetitions" in result.stdout


def test_command_zero_exit_without_required_junit_cannot_become_local_pass(checkout, monkeypatch):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    monkeypatch.setattr(
        driver,
        "local_stages",
        lambda *args: [
            catalog.Stage("tests", (sys.executable, "-c", "print('zero exit, missing evidence')"))
        ],
    )
    output = checkout / "artifacts/missing-evidence"
    assert driver.main(["0.3.0", "--base", "HEAD^", "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed" and report["source_unchanged"]
    assert "FileNotFoundError" in report["error"]


@pytest.mark.parametrize("receipt", [None, "[]", "{}"])
def test_owned_verifier_cannot_finish_without_its_actual_object_receipt(
    checkout, tmp_path, receipt
):
    path = checkout / "artifacts/owned.json"
    runner = owned_runner(checkout, tmp_path, [catalog.Stage("owned", ())])
    statement = (
        "pass"
        if receipt is None
        else f"from pathlib import Path; Path({str(path)!r}).write_text({receipt!r})"
    )
    stage = catalog.Stage("owned", (sys.executable, "-c", statement, "--evidence", str(path)))
    if receipt == "{}":
        runner.run(stage)
        assert runner.report["gates"][0]["evidence"] == str(path)
    else:
        with pytest.raises((OSError, ValueError)):
            runner.run(stage)
        assert runner.report["gates"][0]["status"] == "failed"
        assert runner.report["gates"][0]["process_reaped"]


def test_real_signal_cancellation_returns143_restores_handlers_and_retains_cleanup(
    checkout, monkeypatch, tmp_path
):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    ready, cleaned = tmp_path / "main-ready", tmp_path / "main-cleaned"
    script = (
        "import signal,time; from pathlib import Path\n"
        "def stop(*args):\n"
        f" Path({str(cleaned)!r}).write_text('closed'); raise SystemExit(0)\n"
        "signal.signal(signal.SIGINT,stop)\n"
        f"Path({str(ready)!r}).write_text('ready')\n"
        "time.sleep(30)\n"
    )
    monkeypatch.setattr(
        driver,
        "local_stages",
        lambda *args: [catalog.Stage("cancel", (sys.executable, "-c", script), timeout=3)],
    )
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def cancel():
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if ready.exists():
            os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=cancel)
    thread.start()
    output = checkout / "artifacts/cancel-report"
    try:
        assert driver.main(["0.3.0", "--base", "HEAD^", "--output", str(output)]) == 143
    finally:
        thread.join(timeout=4)
    assert not thread.is_alive() and cleaned.read_text() == "closed"
    assert all(signal.getsignal(signum) == handler for signum, handler in previous.items())
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "cancelled" and report["cancel_signal"] == signal.SIGTERM
    assert report["gates"][0]["process_reaped"] and report["source_unchanged"]
    assert (output / "after").is_dir()


def test_last_source_audit_cannot_leave_pending_or_success_after_late_mutation(
    checkout, monkeypatch
):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    monkeypatch.setattr(
        driver, "local_stages", lambda *args: [catalog.Stage("tests", ("forbidden",))]
    )
    snapshot = driver.snapshot
    calls = 0

    def mutate_last(root):
        nonlocal calls
        calls += 1
        if calls == 3:
            (checkout / "README.md").write_text("late tracked mutation")
        return snapshot(root)

    monkeypatch.setattr(driver, "snapshot", mutate_last)
    output = checkout / "artifacts/late-mutation"
    assert driver.main(["0.3.0", "--collect-only", "--base", "HEAD^", "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed" and not report["source_unchanged"]


def test_repetition_pipeline_uses_three_real_tiny_suites_fresh_temps_and_captured_wheel(
    checkout, monkeypatch, tmp_path
):
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    (checkout / ".gitignore").write_text("artifacts/\ndist/\n.pytest_cache/\n__pycache__/\n")
    contracts = checkout / "tests/contract"
    contracts.mkdir(parents=True)
    (contracts / "test_owned.py").write_text("def test_owned():\n    assert True\n")
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-qm", "Owned pipeline fixture"], cwd=checkout, check=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    uv.write_text(
        f"#!{sys.executable}\nimport os,sys\nassert sys.argv[1:3] == ['run', 'pytest']\nos.execv(sys.executable,[sys.executable,'-m','pytest',*sys.argv[3:]])\n"
    )
    uv.chmod(0o700)
    for name in ("kind", "kubectl"):
        tool = binaries / name
        tool.write_text("#!/bin/sh\nexit 99\n")
        tool.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    output = checkout / "artifacts/pipeline"

    def stages(root, out, temporary, workers, base):
        return [
            catalog.Stage(
                "tests",
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/contract",
                    "--no-cov",
                    "-n",
                    "0",
                    f"--basetemp={temporary / 'tests-pytest'}",
                    f"--junitxml={out / 'cases.xml'}",
                ),
            ),
            catalog.Stage(
                "build",
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; p=Path('dist'); p.mkdir(); (p/'kuberich-0.3.0-py3-none-any.whl').write_text('candidate wheel'); (p/'kuberich-0.3.0.tar.gz').write_text('candidate sdist')",
                ),
            ),
            catalog.Stage(
                "metadata",
                (
                    sys.executable,
                    "-c",
                    "import sys; from pathlib import Path; assert len(sys.argv)==3; assert {Path(p).read_text() for p in sys.argv[1:]} == {'candidate wheel','candidate sdist'}",
                ),
            ),
        ]

    observed = []

    def cluster(out, kind, kubectl, wheel, repetition):
        observed.append((kind, kubectl, wheel.read_text(), repetition))
        evidence = out / f"owned-{repetition}.json"
        return [
            catalog.Stage(
                f"owned-{repetition}",
                (
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(evidence)!r}).write_text('{{}}')",
                    "--evidence",
                    str(evidence),
                ),
            )
        ]

    monkeypatch.setattr(driver, "local_stages", stages)
    monkeypatch.setattr(driver, "cluster_stages", cluster)
    assert (
        driver.main(
            [
                "0.3.0",
                "--base",
                "HEAD^",
                "--workers",
                "0",
                "--repetitions",
                "3",
                "--kind",
                str(binaries / "kind"),
                "--kubectl",
                str(binaries / "kubectl"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "pending" and report["source_unchanged"]
    assert [row[3] for row in observed] == [1, 2, 3]
    assert all(row[2] == "candidate wheel" for row in observed)
    gates = {gate["name"]: gate for gate in report["gates"]}
    assert gates["repetitions"]["status"] == gates["owned-kind"]["status"] == "passed"
    assert gates["native-platforms"]["status"] == "pending"
    assert all(
        gates[name]["status"] == "passed"
        for name in ("tests", "contracts-2", "contracts-3", "metadata")
    )
    temps = [
        next(
            arg.split("=", 1)[1] for arg in gates[name]["command"] if arg.startswith("--basetemp=")
        )
        for name in ("tests", "contracts-2", "contracts-3")
    ]
    assert len(set(temps)) == 3 and all(not Path(path).is_relative_to(checkout) for path in temps)
    assert (output / "after/dist/kuberich-0.3.0-py3-none-any.whl").read_text() == "candidate wheel"


def test_all_three_actual_parent_strict_commands_keep_every_target(tmp_path):
    path = tmp_path / QUALITY_WORKFLOW
    path.parent.mkdir(parents=True)
    commands = "\n".join(
        (
            "uv run mypy --strict scripts/check_private_access.py",
            "uv run mypy --strict src/kuberich scripts/check_coverage.py scripts/qualify.py",
            "uv run mypy --strict scripts/check_startup.py scripts/startup_policy.py scripts/startup_probe.py scripts/check_coverage.py",
        )
    )
    path.write_text(yaml.safe_dump({"jobs": {"application": {"steps": [{"run": commands}]}}}))
    assert catalog.type_command(tmp_path) == (
        "uv",
        "run",
        "mypy",
        "--strict",
        "scripts/check_private_access.py",
        "src/kuberich",
        "scripts/check_coverage.py",
        "scripts/qualify.py",
        "scripts/check_startup.py",
        "scripts/startup_policy.py",
        "scripts/startup_probe.py",
    )


def test_kind_cleanup_budget_covers_the_existing_finally_contract(tmp_path):
    stages = catalog.cluster_stages(
        tmp_path, Path("/owned/kind"), Path("/owned/kubectl"), Path("/owned/app.whl"), 1
    )
    assert all(stage.cleanup_timeout == 219 for stage in stages)
    assert catalog.OWNED_KIND_CLEANUP_SECONDS == 2 * 2 * 30 + 90 + 2 * 2 + 5
    assert catalog.Stage("ordinary", ()).cleanup_timeout == 30


def test_markdown_names_actual_source_and_target_without_promoting_preview_metadata():
    report = {
        "phase": "0.3.0",
        "source_version": "0.2.0",
        "phase_gate": 230,
        "source": {"commit": "a" * 40},
        "status": "pending",
        "gates": [],
    }
    text = catalog.summary(report)
    assert "Actual source version: **0.2.0**" in text
    assert "Target phase: **0.3.0**" in text and "Engineering preview" in text
    report["source_version"] = "0.3.0"
    assert "Engineering preview" not in catalog.summary(report)


@pytest.mark.parametrize("cleanup_seconds,completed", [(30, False), (219, True)])
@pytest.mark.parametrize("cancel_before_wait", [False, True])
def test_held_owned_verifier_cleanup_survives_the_old_thirty_second_cutoff(
    checkout, tmp_path, cleanup_seconds, completed, cancel_before_wait
):
    ready, release, cleaned = (
        tmp_path / name for name in ("cleanup-ready", "cleanup-release", "cleanup-done")
    )
    code = (
        "import signal,time; from pathlib import Path\n"
        "def close(*args):\n"
        " signal.signal(signal.SIGINT,signal.SIG_IGN)\n"
        f" Path({str(ready)!r}).write_text('deleting')\n"
        f" while not Path({str(release)!r}).exists(): time.sleep(.01)\n"
        f" Path({str(cleaned)!r}).write_text('absence verified'); raise SystemExit(0)\n"
        "signal.signal(signal.SIGINT,close)\n"
        f"Path({str(tmp_path / 'running')!r}).write_text('running')\n"
        "time.sleep(60)\n"
    )
    stage = catalog.Stage(
        "held-cleanup", (sys.executable, "-c", code), cleanup_timeout=cleanup_seconds
    )
    runner = owned_runner(checkout, tmp_path, [stage])
    clock = time.monotonic
    checks = 0
    draining = False
    advanced = threading.Event()
    cleanup_ready = threading.Event()
    original_wait = runner.wait
    original_drain = runner.drain

    def wait_after_cleanup_starts(timeout, gate):
        if cancel_before_wait:
            assert cleanup_ready.wait(5), "Owned child did not enter cleanup before wait"
        return original_wait(timeout, gate)

    runner.wait = wait_after_cleanup_starts

    def drain_with_cleanup_clock(gate):
        nonlocal draining
        # Wait's own deadline must not consume the first cleanup-clock sample,
        # even when the real child entered its signal handler before wait began.
        draining = True
        try:
            return original_drain(gate)
        finally:
            draining = False

    runner.drain = drain_with_cleanup_clock

    def cleanup_clock():
        nonlocal checks
        if draining and ready.exists():
            checks += 1
            if checks >= 2:
                advanced.set()
                return clock() + 31
        return clock()

    runner.clock = cleanup_clock

    def close():
        try:
            deadline = clock() + 5
            while (
                not ((tmp_path / "running").exists() and runner.current is not None)
                and clock() < deadline
            ):
                time.sleep(0.01)
            assert (tmp_path / "running").exists() and runner.current is not None
            runner.stop(signal.SIGTERM, None)
            while not ready.exists() and clock() < deadline:
                time.sleep(0.01)
            if ready.exists():
                cleanup_ready.set()
            advanced.wait(5)
            if not completed:
                while (
                    runner.current is not None
                    and runner.current.poll() is None
                    and clock() < deadline
                ):
                    time.sleep(0.01)
        finally:
            release.write_text("release owned cleanup")

    thread = threading.Thread(target=close)
    thread.start()
    try:
        with pytest.raises(RuntimeError):
            runner.run(stage)
    finally:
        release.write_text("final release")
        thread.join(timeout=6)
    assert not thread.is_alive() and advanced.is_set()
    gate = runner.report["gates"][0]
    assert gate["group_drained"] and gate["process_reaped"] and gate["status"] == "failed"
    assert cleaned.exists() is completed
    assert bool(gate.get("forced_group_kill")) is not completed


@pytest.mark.parametrize("cancel", [False, True])
def test_exited_leader_cannot_abandon_same_group_descendant_or_signal_unrelated_group(
    checkout, tmp_path, cancel
):
    # The isolated helper is its own Linux child subreaper so these real fault
    # controls can reap orphans without changing the pytest controller's state.
    helper = tmp_path / "descendant_owner.py"
    helper.write_text("""import ctypes,json,os,signal,subprocess,sys,threading,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts.qualification import Stage
from scripts.qualification_runner import Runner,pending,snapshot
root,work=Path(sys.argv[2]),Path(sys.argv[3]); cancel=sys.argv[4]=='True'
if sys.platform.startswith('linux'):
    assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
out=root/'artifacts/descendants'; out.mkdir(parents=True)
external=work/'external'; external.mkdir(mode=0o700)
pidfile,ready=work/'descendant.pid',work/'leader-ready'
program="import os,signal,time; from pathlib import Path\\nchild=os.fork()\\nif child==0:\\n signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN)\\n Path("+repr(str(pidfile))+").write_text(str(os.getpid()))\\n time.sleep(60); os._exit(0)\\nwhile not Path("+repr(str(pidfile))+").exists(): time.sleep(.01)\\n"
if cancel:
    program+="signal.signal(signal.SIGINT,lambda *args: exit(0))\\nPath("+repr(str(ready))+").write_text('ready')\\ntime.sleep(60)\\n"
else:
    program+="raise SystemExit(0)\\n"
program=program.replace('\\\\n','\\n')
stage=Stage('descendant',(sys.executable,'-c',program),cleanup_timeout=.3)
report={'phase':'0.3.0','phase_gate':230,'source':snapshot(root),'source_version':'0.3.0','status':'running','gates':[pending(stage.name)],'external_temp_owner':{'physical_parent':str(external)}}
runner=Runner(root,out,report)
reaped=threading.Event()
def collect():
    deadline=time.monotonic()+10
    while not pidfile.exists() and time.monotonic()<deadline: time.sleep(.01)
    if not pidfile.exists(): return
    pid=int(pidfile.read_text())
    while time.monotonic()<deadline:
        try:
            os.waitpid(pid,0); reaped.set(); return
        except ChildProcessError:
            try: os.kill(pid,0)
            except ProcessLookupError: reaped.set(); return
            time.sleep(.01)
def stop():
    deadline=time.monotonic()+5
    while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
    if ready.exists(): runner.stop(signal.SIGTERM,None)
reader=threading.Thread(target=collect);reader.start()
closer=threading.Thread(target=stop) if cancel else None
if closer: closer.start()
decoy=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)
try:
    try: runner.run(stage)
    except RuntimeError: pass
    else: raise AssertionError('Forced descendant termination cannot qualify a stage')
    reader.join(timeout=3); assert reaped.is_set(), 'actual descendant was abandoned'
    gate=report['gates'][0]
    assert gate['process_reaped'] and gate['group_drained']
    assert gate['status']=='failed'
    assert gate['forced_group_kill'] and decoy.poll() is None
    if closer: closer.join(timeout=3); assert not closer.is_alive()
    (work/'result.json').write_text(json.dumps({'gate':gate,'unrelated_alive':True,'descendant_reaped':True}))
finally:
    if report['gates'][0].get('pid'):
        try: os.killpg(report['gates'][0]['pid'],signal.SIGKILL)
        except ProcessLookupError: pass
    decoy.terminate();decoy.wait(timeout=5)
    reader.join(timeout=3)
""")
    result = subprocess.run(
        [sys.executable, str(helper), str(ROOT), str(checkout), str(tmp_path), str(cancel)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observation = json.loads((tmp_path / "result.json").read_text())
    assert observation["unrelated_alive"] and observation["descendant_reaped"]
    assert observation["gate"]["returncode"] == 0 and observation["gate"]["group_drained"]
