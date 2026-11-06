"""Per-operation GET bounds reach the owned HTTP transport without changing defaults."""

import asyncio

import pytest
from aiohttp import web

from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    ResponseLimitExceeded,
)
from kuberich.domain.read_budget import ReadBudget
from kuberich.errors import AppError
from kuberich.services.resources import MAX_GET_RESPONSE_BYTES, ResourceReader
from tests.support.resources import item, pod_resource, reader_fixture


@pytest.mark.asyncio
async def test_default_get_keeps_the_original_injected_client_call_shape():
    calls = []

    class Client:
        timeout = 5

        async def get_json(self, path, *, accept, params):
            calls.append((path, accept, params))
            return item()

    reader = ResourceReader(Client())
    record = await reader.get(pod_resource(), "one", "team")
    assert record.uid == "owned-one"
    assert calls == [("/api/v1/namespaces/team/pods/one", "application/json", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "128", MAX_GET_RESPONSE_BYTES + 1])
async def test_invalid_limit_rejects_before_budget_or_transport(tmp_path, limit):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(item())

    async with reader_fixture(tmp_path, handler) as base:
        budget = ReadBudget(1)
        reader = ResourceReader(base.session, budget=budget)
        with pytest.raises(AppError, match="response limit"):
            await reader.get(pod_resource(), "one", "team", max_bytes=limit)
        assert budget.used == 0 and calls == []


@pytest.mark.asyncio
async def test_explicit_limit_accepts_valid_body_and_charges_one_get(tmp_path):
    calls = []

    async def handler(request):
        calls.append((request.method, request.path, dict(request.query)))
        return web.json_response(item())

    async with reader_fixture(tmp_path, handler) as base:
        budget = ReadBudget(1)
        reader = ResourceReader(base.session, budget=budget)
        record = await reader.get(pod_resource(), "one", "team", max_bytes=4096)
        assert record.uid == "owned-one" and budget.used == 1
        assert calls == [("GET", "/api/v1/namespaces/team/pods/one", {})]


@pytest.mark.asyncio
async def test_small_limit_aborts_a_chunked_body_before_the_remainder(tmp_path):
    sent = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    body = web.json_response({**item(), "note": "synthetic-hidden-marker" * 128}).body
    assert body is not None

    async def handler(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        response.enable_chunked_encoding()
        await response.prepare(request)
        try:
            await response.write(body[:512])
            sent.set()
            await release.wait()
            await response.write(body[512:])
            await response.write_eof()
        except ConnectionResetError:
            pass
        finally:
            finished.set()
        return response

    try:
        async with reader_fixture(tmp_path, handler) as reader:
            with pytest.raises(ConnectionProblem) as caught:
                await reader.get(pod_resource(), "one", "team", max_bytes=128)
            assert sent.is_set() and not finished.is_set()
            assert caught.value.state is ConnectionState.API_ERROR
            assert isinstance(caught.value, ResponseLimitExceeded) and caught.value.limit == 128
            assert "synthetic-hidden-marker" not in str(caught.value)
            release.set()
    finally:
        release.set()
    assert finished.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(500, "synthetic-error-body"), (200, "{invalid-json")])
async def test_http_and_malformed_json_are_not_reported_as_body_limit(tmp_path, status, body):
    async def handler(request):
        return web.Response(status=status, text=body, content_type="application/json")

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as caught:
            await reader.get(pod_resource(), "one", "team", max_bytes=4096)
        assert caught.value.state is ConnectionState.API_ERROR
        assert not isinstance(caught.value, ResponseLimitExceeded)
        assert isinstance(caught.value, HttpProblem) is (status == 500)
        assert body not in str(caught.value)
