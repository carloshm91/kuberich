"""Private, bounded diagnostic bundles without credential or configuration contents."""

import json
import os
import platform
import stat
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Literal

from platformdirs import user_state_path

from kuberich.bootstrap import version
from kuberich.diagnostics.logging import LOG_HEADER
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.errors import AppError, ExitCode

type ConfigStatus = Literal["valid", "invalid", "missing", "unavailable"]
MAX_LOG_TAIL = 32768


def _recent_log(path: Path | None) -> dict[str, str]:
    if path is None:
        return {"status": "unavailable"}
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid():
                return {"status": "unavailable"}
            header = os.read(descriptor, len(LOG_HEADER))
            if header not in {LOG_HEADER, LOG_HEADER.replace(b"KubeRich", b"Kubetrol")}:
                return {"status": "unavailable"}
            start = max(len(header), details.st_size - MAX_LOG_TAIL)
            os.lseek(descriptor, start, os.SEEK_SET)
            tail = os.read(descriptor, MAX_LOG_TAIL)
        finally:
            os.close(descriptor)
    except OSError:
        return {"status": "unavailable"}
    # Owned log records are already redacted and physically single-line. Drop a
    # partial first record before reapplying defense-in-depth sanitization.
    if start > len(header):
        tail = tail.partition(b"\n")[2]
    return {
        "status": "included",
        "text": sanitize_text(tail.decode("utf-8", errors="replace"), allow_newlines=True),
    }


def write_report(
    *,
    config_status: ConfigStatus,
    log_path: Path | None = None,
    error: Exception | None = None,
    output: Path | None = None,
) -> Path:
    """Create a mode-0600 JSON bundle; never overwrite a destination or read kubeconfig."""
    terminal: dict[str, object] = {
        "stdin_tty": sys.stdin.isatty(),
        "stdout_tty": sys.stdout.isatty(),
    }
    try:
        size = os.get_terminal_size()
    except OSError:
        pass
    else:
        terminal.update(columns=size.columns, rows=size.lines)
    report: dict[str, object] = {
        "schema_version": 1,
        "version": version("kuberich"),
        "python": platform.python_version(),
        "platform": sys.platform,
        "terminal": terminal,
        "config_check": config_status,
        "recent_log": _recent_log(log_path),
    }
    if error is not None:
        # Omit values, source lines, locals, chains, full paths and process argv.
        report["failure"] = {
            "kind": sanitize_text(type(error).__name__),
            "frames": [
                {
                    "file": sanitize_text(Path(frame.filename).name),
                    "line": frame.lineno,
                    "function": sanitize_text(frame.name),
                }
                for frame in traceback.StackSummary.extract(
                    traceback.walk_tb(error.__traceback__),
                    limit=32,
                    lookup_lines=False,
                    capture_locals=False,
                )
            ],
        }
    payload = (json.dumps(report, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    destination: Path
    try:
        if output is None:
            directory = user_state_path("kuberich", appauthor=False) / "reports"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(
                prefix="kuberich-report-", suffix=".json", dir=directory
            )
            destination = Path(filename)
        else:
            descriptor = os.open(
                output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            destination = output.absolute()
        try:
            try:
                os.fchmod(descriptor, 0o600)
                stream = os.fdopen(descriptor, "wb")
            except BaseException:
                os.close(descriptor)
                raise
            with stream:
                stream.write(payload)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    except OSError:
        raise AppError(
            "Cannot create diagnostic report; choose a new file in a writable directory.",
            ExitCode.LOCAL_IO,
        ) from None
    return destination
