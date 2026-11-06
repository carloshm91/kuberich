"""Opt-in real bottle build, pour and upgrade from the published tap on an owned Actions host."""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from packaging.version import Version

from scripts.homebrew import BOTTLE_BLOCK, FORMULA, bottle_records, prepare, with_bottles
from tests.support.distribution import PROJECT, ROOT, clean_environment, run
from tests.support.homebrew_dependencies import prepared_dependencies
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell
from tests.support.source_candidate import (
    published_baseline,
    published_bottle_pour,
    published_tap,
    source_candidate,
)


@pytest.mark.skipif(
    os.environ.get("KUBERICH_QUALIFY_HOMEBREW_BOTTLES") != "1",
    reason="requires the owned native Homebrew bottle qualification workflow",
)
def test_native_bottle_pours_on_upgrade_from_the_published_release(tmp_path):
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
    output = ROOT / "artifacts/installation"
    output.mkdir(parents=True, exist_ok=True)
    target = platform.system().lower() + "-" + platform.machine().lower()
    bottles = output / f"bottles-{target}"
    bottles.mkdir()
    records, timings = [], {}
    current = Version(PROJECT["version"])
    baseline = published_baseline(str(current))
    version = str(current)

    def execute(arguments, timeout=180, phase=None, cwd=outside):
        command = [brew, *arguments]
        started = time.monotonic()
        record = {"command": command, "timeout_seconds": timeout}
        records.append(record)
        try:
            result = run(command, cwd, timeout, check=False, environment=environment)
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
            record["elapsed_seconds"] = elapsed = round(time.monotonic() - started, 3)
            if phase is not None:
                timings[phase] = elapsed
            (output / f"bottle-{target}-commands.json").write_text(
                json.dumps(records, indent=2) + "\n"
            )

    def commit(message):
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
                message,
            ],
            tap,
        )
        return run(["git", "rev-parse", "HEAD"], tap).stdout.strip()

    def installed():
        binary = prefix / "bin/kuberich"
        info = json.loads(run([str(binary), "info"], outside, environment=environment).stdout)
        assert (
            info["preferences"]["read_only"] is True
            and info["preferences"]["refresh_seconds"] == 1.5
        )
        assert preferences.read_bytes() == before and caller.read_bytes() == caller_before
        return run([str(binary), "--version"], outside, environment=environment).stdout

    help_trust = run([brew, "help", "trust"], outside, check=False, environment=environment)
    trusts = help_trust.returncode == 0
    try:
        source, bundle, sha = source_candidate(tmp_path / "candidate", version)
        prepared = tmp_path / "prepared"
        prepare(bundle, source, prepared)
        candidate = (prepared / FORMULA).read_text()
        baseline = published_tap(tap, baseline, bottled=True)
        (output / f"bottle-{target}-published-formula.rb").write_text((tap / FORMULA).read_text())
        if trusts:
            # Trust only this owned formula for commands that load third-party definitions.
            execute(["trust", "--formula", "kuberich/tap/kuberich"])

        # Build the bottle from the candidate source formula, timing each part separately.
        (tap / FORMULA).write_text(candidate)
        built = commit("test: owned unpublished source formula")
        execute(
            ["install", "--only-dependencies", "kuberich/tap/kuberich"],
            1800,
            "candidate_dependency_check",
        )
        execute(["fetch", "--build-from-source", "kuberich/tap/kuberich"], 600, "source_download")
        execute(
            ["install", "--build-bottle", "kuberich/tap/kuberich"], 1800, "source_build_install"
        )
        root_url = bottles.resolve().as_uri()
        execute(
            ["bottle", "--json", "--no-rebuild", f"--root-url={root_url}", "kuberich/tap/kuberich"],
            600,
            None,
            bottles,
        )
        for path in bottles.glob("kuberich--*.bottle.tar.gz"):
            path.rename(path.with_name(path.name.replace("--", "-", 1)))
        (record,) = bottles.glob("*.bottle.json")
        (tag,) = json.loads(record.read_text())["kuberich/tap/kuberich"]["bottle"]["tags"]
        bottle = bottle_records(bottles, version, root_url, (tag,))
        assert bottle[tag]["revision"] == built
        execute(["uninstall", "--force", "kuberich/tap/kuberich"])

        # Install the published release exactly as a user did, then upgrade to the bottle.
        run(["git", "reset", "--quiet", "--hard", baseline["tap_commit"]], tap)
        installed_baseline = execute(
            ["install", "kuberich/tap/kuberich"], 1800, "published_bottle_install"
        )
        baseline_pour = published_bottle_pour(
            baseline, installed_baseline.stdout + installed_baseline.stderr
        )
        assert installed() == f"kuberich {baseline['version']}\n"
        assert (prefix / "bin/kubetrol").is_file()
        (tap / FORMULA).write_text(with_bottles(candidate, bottle, root_url))
        commit("test: owned unpublished bottle formula")
        execute(["style", "kuberich/tap/kuberich"])
        upgrade = execute(["upgrade", "kuberich/tap/kuberich"], 900, "bottle_upgrade")
        log = upgrade.stdout + upgrade.stderr
        # Homebrew names the poured archive with one or two dashes depending on its source.
        assert re.search(rf"Pouring kuberich--?{re.escape(version)}\.{tag}\.bottle\.tar\.gz", log)
        # A poured bottle downloads no Python resources and compiles nothing.
        assert "Resource kuberich--" not in log and "files.pythonhosted.org" not in log
        assert (prefix / "Cellar/kuberich" / baseline["version"]).is_dir()
        assert installed() == f"kuberich {version}\n"
        for alias in (prefix / "bin/kubetrol", prefix / "opt/kuberich/libexec/bin/kubetrol"):
            assert not alias.exists() and not alias.is_symlink()
        interpreter = str(prefix / "opt/kuberich/libexec/bin/python")
        assert (
            run(
                [interpreter, "-m", "kuberich", "--version"], outside, environment=environment
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
        execute(["test", "kuberich/tap/kuberich"])
        binary = str(prefix / "bin/kuberich")
        help_text = run([binary, "--help"], outside, environment=environment).stdout
        assert help_text.startswith("usage: kuberich")
        for name, trial in (("navigation", terminal_navigation), ("shell", terminal_shell)):
            directory = outside / name
            directory.mkdir()
            if name == "navigation":
                trial([binary], directory, evidence="bottle-homebrew-navigation")
            else:
                trial([binary], directory, "success", evidence="bottle-homebrew-shell")

        # Measure a cold pour (no cached archive) and a warm pour (cached archive).
        execute(["uninstall", "--force", "kuberich/tap/kuberich"])
        if trusts:
            # Homebrew revokes formula trust on uninstall; --cache loads it again.
            execute(["trust", "--formula", "kuberich/tap/kuberich"])
        cached = Path(execute(["--cache", "kuberich/tap/kuberich"]).stdout.strip())
        assert cached.name.endswith(f".{tag}.bottle.tar.gz")
        cached.unlink(missing_ok=True)
        assert not cached.exists() and not cached.is_symlink()
        cold = execute(["install", "kuberich/tap/kuberich"], 900, "bottle_cold_install")
        assert "Pouring" in cold.stdout + cold.stderr
        execute(["uninstall", "--force", "kuberich/tap/kuberich"])
        assert cached.is_file()
        warm_cache_sha256 = hashlib.sha256(cached.read_bytes()).hexdigest()
        assert warm_cache_sha256 == bottle[tag]["sha256"]
        warm = execute(["install", "kuberich/tap/kuberich"], 900, "bottle_warm_install")
        assert "Pouring" in warm.stdout + warm.stderr
        assert hashlib.sha256(cached.read_bytes()).hexdigest() == warm_cache_sha256
        assert installed() == f"kuberich {version}\n"
        dependencies = execute(["deps", "--installed", "kuberich/tap/kuberich"]).stdout.split()
    finally:
        if (prefix / "Cellar/kuberich").exists():
            execute(["uninstall", "--force", "kuberich/tap/kuberich"])
        if trusts:
            untrust = [brew, "untrust", "--formula", "kuberich/tap/kuberich"]
            run(untrust, outside, check=False, environment=environment)
        if tap.exists():
            shutil.rmtree(tap)
    assert not (prefix / "bin/kuberich").exists() and not (prefix / "Cellar/kuberich").exists()
    assert not (prefix / "bin/kubetrol").exists() and not (prefix / "bin/kubetrol").is_symlink()
    assert preferences.read_bytes() == before and caller.read_bytes() == caller_before
    assert not BOTTLE_BLOCK.search(candidate)
    (output / f"bottle-{target}-result.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "source_commit": run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip(),
                "candidate_commit": sha,
                "candidate_version": version,
                "published_tap_commit": baseline["tap_commit"],
                "published_baseline": baseline,
                "published_baseline_pour": baseline_pour,
                "target": target,
                "os": platform.platform(),
                "python": sys.version,
                "brew": execute(["--version"]).stdout,
                "prefix": str(prefix),
                "tag": tag,
                "cellar": bottle[tag]["cellar"],
                "sha256": bottle[tag]["sha256"],
                "dependencies": dependencies,
                "dependency_preparation": dependency_preparation,
                "application_checks_use_prepared_dependencies": True,
                "end_to_end_cold_install": False,
                "timings_seconds": timings,
                "cold_bottle_archive_absent_before_install": True,
                "warm_bottle_cache_sha256": warm_cache_sha256,
                "upgrade_kept_previous_keg_until_cleanup": True,
                "actual_poured_navigation_and_shell": True,
                "all_versions_uninstalled": True,
                "preferences_and_caller_config_unchanged": True,
                "publication_performed": False,
            },
            indent=2,
        )
        + "\n"
    )
