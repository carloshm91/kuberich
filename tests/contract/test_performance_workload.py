"""Real loopback protocol, independent pacing and cleanup of the Q03 source."""

import asyncio
import json
import os
import signal
import sys
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from tests.support.performance_workload import PacedWorkload
from tests.support.workspace import wait_for


@asynccontextmanager
async def workload(rows=10000, *, event_history=None):
    source = PacedWorkload(rows)
    if event_history is not None:
        source.events = deque(maxlen=event_history)
    app = web.Application()
    app.router.add_get("/{path:.*}", source.handler)
    app.router.add_post("/__q03/{action}", source.control)
    runner = web.AppRunner(app, shutdown_timeout=0.2)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    source.workers = [
        asyncio.create_task(source.produce_resources()),
        asyncio.create_task(source.produce_logs()),
    ]
    try:
        async with aiohttp.ClientSession(
            base_url=f"http://127.0.0.1:{runner.addresses[0][1]}"
        ) as client:
            yield source, client
    finally:
        source.enabled.clear()
        source.closed.set()
        for task in source.workers:
            task.cancel()
        await asyncio.gather(*source.workers, return_exceptions=True)
        await runner.cleanup()
        assert source.stats["active_watches"] == source.stats["active_logs"] == 0
        assert not any(not task.done() for task in source.workers)


@pytest.mark.asyncio
async def test_ten_thousand_distinct_resources_page_without_omissions_or_extra_sources():
    async with workload() as (source, client):
        records, token = [], ""
        while True:
            async with client.get(
                "/api/v1/namespaces/team/pods", params={"limit": "500", "continue": token}
            ) as response:
                assert response.status == 200
                page = await response.json()
            assert page["metadata"]["resourceVersion"] == "q03/0"
            records.extend(page["items"])
            token = page["metadata"]["continue"]
            if not token:
                break
        assert len(records) == len({record["metadata"]["uid"] for record in records}) == 10000
        assert source.serial == source.log_serial == 0
        assert source.stats["list_pages"] == 20 and len(source.snapshots) == 0
        assert 10000 * len(source.line(1800000)) < 4 * 1024 * 1024
        assert len(source.line(1)) > 100 and len(source.line(1)) * source.LOG_BATCH <= 8192
        async with client.get("/api/v1/namespaces/default/pods") as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_snapshot_stays_frozen_while_independent_events_modify_every_row():
    async with workload(3) as (source, client):
        async with client.get("/api/v1/namespaces/team/pods", params={"limit": "1"}) as response:
            first = await response.json()
        async with client.post("/__q03/start") as response:
            assert response.status == 200
        await wait_for(lambda: source.serial >= 3)
        token = first["metadata"]["continue"]
        async with client.get(
            "/api/v1/namespaces/team/pods", params={"limit": "2", "continue": token}
        ) as response:
            rest = await response.json()
        assert rest["metadata"]["resourceVersion"] == "q03/0"
        assert [
            item["status"]["containerStatuses"][0]["restartCount"] for item in rest["items"]
        ] == [0, 0]
        async with client.get("/api/v1/namespaces/team/pods/q03-00001") as response:
            current = await response.json()
        assert current["metadata"]["resourceVersion"] != "q03/0"
        assert current["status"]["containerStatuses"][0]["restartCount"] >= 2
        assert len(source.snapshots) == 0


@pytest.mark.asyncio
async def test_both_streams_receive_independently_paced_sequences_and_pause_drains_workers():
    async with workload(10) as (source, client):
        watch = await client.get(
            "/api/v1/namespaces/team/pods", params={"watch": "true", "resourceVersion": "q03/0"}
        )
        logs = await client.get(
            "/api/v1/namespaces/team/pods/q03-00000/log", params={"follow": "true"}
        )
        assert watch.status == logs.status == 200
        assert b"q03-row-00000000000" in await logs.content.readline()
        events, lines = [], []

        async def read_events():
            async for line in watch.content:
                events.append(json.loads(line))

        async def read_logs():
            async for line in logs.content:
                lines.append(line)

        consumers = [asyncio.create_task(read_events()), asyncio.create_task(read_logs())]
        try:
            async with client.post("/__q03/start") as response:
                assert response.status == 200
            await asyncio.sleep(1.05)
            async with client.post("/__q03/pause") as response:
                assert response.status == 200
            await wait_for(lambda: all(task.done() for task in source.workers))
            await wait_for(lambda: len(events) == source.serial and len(lines) == source.log_serial)
            duration = source.paused - source.started
            assert abs(source.serial - 100 * duration) <= 3
            assert abs(source.log_serial - 2000 * duration) <= 40
            assert [event["object"]["metadata"]["resourceVersion"] for event in events] == [
                f"q03/{n}" for n in range(1, source.serial + 1)
            ]
            assert lines == [source.line(n) for n in range(1, source.log_serial + 1)]
            assert len(source.events) <= source.EVENT_HISTORY
            assert len(source.logs) <= source.LOG_CHUNKS
            assert source.receipt()["timing_samples"] is None
            assert source.receipt(include_timings=True)["timing_samples"]
            async with client.post("/__q03/start") as response:
                assert response.status == 409
        finally:
            watch.close()
            logs.close()
            for task in consumers:
                task.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)
            await wait_for(
                lambda: source.stats["active_watches"] == source.stats["active_logs"] == 0
            )


@pytest.mark.asyncio
async def test_expired_replay_reports_410_and_recovery_uses_new_snapshot():
    # A smaller owned ring triggers the same expiry protocol quickly; this is
    # a protocol regression, not a measurement of the default workload.
    async with workload(3, event_history=3) as (source, client):
        async with client.post("/__q03/start") as response:
            assert response.status == 200
        await wait_for(lambda: source.serial >= 5)
        async with client.post("/__q03/pause") as response:
            assert response.status == 200
        async with client.get(
            "/api/v1/namespaces/team/pods", params={"watch": "true", "resourceVersion": "q03/0"}
        ) as response:
            event = json.loads(await response.content.readline())
            assert event == {"type": "ERROR", "object": {"code": 410, "reason": "Expired"}}
            assert await response.content.read() == b""
        assert source.stats["expired_watch"] == 1
        async with client.get("/api/v1/namespaces/team/pods") as response:
            snapshot = await response.json()
        assert snapshot["metadata"]["resourceVersion"] == f"q03/{source.serial}"


@pytest.mark.asyncio
async def test_server_watch_timeout_ends_cleanly_and_current_version_can_reopen():
    async with workload(1) as (source, client):
        async with client.get(
            "/api/v1/namespaces/team/pods",
            params={"watch": "true", "timeoutSeconds": "1", "resourceVersion": "q03/0"},
        ) as response:
            assert response.status == 200
            async with asyncio.timeout(3):
                assert await response.content.read() == b""
        assert source.stats["watch_timeouts"] == 1
        assert source.stats["active_watches"] == 0
        assert list(source.watch_versions) == ["q03/0"]
        reopened = await client.get(
            "/api/v1/namespaces/team/pods", params={"watch": "true", "resourceVersion": "q03/0"}
        )
        assert reopened.status == 200
        reopened.close()
        await wait_for(lambda: source.stats["active_watches"] == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", ["0", "301", "invalid"])
async def test_invalid_watch_duration_never_opens_a_source_slot(timeout):
    async with workload(1) as (source, client):
        async with client.get(
            "/api/v1/namespaces/team/pods", params={"watch": "true", "timeoutSeconds": timeout}
        ) as response:
            assert response.status == 400
        assert source.stats["active_watches"] == source.stats["watch_timeouts"] == 0


@pytest.mark.asyncio
async def test_idle_stream_admission_is_bounded_and_disconnects_release_slots():
    async with workload(1) as (source, client):
        responses = []
        try:
            for _ in range(source.STREAM_LIMIT):
                response = await client.get(
                    "/api/v1/namespaces/team/pods", params={"watch": "true"}
                )
                assert response.status == 200
                responses.append(response)
            async with client.get(
                "/api/v1/namespaces/team/pods", params={"watch": "true"}
            ) as rejected:
                assert rejected.status == 503
            assert source.stats["active_watches"] == 16
        finally:
            for response in responses:
                response.close()
            await wait_for(lambda: source.stats["active_watches"] == 0)
        replacement = await client.get("/api/v1/namespaces/team/pods", params={"watch": "true"})
        assert replacement.status == 200
        replacement.close()
        await wait_for(lambda: source.stats["active_watches"] == 0)


@pytest.mark.asyncio
async def test_separate_source_process_terminates_active_streams_and_emits_bounded_final_receipt():
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-m",
        "tests.support.performance_workload",
        cwd=Path(__file__).resolve().parents[2],
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(10):
            startup = await process.stdout.readline()
        assert len(startup) < 1024
        address = json.loads(startup)["url"]
        assert address.startswith("http://127.0.0.1:")
        async with aiohttp.ClientSession(base_url=address) as client:
            watch = await client.get("/api/v1/namespaces/team/pods", params={"watch": "true"})
            logs = await client.get(
                "/api/v1/namespaces/team/pods/q03-00000/log", params={"follow": "true"}
            )
            assert watch.status == logs.status == 200
            async with client.post("/__q03/start") as response:
                assert response.status == 200
            await asyncio.sleep(0.05)
            assert b"q03-row" in await logs.content.readline()
            assert json.loads(await watch.content.readline())["type"] == "MODIFIED"
            os.killpg(process.pid, signal.SIGTERM)
            async with asyncio.timeout(10):
                output, errors = await process.communicate()
            assert process.returncode == 0 and not errors and len(output) < 8192
            final = json.loads(output)["final"]
            assert final["rows"] == 10000 and final["workers_running"] == 0
            assert final["active_logs"] == final["active_watches"] == 0
            assert final["resource_produced"] > 0 and final["log_produced"] > 0
            assert final["timing_samples"] is None
            watch.close()
            logs.close()
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                async with asyncio.timeout(5):
                    await process.communicate()
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.communicate()
