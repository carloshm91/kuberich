"""Tiny owned writers establish retention behavior, not application qualification."""

import hashlib
import inspect
import json
import signal
import sys
import threading
import time
from contextlib import contextmanager

import pytest

from scripts import qualification as catalog
from scripts import qualification_runner as driver
from tests.quality.test_qualification import checkout as checkout
from tests.quality.test_qualification import owned_runner


def runtime_fixture(root, round_number, nonce_overrides=None, refresh_ui=False):
    """Write deterministic synthetic originals with real source/nonce/hash links."""
    import hashlib
    import json

    root = __import__("pathlib").Path(root)
    source = {
        "tested_checkout_commit": __import__("subprocess")
        .check_output(("git", "rev-parse", "HEAD"), cwd=root, text=True)
        .strip(),
        "tested_checkout_tree": __import__("subprocess")
        .check_output(("git", "rev-parse", "HEAD^{tree}"), cwd=root, text=True)
        .strip(),
        "files": {"README.md": hashlib.sha256((root / "README.md").read_bytes()).hexdigest()},
    }

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else (json.dumps(value) + "\n").encode())

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    runtime_names = {
        "cases.xml",
        "heartbeat.json",
        "source-receipt.json",
        "request.json",
        "stdout.log",
        "stderr.log",
    }
    for family, receipt_name, child_tree, modes in (
        ("backend", "runtime-receipt.json", "runtime", ("positive", "negative")),
        (
            "ui",
            "aggregate-runtime-receipt.json",
            "aggregate-runtime",
            ("positive", "negative", "coverage"),
        ),
    ):
        parent = root / "artifacts" / family
        if (
            family == "ui"
            and round_number > 1
            and not refresh_ui
            and (parent / receipt_name).exists()
        ):
            continue
        children = {}
        for index, mode in enumerate(modes, 1):
            nonce = f"{round_number * 100 + index + (10000 if family == 'ui' else 0):032x}"
            nonce = (nonce_overrides or {}).get(family + ":" + mode, nonce)
            child = parent / child_tree / mode
            names = runtime_names | (
                {"coverage.data", "coverage.json", "coverage.xml"} if mode == "coverage" else set()
            )
            for name in names:
                write(
                    child / name,
                    f"synthetic {round_number} {family} {mode} {name}\x00\xff".encode(),
                )
            write(child / "request.json", {"nonce": nonce, "mode": mode, "source": source})
            write(
                child / "source-receipt.json",
                {"nonce": nonce, "mode": mode, "source_before": source, "source_after": source},
            )
            children[mode] = {
                "nonce": nonce,
                "status": "SYNTHETIC",
                "artifacts": {name: digest(child / name) for name in names},
            }
        write(parent / receipt_name, {"source": source, "children": children})
        observation = (
            "aggregate-tiny-lines-heartbeat.json"
            if family == "backend"
            else "aggregate-heartbeat.json"
        )
        write(parent / observation, {"synthetic": round_number})
    if (
        round_number > 1
        and not refresh_ui
        and (root / "artifacts/ui/coverage-merge-receipt.json").exists()
    ):
        return
    before = root / "artifacts/ui/parent-before-merge" / f"{round_number:032x}"
    hashes = {}
    for name in ("coverage.data", "coverage.json", "coverage.xml"):
        write(before / name, f"parent {round_number} {name}".encode())
        write(
            root / (".coverage" if name == "coverage.data" else name),
            f"parent {round_number} {name}".encode(),
        )
        hashes[name] = digest(before / name)
    write(root / "artifacts/ui/merged-coverage.data", (root / ".coverage").read_bytes())
    write(
        root / "artifacts/ui/coverage-merge-receipt.json",
        {
            "source": source,
            "before_directory": before.relative_to(root / "artifacts/ui").as_posix(),
            "parent_before": hashes,
            "merged": hashes,
            "outer_receipt_sha256": digest(root / "artifacts/ui/aggregate-runtime-receipt.json"),
            "replay_coverage_data_sha256": digest(
                root / "artifacts/ui/aggregate-runtime/coverage/coverage.data"
            ),
            "backend_runtime_receipt_sha256": digest(
                root / "artifacts/backend/runtime-receipt.json"
            ),
        },
    )


def writer_stage(
    root, output, name, round_number=1, tail="", timeout=3, nonce_overrides=None, refresh_ui=False
):
    junit = "cases.xml" if name == "runtime-controls" else name + ".xml"
    script = inspect.getsource(runtime_fixture) + (
        f"\nruntime_fixture({str(root)!r},{round_number},{nonce_overrides!r},{refresh_ui!r})\n"
        f"from pathlib import Path\nPath({str(output / junit)!r}).write_text('<testsuite/>')\n"
        "print('original writer output',flush=True)\n" + tail
    )
    return catalog.Stage(name, (sys.executable, "-c", script), timeout=timeout)


def runner_for(checkout, tmp_path):
    (checkout / ".git/info/exclude").write_text(".coverage\ncoverage.*\n")
    return owned_runner(
        checkout,
        tmp_path,
        [
            catalog.Stage(name, ())
            for name in ("runtime-controls", "contracts-2", "contracts-3", "later")
        ],
    )


def test_each_overwritten_round_keeps_exact_originals_and_first_merge(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    creation = (
        checkout / "artifacts/resource-creation/source/owned-case/nonce/creation-cli-receipt.json"
    )
    creation.parent.mkdir(parents=True)
    creation.write_bytes(b'{"application_result":"Write outcome uncertain"}\n')
    originals = []
    for round_number, stage_name in enumerate(
        ("runtime-controls", "contracts-2", "contracts-3"), 1
    ):
        runner.run(writer_stage(checkout, runner.output, stage_name, round_number))
        record = runner.report["runtime_snapshots"][-1]
        retained = runner.output / record["directory"]
        original = retained / "originals/artifacts/backend/runtime/positive/stdout.log"
        originals.append((original, original.read_bytes()))
        manifest = json.loads((retained / "manifest.json").read_text())
        assert (
            retained / "originals" / creation.relative_to(checkout)
        ).read_bytes() == creation.read_bytes()
        assert manifest["complete"] and manifest["source"] == runner.report["source"]
        identities = manifest["runtime_identities"]
        assert len(set(identities["backend"]["nonces"] + identities["ui"]["nonces"])) == 5
        assert identities["ui"] == runner.report["runtime_snapshots"][0]["runtime_identities"]["ui"]
        link = manifest["files"]["artifacts/backend/runtime/positive/stdout.log"]
        assert link == {
            "original_path": str(checkout / "artifacts/backend/runtime/positive/stdout.log"),
            "size": len(original.read_bytes()),
            "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "status": "retained_original",
        }
        assert all(path.read_bytes() == raw for path, raw in originals)
    first = runner.output / "retained/runtime-controls-1/originals"
    assert (first / ".coverage").read_bytes() == (
        first / "artifacts/ui/merged-coverage.data"
    ).read_bytes()
    assert len({raw for _, raw in originals}) == 3
    assert "original writer output" in (first / "campaign/runtime-controls.log").read_text()
    runner.verify_retained()


@pytest.mark.parametrize("exitcode", [0, 7])
def test_missing_child_retains_partial_originals_but_fails_even_child_zero(
    checkout, tmp_path, exitcode
):
    runner = runner_for(checkout, tmp_path)
    tail = (
        "Path('artifacts/ui/aggregate-runtime/negative/stdout.log').unlink()\n"
        + f"raise SystemExit({exitcode})\n"
    )
    with pytest.raises(ValueError, match="retention failed"):
        runner.run(writer_stage(checkout, runner.output, "runtime-controls", tail=tail))
    retained = runner.output / "retained/runtime-controls-1"
    manifest = json.loads((retained / "manifest.json").read_text())
    assert not manifest["complete"] and "retention_error" in manifest
    assert (retained / "originals/artifacts/backend/runtime/positive/stdout.log").is_file()
    assert runner.report["gates"][0]["status"] == "failed"
    assert runner.report["gates"][0]["returncode"] == exitcode


def test_failed_writer_retains_complete_failed_status(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    with pytest.raises(RuntimeError, match="Stopped at runtime-controls"):
        runner.run(
            writer_stage(checkout, runner.output, "runtime-controls", tail="raise SystemExit(9)\n")
        )
    manifest = json.loads((runner.output / "retained/runtime-controls-1/manifest.json").read_text())
    assert manifest["complete"] and manifest["status"] == "failed"
    assert manifest["gate"]["returncode"] == 9 and manifest["gate"]["group_drained"]


@pytest.mark.parametrize("cancel", [False, True])
def test_deadline_or_cancel_snapshots_only_after_zero_exit_cleanup(checkout, tmp_path, cancel):
    runner = runner_for(checkout, tmp_path)
    ready = tmp_path / "ready"
    tail = (
        "import signal,time\n"
        "def stop(*args):\n"
        " time.sleep(.05)\n"
        " Path('artifacts/backend/drained.log').write_bytes(b'cleanup original')\n"
        " raise SystemExit(0)\n"
        "signal.signal(signal.SIGINT,stop)\n"
        f"Path({str(ready)!r}).touch()\n"
        "time.sleep(20)\n"
    )

    def stop():
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if ready.exists():
            runner.stop(signal.SIGTERM, None)

    closer = threading.Thread(target=stop) if cancel else None
    if closer:
        closer.start()
    try:
        with pytest.raises(RuntimeError):
            runner.run(
                writer_stage(checkout, runner.output, "runtime-controls", tail=tail, timeout=1)
            )
    finally:
        if closer:
            closer.join(timeout=4)
            assert not closer.is_alive()
    retained = runner.output / "retained/runtime-controls-1"
    manifest = json.loads((retained / "manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["gate"]["returncode"] == 0
    assert manifest["gate"]["group_drained"] and manifest["gate"]["process_reaped"]
    assert (
        retained / "originals/artifacts/backend/drained.log"
    ).read_bytes() == b"cleanup original"


@pytest.mark.parametrize("fault", ["tamper", "missing", "extra", "link"])
def test_later_zero_exit_cannot_hide_changed_earlier_snapshot(checkout, tmp_path, fault):
    runner = runner_for(checkout, tmp_path)
    runner.run(writer_stage(checkout, runner.output, "runtime-controls"))
    original = runner.output / "retained/runtime-controls-1/originals/coverage.json"
    if fault == "tamper":
        original.write_text("changed")
    elif fault == "missing":
        original.unlink()
    elif fault == "extra":
        (original.parent / "unexpected").touch()
    else:
        original.unlink()
        original.symlink_to(checkout / "coverage.json")
    with pytest.raises(ValueError, match=r"retained runtime|Unsafe retention"):
        runner.run(catalog.Stage("later", (sys.executable, "-c", "print('zero')")))
    assert runner.report["gates"][-1]["status"] == "failed"
    assert runner.report["gates"][-1]["returncode"] == 0


def test_exclusive_snapshot_collision_never_overwrites_prior_bytes(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    collision = runner.output / "retained/runtime-controls-1"
    collision.mkdir(parents=True)
    original = collision / "existing"
    original.write_bytes(b"prior evidence")
    with pytest.raises(FileExistsError):
        runner.run(writer_stage(checkout, runner.output, "runtime-controls"))
    assert (
        original.read_bytes() == b"prior evidence"
        and runner.report["gates"][0]["status"] == "failed"
    )


def test_symlinked_snapshot_parent_is_refused_before_any_external_write(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    external = tmp_path / "foreign"
    external.mkdir()
    (runner.output / "retained").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe retention"):
        runner.run(writer_stage(checkout, runner.output, "runtime-controls"))
    assert not list(external.iterdir())


def test_unchanged_backend_controls_cannot_stand_in_for_another_contract_round(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    runner.run(writer_stage(checkout, runner.output, "runtime-controls"))
    stage = catalog.Stage(
        "contracts-2",
        (
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(runner.output / 'contracts-2.xml')!r}).write_text('<testsuite/>')",
        ),
    )
    with pytest.raises(ValueError, match="fresh backend"):
        runner.run(stage)
    manifest = json.loads((runner.output / "retained/contracts-2/manifest.json").read_text())
    assert not manifest["complete"] and runner.report["gates"][1]["returncode"] == 0


def test_third_round_cannot_replay_the_initial_backend_nonce(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    runner.run(writer_stage(checkout, runner.output, "runtime-controls", 1))
    runner.run(writer_stage(checkout, runner.output, "contracts-2", 2))
    initial = runner.output / "retained/runtime-controls-1/originals/artifacts/backend"
    tail = f"import shutil\nshutil.copytree({str(initial)!r}, 'artifacts/backend', dirs_exist_ok=True)\n"
    with pytest.raises(ValueError, match="fresh backend"):
        runner.run(writer_stage(checkout, runner.output, "contracts-3", 3, tail=tail))
    assert runner.report["gates"][2]["returncode"] == 0
    assert runner.report["gates"][2]["status"] == "failed"


def test_initial_backend_and_ui_controls_cannot_share_a_nonce(checkout, tmp_path):
    runner = runner_for(checkout, tmp_path)
    stage = writer_stage(
        checkout,
        runner.output,
        "runtime-controls",
        nonce_overrides={
            "ui:positive": f"{101:032x}",
        },
    )
    with pytest.raises(ValueError, match="Invalid retained runtime nonce"):
        runner.run(stage)
    manifest = json.loads((runner.output / "retained/runtime-controls-1/manifest.json").read_text())
    assert not manifest["complete"] and manifest["gate"]["returncode"] == 0
    assert runner.report["gates"][0]["status"] == "failed"


@pytest.mark.parametrize("refresh_ui", [False, True])
def test_new_backend_nonce_cannot_reuse_any_initial_ui_nonce(checkout, tmp_path, refresh_ui):
    runner = runner_for(checkout, tmp_path)
    runner.run(writer_stage(checkout, runner.output, "runtime-controls", 1))
    initial = runner.report["runtime_snapshots"][0]["runtime_identities"]
    reused = initial["ui"]["nonces"][0]
    # A refreshed synthetic UI tree makes the earlier UI nonce absent from the
    # current controls, independently exercising the historical producer union.
    tail = (
        (
            "import json\n"
            "p=Path('artifacts/ui/coverage-merge-receipt.json')\n"
            "merge=json.loads(p.read_text())\n"
            f"merge['backend_runtime_receipt_sha256']={initial['backend']['receipt_sha256']!r}\n"
            "p.write_text(json.dumps(merge))\n"
        )
        if refresh_ui
        else ""
    )
    stage = writer_stage(
        checkout,
        runner.output,
        "contracts-2",
        2,
        nonce_overrides={"backend:positive": reused},
        refresh_ui=refresh_ui,
        tail=tail,
    )
    with pytest.raises(
        ValueError, match="fresh backend" if refresh_ui else "Invalid retained runtime nonce"
    ):
        runner.run(stage)
    manifest = json.loads((runner.output / "retained/contracts-2/manifest.json").read_text())
    assert not manifest["complete"] and manifest["gate"]["returncode"] == 0
    assert runner.report["gates"][1]["status"] == "failed"


@pytest.mark.parametrize("fault", ["source", "nonce", "unsafe-merge", "missing-replay"])
def test_original_source_nonce_and_replay_links_are_mandatory(checkout, tmp_path, fault):
    runner = runner_for(checkout, tmp_path)
    statements = {
        "source": "p=Path('artifacts/backend/runtime-receipt.json'); value=json.loads(p.read_text()); value['source']['tested_checkout_tree']='wrong'; p.write_text(json.dumps(value))",
        "nonce": "p=Path('artifacts/backend/runtime-receipt.json'); value=json.loads(p.read_text()); value['children']['negative']['nonce']=value['children']['positive']['nonce']; p.write_text(json.dumps(value))",
        "unsafe-merge": "p=Path('artifacts/ui/coverage-merge-receipt.json'); value=json.loads(p.read_text()); value['before_directory']='../outside'; p.write_text(json.dumps(value))",
        "missing-replay": "Path('artifacts/ui/aggregate-runtime/coverage/coverage.data').unlink()",
    }
    with pytest.raises(ValueError, match="retention failed"):
        runner.run(
            writer_stage(
                checkout,
                runner.output,
                "runtime-controls",
                tail="import json\n" + statements[fault],
            )
        )
    assert runner.report["gates"][0]["status"] == "failed"
    assert runner.report["gates"][0]["returncode"] == 0


@pytest.mark.parametrize("bound", ["RETENTION_MAX_FILES", "RETENTION_MAX_BYTES"])
def test_retention_is_bounded_and_preserves_incomplete_manifest(
    checkout, tmp_path, monkeypatch, bound
):
    runner = runner_for(checkout, tmp_path)
    monkeypatch.setattr(driver, bound, 1024 if bound.endswith("BYTES") else 1)
    with pytest.raises(ValueError):
        runner.run(writer_stage(checkout, runner.output, "runtime-controls"))
    assert runner.report["gates"][0]["status"] == "failed"
    assert (runner.output / "retained/runtime-controls-1/manifest.json").is_file()


def test_empty_directory_fanout_stops_enumeration_before_all_names(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    root.mkdir()
    for index in range(20):
        (root / f"empty-{index:02}").mkdir()
    scan = driver.os.scandir
    seen = []
    descended = []

    @contextmanager
    def counted(path):
        with scan(path) as iterator:
            if path == root:

                def observed():
                    for child in iterator:
                        seen.append(child.name)
                        yield child

                yield observed()
            else:
                descended.append(path)
                yield iterator

    monkeypatch.setattr(driver.os, "scandir", counted)
    monkeypatch.setattr(driver, "RETENTION_MAX_FILES", 4)
    with pytest.raises(ValueError, match="traversal-entry bound"):
        driver.regular_files(root, root)
    assert len(seen) == 4 and not descended


def test_empty_directories_share_one_bound_across_recursive_visits(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    for parent in ("first", "second"):
        for child in ("one", "two"):
            (root / parent / child).mkdir(parents=True)
    monkeypatch.setattr(driver, "RETENTION_MAX_FILES", 5)
    with pytest.raises(ValueError, match="traversal-entry bound"):
        driver.regular_files(root, root)


def test_late_final_audit_failure_cannot_leave_pending_report(checkout, tmp_path, monkeypatch):
    (checkout / ".git/info/exclude").write_text(".coverage\ncoverage.*\n")
    monkeypatch.setattr(driver, "__file__", str(checkout / "scripts/qualification_runner.py"))
    monkeypatch.setattr(
        driver,
        "local_stages",
        lambda root, out, *args: [writer_stage(root, out, "runtime-controls")],
    )
    archive = driver.archive

    def late_archive(root, destination):
        archive(root, destination)
        if destination.name == "after":
            (destination.parent / "retained/runtime-controls-1/manifest.json").write_text(
                "late tamper"
            )

    monkeypatch.setattr(driver, "archive", late_archive)
    output = checkout / "artifacts/final-audit"
    assert driver.main(["0.3.0", "--base", "HEAD^", "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed" and "retention_error" in report
    assert (output / "before").is_dir() and (output / "after").is_dir()


def test_archive_enrolls_explicit_feature_trees_without_collecting_output(tmp_path):
    root = tmp_path / "root"
    for name in driver.ARCHIVE_TREES:
        source = root / "artifacts" / name
        source.mkdir(parents=True)
        (source / "receipt").write_bytes(name.encode())
    output = root / "artifacts/qualification/run"
    driver.archive(root, output / "before")
    assert {path.name for path in (output / "before").iterdir()} == set(driver.ARCHIVE_TREES)
    assert not (output / "before/qualification").exists()
    with pytest.raises(ValueError, match="recursively"):
        driver.archive(root, root / "artifacts/ui/nested")
    with pytest.raises(ValueError, match="recursively"):
        driver.archive(root, root / "dist/nested")
    assert not (root / "dist").exists()
