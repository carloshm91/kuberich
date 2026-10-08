"""Real temporary files and injected I/O failures verify safe loading and commits."""

import os
import stat
from pathlib import Path

import pytest

from kuberich.config.schema import ConfigDocument, Settings
from kuberich.config.store import MAX_CONFIG_BYTES, read_config, write_config
from kuberich.errors import AppError, ExitCode


def test_missing_file_defaults_are_read_only(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "config.yaml"
    assert read_config(path) == ConfigDocument()
    assert not path.parent.exists()
    with pytest.raises(AppError) as error:
        read_config(path, missing_ok=False)
    assert error.value.code == ExitCode.LOCAL_IO


@pytest.mark.parametrize("content", ["", "# empty preferences\n", "null\n"])
def test_empty_file_uses_current_defaults(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(content)
    assert read_config(path) == ConfigDocument()
    assert path.read_text() == content


def test_migration_and_unknown_fields_round_trip_through_atomic_save(tmp_path: Path) -> None:
    path = tmp_path / "nested space" / "config.yaml"
    path.parent.mkdir()
    original = "refresh: 4\nreadonly: true\nplugin: {name: value, future: [1, 2]}\n"
    path.write_text(original)
    document = read_config(path)
    assert document.migrated
    assert path.read_text() == original
    write_config(path, document, overwrite=True)
    restored = read_config(path)
    assert restored.settings == Settings(refresh_seconds=4.0, read_only=True)
    assert restored.unknown == {"plugin": {"name": "value", "future": [1, 2]}}
    assert not restored.migrated
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".kuberich-*.tmp"))


def test_initial_write_creates_private_directory_and_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "app" / "config.yaml"
    write_config(path, ConfigDocument())
    original = path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    with pytest.raises(AppError, match="already exist"):
        write_config(path, ConfigDocument(Settings(theme="other")))
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "content,message",
    [
        (b"schema_version: [", "Invalid YAML"),
        (b"\xff", "UTF-8"),
        (b"- theme\n- other", "YAML mapping"),
        (b"theme: textual-dark\ntheme: other", "unique strings"),
        (b"extra: {value: one, value: two}", "unique strings"),
        (b"2: value", "unique strings"),
        (b"? [one, two]\n: value", "unique strings"),
        (b"extra: &value {a: 1}\nother: *value", "aliases"),
        (b"extra: &recursive [*recursive]", "aliases"),
        (b"!!python/object/apply:os.system ['touch SHOULD-NOT-EXIST']", "Invalid YAML"),
        (b"---\n{}\n---\n{}", "Invalid YAML"),
        (("extra: " + "[" * 21 + "0" + "]" * 21).encode(), "nesting limit"),
        (("extra: [" + "0," * 5000 + "]").encode(), "size or nesting limit"),
        (b"extra: " + b"9" * 5000, "Invalid YAML"),
    ],
)
def test_malformed_or_unsafe_yaml_has_safe_errors(
    tmp_path: Path, content: bytes, message: str
) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(content)
    with pytest.raises(AppError, match=message) as error:
        read_config(path)
    assert error.value.code == ExitCode.INVALID_INPUT
    assert path.read_bytes() == content
    assert not (tmp_path / "SHOULD-NOT-EXIST").exists()


def test_read_and_write_reject_oversize_preferences(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"#" * (MAX_CONFIG_BYTES + 1))
    with pytest.raises(AppError, match="64 KiB"):
        read_config(path)
    path.unlink()
    with pytest.raises(AppError, match="64 KiB"):
        write_config(path, ConfigDocument(unknown={"large": "x" * MAX_CONFIG_BYTES}))
    assert not path.exists()


def test_directory_and_fifo_are_not_opened_as_preferences(tmp_path: Path) -> None:
    for path in [tmp_path, tmp_path / "fifo"]:
        if path != tmp_path:
            os.mkfifo(path)
        with pytest.raises(AppError, match="regular file"):
            read_config(path)


def test_dangling_preference_symlink_is_not_treated_as_missing_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.symlink_to(tmp_path / "missing.yaml")
    with pytest.raises(AppError, match="regular file"):
        read_config(path)


def test_read_permission_failure_has_no_raw_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.touch()

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("password=private-value")

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(AppError) as error:
        read_config(path)
    assert error.value.code == ExitCode.LOCAL_IO
    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("failure", [OSError("private data"), KeyboardInterrupt()])
def test_interrupted_replace_preserves_previous_file_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    path = tmp_path / "config.yaml"
    write_config(path, ConfigDocument())
    original = path.read_bytes()

    def interrupt(*args: object) -> None:
        raise failure

    monkeypatch.setattr(os, "replace", interrupt)
    expected = AppError if isinstance(failure, OSError) else KeyboardInterrupt
    with pytest.raises(expected):
        write_config(path, ConfigDocument(Settings(theme="changed")), overwrite=True)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".kuberich-*.tmp"))


def test_failed_file_sync_never_commits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.yaml"

    def failed_sync(descriptor: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", failed_sync)
    with pytest.raises(AppError, match="Cannot save"):
        write_config(path, ConfigDocument())
    assert not path.exists()
    assert not list(tmp_path.glob(".kuberich-*.tmp"))


def test_directory_sync_failure_reports_error_after_atomic_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_sync = os.fsync

    def failed_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("directory sync failed")
        original_sync(descriptor)

    monkeypatch.setattr(os, "fsync", failed_directory_sync)
    path = tmp_path / "config.yaml"
    with pytest.raises(AppError, match="Preferences were saved"):
        write_config(path, ConfigDocument())
    assert read_config(path) == ConfigDocument()
    assert not list(tmp_path.glob(".kuberich-*.tmp"))


def test_create_race_does_not_overwrite_the_other_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    original_link = os.link

    def racing_link(source: Path, destination: Path) -> None:
        destination.write_text("theme: race-winner\n")
        original_link(source, destination)

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(AppError, match="Cannot save"):
        write_config(path, ConfigDocument())
    assert path.read_text() == "theme: race-winner\n"
    assert not list(tmp_path.glob(".kuberich-*.tmp"))


def test_symbolic_link_and_kubeconfig_writes_are_refused(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    original = "current-context: fixture\nusers: []\nclusters: []\ncontexts: []\n"
    kubeconfig.write_text(original)
    link = tmp_path / "preferences-link"
    link.symlink_to(kubeconfig)
    with pytest.raises(AppError, match="symbolic link"):
        write_config(link, ConfigDocument(), overwrite=True)
    with pytest.raises(AppError, match="This is a kubeconfig"):
        write_config(kubeconfig, ConfigDocument(), overwrite=True)
    assert kubeconfig.read_text() == original


def test_unrepresentable_unknown_value_does_not_create_files(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    with pytest.raises(AppError, match="safe YAML"):
        write_config(path, ConfigDocument(unknown={"extra": object()}))
    assert not path.exists()


def test_temporary_stream_failure_closes_descriptor_and_removes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[int] = []

    def failed(descriptor: int, *args: object, **kwargs: object) -> None:
        captured.append(descriptor)
        raise OSError("stream initialization failed")

    monkeypatch.setattr(os, "fdopen", failed)
    with pytest.raises(AppError, match="Cannot save"):
        write_config(tmp_path / "config.yaml", ConfigDocument())
    assert not list(tmp_path.glob(".kuberich-*.tmp"))
    with pytest.raises(OSError):
        os.fstat(captured[0])
