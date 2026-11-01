"""Nonqualifying sampler ownership; these checks are not runtime qualification."""

import asyncio
import errno
import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from tests.support import runtime_diagnostics as diagnostics


def test_supervisor_requires_cleanup_inside_its_total_deadline():
    with pytest.raises(ValueError, match="cleanup must fit"):
        diagnostics.DiagnosticSupervisor(lifetime=2, capture_seconds=1, termination_seconds=1)


def test_early_child_exit_is_reaped_and_records_no_invented_snapshots(tmp_path):
    owner = diagnostics.DiagnosticSupervisor(lifetime=5, capture_seconds=2, termination_seconds=1)
    receipt = owner.run([sys.executable, "-c", "print('owned-early-exit')"], os.environ, tmp_path)
    assert receipt["owner_reaped"] and receipt["signals_stopped_before_reap"]
    assert receipt["snapshot_requests"] == [] and receipt["returncode"] == 0
    assert receipt["diagnostic_only"] and not receipt["timing_qualifying"]
    assert not receipt["errors"]
    assert (tmp_path / "stdout.log").read_text() == "owned-early-exit\n"
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["pid"], 0)
    with pytest.raises(RuntimeError, match="identity is not held"):
        owner.signal(signal.SIGUSR2)


def test_failed_spawn_closes_every_created_pipe(tmp_path, monkeypatch):
    descriptors = []
    real_pipe = os.pipe

    def pipe():
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    def fail(*args, **kwargs):
        raise OSError(errno.EAGAIN, "owned spawn refusal")

    monkeypatch.setattr(os, "pipe", pipe)
    monkeypatch.setattr(subprocess, "Popen", fail)
    owner = diagnostics.DiagnosticSupervisor(lifetime=5, capture_seconds=2, termination_seconds=1)
    receipt = owner.run([sys.executable, "-c", "pass"], os.environ, tmp_path)
    assert not receipt["owner_reaped"] and receipt["errors"]
    assert len(descriptors) == 6
    for descriptor in descriptors:
        with pytest.raises(OSError) as observed:
            os.fstat(descriptor)
        assert observed.value.errno == errno.EBADF


def test_signal_refuses_changed_session_before_any_delivery(monkeypatch):
    owner = diagnostics.DiagnosticSupervisor()
    owner.process = type("OwnedChild", (), {"pid": 12345, "returncode": None})()
    owner._owned_process = owner.process
    owner.pid = owner.process.pid
    monkeypatch.setattr(os, "getpgid", lambda pid: owner.group)
    monkeypatch.setattr(os, "getsid", lambda pid: owner.session + 1)
    calls = []
    monkeypatch.setattr(os, "kill", lambda *args: calls.append(args))
    with pytest.raises(RuntimeError, match="left its owned"):
        owner.signal(signal.SIGUSR2)
    assert not calls


def test_full_stack_pipe_is_explicitly_nonblocking_and_retention_is_not_a_score(tmp_path):
    owner = diagnostics.DiagnosticSupervisor(lifetime=5, capture_seconds=2, termination_seconds=1)
    # This owned producer deliberately overflows its nonblocking stack channel.
    # Completion proves the child cannot hang waiting for a stopped/slow sink;
    # the protocol never promises complete stacks or one dump per request.
    child = """import os
fd=int(os.environ['KUBERICH_TEST_DIAGNOSTIC_STACK_FD'])
assert not os.get_blocking(fd)
count=0
for _ in range(10000):
    try: os.write(fd,b'x'*8192)
    except BlockingIOError: count+=1
print('owned-nonblocking',count)
"""
    receipt = owner.run([sys.executable, "-c", child], os.environ, tmp_path)
    assert receipt["owner_reaped"] and receipt["returncode"] == 0
    assert "owned-nonblocking" in (tmp_path / "stdout.log").read_text()
    assert (tmp_path / "faulthandler.txt").stat().st_size <= diagnostics.STACK_BYTES
    assert receipt["stack_capture_integrity"].startswith("best-effort nonblocking")
    assert receipt["snapshot_requests_are_not_dump_count"]


def test_actual_faulthandler_does_not_block_on_a_deliberately_full_pipe(tmp_path):
    child = """import faulthandler,os,signal
read,write=os.pipe()
os.set_blocking(write,False)
while True:
    try: os.write(write,b'x'*8192)
    except BlockingIOError: break
faulthandler.register(signal.SIGUSR2,file=write,all_threads=True,chain=False)
os.kill(os.getpid(),signal.SIGUSR2)
faulthandler.unregister(signal.SIGUSR2)
os.close(write)
os.close(read)
print('owned-full-fault-sink-returned')
"""
    owner = diagnostics.DiagnosticSupervisor(lifetime=5, capture_seconds=2, termination_seconds=1)
    receipt = owner.run([sys.executable, "-c", child], os.environ, tmp_path)
    assert receipt["owner_reaped"] and receipt["returncode"] == 0
    assert not receipt["errors"]
    assert (tmp_path / "stdout.log").read_text() == "owned-full-fault-sink-returned\n"


@pytest.mark.asyncio
async def test_capped_retention_keeps_emitting_progress_and_close_is_idempotent(monkeypatch):
    pipes = [os.pipe() for _ in range(3)]
    event_read, event_write = pipes[0]
    stack_read, stack_write = pipes[1]
    ack_read, ack_write = pipes[2]
    for pair in pipes:
        for fd in pair:
            os.set_blocking(fd, False)
    probe = diagnostics.DiagnosticProbe(event_write, stack_write, ack_read)
    emitted = []
    real_write = os.write

    def write(fd, data):
        if fd == event_write:
            emitted.append(diagnostics.PACKET.unpack(data)[0])
            return len(data)
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", write)
    try:
        probe.start()
        probe.arm()
        for index in range(diagnostics.NUMERIC_RECORDS + 20):
            probe.pulse(index, index + 0.005, 0, 0, "synthetic numeric control")
        assert len(probe.numeric) == diagnostics.NUMERIC_RECORDS
        assert emitted.count(b"H") == diagnostics.NUMERIC_RECORDS + 20
        real_write(ack_write, b"x")
        await probe.close()
        await probe.close()
        assert probe.closed and not probe.thread.is_alive() and probe.handler_restored
    finally:
        for fd in (event_read, stack_read, ack_write):
            os.close(fd)


def test_diagnostic_driver_rejects_a_qualifying_request(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"mode": "positive", "timing_qualifying": True}))
    with pytest.raises(ValueError, match="Only an explicit nonqualifying"):
        diagnostics.main(["--request", str(request)])


@pytest.mark.asyncio
async def test_repeated_close_cancellation_drains_the_real_witness_and_all_owned_descriptors():
    pipes = [os.pipe() for _ in range(3)]
    event_read, event_write = pipes[0]
    stack_read, stack_write = pipes[1]
    ack_read, ack_write = pipes[2]
    for pair in pipes:
        for fd in pair:
            os.set_blocking(fd, False)
    probe = diagnostics.DiagnosticProbe(event_write, stack_write, ack_read)
    pending = bytearray()
    done = False
    try:
        probe.start()
        probe.arm()
        closing = asyncio.create_task(probe.close())
        async with asyncio.timeout(3):
            while not done:
                with suppress(BlockingIOError):
                    pending.extend(os.read(event_read, 8192))
                while len(pending) >= diagnostics.PACKET.size:
                    kind, _, _ = diagnostics.PACKET.unpack(pending[: diagnostics.PACKET.size])
                    del pending[: diagnostics.PACKET.size]
                    done |= kind == b"D"
                if not done:
                    await asyncio.sleep(0)
        closing.cancel("owned first close cancellation")
        await asyncio.sleep(0)
        closing.cancel("owned repeated close cancellation")
        os.write(ack_write, b"x")
        with pytest.raises(asyncio.CancelledError, match="owned first close cancellation"):
            await closing
        assert probe.closing.done() and not probe.thread.is_alive()
        assert probe.closed and probe.acknowledged and probe.handler_restored
        assert probe.report()["descriptors_closed"] and not probe.errors
        for fd in (event_write, stack_write, ack_read):
            with pytest.raises(OSError) as observed:
                os.fstat(fd)
            assert observed.value.errno == errno.EBADF
        await probe.close()
    finally:
        if not probe.closed:
            os.write(ack_write, b"x")
            await probe.close()
        for fd in (event_read, stack_read, ack_write):
            os.close(fd)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper", [None, "nonce", "source", "live-witness", "open-descriptor", "unreaped-owner"]
)
async def test_collection_binds_original_failure_and_rejects_incomplete_diagnostic_receipts(
    tmp_path, monkeypatch, tamper
):
    from kuberich.domain.processes import ProcessResult, ProcessStatus
    from tests.support import aggregate_runtime

    monkeypatch.setattr(aggregate_runtime, "ROOT", tmp_path)
    source = {"tested_checkout_commit": "owned", "files": {"owned-input": "digest"}}
    failed = tmp_path / "artifacts/ui/aggregate-runtime/positive"
    failed.mkdir(parents=True)
    names = ("heartbeat.json", "source-receipt.json", "cases.xml", "stdout.log", "stderr.log")
    for name in names:
        (failed / name).write_text("owned original " + name)
    originals = {name: (failed / name).read_bytes() for name in names}
    original = {
        "nonce": "a" * 32,
        "mode": "positive",
        "source": source,
        "directory": str(failed),
        "node": aggregate_runtime.NODE,
    }

    async def stamp():
        return source

    async def command(argv, environment):
        assert argv[:3] == (sys.executable, "-m", "tests.support.runtime_diagnostics")
        request_path = Path(argv[-1])
        request = json.loads(request_path.read_text())
        assert request["diagnostic_only"] and not request["timing_qualifying"]
        assert request["mode"] == "diagnostic" and request["nonce"] != original["nonce"]
        assert request_path.parent.name == request["nonce"]
        assert request["original_failure"]["nonce"] == original["nonce"]
        assert request["original_failure"]["source"] == source
        assert set(request["original_failure"]["sha256"]) == set(names)
        receipt = {
            "nonce": request["nonce"],
            "mode": "diagnostic",
            "diagnostic_only": True,
            "timing_qualifying": False,
            "source_before": source,
            "source_after": source,
            "after_app_close": {
                "app_running": False,
                "aggregate_registry": 0,
                "api_log_streams": 0,
                "api_watches": 0,
            },
        }
        supervisor = {
            "diagnostic_only": True,
            "timing_qualifying": False,
            "owner_reaped": True,
            "signals_stopped_before_reap": True,
            "errors": [],
        }
        probe = {
            "closed": True,
            "acknowledged": True,
            "handler_restored": True,
            "descriptors_closed": True,
            "thread_alive": False,
            "errors": [],
        }
        if tamper == "nonce":
            receipt["nonce"] = original["nonce"]
        elif tamper == "source":
            receipt["source_after"] = {"owned-input": "changed"}
        elif tamper == "live-witness":
            probe["thread_alive"] = True
        elif tamper == "open-descriptor":
            probe["descriptors_closed"] = False
        elif tamper == "unreaped-owner":
            supervisor["owner_reaped"] = False
        for name, document in [
            ("source-receipt", receipt),
            ("supervisor", supervisor),
            ("probe", probe),
        ]:
            (request_path.parent / (name + ".json")).write_text(json.dumps(document))
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(aggregate_runtime, "source_stamp", stamp)
    monkeypatch.setattr(aggregate_runtime, "command", command)
    if tamper is None:
        evidence = await aggregate_runtime.collect_diagnostic(original, {})
        assert evidence.is_dir() and evidence.parent.name == "diagnostic"
    else:
        with pytest.raises(AssertionError):
            await aggregate_runtime.collect_diagnostic(original, {})
    assert {name: (failed / name).read_bytes() for name in names} == originals


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["positive", "negative", "coverage", "diagnostic"])
async def test_child_mode_boundary_rejects_mixed_diagnostic_identity(tmp_path, monkeypatch, mode):
    from tests.support import aggregate_runtime

    monkeypatch.setattr(aggregate_runtime, "ROOT", tmp_path)
    source = {"files": {}}

    async def stamp():
        return source

    monkeypatch.setattr(aggregate_runtime, "source_stamp", stamp)
    nonce = "b" * 32
    directory = tmp_path / "artifacts/ui/aggregate-runtime" / mode
    if mode == "diagnostic":
        directory /= nonce
    directory.mkdir(parents=True)
    request_path = directory / "request.json"
    request = {
        "mode": mode,
        "nonce": nonce,
        "source": source,
        "node": aggregate_runtime.NODE,
        "directory": str(directory),
        "diagnostic_only": mode != "diagnostic",
        "timing_qualifying": False,
    }
    request_path.write_text(json.dumps(request))
    monkeypatch.setenv(aggregate_runtime.MODE, mode)
    monkeypatch.setenv(aggregate_runtime.REQUEST, str(request_path))
    with pytest.raises(AssertionError):
        await aggregate_runtime.child_request()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["unregister", "restore"])
async def test_signal_cleanup_fault_cannot_replace_body_or_skip_independent_closures(
    tmp_path, monkeypatch, fault
):
    pipes = [os.pipe() for _ in range(3)]
    event_read, event_write = pipes[0]
    stack_read, stack_write = pipes[1]
    ack_read, ack_write = pipes[2]
    for pair in pipes:
        for fd in pair:
            os.set_blocking(fd, False)
    for variable, descriptor in [
        (diagnostics.EVENT_FD, event_write),
        (diagnostics.STACK_FD, stack_write),
        (diagnostics.ACK_FD, ack_read),
    ]:
        monkeypatch.setenv(variable, str(descriptor))
    real_unregister = diagnostics.faulthandler.unregister
    real_signal = signal.signal
    previous = signal.getsignal(signal.SIGUSR2)
    first = AssertionError("owned first assertion before signal cleanup failure")
    request = {"directory": str(tmp_path)}

    def unregister(signum):
        raise OSError(errno.EIO, "owned unregister boundary failure")

    def restore(signum, handler):
        real_signal(signum, handler)
        if handler == previous:
            raise OSError(errno.EIO, "owned restoration boundary failure")

    async def body():
        if fault == "unregister":
            monkeypatch.setattr(diagnostics.faulthandler, "unregister", unregister)
        else:
            monkeypatch.setattr(signal, "signal", restore)
        raise first

    async def finish():
        return None

    os.write(ack_write, b"x")
    try:
        with pytest.raises(AssertionError) as observed:
            await diagnostics.exercise_diagnostic(request, body, finish)
        assert observed.value is first
        probe = request["_diagnostic_probe"]
        assert probe.closed and not probe.thread.is_alive()
        assert probe.report()["descriptors_closed"]
        assert any(fault in error for error in probe.errors)
        assert any("Nonqualifying diagnostic cleanup" in note for note in first.__notes__)
        for fd in (event_write, stack_write, ack_read):
            with pytest.raises(OSError) as error:
                os.fstat(fd)
            assert error.value.errno == errno.EBADF
        with (tmp_path / "unrelated-after-fault").open("w") as unrelated:
            with pytest.raises(RuntimeError):
                await probe.close()
            assert os.fstat(unrelated.fileno())
    finally:
        real_unregister(signal.SIGUSR2)
        real_signal(signal.SIGUSR2, previous)
        for fd in (event_read, stack_read, ack_write):
            os.close(fd)
