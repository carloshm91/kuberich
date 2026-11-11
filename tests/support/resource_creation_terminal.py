"""Actual creation-draft imports and disclosed editor handoff on owned terminals."""

import json
import os
import shlex
import signal
import sys
import time
from collections.abc import Callable, Mapping
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

SHELL_EDITOR = """#!/bin/sh
set -eu
test "$2" = --
test -t 0
marker=$1
draft=$3
printf '%s\\n%s\\n' "$draft" "$$" > "$marker"
printf 'OWNED CREATION EDITOR START\\n'
IFS= read -r starting
test "$starting" = start
printf 'OWNED CREATION EDITOR READY > '
IFS= read -r action
case "$action" in
 edit) printf '%s\\n' 'apiVersion: v1' 'kind: ConfigMap' 'metadata:' '  name: owned-creation' '  labels: {example.io/creation: reviewed-draft}' 'data: {private: creation-pty-private-edited}' > "$draft" ;;
 noop) : ;;
 invalid) printf '%s\\n' 'invalid: [creation-pty-private-source' > "$draft" ;;
 *) exit 9 ;;
esac
"""

type CommandWrap = Callable[[list[str], dict[str, str], Path], list[str]]


def terminal_resource_creation(
    command: list[str],
    directory: Path,
    evidence: str,
    *,
    scenario: str = "success",
    size: tuple[int, int] = (120, 36),
    cleanup_gate: tuple[Path, Path] | None = None,
    shell_editor: bool = False,
    wrap: CommandWrap | None = None,
    environment: Mapping[str, str] | None = None,
    controller_environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if wrap is not None and scenario == "sigterm":
        raise ValueError(
            "Wrapped terminals cannot send host PID signals to namespace-local children."
        )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = directory / "private"
    private.mkdir(mode=0o700)
    source = directory / "owned.yaml"
    source.write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-creation}\ndata: {private: creation-pty-private-source}\n"
    )
    before = source.read_bytes()
    config = directory / "owned-offline-kubeconfig"
    config.write_text("apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n")
    config_before = config.read_bytes()
    helper = directory / (
        "owned-creation-editor.sh" if shell_editor else "owned-creation-editor.py"
    )
    helper.write_text(SHELL_EDITOR if shell_editor else EDITOR)
    helper.chmod(0o700)
    marker = directory / "owned-creation-editor-marker"
    preferences = directory / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    process_environment = {
        **dict(environment or {}),
        "TMPDIR": str(private),
        "KUBERICH_CONFIG": str(preferences),
        "KUBERICH_LOG_FILE": str(directory / "kuberich.log"),
        "KUBERICH_CLIPBOARD": "osc52",
        "KUBERICH_EDITOR": shlex.join(
            ["/bin/sh" if shell_editor else sys.executable, str(helper), str(marker)]
        ),
    }
    outside = dict(controller_environment or {})
    if wrap is None:
        outside.update(process_environment)
    argv = [*command, "--kubeconfig", str(config), "--command", "create"]
    if wrap is not None:
        argv = wrap(argv, process_environment, directory)
    drafts: list[Path] = []

    def editor_state() -> tuple[Path, int]:
        if not shell_editor:
            state = json.loads(marker.read_text())
            return Path(state["draft"]), int(state["pid"])
        filename, pid = marker.read_text().splitlines()
        return Path(filename), int(pid)

    with TerminalSession(
        argv,
        directory,
        environment=outside,
        size=size,
    ) as terminal:
        terminal.wait_for_screen("Create resources · offline source")
        terminal.wait_for_screen("No cluster validation")
        # Back -> source selector -> explicit file path -> preview -> Import.
        terminal.send(b"\t\towned.yaml\t\t\r")
        terminal.wait_for_screen("File captured offline")
        assert "creation-pty-private-source" not in "\n".join(terminal.screen.display)
        # Back -> Review -> Edit -> Import -> preview -> fresh disclosure.
        terminal.send(b"\x1b[Z\x1b[Z\x1b[Z\x1b[Z\x1b[Z \t\t\t\r")
        terminal.wait_for(b"OWNED CREATION EDITOR START")
        ready = terminal.send(b"start\r")
        terminal.wait_for(b"OWNED CREATION EDITOR READY", since=ready)
        draft, editor_pid = editor_state()
        drafts.append(draft)
        assert draft.stat().st_mode & 0o777 == 0o600
        assert draft.parent.stat().st_mode & 0o777 == 0o700
        assert b"creation-pty-private-source" in draft.read_bytes()
        terminal.resize(80, 24)
        if scenario == "sigterm":
            os.kill(editor_pid, signal.SIGTERM)
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
                repeated, _ = editor_state()
                drafts.append(repeated)
                terminal.send(b"noop\r")
                terminal.wait_for_screen("No changes")
            terminal.resize(120, 36)
            terminal.send(b"\x1b")
        terminal.wait_for_screen(
            "No cluster connection", absent=("Create resources · offline source",)
        )
        assert source.read_bytes() == before
        assert not draft.parent.exists()
        assert all(not path.parent.exists() for path in drafts)
        assert not tuple(private.iterdir())
        assert "creation-pty-private-source" not in "\n".join(terminal.screen.display)
        assert "creation-pty-private-edited" not in "\n".join(terminal.screen.display)
        terminal.send(b"\x11")
        terminal.finish()
        for token in (b"creation-pty-private-source", b"creation-pty-private-edited"):
            assert token not in terminal.transcript
            assert token not in (directory / "kuberich.log").read_bytes()
        terminal.save_evidence(evidence)
    assert config.read_bytes() == config_before
    return {
        "editor": "/bin/sh" if shell_editor else "configured Python fixture",
        "editor_sessions": len(drafts),
        "private_files_absent": all(not path.parent.exists() for path in drafts),
        "source_unchanged": source.read_bytes() == before,
        "kubeconfig_unchanged": config.read_bytes() == config_before,
        "wrapped": wrap is not None,
    }
