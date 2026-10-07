"""Explicit SDK session, private TLS material and bounded namespace discovery."""

import asyncio
import base64
import binascii
import copy
import json
import ssl
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, NoReturn
from urllib.parse import urlsplit

import aiohttp
from kubernetes_asyncio import client

from kubetrol.adapters.credentials import ExecToken, auth_problem
from kubetrol.config.catalog import ContextConfig, Entry, mapping, regular_bytes, text
from kubetrol.domain.connection_overrides import IMPERSONATION_FIELDS, impersonation_headers
from kubetrol.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    namespace_name,
)
from kubetrol.errors import AppError


def _decode(data: bytes) -> dict[str, Any]:
    return mapping(json.loads(data, parse_constant=_invalid_constant))


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError("Nonfinite JSON constants are invalid.")


async def _decode_owned(data: bytes) -> dict[str, Any]:
    decoding = asyncio.create_task(asyncio.to_thread(_decode, data))
    try:
        return await asyncio.shield(decoding)
    except asyncio.CancelledError:
        await asyncio.gather(decoding, return_exceptions=True)
        raise


def _retry_after(value: str | None) -> float | None:
    if value is None or not value.isascii() or not value.isdigit():
        return None
    return float(min(int(value), 300)) if len(value) < 8 else 300.0


def _endpoint(value: Any) -> str:
    result = text(value)
    parsed = urlsplit(result)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AppError(
            "Kubernetes server must be an HTTP(S) URL without credentials, query or fragment."
        )
    # Force validation of malformed port values even before the first request.
    if parsed.port == 0:
        raise AppError("Kubernetes server port cannot be zero.")
    return result.rstrip("/")


def _material(entry: Entry, name: str, directory: Path) -> str | None:
    inline = entry.data.get(name + "-data")
    filename = entry.data.get(name)
    if inline is not None:
        if not isinstance(inline, str) or len(inline) > 1400000:
            raise AppError("Embedded TLS material must be bounded base64 text.")
        data = base64.b64decode(inline, validate=True)
    elif filename is not None:
        data = regular_bytes(entry.directory / text(filename))
    else:
        return None
    path = directory / name
    path.write_bytes(data)
    path.chmod(0o600)
    return str(path)


def _prepare(
    context: ContextConfig, directory: Path
) -> tuple[client.Configuration, dict[str, Any]]:
    configuration = client.Configuration()
    cluster, user = context.cluster.data, context.user.data
    configuration.host = _endpoint(cluster.get("server"))
    insecure = cluster.get("insecure-skip-tls-verify", False)
    if type(insecure) is not bool:
        raise AppError("insecure-skip-tls-verify must be true or false.")
    configuration.verify_ssl = not insecure
    configuration.ssl_ca_cert = _material(context.cluster, "certificate-authority", directory)
    configuration.cert_file = _material(context.user, "client-certificate", directory)
    configuration.key_file = _material(context.user, "client-key", directory)
    if bool(configuration.cert_file) != bool(configuration.key_file):
        raise auth_problem("Client certificate and key must be supplied together.")
    if "tls-server-name" in cluster:
        configuration.tls_server_name = text(cluster["tls-server-name"])
    if "proxy-url" in cluster:
        configuration.proxy = _endpoint(cluster["proxy-url"])
    if any(key in user for key in ("auth-provider", "username", "password")):
        raise auth_problem(
            "Legacy auth-provider/basic credentials are unqualified. Use an exec helper, token or certificate; provider qualification is C08 #47."
        )
    mechanisms = sum(
        (
            "exec" in user,
            "token" in user or "tokenFile" in user,
            configuration.cert_file is not None,
        )
    )
    if mechanisms > 1:
        raise auth_problem("The selected user has conflicting credential mechanisms.")
    if "token" in user:
        configuration.api_key["BearerToken"] = "Bearer " + text(user["token"])
    elif "tokenFile" in user:
        configuration.api_key["BearerToken"] = "Bearer " + text(
            regular_bytes(context.user.directory / text(user["tokenFile"])).decode("utf-8").strip()
        )
    info: dict[str, Any] = {"server": configuration.host, "insecure-skip-tls-verify": insecure}
    if configuration.ssl_ca_cert is not None:
        info["certificate-authority-data"] = base64.b64encode(
            Path(configuration.ssl_ca_cert).read_bytes()
        ).decode("ascii")
    for field in ("tls-server-name", "proxy-url"):
        if field in cluster:
            info[field] = cluster[field]
    for extension in cluster.get("extensions", []):
        item = mapping(extension)
        if item.get("name") == "client.authentication.k8s.io/exec":
            info["config"] = item.get("extension")
    return configuration, info


class KubernetesSession:
    """No global SDK config; one owned client and credential cache per context."""

    def __init__(self, context: ContextConfig, timeout: float) -> None:
        self.context = context
        self.timeout = timeout
        self.directory = TemporaryDirectory(prefix="kubetrol-session-")
        self.api: client.ApiClient | None = None
        self.configuration: client.Configuration | None = None
        self.credentials: ExecToken | None = None
        self.insecure = False
        self.impersonation: tuple[tuple[str, str], ...] = ()

    def delegated_config(self) -> dict[str, Any]:
        """Pin kubectl to this prepared session, rather than reloading ambient files."""
        configuration = self.configuration
        if configuration is None:
            raise AppError("The selected Kubernetes session is closed.")
        cluster: dict[str, Any] = {
            "server": configuration.host,
            "insecure-skip-tls-verify": not configuration.verify_ssl,
        }
        for source, destination in (
            ("ssl_ca_cert", "certificate-authority"),
            ("tls_server_name", "tls-server-name"),
            ("proxy", "proxy-url"),
        ):
            value = getattr(configuration, source)
            if value is not None:
                cluster[destination] = value
        if "extensions" in self.context.cluster.data:
            cluster["extensions"] = copy.deepcopy(self.context.cluster.data["extensions"])
        user: dict[str, Any] = {}
        for source, destination in (
            ("cert_file", "client-certificate"),
            ("key_file", "client-key"),
        ):
            value = getattr(configuration, source)
            if value is not None:
                user[destination] = value
        if self.credentials is not None:
            helper = copy.deepcopy(self.credentials.entry.data)
            if self.credentials.eks and self.credentials.command is not None:
                helper["command"] = self.credentials.command
            command = text(helper["command"])
            if "/" in command and not Path(command).is_absolute():
                helper["command"] = str(self.credentials.entry.directory / command)
            user["exec"] = helper
        elif token := configuration.api_key.get("BearerToken"):
            user["token"] = token.removeprefix("Bearer ")
        for field in IMPERSONATION_FIELDS:
            if field in self.context.user.data:
                user[field] = copy.deepcopy(self.context.user.data[field])
        return {
            "apiVersion": "v1",
            "kind": "Config",
            "current-context": self.context.name,
            "clusters": [{"name": "kubetrol-session", "cluster": cluster}],
            "users": [{"name": "kubetrol-session", "user": user}],
            "contexts": [
                {
                    "name": self.context.name,
                    "context": {
                        "cluster": "kubetrol-session",
                        "user": "kubetrol-session",
                        "namespace": self.context.namespace,
                    },
                }
            ],
        }

    async def open(self) -> None:
        preparation = asyncio.create_task(
            asyncio.to_thread(_prepare, self.context, Path(self.directory.name))
        )
        try:
            try:
                configuration, info = await asyncio.shield(preparation)
            except asyncio.CancelledError:
                # A cancelled await does not stop the file-reading thread.
                await asyncio.gather(preparation, return_exceptions=True)
                raise
            self.configuration = configuration
            self.impersonation = impersonation_headers(self.context.user.data)
            self.insecure = not configuration.verify_ssl or str(configuration.host).startswith(
                "http:"
            )
            if "exec" in self.context.user.data:
                self.credentials = ExecToken(
                    Entry(mapping(self.context.user.data["exec"]), self.context.user.directory),
                    info,
                    self.timeout,
                )
                configuration.api_key["BearerToken"] = "Bearer " + await self.credentials.token()
            self.api = client.ApiClient(configuration=configuration)
            # Qualify this pinned SDK boundary in transport tests. Preserve the
            # SDK-created TLS connector but refuse ambient netrc/proxy identity.
            original = self.api.rest_client.pool_manager
            connector = original.connector
            original.detach()
            self.api.rest_client.pool_manager = aiohttp.ClientSession(
                connector=connector, trust_env=False, auto_decompress=False, read_bufsize=16384
            )
        except ssl.SSLError:
            await self.close()
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "Cannot load TLS certificates. Check the CA and client certificate/key pair.",
            ) from None
        except (AppError, OSError, ValueError, UnicodeError, binascii.Error, TypeError):
            await self.close()
            raise ConnectionProblem(
                ConnectionState.CONFIG_ERROR,
                "Cannot load the selected connection. Check server, credential files and kubeconfig fields.",
            ) from None
        except BaseException:
            await self.close()
            raise

    @asynccontextmanager
    async def _response(
        self, path: str, params: dict[str, str] | None, accept: str, timeout: float | None
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        api, configuration, credentials = self.api, self.configuration, self.credentials
        if api is None or configuration is None:
            raise ConnectionProblem(ConnectionState.DISCONNECTED, "The selected session is closed.")
        refreshed = False
        while True:
            if credentials is not None:
                configuration.api_key["BearerToken"] = "Bearer " + await credentials.token()
            revision = credentials.revision if credentials is not None else None
            headers = [("Accept", accept), ("Accept-Encoding", "identity"), *self.impersonation]
            token = configuration.api_key.get("BearerToken")
            if token:
                headers.append(("Authorization", token))
            # Bound connection/header establishment separately from a watch's
            # longer body lifetime. An idle watch need not send bookmarks.
            handshake = self.timeout if timeout is None else min(self.timeout, timeout)
            async with asyncio.timeout(handshake):
                response = await api.rest_client.pool_manager.get(
                    str(configuration.host) + path,
                    headers=headers,
                    params=params,
                    proxy=configuration.proxy,
                    server_hostname=configuration.tls_server_name,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(
                        total=timeout, connect=handshake, sock_read=timeout
                    ),
                )
            async with response:
                if response.status == 401 and credentials is not None and not refreshed:
                    credentials.invalidate(revision)
                    refreshed = True
                    continue
                if response.status != 200:
                    raise HttpProblem(
                        response.status,
                        retry_after=_retry_after(response.headers.get("Retry-After")),
                    )
                yield response
                return

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        max_bytes: int = 8 * 1024 * 1024,
        accept: str = "application/json",
    ) -> dict[str, Any]:
        """Owned read-only transport; callers construct discovered API paths."""
        try:
            async with asyncio.timeout(self.timeout):
                async with self._response(path, params, accept, self.timeout) as response:
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        data.extend(chunk)
                        if len(data) > max_bytes:
                            raise ValueError
                return await _decode_owned(bytes(data))
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT,
                "API request timed out. Check connectivity or --request-timeout; retry with F4.",
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "TLS verification failed. Check the cluster CA and server name.",
            ) from None
        except aiohttp.ClientError:
            raise ConnectionProblem(
                ConnectionState.UNREACHABLE,
                "Cluster is unreachable. Check VPN, network and server address; retry with F4.",
            ) from None
        except (AppError, ValueError, UnicodeError, RecursionError, TypeError):
            raise ConnectionProblem(
                ConnectionState.API_ERROR, "Invalid or oversized Kubernetes JSON response."
            ) from None

    async def log_bytes(
        self, path: str, params: dict[str, str], *, follow: bool
    ) -> AsyncGenerator[bytes | None, None]:
        """None reports open headers; quiet follows have no artificial body deadline."""
        try:
            async with self._response(
                path, params, "*/*", None if follow else self.timeout
            ) as response:
                yield None
                async for chunk in response.content.iter_chunked(8192):
                    yield chunk
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT,
                "Log request timed out while connecting or reading a snapshot.",
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "Log TLS verification failed. Check the cluster CA and server name.",
            ) from None
        except aiohttp.ClientError:
            raise ConnectionProblem(
                ConnectionState.UNREACHABLE,
                "Log stream disconnected. Reopening may repeat historical output.",
            ) from None

    @property
    def watch_seconds(self) -> int:
        """Server renewal interval, independent of connection establishment."""
        return ceil(min(self.timeout, 60.0))

    async def watch_json(
        self, path: str, resource_version: str, *, max_bytes: int = 8 * 1024 * 1024
    ) -> AsyncGenerator[dict[str, Any] | None, None]:
        """None signals an opened stream; complete JSON lines follow, without a queue."""
        duration = self.watch_seconds
        # Allow headers and graceful server expiry before the client deadline.
        # A server which never finishes still times out, including with no events.
        lifetime = duration + min(self.timeout, 60.0) + 1.0
        params = {
            "watch": "true",
            "resourceVersion": resource_version,
            "allowWatchBookmarks": "true",
            "timeoutSeconds": str(duration),
        }
        try:
            async with self._response(path, params, "application/json", lifetime) as response:
                yield None
                buffer = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    buffer.extend(chunk)
                    while (end := buffer.find(b"\n")) >= 0:
                        if end > max_bytes:
                            raise ValueError
                        line = bytes(buffer[:end])
                        del buffer[: end + 1]
                        if line.strip():
                            yield await _decode_owned(line)
                    if len(buffer) > max_bytes:
                        raise ValueError
                if buffer.strip():
                    raise ConnectionProblem(
                        ConnectionState.UNREACHABLE,
                        "The watch ended with an incomplete event. Reconnecting from its last version.",
                    )
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT, "The watch request timed out."
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "Watch TLS verification failed. Check the cluster CA and server name.",
            ) from None
        except aiohttp.ClientError:
            raise ConnectionProblem(
                ConnectionState.UNREACHABLE,
                "Watch connection failed. Check network and server access.",
            ) from None
        except (AppError, ValueError, UnicodeError, RecursionError, TypeError):
            raise ConnectionProblem(
                ConnectionState.API_ERROR, "Invalid or oversized Kubernetes watch response."
            ) from None

    async def namespaces(self) -> tuple[str, ...]:
        try:
            async with asyncio.timeout(self.timeout):
                names: set[str] = set()
                continuation = ""
                for _ in range(32):
                    payload = await self.get_json(
                        "/api/v1/namespaces",
                        params={"limit": "500", "continue": continuation},
                        max_bytes=1024 * 1024,
                    )
                    items = payload.get("items")
                    if not isinstance(items, list) or len(items) > 2048:
                        raise ValueError
                    for item in items:
                        names.add(
                            namespace_name(text(mapping(mapping(item).get("metadata")).get("name")))
                        )
                    if len(names) > 2048:
                        raise ValueError
                    continuation = mapping(payload.get("metadata", {})).get("continue", "")
                    if not isinstance(continuation, str) or len(continuation) > 8192:
                        raise ValueError
                    if not continuation:
                        return tuple(sorted(names))
                raise ValueError
        except HttpProblem as error:
            if error.status == 401:
                raise auth_problem(
                    "The API rejected credentials (401). Complete provider login and retry."
                ) from None
            if error.status == 403:
                raise ConnectionProblem(
                    ConnectionState.LIMITED,
                    "Namespace listing is forbidden (403). Select an allowed namespace with :ns NAME or --namespace.",
                ) from None
            raise ConnectionProblem(
                ConnectionState.API_ERROR,
                "Namespace discovery failed. Check the API endpoint and retry (F4).",
            ) from None
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT,
                "Namespace discovery timed out. Check --request-timeout and retry.",
            ) from None
        except (AppError, ValueError, TypeError):
            raise ConnectionProblem(
                ConnectionState.API_ERROR,
                "Invalid or oversized namespace response (maximum 2048 namespaces, 32 pages, 1 MiB per page).",
            ) from None

    async def close(self) -> None:
        try:
            if self.api is not None:
                await self.api.close()
                self.api = None
        finally:
            if self.credentials is not None:
                self.credentials.invalidate()
                self.credentials = None
            self.configuration = None
            self.directory.cleanup()
