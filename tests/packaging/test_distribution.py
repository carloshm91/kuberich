"""Check real built artifacts and entry points outside the source checkout."""

import configparser
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

from tests.support.handoff import terminal_handoff_trial
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell
from tests.terminal.pty_support import TerminalSession

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def run(
    command: list[str], directory: Path, timeout: int = 120, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run tools with an explicit directory and without ambient source import paths."""
    environment = os.environ.copy()
    for name in os.environ:
        if name.startswith("KUBETROL_"):
            environment.pop(name)
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment["KUBECONFIG"] = str(directory / "no-cluster-config")
    environment["KUBETROL_CONFIG"] = str(directory / "preferences.yaml")
    environment["KUBETROL_LOG_FILE"] = str(directory / "kubetrol.log")
    return subprocess.run(
        command,
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


@pytest.fixture(scope="session")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv is not None, "Install uv to run the distribution checks."
    output = tmp_path_factory.mktemp("artifacts")
    run([uv, "build", "--out-dir", str(output)], ROOT)
    return next(output.glob("*.whl")), next(output.glob("*.tar.gz"))


@pytest.fixture(scope="session")
def installed_wheel(
    artifacts: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv is not None
    directory = tmp_path_factory.mktemp("installed-wheel")
    (directory / "preferences.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    venv = directory / "venv"
    run([uv, "venv", "--python", sys.executable, str(venv)], directory)
    binary_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    python = binary_dir / ("python.exe" if sys.platform == "win32" else "python")
    run([uv, "pip", "install", "--python", str(python), str(artifacts[0])], directory, 180)
    return binary_dir, directory


def test_wheel_metadata_entry_point_and_assets(artifacts: tuple[Path, Path]) -> None:
    with zipfile.ZipFile(artifacts[0]) as archive:
        names = archive.namelist()
        assert "kubetrol/py.typed" in names
        assert "kubetrol/ui/kubetrol.tcss" in names
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        assert metadata["Name"] == "kubetrol"
        assert metadata["Version"] == PROJECT["version"]
        assert metadata["License-Expression"] == "MIT"
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(entry_name).decode())
        assert entry_points["console_scripts"]["kubetrol"] == "kubetrol.cli:main"
        assert not any(name.startswith(("tests/", ".venv/", ".github/")) for name in names)


def test_installed_terminal_handoff_uses_packaged_services(installed_wheel) -> None:
    binary_dir, directory = installed_wheel
    terminal_handoff_trial(
        str(binary_dir / "python"), directory, "success", name="installed-handoff"
    )


def test_installed_selected_container_shell_uses_real_cli(installed_wheel) -> None:
    binary_dir, directory = installed_wheel
    terminal_shell(
        [str(binary_dir / "kubetrol")], directory, "success", evidence="installed-container-shell"
    )


def test_source_distribution_can_build_a_wheel(
    artifacts: tuple[Path, Path], tmp_path: Path
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    with tarfile.open(artifacts[1]) as archive:
        archive.extractall(tmp_path, filter="data")
    source = next(tmp_path.glob("kubetrol-*"))
    assert (source / "src/kubetrol/py.typed").is_file()
    assert (source / "src/kubetrol/ui/kubetrol.tcss").is_file()
    assert (source / "LICENSE").is_file()
    rebuilt = tmp_path / "rebuilt"
    run([uv, "build", "--wheel", "--out-dir", str(rebuilt)], source)
    assert next(rebuilt.glob("*.whl")).name == artifacts[0].name


@pytest.mark.parametrize("entry_point", ["console", "module"])
@pytest.mark.parametrize("argument", ["--help", "--version", "info", None])
def test_installed_entry_points_work_without_source_or_cluster(
    installed_wheel: tuple[Path, Path], entry_point: str, argument: str | None
) -> None:
    binary_dir, directory = installed_wheel
    if entry_point == "console":
        command = [str(binary_dir / ("kubetrol.exe" if sys.platform == "win32" else "kubetrol"))]
    else:
        command = [
            str(binary_dir / ("python.exe" if sys.platform == "win32" else "python")),
            "-m",
            "kubetrol",
        ]
    if argument is not None:
        command.append(argument)
    output = run(command, directory, 10, check=argument is not None)

    if argument is None:
        assert output.returncode == 2
        assert output.stdout == ""
        assert "requires an interactive terminal" in output.stderr
        return
    assert output.stderr == ""
    if argument == "--version":
        assert output.stdout == f"kubetrol {PROJECT['version']}\n"
    elif argument == "--help":
        assert "usage: kubetrol" in output.stdout
    elif argument == "info":
        information = json.loads(output.stdout)
        assert information["config_file"] == str(directory / "preferences.yaml")
        assert not information["cluster_connected"]
        assert information["terminal_ui_available"]


def test_installed_package_has_assets_and_runtime_dependencies(
    installed_wheel: tuple[Path, Path],
) -> None:
    binary_dir, directory = installed_wheel
    python = binary_dir / ("python.exe" if sys.platform == "win32" else "python")
    code = (
        "import importlib.metadata as m, importlib.resources as r, json; "
        "import textual, kubernetes_asyncio, platformdirs, yaml; "
        "print(json.dumps({'version': m.version('kubetrol'), "
        "'typed': r.files('kubetrol').joinpath('py.typed').is_file(), "
        "'textual': m.version('textual'), 'kubernetes_asyncio': m.version('kubernetes-asyncio')}))"
    )
    result = json.loads(run([str(python), "-c", code], directory, 10).stdout)
    assert result["version"] == PROJECT["version"]
    assert result["typed"] is True
    assert result["textual"] and result["kubernetes_asyncio"]


def test_installed_config_init_check_and_refusal_to_overwrite(
    installed_wheel: tuple[Path, Path], tmp_path: Path
) -> None:
    binary_dir, directory = installed_wheel
    command = [str(binary_dir / "kubetrol"), "--config", str(tmp_path / "preferences.yaml")]
    assert "Created default" in run([*command, "config", "init"], directory, 10).stdout
    assert "valid" in run([*command, "config", "check"], directory, 10).stdout
    with pytest.raises(subprocess.CalledProcessError) as error:
        run([*command, "config", "init"], directory, 10)
    assert error.value.returncode == 3
    assert "already exist" in error.value.stderr


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_terminal_launch_restores_tty_outside_the_checkout(
    installed_wheel: tuple[Path, Path], entry_point: str
) -> None:
    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kubetrol")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kubetrol"]
    )
    with TerminalSession(command, directory) as terminal:
        terminal.wait_for(b"Disconnected")
        terminal.send(b"q")
        terminal.finish()
        terminal.save_evidence(f"installed-{entry_point}")


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["help"], 0),
        (["version", "--short"], 0),
        (["--readonly", "info"], 0),
        (["--context", "fixture"], 2),
        (["--token", "opaque-secret"], 4),
        (["--readonly", "-c", "shell"], 2),
    ],
)
def test_installed_launch_contract_outside_checkout(
    installed_wheel: tuple[Path, Path],
    arguments: list[str],
    expected: int,
) -> None:
    binary_dir, directory = installed_wheel
    output = run([str(binary_dir / "kubetrol"), *arguments], directory, 10, check=False)
    assert output.returncode == expected
    assert "opaque-secret" not in output.stdout + output.stderr
    if arguments == ["version", "--short"]:
        assert output.stdout == f"{PROJECT['version']}\n"
    elif arguments == ["--readonly", "info"]:
        assert json.loads(output.stdout)["preferences"]["read_only"]
    elif expected == 4:
        assert "unavailable" in output.stderr and "F05 #19" in output.stderr
    elif arguments == ["--context", "fixture"]:
        assert "interactive terminal" in output.stderr
    elif expected == 2:
        assert "Read-only mode blocks" in output.stderr


def test_installed_initial_help_and_visibility_options_restore_tty(
    installed_wheel: tuple[Path, Path],
) -> None:
    binary_dir, directory = installed_wheel
    command = [str(binary_dir / "kubetrol"), "--logoless", "--crumbsless", "--command", "help"]
    with TerminalSession(command, directory) as terminal:
        terminal.wait_for(b"Keyboard help")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("installed-launch-help")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_navigation_and_initial_namespace_outside_checkout(installed_wheel, entry_point):
    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kubetrol")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kubetrol"]
    )
    terminal_navigation(
        command, directory, evidence=f"installed-navigation-{entry_point}", initial_scope=True
    )


@pytest.mark.parametrize("quiet", [False, True])
def test_installed_wheel_connects_to_owned_api_and_changes_namespace(
    installed_wheel: tuple[Path, Path],
    quiet: bool,
) -> None:
    import threading
    import time

    from tests.support.terminal_api import Server, config

    binary_dir, directory = installed_wheel
    server = Server()
    if quiet:
        server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "owned-installed-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [str(binary_dir / "kubetrol"), "--kubeconfig", str(path), "--request-timeout", "250ms"],
            directory,
        ) as terminal:
            terminal.wait_for(b"Live")
            terminal.wait_for(b"1 pods")
            terminal.wait_for(b"owned-pty-pod")
            if quiet:
                deadline = time.monotonic() + 8
                while not server.renewed.is_set():
                    terminal._read()
                    assert time.monotonic() < deadline, "Installed quiet watch failed to renew"
                assert len(set(server.watch_versions)) == 1
                assert b"Stale resource data" not in terminal.transcript
                assert b"Reconnecting" not in terminal.transcript
            marker = terminal.send(b":ns team\r")
            terminal.wait_for(b"Namespace: team", since=marker)
            terminal.wait_for(b"Live", since=marker)
            terminal.send(b"q")
            terminal.finish()
            terminal.save_evidence(
                "installed-quiet-watch" if quiet else "installed-context-session"
            )
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_resource_inspection_outside_checkout(installed_wheel, entry_point):
    from tests.support.inspection import terminal_inspection

    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kubetrol")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kubetrol"]
    )
    terminal_inspection(command, directory, evidence=f"installed-inspection-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_log_viewer_outside_checkout(installed_wheel, entry_point):
    from tests.support.log_viewer import terminal_logs

    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kubetrol")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kubetrol"]
    )
    terminal_logs(command, directory, evidence=f"installed-log-viewer-{entry_point}")
