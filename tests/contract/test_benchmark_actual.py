"""Pinned real Vegeta talks only to owned HTTP servers through production execution."""

import asyncio
import json
import os
import stat
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from aiohttp import web

from kuberich.domain.benchmark_results import BenchmarkProvenance, BenchmarkResult
from kuberich.domain.benchmarks import LoadOptions, RequestOptions
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmark_tool import BenchmarkTool
from scripts.benchmark_tools import verify_benchmark_binary
from tests.support.benchmarks import gone


@pytest_asyncio.fixture
async def actual_tool(tmp_path):
    configured = os.environ.get("KUBERICH_TEST_VEGETA")
    if configured is None:
        pytest.skip("Explicit KUBERICH_TEST_VEGETA is required for actual optional-tool contracts.")
    executable = Path(configured)
    assert executable.is_absolute(), "The configured actual fixture must be an absolute path."
    # Authenticate the reviewed host-specific bytes before executing any configured file.
    await asyncio.to_thread(verify_benchmark_binary, executable)
    tool = BenchmarkTool(executable, AccessPolicy(False), tmp_path, lambda: None)
    version = await tool.probe()
    try:
        yield tool, version
    finally:
        for pid in tool.process_ids:
            await gone(pid)
        assert not tuple(tmp_path.glob("benchmark-*"))


class OwnedHTTP:
    def __init__(self, handler):
        self.handler = handler
        self.observed = []
        self.arrived = asyncio.Event()
        self.drained = asyncio.Event()
        self.drained.set()
        self.active = self.peak = 0
        self.port = None

    async def dispatch(self, request):
        index = len(self.observed)
        self.observed.append((request.method, request.path, time.monotonic()))
        self.arrived.set()
        self.drained.clear()
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            return await self.handler(request, index)
        finally:
            self.active -= 1
            if not self.active:
                self.drained.set()


@asynccontextmanager
async def owned_http(handler):
    observed = OwnedHTTP(handler)
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", observed.dispatch)
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=3)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    try:
        await site.start()
        observed.port = runner.addresses[0][1]
        yield observed
    finally:
        await runner.cleanup()
    assert observed.active == 0


@pytest.mark.asyncio
async def test_actual_post_private_request_files_and_normalized_success(actual_tool, tmp_path):
    tool, version = actual_tool
    received = []

    async def handler(request, index):
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer owned-synthetic-auth"
        assert await request.read() == b"owned-synthetic-body"
        assert request.query["private"] == "owned-synthetic-query"
        directories = tuple(tmp_path.glob("benchmark-*"))
        assert len(directories) == 1
        assert stat.S_IMODE(directories[0].stat().st_mode) == 0o700
        staged = tuple(directories[0].iterdir())
        assert len(staged) == 1 and stat.S_IMODE(staged[0].stat().st_mode) == 0o600
        target = json.loads(staged[0].read_bytes())
        assert target["header"]["Authorization"] == ["Bearer owned-synthetic-auth"]
        received.append(index)
        return web.Response(text="owned-response-body")

    async with owned_http(handler) as server:
        metrics = await tool.execute(
            RequestOptions(
                method="POST",
                target="/owned?private=owned-synthetic-query",
                headers=(("Authorization", "Bearer owned-synthetic-auth"),),
                body=b"owned-synthetic-body",
            ),
            LoadOptions(duration_seconds=2, timeout_seconds=1),
            server.port,
            version=version,
        )
    assert metrics.attempts == len(received) == len(server.observed) >= 1
    assert metrics.status_counts == ((200, metrics.attempts),)
    assert metrics.successful_requests == metrics.attempts
    assert metrics.transport_failures == metrics.http_failures == 0
    assert not metrics.errors_present and len(tool.process_ids) == 3
    assert "owned-synthetic" not in repr(metrics)


@pytest.mark.asyncio
async def test_actual_mixed_http_status_counts_are_not_distinct_error_strings(actual_tool):
    tool, version = actual_tool
    statuses = []

    async def handler(request, index):
        assert request.path == "/mixed"
        status = (200, 302, 404, 503)[index % 4]
        statuses.append(status)
        return web.Response(status=status, headers={"Location": "/must-not-follow"}, text="owned")

    async with owned_http(handler) as server:
        metrics = await tool.execute(
            RequestOptions(target="/mixed"),
            LoadOptions(rate=4, duration_seconds=2, timeout_seconds=1),
            server.port,
            version=version,
        )
    assert {200, 302, 404, 503} <= set(statuses)
    assert metrics.attempts == len(statuses) == len(server.observed)
    assert metrics.status_counts == tuple(sorted(Counter(statuses).items()))
    assert metrics.successful_requests == sum(200 <= status < 400 for status in statuses)
    assert metrics.http_failures == sum(status >= 400 for status in statuses)
    assert metrics.redirects == statuses.count(302) and metrics.transport_failures == 0
    assert metrics.errors_present


@pytest.mark.asyncio
async def test_actual_redirect_is_not_followed_and_poison_proxy_receives_no_traffic(
    actual_tool, monkeypatch
):
    tool, version = actual_tool

    async def proxy(request, index):
        return web.Response(status=502)

    async def redirect(request, index):
        assert request.path == "/redirect"
        return web.Response(status=302, headers={"Location": "/must-not-follow"})

    async with owned_http(proxy) as poisoned, owned_http(redirect) as server:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            monkeypatch.setenv(name, f"http://127.0.0.1:{poisoned.port}")
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        metrics = await tool.execute(
            RequestOptions(target="/redirect"),
            LoadOptions(rate=2, duration_seconds=1, timeout_seconds=1),
            server.port,
            version=version,
        )
        assert poisoned.observed == []
    # This observes actual loopback traffic; separate argv/environment contracts
    # establish the minimal environment, independent of Go's loopback proxy rule.
    assert {path for _, path, _ in server.observed} == {"/redirect"}
    assert metrics.status_counts == ((302, metrics.attempts),)
    assert metrics.successful_requests == metrics.redirects == len(server.observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "truncated-body"])
async def test_actual_transport_failures_can_follow_server_acceptance(actual_tool, mode):
    tool, version = actual_tool
    headers_sent = []

    async def handler(request, index):
        if mode == "timeout":
            await asyncio.sleep(1.25)
            return web.Response(text="owned-response-after-client-timeout")
        response = web.StreamResponse(status=200, headers={"Content-Length": "100"})
        await response.prepare(request)
        headers_sent.append(200)
        await response.write(b"short")
        assert request.transport is not None
        request.transport.close()
        return response

    async with owned_http(handler) as server:
        metrics = await tool.execute(
            RequestOptions(target="/owned"),
            LoadOptions(duration_seconds=1, timeout_seconds=1),
            server.port,
            version=version,
        )
        await asyncio.wait_for(server.drained.wait(), 3)
    assert metrics.attempts == len(server.observed) >= 1
    assert metrics.status_counts == ((0, metrics.attempts),)
    assert metrics.transport_failures == metrics.attempts
    assert metrics.successful_requests == metrics.http_failures == 0 and metrics.errors_present
    if mode == "truncated-body":
        assert headers_sent == [200] * metrics.attempts
    if metrics.duration_ns == 0:
        assert metrics.actual_rate is metrics.throughput is None
    # A timeout can leave remote processing alive after its local worker ends.
    # Do not claim remote handler concurrency is bounded by local worker count.


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_actual_worker_cap_and_paced_load_metrics_are_bounded(
    actual_tool, concurrency, request
):
    tool, version = actual_tool

    async def handler(request, index):
        if concurrency == 1 and index == 0:
            await asyncio.sleep(0.45)
        elif concurrency == 2:
            await asyncio.sleep(0.12)
        return web.Response(text="owned-worker-response")

    load = LoadOptions(
        rate=5 if concurrency == 1 else 20,
        concurrency=concurrency,
        duration_seconds=1,
        timeout_seconds=2,
    )
    async with owned_http(handler) as server:
        metrics = await tool.execute(RequestOptions(), load, server.port, version=version)
    assert 1 <= server.peak <= concurrency
    assert 1 <= metrics.attempts == len(server.observed) <= load.nominal_requests + 1
    assert metrics.status_counts == ((200, metrics.attempts),)
    assert metrics.successful_requests == metrics.attempts and not metrics.errors_present
    if metrics.duration_ns:
        assert metrics.actual_rate == pytest.approx(metrics.attempts * 1e9 / metrics.duration_ns)
    # Requested pacing can catch up after a slow worker. Keep actual intervals
    # observable without turning a short-interval timing target into a hard gate.
    intervals = [b[2] - a[2] for a, b in zip(server.observed, server.observed[1:], strict=False)]
    request.node.user_properties.extend(
        (
            ("requested_rate", load.rate),
            ("minimum_observed_interval_seconds", min(intervals) if intervals else "N/A"),
            ("catch_up_observed", any(interval < 0.5 / load.rate for interval in intervals)),
        )
    )


@pytest.mark.asyncio
async def test_actual_cancellation_reaps_load_and_observes_no_new_requests(actual_tool, tmp_path):
    tool, version = actual_tool

    async def handler(request, index):
        return web.Response(text="owned-cancel-response")

    async with owned_http(handler) as server:
        running = asyncio.create_task(
            tool.execute(
                RequestOptions(),
                LoadOptions(rate=5, duration_seconds=30, timeout_seconds=1),
                server.port,
                version=version,
            )
        )
        try:
            await asyncio.wait_for(server.arrived.wait(), 5)
        finally:
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        for pid in tool.process_ids:
            await gone(pid)
        assert not tuple(tmp_path.glob("benchmark-*"))
        await asyncio.wait_for(server.drained.wait(), 3)
        count = len(server.observed)
        await asyncio.sleep(0.35)
        assert len(server.observed) == count >= 1


@pytest.mark.asyncio
async def test_actual_slow_worker_may_start_after_duration_within_original_wall_budget(
    actual_tool, tmp_path
):
    tool, version = actual_tool

    async def handler(request, index):
        if index == 0:
            await asyncio.sleep(4)
        return web.Response(text="owned delayed worker")

    load = LoadOptions(rate=5, duration_seconds=1, timeout_seconds=5)
    started = datetime.now(UTC)
    async with owned_http(handler) as server:
        metrics = await tool.execute(RequestOptions(), load, server.port, version=version)
    assert metrics.attempts == len(server.observed) == 2
    assert metrics.duration_ns > (load.duration_seconds + 2) * 1e9
    assert (
        metrics.duration_ns + metrics.wait_ns
        <= (load.duration_seconds + load.timeout_seconds + 2) * 1e9
    )
    value = BenchmarkResult(
        uuid4(),
        started,
        datetime.now(UTC),
        version,
        BenchmarkProvenance("owned-loopback", "synthetic", "slow", "synthetic-uid", 8080),
        "GET",
        load,
        "complete",
        metrics,
    )
    store = BenchmarkStore(tmp_path / "saved-slow")
    saved = await store.save(value)
    assert await BenchmarkStore(store.default_root).read(saved.ref) == value
