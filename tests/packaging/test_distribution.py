"""Check real built artifacts and entry points outside the source checkout."""

import asyncio
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

from tests.support.aggregate_terminal import terminal_aggregate_logs
from tests.support.azure_handoff import azure_terminal_trial
from tests.support.connections import fake_api
from tests.support.credential_handoff import credential_terminal_trial, encrypted_key_terminal_trial
from tests.support.custom_terminal import terminal_custom_views
from tests.support.distribution import PROJECT, run
from tests.support.editing_terminal import terminal_editing
from tests.support.forward_terminal import terminal_forward
from tests.support.handoff import terminal_handoff_trial
from tests.support.mutation_terminal import terminal_mutation
from tests.support.navigation import terminal_navigation
from tests.support.operation_terminal import terminal_operation
from tests.support.operations import operation_api
from tests.support.shell import terminal_shell
from tests.support.standard_terminal import terminal_standard_views
from tests.support.transports import TerminalTransport
from tests.support.workload_terminal import terminal_workload
from tests.support.workloads import workload_api
from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_aggregate_logs_and_terminal_restore(installed_wheel, entry_point):
    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kuberich")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kuberich"]
    )
    terminal_aggregate_logs(command, directory, f"installed-aggregate-logs-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_standard_resource_views_outside_checkout(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    terminal_standard_views(command, directory, f"installed-standard-{entry_point}")
    terminal_custom_views(command, directory, f"installed-custom-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_port_forward_owns_children_and_restores_terminal(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    terminal_forward(command, directory, f"installed-forward-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_mutation_confirmation_and_terminal_restoration(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    terminal_mutation(command, directory, f"installed-mutation-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_manifest_editor_and_terminal_restoration(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    terminal_editing(command, directory, f"installed-editor-{entry_point}")


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["console", "module"])
async def test_installed_workload_confirmation_and_restoration(installed_wheel, entry_point):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    async with workload_api() as (url, api):
        await asyncio.to_thread(
            terminal_workload, command, directory, "installed-workload-" + entry_point, url, api
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["console", "module"])
@pytest.mark.parametrize("alias,action", [("cj", "trigger"), ("cm", "delete")])
async def test_installed_resource_operation_confirmation(
    installed_wheel, entry_point, alias, action
):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    async with operation_api(alias) as (url, api):
        await asyncio.to_thread(
            terminal_operation,
            command,
            directory,
            f"installed-operation-{entry_point}-{action}",
            url,
            api,
            action,
            alias,
        )


def test_wheel_metadata_entry_point_and_assets(artifacts: tuple[Path, Path]) -> None:
    with zipfile.ZipFile(artifacts[0]) as archive:
        names = archive.namelist()
        assert "kuberich/py.typed" in names
        assert "kuberich/ui/kuberich.tcss" in names
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        assert metadata["Name"] == "kuberich"
        assert metadata["Version"] == PROJECT["version"]
        assert metadata["License-Expression"] == "Apache-2.0"
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
        assert any(name.endswith(".dist-info/licenses/NOTICE") for name in names)
        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(entry_name).decode())
        assert entry_points["console_scripts"]["kuberich"] == "kuberich.cli:main"
        assert entry_points["console_scripts"]["kubetrol"] == "kuberich.cli:main"
        assert not any(name.startswith(("tests/", ".venv/", ".github/")) for name in names)


def test_installed_legacy_console_alias_uses_current_metadata(installed_wheel) -> None:
    binary, directory = installed_wheel
    for executable in ("kuberich", "kubetrol"):
        result = run([str(binary / executable), "--version"], directory, 10)
        assert result.stdout == f"kuberich {PROJECT['version']}\n"
        result = run([str(binary / executable), "--help"], directory, 10)
        assert "usage: kuberich" in result.stdout and "--context" in result.stdout


@pytest.mark.parametrize("executable", ["kuberich", "kubetrol"])
def test_installed_default_preferences_migrate_without_losing_legacy_state(
    installed_wheel, tmp_path: Path, executable: str
) -> None:
    binary, _ = installed_wheel
    home = tmp_path / "owned-home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_CACHE_HOME": str(home / "cache"),
    }
    unset = ("KUBERICH_CONFIG", "KUBERICH_LOG_FILE")
    result = run(
        [
            str(binary / "python"),
            "-c",
            "import json; from platformdirs import user_config_path; "
            "print(json.dumps([str(user_config_path(name, appauthor=False) / 'config.yaml') "
            "for name in ('kubetrol', 'kuberich')]))",
        ],
        tmp_path,
        10,
        environment=environment,
        unset_environment=unset,
    )
    source, destination = (Path(value) for value in json.loads(result.stdout))
    assert source.is_relative_to(home) and destination.is_relative_to(home)
    source.parent.mkdir(parents=True)
    original = b"readonly: true\nrefresh: 3.5\nopaque-private-field: owned-private-value\n"
    source.write_bytes(original)
    command = [str(binary / executable)]
    before = run([*command, "info"], tmp_path, 10, environment=environment, unset_environment=unset)
    data = json.loads(before.stdout)
    assert data["config_file"] == str(source) and data["migration_pending"]
    assert "owned-private-value" not in before.stdout + before.stderr
    assert not destination.exists()
    migrated = run(
        [*command, "config", "migrate"],
        tmp_path,
        10,
        environment=environment,
        unset_environment=unset,
    )
    assert "Original Kubetrol preferences were retained" in migrated.stdout
    assert source.read_bytes() == original
    assert "opaque-private-field: owned-private-value" in destination.read_text()
    after = run([*command, "info"], tmp_path, 10, environment=environment, unset_environment=unset)
    data = json.loads(after.stdout)
    assert data["config_file"] == str(destination) and not data["migration_pending"]
    assert data["preferences"]["read_only"] and data["preferences"]["refresh_seconds"] == 3.5
    assert "owned-private-value" not in after.stdout + after.stderr


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


@pytest.mark.parametrize("scenario", ["always", "never", "cancel"])
def test_installed_generic_login_keeps_declared_input_mode_and_restores_tty(
    installed_wheel, scenario
):
    binary_dir, directory = installed_wheel
    credential_terminal_trial(
        str(binary_dir / "python"), directory, scenario, name=f"installed-generic-login-{scenario}"
    )


@pytest.mark.asyncio
async def test_installed_encrypted_key_refuses_without_native_password_prompt(installed_wheel):
    binary, directory = installed_wheel
    called = []

    async def handler(request):
        called.append(True)
        raise AssertionError("Rejected client key cannot make an API request.")

    async with fake_api(handler) as server:
        await asyncio.to_thread(
            encrypted_key_terminal_trial,
            str(binary / "python"),
            directory,
            server,
            name="installed-encrypted-key",
        )
    assert not called


def test_installed_selected_container_shell_uses_real_cli(installed_wheel) -> None:
    binary_dir, directory = installed_wheel
    terminal_shell(
        [str(binary_dir / "kuberich")], directory, "success", evidence="installed-container-shell"
    )


@pytest.mark.parametrize("kind", ["ssh", "ssh_tmux"])
def test_installed_wheel_embedded_protocol_over_real_transport(installed_wheel, tmp_path, kind):
    binary_dir, _ = installed_wheel
    with TerminalTransport(tmp_path / "transport", kind) as transport:
        terminal_shell(
            [str(binary_dir / "kuberich")],
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
    source = next(tmp_path.glob("kuberich-*"))
    assert (source / "src/kuberich/py.typed").is_file()
    assert (source / "src/kuberich/ui/kuberich.tcss").is_file()
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
        command = [str(binary_dir / ("kuberich.exe" if sys.platform == "win32" else "kuberich"))]
    else:
        command = [
            str(binary_dir / ("python.exe" if sys.platform == "win32" else "python")),
            "-m",
            "kuberich",
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
        assert output.stdout == f"kuberich {PROJECT['version']}\n"
    elif argument == "--help":
        assert "usage: kuberich" in output.stdout
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
        "print(json.dumps({'version': m.version('kuberich'), "
        "'typed': r.files('kuberich').joinpath('py.typed').is_file(), "
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
    command = [str(binary_dir / "kuberich"), "--config", str(tmp_path / "preferences.yaml")]
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
        [str(binary_dir / "kuberich")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kuberich"]
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
    output = run([str(binary_dir / "kuberich"), *arguments], directory, 10, check=False)
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
        directory, [str(binary_dir / "kuberich")], evidence="installed-connection-overrides"
    )


def test_installed_initial_help_and_visibility_options_restore_tty(
    installed_wheel: tuple[Path, Path],
) -> None:
    binary_dir, directory = installed_wheel
    command = [str(binary_dir / "kuberich"), "--logoless", "--crumbsless", "--command", "help"]
    with TerminalSession(command, directory) as terminal:
        terminal.wait_for(b"Keyboard help")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("installed-launch-help")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_navigation_and_initial_namespace_outside_checkout(installed_wheel, entry_point):
    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kuberich")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kuberich"]
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
            [str(binary_dir / "kuberich"), "--kubeconfig", str(path), "--request-timeout", "250ms"],
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
        [str(binary_dir / "kuberich")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kuberich"]
    )
    terminal_inspection(command, directory, evidence=f"installed-inspection-{entry_point}")


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_log_viewer_outside_checkout(installed_wheel, entry_point):
    from tests.support.log_viewer import terminal_logs

    binary_dir, directory = installed_wheel
    command = (
        [str(binary_dir / "kuberich")]
        if entry_point == "console"
        else [str(binary_dir / "python"), "-m", "kuberich"]
    )
    terminal_logs(command, directory, evidence=f"installed-log-viewer-{entry_point}")
