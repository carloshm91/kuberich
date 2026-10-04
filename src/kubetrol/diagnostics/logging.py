"""An owned logger with no console handler, private files, and bounded rotation."""

import fcntl
import io
import logging
import os
import stat
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from kubetrol.config.schema import LOG_LEVELS
from kubetrol.diagnostics.redaction import sanitize_text
from kubetrol.errors import AppError, ExitCode

MAX_LOG_BYTES = 1024 * 1024
LOG_BACKUPS = 3
MAX_RECORD_BYTES = 8192
LOG_HEADER = b"# Kubetrol diagnostic log v1\n"
_LOCK_HEADER = b"# Kubetrol diagnostic lock v1\n"


def _private_open(path: str | Path, header: bytes) -> int:
    descriptor = os.open(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise OSError("Diagnostic destination must be a regular file.")
        if details.st_size and os.pread(descriptor, len(header), 0) != header:
            raise OSError("Diagnostic destination is not a Kubetrol file.")
        os.fchmod(descriptor, 0o600)
        if not details.st_size:
            os.write(descriptor, header)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _check_archives(path: Path) -> None:
    for index in range(1, LOG_BACKUPS + 1):
        archive = path.with_name(f"{path.name}.{index}")
        if not archive.exists() and not archive.is_symlink():
            continue
        descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if (
                not stat.S_ISREG(os.fstat(descriptor).st_mode)
                or os.read(descriptor, len(LOG_HEADER)) != LOG_HEADER
            ):
                raise OSError("Refusing to rotate a foreign diagnostic archive.")
        finally:
            os.close(descriptor)


class SanitizedFormatter(logging.Formatter):
    def converter(self, timestamp: float | None) -> time.struct_time:
        return time.gmtime(timestamp)

    def format(self, record: logging.LogRecord) -> str:
        message = sanitize_text(record.getMessage())
        if record.exc_info:
            # Deliberately omit exception values, source lines, locals and chained values.
            kind, _, trace = record.exc_info
            frames = traceback.extract_tb(trace)
            details = "; ".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames
            )
            message += sanitize_text(
                f" exception={kind.__name__ if kind else 'unknown'} frames={details}"
            )
        result = f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')}Z {record.levelname} {message}"
        return result.encode("utf-8")[:MAX_RECORD_BYTES].decode("utf-8", errors="ignore")


class _PrivateRotatingHandler(RotatingFileHandler):
    def _open(self) -> io.TextIOWrapper:
        descriptor = _private_open(self.baseFilename, LOG_HEADER)
        try:
            return os.fdopen(descriptor, "a", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise

    def handleError(self, record: logging.LogRecord) -> None:
        # logging's default fallback prints the raw record and exception to stderr.
        raise AppError(
            "Cannot write diagnostic log; check permissions and free space.", ExitCode.LOCAL_IO
        ) from None


@contextmanager
def diagnostic_logging(path: Path, level: str) -> Iterator[logging.Logger]:
    if level not in LOG_LEVELS:
        raise AppError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    if not path.name:
        raise AppError("Diagnostic log path must name a file.", ExitCode.LOCAL_IO)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = _private_open(path.with_name(f"{path.name}.lock"), _LOCK_HEADER)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _check_archives(path)
            handler = _PrivateRotatingHandler(
                path, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
            )
        except BaseException:
            os.close(lock)
            raise
    except OSError:
        raise AppError(
            "Cannot open diagnostic log; check path, permissions, and whether another Kubetrol process is using it.",
            ExitCode.LOCAL_IO,
        ) from None
    handler.setFormatter(SanitizedFormatter())
    logger = logging.Logger("kubetrol", level=level)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        handler.close()
        logger.removeHandler(handler)
        os.close(lock)
