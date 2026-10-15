"""Optional, bounded public-release reads and a private local cache; no credentials."""

import asyncio
import json
import os
import stat
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from kuberich.adapters.editing import file_worker
from kuberich.domain.releases import (
    Release,
    cached_release,
    installed_version,
    is_newer,
    release_record,
)
from kuberich.errors import AppError
from kuberich.services.processes import _finish_owned

ENDPOINT = "https://api.github.com/repos/carloshm91/kuberich/releases/latest"
MAX_RESPONSE_BYTES = 65536


@dataclass(frozen=True)
class UpdateResult:
    message: str
    release: Release | None = None
    cached: bool = False


def read_cache(path: Path) -> object:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise AppError("Version cache must be a regular file.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise AppError("Version cache exceeds its size limit.")
        return json.loads(data)
    finally:
        os.close(descriptor)


def write_cache(path: Path, release: Release, now: float) -> None:
    if path.is_symlink():
        raise AppError("Version cache cannot be a symbolic link.")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".version-", dir=path.parent)
    temporary = Path(name)
    try:
        try:
            stream = os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            json.dump({"checked_at": now, "release": release.mapping()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class UpdateService:
    def __init__(self, current: str, cache: Path, *, endpoint: str = ENDPOINT) -> None:
        self.current, self.cache, self.endpoint = current, cache, endpoint

    def _result(self, release: Release, *, cached: bool) -> UpdateResult:
        return UpdateResult(
            f"New stable release: {release.version}"
            if is_newer(release, self.current)
            else "No newer stable release announced.",
            release if is_newer(release, self.current) else None,
            cached,
        )

    async def check(self) -> UpdateResult:
        try:
            current = str(installed_version(self.current))
            now = time.time()
            try:
                record = await file_worker(lambda: read_cache(self.cache))
                return self._result(cached_release(record, now), cached=True)
            except (OSError, AppError, ValueError, UnicodeError):
                pass
            session = aiohttp.ClientSession(
                trust_env=False,
                auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                timeout=aiohttp.ClientTimeout(total=3, connect=2, sock_read=2),
                headers={
                    "Accept": "application/vnd.github+json",
                    "Accept-Encoding": "identity",
                    "User-Agent": f"KubeRich/{current}",
                },
            )
            try:
                async with session.get(self.endpoint, allow_redirects=False) as response:
                    if response.status != 200:
                        raise AppError("Version check unavailable.")
                    data = bytearray()
                    async for part in response.content.iter_chunked(8192):
                        data.extend(part)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise AppError("Version response exceeds its size limit.")
                    release = release_record(json.loads(data))
            finally:
                await _finish_owned(asyncio.create_task(session.close()))
            with suppress(OSError, AppError):
                await file_worker(lambda: write_cache(self.cache, release, now))
            return self._result(release, cached=False)
        except (
            OSError,
            aiohttp.ClientError,
            TimeoutError,
            AppError,
            ValueError,
            UnicodeError,
            RecursionError,
        ):
            return UpdateResult("Version check unavailable; startup continues offline.")
