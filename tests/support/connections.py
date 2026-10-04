"""Owned fake API/TLS and synthetic kubeconfig builders."""

import base64
import ipaddress
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from kubetrol.config.catalog import KubeCatalog, load_catalog
from kubetrol.domain.connections import ConnectionRequest


def catalog_fixture(
    directory: Path, server: str, user: dict | None = None, cluster: dict | None = None
) -> KubeCatalog:
    data = {
        "current-context": "kubetrol-test-one",
        "contexts": [
            {
                "name": "kubetrol-test-one",
                "context": {"cluster": "owned", "user": "owned", "namespace": "team"},
            },
            {
                "name": "kubetrol-test-Two",
                "context": {"cluster": "owned", "user": "owned", "namespace": "default"},
            },
        ],
        "clusters": [{"name": "owned", "cluster": {"server": server, **(cluster or {})}}],
        "users": [{"name": "owned", "user": user if user is not None else {"token": "synthetic"}}],
    }
    path = directory / "fixture-config"
    path.write_text(yaml.safe_dump(data))
    return load_catalog(ConnectionRequest(kubeconfig=str(path)), {})


def namespaces(*names: str, continuation: str = "") -> web.Response:
    return web.json_response(
        {
            "kind": "NamespaceList",
            "metadata": {"continue": continuation},
            "items": [{"metadata": {"name": name}} for name in names],
        }
    )


@asynccontextmanager
async def fake_api(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    tls: ssl.SSLContext | None = None,
) -> AsyncIterator[str]:
    app = web.Application()
    app.router.add_get("/api/v1/namespaces", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    address = runner.addresses[0]
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{address[1]}"
    finally:
        await runner.cleanup()


def certificate(directory: Path, *, client_auth: bool = False) -> tuple[ssl.SSLContext, dict]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "kubetrol-test-local")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    cert_path, key_path = directory / "fixture-cert", directory / "fixture-key"
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    if client_auth:
        tls.verify_mode = ssl.CERT_REQUIRED
        tls.load_verify_locations(cafile=str(cert_path))
    return tls, {
        "certificate-authority-data": base64.b64encode(cert_pem).decode(),
        "client-certificate-data": base64.b64encode(cert_pem).decode(),
        "client-key-data": base64.b64encode(key_pem).decode(),
    }
