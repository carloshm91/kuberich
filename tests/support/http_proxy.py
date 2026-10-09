"""Actual HTTP proxy/CONNECT relay restricted to one owned loopback destination."""

import asyncio
import base64
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from tests.support.proxy_transport import close_relays


@dataclass
class HttpProxyWitness:
    requests: list[tuple[str, str | None]] = field(default_factory=list)
    active: set[asyncio.Task[None]] = field(default_factory=set)
    failures: list[AssertionError] = field(default_factory=list)


@asynccontextmanager
async def http_proxy(
    target: str, *, credentials: tuple[str, str] | None = None, tls: ssl.SSLContext | None = None
) -> AsyncIterator[tuple[str, HttpProxyWitness]]:
    endpoint = urlsplit(target)
    assert endpoint.hostname == "127.0.0.1" and endpoint.port is not None
    expected = endpoint.hostname, endpoint.port
    witness = HttpProxyWitness()

    async def copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while chunk := await reader.read(16384):
            writer.write(chunk)
            await writer.drain()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        witness.active.add(task)
        peer = None
        copies: list[asyncio.Task[None]] = []
        try:
            block = await reader.readuntil(b"\r\n\r\n")
            assert len(block) <= 32768
            lines = block.split(b"\r\n")
            method, destination, version = lines[0].decode("ascii").split(" ")
            headers = [line for line in lines[1:] if line]
            authentication = next(
                (
                    line.split(b":", 1)[1].strip().decode("ascii")
                    for line in headers
                    if line.lower().startswith(b"proxy-authorization:")
                ),
                None,
            )
            witness.requests.append((method, authentication))
            if credentials is not None:
                required = "Basic " + base64.b64encode(":".join(credentials).encode()).decode()
                if authentication != required:
                    writer.write(
                        b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="owned"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
                    )
                    await writer.drain()
                    return
            parsed = urlsplit("//" + destination if method == "CONNECT" else destination)
            assert (parsed.hostname, parsed.port) == expected, (
                "Proxy cannot contact another destination."
            )
            upstream, peer = await asyncio.open_connection(*expected)
            if method == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                # Proxy identity never reaches the Kubernetes endpoint.
                headers = [
                    line
                    for line in headers
                    if not line.lower().startswith((b"proxy-authorization:", b"connection:"))
                ]
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                peer.write(
                    f"{method} {path} {version}\r\n".encode()
                    + b"\r\n".join(headers)
                    + b"\r\nConnection: close\r\n\r\n"
                )
                await peer.drain()
            copies = [
                asyncio.create_task(copy(reader, peer)),
                asyncio.create_task(copy(upstream, writer)),
            ]
            await asyncio.wait(copies, return_when=asyncio.FIRST_COMPLETED)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except AssertionError as error:
            witness.failures.append(error)
        finally:
            try:
                await close_relays(copies, (peer, writer))
            finally:
                witness.active.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0, limit=32768, ssl=tls)
    login = f"{credentials[0]}:{credentials[1]}@" if credentials is not None else ""
    try:
        yield (
            f"{'https' if tls else 'http'}://{login}127.0.0.1:{server.sockets[0].getsockname()[1]}",
            witness,
        )
    finally:
        server.close()
        for task in tuple(witness.active):
            task.cancel()
        await asyncio.gather(*tuple(witness.active), return_exceptions=True)
        await server.wait_closed()
        assert not witness.active
        assert not witness.failures
