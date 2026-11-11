"""Actual creation-draft imports and disclosed editor handoff on owned terminals."""

import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path

from tests.terminal.pty_support import TerminalSession

EDITOR = """import json,os,pathlib,signal,stat,sys,termios,yaml
draft=pathlib.Path(sys.argv[-1])
assert sys.argv[-2]=='--'
assert stat.S_IMODE(draft.stat().st_mode)==0o600
assert stat.S_IMODE(draft.parent.stat().st_mode)==0o700
assert b'creation-pty-private-source' in draft.read_bytes()
marker=pathlib.Path(sys.argv[1])
marker.write_text(json.dumps({'draft':str(draft),'pid':os.getpid()}))
signal.signal(signal.SIGINT,signal.SIG_DFL)
print('OWNED CREATION EDITOR START',flush=True)
assert sys.stdin.readline().strip()=='start'
mode=termios.tcgetattr(0)
assert os.isatty(0) and os.tcgetpgrp(0)==os.getpgrp()
assert mode[3]&termios.ISIG and mode[3]&termios.ICANON and mode[3]&termios.ECHO
action=input('OWNED CREATION EDITOR READY > ')
if action=='fail': sys.exit(9)
if action=='invalid': draft.write_text('invalid: [creation-pty-private-source')
if action=='edit':
 value=yaml.safe_load(draft.read_text())
 value['metadata'].setdefault('labels',{})['example.io/creation']='reviewed-draft'
 value['data']['private']='creation-pty-private-edited'
 draft.write_text(json.dumps(value))
"""


def terminal_resource_creation(
    command, directory, evidence, *, scenario="success", size=(120, 36), cleanup_gate=None
):
    source = directory / "owned.yaml"
    source.write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-creation}\ndata: {private: creation-pty-private-source}\n"
    )
    before = source.read_bytes()
    config = directory / "owned-offline-kubeconfig"
    config.write_text("apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n")
    config_before = config.read_bytes()
    helper = directory / "owned-creation-editor.py"
    helper.write_text(EDITOR)
    marker = directory / "owned-creation-editor-marker"
    environment = {"KUBERICH_EDITOR": shlex.join([sys.executable, str(helper), str(marker)])}
    with TerminalSession(
        [*command, "--kubeconfig", str(config), "--command", "create"],
        directory,
        environment=environment,
        size=size,
    ) as terminal:
        terminal.wait_for_screen("Create resources · offline source")
        terminal.wait_for_screen("No cluster validation")
        # Back is initial focus. Tab wraps to the explicit file path.
        terminal.send(b"\towned.yaml\t\t\r")
        terminal.wait_for_screen("File captured offline")
        assert "creation-pty-private-source" not in "\n".join(terminal.screen.display)
        # Back -> Review -> Edit -> Import -> preview -> fresh disclosure.
        terminal.send(b"\x1b[Z\x1b[Z\x1b[Z\x1b[Z\x1b[Z \t\t\t\r")
        terminal.wait_for(b"OWNED CREATION EDITOR START")
        ready = terminal.send(b"start\r")
        terminal.wait_for(b"OWNED CREATION EDITOR READY", since=ready)
        state = json.loads(marker.read_text())
        draft = Path(state["draft"])
        terminal.resize(80, 24)
        if scenario == "sigterm":
            os.kill(state["pid"], signal.SIGTERM)
        else:
            terminal.send(
                {
                    "success": b"edit\r",
                    "repeat": b"noop\r",
                    "noop": b"noop\r",
                    "failure": b"fail\r",
                    "invalid": b"invalid\r",
                    "ctrl_c": b"\x03",
                }[scenario]
            )
        if cleanup_gate is not None:
            receipt, release = cleanup_gate
            terminal.send(b"\x1b")
            try:
                deadline = time.monotonic() + 5
                while not receipt.exists():
                    terminal.read(0.01)
                    assert time.monotonic() < deadline, "Owned draft cleanup was not entered"
                observed = json.loads(receipt.read_text())
                assert observed["foreground"] == "ResourceCreationScreen"
                assert draft.parent.exists()
            finally:
                if receipt.exists():
                    descriptor = os.open(release, os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        os.write(descriptor, b"1")
                    finally:
                        os.close(descriptor)
        else:
            needle = (
                "Draft updated"
                if scenario == "success"
                else "No changes"
                if scenario in {"noop", "repeat"}
                else "Invalid manifest YAML"
                if scenario == "invalid"
                else "Editor cancelled or failed"
            )
            terminal.wait_for_screen(needle)
            assert not draft.parent.exists()
            if scenario == "repeat":
                again = terminal.send(b"\x1b[Z\x1b[Z\x1b[Z\x1b[Z\x1b[Z \t\t\t\r")
                terminal.wait_for(b"OWNED CREATION EDITOR START", since=again)
                ready = terminal.send(b"start\r")
                terminal.wait_for(b"OWNED CREATION EDITOR READY", since=ready)
                terminal.send(b"noop\r")
                terminal.wait_for_screen("No changes")
            terminal.resize(120, 36)
            terminal.send(b"\x1b")
        terminal.wait_for_screen("Status", absent=("Create resources · offline source",))
        assert source.read_bytes() == before
        assert not draft.parent.exists()
        assert "creation-pty-private-source" not in "\n".join(terminal.screen.display)
        assert "creation-pty-private-edited" not in "\n".join(terminal.screen.display)
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
    assert config.read_bytes() == config_before
