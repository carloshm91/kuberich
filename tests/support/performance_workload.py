"""Independently paced, bounded loopback Kubernetes workload for Q03.

No real kubeconfig or cluster is used. Running this module starts a separate
owned source process; its first JSON line announces the ephemeral loopback URL.
"""

import asyncio
import json
import signal
import time
from collections import OrderedDict, deque
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from aiohttp import web

from tests.support.connections import namespaces
from tests.support.pods import pod
from tests.support.resources import collection, legacy_roots
from tests.support.watches import frame


class PacedWorkload:
    EVENT_HISTORY = 1000
    LOG_CHUNKS = 64
    TIMING_SAMPLES = 4096
    LOG_BATCH = 20
    STREAM_LIMIT = 16

    def __init__(self, rows=10000):
        if type(rows) is not int or not 1 <= rows <= 10000:
            raise ValueError("Workload rows must be an integer from 1 through 10000.")
        self.created = datetime.now(UTC) - timedelta(days=1)
        self.items = [self.item(index, 0) for index in range(rows)]
        self.events = deque(maxlen=self.EVENT_HISTORY)
        self.logs = deque(maxlen=self.LOG_CHUNKS)
        self.timing = deque(maxlen=self.TIMING_SAMPLES)
        self.snapshots = OrderedDict()
        self.serial = self.log_serial = self.snapshot_serial = 0
        self.enabled = asyncio.Event()
        self.closed = asyncio.Event()
        self.changed = asyncio.Condition()
        self.started = None
        self.paused = None
        self.workers = []
        self.watch_versions = deque(maxlen=16)
        self.stats = {
            "resource_sent": 0,
            "log_sent": 0,
            "active_watches": 0,
            "active_logs": 0,
            "expired_watch": 0,
            "expired_logs": 0,
            "list_pages": 0,
            "watch_timeouts": 0,
        }

    def item(self, index, serial):
        value = pod(
            f"q03-{index:05}",
            restarts=serial,
            created=self.created - timedelta(seconds=index),
        )
        value["metadata"]["resourceVersion"] = f"q03/{serial}"
        return value

    def line(self, serial):
        # Longer than the reference terminal width, but 10,000 lines fit 4 MiB.
        value = (
            "2026-10-10T00:00:00Z "
            f"q03-row-{serial:011} " + "abcdefghij" * 15 + f" q03-tail-{serial:011}\n"
        )
        return value.encode()

    async def produce_resources(self):
        await self.enabled.wait()
        start = self.started
        assert start is not None
        while self.enabled.is_set() and not self.closed.is_set():
            serial = self.serial + 1
            due = start + (serial - 1) / 100
            await asyncio.sleep(max(0, due - time.monotonic()))
            if not self.enabled.is_set() or self.closed.is_set():
                break
            index = (serial - 1) % len(self.items)
            value = self.item(index, serial)
            async with self.changed:
                self.serial = serial
                self.items[index] = value
                self.events.append((serial, frame({"type": "MODIFIED", "object": value})))
                self.timing.append(("resource", serial, time.monotonic(), due))
                self.changed.notify_all()

    async def produce_logs(self):
        await self.enabled.wait()
        start = self.started
        assert start is not None
        while self.enabled.is_set() and not self.closed.is_set():
            first = self.log_serial + 1
            due = start + (first - 1) / 2000
            await asyncio.sleep(max(0, due - time.monotonic()))
            if not self.enabled.is_set() or self.closed.is_set():
                break
            last = first + self.LOG_BATCH - 1
            payload = b"".join(self.line(number) for number in range(first, last + 1))
            assert len(payload) <= 8192
            async with self.changed:
                self.logs.append((first, last, payload))
                self.log_serial = last
                self.timing.append(("logs", last, time.monotonic(), due))
                self.changed.notify_all()

    def receipt(self, *, include_timings=False):
        return {
            **self.stats,
            "rows": len(self.items),
            "resource_produced": self.serial,
            "log_produced": self.log_serial,
            "started_monotonic": self.started,
            "paused_monotonic": self.paused,
            "event_history": len(self.events),
            "event_history_limit": self.EVENT_HISTORY,
            "log_chunks": len(self.logs),
            "log_chunk_limit": self.LOG_CHUNKS,
            "retained_source_log_bytes": sum(len(entry[2]) for entry in self.logs),
            "timing_samples": list(self.timing) if include_timings else None,
            "timing_sample_count": len(self.timing),
            "timing_sample_limit": self.TIMING_SAMPLES,
            "list_snapshots": len(self.snapshots),
            "workers_running": sum(not task.done() for task in self.workers),
            "watch_versions": list(self.watch_versions),
        }

    def list_response(self, request):
        self.stats["list_pages"] += 1
        now = time.monotonic()
        for key in tuple(self.snapshots):
            if now - self.snapshots[key][2] > 30:
                del self.snapshots[key]
        token = request.query.get("continue")
        if token:
            try:
                key, offset = token.split("/", 1)
                offset = int(offset)
                version, items, _ = self.snapshots[key]
                if not 0 <= offset < len(items):
                    raise ValueError
            except (KeyError, ValueError):
                raise web.HTTPGone(text="Expired owned list snapshot.") from None
        else:
            self.snapshot_serial += 1
            key, offset = str(self.snapshot_serial), 0
            version, items = self.serial, tuple(self.items)
            if len(self.snapshots) == 2:
                self.snapshots.popitem(last=False)
            self.snapshots[key] = (version, items, now)
        try:
            limit = int(request.query.get("limit", "500"))
            if not 1 <= limit <= 10000:
                raise ValueError
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid owned page limit.") from None
        end = min(len(items), offset + limit)
        token = f"{key}/{end}" if end < len(items) else ""
        response = web.json_response(
            collection(*items[offset:end], rv=f"q03/{version}", token=token)
        )
        if not token:
            del self.snapshots[key]
        return response

    async def watch(self, request):
        if self.stats["active_watches"] >= self.STREAM_LIMIT:
            raise web.HTTPServiceUnavailable(text="Owned watch limit reached.")
        version = request.query.get("resourceVersion", "q03/0")
        try:
            prefix, serial = version.split("/", 1)
            serial = int(serial)
            if prefix != "q03" or not 0 <= serial <= self.serial:
                raise ValueError
        except ValueError:
            raise web.HTTPGone(text="Unknown owned resource version.") from None
        try:
            seconds = int(request.query.get("timeoutSeconds", "30"))
            if not 1 <= seconds <= 300:
                raise ValueError
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid owned watch timeout.") from None
        deadline = time.monotonic() + seconds
        self.watch_versions.append(version)
        response = web.StreamResponse()
        await response.prepare(request)
        self.stats["active_watches"] += 1
        try:
            while (
                not self.closed.is_set()
                and request.transport is not None
                and not request.transport.is_closing()
                and time.monotonic() < deadline
            ):
                expired = False
                async with self.changed:
                    pending = [entry for entry in self.events if entry[0] > serial]
                    if self.events and serial < self.events[0][0] - 1:
                        self.stats["expired_watch"] += 1
                        expired = True
                    elif not pending:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(self.changed.wait(), 0.1)
                        continue
                if expired:
                    # Slow socket writers must never hold the producer's lock.
                    await response.write(
                        frame({"type": "ERROR", "object": {"code": 410, "reason": "Expired"}})
                    )
                    break
                for number, payload in pending:
                    await response.write(payload)
                    serial = number
                    self.stats["resource_sent"] += 1
        except ConnectionError:
            pass
        finally:
            if time.monotonic() >= deadline:
                self.stats["watch_timeouts"] += 1
            self.stats["active_watches"] -= 1
        return response

    async def stream_logs(self, request):
        if self.stats["active_logs"] >= self.STREAM_LIMIT:
            raise web.HTTPServiceUnavailable(text="Owned log limit reached.")
        if request.query.get("previous") == "true":
            raise web.HTTPBadRequest(text="No previous owned log instance.")
        response = web.StreamResponse()
        await response.prepare(request)
        self.stats["active_logs"] += 1
        serial = self.log_serial
        try:
            await response.write(self.line(serial))
            if request.query.get("follow") == "false":
                return response
            while (
                not self.closed.is_set()
                and request.transport is not None
                and not request.transport.is_closing()
            ):
                async with self.changed:
                    pending = [entry for entry in self.logs if entry[1] > serial]
                    if self.logs and serial < self.logs[0][0] - 1:
                        self.stats["expired_logs"] += 1
                        break
                    if not pending:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(self.changed.wait(), 0.1)
                        continue
                for first, last, payload in pending:
                    await response.write(payload)
                    serial = last
                    self.stats["log_sent"] += last - first + 1
        except ConnectionError:
            pass
        finally:
            self.stats["active_logs"] -= 1
        return response

    async def handler(self, request):
        path = request.path
        if path == "/__q03/status":
            return web.json_response(
                self.receipt(include_timings=request.query.get("timings") == "true")
            )
        if path == "/api/v1/namespaces":
            if "watch" in request.query:
                raise web.HTTPBadRequest(text="Namespace watches are outside this workload.")
            return namespaces("team", "default")
        roots = legacy_roots()
        if path in roots:
            return web.json_response(roots[path])
        if path in {"/api/v1/pods", "/api/v1/namespaces/team/pods"}:
            return (
                await self.watch(request)
                if "watch" in request.query
                else self.list_response(request)
            )
        prefix = "/api/v1/namespaces/team/pods/"
        if path.startswith(prefix):
            parts = path.removeprefix(prefix).split("/")
            if len(parts) > 2 or (len(parts) == 2 and parts[1] != "log"):
                raise web.HTTPNotFound()
            name = parts[0]
            try:
                index = int(name.removeprefix("q03-"))
                if not 0 <= index < len(self.items) or name != f"q03-{index:05}":
                    raise ValueError
            except ValueError:
                raise web.HTTPNotFound() from None
            if path.endswith("/log"):
                return await self.stream_logs(request)
            return web.json_response(self.items[index])
        raise web.HTTPNotFound()

    async def control(self, request):
        action = request.match_info["action"]
        if action == "start" and self.started is None:
            self.started = time.monotonic()
            self.enabled.set()
        elif action == "pause" and self.enabled.is_set():
            self.enabled.clear()
            self.paused = time.monotonic()
        elif action == "close":
            self.enabled.clear()
            self.closed.set()
        else:
            raise web.HTTPConflict(text="Invalid owned workload transition.")
        async with self.changed:
            self.changed.notify_all()
        return web.json_response(self.receipt())


async def main():
    source = PacedWorkload()
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
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, source.closed.set)
    print(json.dumps({"url": f"http://127.0.0.1:{runner.addresses[0][1]}"}), flush=True)
    try:
        await source.closed.wait()
    finally:
        source.enabled.clear()
        for task in source.workers:
            task.cancel()
        await asyncio.gather(*source.workers, return_exceptions=True)
        await runner.cleanup()
    print(json.dumps({"final": source.receipt()}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
