"""Crash bundles expose safe metadata and only a limited application-log tail."""

import io
import json
import linecache
import os
import stat
from pathlib import Path

import pytest

from kuberich.diagnostics import reports
from kuberich.diagnostics.logging import LOG_HEADER, diagnostic_logging
from kuberich.diagnostics.reports import MAX_LOG_TAIL, write_report
from kuberich.errors import AppError, ExitCode


def report_at(directory, **options):
    destination = directory / "report.json"
    assert write_report(output=destination, **options) == destination
    return json.loads(destination.read_text())


def test_private_bundle_contains_metadata_and_the_actual_logger_redacts_values(tmp_path):
    log = tmp_path / "diagnostic.log"
    with diagnostic_logging(log, "DEBUG") as logger:
        logger.warning("token=secret-log-marker Authorization: Bearer private-credential")
        logger.info("safe diagnostic event")
    value = report_at(tmp_path, config_status="valid", log_path=log)
    assert stat.S_IMODE((tmp_path / "report.json").stat().st_mode) == 0o600
    assert set(value) == {
        "schema_version",
        "version",
        "python",
        "platform",
        "terminal",
        "config_check",
        "recent_log",
    }
    assert value["schema_version"] == 1 and value["version"] and value["python"]
    assert value["config_check"] == "valid"
    assert value["recent_log"]["status"] == "included"
    assert "safe diagnostic event" in value["recent_log"]["text"]
    assert "REDACTED" in value["recent_log"]["text"]
    serialized = json.dumps(value)
    assert "secret-log-marker" not in serialized and "private-credential" not in serialized
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize("kind", ["regular", "symlink", "dangling", "fifo", "directory"])
def test_destination_refuses_existing_files_and_special_paths_without_changing_them(tmp_path, kind):
    destination = tmp_path / "existing"
    target = tmp_path / "target"
    target.write_text("unmodified private data")
    if kind == "regular":
        destination.write_text("keep existing report")
    elif kind == "symlink":
        destination.symlink_to(target)
    elif kind == "dangling":
        destination.symlink_to(tmp_path / "missing")
    elif kind == "fifo":
        os.mkfifo(destination)
    else:
        destination.mkdir()
    before = destination.lstat()
    with pytest.raises(AppError) as caught:
        write_report(config_status="missing", output=destination)
    assert caught.value.code == ExitCode.LOCAL_IO
    assert destination.lstat() == before
    assert target.read_text() == "unmodified private data"


@pytest.mark.parametrize("mask", [0, 0o077, 0o777])
def test_new_report_has_exact_private_permissions_under_any_umask(tmp_path, mask):
    previous = os.umask(mask)
    try:
        destination = write_report(config_status="unavailable", output=tmp_path / "report.json")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_automatic_reports_are_unique_private_and_use_the_selected_state_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(reports, "user_state_path", lambda *args, **kwargs: tmp_path / "state")
    first = write_report(config_status="invalid")
    second = write_report(config_status="missing")
    assert first != second and first.parent == second.parent == tmp_path / "state/reports"
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700
    for path in (first, second):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text())["recent_log"] == {"status": "unavailable"}


@pytest.mark.parametrize("kind", ["missing", "foreign", "symlink", "fifo", "directory"])
def test_report_does_not_read_foreign_missing_or_special_log_inputs(tmp_path, kind):
    source = tmp_path / "log"
    target = tmp_path / "private-config"
    target.write_text("secret-token-that-must-not-be-read")
    if kind == "foreign":
        source.write_text("password: secret-token-that-must-not-be-read")
    elif kind == "symlink":
        source.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "directory":
        source.mkdir()
    value = report_at(tmp_path, config_status="invalid", log_path=source)
    assert value["recent_log"] == {"status": "unavailable"}
    assert "secret-token-that-must-not-be-read" not in json.dumps(value)


def test_a_regular_log_owned_by_another_user_is_rejected_before_read(tmp_path, monkeypatch):
    source = tmp_path / "log"
    source.write_bytes(LOG_HEADER + b"must not read this body\n")
    real_fstat = os.fstat

    def foreign_owner(descriptor):
        details = list(real_fstat(descriptor))
        details[4] = os.geteuid() + 1
        return os.stat_result(details)

    def forbidden_read(*args):
        pytest.fail("Foreign log owner must be rejected before reading a byte")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", foreign_owner)
        patch.setattr(os, "read", forbidden_read)
        value = report_at(tmp_path, config_status="valid", log_path=source)
    assert value["recent_log"] == {"status": "unavailable"}


@pytest.mark.parametrize("legacy", [False, True])
def test_recent_tail_drops_a_partial_record_limits_input_and_redacts_again(tmp_path, legacy):
    source = tmp_path / "log"
    header = LOG_HEADER.replace(b"KubeRich", b"Kubetrol") if legacy else LOG_HEADER
    source.write_bytes(
        header + b"a" * (MAX_LOG_TAIL * 2) + b"\nsafe current event\ntoken=private-tail-marker\n"
    )
    value = report_at(tmp_path, config_status="valid", log_path=source)
    tail = value["recent_log"]["text"]
    assert "safe current event" in tail and "REDACTED" in tail
    assert "private-tail-marker" not in tail and "aaaa" not in tail
    assert len(tail.encode()) < MAX_LOG_TAIL


def test_traceback_metadata_does_not_read_source_or_serialize_values_locals_or_chains(
    tmp_path, monkeypatch
):
    def source_lookup(*args, **kwargs):
        pytest.fail("Report frame metadata must not read source lines")

    try:
        private_local = "private-local-marker"
        try:
            raise ValueError("private-cause-marker")
        except ValueError as cause:
            raise RuntimeError("private-value-marker", private_local) from cause
    except RuntimeError as failure:
        monkeypatch.setattr(linecache, "getlines", source_lookup)
        value = report_at(tmp_path, config_status="valid", error=failure)
    assert value["failure"]["kind"] == "RuntimeError"
    assert value["failure"]["frames"]
    for frame in value["failure"]["frames"]:
        assert set(frame) == {"file", "line", "function"}
        assert frame["file"] == Path(__file__).name and isinstance(frame["line"], int)
    serialized = json.dumps(value)
    for forbidden in (
        "private-local-marker",
        "private-cause-marker",
        "private-value-marker",
        str(tmp_path),
    ):
        assert forbidden not in serialized


def test_frame_count_is_limited_and_unraised_errors_have_no_fabricated_frames(tmp_path):
    def nested(depth):
        if depth:
            return nested(depth - 1)
        raise RuntimeError("private deep exception")

    try:
        nested(50)
    except RuntimeError as error:
        value = report_at(tmp_path, config_status="valid", error=error)
    assert len(value["failure"]["frames"]) == 32
    second = tmp_path / "second"
    second.mkdir()
    assert (
        report_at(second, config_status="missing", error=RuntimeError("private"))["failure"][
            "frames"
        ]
        == []
    )


def test_terminal_metadata_uses_real_query_result_without_environment_or_paths(
    tmp_path, monkeypatch
):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("sys.stdout", Terminal())
    monkeypatch.setattr(os, "get_terminal_size", lambda: os.terminal_size((100, 35)))
    value = report_at(tmp_path, config_status="valid")
    assert value["terminal"] == {"stdin_tty": True, "stdout_tty": True, "columns": 100, "rows": 35}


@pytest.mark.parametrize("boundary", ["fdopen", "fchmod"])
def test_descriptor_and_new_file_are_cleaned_when_stream_setup_fails(
    tmp_path, monkeypatch, boundary
):
    descriptors = []

    def fail(descriptor, *args):
        descriptors.append(descriptor)
        raise OSError("private error details")

    destination = tmp_path / "report.json"
    with monkeypatch.context() as patch:
        patch.setattr(os, boundary, fail)
        with pytest.raises(AppError) as caught:
            write_report(config_status="valid", output=destination)
    assert "private error details" not in str(caught.value)
    assert len(descriptors) == 1 and not destination.exists()
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
