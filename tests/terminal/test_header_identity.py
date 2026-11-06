"""Native synthetic identity, evidence access, resize and owned terminal restoration."""

import asyncio
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from kuberich.services.ownership import finish_owned
from tests.support.authorization_ui import authorization_api
from tests.terminal.pty_support import TerminalSession
from tests.ui.test_header_identity import NS, ROLE, ReviewAPI, config

EVIDENCE = Path(__file__).resolve().parents[2] / "artifacts/terminal/header-identity"


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


def right_edge_complete(display):
    return (
        len(display) == 36
        and all(len(line) == 120 for line in display)
        and display[10].startswith(" ┌")
        and display[10].rstrip().endswith("┐")
        and display[11].startswith(" │ERVATION")
        and tuple(line.strip(" │") for line in display[27:32])
        == ("", "core", "ods", "es: example", "URLs: none")
        and display[33].startswith(" └")
        and display[33].rstrip().endswith("┘")
    )


def one_left_complete(display):
    return display[11].startswith(" │SERVATION") and tuple(
        line.strip(" │") for line in display[27:32]
    ) == ("h", "core", "pods", "mes: example", "e URLs: none")


def role_table_complete(display):
    return (
        f"roles({NS})[1] · live" in display[10]
        and display[12].split("│", 1)[-1].split()[:3] == [NS, ROLE, "2"]
        and "Live · 1 roles" in display[35]
    )


def drive(directory, path, api, stopping, output, read_size):
    terminal = None
    frames = {}
    width = 120

    def frame(label, required, marker, *, predicate=lambda display: True):
        deadline = time.monotonic() + 15
        while True:
            display = terminal.screen.display
            text = "\n".join(display)
            if (
                len(terminal.transcript) > marker
                and all(value in text for value in required)
                and complete_header(display, width)
                and predicate(display)
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
            read_size=read_size,
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
            frame("role-object", (), marker, predicate=role_table_complete)
            marker = terminal.send(b"g\r")
            expected_uid = api.objects["rbac.authorization.k8s.io", "roles", NS, ROLE]["metadata"][
                "uid"
            ]
            frame("role-inspector", ("details(", "kind: Role", expected_uid), marker)
            marker = terminal.send(b"L")
            frame("role-links", ("links(", "Explain role and aggregation"), marker)
            marker = terminal.send(b"\r")
            frame("authorization", ("role · namespace", "RBAC role", "Observed evidence"), marker)
            marker = terminal.send(b"G")
            frame("authorization-last-rule", ("Rule 2 · Role/" + ROLE,), marker)
            marker = terminal.send(b"\x1b[F")
            frame("authorization-right-edge", (), marker, predicate=right_edge_complete)
            marker = terminal.send(b"h")
            frame("authorization-one-left", (), marker, predicate=one_left_complete)
            marker = terminal.send(b"o")
            frame("selected-role-object", (), marker, predicate=role_table_complete)
            inspected_from = len(api.reads)
            marker = terminal.send(b"\r")
            frame(
                "selected-role-inspector",
                (
                    "details(",
                    "kind: Role",
                    "apiVersion: rbac.authorization.k8s.io/v1",
                    expected_uid,
                ),
                marker,
            )
            assert any(
                path == f"/apis/rbac.authorization.k8s.io/v1/namespaces/{NS}/roles/{ROLE}"
                for path, _ in api.reads[inspected_from:]
            )
            marker = terminal.send(b"y")
            frame("selected-role-yaml", ("yaml(", "kind: Role", expected_uid), marker)
            marker = terminal.send(b"G")
            frame("selected-role-full-rules", ("verbs:", "- watch", "resources:", "- pods"), marker)
            marker = terminal.send(b"\x1b")
            frame("selected-role-close", (), marker, predicate=role_table_complete)
            marker = terminal.send(b"\x1b")
            frame(
                "authorization-back",
                ("role · namespace", "Observed evidence"),
                marker,
                predicate=one_left_complete,
            )
            marker = terminal.send(b"\x1b[H")
            frame("authorization-left", ("role · namespace", "EVIDENCE"), marker)
            resized("authorization", "role", "EVIDENCE")
            terminal.send(b"\x11")
            terminal.finish()
    finally:
        if terminal is not None:
            payload = {
                "frames": frames,
                "last_screen": terminal.screen.display,
                "cleanup": terminal.cleanup,
                "sizes": terminal.sizes,
                "requests": api.reads,
                "temporary_directory": str(directory),
                "read_size": read_size,
                "evidence_directory": str(output),
            }
            for name, content in (
                ("frames.json", json.dumps(payload, indent=2) + "\n"),
                ("native.ansi", bytes(terminal.transcript)),
            ):
                target = output / name
                if isinstance(content, bytes):
                    target.write_bytes(content)
                else:
                    target.write_text(content)
                target.chmod(0o600)
    assert terminal.cleanup["owner_reaped"] and terminal.cleanup["group"] == "gone"
    assert terminal.cleanup["descriptors_closed"]
    assert any(
        path == f"/apis/rbac.authorization.k8s.io/v1/namespaces/{NS}/roles/{ROLE}"
        for path, _ in api.reads
    )
    assert any(path == f"/api/v1/namespaces/{NS}/pods/example" for path, _ in api.reads)


@pytest.mark.asyncio
@pytest.mark.parametrize("read_size", [65536, 4096], ids=["native", "fragmented"])
async def test_real_native_identity_and_evidence_survive_all_supported_header_layouts(
    tmp_path, read_size
):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=tmp_path.name + "-", dir=EVIDENCE))
    api = ReviewAPI()
    async with authorization_api(api) as url:
        path = config(tmp_path, url)
        before = path.read_bytes()
        stopping = threading.Event()
        worker = asyncio.create_task(
            asyncio.to_thread(drive, tmp_path, path, api, stopping, output, read_size)
        )
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            stopping.set()
            await finish_owned(asyncio.gather(worker, return_exceptions=True))
            raise
        except BaseException as error:
            error.add_note("Retained native evidence: " + str(output))
            raise
        assert path.read_bytes() == before
    assert api.active_watches == 0


def test_far_right_oracle_rejects_a_mixed_repaint_before_the_first_horizontal_key():
    display = [" " * 120 for _ in range(36)]
    display[10] = " ┌" + "─" * 116 + "┐ "
    display[11] = " │ERVATION".ljust(118) + "│ "
    for row, text in zip(
        range(27, 32), ("", "core", "ods", "es: example", "URLs: none"), strict=True
    ):
        display[row] = (" │" + text).ljust(118) + "│ "
    display[33] = " └" + "─" * 116 + "┘ "
    assert right_edge_complete(display)
    partial = display.copy()
    partial[27] = " │ Source rolebindings".ljust(118) + "│ "
    partial[31] = " │ Source serviceaccounts".ljust(118) + "│ "
    assert "ERVATION" in "\n".join(partial)
    assert not right_edge_complete(partial)
    role = [" " * 120 for _ in range(36)]
    role[10] = f"roles({NS})[1] · live"
    role[12] = f" │ {NS} {ROLE} 2 2 0"
    role[35] = " Read-only · Insecure transport · Live · 1 roles"
    assert role_table_complete(role)
    loading = role.copy()
    loading[10] = f"roles({NS})[0] · loading"
    loading[12] = " │"
    loading[21] = f" │ observed UID: roles-{NS}-{ROLE}"
    assert "roles(" in "\n".join(loading) and ROLE in "\n".join(loading)
    assert not role_table_complete(loading)
