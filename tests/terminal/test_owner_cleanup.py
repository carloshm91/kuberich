"""A failed terminal body must not abandon its direct child or diagnostic lock."""

import asyncio
import errno
import fcntl
import json
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.terminal import pty_support
from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("ignore_term", [False, True])
def test_failed_terminal_body_reaps_child_and_releases_lock(tmp_path, ignore_term):
    child = (
        "import fcntl,os,signal,time\n"
        "from pathlib import Path\n"
        "lock = open('owned-log.lock','w')\n"
        "fcntl.flock(lock,fcntl.LOCK_EX)\n"
        "Path('child.pid').write_text(str(os.getpid()))\n"
        "signal.signal(signal.SIGHUP,signal.SIG_IGN)\n"
        + (
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            if ignore_term
            else "signal.signal(signal.SIGTERM,lambda *_: time.sleep(0.5) or os._exit(0))\n"
        )
        + "os.write(1,b'owned-child-ready')\nwhile True: signal.pause()\n"
    )
    pid = None
    try:
        with (
            pytest.raises(RuntimeError, match="owned injected body failure"),
            TerminalSession([sys.executable, "-c", child], tmp_path) as terminal,
        ):
            terminal.wait_for(b"owned-child-ready")
            pid = int((tmp_path / "child.pid").read_text())
            raise RuntimeError("owned injected body failure")
        assert terminal.process.poll() == 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        with (tmp_path / "owned-log.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert terminal.cleanup["status"] == "complete"
        assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
        for descriptor in (
            terminal.master,
            terminal.slave,
            terminal.completion_read,
            terminal.acknowledgement_write,
        ):
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def child_command():
    return [
        sys.executable,
        "-c",
        "import os,signal;os.write(1,b'cleanup-ready');signal.pause()",
    ]


def assert_descriptors_closed(terminal):
    for descriptor in (
        terminal.master,
        terminal.slave,
        terminal.completion_read,
        terminal.acknowledgement_write,
    ):
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@pytest.mark.parametrize("system", ["linux", "darwin"])
@pytest.mark.parametrize("probe", ["gone", "live", "denied"])
def test_denied_signal_policy_needs_esrch_and_never_treats_live_denial_as_exit(
    tmp_path, monkeypatch, system, probe
):
    # Inject just the platform errno sequence into a real disposable session;
    # restore the primitive before its real teardown. This is not a native
    # Darwin kernel trial or evidence that an actually live group disappeared.
    with TerminalSession(child_command(), tmp_path) as terminal:
        terminal.wait_for(b"cleanup-ready")
        calls = []

        def denied(pid, value):
            assert pid == terminal.process.pid
            calls.append(value)
            if value:
                raise PermissionError(errno.EPERM, "owned injected group denial")
            if probe == "gone":
                raise ProcessLookupError(errno.ESRCH, "owned injected group disappearance")
            if probe == "denied":
                raise PermissionError(errno.EPERM, "owned persistent probe denial")

        with monkeypatch.context() as faults:
            faults.setattr(pty_support, "sys", SimpleNamespace(platform=system))
            faults.setattr(os, "killpg", denied)
            if system == "darwin" and probe == "gone":
                assert terminal._signal_group(signal.SIGKILL, time.monotonic() + 3) == "gone"
            else:
                with pytest.raises(PermissionError):
                    terminal._signal_group(signal.SIGKILL, time.monotonic() + 3)
        assert calls[0] == signal.SIGKILL
        assert calls[1:] == ([] if system == "linux" else [0] * (5 if probe == "denied" else 1))
    assert terminal.cleanup["group"] == "gone"
    assert_descriptors_closed(terminal)


@pytest.mark.parametrize("probe", ["live", "denied"])
def test_first_assertion_survives_actual_denied_cleanup_with_separate_receipt(
    tmp_path, monkeypatch, probe
):
    monkeypatch.setattr(pty_support, "ROOT", tmp_path)
    first = AssertionError("owned first behavioral assertion")
    terminal = TerminalSession(child_command(), tmp_path)
    real_killpg = os.killpg
    calls = []

    def denied(pid, value):
        assert pid == terminal.process.pid
        calls.append(value)
        if value or probe == "denied":
            raise PermissionError(errno.EPERM, "owned injected denied cleanup")
        return real_killpg(pid, value)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(pty_support, "sys", SimpleNamespace(platform="darwin"))
        monkeypatch.setattr(os, "killpg", denied)
        raise first
    assert observed.value is first
    assert any("PermissionError" in note for note in first.__notes__)
    assert terminal.cleanup["status"] == "failed" and terminal.cleanup["owner_reaped"]
    assert_descriptors_closed(terminal)
    receipt = json.loads(next((tmp_path / "artifacts/terminal").glob("failure-*.json")).read_text())
    assert receipt["error_type"] == "AssertionError"
    assert receipt["body_error"] == str(first)
    assert receipt["cleanup"]["status"] == "failed"
    assert any(error["type"] == "PermissionError" for error in receipt["cleanup"]["errors"])
    with pytest.raises(ProcessLookupError):
        real_killpg(terminal.process.pid, 0)


@pytest.mark.parametrize("failure", [AssertionError, asyncio.CancelledError, KeyboardInterrupt])
def test_body_exception_identity_survives_acknowledgement_failure(tmp_path, monkeypatch, failure):
    first = failure("owned body failure")
    terminal = TerminalSession(child_command(), tmp_path)
    original = os.write

    def write(descriptor, data):
        if descriptor == terminal.acknowledgement_write:
            raise BrokenPipeError(errno.EPIPE, "owned acknowledgement failure")
        return original(descriptor, data)

    with pytest.raises(failure) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(os, "write", write)
        raise first
    assert observed.value is first
    assert terminal.cleanup["status"] == "failed"
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["completion_observed"]
    assert not terminal.cleanup["acknowledged"]
    assert any("BrokenPipeError" in note for note in first.__notes__)
    assert_descriptors_closed(terminal)


def test_evidence_failure_cannot_skip_reaping_or_replace_the_first_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pty_support, "ROOT", tmp_path)
    terminal = TerminalSession(child_command(), tmp_path)
    original = Path.write_text
    first = AssertionError("owned first assertion before evidence failure")

    def write(path, text, *args, **kwargs):
        if path.parent == tmp_path / "artifacts/terminal":
            raise OSError(errno.ENOSPC, "owned evidence write failure")
        return original(path, text, *args, **kwargs)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(Path, "write_text", write)
        raise first
    assert observed.value is first
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
    assert terminal.cleanup["status"] == "failed" and "evidence_error" in terminal.cleanup
    assert any("unavailable" in note for note in first.__notes__)
    assert_descriptors_closed(terminal)


def test_repeat_teardown_does_not_close_a_recycled_descriptor(tmp_path):
    terminal = TerminalSession(child_command(), tmp_path)
    with terminal:
        terminal.wait_for(b"cleanup-ready")
    assert terminal.cleanup["status"] == "complete"
    assert_descriptors_closed(terminal)
    with (tmp_path / "unrelated-file").open("w") as unrelated:
        terminal.__exit__(None, None, None)
        unrelated.write("still open")
        unrelated.flush()
        assert os.fstat(unrelated.fileno())


def test_changed_live_group_is_refused_without_signalling_any_other_group(tmp_path, monkeypatch):
    first = AssertionError("owned body assertion before identity refusal")
    terminal = TerminalSession(child_command(), tmp_path)
    original_group, original_signal = os.getpgid, os.killpg
    signals = []

    def group(pid):
        return os.getpgrp() if pid == terminal.process.pid else original_group(pid)

    def killpg(pid, value):
        signals.append((pid, value))
        return original_signal(pid, value)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(os, "getpgid", group)
        monkeypatch.setattr(os, "killpg", killpg)
        raise first
    assert observed.value is first
    assert all(pid == terminal.process.pid and value == 0 for pid, value in signals)
    assert terminal.cleanup["status"] == "failed" and terminal.cleanup["owner_reaped"]
    assert_descriptors_closed(terminal)


@pytest.mark.parametrize("denied", [False, True])
def test_post_child_reap_owner_hang_preserves_first_assertion_through_kill_escalation(
    tmp_path, monkeypatch, denied
):
    # The direct application child is reaped before the owner stalls. This
    # reproduces the original wait(3) -> killpg failure boundary using only
    # disposable processes, without leaving an orphan behind the injected hang.
    owner = pty_support._SESSION_OWNER.replace(
        "after = termios.tcgetattr(0)", "while True: time.sleep(0.1)\nafter = termios.tcgetattr(0)"
    )
    monkeypatch.setattr(pty_support, "_SESSION_OWNER", owner)
    first = AssertionError("owned first assertion before the three-second owner timeout")
    terminal = TerminalSession(child_command(), tmp_path)
    original = os.killpg

    def killpg(pid, value):
        assert pid == terminal.process.pid
        if denied and value == signal.SIGKILL:
            raise PermissionError(errno.EPERM, "owned Darwin group denial after timeout")
        return original(pid, value)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(os, "killpg", killpg)
        monkeypatch.setattr(pty_support, "sys", SimpleNamespace(platform="darwin"))
        raise first
    assert observed.value is first
    assert {"wait_seconds": 3, "outcome": "timeout"} in terminal.cleanup["stages"]
    assert any(stage.get("signal") == "SIGKILL" for stage in terminal.cleanup["stages"])
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
    assert not terminal.cleanup["completion_observed"] and terminal.completion is None
    assert terminal.cleanup["status"] == ("failed" if denied else "complete")
    assert_descriptors_closed(terminal)


def test_cleanup_failure_without_a_body_failure_raises(tmp_path, monkeypatch):
    terminal = TerminalSession(child_command(), tmp_path)
    original = os.killpg

    def denied(pid, value):
        assert pid == terminal.process.pid
        if value:
            raise PermissionError(errno.EPERM, "owned denied cleanup without body error")
        return original(pid, value)

    with pytest.raises(ExceptionGroup) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(os, "killpg", denied)
    assert any(isinstance(error, PermissionError) for error in observed.value.exceptions)
    assert terminal.cleanup["status"] == "failed" and terminal.cleanup["owner_reaped"]
    assert_descriptors_closed(terminal)


def test_one_close_failure_does_not_mask_body_or_skip_other_descriptors(tmp_path, monkeypatch):
    first = AssertionError("owned assertion before descriptor failure")
    terminal = TerminalSession(child_command(), tmp_path)
    original = os.close
    failed = False

    def close(descriptor):
        nonlocal failed
        original(descriptor)
        if descriptor == terminal.master and not failed:
            failed = True
            raise OSError(errno.EIO, "owned close failure after descriptor release")

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(os, "close", close)
        raise first
    assert observed.value is first
    assert terminal.cleanup["status"] == "failed" and terminal.cleanup["owner_reaped"]
    assert_descriptors_closed(terminal)
    with (tmp_path / "unrelated-after-error").open("w") as unrelated:
        with pytest.raises(ExceptionGroup):
            terminal.__exit__(None, None, None)
        assert os.fstat(unrelated.fileno())


@pytest.mark.parametrize("failure", ["attributes", "pipe", "preferences", "spawn"])
def test_constructor_failure_releases_every_allocated_descriptor(tmp_path, monkeypatch, failure):
    allocated = []
    original_openpty, original_pipe = pty_support.pty.openpty, os.pipe

    def openpty():
        pair = original_openpty()
        allocated.extend(pair)
        return pair

    def pipe():
        if failure == "pipe":
            raise OSError(errno.EMFILE, "owned pipe allocation failure")
        pair = original_pipe()
        allocated.extend(pair)
        return pair

    def broken(*args, **kwargs):
        raise RuntimeError("owned setup failure")

    monkeypatch.setattr(pty_support.pty, "openpty", openpty)
    monkeypatch.setattr(os, "pipe", pipe)
    if failure == "attributes":
        monkeypatch.setattr(pty_support.termios, "tcgetattr", broken)
    elif failure == "preferences":
        monkeypatch.setattr(Path, "write_text", broken)
    elif failure == "spawn":
        monkeypatch.setattr(pty_support.subprocess, "Popen", broken)
    with pytest.raises((RuntimeError, OSError)):
        TerminalSession(child_command(), tmp_path)
    assert allocated
    for descriptor in allocated:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


def test_closed_acknowledgement_pipe_fails_without_reusing_its_fd(tmp_path):
    terminal = TerminalSession(child_command(), tmp_path)
    with pytest.raises(ExceptionGroup), terminal:
        terminal.wait_for(b"cleanup-ready")
        terminal._close_descriptor(terminal.acknowledgement_write)
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["status"] == "failed"
    assert not terminal.cleanup["acknowledged"]
    assert_descriptors_closed(terminal)


def test_early_reaped_owner_allows_only_read_only_group_probes(tmp_path, monkeypatch):
    first = AssertionError("owned assertion after early session-owner exit")
    command = [sys.executable, "-c", "import os;os.write(1,b'early-completion')"]
    terminal = TerminalSession(command, tmp_path)
    calls = []
    original = os.killpg

    def killpg(pid, value):
        calls.append((pid, value))
        return original(pid, value)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"early-completion")
        deadline = time.monotonic() + 3
        while terminal.completion is None:
            terminal._read()
            assert time.monotonic() < deadline
        # The actual child has already exited and been reaped by its guard.
        terminal.process.kill()
        terminal.process.wait(timeout=3)
        monkeypatch.setattr(os, "killpg", killpg)
        raise first
    assert observed.value is first
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
    assert terminal.cleanup["owner_returncode"] == -signal.SIGKILL
    assert calls and all(pid == terminal.process.pid and value == 0 for pid, value in calls)
    assert terminal.completion["exit"] == 0
    assert_descriptors_closed(terminal)


def test_acknowledgement_waits_for_fresh_observation_and_reaping_of_an_owned_group_member(
    tmp_path, monkeypatch
):
    extra = """import os,signal,sys,time
from pathlib import Path
def stop(*_):
    while not Path('release-member').exists():
        time.sleep(0.01)
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
Path('member.pid').write_text(str(os.getpid()))
os.write(1,b'owned-member-ready')
while True: signal.pause()
"""
    owner = pty_support._SESSION_OWNER.replace(
        "process = subprocess.Popen(sys.argv[3:])",
        f"extra = subprocess.Popen([sys.executable, '-c', {extra!r}])\n"
        "process = subprocess.Popen(sys.argv[3:])",
    ).replace(
        "os.read(int(sys.argv[2]), 1)",
        "import threading\nthreading.Thread(target=extra.wait).start()\n"
        "os.read(int(sys.argv[2]), 1)",
    )
    monkeypatch.setattr(pty_support, "_SESSION_OWNER", owner)
    first = AssertionError("owned body failure with a terminating group member")
    terminal = TerminalSession(child_command(), tmp_path)
    snapshots, acknowledgements = [], []
    original_run, original_write = pty_support.subprocess.run, os.write
    member = None

    def run(command, *args, **kwargs):
        result = original_run(command, *args, **kwargs)
        if command == ["ps", "-axo", "pid=,pgid="]:
            snapshot = {
                int(row.split()[0])
                for row in result.stdout.splitlines()
                if int(row.split()[1]) == terminal.process.pid
            }
            snapshots.append(snapshot)
            if member in snapshot:
                (tmp_path / "release-member").touch()
        return result

    def write(descriptor, data):
        if descriptor == terminal.acknowledgement_write:
            assert snapshots[-1] == {terminal.process.pid}
            with pytest.raises(ProcessLookupError):
                os.kill(member, 0)
            acknowledgements.append(True)
        return original_write(descriptor, data)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        terminal.wait_for(b"owned-member-ready")
        member = int((tmp_path / "member.pid").read_text())
        assert os.getpgid(member) == os.getsid(member) == terminal.process.pid
        monkeypatch.setattr(pty_support.subprocess, "run", run)
        monkeypatch.setattr(os, "write", write)
        raise first
    assert observed.value is first
    assert any(member in snapshot for snapshot in snapshots)
    assert acknowledgements == [True]
    assert terminal.cleanup["status"] == "complete" and terminal.cleanup["group"] == "gone"
    assert_descriptors_closed(terminal)


@pytest.mark.parametrize("interruption", [InterruptedError, KeyboardInterrupt])
def test_cleanup_poll_interruption_still_reaps_owner_and_preserves_the_body(
    tmp_path, monkeypatch, interruption
):
    first = AssertionError("owned first assertion before interrupted cleanup wait")
    terminal = TerminalSession(child_command(), tmp_path)
    original = terminal.process.poll
    calls = 0

    def poll():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise interruption("owned cleanup wait interruption")
        return original()

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(terminal.process, "poll", poll)
        raise first
    assert observed.value is first
    assert terminal.cleanup["poll_failures"] == 1 and terminal.cleanup["status"] == "failed"
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
    assert_descriptors_closed(terminal)


def test_expired_membership_observation_cannot_report_an_empty_group(tmp_path):
    with TerminalSession(child_command(), tmp_path) as terminal:
        terminal.wait_for(b"cleanup-ready")
        with pytest.raises(TimeoutError, match="group observation exceeded"):
            terminal._group_members(time.monotonic() - 1)
    assert terminal.cleanup["status"] == "complete"
    assert_descriptors_closed(terminal)


def test_killed_guard_never_attempts_a_completion_acknowledgement(tmp_path, monkeypatch):
    first = AssertionError("owned first assertion before a completed but pinned guard is killed")
    terminal = TerminalSession(child_command(), tmp_path)
    original_members = terminal._group_members
    original_signal, original_write, original_poll = os.killpg, os.write, terminal.process.poll
    killed, deferred_poll, acknowledgements = False, False, []

    def members(deadline):
        # A deliberately uncertain observation pins the real owner after its
        # real child has exited. No extra process or unrelated signal target
        # is created. Once killed, a stale owner-only observation must never
        # cause a write into the guard's now-unread acknowledgement pipe.
        return {terminal.process.pid} if killed else original_members(deadline) | {0}

    def killpg(pid, value):
        nonlocal killed
        result = original_signal(pid, value)
        if value == signal.SIGKILL:
            killed = True
        return result

    def poll():
        nonlocal deferred_poll
        if killed and not deferred_poll:
            deferred_poll = True
            return None  # Exercise the interval before the next actual reap.
        return original_poll()

    def write(descriptor, data):
        if descriptor == terminal.acknowledgement_write:
            acknowledgements.append(True)
            raise BrokenPipeError(errno.EPIPE, "a killed guard cannot consume an acknowledgement")
        return original_write(descriptor, data)

    with pytest.raises(AssertionError) as observed, terminal:
        terminal.wait_for(b"cleanup-ready")
        monkeypatch.setattr(terminal, "_group_members", members)
        monkeypatch.setattr(os, "killpg", killpg)
        monkeypatch.setattr(terminal.process, "poll", poll)
        monkeypatch.setattr(os, "write", write)
        raise first
    assert observed.value is first
    assert killed and deferred_poll and not acknowledgements
    assert terminal.cleanup["status"] == "complete" and terminal.cleanup["group"] == "gone"
    assert terminal.cleanup["owner_returncode"] == -signal.SIGKILL
    assert terminal.cleanup["completion_observed"] and not terminal.cleanup["acknowledged"]
    assert terminal.completion["exit"] == -signal.SIGTERM
    assert_descriptors_closed(terminal)
