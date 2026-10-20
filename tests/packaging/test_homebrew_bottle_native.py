"""Opt-in real bottle build, pour and upgrade from the published tap on an owned Actions host."""

import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

import pytest
from packaging.version import Version

from scripts.homebrew import BOTTLE_BLOCK, FORMULA, bottle_records, prepare, with_bottles
from tests.support.distribution import PROJECT, ROOT, clean_environment, run
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell
from tests.support.source_candidate import source_candidate

# The reviewed public tap commit that published the source-only 0.1.0 formula.
PUBLISHED = "ec62f339cdb71bf379724fcb2753326dd26ad570"
PUBLISHED_VERSION = "0.1.0"
TAP_URL = "https://github.com/kuberich/homebrew-tap"


@pytest.mark.skipif(
    os.environ.get("KUBERICH_QUALIFY_HOMEBREW_BOTTLES") != "1",
    reason="requires the owned native Homebrew bottle qualification workflow",
)
def test_native_bottle_pours_on_upgrade_from_the_published_release(tmp_path):
    # Do not mutate a developer's personal Homebrew installation.
    assert os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_TEMP")
    brew = shutil.which("brew")
    assert brew is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    environment = clean_environment(outside)
    environment.update(
        {
            "HOMEBREW_NO_ANALYTICS": "1",
            "HOMEBREW_NO_AUTO_UPDATE": "1",
            "HOMEBREW_NO_INSTALL_CLEANUP": "1",
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
    version = str(current) if current > Version(PUBLISHED_VERSION) else "0.2.0rc1"

    def execute(arguments, timeout=180, phase=None, cwd=outside):
        command = [brew, *arguments]
        started = time.monotonic()
        result = run(command, cwd, timeout, check=False, environment=environment)
        if phase is not None:
            timings[phase] = round(time.monotonic() - started, 1)
        records.append(
            {
                "command": command,
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        (output / f"bottle-{target}-commands.json").write_text(json.dumps(records, indent=2) + "\n")
        assert result.returncode == 0, result.stdout + result.stderr
        return result

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

    try:
        source, bundle, sha = source_candidate(tmp_path / "candidate", version)
        prepared = tmp_path / "prepared"
        prepare(bundle, source, prepared)
        candidate = (prepared / FORMULA).read_text()
        tap.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--quiet", TAP_URL, str(tap)], outside)
        run(["git", "checkout", "--quiet", "-B", "main", PUBLISHED], tap)
        assert f"# Source version: {PUBLISHED_VERSION}\n" in (tap / FORMULA).read_text()

        # Build the bottle from the candidate source formula, timing each part separately.
        (tap / FORMULA).write_text(candidate)
        built = commit("test: owned unpublished source formula")
        execute(["install", "--only-dependencies", "kuberich/tap/kuberich"], 1800, "dependencies")
        execute(["fetch", "--build-from-source", "kuberich/tap/kuberich"], 600, "source_download")
        execute(
            ["install", "--build-bottle", "kuberich/tap/kuberich"], 1800, "source_build_install"
        )
        root_url = bottles.resolve().as_uri()
        execute(
            ["bottle", "--json", f"--root-url={root_url}", "kuberich/tap/kuberich"],
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
        run(["git", "reset", "--quiet", "--hard", PUBLISHED], tap)
        execute(["install", "kuberich/tap/kuberich"], 1800, "published_source_install")
        assert installed() == f"kuberich {PUBLISHED_VERSION}\n"
        (tap / FORMULA).write_text(with_bottles(candidate, bottle, root_url))
        commit("test: owned unpublished bottle formula")
        execute(["style", "kuberich/tap/kuberich"])
        upgrade = execute(["upgrade", "kuberich/tap/kuberich"], 900, "bottle_upgrade")
        log = upgrade.stdout + upgrade.stderr
        assert f"Pouring kuberich--{version}.{tag}.bottle.tar.gz" in log
        # A poured bottle downloads no Python resources and compiles nothing.
        assert "Resource kuberich--" not in log and "files.pythonhosted.org" not in log
        assert (prefix / "Cellar/kuberich" / PUBLISHED_VERSION).is_dir()
        assert installed() == f"kuberich {version}\n"
        execute(["test", "kuberich/tap/kuberich"])
        binary = str(prefix / "bin/kuberich")
        assert "Usage" in run([binary, "--help"], outside, environment=environment).stdout
        for name, trial in (("navigation", terminal_navigation), ("shell", terminal_shell)):
            directory = outside / name
            directory.mkdir()
            if name == "navigation":
                trial([binary], directory, evidence="bottle-homebrew-navigation")
            else:
                trial([binary], directory, "success", evidence="bottle-homebrew-shell")

        # Measure a cold pour (no cached archive) and a warm pour (cached archive).
        execute(["uninstall", "--force", "kuberich/tap/kuberich"])
        cached = Path(execute(["--cache", "kuberich/tap/kuberich"]).stdout.strip())
        assert cached.name.endswith(f".{tag}.bottle.tar.gz")
        cached.unlink(missing_ok=True)
        cold = execute(["install", "kuberich/tap/kuberich"], 900, "bottle_cold_install")
        assert "Pouring" in cold.stdout + cold.stderr
        execute(["uninstall", "--force", "kuberich/tap/kuberich"])
        warm = execute(["install", "kuberich/tap/kuberich"], 900, "bottle_warm_install")
        assert "Pouring" in warm.stdout + warm.stderr
        assert installed() == f"kuberich {version}\n"
        dependencies = execute(["deps", "--installed", "kuberich/tap/kuberich"]).stdout.split()
    finally:
        if (prefix / "Cellar/kuberich").exists():
            execute(["uninstall", "--force", "kuberich/tap/kuberich"])
        if tap.exists():
            shutil.rmtree(tap)
    assert not (prefix / "bin/kuberich").exists() and not (prefix / "Cellar/kuberich").exists()
    assert preferences.read_bytes() == before and caller.read_bytes() == caller_before
    assert not BOTTLE_BLOCK.search(candidate)
    (output / f"bottle-{target}-result.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "source_commit": run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip(),
                "candidate_commit": sha,
                "candidate_version": version,
                "published_tap_commit": PUBLISHED,
                "target": target,
                "os": platform.platform(),
                "python": sys.version,
                "brew": execute(["--version"]).stdout,
                "prefix": str(prefix),
                "tag": tag,
                "cellar": bottle[tag]["cellar"],
                "sha256": bottle[tag]["sha256"],
                "dependencies": dependencies,
                "timings_seconds": timings,
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
