"""Nonqualifying, bounded witnesses for an already failed runtime heartbeat.

No sampler is imported or started by the ordinary qualifying modes. Python
witnesses need the GIL; the independent owner can request a C faulthandler dump
without assuming that witness executes. Missing or truncated samples prove no
cause. Process rusage includes this instrumentation and is never a timing score.
"""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import json
import os
import resource
import select
import signal
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

EVENT_FD = "KUBERICH_TEST_DIAGNOSTIC_EVENTS_FD"
STACK_FD = "KUBERICH_TEST_DIAGNOSTIC_STACK_FD"
ACK_FD = "KUBERICH_TEST_DIAGNOSTIC_ACK_FD"
PACKET = struct.Struct("!cQQ")  # kind, monotonic nanoseconds, sequence
INTERVAL = 0.01
STALE_NS = 50_000_000
MAX_STACK_REQUESTS = 8
STACK_BYTES = 1024 * 1024
OUTPUT_BYTES = 256 * 1024
NUMERIC_RECORDS = 1024
STACK_RECORDS = 64
USAGE_FIELDS = ("ru_nvcsw", "ru_nivcsw", "ru_minflt", "ru_majflt")


def usage(who: int = resource.RUSAGE_SELF) -> dict[str, int]:
    record = resource.getrusage(who)
    return {field: int(getattr(record, field)) for field in USAGE_FIELDS}


class DiagnosticProbe:
    """Own a disposable child's witness thread, signal handler and inherited pipes."""

    def __init__(self, event_fd: int, stack_fd: int, ack_fd: int) -> None:
        self.event_fd, self.stack_fd, self.ack_fd = event_fd, stack_fd, ack_fd
        self.main_ident = threading.get_ident()
        self.previous_handler = signal.getsignal(signal.SIGUSR2)
        self.stopped = threading.Event()
        self.armed = False
        self.last_pulse_ns = 0
        self.sequence = self.emitted = self.dropped = 0
        self.witness_ticks = self.frames_seen = 0
        self.numeric: deque[dict[str, Any]] = deque(maxlen=NUMERIC_RECORDS)
        self.frames: deque[dict[str, Any]] = deque(maxlen=STACK_RECORDS)
        self.last_usage: dict[str, int] | None = None
        self.last_thread_usage: dict[str, int] | None = None
        self.errors: list[str] = []
        self.acknowledged = self.handler_restored = self.closed = False
        self.registered = self.signal_owned = False
        self.closed_descriptors: set[int] = set()
        self.attempted_descriptors: set[int] = set()
        self.closing: asyncio.Task[None] | None = None
        self.thread = threading.Thread(target=self._run_observer, name="runtime-diagnostic-witness")

    def start(self) -> None:
        if len({self.event_fd, self.stack_fd, self.ack_fd}) != 3:
            raise ValueError("Diagnostic pipes must have distinct descriptors.")
        for descriptor in (self.event_fd, self.stack_fd, self.ack_fd):
            if os.get_blocking(descriptor):
                raise ValueError("Diagnostic pipes must be nonblocking.")
        if self.previous_handler not in (signal.SIG_DFL, signal.SIG_IGN):
            raise ValueError("Diagnostic user signal already has an owner.")
        # On a broken shutdown handshake, unregistering must restore IGN rather
        # than a fatal default while an independently running peer may signal.
        signal.signal(signal.SIGUSR2, signal.SIG_IGN)
        self.signal_owned = True
        faulthandler.register(signal.SIGUSR2, file=self.stack_fd, all_threads=True, chain=False)
        self.registered = True
        self.thread.start()
        self._emit(b"R")

    def _emit(self, kind: bytes) -> bool:
        self.sequence += 1
        try:
            written = os.write(self.event_fd, PACKET.pack(kind, time.monotonic_ns(), self.sequence))
        except BlockingIOError:
            self.dropped += 1
            return False
        except OSError as error:
            if not self.errors:
                self.errors.append(f"event pipe: {type(error).__name__}")
            self.dropped += 1
            return False
        if written != PACKET.size:
            self.errors.append("event pipe: partial fixed-size packet")
            return False
        self.emitted += 1
        return True

    def arm(self) -> None:
        self.last_usage = usage()
        if hasattr(resource, "RUSAGE_THREAD"):
            self.last_thread_usage = usage(resource.RUSAGE_THREAD)
        self.last_pulse_ns = time.monotonic_ns()
        self.armed = True
        self._emit(b"A")

    def pulse(self, start: float, end: float, cpu: float, main_cpu: float, phase: str) -> None:
        now_usage = usage()
        record: dict[str, Any] = {
            "start": start,
            "end": end,
            "wall_seconds": end - start,
            "process_cpu_seconds": cpu,
            "main_cpu_seconds": main_cpu,
            "phase_at_resume": phase,
            "process_usage_delta": {
                key: now_usage[key] - value for key, value in (self.last_usage or now_usage).items()
            },
            "main_thread_usage_delta": None,
        }
        if self.last_thread_usage is not None:
            current = usage(resource.RUSAGE_THREAD)
            record["main_thread_usage_delta"] = {
                key: current[key] - value for key, value in self.last_thread_usage.items()
            }
            self.last_thread_usage = current
        self.last_usage = now_usage
        self.numeric.append(record)
        self.last_pulse_ns = time.monotonic_ns()
        self._emit(b"H")  # Ring retention never stops the live progress emitter.

    def _observe(self) -> None:
        while not self.stopped.wait(INTERVAL):
            if not self.armed:
                continue
            now = time.monotonic_ns()
            self.witness_ticks += 1
            self._emit(b"W")
            if now - self.last_pulse_ns <= STALE_NS:
                continue
            frame = sys._current_frames().get(self.main_ident)
            frames = []
            for _ in range(16):
                if frame is None:
                    break
                frames.append(
                    {
                        "file": frame.f_code.co_filename[:500],
                        "function": frame.f_code.co_name[:500],
                        "line": frame.f_lineno,
                    }
                )
                frame = frame.f_back
            del frame
            self.frames_seen += 1
            self.frames.append(
                {"time_ns": now, "main_last_pulse_ns": self.last_pulse_ns, "frames": frames}
            )

    def _run_observer(self) -> None:
        try:
            self._observe()
        except BaseException as observer_error:
            self.errors.append(f"witness stopped: {type(observer_error).__name__}")

    async def close(self) -> None:
        if self.closed:
            if self.errors:
                raise RuntimeError("Diagnostic probe cleanup: " + "; ".join(self.errors))
            return
        if self.closing is None:
            self.closing = asyncio.create_task(self._close())
        cancellation: asyncio.CancelledError | None = None
        while not self.closing.done():
            try:
                await asyncio.shield(self.closing)
            except asyncio.CancelledError as interrupted:
                if cancellation is None:
                    cancellation = interrupted
        try:
            self.closing.result()
        except BaseException as cleanup_error:
            if cancellation is not None:
                cancellation.add_note(
                    f"Diagnostic cleanup also failed: {type(cleanup_error).__name__}"
                )
                raise cancellation from None
            raise
        if cancellation is not None:
            raise cancellation

    async def _close(self) -> None:
        self.stopped.set()
        deadline = time.monotonic() + 1
        # Stop the independent signal owner before spending the remaining
        # bounded budget on joining the cooperative Python witness.
        delivered = False
        while self.registered and time.monotonic() < deadline:
            if not delivered:
                delivered = self._emit(b"D")
            try:
                acknowledgement = os.read(self.ack_fd, 1)
                if acknowledgement == b"x":
                    self.acknowledged = True
                    break
                if not acknowledgement:
                    self.errors.append("supervisor acknowledgement pipe reached EOF")
                    break
            except BlockingIOError:
                pass
            except OSError as error:
                self.errors.append(f"acknowledgement: {type(error).__name__}")
                break
            await asyncio.sleep(0.001)
        if self.registered and not self.acknowledged:
            self.errors.append("supervisor stop acknowledgement absent")
        while self.thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
        if self.thread.is_alive():
            self.errors.append("witness thread did not drain")
        elif self.thread.ident is not None:
            self.thread.join(0)
        safe_stack_close = not self.registered
        unregistered = not self.registered
        if self.registered:
            try:
                faulthandler.unregister(signal.SIGUSR2)  # Restores our safe IGN baseline.
                safe_stack_close = unregistered = True
            except BaseException as unregister_error:
                self.errors.append(f"unregister: {type(unregister_error).__name__}")
                try:
                    signal.signal(signal.SIGUSR2, signal.SIG_IGN)
                    safe_stack_close = True
                except BaseException as ignore_error:
                    self.errors.append(f"safe signal fallback: {type(ignore_error).__name__}")
        if self.signal_owned and unregistered and (self.acknowledged or not self.registered):
            try:
                signal.signal(signal.SIGUSR2, self.previous_handler)
                self.handler_restored = True
            except BaseException as restore_error:
                self.errors.append(f"signal restore: {type(restore_error).__name__}")
        for descriptor in (self.event_fd, self.stack_fd, self.ack_fd):
            if descriptor in self.attempted_descriptors:
                continue
            if descriptor == self.event_fd and self.thread.is_alive():
                self.errors.append("event descriptor retained for the still-live writer")
                continue
            if descriptor == self.stack_fd and not safe_stack_close:
                self.errors.append("stack descriptor retained for an unverified signal handler")
                continue
            self.attempted_descriptors.add(descriptor)
            try:
                os.close(descriptor)
                self.closed_descriptors.add(descriptor)
            except BaseException as error:
                self.errors.append(f"descriptor close: {type(error).__name__}")
        self.closed = len(self.closed_descriptors) == 3 and not self.thread.is_alive()
        if self.errors:
            raise RuntimeError("Diagnostic probe cleanup: " + "; ".join(self.errors))

    def report(self) -> dict[str, Any]:
        return {
            "diagnostic_only": True,
            "timing_qualifying": False,
            "process_counters_include_witness": True,
            "main_thread_usage_supported": hasattr(resource, "RUSAGE_THREAD"),
            "witness_requires_gil": True,
            "witness_interval_seconds": INTERVAL,
            "main_thread_ident": self.main_ident,
            "witness_ticks": self.witness_ticks,
            "frames_seen": self.frames_seen,
            "events_attempted": self.sequence,
            "events_emitted": self.emitted,
            "events_dropped": self.dropped,
            "numeric_capacity": NUMERIC_RECORDS,
            "stack_capacity": STACK_RECORDS,
            "intervals": list(self.numeric),
            "python_witness": list(self.frames),
            "thread_alive": self.thread.is_alive(),
            "acknowledged": self.acknowledged,
            "handler_restored": self.handler_restored,
            "closed": self.closed,
            "descriptors_closed": len(self.closed_descriptors) == 3,
            "errors": list(self.errors),
        }


async def exercise_diagnostic(
    request: dict[str, Any],
    exercise: Callable[[], Awaitable[None]],
    finish: Callable[[], Awaitable[None]],
) -> None:
    """Preserve the actual scenario error while draining independent witnesses."""
    probe = DiagnosticProbe(*(int(os.environ[name]) for name in (EVENT_FD, STACK_FD, ACK_FD)))
    request["_diagnostic_probe"] = probe
    first: BaseException | None = None
    try:
        probe.start()
        await exercise()
    except BaseException as error:
        first = error
        raise
    finally:
        cleanup: list[BaseException] = []
        for operation in (probe.close, finish):
            try:
                await operation()
            except BaseException as error:
                cleanup.append(error)
        try:
            Path(request["directory"], "probe.json").write_text(
                json.dumps(probe.report(), indent=2) + "\n"
            )
        except BaseException as evidence_error:
            cleanup.append(evidence_error)
        if first is not None:
            for cleanup_error in cleanup:
                first.add_note(f"Nonqualifying diagnostic cleanup: {type(cleanup_error).__name__}")
        elif cleanup:
            raise BaseExceptionGroup("Nonqualifying diagnostic cleanup failed", cleanup)


class DiagnosticSupervisor:
    """Hold the actual child's PID until all snapshot requests have stopped."""

    def __init__(
        self, *, lifetime: float = 120, capture_seconds: float = 105, termination_seconds: float = 5
    ) -> None:
        self.lifetime, self.capture_seconds, self.termination_seconds = (
            lifetime,
            capture_seconds,
            termination_seconds,
        )
        if not 0 < capture_seconds + 2 * termination_seconds < lifetime:
            raise ValueError("Diagnostic cleanup must fit inside the original deadline.")
        self.process: subprocess.Popen[bytes] | None = None
        self._owned_process: subprocess.Popen[bytes] | None = None
        self.pid: int | None = None
        self.group, self.session = os.getpgrp(), os.getsid(0)
        self.signals_stopped = False
        self.requests: list[dict[str, Any]] = []
        self.ticks: deque[dict[str, Any]] = deque(maxlen=NUMERIC_RECORDS)
        self.stack_reads: deque[dict[str, int]] = deque(maxlen=STACK_RECORDS)
        self.last_main = self.last_witness = 0
        self.ready = self.armed = self.done = False
        self.errors: list[str] = []

    def signal(self, value: signal.Signals) -> None:
        process = self.process
        if (
            self.signals_stopped
            or process is None
            or process is not self._owned_process
            or process.pid != self.pid
            or process.returncode is not None
            or self.pid is None
            or self.pid <= 1
            or self.pid == os.getpid()
        ):
            raise RuntimeError("Diagnostic child identity is not held.")
        if os.getpgid(self.pid) != self.group or os.getsid(self.pid) != self.session:
            raise RuntimeError("Diagnostic child left its owned session/group.")
        os.kill(self.pid, value)

    def run(
        self, argv: Sequence[str], environment: Mapping[str, str], directory: Path
    ) -> dict[str, Any]:
        started = time.monotonic()
        deadline, cutoff = started + self.lifetime, started + self.capture_seconds
        descriptors: list[int] = []
        output = {"stdout": bytearray(), "stderr": bytearray(), "stacks": bytearray()}
        discarded = dict.fromkeys(output, 0)
        reaped = False
        pending = bytearray()
        last_tick = started
        last_request = 0.0
        readers: dict[int, str] = {}
        process: subprocess.Popen[bytes] | None = None
        try:
            event_read, event_write = os.pipe()
            descriptors.extend((event_read, event_write))
            stack_read, stack_write = os.pipe()
            descriptors.extend((stack_read, stack_write))
            ack_read, ack_write = os.pipe()
            descriptors.extend((ack_read, ack_write))
            for descriptor in descriptors:
                os.set_blocking(descriptor, False)
            process = subprocess.Popen(
                list(argv),
                env={
                    **environment,
                    EVENT_FD: str(event_write),
                    STACK_FD: str(stack_write),
                    ACK_FD: str(ack_read),
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(event_write, stack_write, ack_read),
            )
            self.process, self.pid = process, process.pid
            self._owned_process = process
            assert process.stdout is not None and process.stderr is not None
            for descriptor in (event_write, stack_write, ack_read):
                os.close(descriptor)
                descriptors.remove(descriptor)
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
            readers = {
                event_read: "events",
                stack_read: "stacks",
                process.stdout.fileno(): "stdout",
                process.stderr.fileno(): "stderr",
            }
            while readers and time.monotonic() < cutoff:
                now = time.monotonic()
                wake_gap = now - last_tick
                self.ticks.append(
                    {
                        "time_ns": time.monotonic_ns(),
                        "wake_gap_seconds": wake_gap,
                        "main_last_ns": self.last_main,
                        "witness_last_ns": self.last_witness,
                    }
                )
                last_tick = now
                ready, _, _ = select.select(list(readers), [], [], INTERVAL)
                for descriptor in ready:
                    kind = readers[descriptor]
                    for _ in range(16):
                        try:
                            data = os.read(descriptor, 8192)
                        except BlockingIOError:
                            break
                        if not data:
                            del readers[descriptor]
                            if kind == "events":
                                self.done = True
                            break
                        if kind != "events":
                            limit = STACK_BYTES if kind == "stacks" else OUTPUT_BYTES
                            keep = min(len(data), max(0, limit - len(output[kind])))
                            output[kind].extend(data[:keep])
                            discarded[kind] += len(data) - keep
                            if kind == "stacks":
                                self.stack_reads.append(
                                    {
                                        "read_ns": time.monotonic_ns(),
                                        "bytes": len(data),
                                        "retained_bytes": keep,
                                    }
                                )
                            continue
                        pending.extend(data)
                        while len(pending) >= PACKET.size:
                            code, at, _ = PACKET.unpack(pending[: PACKET.size])
                            del pending[: PACKET.size]
                            if code == b"R":
                                self.ready = True
                            elif code == b"A":
                                self.armed = True
                                self.last_main = at
                            elif code == b"H":
                                self.last_main = at
                            elif code == b"W":
                                self.last_witness = at
                            elif code == b"D":
                                self.done = True
                                os.write(ack_write, b"x")
                # A late peer or a deliberately capped retention ring is not
                # evidence of a stale producer. Live emitters never ring-cap.
                if (
                    self.ready
                    and self.armed
                    and not self.done
                    and self.last_main
                    and time.monotonic_ns() - self.last_main > STALE_NS
                    and wake_gap <= 0.025
                    and now - last_request >= 0.1
                    and len(self.requests) < MAX_STACK_REQUESTS
                    and not discarded["stacks"]
                    and len(output["stacks"]) < STACK_BYTES
                ):
                    before_bytes = len(output["stacks"])
                    self.signal(signal.SIGUSR2)
                    self.requests.append(
                        {
                            "sent_ns": time.monotonic_ns(),
                            "main_last_ns": self.last_main,
                            "witness_last_ns": self.last_witness,
                            "retained_bytes_before_request": before_bytes,
                        }
                    )
                    last_request = now
            # No poll/wait has reaped the child while a sampling signal was
            # possible. Only the held Popen may now receive TERM/KILL.
            self.signals_stopped = True
            remaining = max(0, min(cutoff, deadline) - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(
                        timeout=max(
                            0,
                            min(started + self.capture_seconds + self.termination_seconds, deadline)
                            - time.monotonic(),
                        )
                    )
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(
                        timeout=max(
                            0,
                            min(
                                started + self.capture_seconds + 2 * self.termination_seconds,
                                deadline,
                            )
                            - time.monotonic(),
                        )
                    )
            reaped = True
        except BaseException as error:
            self.errors.append(
                f"supervisor: {type(error).__name__}, errno={getattr(error, 'errno', None)}"
            )
            self.signals_stopped = True
            if process is not None:
                try:
                    process.kill()
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                    reaped = True
                except BaseException as cleanup_error:
                    self.errors.append(f"cleanup: {type(cleanup_error).__name__}")
        finally:
            self.signals_stopped = True
            if reaped:
                # Stop requesting samples before reaping, then drain only the
                # already closed producer's remaining bytes without waiting.
                for descriptor, output_kind in readers.items():
                    if output_kind == "events":
                        continue
                    try:
                        for _ in range(64):
                            chunk = os.read(descriptor, 8192)
                            if not chunk:
                                break
                            limit = STACK_BYTES if output_kind == "stacks" else OUTPUT_BYTES
                            kept = min(len(chunk), max(0, limit - len(output[output_kind])))
                            output[output_kind].extend(chunk[:kept])
                            discarded[output_kind] += len(chunk) - kept
                        else:
                            self.errors.append("final pipe drain exceeded its bounded work budget")
                    except BlockingIOError:
                        pass
                    except BaseException as drain_error:
                        self.errors.append(f"drain: {type(drain_error).__name__}")
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except BaseException as error:
                    self.errors.append(f"close: {type(error).__name__}")
            if process is not None:
                for final_stream in (process.stdout, process.stderr):
                    if final_stream is not None:
                        try:
                            final_stream.close()
                        except BaseException as stream_error:
                            self.errors.append(f"stream close: {type(stream_error).__name__}")
        directory.mkdir(parents=True, exist_ok=True)
        for name, buffered in output.items():
            (directory / ("faulthandler.txt" if name == "stacks" else name + ".log")).write_bytes(
                buffered
            )
        receipt = {
            "diagnostic_only": True,
            "timing_qualifying": False,
            "pid": self.pid,
            "group": self.group,
            "session": self.session,
            "started": started,
            "capture_cutoff": cutoff,
            "absolute_deadline": deadline,
            "finished": time.monotonic(),
            "returncode": process.returncode if process is not None else None,
            "owner_reaped": reaped,
            "signals_stopped_before_reap": self.signals_stopped,
            "snapshot_requests": self.requests,
            "snapshot_requests_are_not_dump_count": True,
            "stack_capture_integrity": "best-effort nonblocking: pipe loss cannot be ruled out",
            "stack_truncation": "confirmed retention limit"
            if discarded["stacks"]
            else "unknown: nonblocking pipe loss is possible",
            "retention_truncated": bool(discarded["stacks"]),
            "discarded_retention_bytes": discarded,
            "peer_ticks": list(self.ticks),
            "stack_reads": list(self.stack_reads),
            "errors": self.errors,
        }
        (directory / "supervisor.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    arguments = parser.parse_args(argv)
    request = json.loads(arguments.request.read_text())
    if (
        request.get("mode") != "diagnostic"
        or request.get("diagnostic_only") is not True
        or request.get("timing_qualifying") is not False
    ):
        raise ValueError("Only an explicit nonqualifying diagnostic request is accepted.")
    from tests.support.aggregate_runtime import MODE, NODE, REQUEST

    directory = arguments.request.parent
    result = DiagnosticSupervisor().run(
        (
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "-p",
            "pytest_cov.plugin",
            "-o",
            "addopts=--strict-config --strict-markers",
            NODE,
            "-q",
            "--tb=short",
            f"--junitxml={directory / 'cases.xml'}",
        ),
        {**os.environ, MODE: "diagnostic", REQUEST: str(arguments.request.resolve())},
        directory,
    )
    print("Nonqualifying diagnostic collection; child returncode:", result["returncode"])
    return 1 if result["errors"] or not result["owner_reaped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
