"""Installer commands drain owned descendants without changing outputs or exits."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress

import pytest

from tests.support.distribution import run

CHILD = """
import json, os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
path = Path(sys.argv[1])
temporary = path.with_suffix('.publishing')
temporary.write_text(json.dumps({'child_pid': os.getpid(), 'pgid': os.getpgrp()}))
temporary.replace(path)
time.sleep(30)
"""
LEADER = """
import json, os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen(
    [sys.executable, '-c', CHILD_CODE, sys.argv[2]],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
ready = Path(sys.argv[2])
deadline = time.monotonic() + 3
while not ready.exists():
    if time.monotonic() > deadline:
        child.kill()
        child.wait()
        raise RuntimeError('Owned child did not become ready')
    time.sleep(0.005)
info = json.loads(ready.read_text())
assert info['child_pid'] == child.pid and info['pgid'] == os.getpgrp()
info['leader_pid'] = os.getpid()
path = Path(sys.argv[1])
temporary = path.with_suffix('.publishing')
temporary.write_text(json.dumps(info))
temporary.replace(path)
print('owned stdout', flush=True)
print('owned stderr', file=sys.stderr, flush=True)
if sys.argv[3] == 'timeout':
    time.sleep(30)
raise SystemExit(7 if sys.argv[3] == 'failure' else 0)
""".replace("CHILD_CODE", repr(CHILD))


@pytest.fixture
def adopt_owned_children():
    # Linux containers need a subreaper to avoid leaving orphans with PID 1.
    if sys.platform == "linux":
        library = ctypes.CDLL(None, use_errno=True)
        original = ctypes.c_int()
        assert library.prctl(37, ctypes.byref(original), 0, 0, 0) == 0
        assert library.prctl(36, 1, 0, 0, 0) == 0
    try:
        yield
    finally:
        if sys.platform == "linux":
            assert library.prctl(36, original.value, 0, 0, 0) == 0


def group_absent(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def reap_owned_child(pid):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            waited, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        else:
            if waited == pid:
                return True
        time.sleep(0.005)
    return False


def text_output(value):
    return value.decode() if isinstance(value, bytes) else value


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize(
    ("mode", "check"), [("success", True), ("failure", True), ("failure", False), ("timeout", True)]
)
def test_installer_owns_closed_stdio_term_ignoring_descendant(
    tmp_path, mode, check, adopt_owned_children
):
    metadata, ready = tmp_path / "owned-pids.json", tmp_path / "child-ready.json"
    info = None
    try:
        command = [sys.executable, "-c", LEADER, str(metadata), str(ready), mode]
        if mode == "timeout":
            with pytest.raises(subprocess.TimeoutExpired) as failure:
                run(command, tmp_path, timeout=1, check=check)
            stdout, stderr = failure.value.stdout, failure.value.stderr
        elif mode == "failure" and check:
            with pytest.raises(subprocess.CalledProcessError) as failure:
                run(command, tmp_path, check=check)
            assert failure.value.returncode == 7
            stdout, stderr = failure.value.stdout, failure.value.stderr
        else:
            completed = run(command, tmp_path, check=check)
            assert completed.returncode == (7 if mode == "failure" else 0)
            stdout, stderr = completed.stdout, completed.stderr
        assert text_output(stdout) == "owned stdout\n"
        assert text_output(stderr) == "owned stderr\n"
        info = json.loads(metadata.read_text())
        assert info["leader_pid"] == info["pgid"] != os.getpgrp()
        assert reap_owned_child(info["child_pid"])
        assert group_absent(info["pgid"])
    finally:
        if info is None and ready.exists():
            info = json.loads(ready.read_text())
        if info is not None:
            assert info["pgid"] != os.getpgrp()
            with suppress(ProcessLookupError):
                os.killpg(info["pgid"], signal.SIGKILL)
            assert reap_owned_child(info["child_pid"])
            assert group_absent(info["pgid"])
