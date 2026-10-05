"""Explicit, private, non-overwriting exports with awaited thread cleanup."""

import asyncio
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from kubetrol.domain.logs import MAX_BYTES, MAX_LINES
from kubetrol.errors import AppError


def _save(path: str, text: str) -> Path:
    target = Path(path).expanduser()
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix=".kubetrol-log-", delete=False) as file:
            temporary = Path(file.name)
            file.write(text.encode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
        # An exclusive hard link publishes a complete private file without
        # replacing an existing destination, including a destination symlink.
        os.link(temporary, target)
        return target
    except (OSError, ValueError):
        raise AppError(
            "Cannot save logs: use a new file in an existing writable directory."
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def save_logs(path: str, text: str) -> Path:
    if not path.strip() or len(text.encode("utf-8")) > MAX_BYTES + MAX_LINES:
        raise AppError("Log export requires a file path and bounded retained text.")
    worker = asyncio.create_task(asyncio.to_thread(_save, path, text))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # A filesystem thread is not killed by cancellation. Drain it before
        # returning to the terminal; an explicitly requested save may finish.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except AppError:
                break
        if not worker.cancelled():
            worker.exception()
        raise
