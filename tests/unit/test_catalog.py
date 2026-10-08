"""Read-only merge, path provenance and bounded kubeconfig parsing."""

import os
from pathlib import Path

import pytest
import yaml

from kuberich.config.catalog import KubeCatalog, load_catalog, regular_bytes
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest
from kuberich.errors import AppError


def fixture(path: Path, name: str = "one", **extra: object) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "current-context": name,
                "contexts": [{"name": name, "context": {"cluster": name, "user": name}}],
                "clusters": [{"name": name, "cluster": {"server": "http://127.0.0.1:12345"}}],
                "users": [{"name": name, "user": {"token": "synthetic"}}],
                **extra,
            }
        )
    )
    return path


def test_explicit_file_overrides_environment_and_preserves_source(tmp_path: Path) -> None:
    path = fixture(tmp_path / "chosen")
    before = path.read_bytes()
    catalog = load_catalog(ConnectionRequest(kubeconfig=str(path)), {"KUBECONFIG": "/never/read"})
    assert catalog.current == "one" and catalog.names == ("one",)
    selected = catalog.select("one")
    assert selected.namespace == "default" and selected.user.directory == tmp_path
    selected.user.data["token"] = "changed"
    assert catalog.select("one").user.data["token"] == "synthetic"
    assert path.read_bytes() == before


def test_merge_first_file_wins_for_current_and_whole_named_entries(tmp_path: Path) -> None:
    first = fixture(tmp_path / "first")
    other = fixture(tmp_path / "second", "two")
    duplicate = fixture(
        tmp_path / "duplicate", users=[{"name": "one", "user": {"token": "second"}}]
    )
    catalog = load_catalog(
        ConnectionRequest(),
        {
            "KUBECONFIG": os.pathsep.join(
                (str(first), "", str(first), str(other), str(duplicate), str(tmp_path / "absent"))
            )
        },
    )
    assert catalog.names == ("one", "two") and catalog.current == "one"
    assert catalog.select("one").user.data == {"token": "synthetic"}
    assert catalog.select("two").cluster.directory == tmp_path


def test_default_path_missing_is_disconnected_and_existing_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_catalog(ConnectionRequest(), {}).names == ()
    path = tmp_path / ".kube/config"
    path.parent.mkdir()
    fixture(path)
    assert load_catalog(ConnectionRequest(), {}).current == "one"


def test_first_nonempty_current_context_and_anonymous_context(tmp_path: Path) -> None:
    first = fixture(
        tmp_path / "empty-current",
        **{
            "current-context": "",
            "contexts": [{"name": "one", "context": {"cluster": "one", "namespace": "team"}}],
        },
    )
    second = fixture(tmp_path / "second", "two")
    catalog = load_catalog(ConnectionRequest(), {"KUBECONFIG": f"{first}{os.pathsep}{second}"})
    assert catalog.current == "two"
    assert catalog.select("one").user.data == {} and catalog.select("one").namespace == "team"


@pytest.mark.parametrize("contents", [b"", b"contexts: null\n"])
def test_empty_config_is_valid_but_not_connected(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "input"
    path.write_bytes(contents)
    assert load_catalog(ConnectionRequest(kubeconfig=str(path)), {}).names == ()


@pytest.mark.parametrize(
    "contents",
    [
        b"\xff",
        b"[bad",
        b"!unsafe x",
        b"[]",
        b"token: one\ntoken: two",
        b"1: value",
        b"x: &x [a]\ny: *x",
        b"x: " + b"[" * 31 + b"a" + b"]" * 31,
        b"x: [" + b"a," * 65537 + b"]",
        b"x" * (1024 * 1024 + 1),
        b"contexts: {}",
        b"contexts: [null]",
        b"contexts: [{name: x, context: {}}, {name: x, context: {}}]",
        b"contexts: [{name: 1, context: {}}]",
        b"current-context: 1",
        b"contexts: [{name: x, context: []}]",
        b"contexts: [{name: '', context: {}}]",
    ],
)
def test_ambiguous_or_invalid_configuration_never_executes(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "invalid"
    path.write_bytes(contents)
    with pytest.raises(AppError):
        load_catalog(ConnectionRequest(kubeconfig=str(path)), {})


def test_file_and_entry_limits(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="32"):
        load_catalog(
            ConnectionRequest(),
            {"KUBECONFIG": os.pathsep.join(str(tmp_path / str(i)) for i in range(33))},
        )
    path = fixture(
        tmp_path / "too-many", contexts=[{"name": str(i), "context": {}} for i in range(2049)]
    )
    with pytest.raises(AppError, match="2048"):
        load_catalog(ConnectionRequest(kubeconfig=str(path)), {})


def test_missing_explicit_file_and_non_regular_files_fail_safely(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="missing"):
        load_catalog(ConnectionRequest(kubeconfig=str(tmp_path / "absent")), {})
    path = tmp_path / "fifo"
    os.mkfifo(path)
    with pytest.raises(AppError, match="regular"):
        regular_bytes(path)
    with pytest.raises(AppError, match="regular"):
        load_catalog(ConnectionRequest(kubeconfig=str(tmp_path)), {})


@pytest.mark.parametrize(
    "context",
    [
        {"cluster": "missing"},
        {"cluster": "one", "user": "missing"},
        {"cluster": "one", "namespace": "INVALID"},
    ],
)
def test_context_reference_errors_do_not_fall_back(tmp_path: Path, context: dict) -> None:
    path = fixture(tmp_path / "references", contexts=[{"name": "one", "context": context}])
    catalog = load_catalog(ConnectionRequest(kubeconfig=str(path)), {})
    with pytest.raises((AppError, ConnectionProblem)):
        catalog.select("one")
    with pytest.raises(AppError):
        catalog.select("missing")
    assert KubeCatalog().names == ()


def test_merged_name_limit_applies_across_files(tmp_path: Path) -> None:
    first = fixture(
        tmp_path / "first", contexts=[{"name": str(i), "context": {}} for i in range(2048)]
    )
    second = fixture(tmp_path / "second", contexts=[{"name": "extra", "context": {}}])
    with pytest.raises(AppError, match="Merged"):
        load_catalog(ConnectionRequest(), {"KUBECONFIG": f"{first}{os.pathsep}{second}"})


def test_unreadable_descriptor_has_an_owned_local_io_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture(tmp_path / "unreadable")

    def denied(*args, **kwargs):
        raise PermissionError("opaque-private-path")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(AppError, match="Cannot read") as error:
        load_catalog(ConnectionRequest(kubeconfig=str(path)), {})
    assert error.value.code == 3 and "opaque-private" not in str(error.value)


def test_alias_overrides_select_merged_entries_without_rewriting_context(tmp_path):
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = fixture(
        first_dir / "config",
        contexts=[
            {
                "name": "one",
                "context": {"cluster": "missing", "user": "missing", "namespace": "team"},
            }
        ],
    )
    second = fixture(second_dir / "config", "two")
    before = (first.read_bytes(), second.read_bytes())
    catalog = load_catalog(ConnectionRequest(), {"KUBECONFIG": f"{first}{os.pathsep}{second}"})
    selected = catalog.select(
        "one", ConnectionOverrides(cluster="two", user="two", token="override")
    )
    assert selected.namespace == "team" and selected.name == "one"
    assert selected.cluster.directory == selected.user.directory == second_dir
    assert selected.user.data == {"token": "override"}
    selected.cluster.data["server"] = "changed"
    assert catalog.select("two").cluster.data["server"] == "http://127.0.0.1:12345"
    assert catalog.select("two").user.data == {"token": "synthetic"}
    assert (first.read_bytes(), second.read_bytes()) == before


@pytest.mark.parametrize(
    "overrides", [ConnectionOverrides(cluster="missing"), ConnectionOverrides(user="missing")]
)
def test_missing_override_alias_never_falls_back_to_context(tmp_path, overrides):
    catalog = load_catalog(ConnectionRequest(kubeconfig=str(fixture(tmp_path / "config"))), {})
    with pytest.raises((AppError, ConnectionProblem)):
        catalog.select("one", overrides)
