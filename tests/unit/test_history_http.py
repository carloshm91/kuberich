"""External credentials and URL ownership stay private and bounded."""

import asyncio
import os
import ssl
import threading
from pathlib import Path

import pytest

from kuberich.adapters.history_http import ExternalHistoryTransport
from kuberich.config.observability import parse_observability
from kuberich.domain.history import ExternalHistoryBackend
from kuberich.errors import AppError


def token_transport(path):
    return ExternalHistoryTransport(
        ExternalHistoryBackend("https://127.0.0.1:1", bearer_token_file=path)
    )


def test_configuration_is_offline_and_separates_sources(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Configuration read a credential or TLS file")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(ssl, "create_default_context", forbidden)
    settings = parse_observability(
        {
            "history": {
                "url": "https://metrics.example.test/select/0/prometheus/",
                "ca_file": str(tmp_path / "ca"),
                "bearer_token_file": str(tmp_path / "token"),
                "provider": "victoriametrics",
                "node_matchers": {"job": "node"},
                "state_matchers": {"job": "state"},
                "rate_window_seconds": 120,
            }
        }
    )
    options = settings.history
    assert options.provider == "victoriametrics"
    assert options.endpoint.prefix == "/select/0/prometheus"
    assert options.node_matchers == (("job", "node"),)
    assert options.state_matchers == (("job", "state"),)
    assert "token" not in repr(options) and str(tmp_path) not in repr(options)
    assert ExternalHistoryTransport(options.endpoint).operation_count == 0


@pytest.mark.parametrize(
    "raw",
    [
        {"url": 3},
        {"url": "https://metrics.test", "namespace": "team"},
        {"url": "https://metrics.test", "ca_file": 3},
        {"url": "https://metrics.test", "ca_file": ""},
        {"url": "https://metrics.test", "ca_file": "bad\n"},
        {"url": "https://metrics.test", "bearer_token_file": "x" * 4097},
        {"url": "http://metrics.test", "bearer_token_file": "private"},
        {"namespace": "team", "service": "metrics", "ca_file": "private"},
        {"namespace": "team", "service": "metrics", "node_matchers": []},
        {"namespace": "team", "service": "metrics", "state_matchers": []},
        {"url": "https://metrics.test", "provider": 3},
        {"url": "https://metrics.test", "profile": 3},
        {"namespace": "team", "service": "metrics", "api_prefix": 3},
        {"url": "https://metrics.test", "provider": "unsupported"},
    ],
)
def test_configuration_rejects_mixed_or_invalid_declarations(raw):
    with pytest.raises(AppError):
        parse_observability({"history": raw})


@pytest.mark.parametrize("body", [b"", b"two tokens", b"line\nbreak", b"\xff", b"x" * 8193])
@pytest.mark.asyncio
async def test_token_is_bounded_and_has_no_whitespace_or_error_body(tmp_path, body):
    token = tmp_path / "synthetic-token-private-path"
    token.write_bytes(body)
    token.chmod(0o600)
    transport = token_transport(token)
    try:
        with pytest.raises(AppError) as error:
            await transport.prepare()
        assert str(token) not in str(error.value)
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_token_private_revision_rotates_and_symlinks_are_rejected(tmp_path):
    token = tmp_path / "private-token"
    token.write_text("synthetic-one\n")
    token.chmod(0o600)
    transport = token_transport(token)
    try:
        first = await transport.prepare()
        assert first == transport.auth_revision and "synthetic-one" not in repr(transport)
        token.write_text("synthetic-two")
        assert await transport.prepare() != first
        token.chmod(0o644)
        with pytest.raises(AppError):
            await transport.prepare()
    finally:
        await transport.close()
    token.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(token)
    for path in (link, tmp_path, tmp_path / "missing"):
        rejected = token_transport(path)
        try:
            with pytest.raises(AppError):
                await rejected.prepare()
        finally:
            await rejected.close()


@pytest.mark.asyncio
async def test_token_replacement_during_read_is_rejected(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("synthetic-one")
    token.chmod(0o600)
    original = os.read

    def replace(descriptor, count):
        data = original(descriptor, count)
        replacement = tmp_path / "replacement"
        replacement.write_text("synthetic-two")
        replacement.chmod(0o600)
        replacement.replace(token)
        return data

    monkeypatch.setattr(os, "read", replace)
    transport = token_transport(token)
    try:
        with pytest.raises(AppError):
            await transport.prepare()
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_token_other_owner_and_tls_configuration_errors_are_sanitized(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("synthetic-one")
    token.chmod(0o600)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(token).st_uid + 1)
    transport = token_transport(token)
    invalid_ca = ExternalHistoryTransport(
        ExternalHistoryBackend("https://127.0.0.1:1", ca_file=tmp_path / "missing-ca")
    )
    try:
        for rejected in (transport, invalid_ca):
            with pytest.raises(AppError) as error:
                await rejected.prepare()
            assert str(tmp_path) not in str(error.value)
    finally:
        await transport.close()
        await invalid_ca.close()


@pytest.mark.asyncio
async def test_closed_transport_and_invalid_input_do_no_network():
    with pytest.raises(AppError):
        ExternalHistoryTransport(object())
    transport = ExternalHistoryTransport(ExternalHistoryBackend("http://127.0.0.1:1"))
    assert transport.auth_revision == "unprepared"
    for suffix, limit in (("../query", 10), ("query", 0), ("query", 1048577), ("query", True)):
        with pytest.raises(AppError):
            await transport.get_json(suffix, {}, max_bytes=limit)
    await transport.close()
    await transport.close()
    with pytest.raises(AppError):
        await transport.prepare()
    with pytest.raises(AppError):
        await transport.get_json("query", {}, max_bytes=1024)


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_private_token_worker(tmp_path, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    token = tmp_path / "token"
    token.write_text("synthetic-independent")
    token.chmod(0o600)
    original = os.read

    def held(descriptor, maximum):
        entered.set()
        try:
            assert release.wait(5)
            return original(descriptor, maximum)
        finally:
            finished.set()

    monkeypatch.setattr(os, "read", held)
    transport = token_transport(token)
    task = asyncio.create_task(transport.get_json("query", {}, max_bytes=1024))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await transport.close()
    assert finished.is_set() and transport.operation_count == 0


@pytest.mark.asyncio
async def test_close_owns_a_standalone_credential_preparation_through_repeated_cancel(
    tmp_path, monkeypatch
):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    token = tmp_path / "token"
    token.write_text("synthetic-independent")
    token.chmod(0o600)
    original = os.read

    def held(descriptor, maximum):
        entered.set()
        try:
            assert release.wait(5)
            return original(descriptor, maximum)
        finally:
            finished.set()

    monkeypatch.setattr(os, "read", held)
    transport = token_transport(token)
    preparing = asyncio.create_task(transport.prepare())
    assert await asyncio.to_thread(entered.wait, 5)
    closing = asyncio.create_task(transport.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    assert not closing.done()
    release.set()
    await preparing
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert finished.is_set()
    await transport.close()


@pytest.mark.asyncio
async def test_short_regular_file_read_does_not_install_partial_bearer(tmp_path, monkeypatch):
    token = tmp_path / "independent-token"
    token.write_text("synthetic-independent")
    token.chmod(0o600)
    original = os.read
    monkeypatch.setattr(os, "read", lambda descriptor, maximum: original(descriptor, maximum)[:1])
    transport = token_transport(token)
    try:
        with pytest.raises(AppError):
            await transport.prepare()
    finally:
        await transport.close()
