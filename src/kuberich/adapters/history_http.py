"""Independent, bounded HTTP transport for an explicitly configured history URL.

This adapter receives no Kubernetes configuration or client. Its TLS, bearer,
cookies and connection pool belong exclusively to the external endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.history import ExternalHistoryBackend
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import parse_owned

if TYPE_CHECKING:
    import aiohttp

type HistorySuffix = Literal["query", "query_range", "status/buildinfo"]
_SUFFIXES = frozenset({"query", "query_range", "status/buildinfo"})
_MAX_BODY = 1024 * 1024
_MAX_TOKEN = 8192


@dataclass(frozen=True, slots=True)
class _Credentials:
    token: str | None = field(repr=False)
    revision: str = field(repr=False)


def _credentials(path: Path | None) -> _Credentials:
    if path is None:
        return _Credentials(None, "anonymous")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o077:
            raise ValueError
        if hasattr(os, "getuid") and before.st_uid != os.getuid():
            raise ValueError
        data = os.read(descriptor, _MAX_TOKEN + 1)
        after = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

        if (
            identity(before) != identity(after)
            or identity(after) != identity(current)
            or len(data) != before.st_size
        ):
            raise ValueError
        token = data.decode("utf-8").strip()
        if (
            not token
            or len(data) > _MAX_TOKEN
            or any(ord(char) <= 32 or ord(char) >= 127 for char in token)
        ):
            raise ValueError
        revision = hashlib.sha256(repr(identity(after)).encode() + b"\0" + data).hexdigest()
        return _Credentials(token, revision)
    except (OSError, UnicodeError, ValueError):
        raise AppError(
            "External history bearer file must be private, stable and bounded."
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _tls(path: Path | None) -> ssl.SSLContext:
    try:
        return ssl.create_default_context(cafile=path)
    except (OSError, ssl.SSLError):
        raise AppError("External history CA configuration is unavailable or invalid.") from None


def _decode(data: bytes) -> object:
    try:
        return json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        raise AppError("Invalid external history JSON response.") from None


class ExternalHistoryTransport:
    """Own a dedicated external pool and all of its reads and credential work."""

    def __init__(self, endpoint: ExternalHistoryBackend) -> None:
        if not isinstance(endpoint, ExternalHistoryBackend):
            raise AppError("External history requires its own explicit endpoint settings.")
        self._endpoint = endpoint
        self._session: aiohttp.ClientSession | None = None
        self._credentials: _Credentials | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[object]] = set()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    @property
    def auth_revision(self) -> str:
        """Private cache discriminator; callers must never display or export it."""
        return self._credentials.revision if self._credentials is not None else "unprepared"

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    async def prepare(self) -> str:
        """Refresh independent auth before cache lookup, replacing its pool on rotation."""
        import aiohttp

        async with self._lock:
            if self._closed:
                raise AppError("External history transport is closed.")
            credentials = await parse_owned(lambda: _credentials(self._endpoint.bearer_token_file))
            if self._credentials == credentials and self._session is not None:
                return credentials.revision
            context = await parse_owned(lambda: _tls(self._endpoint.ca_file))
            if self._session is not None:
                await self._session.close()
            connector = aiohttp.TCPConnector(ssl=context, limit=2, limit_per_host=2)
            self._session = aiohttp.ClientSession(
                connector=connector,
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=10, connect=10, sock_read=10),
                headers={"Accept": "application/json"},
            )
            self._credentials = credentials
            return credentials.revision

    async def _get_json(
        self, suffix: HistorySuffix, params: Mapping[str, str], max_bytes: int
    ) -> object:
        import aiohttp

        await self.prepare()
        session, credentials = self._session, self._credentials
        if session is None or credentials is None:
            raise AppError("External history transport is unavailable.")
        url = self._endpoint.url.rstrip("/") + "/api/v1/" + suffix
        headers = {"Authorization": "Bearer " + credentials.token} if credentials.token else {}
        try:
            async with asyncio.timeout(10):
                async with session.get(
                    url, params=dict(params), headers=headers, allow_redirects=False
                ) as response:
                    if response.status != 200:
                        raise HttpProblem(response.status)
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        data.extend(chunk)
                        if len(data) > max_bytes:
                            raise AppError(
                                "External history response exceeded its decoded body limit."
                            )
                return await parse_owned(lambda: _decode(bytes(data)))
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT, "External history request timed out."
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR, "External history TLS verification failed."
            ) from None
        except (aiohttp.ClientError, OSError, asyncio.IncompleteReadError):
            raise ConnectionProblem(
                ConnectionState.UNREACHABLE, "External history endpoint is unreachable."
            ) from None

    async def get_json(
        self, suffix: HistorySuffix, params: Mapping[str, str], *, max_bytes: int
    ) -> object:
        if suffix not in _SUFFIXES or type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_BODY:
            raise AppError("External history requires a fixed API suffix and bounded body.")
        if self._closed:
            raise AppError("External history transport is closed.")
        task = asyncio.create_task(self._get_json(suffix, params, max_bytes))
        self._tasks.add(task)
        try:
            return await task
        finally:
            self._tasks.discard(task)

    async def _close(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None
            self._credentials = None

    async def close(self) -> None:
        self._closed = True
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        completion = asyncio.gather(self._closing, return_exceptions=True)
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await finish_owned(completion)
            raise
