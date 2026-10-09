"""Public aggregate controls against live owned HTTP, with source identity and lifetime."""

import asyncio
import gc
import json
import logging
import sys
import time
from collections import deque
from copy import deepcopy
from pathlib import Path

import pytest
from textual.widgets import Input, OptionList, Static

from kuberich.config.schema import Settings
from kuberich.domain.aggregate_logs import AggregateHistory, LogSource
from kuberich.domain.logs import LogDecoder
from kuberich.domain.views import ViewStatus
from kuberich.services.processes import _finish_owned
from kuberich.services.resources import parse_owned
from kuberich.ui.aggregate_logs import AggregateLogScreen, LogSourcesScreen
from kuberich.ui.app import KubeRichApp
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.logs import LogScreen
from tests.support.aggregate_logs import AggregateApi
from tests.support.connections import catalog_fixture, namespaces
from tests.support.standard import roots
from tests.support.workspace import wait_for, workspace_api


async def ns(request):
    return namespaces("team", "default")


def app_for(tmp_path, url):
    return KubeRichApp(
        Settings(read_only=True),
        logging.Logger("aggregate", level=100),
        catalog=catalog_fixture(tmp_path, url),
    )


def rendered(screen):
    return "\n".join(strip.text for _, strips in screen.body.rows for strip in strips)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_public_aggregate_controls_reuse_history_with_json_filter_export_and_restore(
    tmp_path, size
):
    api = AggregateApi(count=2)
    api.pods["pod-00"]["spec"].update(
        initContainers=[{"name": "init"}], ephemeralContainers=[{"name": "debug"}]
    )
    api.initial["pod-00", "app"] = (
        b'2026-10-09T12:00:03Z {"pass\\u0077ord":"hidden-json-value","message":"owned-json","control":"\\u001b[red]"}\n'
    )
    api.initial["pod-00", "init"] = b'2026-10-09T11:00:00-02:00 init earlier-clock\n{"bad-json":\n'
    async with workspace_api(ns, api.handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 2)
            before = app.resources.capture_viewport()
            await pilot.press("L")
            await wait_for(lambda: isinstance(app.screen, AggregateLogScreen))
            screen = app.screen
            await wait_for(lambda: len(screen.body.rows) == 4)
            assert api.active == 3 and not api.requests["pod-01", "app"]
            assert "hidden-json-value" not in rendered(screen) and "owned-pod-00" in rendered(
                screen
            )
            assert "unavailable" in rendered(screen)
            baseline = api.requests.copy()
            await pilot.press("t")
            await wait_for(lambda: "2026-10-09" not in rendered(screen))
            assert "owned-pod-00" in rendered(screen)
            await pilot.press("J")
            await wait_for(lambda: '"source":' in rendered(screen))
            assert '"timestamp":null' in rendered(screen)
            await pilot.press("t")
            await wait_for(lambda: "2026-10-09" in rendered(screen))
            assert api.requests == baseline
            for line in screen.aggregate.export().splitlines():
                value = json.loads(line)
                assert value["source"]["uid"] == "owned-pod-00" and value["source"]["id"] > 0
            await pilot.press("p", "g", "G", "w", "L", "z")
            assert screen.paused and screen.body.follow and screen.wrap and screen.body.column_lock
            await api.emit("pod-00", "app", b"held-while-paused\n")
            await pilot.pause()
            assert "held-while-paused" not in screen.aggregate.export()
            await pilot.press("p")
            await wait_for(lambda: "held-while-paused" in screen.aggregate.export())
            await pilot.press("slash", *"owned-json", "enter", "n", "N", "m")
            await pilot.pause()
            assert len(screen.body.matches) == 1 and screen.aggregate.marks
            await pilot.press("s")
            app.screen.query_one(OptionList).highlighted = 1
            await pilot.press("enter")
            await wait_for(lambda: screen.aggregate.filter is not None)
            await pilot.press("ctrl+y")
            await wait_for(lambda: screen._copy_task is not None and screen._copy_task.done())
            assert app.clipboard == screen.aggregate.export()
            assert api.requests == baseline
            await pilot.press("ctrl+s")
            destination = tmp_path / "aggregate.jsonl"
            app.screen.query_one("#log-value", Input).value = str(destination)
            await pilot.press("enter")
            await wait_for(lambda: destination.exists() and screen._save_task.done())
            assert destination.read_text() == screen.aggregate.export()
            assert destination.stat().st_mode & 0o777 == 0o600
            await pilot.press("question_mark")
            assert "source admission" in app.screen.status
            await pilot.press("escape")
            await pilot.resize_terminal(55, 16)
            await pilot.pause()
            evidence = Path("artifacts/ui")
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(
                filename=f"aggregate-logs-{size[0]}.svg", path=str(evidence.resolve())
            )
            await pilot.press("c")
            assert isinstance(app.screen, LogSourcesScreen)
            picker = app.screen
            assert picker.table.row_count == 3
            picker.table.move_cursor(row=1)
            await pilot.press("enter")
            await wait_for(lambda: api.active == 1)
            assert screen.owner.selected == frozenset({("owned-pod-00", "init")})
            await pilot.press("a")
            await wait_for(lambda: api.active == 3)
            await pilot.press("escape", "C")
            assert not screen.aggregate.records
            await pilot.press("escape")
            await wait_for(lambda: api.active == 0)
            assert app.resources.capture_viewport() == before
            assert (
                screen._controller.done() and screen._renderer.done() and screen._read_task.done()
            )
            # Existing Pod Enter -> container list -> one selected log viewer stays intact.
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, ContainerScreen))
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    isinstance(app.screen, LogScreen)
                    and not isinstance(app.screen, AggregateLogScreen)
                )
            )
            await pilot.press("escape", "escape")


@pytest.mark.asyncio
async def test_typed_command_and_hidden_context_replacement_drain_all_readers(tmp_path):
    api = AggregateApi(count=1)
    async with workspace_api(ns, api.handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            app._submit_command(":logsall")
            await wait_for(lambda: isinstance(app.screen, AggregateLogScreen) and api.active == 1)
            screen = app.screen
            await pilot.press("ctrl+s")
            client = screen.owner.client
            # Covered aggregate must be stale/drained before the captured SDK closes.
            task = app.workspace.connect("kuberich-test-two")
            await task
            assert screen.closed and not screen.owner._owned
            assert screen._read_task.done() and screen._renderer.done()
            await wait_for(lambda: api.active == 0)
            assert "Reception stopped" in str(screen.status.content)
            assert "0/8 readers" in str(screen.status.content)
            assert "Receiving enabled" not in str(screen.status.content)
            assert "cleanup draining" not in str(screen.status.content)
            assert app.sessions.client is not client
            assert not screen.aggregate.records and not screen.body.rows
            await pilot.press("escape", "escape")


@pytest.mark.asyncio
async def test_source_picker_uid_recreation_expired_selection_and_manual_space(tmp_path):
    api = AggregateApi(count=1)
    api.pods["pod-00"]["spec"]["initContainers"] = [{"name": "init"}]
    api.denied.add(("pod-00", "init"))
    async with workspace_api(ns, api.handler, discovery_roots=roots) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            app._submit_command(":rs")
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.press("f1")
            help_text = str(app.screen.query_one("#help-content", Static).content)
            assert "Shift+L / :logsall Aggregate Pod/workload logs" in help_text
            await pilot.press("escape")
            await pilot.press("L")
            await wait_for(lambda: isinstance(app.screen, AggregateLogScreen))
            screen = app.screen
            await wait_for(lambda: "1 failed" in str(screen.status.content))
            assert "c sources" in str(screen.status.content)
            await pilot.press("c", "enter")
            picker = app.screen
            assert isinstance(picker, LogSourcesScreen)
            assert screen.owner.selected == frozenset({("owned-pod-00", "app")})
            old_number = picker.table.get_row_at(picker.table.cursor_row)[0]
            value = deepcopy(api.pods["pod-00"])
            for index in range(34):
                await api.update("DELETED", value)
                await wait_for(lambda: not screen.owner.states and api.active == 0)
                value["metadata"]["uid"] = (
                    "same-name-new-uid" if index == 33 else f"earlier-{index}"
                )
                await api.update("ADDED", value)
                await wait_for(lambda: len(screen.owner.states) == 2)
            await wait_for(lambda: len(screen.owner.states) == 2)
            await pilot.pause(0.3)
            assert picker.table.get_row_at(picker.table.cursor_row)[0] == old_number
            before = api.requests.copy()
            await pilot.press("enter")
            assert screen.owner.selected == frozenset() and api.requests == before
            assert len(screen.owner.retired) == 64 and picker.table.row_count == 67
            selected = screen.owner.states["same-name-new-uid", "app"]
            picker.table.move_cursor(row=picker.table.get_row_index(str(selected.number)))
            await pilot.pause()
            await pilot.press("space")
            await wait_for(lambda: api.active == 1)
            assert screen.owner.selected == frozenset({("same-name-new-uid", "app")})
            await pilot.press("escape", "escape")
            await wait_for(lambda: api.active == 0 and api.watch_active == 1)


@pytest.mark.asyncio
async def test_detached_export_is_drained_before_context_client_cleanup(tmp_path, monkeypatch):
    api = AggregateApi(count=1)
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held_save(path, text):
        entered.set()
        await _finish_owned(asyncio.create_task(release.wait()))
        finished.set()

    monkeypatch.setattr("kuberich.ui.aggregate_logs.save_logs", held_save)
    async with workspace_api(ns, api.handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("L")
            await wait_for(lambda: isinstance(app.screen, AggregateLogScreen) and api.active == 1)
            screen = app.screen
            await pilot.press("ctrl+s")
            app.screen.query_one("#log-value", Input).value = str(tmp_path / "held.log")
            await pilot.press("enter")
            await wait_for(entered.is_set)
            client = screen.owner.client
            try:
                escape = asyncio.create_task(pilot.press("escape"))
                await wait_for(lambda: screen not in app.screen_stack)
                assert app._aggregate_screens == {screen}
                before = api.requests.copy()
                app.action_logs_all()
                assert app._aggregate_screens == {screen} and api.requests == before
                assert "closing" in str(app.status.content)
                connecting = app.workspace.connect("kuberich-test-two")
                await asyncio.sleep(0.1)
                assert not connecting.done() and client.api is not None
            finally:
                release.set()
            await connecting
            await escape
            assert finished.is_set() and screen._save_task.done()
            assert not app._aggregate_screens


@pytest.mark.asyncio
async def test_picker_overflow_explicit_reopen_empty_manual_selection_and_back_button(tmp_path):
    api = AggregateApi(count=10)
    api.denied.add(("pod-00", "app"))
    async with workspace_api(ns, api.handler, discovery_roots=roots) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 10)
            app._submit_command(":rs")
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.press("L")
            await wait_for(lambda: isinstance(app.screen, AggregateLogScreen) and api.active == 8)
            screen = app.screen
            await pilot.press("c")
            picker = app.screen
            picker.table.move_cursor(row=9)
            await pilot.press("space")
            assert "at most eight" in str(picker.notice.content) and screen.owner.selected is None
            await pilot.press("enter")
            await wait_for(lambda: api.active == 1)
            assert screen.owner.selected == frozenset({("owned-pod-09", "app")})
            await pilot.press("space")
            await wait_for(lambda: api.active == 0)
            assert screen.owner.selected == frozenset()
            picker.table.move_cursor(row=0)
            api.denied.clear()
            await pilot.press("r")
            await wait_for(lambda: api.active == 1 and api.requests["pod-00", "app"] == 2)
            await pilot.click("#source-back")
            await wait_for(lambda: app.screen is screen)
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_empty_sources_and_generic_core_route_guard(tmp_path):
    api = AggregateApi(count=0)
    async with workspace_api(ns, api.handler, discovery_roots=roots) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            app._submit_command(":rs")
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.press("L")
            await wait_for(lambda: isinstance(app.screen, AggregateLogScreen))
            await pilot.press("c", "enter", "r", "space", "a")
            assert app.screen.table.row_count == 0 and not api.requests
            await pilot.press("escape", "escape")
            app._submit_command(":resource pods")
            await wait_for(lambda: app.custom_table.display)
            app._submit_command(":logsall")
            await pilot.pause()
            assert len(app.screen_stack) == 1 and "Generic resources" in str(app.status.content)


@pytest.mark.asyncio
async def test_full_retained_history_format_heartbeat_clipboard_bound_save_failure_and_previous(
    tmp_path,
):
    # Prior run_test apps can retain large closed fixture graphs; isolate this
    # benchmark before creating its app. GC stays enabled throughout live work.
    assert gc.isenabled()
    preparation_started = time.monotonic()
    preparation_collected = gc.collect()
    preparation_seconds = time.monotonic() - preparation_started
    api = AggregateApi(count=1)
    async with workspace_api(ns, api.handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            background_watches = api.watch_active
            await pilot.press("L")
            await wait_for(
                lambda: isinstance(app.screen, AggregateLogScreen) and bool(app.screen.body.rows)
            )
            screen = app.screen
            line = LogDecoder().feed(("2026-10-09T12:00:00Z " + "x" * 350 + "\n").encode())[0]
            maximum_prepared_records = maximum_combined_records = 0

            def full_history(other_records=0):
                nonlocal maximum_prepared_records, maximum_combined_records
                history = AggregateHistory()
                for source in range(10):
                    identity = LogSource(
                        "team", f"historical-{source}", f"historic-uid-{source}", "app"
                    )
                    for _ in range(500):
                        history.retain(identity, source + 1, line)
                maximum_prepared_records = max(maximum_prepared_records, len(history.records))
                maximum_combined_records = max(
                    maximum_combined_records, other_records + len(history.records)
                )
                return history

            history = full_history()
            gaps = []
            phase = "initial layout"
            slow_pulses = deque(maxlen=32)
            collections = deque(maxlen=64)
            slow_collections = deque(maxlen=16)
            collecting = {}

            def collect(event, info):
                now = time.monotonic()
                collections.append({"event": event, "generation": info["generation"], "time": now})
                if event == "start":
                    stack = []
                    if info["generation"] == 2:
                        frame = sys._getframe()
                        for _ in range(16):
                            stack.append(
                                {
                                    "file": frame.f_code.co_filename,
                                    "line": frame.f_lineno,
                                    "function": frame.f_code.co_name,
                                }
                            )
                            frame = frame.f_back
                            if frame is None:
                                break
                        del frame
                    collecting[info["generation"]] = now, phase, stack
                else:
                    started, at_phase, stack = collecting.pop(info["generation"], (now, phase, []))
                    if now - started > 0.01:
                        slow_collections.append(
                            {
                                "generation": info["generation"],
                                "phase": at_phase,
                                "start": started,
                                "end": now,
                                "seconds": now - started,
                                "collected": info.get("collected", 0),
                                "uncollectable": info.get("uncollectable", 0),
                                "allocation_stack": stack,
                            }
                        )

            async def pulse():
                before = asyncio.get_running_loop().time()
                cpu_before = time.process_time()
                main_before = time.thread_time()
                while True:
                    await asyncio.sleep(0.005)
                    now = asyncio.get_running_loop().time()
                    gaps.append(now - before)
                    cpu, main = time.process_time(), time.thread_time()
                    if now - before > 0.05:
                        slow_pulses.append(
                            {
                                "phase": phase,
                                "start": before,
                                "end": now,
                                "wall_seconds": now - before,
                                "cpu_seconds": cpu - cpu_before,
                                "main_cpu_seconds": main - main_before,
                            }
                        )
                    before = now
                    cpu_before, main_before = cpu, main

            gc.callbacks.append(collect)
            heartbeat = asyncio.create_task(pulse())
            completed_rounds = 0
            after_close = None
            try:
                for iteration in (1, 2):
                    if iteration == 2:
                        # Refill after clearing the previous window, measuring
                        # delivery without retaining two full input histories.
                        phase = "round 2 input delivery"
                        remaining = len(screen.aggregate.records)
                        history = await parse_owned(
                            lambda remaining=remaining: full_history(remaining)
                        )
                    phase = f"round {iteration} initial layout"
                    screen.aggregate = screen.history = history
                    batches = screen.body.render_batches
                    screen._display_changed()
                    await wait_for(
                        lambda batches=batches: (
                            screen.body.render_batches > batches and len(screen.body.rows) == 5000
                        )
                    )
                    baseline = api.requests.copy()
                    phase = f"round {iteration} mode/timestamp/copy"
                    await pilot.press("J", "t", "ctrl+y")
                    await wait_for(lambda: "Copy exceeds 1 MiB" in str(screen.status.content))
                    assert api.requests == baseline and len(history.records) == 5000
                    destination = tmp_path / "existing.log"
                    destination.write_text("keep-existing")
                    phase = f"round {iteration} save"
                    await pilot.press("ctrl+s")
                    app.screen.query_one("#log-value", Input).value = str(destination)
                    await pilot.press("enter")
                    await wait_for(lambda: screen._save_task.done())
                    assert "Cannot save logs" in str(screen.status.content)
                    assert destination.read_text() == "keep-existing"
                    assert gaps and max(gaps) < 0.15, list(slow_pulses)
                    phase = f"round {iteration} previous/current transitions"
                    await pilot.press("v")
                    await wait_for(lambda: "1 no previous" in str(screen.status.content))
                    assert not screen.aggregate.records
                    await pilot.press("v")
                    await wait_for(
                        lambda iteration=iteration: api.requests["pod-00", "app"] == iteration + 1
                    )
                    await wait_for(lambda: bool(screen.body.rows))
                    assert gaps and max(gaps) < 0.15, list(slow_pulses)
                    completed_rounds += 1
                phase = "leave/drain viewer"
                await pilot.press("escape")
                await wait_for(lambda: not app._aggregate_screens)
                await wait_for(lambda: api.active == 0 and api.watch_active == background_watches)
                assert len(app.screen_stack) == 1
                assert screen.closed and screen.owner.closed and not screen.owner._owned
                assert all(
                    state.task is None or state.task.done()
                    for state in screen.owner.states.values()
                )
                after_close = {
                    "viewer_closed": screen.closed,
                    "owner_closed": screen.owner.closed,
                    "owner_tasks": len(screen.owner._owned),
                    "active_readers": sum(
                        state.status == "active" for state in screen.owner.states.values()
                    ),
                    "registry_size": len(app._aggregate_screens),
                    "api_log_streams": api.active,
                    "api_watches": api.watch_active,
                    "background_watches": background_watches,
                }
                assert gaps and max(gaps) < 0.15, list(slow_pulses)
            finally:
                gc.callbacks.remove(collect)
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                evidence = Path("artifacts/ui")
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / "aggregate-heartbeat.json").write_text(
                    json.dumps(
                        {
                            "fixture_preparation": {
                                "before_app_creation": True,
                                "collected": preparation_collected,
                                "seconds": preparation_seconds,
                            },
                            "gc_enabled": gc.isenabled(),
                            "gc_thresholds": gc.get_threshold(),
                            "requested_full_history_rounds": 2,
                            "completed_full_history_rounds": completed_rounds,
                            "maximum_simultaneously_prepared_records": maximum_prepared_records,
                            "maximum_retained_plus_prepared_records": maximum_combined_records,
                            "after_close": after_close,
                            "max_gap_seconds": max(gaps, default=0),
                            "limit_seconds": 0.15,
                            "slow_pulses": list(slow_pulses),
                            "gc": list(collections),
                            "slow_gc": list(slow_collections),
                        },
                        indent=2,
                    )
                    + "\n"
                )
