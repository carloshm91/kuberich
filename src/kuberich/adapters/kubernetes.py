"""Explicit SDK session, private TLS material and bounded namespace discovery."""

import asyncio
import base64
import binascii
import copy
import json
import os
import ssl
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any, NoReturn
from urllib.parse import urlsplit

import aiohttp
from aiohttp_socks import ProxyConnectionError, ProxyConnector, ProxyError, ProxyTimeoutError
from kubernetes_asyncio import client

from kuberich.adapters.credentials import CredentialLogin, ExecToken, auth_problem
from kuberich.config.catalog import ContextConfig, Entry, mapping, regular_bytes, text
from kuberich.domain.connection_overrides import IMPERSONATION_FIELDS, impersonation_headers
from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    namespace_name,
)
from kuberich.domain.credential_helpers import bearer_token
from kuberich.domain.exec_credentials import encrypted_key
from kuberich.domain.proxies import effective_proxy, tls_failure
from kuberich.errors import AppError


def decode_json(data: bytes) -> dict[str, Any]:
    """Decode a bounded JSON object for an owned transport or service worker."""
    return mapping(json.loads(data, parse_constant=_invalid_constant))


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError("Nonfinite JSON constants are invalid.")


async def _decode_owned(data: bytes) -> dict[str, Any]:
    decoding = asyncio.create_task(asyncio.to_thread(decode_json, data))
    return await _finish_task(decoding)


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
    if name == "client-key" and encrypted_key(data):
        raise auth_problem(
            "Encrypted client TLS keys are unsupported. Use an unencrypted kubeconfig key or an explicit exec helper that owns decryption."
        )
    path = directory / name
    path.write_bytes(data)
    path.chmod(0o600)
    return str(path)


class _ServerNameContext(ssl.SSLContext):
    expected_name: str | None = None

    def wrap_bio(
        self,
        incoming: ssl.MemoryBIO,
        outgoing: ssl.MemoryBIO,
        server_side: bool = False,
        server_hostname: str | bytes | None = None,
        session: ssl.SSLSession | None = None,
    ) -> ssl.SSLObject:
        # The pinned SOCKS connector drops request-level server_hostname.
        # Bind the configured identity at Python's public TLS BIO boundary.
        return super().wrap_bio(
            incoming,
            outgoing,
            server_side=server_side,
            server_hostname=None if server_side else self.expected_name or server_hostname,
            session=session,
        )


def _ssl_context(
    configuration: client.Configuration, *, bind_server_name: bool = False
) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=configuration.ssl_ca_cert)
    expected_name = configuration.tls_server_name or urlsplit(str(configuration.host)).hostname
    if bind_server_name and expected_name is not None:
        named = _ServerNameContext(ssl.PROTOCOL_TLS_CLIENT)
        named.expected_name = expected_name
        named.verify_flags = context.verify_flags
        named.options = context.options
        named.minimum_version, named.maximum_version = (
            context.minimum_version,
            context.maximum_version,
        )
        if configuration.ssl_ca_cert is not None:
            named.load_verify_locations(cafile=configuration.ssl_ca_cert)
        else:
            named.load_default_certs()
        context = named
    if configuration.cert_file:
        context.load_cert_chain(configuration.cert_file, keyfile=configuration.key_file)
    if not configuration.verify_ssl:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if configuration.disable_strict_ssl_verification:
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


async def _finish_task[T](task: asyncio.Task[T]) -> T:
    # Shield the collector: cancelled shields can report the child's late error.
    finishing = asyncio.gather(task, return_exceptions=True)
    try:
        await asyncio.shield(finishing)
    except asyncio.CancelledError:
        while not finishing.done():
            try:
                await asyncio.shield(finishing)
            except asyncio.CancelledError:
                continue
        await finishing
        raise
    return task.result()


def _prepare(
    context: ContextConfig, directory: Path, environment: dict[str, str] | None = None
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
    if "tls-server-name" in cluster and cluster["tls-server-name"] != "":
        configuration.tls_server_name = text(cluster["tls-server-name"])
    configuration.proxy = effective_proxy(
        configuration.host, cluster.get("proxy-url"), environment if environment is not None else {}
    )
    if any(key in user for key in ("auth-provider", "username", "password")):
        raise auth_problem(
            "Legacy auth-provider/basic credentials are unsupported. Regenerate GKE/AKS exec kubeconfig or configure an external OIDC exec helper; token/certificate users need no helper."
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
        configuration.api_key["BearerToken"] = "Bearer " + bearer_token(user["token"])
    if "tokenFile" in user:
        try:
            configuration.api_key["BearerToken"] = "Bearer " + bearer_token(
                regular_bytes(context.user.directory / text(user["tokenFile"]))
                .decode("utf-8")
                .strip()
            )
        except (AppError, OSError, UnicodeError, ValueError):
            if "BearerToken" not in configuration.api_key:
                raise auth_problem(
                    "Cannot read tokenFile credentials. Check its path and permissions."
                ) from None
    info: dict[str, Any] = {"server": configuration.host, "insecure-skip-tls-verify": insecure}
    if configuration.ssl_ca_cert is not None:
        info["certificate-authority-data"] = base64.b64encode(
            Path(configuration.ssl_ca_cert).read_bytes()
        ).decode("ascii")
    if configuration.tls_server_name is not None:
        info["tls-server-name"] = configuration.tls_server_name
    if configuration.proxy is not None:
        info["proxy-url"] = configuration.proxy
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
        self.token_file = (
            context.user.directory / text(context.user.data["tokenFile"])
            if "tokenFile" in context.user.data
            else None
        )
        self.directory = TemporaryDirectory(prefix="kuberich-session-")
        self.api: client.ApiClient | None = None
        self.configuration: client.Configuration | None = None
        self.credentials: ExecToken | None = None
        self.insecure = False
        self.impersonation: tuple[tuple[str, str], ...] = ()
        self.environment = dict(os.environ)
        self.authentication_lock = asyncio.Lock()
        self.credential_revision = -1
        self.token_read_after = 0.0
        self.certificate_files: tuple[Path, ...] = ()

    @property
    def request_proxy(self) -> str | None:
        proxy = self.configuration.proxy if self.configuration is not None else None
        return None if proxy and proxy.startswith("socks5:") else proxy

    async def _new_pool(self, configuration: client.Configuration) -> aiohttp.ClientSession:
        proxy = configuration.proxy
        context = await _finish_task(
            asyncio.create_task(
                asyncio.to_thread(
                    _ssl_context,
                    configuration,
                    bind_server_name=bool(proxy and proxy.startswith("socks5:")),
                )
            )
        )
        connector = (
            ProxyConnector.from_url(proxy, ssl=context, limit=configuration.connection_pool_maxsize)
            if proxy and proxy.startswith("socks5:")
            else aiohttp.TCPConnector(ssl=context, limit=configuration.connection_pool_maxsize)
        )
        return aiohttp.ClientSession(
            connector=connector, trust_env=False, auto_decompress=False, read_bufsize=16384
        )

    async def _rotate_certificate(self, pair: tuple[str, str] | None, revision: int) -> None:
        configuration = self.configuration
        if configuration is None:
            raise auth_problem("The selected session closed before credential preparation.")
        files = (
            tuple(
                Path(self.directory.name) / f"exec-{revision}-{name}.pem"
                for name in ("cert", "key")
            )
            if pair is not None
            else ()
        )
        previous = self.certificate_files
        previous_material = configuration.cert_file, configuration.key_file
        created: list[Path] = []
        committed = False

        def write() -> None:
            for path, content in zip(files, pair or (), strict=True):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created.append(path)
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(content)

        try:
            await _finish_task(asyncio.create_task(asyncio.to_thread(write)))
            configuration.cert_file, configuration.key_file = (
                map(str, files) if files else (None, None)
            )
            if self.api is not None:
                fresh = await self._new_pool(configuration)
                old = self.api.rest_client.pool_manager
                self.api.rest_client.pool_manager = fresh
                self.certificate_files = files
                committed = True
                await old.close()
            else:
                self.certificate_files = files
                committed = True
        finally:
            if not committed:
                configuration.cert_file, configuration.key_file = previous_material
            unused = previous if committed else created
            for path in unused:
                path.unlink(missing_ok=True)

    async def refresh_credentials(self, *, authenticate: CredentialLogin | None = None) -> None:
        """Refresh before transport use; never replay an effectful request."""
        async with self.authentication_lock:
            configuration = self.configuration
            if configuration is None:
                raise ConnectionProblem(
                    ConnectionState.DISCONNECTED, "The selected session is closed."
                )
            if self.credentials is not None:
                token = (
                    await self.credentials.token()
                    if authenticate is None
                    else await authenticate(self.credentials)
                )
                if (
                    self.credentials.certificate is not None or self.certificate_files
                ) and self.credential_revision != self.credentials.revision:
                    await _finish_task(
                        asyncio.create_task(
                            self._rotate_certificate(
                                self.credentials.certificate, self.credentials.revision
                            )
                        )
                    )
                if token is None:
                    configuration.api_key.pop("BearerToken", None)
                else:
                    configuration.api_key["BearerToken"] = "Bearer " + token
                self.credential_revision = self.credentials.revision
            elif self.token_file is not None and monotonic() >= self.token_read_after:
                self.token_read_after = monotonic() + 60.0
                try:
                    material = await _finish_task(
                        asyncio.create_task(asyncio.to_thread(regular_bytes, self.token_file))
                    )
                    configuration.api_key["BearerToken"] = "Bearer " + bearer_token(
                        material.decode("utf-8").strip()
                    )
                except (AppError, OSError, ValueError, UnicodeError):
                    if "BearerToken" not in configuration.api_key:
                        raise auth_problem(
                            "Cannot read tokenFile credentials. Check its path and permissions."
                        ) from None

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
            value = getattr(configuration, source) if self.credentials is None else None
            if value is not None:
                user[destination] = value
        if self.credentials is not None:
            helper = copy.deepcopy(self.credentials.entry.data)
            if self.credentials.command is not None:
                helper["command"] = self.credentials.command
            command = text(helper["command"])
            if "/" in command and not Path(command).is_absolute():
                helper["command"] = str(self.credentials.entry.directory / command)
            user["exec"] = helper
        elif token := configuration.api_key.get("BearerToken"):
            user["token"] = token.removeprefix("Bearer ")
            if self.token_file is not None:
                user["tokenFile"] = str(self.token_file.absolute())
        for field in IMPERSONATION_FIELDS:
            if field in self.context.user.data:
                user[field] = copy.deepcopy(self.context.user.data[field])
        return {
            "apiVersion": "v1",
            "kind": "Config",
            "current-context": self.context.name,
            "clusters": [{"name": "kuberich-session", "cluster": cluster}],
            "users": [{"name": "kuberich-session", "user": user}],
            "contexts": [
                {
                    "name": self.context.name,
                    "context": {
                        "cluster": "kuberich-session",
                        "user": "kuberich-session",
                        "namespace": self.context.namespace,
                    },
                }
            ],
        }

    async def open(self, *, authenticate: CredentialLogin | None = None) -> None:
        preparation = asyncio.create_task(
            asyncio.to_thread(_prepare, self.context, Path(self.directory.name), self.environment)
        )
        try:
            # File work continues after an await is cancelled; drain it through
            # repeated cancellation before close removes the owned directory.
            configuration, info = await _finish_task(preparation)
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
                self.credentials.environment = dict(self.environment)
                await self.refresh_credentials(authenticate=authenticate)
            elif authenticate is not None:
                raise auth_problem(
                    "The selected user has no exec helper to authenticate with :login."
                )
            self.api = client.ApiClient(configuration=configuration)
            # Qualify this pinned SDK boundary in transport tests. Preserve the
            # SDK-created TLS connector but refuse ambient netrc/proxy identity.
            original = self.api.rest_client.pool_manager
            if configuration.proxy and configuration.proxy.startswith("socks5:"):
                self.api.rest_client.pool_manager = await self._new_pool(configuration)
                await original.close()
                return
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
            await self.refresh_credentials()
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
                    proxy=self.request_proxy,
                    server_hostname=configuration.tls_server_name,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(
                        total=timeout, connect=handshake, sock_read=timeout
                    ),
                )
            async with response:
                if (
                    response.status == 401
                    and (credentials is not None or self.token_file is not None)
                    and not refreshed
                ):
                    if credentials is not None:
                        credentials.invalidate(revision)
                    self.token_read_after = 0.0
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
        except (TimeoutError, ProxyTimeoutError):
            raise ConnectionProblem(
                ConnectionState.TIMEOUT,
                "API request timed out. Check connectivity or --request-timeout; retry with F4.",
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "TLS verification failed. Check the cluster CA and server name.",
            ) from None
        except (
            aiohttp.ClientError,
            ProxyError,
            ProxyConnectionError,
            OSError,
            asyncio.IncompleteReadError,
        ) as error:
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR if tls_failure(error) else ConnectionState.UNREACHABLE,
                "TLS verification failed. Check the cluster CA and server name."
                if tls_failure(error)
                else "Cluster is unreachable. Check VPN, network and server address; retry with F4.",
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
        except (TimeoutError, ProxyTimeoutError):
            raise ConnectionProblem(
                ConnectionState.TIMEOUT,
                "Log request timed out while connecting or reading a snapshot.",
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "Log TLS verification failed. Check the cluster CA and server name.",
            ) from None
        except (
            aiohttp.ClientError,
            ProxyError,
            ProxyConnectionError,
            OSError,
            asyncio.IncompleteReadError,
        ) as error:
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR if tls_failure(error) else ConnectionState.UNREACHABLE,
                "Log TLS verification failed. Check the cluster CA and server name."
                if tls_failure(error)
                else "Log stream disconnected. Reopening may repeat historical output.",
            ) from None

    @property
    def watch_seconds(self) -> int:
        """Server renewal interval, independent of connection establishment."""
        return ceil(min(self.timeout, 60.0))

    async def watch_json(
        self,
        path: str,
        resource_version: str,
        *,
        max_bytes: int = 8 * 1024 * 1024,
        accept: str = "application/json",
        include_object: bool = False,
    ) -> AsyncGenerator[dict[str, Any] | None, None]:
        """None signals an opened stream; complete JSON lines follow, without a queue."""
        try:
            async with aclosing(
                self.watch_bytes(
                    path,
                    resource_version,
                    max_bytes=max_bytes,
                    accept=accept,
                    include_object=include_object,
                )
            ) as stream:
                async for line in stream:
                    yield await _decode_owned(line) if line is not None else None
        except (AppError, ValueError, UnicodeError, RecursionError, TypeError):
            raise ConnectionProblem(
                ConnectionState.API_ERROR, "Invalid or oversized Kubernetes watch response."
            ) from None

    async def watch_bytes(
        self,
        path: str,
        resource_version: str,
        *,
        max_bytes: int = 8 * 1024 * 1024,
        accept: str = "application/json",
        include_object: bool = False,
    ) -> AsyncGenerator[bytes | None, None]:
        """Pull one bounded complete frame; its consumer owns parsing and validation."""
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
        if include_object:
            params["includeObject"] = "Object"
        try:
            async with self._response(path, params, accept, lifetime) as response:
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
                            yield line
                    if len(buffer) > max_bytes:
                        raise ValueError
                if buffer.strip():
                    raise ConnectionProblem(
                        ConnectionState.UNREACHABLE,
                        "The watch ended with an incomplete event. Reconnecting from its last version.",
                    )
        except (TimeoutError, ProxyTimeoutError):
            raise ConnectionProblem(
                ConnectionState.TIMEOUT, "The watch request timed out."
            ) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR,
                "Watch TLS verification failed. Check the cluster CA and server name.",
            ) from None
        except (
            aiohttp.ClientError,
            ProxyError,
            ProxyConnectionError,
            OSError,
            asyncio.IncompleteReadError,
        ) as error:
            raise ConnectionProblem(
                ConnectionState.TLS_ERROR if tls_failure(error) else ConnectionState.UNREACHABLE,
                "Watch TLS verification failed. Check the cluster CA and server name."
                if tls_failure(error)
                else "Watch connection failed. Check network and server access.",
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
        except (TimeoutError, ProxyTimeoutError):
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
        async with self.authentication_lock:
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
