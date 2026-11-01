"""The owned editor declares Ctrl+C handling independently of its launcher."""

import json
import os
import sys
import termios
import time
from pathlib import Path

import pytest

from tests.support import editing_terminal


def test_editor_ctrl_c_with_an_ignored_parent_signal(tmp_path):
    launcher = tmp_path / "ignored-sigint-cli.py"
    launcher.write_text(
        "import signal\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "from kuberich.cli import main\n"
        "raise SystemExit(main())\n"
    )
    editing_terminal.terminal_editing(
        [sys.executable, str(launcher)],
        tmp_path,
        "editor-inherited-ignored-sigint",
        scenario="ctrl_c",
    )
    state = json.loads((tmp_path / "owned-editor-path.signals").read_text())
    assert state == {
        "inherited_sigint_ignored": True,
        "kernel_sigint_default": True,
        "vintr_hex": "03",
        "foreground": True,
        "isig": True,
        "canonical": True,
    }


@pytest.mark.skipif(
    sys.platform != "linux", reason="The owned pre-read state gate uses Linux /proc."
)
def test_editor_ctrl_c_at_the_cpython_prompt_before_read_window(tmp_path, monkeypatch):
    # The documented C-API input hook runs after the prompt and before fgets.
    # libc.pause holds that window without a compiler, timing sleep or Python
    # callback that could itself consume the deferred KeyboardInterrupt.
    prefix = """import ctypes,os,sys
from pathlib import Path
Path(sys.argv[1]+".input-hook-pid").write_text(str(os.getpid()))
libc=ctypes.CDLL(None)
libc.pause.argtypes=[]
libc.pause.restype=ctypes.c_int
ctypes.c_void_p.in_dll(ctypes.pythonapi,"PyOS_InputHook").value=ctypes.cast(libc.pause,ctypes.c_void_p).value
"""
    monkeypatch.setattr(editing_terminal, "EDITOR", prefix + editing_terminal.EDITOR)
    original_send = editing_terminal.TerminalSession.send
    observed = {}

    def send(terminal, data):
        if data == b"\x03":
            pid = int((tmp_path / "owned-editor-path.input-hook-pid").read_text())
            deadline = time.monotonic() + 5
            while True:
                state = (Path("/proc") / str(pid) / "wchan").read_text().strip()
                if "pause" in state or "sigsuspend" in state:
                    break
                assert time.monotonic() < deadline, "The owned editor never entered its input hook."
                terminal.read(0.01)
            mode = termios.tcgetattr(terminal.slave)
            observed.update(
                pid=pid,
                wait=state,
                foreground=os.tcgetpgrp(terminal.master) == pid,
                vintr_hex=mode[6][termios.VINTR].hex(),
                isig=bool(mode[3] & termios.ISIG),
                canonical=bool(mode[3] & termios.ICANON),
            )
            assert observed["foreground"] and observed["vintr_hex"] == "03"
            assert observed["isig"] and observed["canonical"]
            (tmp_path / "editor-pre-read-window.json").write_text(json.dumps(observed))
        return original_send(terminal, data)

    monkeypatch.setattr(editing_terminal.TerminalSession, "send", send)
    editing_terminal.terminal_editing(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "editor-cpython-pre-read-window",
        scenario="ctrl_c",
    )
    assert observed
    with pytest.raises(ProcessLookupError):
        os.kill(observed["pid"], 0)
