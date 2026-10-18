"""Actual explicit plugin files, bounded discovery and offline CLI validation."""

import os
from dataclasses import replace

import pytest
import yaml

from kuberich.adapters.plugin_files import _file, load_plugins
from kuberich.cli import main
from kuberich.config.plugins import PluginLayer, PluginPreferences, parse_plugins
from kuberich.errors import AppError
from tests.unit.test_plugins import definition, plugin


def write(path, commands=None, **extension):
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "plugins": {
                    "schema_version": 1,
                    "commands": commands or {"inspect": definition()},
                    **extension,
                },
            }
        )
    )
    return path


def preferences(directory, **raw):
    return parse_plugins({"schema_version": 1, **raw}, directory)


def test_explicit_files_directories_context_shadowing_and_no_ambient_loading(tmp_path, monkeypatch):
    unrelated = tmp_path / "cwd"
    unrelated.mkdir()
    write(unrelated / "plugins.yaml", {"ambient": definition(command="never")})
    monkeypatch.chdir(unrelated)
    assert load_plugins(PluginPreferences(), "demo") == ()
    folder = tmp_path / "configured"
    folder.mkdir()
    write(folder / "b.yml", {"inspect": definition(command="from-file", directory="work")})
    (folder / "ignored.txt").write_text("not a plugin")
    write(folder / "a.yaml", {"other": definition()})
    scoped = tmp_path / "context.yaml"
    write(scoped, {"inspect": definition(command="context-tool")})
    configured = preferences(
        tmp_path, locations=["configured"], contexts={"demo": {"locations": [str(scoped)]}}
    )
    global_commands = load_plugins(configured, None)
    assert [item.name for item in global_commands] == ["inspect", "other"]
    assert global_commands[0].directory == folder / "work"
    assert load_plugins(configured, "unknown") == global_commands
    assert load_plugins(configured, "demo")[0].command == "context-tool"
    assert load_plugins(configured, "demo")[0].directory == tmp_path


@pytest.mark.parametrize(
    "content",
    [
        b"\xff",
        b"x" * 65537,
        b"[not a mapping]",
        b"plugins: [bad]",
        b"plugins: {}",
        b"plugins: {schema_version: true}",
        b"plugins: {schema_version: 1, contexts: {}}",
        b"plugins: {schema_version: 1, locations: []}",
        b"plugins: &a {commands: *a}",
        b"plugins: {schema_version: 1, commands: {a: {command: one}, a: {command: two}}}",
        b"plugins: {schema_version: 1, commands: {a: {command: [bad]}}}",
    ],
)
def test_malformed_private_files_fail_with_safe_actionable_messages(tmp_path, content):
    path = tmp_path / "plugin.yaml"
    path.write_bytes(content)
    with pytest.raises(AppError, match=r"[Pp]lugin|YAML|Preference"):
        load_plugins(preferences(tmp_path, locations=[str(path)]), None)


def test_missing_symlink_fifo_and_yaml_directory_are_never_followed(tmp_path):
    missing = tmp_path / "absent"
    symlink = tmp_path / "linked.yaml"
    symlink.symlink_to(write(tmp_path / "real.yaml"))
    directory = tmp_path / "directory.yaml"
    directory.mkdir()
    fifo = tmp_path / "fifo.yaml"
    os.mkfifo(fifo)
    for path in (missing, symlink, fifo):
        with pytest.raises(AppError):
            load_plugins(preferences(tmp_path, locations=[str(path)]), None)
    # A directory entry ending in YAML must not become an implicit recursive search.
    with pytest.raises(AppError):
        _file(directory)
    configured = tmp_path / "with-link"
    configured.mkdir()
    (configured / "unsafe.yaml").symlink_to(tmp_path / "real.yaml")
    with pytest.raises(AppError):
        load_plugins(preferences(tmp_path, locations=[str(configured)]), None)


def test_empty_file_and_external_recursive_locations_are_rejected(tmp_path):
    path = tmp_path / "plugin.yaml"
    path.write_text("")
    with pytest.raises(AppError):
        _file(path)
    write(path, locations=["another.yaml"])
    with pytest.raises(AppError, match="External"):
        _file(path)
    path.write_text("schema_version: 1\nplugins: {schema_version: 1}\n")
    assert _file(path) == ()


def test_duplicate_names_limits_and_scope_aware_key_collisions(tmp_path):
    first = write(tmp_path / "one.yaml")
    second = write(tmp_path / "two.yaml")
    with pytest.raises(AppError, match="Duplicate"):
        load_plugins(preferences(tmp_path, locations=[str(first), str(second)]), None)
    with pytest.raises(AppError, match="Duplicate"):
        load_plugins(
            preferences(tmp_path, commands={"inspect": definition()}, locations=[str(first)]), None
        )
    folder = tmp_path / "many-files"
    folder.mkdir()
    for index in range(17):
        write(folder / f"{index}.yaml")
    with pytest.raises(AppError, match="16"):
        load_plugins(preferences(tmp_path, locations=[str(folder)]), None)
    large = tmp_path / "many-entries"
    large.mkdir()
    for index in range(129):
        (large / str(index)).touch()
    with pytest.raises(AppError, match="128"):
        load_plugins(preferences(tmp_path, locations=[str(large)]), None)
    base = {f"plugin{i}": definition() for i in range(64)}
    with pytest.raises(AppError, match="64"):
        load_plugins(preferences(tmp_path, commands=base, locations=[str(first)]), None)
    with pytest.raises(AppError, match="64"):
        load_plugins(
            preferences(
                tmp_path, commands=base, contexts={"demo": {"commands": {"inspect": definition()}}}
            ),
            "demo",
        )
    assert len(load_plugins(preferences(tmp_path, commands=base), None)) == 64
    collision = preferences(
        tmp_path,
        commands={
            "one": definition(shortcut="a"),
            "two": definition(shortcut="a", scopes=["v1/pods"]),
        },
    )
    with pytest.raises(AppError, match="conflicting"):
        load_plugins(collision, None)
    with pytest.raises(AppError, match="override"):
        load_plugins(preferences(tmp_path, commands={"inspect": definition(shortcut="j")}), None)


def test_directory_permissions_and_file_errors_are_translated(tmp_path, monkeypatch):
    configured = preferences(tmp_path, locations=[str(tmp_path)])

    def denied(*args, **kwargs):
        raise PermissionError("private-detail")

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(AppError, match="enumerate") as error:
        load_plugins(configured, None)
    assert "private-detail" not in str(error.value)
    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(AppError, match="configured plugin file") as error:
        _file(tmp_path / "file.yaml")
    assert "private-detail" not in str(error.value)


def test_offline_cli_validates_every_context_and_does_not_execute(tmp_path, capsys):
    sentinel = tmp_path / "never-executed"
    config = tmp_path / "config.yaml"
    write(config, {"inspect": {"command": "/usr/bin/touch", "args": [str(sentinel)]}})
    original = config.read_bytes()
    assert main(["--config", str(config), "config", "check"]) == 0
    assert "valid" in capsys.readouterr().out and not sentinel.exists()
    assert config.read_bytes() == original
    write(config, contexts={"unused": {"commands": {"invalid": definition(shortcut="j")}}})
    assert main(["--config", str(config), "config", "check"]) != 0
    assert "override" in capsys.readouterr().err and not sentinel.exists()
    # Local diagnostics must remain usable without accessing invalid plugin paths.
    write(config, locations=[str(tmp_path / "missing.yaml")])
    assert main(["--config", str(config), "info"]) == 0
    assert '"cluster_connected": false' in capsys.readouterr().out


def test_context_rename_references_are_local_and_do_not_change_the_manifest(tmp_path):
    first = plugin(shortcut="a", scopes=["v1/pods"])
    second = replace(first, name="other", scopes=("v1/services",))
    preferences_value = PluginPreferences(PluginLayer((first, second)))
    assert load_plugins(preferences_value, "renamed") == (first, second)
