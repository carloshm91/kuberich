"""Captured copy paths, scopes, permissions and literal process decisions."""

from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessResult, ProcessStatus
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.transfers import (
    TransferDirection,
    TransferIntent,
    download_arguments,
    remote_exec,
    remote_path,
    remote_test_result,
    transfer_command,
    upload_arguments,
    utf8_size,
    validate_pax_records,
)
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService


def target(**changes):
    return replace(
        ResourceTarget(SessionIdentity("owned", 7), "", "pods", "team", "api", "uid", "app"),
        **changes,
    )


def intent(tmp_path, direction=TransferDirection.DOWNLOAD, **changes):
    return replace(
        TransferIntent(direction, target(), tmp_path / "local", PurePosixPath("/tmp/a b;literal")),
        **changes,
    )


@pytest.mark.parametrize(
    "direction,purpose",
    [
        (TransferDirection.UPLOAD, ProcessPurpose.UPLOAD),
        (TransferDirection.DOWNLOAD, ProcessPurpose.DOWNLOAD),
    ],
)
def test_copy_scope_and_purpose_are_captured_literal_and_immutable(tmp_path, direction, purpose):
    value = intent(tmp_path, direction)
    config = tmp_path / "owned config"
    environment = {"PATH": "captured", "KUBECONFIG": "wrong"}
    args = (
        download_arguments(value)
        if direction is TransferDirection.DOWNLOAD
        else upload_arguments(value, tmp_path / "snapshot")
    )
    command = transfer_command(
        value,
        config,
        args,
        environment=environment,
        directory=tmp_path,
        mode=ProcessMode.BACKGROUND,
    )
    environment["PATH"] = "changed"
    assert command.argv[:4] == (
        "kubectl",
        f"--kubeconfig={config}",
        "--context=owned",
        "--namespace=team",
    )
    assert command.target == value.target and command.purpose is purpose
    assert command.mode is ProcessMode.BACKGROUND
    assert dict(command.environment) == {"PATH": "captured", "KUBECONFIG": str(config)}
    assert "sh" not in command.argv and "-c" not in command.argv
    if direction is TransferDirection.DOWNLOAD:
        assert command.argv[4:] == (
            "exec",
            "--container=app",
            "api",
            "--",
            "tar",
            "cf",
            "-",
            "-C",
            "/tmp",
            "--",
            "a b;literal",
        )
        AccessPolicy(True).require(command.purpose.action)
    else:
        assert command.argv[4:] == (
            "cp",
            "--retries=0",
            "--no-preserve",
            "--container=app",
            str(tmp_path / "snapshot"),
            "team/api:/tmp/a b;literal",
        )
        with pytest.raises(AppError, match="Read-only"):
            AccessPolicy(True).require(command.purpose.action)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "relative",
        "/",
        "/tmp/",
        "/tmp//x",
        "/tmp/./x",
        "/tmp/../x",
        "/x\x1b",
        "/tmp/\udcff",
        "/" + "a" * 4097,
        "/" + "/".join(["a"] * 33),
    ],
)
def test_remote_paths_refuse_ambiguous_unbounded_and_control_values(value):
    with pytest.raises(AppError):
        remote_path(value)


def test_remote_paths_allow_spaces_unicode_colons_and_literal_shell_characters():
    assert str(remote_path("/tmp/-c café:$()")) == "/tmp/-c café:$()"


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "download"},
        {"target": target(group="apps")},
        {"target": target(resource="services")},
        {"target": target(namespace=None)},
        {"target": target(container=None)},
        {"local": "absolute"},
        {"local": Path("relative")},
        {"local": Path("/")},
        {"local": Path("/tmp/..")},
        {"overwrite": 1},
    ],
)
def test_copy_intent_rejects_missing_or_ambiguous_scope_and_effect(tmp_path, changes):
    with pytest.raises(AppError):
        intent(tmp_path, **changes)


def test_builders_require_absolute_unambiguous_private_paths(tmp_path):
    value = intent(tmp_path)
    with pytest.raises(AppError, match="absolute"):
        transfer_command(
            value,
            Path("relative"),
            remote_exec(value, ("test", "-e", "/tmp/x")),
            environment={},
            directory=tmp_path,
        )
    with pytest.raises(AppError, match="absolute"):
        upload_arguments(value, Path("relative"))
    with pytest.raises(AppError, match="colons"):
        upload_arguments(value, tmp_path / "a:b")
    assert (
        transfer_command(
            value, tmp_path / "cfg", ("version",), environment={}, directory=tmp_path
        ).mode
        is ProcessMode.CAPTURE
    )


def test_copy_commands_preserve_download_in_readonly_and_gate_upload():
    readonly = CommandService(AccessPolicy(True))
    assert readonly.resolve(":download") is Command.DOWNLOAD
    with pytest.raises(AppError, match="Read-only"):
        readonly.resolve(":upload")
    assert CommandService(AccessPolicy(False)).resolve(":upload") is Command.UPLOAD


def test_transfer_paths_refuse_non_utf8_local_or_remote_text(tmp_path):
    with pytest.raises(AppError):
        remote_path("/tmp/\udcff")
    with pytest.raises(AppError):
        intent(tmp_path, local=tmp_path / "\udcff")
    with pytest.raises(AppError, match="UTF-8"):
        utf8_size("\udcff")


@pytest.mark.parametrize(
    "result,expected",
    [
        ((ProcessStatus.SUCCEEDED, 0, b"", b""), True),
        ((ProcessStatus.FAILED, 1, b"", b"command terminated with exit code 1\n"), False),
    ],
)
def test_remote_predicate_distinguishes_confirmed_true_and_false(result, expected):
    assert remote_test_result(ProcessResult(*result)) is expected


@pytest.mark.parametrize(
    "result",
    [
        (ProcessStatus.FAILED, 1, b"", b"Error from server (Forbidden): synthetic-private"),
        (ProcessStatus.FAILED, 1, b"", b"executable file not found in PATH"),
        (ProcessStatus.FAILED, 1, b"", b""),
        (ProcessStatus.FAILED, 127, b"", b"command terminated with exit code 127\n"),
        (ProcessStatus.FAILED, 1, b"unknown", b"command terminated with exit code 1\n"),
        (ProcessStatus.SUCCEEDED, 0, b"unknown", b""),
        (ProcessStatus.SUCCEEDED, 0, b"", b"unknown"),
        (ProcessStatus.SUCCEEDED, 1, b"", b""),
        (ProcessStatus.TIMED_OUT, 1, b"", b"command terminated with exit code 1\n"),
    ],
)
def test_remote_exec_failure_is_never_interpreted_as_absent_destination(result):
    with pytest.raises(AppError, match="Remote path check") as error:
        remote_test_result(ProcessResult(*result))
    assert "synthetic-private" not in str(error.value)


def pax_record(key, value):
    body = key + b"=" + value + b"\n"
    length = len(body) + 2
    while len(str(length)) + 1 + len(body) != length:
        length = len(str(length)) + 1 + len(body)
    return str(length).encode() + b" " + body


def test_pax_metadata_accepts_bounded_ordinary_fields_and_multiple_records():
    validate_pax_records(b"")
    validate_pax_records(pax_record(b"path", b"root/caf\xc3\xa9") + pax_record(b"mtime", b"123.4"))
    validate_pax_records(pax_record(b"size", b"0") + pax_record(b"size", b"536870912"))


@pytest.mark.parametrize("size", [b"bad", b"", b"-1", b"1.5", b"9" * 11, b"536870913"])
def test_pax_payload_size_cannot_be_coerced_or_exceed_the_transfer_bound(size):
    with pytest.raises(AppError, match="extended payload size"):
        validate_pax_records(pax_record(b"size", size))


@pytest.mark.parametrize(
    "data",
    [
        b"bad",
        b"1234567 path=x\n",
        b"a path=x\n",
        b" path=x\n",
        b"99 path=x\n",
        b"0 path=x\n",
        b"12 path=x!",
        b"13 pathvalue\n",
        pax_record(b"GNU.sparse.map", b"0,512"),
        pax_record(b"GNU.sparse.major", b"1"),
        pax_record(b"SCHILY.xattr.private", b"ignored"),
    ],
)
def test_sparse_unknown_and_malformed_pax_is_rejected_before_tarfile(data):
    with pytest.raises(AppError):
        validate_pax_records(data)
