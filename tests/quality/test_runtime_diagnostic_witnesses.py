"""Causal sampler controls, never application timing or release qualification.

These cases need their existing exclusive reference window. The C helper retries
EINTR against one monotonic deadline, so an observer signal cannot shorten its
wait. PyDLL retains the GIL; CDLL releases it around the same owned C function.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from tests.support.runtime_diagnostics import DiagnosticSupervisor
from tests.support.tiers import runtime_environment

WAIT_SOURCE = """#include <errno.h>
#include <time.h>
long long owned_now(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000000000LL + now.tv_nsec;
}
int owned_wait(unsigned int milliseconds, long long *started, long long *ended) {
    *started = owned_now();
    const long long deadline = *started + (long long)milliseconds * 1000000LL;
    int interruptions = 0;
    for (;;) {
        long long remaining = deadline - owned_now();
        if (remaining <= 0) {
            *ended = owned_now();
            return interruptions;
        }
        struct timespec delay = {remaining / 1000000000LL, remaining % 1000000000LL};
        if (nanosleep(&delay, 0) != 0 && errno == EINTR) interruptions++;
    }
}
"""

CHILD = """import asyncio,ctypes,json,os,signal,sys,time
from pathlib import Path
from tests.support.runtime_diagnostics import DiagnosticProbe,EVENT_FD,STACK_FD,ACK_FD
kind,library,directory=sys.argv[1:]
directory=Path(directory)
async def trial():
    probe=DiagnosticProbe(*(int(os.environ[name]) for name in (EVENT_FD,STACK_FD,ACK_FD)))
    probe.start()
    probe.arm()
    async def heartbeat():
        before=time.monotonic()
        while True:
            await asyncio.sleep(0.005)
            now=time.monotonic()
            probe.pulse(before,now,0,0,'owned witness control')
            before=now
    task=asyncio.create_task(heartbeat())
    try:
        await asyncio.sleep(0.04)
        module=(ctypes.PyDLL if kind=='held' else ctypes.CDLL)(library)
        module.owned_wait.argtypes=[ctypes.c_uint,ctypes.POINTER(ctypes.c_longlong),ctypes.POINTER(ctypes.c_longlong)]
        module.owned_wait.restype=ctypes.c_int
        module.owned_now.argtypes=[]
        module.owned_now.restype=ctypes.c_longlong
        before=time.monotonic_ns()
        native_now=module.owned_now()
        after=time.monotonic_ns()
        offset_low,offset_high=before-native_now,after-native_now
        def block():
            (directory/'entered.json').write_text('{}')
            start=time.monotonic_ns()
            if kind=='suspended':
                os.kill(os.getpid(),signal.SIGSTOP)
                interrupted=None
                end=time.monotonic_ns()
                elapsed=end-start
            else:
                native_start,native_end=ctypes.c_longlong(),ctypes.c_longlong()
                interrupted=module.owned_wait(200,ctypes.byref(native_start),ctypes.byref(native_end))
                start=native_start.value+offset_high
                end=native_end.value+offset_low
                elapsed=native_end.value-native_start.value
            return {'start_ns':start,'end_ns':end,'native_elapsed_ns':elapsed,'clock_alignment_uncertainty_ns':offset_high-offset_low,'eintr_retries':interrupted}
        window=block()
        await asyncio.sleep(0.02)
        (directory/'control-window.json').write_text(json.dumps(window))
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await probe.close()
        (directory/'probe.json').write_text(json.dumps(probe.report()))
asyncio.run(trial())
"""


@pytest.mark.performance
@pytest.mark.runtime_control(order=2)
@pytest.mark.parametrize("kind", ["held", "released", "suspended"])
def test_witnesses_distinguish_owned_gil_waits_and_suspension_conservatively(tmp_path, kind):
    source = tmp_path / "owned_wait.c"
    library = tmp_path / ("owned_wait.dylib" if sys.platform == "darwin" else "owned_wait.so")
    source.write_text(WAIT_SOURCE)
    owner = DiagnosticSupervisor(lifetime=7, capture_seconds=4, termination_seconds=1)
    resume_errors, continuation = [], []
    stop_resumer = threading.Event()

    def resume():
        until = time.monotonic() + 3
        entered = tmp_path / "entered.json"
        while not entered.exists() and not stop_resumer.wait(0.001):
            if time.monotonic() > until:
                resume_errors.append("owned suspension never began")
                return
        if stop_resumer.is_set():
            return
        time.sleep(0.2)
        try:
            continuation.append(time.monotonic_ns())
            owner.signal(signal.SIGCONT)
        except BaseException as error:
            resume_errors.append(type(error).__name__)

    with runtime_environment(dict(os.environ), exclusive=True) as environment:
        subprocess.run(
            [
                "cc",
                "-dynamiclib" if sys.platform == "darwin" else "-shared",
                "-fPIC",
                str(source),
                "-o",
                str(library),
            ],
            capture_output=True,
            check=True,
            timeout=15,
        )
        resumer = threading.Thread(target=resume, name="owned-suspension-resumer")
        if kind == "suspended":
            resumer.start()
        try:
            receipt = owner.run(
                [sys.executable, "-c", CHILD, kind, str(library), str(tmp_path)],
                environment,
                tmp_path,
            )
        finally:
            stop_resumer.set()
            if resumer.ident is not None:
                resumer.join(1)
                assert not resumer.is_alive()
    assert not resume_errors
    assert receipt["owner_reaped"] and receipt["returncode"] == 0
    assert not receipt["errors"], (tmp_path / "stderr.log").read_text()
    assert receipt["diagnostic_only"] and not receipt["timing_qualifying"]
    probe = json.loads((tmp_path / "probe.json").read_text())
    window = json.loads((tmp_path / "control-window.json").read_text())
    assert probe["closed"] and probe["handler_restored"] and not probe["thread_alive"]
    assert probe["acknowledged"] and not probe["errors"]
    start, end = window["start_ns"], window["end_ns"]
    assert window["native_elapsed_ns"] >= 200_000_000  # Signals cannot shorten the owned wait.
    if kind == "suspended":
        assert continuation
        end = continuation[0]  # The actual resume request bounds the known suspension.
    during = [sample for sample in probe["python_witness"] if start < sample["time_ns"] < end]
    peer = [tick for tick in receipt["peer_ticks"] if start < tick["time_ns"] < end]
    requests = [
        sample for sample in receipt["snapshot_requests"] if start < sample["sent_ns"] < end
    ]
    (tmp_path / "control-observation.json").write_text(
        json.dumps(
            {
                "injected_control": kind,
                "diagnostic_only": True,
                "timing_qualifying": False,
                "definite_interval_start_ns": start,
                "definite_interval_end_ns": end,
                "continuation_requests_ns": continuation,
                "python_witness_samples_inside_interval": len(during),
                "peer_ticks_inside_interval": len(peer),
                "stack_requests_inside_interval": len(requests),
            },
            indent=2,
        )
        + "\n"
    )
    assert peer and requests, "Independent owner must actually observe the controlled interval"
    if kind == "released":
        assert during and any(
            frame["function"] == "block" for sample in during for frame in sample["frames"]
        )
    else:
        assert not during, "A Python witness cannot run while the GIL or entire process is held"
    if kind == "suspended":
        assert continuation
        assert all(sample["read_ns"] >= continuation[0] for sample in receipt["stack_reads"])
        assert receipt["snapshot_requests_are_not_dump_count"]
    else:
        assert type(window["eintr_retries"]) is int
        assert "block" in (tmp_path / "faulthandler.txt").read_text()
