"""Independent bounded distribution HTTP, without ambient credentials or helpers."""

from __future__ import annotations

import asyncio
import base64
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit
from urllib.request import parse_http_list, parse_keqv_list

from kuberich.domain.helm_catalog import (
    MAX_CHART_BYTES,
    HelmRepository,
    HelmRepositoryKind,
    RepositoryCredentials,
    catalog_text,
    catalog_url,
    oci_digest,
    oci_tag,
    url_origin,
)
from kuberich.domain.helm_cli import helm_json
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import parse_owned

if TYPE_CHECKING:
    import aiohttp


class CatalogHttpProblem(AppError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(
            f"Helm repository request refused with HTTP {status}; no catalog change applied."
        )


@dataclass(frozen=True, slots=True, repr=False)
class CatalogBody:
    data: bytes
    content_type: str
    content_digest: str | None
    link: str | None


def _basic(credentials: RepositoryCredentials) -> str | None:
    if credentials.username is None:
        return None
    return "Basic " + base64.b64encode(
        (credentials.username + ":" + str(credentials.password)).encode()
    ).decode("ascii")


def _tls(repository: HelmRepository) -> ssl.SSLContext:
    try:
        return ssl.create_default_context(cafile=repository.ca_file)
    except (OSError, ssl.SSLError):
        raise AppError("Helm repository CA configuration is unavailable or invalid.") from None


class CatalogHttp:
    """Own a small origin-bound pool; no cookies, proxies, netrc or implicit retry."""

    def __init__(self, repository: HelmRepository, credentials: RepositoryCredentials) -> None:
        self.repository = repository
        self._credentials = credentials
        self._session: aiohttp.ClientSession | None = None
        self._pool_lock = asyncio.Lock()
        self._token: str | None = None
        self._closed = False
        self._tasks: set[asyncio.Task[CatalogBody]] = set()

    async def _pool(self) -> aiohttp.ClientSession:
        async with self._pool_lock:
            return await self._prepare_pool()

    async def _prepare_pool(self) -> aiohttp.ClientSession:
        import aiohttp

        if self._closed:
            raise AppError("Helm catalog transport is closed.")
        if self._session is None:
            context = await parse_owned(lambda: _tls(self.repository))
            if self._closed:
                raise AppError("Helm catalog transport is closed.")
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=context, limit=2, limit_per_host=2),
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=20, connect=10, sock_read=10),
                headers={"Accept-Encoding": "identity"},
            )
        return self._session

    def _url(self, url: str, *, token: bool = False) -> str:
        canonical = catalog_url(url, allow_loopback_http=self.repository.allow_loopback_http)
        allowed = {self.repository.origin}
        allowed.update(self.repository.token_origins if token else self.repository.download_origins)
        if canonical != url or url_origin(url) not in allowed:
            raise AppError("Helm distribution request escaped the explicitly configured origins.")
        if (
            self.repository.kind is HelmRepositoryKind.OCI
            and not token
            and url_origin(url) == self.repository.origin
        ):
            prefix = "/v2/" + self.repository.oci_path + "/"
            path = urlsplit(url).path
            if not path.startswith(prefix):
                raise AppError("OCI request escaped the registered chart repository path.")
            suffix = path[len(prefix) :]
            if suffix != "tags/list":
                command, separator, reference = suffix.partition("/")
                if not separator or "/" in reference or command not in {"manifests", "blobs"}:
                    raise AppError(
                        "OCI request requires an exact chart manifest or blob destination."
                    )
                if command == "blobs" or reference.startswith("sha256:"):
                    oci_digest(reference)
                else:
                    oci_tag(reference)
        return url

    async def _request(
        self,
        url: str,
        limit: int,
        accept: str,
        authorization: str | None,
        guard: Callable[[], None],
        *,
        token: bool = False,
        params: dict[str, str] | None = None,
    ) -> tuple[CatalogBody | None, str | None]:
        import aiohttp

        pool = await self._pool()
        for _ in range(4):
            guard()
            self._url(url, token=token)
            headers = {"Accept": accept}
            if authorization is not None:
                headers["Authorization"] = authorization
            try:
                async with pool.get(
                    url, headers=headers, params=params, allow_redirects=False
                ) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location", "")
                        destination = urljoin(url, location)
                        self._url(destination, token=token)
                        if (
                            urlsplit(url).scheme == "https"
                            and urlsplit(destination).scheme != "https"
                        ):
                            raise AppError("Helm distribution redirects cannot downgrade HTTPS.")
                        if url_origin(destination) != url_origin(url):
                            authorization = None
                        url, params = destination, None
                        continue
                    if response.status == 401 and not token:
                        if url_origin(url) != self.repository.origin:
                            raise CatalogHttpProblem(401)
                        return None, response.headers.get("WWW-Authenticate", "")
                    if response.status != 200:
                        raise CatalogHttpProblem(response.status)
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise AppError(
                            "Helm repository compressed HTTP bodies are unsupported; request an identity response."
                        )
                    if response.content_length is not None and response.content_length > limit:
                        raise AppError(
                            "Helm repository response exceeded its advertised byte bound."
                        )
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(16_384):
                        guard()
                        if len(data) + len(chunk) > limit:
                            raise AppError(
                                "Helm repository response exceeded its streaming byte bound."
                            )
                        data.extend(chunk)
                    guard()
                    for name in ("Content-Type", "Docker-Content-Digest", "Link"):
                        if len(response.headers.getall(name, [])) > 1:
                            raise AppError(
                                "Helm repository response has ambiguous content metadata."
                            )
                    return CatalogBody(
                        bytes(data),
                        response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower(),
                        response.headers.get("Docker-Content-Digest"),
                        response.headers.get("Link"),
                    ), None
            except TimeoutError:
                raise AppError(
                    "Helm repository request timed out; refresh explicitly before retrying."
                ) from None
            except (aiohttp.ClientError, OSError, ssl.SSLError):
                raise AppError(
                    "Helm repository TLS or transport failed; no catalog change applied."
                ) from None
        raise AppError("Helm repository redirects exceeded their fixed bound.")

    async def _challenge(self, challenge: str, guard: Callable[[], None]) -> str:
        if len(challenge) > 8192 or not challenge.startswith("Bearer "):
            raise CatalogHttpProblem(401)
        try:
            pairs = parse_http_list(challenge[7:])
            if len(pairs) > 4 or len({pair.split("=", 1)[0].strip() for pair in pairs}) != len(
                pairs
            ):
                raise ValueError
            values = parse_keqv_list(pairs)
            if set(values) - {"realm", "service", "scope"}:
                raise ValueError
            realm = self._url(values["realm"], token=True)
            scope = "repository:" + self.repository.oci_path + ":pull"
            if values.get("scope", scope) != scope:
                raise ValueError
            service = values.get("service", "")
            if service:
                catalog_text(service, limit=256)
            params = {"scope": scope}
            if service:
                params["service"] = service
        except (KeyError, ValueError):
            raise AppError("OCI bearer challenge has an unsupported realm or pull scope.") from None
        body, _ = await self._request(
            realm,
            65_536,
            "application/json",
            _basic(self._credentials),
            guard,
            token=True,
            params=params,
        )
        assert body is not None
        try:
            value = await parse_owned(lambda: helm_json(body.data, limit=65_536))
            if not isinstance(value, dict):
                raise ValueError
            token = value.get("token", value.get("access_token"))
            if value.get("access_token", token) != token:
                raise ValueError
            checked = RepositoryCredentials(token=token)
            if checked.token is None:
                raise ValueError
            return checked.token
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise AppError(
                "OCI token response is invalid; credentials and response details withheld."
            ) from None

    async def _get(
        self,
        url: str,
        limit: int,
        accept: str,
        guard: Callable[[], None],
        params: dict[str, str] | None,
    ) -> CatalogBody:
        token = self._token or self._credentials.token
        authorization = (
            ("Bearer " + token if token is not None else _basic(self._credentials))
            if url_origin(url) == self.repository.origin
            else None
        )
        body, challenge = await self._request(
            url, limit, accept, authorization, guard, params=params
        )
        if body is None:
            if url_origin(url) != self.repository.origin:
                raise CatalogHttpProblem(401)
            self._token = await self._challenge(challenge or "", guard)
            body, _ = await self._request(
                url, limit, accept, "Bearer " + self._token, guard, params=params
            )
            if body is None:
                raise CatalogHttpProblem(401)
        return body

    async def get(
        self,
        url: str,
        *,
        max_bytes: int,
        accept: str,
        guard: Callable[[], None],
        params: dict[str, str] | None = None,
    ) -> CatalogBody:
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CHART_BYTES:
            raise AppError("Helm HTTP requests require an explicit supported byte bound.")
        self._url(url)
        if params is not None:
            if (
                self.repository.kind is not HelmRepositoryKind.OCI
                or not url.endswith("/tags/list")
                or not isinstance(params, dict)
                or set(params) - {"n", "last"}
            ):
                raise AppError("OCI listing accepts only bounded structured pagination parameters.")
            count = params.get("n", "500")
            if (
                not isinstance(count, str)
                or not 1 <= len(count) <= 3
                or not count.isascii()
                or not count.isdecimal()
                or not 1 <= int(count) <= 500
            ):
                raise AppError("OCI listing page size must be between one and 500 tags.")
            if "last" in params:
                oci_tag(params["last"])
        task = asyncio.create_task(
            self._get(url, max_bytes, accept, guard, dict(params) if params is not None else None)
        )
        self._tasks.add(task)
        try:
            return await task
        finally:
            self._tasks.discard(task)

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._token = None
        self._credentials = RepositoryCredentials()
