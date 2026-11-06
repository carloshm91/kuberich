"""Opt-in real source-install/version-upgrade on an owned ephemeral Actions host."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from packaging.version import Version

from scripts.homebrew import FORMULA, prepare
from tests.support.distribution import PROJECT, ROOT, clean_environment, run
from tests.support.homebrew_dependencies import prepared_dependencies
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell
from tests.support.source_candidate import (
    published_baseline,
    published_tap,
    source_candidate,
    source_upgrade_versions,
)


@pytest.mark.skipif(
    os.environ.get("KUBERICH_QUALIFY_HOMEBREW") != "1",
    reason="requires the owned native Homebrew qualification workflow",
)
@pytest.mark.parametrize("baseline_kind", ["private-rc", "published"])
def test_native_source_install_real_version_upgrade_and_uninstall(tmp_path, baseline_kind):
    # Do not mutate a developer's personal Homebrew installation.
    assert os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_TEMP")
    brew = shutil.which("brew")
    assert brew is not None
    dependency_preparation = prepared_dependencies(brew)
    outside = tmp_path / "outside"
    outside.mkdir()
    environment = clean_environment(outside)
    environment.update(
        {
            "HOMEBREW_NO_ANALYTICS": "1",
            "HOMEBREW_NO_AUTO_UPDATE": "1",
            "HOMEBREW_NO_INSTALL_CLEANUP": "1",
            "HOMEBREW_NO_AUTOREMOVE": "1",
        }
    )
    prefix = Path(run([brew, "--prefix"], outside, environment=environment).stdout.strip())
    repository = Path(run([brew, "--repository"], outside, environment=environment).stdout.strip())
    tap = repository / "Library/Taps/kuberich/homebrew-tap"
    assert not tap.exists() and not tap.is_symlink()
    assert not (prefix / "bin/kuberich").exists()
    preferences = Path(environment["KUBERICH_CONFIG"])
    preferences.write_text("schema_version: 1\nread_only: true\nrefresh_seconds: 1.5\n")
    caller = Path(environment["KUBECONFIG"])
    caller.write_bytes(b"owned caller sentinel; never use ambient credentials\n")
    before, caller_before = preferences.read_bytes(), caller.read_bytes()
    records = []
    candidates = []
    output = ROOT / "artifacts/installation"
    output.mkdir(parents=True, exist_ok=True)
    target = platform.system().lower() + "-" + platform.machine().lower()
    evidence = f"homebrew-{target}-{baseline_kind}"

    def execute(arguments, timeout=120):
        command = [brew, *arguments]
        started = time.monotonic()
        record = {"command": command, "timeout_seconds": timeout}
        records.append(record)
        try:
            result = run(command, outside, timeout, check=False, environment=environment)
            record.update(exit=result.returncode, stdout=result.stdout, stderr=result.stderr)
            assert result.returncode == 0, result.stdout + result.stderr
            return result
        except BaseException as error:
            record["error"] = type(error).__name__
            if isinstance(error, subprocess.TimeoutExpired):
                for name in ("stdout", "stderr"):
                    value = getattr(error, name)
                    record[name] = (
                        value.decode(errors="replace") if isinstance(value, bytes) else value
                    )
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            (output / f"{evidence}-commands.json").write_text(json.dumps(records, indent=2) + "\n")

    help_trust = run([brew, "help", "trust"], outside, check=False, environment=environment)
    trusts = help_trust.returncode == 0
    try:
        current = PROJECT["version"]
        # Keep the private RC rehearsal and independently install the actual
        # published predecessor; never generate a replacement for public bytes.
        published = published_baseline(current) if baseline_kind == "published" else None
        versions = source_upgrade_versions(current, published)
        for index, version in enumerate(versions):
            bundle = None
            if published is not None and index == 0:
                candidate_record = published_tap(tap, published)
                candidate_record["source_only_local_candidate"] = False
                (output / f"{evidence}-published-formula.rb").write_text(
                    (tap / FORMULA).read_text()
                )
            else:
                source, bundle, sha = source_candidate(tmp_path / ("candidate-" + version), version)
                prepared = tmp_path / ("tap-" + version)
                prepare(bundle, source, prepared)
                if not tap.exists():
                    tap.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(prepared, tap)
                    run(["git", "init", "--initial-branch=main"], tap)
                else:
                    shutil.copyfile(prepared / FORMULA, tap / FORMULA)
                run(["git", "add", "."], tap)
                run(
                    [
                        "git",
                        "-c",
                        "user.name=Release Fixture",
                        "-c",
                        "user.email=fixture@example.invalid",
                        "commit",
                        "-s",
                        "-m",
                        "test: owned unpublished formula version",
                    ],
                    tap,
                )
                candidate_record = {
                    "version": version,
                    "commit": sha,
                    "source_only_local_candidate": True,
                    "files": json.loads((bundle / "release.json").read_text())["files"],
                }
            if index == 0 and trusts:
                # Newer Homebrew loads third-party formulae for audit and test only once trusted.
                execute(["trust", "--formula", "kuberich/tap/kuberich"])
            execute(["style", "kuberich/tap/kuberich"], 180)
            execute(["audit", "--strict", "--online", "kuberich/tap/kuberich"], 300)
            execute(
                [
                    "install" if index == 0 else "upgrade",
                    "--build-from-source",
                    "kuberich/tap/kuberich",
                ],
                1800,
            )
            execute(["test", "kuberich/tap/kuberich"], 180)
            binary = prefix / "bin/kuberich"
            assert (
                run([str(binary), "--version"], outside, environment=environment).stdout
                == f"kuberich {version}\n"
            )
            if Version(version).release >= (0, 4, 0):
                for alias in (
                    prefix / "bin/kubetrol",
                    prefix / "opt/kuberich/libexec/bin/kubetrol",
                ):
                    assert not alias.exists() and not alias.is_symlink()
                interpreter = str(prefix / "opt/kuberich/libexec/bin/python")
                assert (
                    run(
                        [interpreter, "-m", "kuberich", "--version"],
                        outside,
                        environment=environment,
                    ).stdout
                    == f"kuberich {version}\n"
                )
                run(
                    [
                        interpreter,
                        "-c",
                        "import kuberich.cli; assert not hasattr(kuberich.cli, 'legacy_main')",
                    ],
                    outside,
                    environment=environment,
                )
            elif published is not None:
                assert (prefix / "bin/kubetrol").is_file()
            info = json.loads(run([str(binary), "info"], outside, environment=environment).stdout)
            assert (
                info["preferences"]["read_only"] is True
                and info["preferences"]["refresh_seconds"] == 1.5
            )
            assert preferences.read_bytes() == before and caller.read_bytes() == caller_before
            candidates.append(candidate_record)
            if published is not None and index == 1:
                assert (prefix / "Cellar/kuberich" / published["version"]).is_dir()
            if bundle is not None:
                shutil.copytree(bundle, output / f"{evidence}-{version}")
        for name, trial in (("navigation", terminal_navigation), ("shell", terminal_shell)):
            directory = outside / name
            directory.mkdir()
            if name == "navigation":
                trial(
                    [str(binary)],
                    directory,
                    evidence=f"upgraded-homebrew-{baseline_kind}-navigation",
                )
            else:
                trial(
                    [str(binary)],
                    directory,
                    "success",
                    evidence=f"upgraded-homebrew-{baseline_kind}-shell",
                )
    finally:
        if (prefix / "Cellar/kuberich").exists():
            execute(["uninstall", "--force", "kuberich/tap/kuberich"], 180)
        if trusts:
            untrust = [brew, "untrust", "--formula", "kuberich/tap/kuberich"]
            run(untrust, outside, check=False, environment=environment)
        if tap.exists():
            shutil.rmtree(tap)
    assert not (prefix / "bin/kuberich").exists() and not (prefix / "Cellar/kuberich").exists()
    assert not (prefix / "bin/kubetrol").exists() and not (prefix / "bin/kubetrol").is_symlink()
    assert preferences.read_bytes() == before and caller.read_bytes() == caller_before
    (output / f"{evidence}-result.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "source_commit": run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip(),
                "target": target,
                "python": sys.version,
                "brew": execute(["--version"]).stdout,
                "candidates": candidates,
                "baseline_kind": baseline_kind,
                "dependency_preparation": dependency_preparation,
                "application_checks_use_prepared_dependencies": True,
                "end_to_end_cold_install": False,
                "normal_manager_version_upgrade": True,
                "actual_upgraded_navigation_and_shell": True,
                "all_versions_uninstalled": True,
                "preferences_and_caller_config_unchanged": True,
                "preferences_sha256": hashlib.sha256(before).hexdigest(),
                "publication_performed": False,
            },
            indent=2,
        )
        + "\n"
    )
