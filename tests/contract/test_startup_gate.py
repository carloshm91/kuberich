"""A cancelled pre-connect readiness wait cannot leak work or block a replacement."""

import asyncio

import pytest

from kuberich.domain.connections import ConnectionRequest, ConnectionState
from kuberich.errors import AppError
from kuberich.services.sessions import SessionService
from tests.support.connections import catalog_fixture, fake_api, namespaces


@pytest.mark.asyncio
async def test_context_replacement_cancels_the_owned_wait_before_any_client_or_request(tmp_path):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return namespaces("default", "team")

    entered, release = asyncio.Event(), asyncio.Event()

    async def ready():
        entered.set()
        await release.wait()

    async with fake_api(handler) as url:
        service = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        service.before_connect = ready
        first = asyncio.create_task(service.connect("kuberich-test-one"))
        replacement = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert service.observation.state is ConnectionState.CONNECTING
            assert service.client is None and requests == []
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert service.client is None and requests == []

            entered.clear()
            replacement = asyncio.create_task(service.connect("kuberich-test-Two"))
            await asyncio.wait_for(entered.wait(), 5)
            assert service.client is None and requests == []
            release.set()
            observed = await asyncio.wait_for(replacement, 5)
            assert observed.state is ConnectionState.CONNECTED
            assert observed.identity.context == "kuberich-test-Two"
            assert requests == ["/api/v1/namespaces"]
        finally:
            for task in (first, replacement):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (first, replacement) if task is not None),
                return_exceptions=True,
            )
            await service.close()
        assert service.client is None


@pytest.mark.asyncio
async def test_readiness_failure_keeps_config_error_classification_and_owned_cleanup(tmp_path):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return namespaces("default")

    async def unavailable():
        raise AppError("Owned readiness is unavailable.")

    async with fake_api(handler) as url:
        service = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        service.before_connect = unavailable
        try:
            observed = await service.connect("kuberich-test-one")
            assert observed.state is ConnectionState.CONFIG_ERROR
            assert service.client is None and requests == []
        finally:
            await service.close()
