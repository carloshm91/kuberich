"""Owned SOCKS5 fixture that can relay only one predeclared loopback destination."""

import asyncio
import ipaddress
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from tests.support.proxy_transport import close_relays


@dataclass
class SocksWitness:
    destinations: list[tuple[str, int]] = field(default_factory=list)
    authentications: list[tuple[bytes, bytes]] = field(default_factory=list)
    active: set[asyncio.Task] = field(default_factory=set)
    failures: list[AssertionError] = field(default_factory=list)


@asynccontextmanager
async def socks_proxy(
    target: str,
    *,
    credentials: tuple[str, str] | None = None,
    mode: str = "relay",
    aliases: tuple[str, ...] = (),
) -> AsyncIterator[tuple[str, SocksWitness]]:
    endpoint = urlsplit(target)
    assert endpoint.hostname == "127.0.0.1" and endpoint.port is not None
    expected = endpoint.hostname, endpoint.port
    assert all(alias.endswith(".invalid") for alias in aliases)
    witness = SocksWitness()

    async def relay(source, destination):
        while data := await source.read(16384):
            destination.write(data)
            await destination.drain()

    async def serve(reader, writer):
        task = asyncio.current_task()
        witness.active.add(task)
        peer = None
        copies = []
        try:
            version, length = await reader.readexactly(2)
            assert version == 5
            methods = await reader.readexactly(length)
            method = 2 if credentials is not None else 0
            writer.write(bytes((5, method if method in methods else 255)))
            await writer.drain()
            if method not in methods:
                return
            if credentials is not None:
                version, length = await reader.readexactly(2)
                assert version == 1
                username = await reader.readexactly(length)
                length = (await reader.readexactly(1))[0]
                password = await reader.readexactly(length)
                witness.authentications.append((username, password))
                accepted = (username, password) == tuple(value.encode() for value in credentials)
                writer.write(bytes((1, 0 if accepted else 1)))
                await writer.drain()
                if not accepted:
                    return
            version, command, reserved, address_type = await reader.readexactly(4)
            assert (version, command, reserved) == (5, 1, 0)
            if address_type == 1:
                host = str(ipaddress.ip_address(await reader.readexactly(4)))
            elif address_type == 4:
                host = str(ipaddress.ip_address(await reader.readexactly(16)))
            else:
                assert address_type == 3
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode("ascii")
            port = int.from_bytes(await reader.readexactly(2), "big")
            witness.destinations.append((host, port))
            assert port == expected[1] and host in {expected[0], *aliases}, (
                "Proxy fixture cannot contact any other destination."
            )
            if mode == "hang":
                await asyncio.Event().wait()
            if mode == "disconnect":
                return
            writer.write(
                b"\x05"
                + (b"\x05" if mode == "reject" else b"\x00")
                + b"\x00\x01\x7f\x00\x00\x01"
                + port.to_bytes(2, "big")
            )
            await writer.drain()
            if mode == "reject":
                return
            upstream, peer = await asyncio.open_connection(*expected)
            copies = [
                asyncio.create_task(relay(reader, peer)),
                asyncio.create_task(relay(upstream, writer)),
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

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    login = f"{credentials[0]}:{credentials[1]}@" if credentials is not None else ""
    try:
        yield f"socks5://{login}127.0.0.1:{server.sockets[0].getsockname()[1]}", witness
    finally:
        server.close()
        for task in tuple(witness.active):
            task.cancel()
        await asyncio.gather(*tuple(witness.active), return_exceptions=True)
        await server.wait_closed()
        assert not witness.active
        assert not witness.failures
