"""Captured routing/trust fingerprints exclude tokens and drain their private file worker."""

import asyncio
import threading

import pytest

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell import session_fingerprint
from kuberich.errors import AppError
from tests.contract.test_node_shell import source_fixture


@pytest.mark.asyncio
async def test_fingerprint_requires_an_explicitly_connected_session(tmp_path):
    async with source_fixture(tmp_path) as values:
        client = values[1]
        configuration = client.configuration
        client.configuration = None
        try:
            with pytest.raises(AppError, match="explicitly connected"):
                await session_fingerprint(client)
        finally:
            client.configuration = configuration


@pytest.mark.asyncio
async def test_ambiguous_bearer_identity_matches_only_original_live_session(tmp_path):
    async with source_fixture(tmp_path) as values:
        client = values[1]
        original = await session_fingerprint(client)
        client.context.user.data["token"] = "rotated-synthetic-token"
        assert await session_fingerprint(client) == original
        reopened = KubernetesSession(client.context, 2)
        try:
            await reopened.open()
            assert await session_fingerprint(reopened) != original
            client.context.user.data["username"] = "synthetic-stable-identity"
            assert await session_fingerprint(reopened) == await session_fingerprint(client)
        finally:
            await reopened.close()


@pytest.mark.asyncio
async def test_provider_identity_excludes_rotating_credentials_but_binds_configuration(tmp_path):
    async with source_fixture(tmp_path) as values:
        client = values[1]
        client.context.user.data["auth-provider"] = {
            "name": "oidc",
            "config": {
                "issuer": "https://fixture.invalid",
                "access-token": "synthetic-a",
                "id-token": "synthetic-b",
                "refresh-token": "synthetic-c",
                "expiry": "old",
            },
        }
        original = await session_fingerprint(client)
        config = client.context.user.data["auth-provider"]["config"]
        config.update(
            {
                "access-token": "rotated",
                "id-token": "rotated",
                "refresh-token": "rotated",
                "expiry": "new",
            }
        )
        assert await session_fingerprint(client) == original
        config["issuer"] = "https://other-fixture.invalid"
        assert await session_fingerprint(client) != original


@pytest.mark.asyncio
async def test_fingerprint_reads_captured_ca_and_public_certificate_not_their_paths(tmp_path):
    async with source_fixture(tmp_path) as values:
        client = values[1]
        configuration = client.configuration
        ca, certificate = tmp_path / "owned-ca", tmp_path / "owned-public-certificate"
        ca.write_bytes(b"synthetic-trust")
        certificate.write_bytes(b"synthetic-public-certificate")
        configuration.host, configuration.verify_ssl = "https://fixture.invalid", True
        configuration.ssl_ca_cert, configuration.cert_file = str(ca), str(certificate)
        original = await session_fingerprint(client)
        alias = tmp_path / "another-public-certificate"
        alias.write_bytes(certificate.read_bytes())
        configuration.cert_file = str(alias)
        assert await session_fingerprint(client) == original
        alias.write_bytes(b"different-public-certificate")
        assert await session_fingerprint(client) != original


@pytest.mark.asyncio
async def test_fingerprint_uses_effective_default_trust_and_refuses_missing_trust(
    tmp_path, monkeypatch
):
    class Trust:
        def __init__(self):
            self.certificates = [b"synthetic-der-two", b"synthetic-der-one"]

        def get_ca_certs(self, *, binary_form):
            assert binary_form is True
            return self.certificates

    trust = Trust()
    async with source_fixture(tmp_path) as values:
        monkeypatch.setattr(
            "kuberich.adapters.node_shell.ssl.create_default_context", lambda: trust
        )
        client = values[1]
        client.configuration.host = "https://fixture.invalid"
        client.configuration.verify_ssl = True
        original = await session_fingerprint(client)
        trust.certificates.reverse()
        assert await session_fingerprint(client) == original
        trust.certificates = []
        with pytest.raises(AppError, match="trust material"):
            await session_fingerprint(client)


@pytest.mark.asyncio
async def test_cancelled_fingerprint_waits_for_its_owned_worker(tmp_path, monkeypatch):
    from kuberich.domain.node_shell_journal import connection_fingerprint

    entered, release = threading.Event(), threading.Event()

    def held(**kwargs):
        entered.set()
        assert release.wait(5)
        return connection_fingerprint(**kwargs)

    monkeypatch.setattr("kuberich.adapters.node_shell.connection_fingerprint", held)
    async with source_fixture(tmp_path) as values:
        operation = asyncio.create_task(session_fingerprint(values[1]))
        async with asyncio.timeout(5):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
