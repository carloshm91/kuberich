"""Actual authenticated Service-proxy reads, availability and drained cancellation."""

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from aiohttp import web

import kuberich.services.history as history_service
from kuberich.domain.history import HistoryBackend, HistoryStatus
from kuberich.services.history import HistoryReader
from tests.support.resources import reader_fixture

NOW = datetime(2026, 1, 1, tzinfo=UTC)
BACKEND = HistoryBackend(
    "observability", "prometheus", cluster_label="cluster", cluster_value="owned"
)


def payload(request, *, value=None, empty=False, warning=False):
    values = [
        [
            stamp,
            value if value is not None else "0" if "rate(" in request.query["query"] else "1048576",
        ]
        for stamp in range(
            int(request.query["start"]), int(request.query["end"]) + 1, int(request.query["step"])
        )
    ]
    result = {
        "status": "success",
        "data": {"resultType": "matrix", "result": [] if empty else [{"values": values}]},
    }
    if warning:
        result["warnings"] = ["synthetic private warning"]
    return result


@pytest.mark.asyncio
async def test_queries_use_exact_relative_path_client_credentials_and_numeric_units(tmp_path):
    calls = []

    async def handler(request):
        calls.append((request.path, request.headers.get("Authorization"), dict(request.query)))
        assert request.path == BACKEND.path
        return web.json_response(payload(request))

    async with reader_fixture(tmp_path, handler) as reader:
        report = await HistoryReader().read(reader.session, BACKEND, "team", now=NOW)
    assert report.status is HistoryStatus.VALID and report.observed_at == NOW
    assert len(calls) == 2 and {auth for _, auth, _ in calls} == {"Bearer synthetic"}
    assert all(
        'cluster="owned"' in query["query"] and 'namespace="team"' in query["query"]
        for _, _, query in calls
    )
    assert all(query["timeout"] == "8s" and query["step"] == "15" for _, _, query in calls)
    assert report.series[0].unit == "cores" and report.series[0].points[-1].value == Decimal(0)
    assert report.series[1].unit == "bytes" and report.series[1].points[-1].value == 1048576
    assert "Configured cluster selector" in report.scope_label
    assert "scrape freshness" in report.detail


@pytest.mark.asyncio
async def test_no_backend_and_conflicting_namespace_make_no_network_request(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.Response(status=500)

    async with reader_fixture(tmp_path, handler) as reader:
        empty = await HistoryReader().read(reader.session, None, "team")
        conflict = await HistoryReader().read(
            reader.session,
            HistoryBackend("observability", "prometheus", matchers=(("namespace", "other"),)),
            "team",
            now=NOW,
        )
    assert empty.status is HistoryStatus.UNCONFIGURED
    assert (
        conflict.status is HistoryStatus.FAILED and "scope is unavailable" in conflict.scope_label
    )
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (403, HistoryStatus.FORBIDDEN),
        (404, HistoryStatus.UNAVAILABLE),
        (503, HistoryStatus.UNAVAILABLE),
        (401, HistoryStatus.FAILED),
        (500, HistoryStatus.FAILED),
    ],
)
async def test_failed_proxy_reads_do_not_become_zero_history(tmp_path, code, status):
    async def handler(request):
        return web.Response(status=code, text="synthetic private response")

    async with reader_fixture(tmp_path, handler) as reader:
        report = await HistoryReader().read(reader.session, BACKEND, None, now=NOW)
    assert report.status is status and all(not item.points for item in report.series)
    assert "private" not in repr(report)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,status",
    [
        ("empty", HistoryStatus.NO_DATA),
        ("warning", HistoryStatus.PARTIAL),
        ("missing-memory", HistoryStatus.PARTIAL),
        ("failed-memory", HistoryStatus.PARTIAL),
        ("malformed", HistoryStatus.FAILED),
        ("oversized", HistoryStatus.FAILED),
    ],
)
async def test_empty_partial_malformed_and_bounded_bodies_remain_explicit(tmp_path, mode, status):
    async def handler(request):
        memory = "working_set" in request.query["query"]
        if mode == "oversized":
            return web.Response(text='{"padding":"' + "x" * (1024 * 1024) + '"}')
        if mode == "malformed":
            return web.json_response({"wrong": True})
        if mode == "failed-memory" and memory:
            return web.Response(status=500)
        return web.json_response(
            payload(
                request,
                empty=mode == "empty" or (mode == "missing-memory" and memory),
                warning=mode == "warning",
            )
        )

    async with reader_fixture(tmp_path, handler) as reader:
        report = await HistoryReader().read(reader.session, BACKEND, None, now=NOW)
    assert report.status is status
    if mode in {"missing-memory", "failed-memory"}:
        assert report.series[0].points[-1].value == 0
    assert "synthetic private warning" not in report.detail


@pytest.mark.asyncio
async def test_redirects_cannot_send_kubernetes_credentials_to_another_path(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path == BACKEND.path:
            raise web.HTTPFound("/untrusted-redirect")
        raise AssertionError("History followed a redirect with Kubernetes credentials")

    async with reader_fixture(tmp_path, handler) as reader:
        report = await HistoryReader().read(reader.session, BACKEND, None, now=NOW)
    assert report.status is HistoryStatus.FAILED
    assert calls == [BACKEND.path, BACKEND.path]


@pytest.mark.asyncio
async def test_timeout_and_transport_failure_clear_history_instead_of_reusing_it(
    tmp_path, monkeypatch
):
    async def handler(request):
        await asyncio.sleep(0.2)
        return web.json_response(payload(request))

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:
        result = await HistoryReader().read(reader.session, BACKEND, None, now=NOW)
        assert result.status is HistoryStatus.FAILED

        async def timed_out(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr(reader.session, "get_json", timed_out)
        assert (
            await HistoryReader().read(reader.session, BACKEND, None, now=NOW)
        ).status is HistoryStatus.FAILED


@pytest.mark.asyncio
async def test_cancellation_propagates_and_drains_a_held_parser_even_after_second_interrupt(
    tmp_path, monkeypatch
):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = history_service.parse_history_range

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        try:
            return original(*args, **kwargs)
        finally:
            finished.set()

    async def handler(request):
        return web.json_response(payload(request))

    monkeypatch.setattr(history_service, "parse_history_range", held)
    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(HistoryReader().read(reader.session, BACKEND, None, now=NOW))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 5), 6)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
