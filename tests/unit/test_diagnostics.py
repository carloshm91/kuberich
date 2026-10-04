"""Sensitive fixture strings, terminal escapes, rotation, and file failure paths."""

import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kubetrol.diagnostics.logging import (
    LOG_BACKUPS,
    LOG_HEADER,
    MAX_LOG_BYTES,
    MAX_RECORD_BYTES,
    SanitizedFormatter,
    diagnostic_logging,
)
from kubetrol.diagnostics.redaction import sanitize_text
from kubetrol.errors import AppError, ExitCode


@pytest.mark.parametrize(
    "message,secret",
    [
        ("Authorization: Bearer super-private-token", "super-private-token"),
        ("Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
        ("https://username:private-password@example.test/path", "private-password"),
        ("eyJhbGciOiJub25lIn0.eyJzdWIiOiJmaXh0dXJlIn0.signature", "signature"),
        ("AWS key AKIA1234567890ABCDEF", "AKIA1234567890ABCDEF"),
        ("session ASIA1234567890ABCDEF", "ASIA1234567890ABCDEF"),
        ('{"token": "sensitive value with spaces"}', "sensitive value with spaces"),
        ('token="unterminated sensitive value', "unterminated sensitive value"),
        ("password='unterminated sensitive value", "unterminated sensitive value"),
        ("password='sensitive value with spaces'", "sensitive value with spaces"),
        ("?access_token=private-token&next=true", "private-token"),
        ("AWS_SECRET_ACCESS_KEY=private-key", "private-key"),
        ("client-key=private-key", "private-key"),
        ("client-certificate-data: private-cert", "private-cert"),
        ("certificate-authority-data=private-ca", "private-ca"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nprivate-material\n-----END RSA PRIVATE KEY-----",
            "private-material",
        ),
        ("-----BEGIN PRIVATE KEY-----\nprivate-material", "private-material"),
    ],
)
def test_common_credentials_are_removed(message: str, secret: str) -> None:
    result = sanitize_text(message)
    assert secret not in result
    assert "REDACTED" in result


def test_terminal_controls_are_inert_and_plain_unicode_is_preserved() -> None:
    result = sanitize_text("pod 🚀\x1b]52;c;clipboard\x07\n\r\x85\u202eunsafe\u2066")
    assert result.startswith("pod 🚀\\u001b")
    assert "\\u0007" in result and "\\u000a" in result and "\\u0085" in result
    assert "\\u202e" in result and "\\u2066" in result
    assert not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in result)
    assert sanitize_text("ordinary pod names 你好") == "ordinary pod names 你好"


def test_truncated_credential_is_still_redacted() -> None:
    result = sanitize_text("password=" + "private" * 20000)
    assert result == "password=[REDACTED]"


def test_long_nonsecret_word_is_bounded_and_preserved() -> None:
    assert sanitize_text("x" * 100000) == "x" * 65536


def test_logger_has_no_console_handler_does_not_mutate_root_and_closes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root_handlers = logging.getLogger().handlers.copy()
    path = tmp_path / "logs" / "kubetrol.log"
    with diagnostic_logging(path, "DEBUG") as logger:
        handler = logger.handlers[0]
        logger.warning("token=%s", "sensitive-fixture")
        logger.debug("plain message")
        assert not logger.propagate
    assert logging.getLogger().handlers == root_handlers
    assert handler.stream is None
    assert logger.handlers == []
    output = capsys.readouterr()
    assert output.out == output.err == ""
    contents = path.read_text()
    assert contents.startswith(LOG_HEADER.decode())
    assert "plain message" in contents and "sensitive-fixture" not in contents
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_debug_exception_has_locations_without_values_source_locals_or_stack_info(
    tmp_path: Path,
) -> None:
    path = tmp_path / "diagnostics.log"
    with diagnostic_logging(path, "DEBUG") as logger:
        try:
            raise ValueError("opaque-secret-without-a-recognizable-label")
        except ValueError:
            logger.debug("operation failed", exc_info=True, stack_info=True)
    contents = path.read_text()
    assert "exception=ValueError" in contents
    assert "test_diagnostics.py:" in contents
    assert "opaque-secret" not in contents and "raise ValueError" not in contents
    assert "Stack (most recent call last)" not in contents


def test_formatter_handles_empty_exception_tuple_and_bounds_multibyte_records() -> None:
    formatter = SanitizedFormatter()
    record = logging.LogRecord(
        "owned", logging.ERROR, __file__, 1, "你好" * 5000, (), (None, None, None)
    )
    result = formatter.format(record)
    assert len(result.encode()) <= MAX_RECORD_BYTES
    assert "你好" in result
    record = logging.LogRecord(
        "owned", logging.ERROR, __file__, 1, "failed", (), (None, None, None)
    )
    assert "exception=unknown" in formatter.format(record)


def test_rotation_bounds_files_and_retains_recent_messages_with_private_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "kubetrol.log"
    with diagnostic_logging(path, "INFO") as logger:
        for index in range(700):
            logger.info("message-%s %s token=secret-fixture", index, "x" * 8000)
    logs = sorted(item for item in tmp_path.glob("kubetrol.log*") if item.suffix != ".lock")
    assert len(logs) == LOG_BACKUPS + 1
    assert "message-699" in path.read_text()
    assert "message-0 " not in "".join(item.read_text() for item in logs)
    for item in logs:
        assert item.stat().st_size <= MAX_LOG_BYTES + MAX_RECORD_BYTES
        assert stat.S_IMODE(item.stat().st_mode) == 0o600
        assert "secret-fixture" not in item.read_text()
        assert item.read_bytes().startswith(LOG_HEADER)


def test_existing_owned_log_is_appended_and_permissions_are_restricted(tmp_path: Path) -> None:
    path = tmp_path / "existing.log"
    path.write_bytes(LOG_HEADER + b"old message\n")
    path.chmod(0o644)
    with diagnostic_logging(path, "WARNING") as logger:
        logger.warning("new message")
    assert "old message" in path.read_text() and "new message" in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_rotation_reopens_existing_owned_archives(tmp_path: Path) -> None:
    path = tmp_path / "existing.log"
    for index in range(1, LOG_BACKUPS + 1):
        path.with_name(f"{path.name}.{index}").write_bytes(LOG_HEADER + b"archive\n")
    with diagnostic_logging(path, "INFO") as logger:
        logger.info("recent message")
    assert "recent message" in path.read_text()


@pytest.mark.parametrize("kind", ["foreign", "symlink", "fifo"])
def test_foreign_or_special_archives_are_never_rotated(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "kubetrol.log"
    archive = tmp_path / "kubetrol.log.1"
    original = "current-context: protected-fixture\n"
    other = tmp_path / "kubeconfig"
    other.write_text(original)
    if kind == "foreign":
        archive.write_text(original)
    elif kind == "symlink":
        archive.symlink_to(other)
    else:
        os.mkfifo(archive)
    with pytest.raises(AppError, match="Cannot open"), diagnostic_logging(path, "INFO"):
        pytest.fail("Unsafe archive was accepted")
    assert other.read_text() == original
    if kind == "foreign":
        assert archive.read_text() == original


def test_only_one_process_can_own_a_log_path_and_lock_is_released(tmp_path: Path) -> None:
    path = tmp_path / "kubetrol.log"
    with diagnostic_logging(path, "INFO"):
        with (
            pytest.raises(AppError, match="another Kubetrol process"),
            diagnostic_logging(path, "INFO"),
        ):
            pytest.fail("Second owner was accepted")
        with diagnostic_logging(tmp_path / "independent.log", "INFO") as logger:
            logger.info("independent session")
    with diagnostic_logging(path, "INFO") as logger:
        logger.info("lock released")
    assert "lock released" in path.read_text()
    assert stat.S_IMODE(path.with_name(f"{path.name}.lock").stat().st_mode) == 0o600


def test_foreign_lock_file_is_not_modified(tmp_path: Path) -> None:
    lock = tmp_path / "kubetrol.log.lock"
    lock.write_text("current-context: keep\n")
    with (
        pytest.raises(AppError, match="Cannot open"),
        diagnostic_logging(tmp_path / "kubetrol.log", "INFO"),
    ):
        pytest.fail("Foreign lock was accepted")
    assert lock.read_text() == "current-context: keep\n"


def test_log_lock_excludes_a_real_second_process_and_allows_reuse(tmp_path: Path) -> None:
    path = tmp_path / "shared.log"
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from kubetrol.diagnostics.logging import diagnostic_logging\n"
        "from kubetrol.errors import AppError\n"
        "try:\n"
        "    with diagnostic_logging(Path(sys.argv[1]), 'INFO') as logger:\n"
        "        logger.info('child process acquired lock')\n"
        "except AppError as error:\n"
        "    print(str(error), file=sys.stderr)\n"
        "    sys.exit(error.code)\n"
    )
    with diagnostic_logging(path, "INFO"):
        denied = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert denied.returncode == 3
    assert "another Kubetrol process" in denied.stderr
    allowed = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert allowed.returncode == 0 and allowed.stderr == ""
    assert "child process acquired lock" in path.read_text()


def test_stream_initialization_failure_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise OSError("stream initialization failed")

    monkeypatch.setattr(os, "fdopen", failed)
    with pytest.raises(AppError, match="Cannot open"), diagnostic_logging(tmp_path / "log", "INFO"):
        pytest.fail("Stream failure was ignored")


def test_invalid_logger_level_fails_before_creating_files(tmp_path: Path) -> None:
    with (
        pytest.raises(AppError, match="log_level"),
        diagnostic_logging(tmp_path / "logs/log", "invalid"),
    ):
        pytest.fail("Invalid logger level was accepted")
    assert not (tmp_path / "logs").exists()


def test_root_directory_cannot_be_selected_as_a_log_file() -> None:
    with (
        pytest.raises(AppError, match="must name a file") as error,
        diagnostic_logging(Path("/"), "INFO"),
    ):
        pytest.fail("Root directory was accepted")
    assert error.value.code == ExitCode.LOCAL_IO


def test_logs_refuse_foreign_files_symlinks_directories_and_fifos(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    original = "current-context: protected-fixture\n"
    kubeconfig.write_text(original)
    link = tmp_path / "linked.log"
    link.symlink_to(kubeconfig)
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)
    for path in [kubeconfig, link, tmp_path, fifo]:
        with (
            pytest.raises(AppError, match="Cannot open") as error,
            diagnostic_logging(path, "INFO"),
        ):
            pytest.fail("Unsafe log destination was accepted")
        assert error.value.code == ExitCode.LOCAL_IO
    assert kubeconfig.read_text() == original


def test_log_open_failure_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> int:
        raise PermissionError("private-token")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(AppError) as error, diagnostic_logging(tmp_path / "log", "INFO"):
        pytest.fail("Expected open failure")
    assert "private-token" not in str(error.value)


def test_write_failure_never_uses_logging_raw_stderr_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with diagnostic_logging(tmp_path / "log", "DEBUG") as logger:

        def fail_format(record: logging.LogRecord) -> str:
            raise OSError("password=secret-fixture")

        monkeypatch.setattr(logger.handlers[0].formatter, "format", fail_format)
        with pytest.raises(AppError, match="Cannot write") as error:
            logger.warning("opaque-private-message")
        assert error.value.code == ExitCode.LOCAL_IO
    assert capsys.readouterr().err == ""


def test_handler_closes_on_application_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), diagnostic_logging(tmp_path / "log", "DEBUG") as logger:
        handler = logger.handlers[0]
        raise RuntimeError("fixture")
    assert handler.stream is None
    assert logger.handlers == []
