"""Check real built artifacts and entry points outside the source checkout."""

import configparser
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

from tests.support.azure_handoff import azure_terminal_trial
from tests.support.distribution import PROJECT, run
from tests.support.editing_terminal import terminal_editing
from tests.support.forward_terminal import terminal_forward
from tests.support.handoff import terminal_handoff_trial
from tests.support.mutation_terminal import terminal_mutation
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell
from tests.support.standard_terminal import terminal_standard_views
from tests.support.transports import TerminalTransport
from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_standard_resource_views_outside_checkout(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kubetrol")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kubetrol"]
    )
    terminal_standard_views(command, directory, f"installed-standard-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_port_forward_owns_children_and_restores_terminal(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kubetrol")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kubetrol"]
    )
    terminal_forward(command, directory, f"installed-forward-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_mutation_confirmation_and_terminal_restoration(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kubetrol")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kubetrol"]
    )
    terminal_mutation(command, directory, f"installed-mutation-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_manifest_editor_and_terminal_restoration(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kubetrol")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kubetrol"]
    )
    terminal_editing(command, directory, f"installed-editor-{entry_point}")


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


def test_installed_azure_login_keeps_credentials_private_and_restores_tty(installed_wheel):
    binary_dir, directory = installed_wheel
    azure_terminal_trial(
        str(binary_dir / "python"), directory, "success", name="installed-azure-login"
    )


def test_installed_selected_container_shell_uses_real_cli(installed_wheel) -> None:
    binary_dir, directory = installed_wheel
    terminal_shell(
        [str(binary_dir / "kubetrol")], directory, "success", evidence="installed-container-shell"
    )


@pytest.mark.parametrize("kind", ["ssh", "ssh_tmux"])
def test_installed_wheel_embedded_protocol_over_real_transport(installed_wheel, tmp_path, kind):
    binary_dir, _ = installed_wheel
    with TerminalTransport(tmp_path / "transport", kind) as transport:
        terminal_shell(
            [str(binary_dir / "kubetrol")],
            tmp_path,
            "protocol",
            evidence=f"installed-{kind}-embedded-protocol",
            transport=transport,
        )


def test_installed_wheel_native_handoff_over_ssh(installed_wheel, tmp_path):
    binary_dir, _ = installed_wheel
    with TerminalTransport(tmp_path / "transport", "ssh") as transport:
        terminal_handoff_trial(
            str(binary_dir / "python"),
            tmp_path,
            "success",
            name="installed-ssh-native",
            transport=transport,
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
        (["--token", "opaque-secret"], 2),
        (["--invert"], 4),
        (["--readonly", "-c", "shell"], 2),
        (["--readonly", "-c", "annotate"], 2),
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
        assert "unavailable" in output.stderr and "U01 #56" in output.stderr
    elif arguments in (["--context", "fixture"], ["--token", "opaque-secret"]):
        assert "interactive terminal" in output.stderr
    elif expected == 2:
        assert "Read-only mode blocks" in output.stderr


def test_installed_connection_overrides_in_real_terminal(installed_wheel):
    from tests.terminal.test_contexts import verify_connection_overrides

    binary_dir, directory = installed_wheel
    verify_connection_overrides(
        directory, [str(binary_dir / "kubetrol")], evidence="installed-connection-overrides"
    )


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
            terminal.wait_for_screen("Namespace: team")
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
