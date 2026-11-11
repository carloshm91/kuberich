"""Installer commands drain owned descendants without changing outputs or exits."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from contextlib import suppress

import pytest

from scripts import ci_apt
from tests.support.distribution import run

FAILURE_PROGRAM = """
import sys
from pathlib import Path
directory = Path(__file__).parent
sys.stdout.write((directory / 'stdout.txt').read_text())
sys.stderr.write((directory / 'stderr.txt').read_text())
raise SystemExit(19)
"""


def failing_command(tmp_path, stdout, stderr):
    script = tmp_path / "owned-failing-installer.py"
    script.write_text(FAILURE_PROGRAM)
    for name, value in (("stdout", stdout), ("stderr", stderr)):
        path = tmp_path / (name + ".txt")
        path.write_text(value)
        path.chmod(0o600)
    return [sys.executable, "-I", "-S", str(script)]


def test_failed_installer_notes_preserve_cause_and_raw_attributes_without_credentials(tmp_path):
    stdout = "Preparing the owned fixture wheel.\n"
    stderr = (
        "Dependency download refused: HTTP 503.\n"
        "Authorization: Bearer synthetic-private-bearer\n"
        "https://fixture-user:synthetic-private-password@example.invalid/simple\n"
        "password=synthetic-private-assignment\n"
        "-----BEGIN PRIVATE KEY-----\nsynthetic-private-key\n-----END PRIVATE KEY-----\n"
        "\x1b]52;c;synthetic-clipboard\x07\x1b[31mterminal controls\x1b[0m\n"
    )
    command = failing_command(tmp_path, stdout, stderr)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run(command, tmp_path, timeout=3)
    error = caught.value
    assert error.returncode == 19 and error.cmd == command
    assert error.stdout == stdout and error.stderr == stderr
    notes = error.__notes__
    assert len(notes) == 2 and all(len(note) <= 8192 for note in notes)
    rendered = "".join(traceback.format_exception_only(error))
    assert "Preparing the owned fixture wheel." in rendered
    assert "Dependency download refused: HTTP 503." in rendered
    assert "[REDACTED]" in rendered and "[REDACTED KEY]" in rendered
    assert "synthetic-private" not in rendered and "fixture-user" not in rendered
    assert "\x1b" not in rendered and "\x07" not in rendered


def test_failed_installer_redacts_before_clipping_and_reports_the_bound(tmp_path):
    secret = "synthetic-private-" + "x" * 10000
    stdout = "password=" + secret + "\nCausal detail after the long credential.\n" + "f" * 70000
    command = failing_command(tmp_path, stdout, "Owned fixture failure.\n")
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run(command, tmp_path, timeout=3)
    error = caught.value
    assert error.returncode == 19 and error.cmd == command and error.stdout == stdout
    notes = error.__notes__
    assert len(notes) == 2 and all(len(note) <= 8192 for note in notes)
    assert notes[0].endswith("[diagnostic truncated]")
    assert "Causal detail after the long credential." in notes[0]
    assert "synthetic-private" not in "".join(notes) and "x" * 100 not in "".join(notes)


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


@pytest.mark.skipif(sys.platform != "linux", reason="requires GNU timeout and owned-child adoption")
def test_compiler_syntax_preflight_timeout_drains_its_owned_process_group(
    tmp_path, monkeypatch, adopt_owned_children
):
    metadata, ready = tmp_path / "owned-compiler.json", tmp_path / "compiler-child-ready.json"
    actual_run = subprocess.run
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def command(argv, **kwargs):
        if argv[0] == "/usr/bin/dpkg-query":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=b"".join(
                    f"{name}\tinstall ok installed\t1.0\n".encode()
                    for name in ("gcc", "libc6-dev", "binutils")
                ),
            )
        if argv[0] != "/usr/bin/timeout":
            assert argv in {
                ("/usr/bin/gcc", "--version"),
                ("/usr/bin/cc", "--version"),
                ("/usr/bin/readelf", "--version"),
                ("/usr/bin/objdump", "--version"),
            }
            return subprocess.CompletedProcess(argv, 0)
        assert argv[:4] == ("/usr/bin/timeout", "--signal=TERM", "--kill-after=1s", "5s")
        assert argv[4:] == ("/usr/bin/cc", "-fsyntax-only", "-x", "c", "-")
        assert kwargs["timeout"] == 8
        # The compiler and its cc1-like child both ignore TERM, requiring KILL.
        program = "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" + LEADER
        return actual_run(
            (*argv[:4], sys.executable, "-c", program, str(metadata), str(ready), "timeout"),
            **kwargs,
        )

    monkeypatch.setattr(ci_apt.subprocess, "run", command)
    info = None
    try:
        assert not ci_apt.compiler_ready(("gcc", "libc6-dev", "binutils"))
        info = json.loads(metadata.read_text())
        assert info["pgid"] not in {os.getpgrp(), os.getpgid(unrelated.pid)}
        assert reap_owned_child(info["leader_pid"])
        assert reap_owned_child(info["child_pid"])
        assert group_absent(info["pgid"])
        assert unrelated.poll() is None
    finally:
        if info is None and metadata.exists():
            info = json.loads(metadata.read_text())
        if info is not None:
            assert info["pgid"] != os.getpgrp()
            with suppress(ProcessLookupError):
                os.killpg(info["pgid"], signal.SIGKILL)
            assert reap_owned_child(info["leader_pid"])
            assert reap_owned_child(info["child_pid"])
            assert group_absent(info["pgid"])
        unrelated.kill()
        unrelated.wait(timeout=3)
