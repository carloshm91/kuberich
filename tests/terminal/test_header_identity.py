"""Native synthetic identity, evidence access, resize and owned terminal restoration."""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from kuberich.services.ownership import finish_owned
from tests.support.authorization_ui import authorization_api
from tests.terminal.pty_support import TerminalSession
from tests.ui.test_header_identity import NS, ROLE, ReviewAPI, config

OUTPUT = Path("artifacts/issue75/terminal-review/native-verified")


def complete_header(display, width):
    if not display[0].startswith(" Context: synthetic-context-"):
        return False
    if width == 40:
        return display[1].startswith(" Namespace: synthetic-") and display[2].startswith(
            " State: Connected"
        )
    return (
        display[1].startswith(" Cluster: synthetic-cluster-")
        and display[2].startswith(" User: synthetic-user-")
        and display[3].startswith(" Namespace: synthetic-")
        and display[4].startswith(" State: Connected")
        and (
            "workspace" in display[4] and "Kubernetes" in display[2]
            if width == 120
            else "KubeRich" in display[0] and "Kubernetes" not in display[2]
        )
    )


def drive(directory, path, api, stopping):
    terminal = None
    frames = {}
    width = 120

    def frame(label, required, marker, *, previous_heading=None):
        deadline = time.monotonic() + 15
        while True:
            display = terminal.screen.display
            text = "\n".join(display)
            if (
                len(terminal.transcript) > marker
                and all(value in text for value in required)
                and complete_header(display, width)
                and (previous_heading is None or display[11] != previous_heading)
            ):
                frames[label] = display.copy()
                return
            assert not stopping.is_set()
            assert terminal.completion is None and terminal.process.poll() is None
            assert time.monotonic() < deadline, (label, display)
            terminal.read(0.05)

    def resized(label, title, column):
        nonlocal width
        for width, height in ((100, 30), (40, 12), (120, 36)):
            marker = terminal.resize(width, height)
            frame(label + "-" + str(width), (title, column), marker)

    try:
        with TerminalSession(
            [
                sys.executable,
                "-m",
                "kuberich",
                "--kubeconfig",
                str(path),
                "--readonly",
                "-n",
                NS,
            ],
            directory,
            size=(120, 36),
        ) as terminal:
            frame("pods", ("pods(", "example", "live"), -1)
            marker = terminal.send(b":pulse\r")
            frame("pulse", ("pulse(", "Node usage CPU"), marker)
            resized("pulse", "pulse(", "SUMMARY")
            marker = terminal.send(b":pods\r")
            frame("pods-back", ("pods(", "example", "live"), marker)
            marker = terminal.send(b":xray\r")
            frame("relationships", ("xray", "Pod/example"), marker)
            marker = terminal.send(b"\x1b[F")
            frame("relationship-identity", ("expected UID:", "observed UID:"), marker)
            marker = terminal.send(b"o")
            frame("relationship-open", ("pods(", "example", "live"), marker)
            marker = terminal.send(b"\x1b")
            frame("relationship-back", ("xray", "expected UID:", "observed UID:"), marker)
            marker = terminal.send(b"\x1b[H")
            frame("relationship-left", ("xray", "RESOURCE"), marker)
            resized("relationships", "xray", "RESOURCE")
            marker = terminal.send(b":roles " + NS.encode() + b"\r")
            frame("role-object", ("roles(", ROLE), marker)
            marker = terminal.send(b"g\r")
            expected_uid = api.objects["rbac.authorization.k8s.io", "roles", NS, ROLE]["metadata"][
                "uid"
            ]
            frame("role-inspector", ("details(", "kind: Role", expected_uid), marker)
            marker = terminal.send(b"L")
            frame("role-links", ("links(", "Explain role and aggregation"), marker)
            marker = terminal.send(b"\r")
            frame("authorization", ("role · namespace", "RBAC role", "Observed evidence"), marker)
            marker = terminal.send(b"G\x1b[F")
            frame("authorization-right-edge", ("ERVATION",), marker)
            for step in range(20):
                heading = terminal.screen.display[11]
                marker = terminal.send(b"h")
                frame(
                    "authorization-scroll-" + str(step),
                    ("role · namespace",),
                    marker,
                    previous_heading=heading,
                )
            frame("authorization-rules", ("verbs: watch", "resources: pods"), marker)
            marker = terminal.send(b"\x1b[H")
            frame("authorization-left", ("role · namespace", "EVIDENCE"), marker)
            resized("authorization", "role", "EVIDENCE")
            terminal.send(b"\x11")
            terminal.finish()
    finally:
        if terminal is not None:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            payload = {
                "frames": frames,
                "last_screen": terminal.screen.display,
                "cleanup": terminal.cleanup,
                "sizes": terminal.sizes,
                "requests": api.reads,
            }
            for name, content in (
                ("frames.json", json.dumps(payload, indent=2) + "\n"),
                ("native.ansi", bytes(terminal.transcript)),
            ):
                output = OUTPUT / name
                if isinstance(content, bytes):
                    output.write_bytes(content)
                else:
                    output.write_text(content)
                output.chmod(0o600)
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
    assert terminal.cleanup["descriptors_closed"]
    assert any(
        path == f"/apis/rbac.authorization.k8s.io/v1/namespaces/{NS}/roles/{ROLE}"
        for path, _ in api.reads
    )
    assert any(path == f"/api/v1/namespaces/{NS}/pods/example" for path, _ in api.reads)


@pytest.mark.asyncio
async def test_real_native_identity_and_evidence_survive_all_supported_header_layouts(tmp_path):
    api = ReviewAPI()
    async with authorization_api(api) as url:
        path = config(tmp_path, url)
        before = path.read_bytes()
        stopping = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(drive, tmp_path, path, api, stopping))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            stopping.set()
            await finish_owned(asyncio.gather(worker, return_exceptions=True))
            raise
        assert path.read_bytes() == before
    assert api.active_watches == 0
