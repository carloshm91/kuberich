"""Actual offline CLI local-file editing through the owned native terminal lease."""

import json
import os
import shlex
import signal
import sys
from pathlib import Path

from tests.terminal.pty_support import TerminalSession

EDITOR = """import json,os,pathlib,signal,stat,sys,termios,yaml
draft=pathlib.Path(sys.argv[-1])
assert sys.argv[-2]=='--'
assert stat.S_IMODE(draft.stat().st_mode)==0o600
assert stat.S_IMODE(draft.parent.stat().st_mode)==0o700
assert b'local-pty-private-source' in draft.read_bytes()
marker=pathlib.Path(sys.argv[1])
marker.write_text(json.dumps({'draft':str(draft),'pid':os.getpid()}))
signal.signal(signal.SIGINT,signal.SIG_DFL)
print('OWNED LOCAL EDITOR START',flush=True)
assert sys.stdin.readline().strip()=='start'
mode=termios.tcgetattr(0)
assert os.isatty(0) and os.tcgetpgrp(0)==os.getpgrp()
assert mode[3]&termios.ISIG and mode[3]&termios.ICANON and mode[3]&termios.ECHO
action=input('OWNED LOCAL EDITOR READY > ')
if action=='fail': sys.exit(9)
if action=='invalid': draft.write_text('invalid: [local-pty-private-source')
if action=='edit':
 value=yaml.safe_load(draft.read_text())
 value['metadata'].setdefault('labels',{})['example.io/local']='reviewed-local-change'
 value['data']['private']='local-pty-private-edited'
 draft.write_text(json.dumps(value))
"""


def terminal_local_manifests(command, directory, evidence, *, scenario="success", size=(120, 36)):
    source = directory / "owned.yaml"
    source.write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-local}\ndata: {private: local-pty-private-source}\n"
    )
    before = source.read_bytes()
    config = directory / "owned-offline-kubeconfig"
    config.write_text("apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n")
    config_before = config.read_bytes()
    helper = directory / "owned-local-editor.py"
    helper.write_text(EDITOR)
    marker = directory / "owned-local-editor-marker"
    environment = {"KUBERICH_EDITOR": shlex.join([sys.executable, str(helper), str(marker)])}
    with TerminalSession(
        [*command, "--kubeconfig", str(config), "--command", "manifests"],
        directory,
        environment=environment,
        size=size,
    ) as terminal:
        terminal.wait_for_screen("Local manifests · inspect")
        terminal.wait_for_screen("no files or helpers executed")
        # Back is the default; reverse traversal skips unavailable page/review controls.
        terminal.send(b"\x1b[Z\x1b[Z\r")
        terminal.wait_for_screen("Ready · allow fresh disclosure")
        terminal.send(b"\t \t\t\r")
        terminal.wait_for(b"OWNED LOCAL EDITOR START")
        ready = terminal.send(b"start\r")
        terminal.wait_for(b"OWNED LOCAL EDITOR READY", since=ready)
        state = json.loads(marker.read_text())
        draft = Path(state["draft"])
        terminal.resize(80, 24)
        if scenario == "sigterm":
            # Signal only the fixture-owned editor child; its process owner must reap it.
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
        needle = (
            "Review the redacted diff"
            if scenario == "success"
            else "No changes"
            if scenario in {"noop", "repeat"}
            else "Invalid manifest YAML"
            if scenario == "invalid"
            else "Editor cancelled or failed"
        )
        terminal.wait_for_screen(needle)
        assert source.read_bytes() == before
        assert "local-pty-private-source" not in "\n".join(terminal.screen.display)
        assert "local-pty-private-edited" not in "\n".join(terminal.screen.display)
        if scenario == "repeat":
            again = terminal.send(b"\t \t\t\r")
            terminal.wait_for(b"OWNED LOCAL EDITOR START", since=again)
            ready = terminal.send(b"start\r")
            terminal.wait_for(b"OWNED LOCAL EDITOR READY", since=ready)
            terminal.send(b"noop\r")
            terminal.wait_for_screen("No changes")
        if scenario == "success":
            # Back -> Open -> Save local; the cluster still has no connection.
            terminal.send(b"\t\t\t\t\r")
            terminal.wait_for_screen("Local source saved")
            assert b"local-pty-private-edited" in source.read_bytes()
        terminal.resize(120, 36)
        terminal.wait_for_screen("Edit local manifest")
        terminal.send(b"\x1b")
        terminal.wait_for_screen("Local manifests · inspect", absent=("Edit local manifest",))
        assert not draft.parent.exists()
        terminal.send(b"\x1b\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
    assert config.read_bytes() == config_before
