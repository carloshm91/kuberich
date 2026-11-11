"""Real private-RC and published-predecessor manager upgrades without publication."""

import hashlib
import json
import os
import shlex
import shutil
import stat
import sys
import zipfile
from pathlib import Path

import pytest
from packaging.version import Version

from scripts.build_standalone import source_inputs
from tests.support.distribution import PROJECT, ROOT, clean_environment, run
from tests.support.navigation import terminal_navigation
from tests.support.published_wheel import published_upgrade_wheel, require_wheelhouse
from tests.support.shell import terminal_shell
from tests.support.source_candidate import published_has_legacy_alias


def installed_identity(python, directory, environment):
    result = run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata as m, json; from pathlib import Path; "
            "from kuberich import cli; "
            "print(json.dumps({'scripts': {p.name:p.value for p in m.distribution('kuberich').entry_points "
            "if p.group=='console_scripts'}, 'legacy_main':hasattr(cli,'legacy_main'), "
            "'module':str(Path(cli.__file__).resolve())}))",
        ],
        directory,
        environment=environment,
    )
    return json.loads(result.stdout)


def retained_files(paths):
    return {
        str(path): {
            "bytes": path.read_bytes(),
            "uid": path.stat().st_uid,
            "gid": path.stat().st_gid,
            "mode": stat.S_IMODE(path.stat().st_mode),
        }
        for path in paths
    }


@pytest.fixture(scope="session")
def private_upgrade_artifacts(artifacts, tmp_path_factory):
    directory = tmp_path_factory.mktemp("upgrade-artifacts")
    source = directory / "source"
    source.mkdir()
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "CHANGELOG.md", "LICENSE", "NOTICE", ".gitignore"):
        shutil.copyfile(ROOT / name, source / name)
    # This is an unpublished owned test build, not a repository version bump or edited wheel.
    current = Version(PROJECT["version"])
    fixture_version = (
        f"{current.base_version}.dev{current.dev + 1}"
        if current.dev is not None
        else current.public + ".post1"
        if current.is_prerelease
        else f"{current.base_version}rc1"
    )
    # A stable candidate receives the real normal upgrade, rather than only
    # serving as the baseline for a hypothetical subsequent test version.
    old_version, version = (
        (str(current), fixture_version)
        if current.is_prerelease
        else (fixture_version, str(current))
    )
    assert Version(version) > Version(old_version)
    project = source / "pyproject.toml"
    original = project.read_text()
    assert original.count(f'version = "{PROJECT["version"]}"') == 1
    project.write_text(
        original.replace(f'version = "{PROJECT["version"]}"', f'version = "{fixture_version}"', 1)
    )
    output = directory / "new"
    run(["uv", "build", "--wheel", "--python", sys.executable, "--out-dir", str(output)], source)
    fixture_wheel = next(output.glob("*.whl"))
    old, newer = (
        (artifacts[0], fixture_wheel) if current.is_prerelease else (fixture_wheel, artifacts[0])
    )
    with zipfile.ZipFile(old) as before, zipfile.ZipFile(newer) as after:
        old_payload = {
            name: before.read(name) for name in before.namelist() if name.startswith("kuberich/")
        }
        new_payload = {
            name: after.read(name) for name in after.namelist() if name.startswith("kuberich/")
        }
        assert old_payload and old_payload == new_payload
    return old, newer, old_version, version


@pytest.fixture(scope="session")
def upgrade_dependencies(tmp_path_factory):
    directory = tmp_path_factory.mktemp("upgrade-dependencies")
    requirements = directory / "runtime.txt"
    run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        ROOT,
    )
    dependencies = directory / "dependencies"
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--dest",
            str(dependencies),
            "--requirement",
            str(requirements),
        ],
        directory,
        180,
    )
    assert list(dependencies.glob("*.whl"))
    return dependencies


@pytest.fixture(scope="session", params=["private-rc", "published", "published-alias"])
def upgrade_artifacts(request, artifacts, upgrade_dependencies, tmp_path_factory):
    kind = request.param
    if kind == "private-rc":
        old, newer, old_version, version = request.getfixturevalue("private_upgrade_artifacts")
        provenance = {"baseline_kind": kind, "published_predecessor": False}
    else:
        old, published = published_upgrade_wheel(
            tmp_path_factory.mktemp("published-upgrade") / "original",
            PROJECT["version"],
            predecessor="0.3.0" if kind == "published-alias" else None,
        )
        newer, old_version, version = artifacts[0], published["version"], PROJECT["version"]
        assert Version(version) > Version(old_version)
        assert published["source_commit"] != run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip()
        provenance = {"baseline_kind": kind, "published_predecessor": published}
    for wheel in (old, newer):
        require_wheelhouse(wheel, upgrade_dependencies)
    provenance["old_artifact"] = {
        "filename": old.name,
        "sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
    }
    provenance["new_artifact"] = {
        "filename": newer.name,
        "sha256": hashlib.sha256(newer.read_bytes()).hexdigest(),
    }
    provenance["candidate_source"] = {
        "commit": run(["git", "rev-parse", "HEAD"], ROOT).stdout.strip(),
        "tracked_status": run(
            ["git", "status", "--porcelain", "--untracked-files=no"], ROOT
        ).stdout,
        "inputs": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in {*source_inputs(ROOT), "uv.lock"}
        },
    }
    provenance["locked_dependency_wheels"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in upgrade_dependencies.glob("*.whl")
    }
    return old, newer, old_version, version, upgrade_dependencies, provenance


@pytest.mark.parametrize("installer,pinned_spec", [("uv", False), ("pipx", False), ("pipx", True)])
def test_real_version_upgrade_retains_preferences_and_runs_installed_ui(
    upgrade_artifacts, tmp_path, installer, pinned_spec
):
    old, newer, old_version, version, dependencies, provenance = upgrade_artifacts
    baseline_kind = provenance["baseline_kind"]
    outside = tmp_path / "outside"
    outside.mkdir()
    wheelhouse = tmp_path / "owned wheelhouse"
    shutil.copytree(dependencies, wheelhouse)
    shutil.copyfile(old, wheelhouse / old.name)
    environment = clean_environment(outside)
    home = outside / "home"
    home.mkdir(mode=0o700)
    environment.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_STATE_HOME": str(home / "state"),
            "XDG_CACHE_HOME": str(home / "cache"),
        }
    )
    preferences = Path(environment["KUBERICH_CONFIG"])
    preferences.write_text("schema_version: 1\nread_only: true\nrefresh_seconds: 1.5\n")
    caller_config = Path(environment["KUBECONFIG"])
    caller_config.write_bytes(b"owned caller sentinel; no cluster credentials\n")
    preference_bytes, caller_bytes = preferences.read_bytes(), caller_config.read_bytes()
    originals = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (old, newer)}
    if installer == "uv":
        manager = ["uv", "tool"]
        options = ["--no-index", "--find-links", str(wheelhouse), "--prerelease", "allow"]
        install = [*manager, "install", "--python", sys.executable, *options, "kuberich"]
        upgrade = [*manager, "upgrade", *options, "kuberich"]
        binary = Path(environment["UV_TOOL_BIN_DIR"]) / "kuberich"
        prefix = Path(environment["UV_TOOL_DIR"]) / "kuberich"
    else:
        manager = [sys.executable, "-m", "pipx"]
        options = [
            "--pip-args",
            shlex.join(["--no-index", "--find-links", str(wheelhouse), "--pre"]),
        ]
        install = [
            *manager,
            "install",
            "--backend",
            "pip",
            "--python",
            sys.executable,
            *options,
            "kuberich",
        ]
        upgrade = [*manager, "upgrade", "--skip-maintenance", *options, "kuberich"]
        binary = Path(environment["PIPX_BIN_DIR"]) / "kuberich"
        prefix = Path(environment["PIPX_HOME"]) / "venvs/kuberich"
    python = prefix / "bin/python"
    retired = (binary.with_name("kubetrol"), prefix / "bin/kubetrol")
    old_has_alias = bool(provenance["published_predecessor"]) and published_has_legacy_alias(
        old_version
    )
    reinstall = [*manager, "reinstall", "--skip-maintenance", "kuberich"]
    if pinned_spec:
        install[-1] = f"kuberich=={old_version}"
    refresh_old = reinstall if pinned_spec else upgrade
    transition_method = (
        "uv-tool-upgrade"
        if installer == "uv"
        else "pipx-uninstall-install-spec-replacement"
        if pinned_spec
        else "pipx-reinstall-alias-removal"
        if old_has_alias
        else "pipx-upgrade"
    )
    scenario = "pinned" if pinned_spec else "unversioned"
    identities = []
    preserved = None
    legacy_paths = ()
    migrated = None
    commands = []
    installed = False
    try:
        for argv in (install, refresh_old):
            result = run(argv, outside, 180, environment=environment)
            installed = True
            commands.append({"command": argv, "exit": result.returncode})
            assert (
                run([str(binary), "--version"], outside, environment=environment).stdout
                == f"kuberich {old_version}\n"
            )
            identity = installed_identity(python, outside, environment)
            assert identity["legacy_main"] is old_has_alias
            assert identity["scripts"] == {
                "kuberich": "kuberich.cli:main",
                **({"kubetrol": "kuberich.cli:legacy_main"} if old_has_alias else {}),
            }
            assert Path(identity["module"]).is_relative_to(prefix)
            for path in retired:
                assert path.exists() is old_has_alias
                if not old_has_alias:
                    assert not path.is_symlink()
            if old_has_alias:
                result = run([str(retired[0]), "--version"], outside, environment=environment)
                assert result.stdout == f"kuberich {old_version}\n"
                assert "deprecated" in result.stderr and "removed in 0.4.0" in result.stderr
            identities.append(identity)
        locations = json.loads(
            run(
                [
                    str(python),
                    "-I",
                    "-c",
                    "import json; from platformdirs import user_config_path; "
                    "print(json.dumps([str(user_config_path(name,appauthor=False)/'config.yaml') "
                    "for name in ('kubetrol','kuberich')]))",
                ],
                outside,
                environment=environment,
            ).stdout
        )
        legacy_config, migrated = map(Path, locations)
        assert legacy_config.is_relative_to(home) and migrated.is_relative_to(home)
        assert not migrated.exists()
        legacy_config.parent.mkdir(parents=True, mode=0o700)
        legacy_config.write_bytes(
            b"readonly: true\nrefresh: 3.5\nlog_file: logs/legacy.log\n"
            b"opaque-private-field: owned-upgrade-private-value\n"
        )
        legacy_log = legacy_config.parent / "logs/legacy.log"
        legacy_log.parent.mkdir(mode=0o700)
        legacy_log.write_bytes(b"# Kubetrol diagnostic log v1\nretained old log bytes\n")
        legacy_lock = legacy_log.with_name("legacy.log.lock")
        legacy_lock.write_bytes(b"# Kubetrol diagnostic lock v1\n")
        legacy_archive = legacy_log.with_name("legacy.log.1")
        legacy_archive.write_bytes(b"# Kubetrol diagnostic log v1\nretained archive bytes\n")
        legacy_paths = (legacy_config, legacy_log, legacy_lock, legacy_archive)
        for path in legacy_paths:
            path.chmod(0o600)
        preserved = retained_files(legacy_paths)
        before_default = run(
            [str(binary), "info"],
            outside,
            environment=environment,
            unset_environment=("KUBERICH_CONFIG", "KUBERICH_LOG_FILE"),
        )
        assert json.loads(before_default.stdout)["config_file"] == str(legacy_config)
        assert "owned-upgrade-private-value" not in before_default.stdout + before_default.stderr
        # An explicit old pipx spec requires deliberate supported replacement;
        # the ordinary unversioned 0.4+ installation uses the actual upgrade.
        shutil.copyfile(newer, wheelhouse / newer.name)
        if pinned_spec:
            for constrained in (upgrade, reinstall):
                result = run(constrained, outside, 180, environment=environment)
                commands.append({"command": constrained, "exit": result.returncode})
                assert (
                    run([str(binary), "--version"], outside, environment=environment).stdout
                    == f"kuberich {old_version}\n"
                )
                unchanged = installed_identity(python, outside, environment)
                assert unchanged["legacy_main"] is old_has_alias
                for path in retired:
                    assert path.exists() is old_has_alias
                    if not old_has_alias:
                        assert not path.is_symlink()
            removed = run([*manager, "uninstall", "kuberich"], outside, environment=environment)
            commands.append(
                {"command": [*manager, "uninstall", "kuberich"], "exit": removed.returncode}
            )
            installed = False
            assert not prefix.exists() and not binary.exists()
            for path in retired:
                assert not path.exists() and not path.is_symlink()
            transition = [*install[:-1], f"kuberich=={version}"]
        else:
            transition = reinstall if installer == "pipx" and old_has_alias else upgrade
        result = run(transition, outside, 180, environment=environment)
        installed = True
        commands.append({"command": transition, "exit": result.returncode})
        assert (
            run([str(binary), "--version"], outside, environment=environment).stdout
            == f"kuberich {version}\n"
        )
        identity = installed_identity(python, outside, environment)
        assert identity["scripts"] == {"kuberich": "kuberich.cli:main"}
        assert identity["legacy_main"] is False
        assert Path(identity["module"]).is_relative_to(prefix)
        identities.append(identity)
        for path in retired:
            assert not path.exists() and not path.is_symlink()
        info = json.loads(run([str(binary), "info"], outside, environment=environment).stdout)
        assert info["version"] == version and info["preferences"]["read_only"] is True
        assert info["preferences"]["refresh_seconds"] == 1.5 and not info["cluster_connected"]
        assert (
            preferences.read_bytes() == preference_bytes
            and caller_config.read_bytes() == caller_bytes
        )
        unset = ("KUBERICH_CONFIG", "KUBERICH_LOG_FILE")
        default = run(
            [str(binary), "info"], outside, environment=environment, unset_environment=unset
        )
        assert json.loads(default.stdout)["config_file"] == str(legacy_config)
        assert json.loads(default.stdout)["migration_pending"]
        copied = run(
            [str(binary), "config", "migrate"],
            outside,
            environment=environment,
            unset_environment=unset,
        )
        assert "Original Kubetrol preferences were retained" in copied.stdout
        assert "owned-upgrade-private-value" not in copied.stdout + copied.stderr
        migrated_info = json.loads(
            run(
                [str(binary), "info"], outside, environment=environment, unset_environment=unset
            ).stdout
        )
        assert migrated_info["config_file"] == str(migrated)
        assert not migrated_info["migration_pending"]
        assert migrated_info["preferences"]["refresh_seconds"] == 3.5
        assert migrated_info["log_file"] == str(legacy_log)
        assert "opaque-private-field: owned-upgrade-private-value" in migrated.read_text()
        assert stat.S_IMODE(migrated.stat().st_mode) == 0o600
        assert retained_files(legacy_paths) == preserved
        for name, trial in (("navigation", terminal_navigation), ("shell", terminal_shell)):
            directory = outside / name
            directory.mkdir()
            if name == "navigation":
                trial(
                    [str(binary)],
                    directory,
                    evidence=f"upgraded-{installer}-{baseline_kind}-{scenario}-navigation",
                )
            else:
                trial(
                    [str(binary)],
                    directory,
                    "success",
                    evidence=f"upgraded-{installer}-{baseline_kind}-{scenario}-shell",
                )
    finally:
        result = run(
            [*manager, "uninstall", "kuberich"], outside, 60, check=False, environment=environment
        )
        if installed:
            assert result.returncode == 0 and not binary.exists() and not prefix.exists()
            for path in retired:
                assert not path.exists() and not path.is_symlink()
    assert (
        preferences.read_bytes() == preference_bytes and caller_config.read_bytes() == caller_bytes
    )
    assert preserved is not None and retained_files(legacy_paths) == preserved
    assert all(path.stat().st_uid == os.getuid() for path in legacy_paths)
    assert originals == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (old, newer)
    }
    output = ROOT / "artifacts/packaging"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{installer}-{baseline_kind}-{scenario}-version-transition.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "installer": installer,
                "artifact_provenance": provenance,
                "old_version": old_version,
                "new_version": version,
                "original_artifacts": originals,
                "commands": commands,
                "normal_manager_upgrade": transition_method in {"uv-tool-upgrade", "pipx-upgrade"},
                "normal_manager_transition": True,
                "transition_method": transition_method,
                "original_spec": f"kuberich=={old_version}" if pinned_spec else "kuberich",
                "explicit_old_spec_reinstall_preserves_version": pinned_spec,
                "explicit_old_spec_upgrade_preserves_version": pinned_spec,
                "actual_upgraded_navigation_and_shell": True,
                "preferences_and_caller_config_unchanged": True,
                "legacy_config_log_lock_archive_bytes_and_ownership_unchanged": True,
                "explicit_legacy_migration_truthful": True,
                "old_alias_existed_before_upgrade": old_has_alias,
                "canonical_only_after_upgrade": True,
                "installed_identities": identities,
                "uninstalled": True,
                "publication_performed": False,
            },
            indent=2,
        )
        + "\n"
    )
