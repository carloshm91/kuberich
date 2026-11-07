"""READY must describe actual helper foreground ownership before native Ctrl+C."""

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from tests.support import credential_handoff as handoff
from tests.support.terminal_modes import restored_modes

CLAIM_GATE = """
from kuberich.adapters.terminal import TerminalLease
import select
original_claim = TerminalLease.claim
def held_claim(self, group):
    handler = signal.getsignal(signal.SIGINT)
    function = getattr(handler, 'func', handler)
    pending = Path('claim-entry.pending')
    pending.write_text(json.dumps({
        'foreground': os.tcgetpgrp(self.descriptor),
        'app_group': os.getpgrp(), 'helper_group': group,
        'sigint_type': type(handler).__name__,
        'sigint_function_module': getattr(function, '__module__', None),
        'sigint_function_name': getattr(function, '__qualname__', None)}))
    pending.replace('claim-entry.json')
    descriptor = os.open('claim-release', os.O_RDONLY | os.O_NONBLOCK)
    try:
        assert select.select([descriptor], [], [], 15)[0], 'Claim was not released'
        assert os.read(descriptor, 1) == b'x'
    finally:
        os.close(descriptor)
    return original_claim(self, group)
TerminalLease.claim = held_claim
"""


@pytest.mark.parametrize("premature_ready", [False, True])
def test_generic_login_ready_requires_the_real_foreground_claim(
    tmp_path, monkeypatch, premature_ready
):
    output = Path(__file__).resolve().parents[2] / "artifacts/terminal/credential-foreground"
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    evidence = Path(tempfile.mkdtemp(prefix=tmp_path.name + "-", dir=output))
    sessions, inputs = [], []
    original = handoff.TerminalSession

    class HeldClaimTerminal(original):
        def __init__(self, command, directory, **kwargs):
            self.owned_directory = directory
            release = directory / "claim-release"
            os.mkfifo(release, 0o600)
            self.release_descriptor = os.open(release, os.O_RDWR | os.O_NONBLOCK)
            self.claim_released = False
            try:
                if premature_ready:
                    helper = directory / "oidc-helper"
                    helper.write_text(
                        helper.read_text().replace(
                            "print('GENERIC LOGIN SPAWNED',file=sys.stderr,flush=True)",
                            "print('GENERIC LOGIN READY',file=sys.stderr,flush=True)\n"
                            "print('GENERIC LOGIN SPAWNED',file=sys.stderr,flush=True)",
                            1,
                        )
                    )
                super().__init__(command, directory, **kwargs)
            except BaseException:
                self.close_claim()
                raise
            sessions.append(self)

        def close_claim(self):
            if self.release_descriptor is not None:
                descriptor = self.release_descriptor
                self.release_descriptor = None
                os.close(descriptor)

        def release_claim(self):
            if not self.claim_released:
                assert self.release_descriptor is not None
                os.write(self.release_descriptor, b"x")
                self.claim_released = True

        def wait_for(self, text, *, timeout=15, **kwargs):
            if text == b"GENERIC LOGIN READY":
                deadline = time.monotonic() + timeout
                super().wait_for(b"GENERIC LOGIN SPAWNED", timeout=timeout, **kwargs)
                entry = self.owned_directory / "claim-entry.json"
                while not entry.exists():
                    assert time.monotonic() < deadline
                    self.read(min(0.1, max(0, deadline - time.monotonic())))
                claim = json.loads(entry.read_text())
                spawned = json.loads((self.owned_directory / "helper-spawned.json").read_text())
                assert spawned["foreground"] == claim["foreground"] == claim["app_group"]
                assert spawned["group"] == claim["helper_group"] != claim["foreground"]
                assert b"GENERIC LOGIN READY" not in self.transcript, (
                    "READY preceded the real foreground claim"
                )
                self.release_claim()
                timeout = max(0, deadline - time.monotonic())
            return super().wait_for(text, timeout=timeout, **kwargs)

        def send(self, data):
            inputs.append(data)
            return super().send(data)

        def __exit__(self, kind, value, trace):
            self.release_claim()
            try:
                return super().__exit__(kind, value, trace)
            finally:
                self.close_claim()
                (evidence / "terminal.ansi").write_bytes(self.transcript)
                (evidence / "receipt.json").write_text(
                    json.dumps(
                        {
                            "premature_ready": premature_ready,
                            "completion": self.completion,
                            "cleanup": self.cleanup,
                            "ctrl_c_inputs": inputs.count(b"\x03"),
                            "helper_sha256": hashlib.sha256(
                                (self.owned_directory / "oidc-helper").read_bytes()
                            ).hexdigest(),
                            "observations": {
                                name: json.loads(path.read_text())
                                if (path := self.owned_directory / name).exists()
                                else None
                                for name in (
                                    "claim-entry.json",
                                    "helper-spawned.json",
                                    "helper-ready.json",
                                )
                            },
                        },
                        indent=2,
                    )
                    + "\n"
                )
                for path in evidence.iterdir():
                    path.chmod(0o600)
                print(f"Credential foreground evidence: {evidence}")

    monkeypatch.setattr(
        handoff,
        "APP",
        handoff.APP.replace("directory=Path.cwd()", CLAIM_GATE + "\ndirectory=Path.cwd()", 1),
    )
    monkeypatch.setattr(handoff, "TerminalSession", HeldClaimTerminal)
    if premature_ready:
        with pytest.raises(AssertionError, match="READY preceded the real foreground claim"):
            handoff.credential_terminal_trial(
                sys.executable, tmp_path, "ctrl_c", name="early-ready"
            )
        assert inputs.count(b"\x03") == 0
    else:
        handoff.credential_terminal_trial(sys.executable, tmp_path, "ctrl_c", name="owned-ready")
        assert inputs.count(b"\x03") == 1
    assert len(sessions) == 1 and sessions[0].cleanup["status"] == "complete"
    assert sessions[0].cleanup["owner_reaped"] and sessions[0].cleanup["group"] == "gone"
    terminal = sessions[0]
    assert terminal.completion is not None
    assert restored_modes(terminal.completion["before"], terminal.completion["after"])
    helper_pid = int((terminal.owned_directory / "helper.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(helper_pid, 0)
    assert handoff.TOKEN.encode() not in terminal.transcript
    assert b'"kind": "ExecCredential"' not in terminal.transcript
    for descriptor in (
        terminal.master,
        terminal.slave,
        terminal.completion_read,
        terminal.acknowledgement_write,
    ):
        with pytest.raises(OSError):
            os.fstat(descriptor)
