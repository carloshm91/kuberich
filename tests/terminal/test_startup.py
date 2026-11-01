"""Actual native frames precede SDK, helper and network work on startup routes."""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession

ROOT = Path(__file__).resolve().parents[2]


def wait_for_paint_observation(report, terminal):
    deadline = time.monotonic() + 5
    while not report.with_suffix(".painted.json").is_file():
        assert terminal.process.poll() is None, "Application exited before its refresh callback."
        assert time.monotonic() < deadline, "Actual first-frame observation did not complete."
        terminal.read(0.01)


@pytest.mark.parametrize(
    "initial,expected",
    [
        ("", "resources"),
        ("ctx", "contexts"),
        ("ns", "namespaces"),
        ("deploy", "standard-resources"),
        ("retry", "resources"),
        ("login", "resources"),
        ("themes", "resources"),
        ("about", "resources"),
        ("views", "resources"),
        ("help", "resources"),
        ("status", "resources"),
        ("ctx owned", "resources"),
        ("ns default", "resources"),
        ("crontabs.example.test", "resources"),
    ],
)
def test_initial_route_paints_its_actual_mounted_table_before_any_connection_work(
    tmp_path, initial, expected
):
    path = config(tmp_path / "owned-config", "http://127.0.0.1:9", {"token": "synthetic-pty"})
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    report = tmp_path / "startup.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        str(preferences),
        "--kubeconfig",
        str(path),
        "--initial",
        initial,
        "--mode",
        "paint",
    ]
    with TerminalSession(command, tmp_path, size=(120, 36)) as terminal:
        terminal.finish()
        terminal.save_evidence("startup-initial-route")
    observed = json.loads(report.read_text())
    assert observed["painted"] and expected in observed["shown_tables"]
    table = observed["table_frames"][expected]
    assert table["mounted"] and table["columns"] > 0
    x, y, width, height = table["region"]
    assert x >= 0 and y >= 0 and width > 0 and height > 0
    assert x + width <= 120 and y + height <= 36
    assert observed["events"] == [{"kind": "paint", "painted": True}]
    assert observed["sdk_before_paint"] == [] and observed["sdk_models_at_exit"] == 0
    assert observed["client_closed"] and observed["violations"] == []


@pytest.mark.parametrize(
    "initial,helper",
    [
        ("", False),
        ("ctx", False),
        ("retry", False),
        ("login", False),
        ("themes", False),
        ("about", False),
        ("views", False),
        ("", True),
    ],
)
def test_actual_first_refresh_precedes_connection_work_and_retains_initial_view(
    tmp_path, initial, helper
):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    user = {"token": "synthetic-pty"}
    if helper:
        executable = tmp_path / "owned-credential.py"
        executable.write_text(
            "import json\nfrom pathlib import Path\n"
            "Path('owned-helper-ran').write_text('executed')\n"
            "print(json.dumps({'apiVersion':'client.authentication.k8s.io/v1','kind':'ExecCredential','status':{'token':'synthetic-pty'}}))\n"
        )
        user = {
            "exec": {
                "apiVersion": "client.authentication.k8s.io/v1",
                "command": sys.executable,
                "args": [str(executable)],
                "interactiveMode": "Never",
            }
        }
    path = config(
        tmp_path / "owned-config",
        f"http://127.0.0.1:{server.server_port}",
        user,
    )
    report = tmp_path / "startup.json"
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    command = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        str(preferences),
        "--kubeconfig",
        str(path),
        "--initial",
        initial,
        "--mode",
        "observe",
    ]
    command.extend(("--owned-api-port", str(server.server_port)))
    try:
        with TerminalSession(command, tmp_path, size=(120, 36)) as terminal:
            wait_for_paint_observation(report, terminal)
            if initial == "login":
                terminal.wait_for(b"no exec helper")
            elif initial not in {"themes", "about", "views"}:
                terminal.wait_for(b"Connected")
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(
                "startup-" + (initial or "default") + ("-helper" if helper else "")
            )
        observed = json.loads(report.read_text())
        assert observed["painted"] and observed["viewport"] == [120, 36]
        assert observed["sdk_before_paint"] == [] and observed["violations"] == []
        assert observed["client_closed"]
        assert observed["events"][0] == {"kind": "paint", "painted": True}
        if initial == "ctx":
            assert "contexts" in observed["shown_tables"]
            assert observed["context_rows"] == 1
        if initial in {"themes", "about", "views"}:
            assert not server.namespace_requested.is_set()
            assert observed["sdk_models_at_exit"] == 0
        elif initial == "login":
            assert not server.namespace_requested.is_set()
            assert observed["last_state"] == "AUTH_ERROR"
            assert all(event["painted"] for event in observed["events"])
        else:
            assert server.namespace_requested.is_set()
            assert any(event["kind"] == "sdk-import" for event in observed["events"])
            assert all(event["painted"] for event in observed["events"])
        if helper:
            assert (tmp_path / "owned-helper-ran").read_text() == "executed"
            assert any(event["kind"] == "helper" for event in observed["events"])
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "initial,mode", [("", "observe"), ("about", "observe"), ("", "paint"), ("", "cancel")]
)
def test_opted_in_owned_release_request_waits_for_the_actual_frame(tmp_path, initial, mode):
    requests = []

    class ReleaseHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            assert self.headers.get("Authorization") is None
            body = json.dumps(
                {
                    "tag_name": "v9.9.9",
                    "draft": False,
                    "prerelease": False,
                    "html_url": "https://github.com/carloshm91/kuberich/releases/tag/v9.9.9",
                    "name": "Owned synthetic release",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text("schema_version: 1\nappearance:\n  check_updates: true\n")
    kubeconfig = tmp_path / "empty-kubeconfig"
    kubeconfig.write_text("apiVersion: v1\nkind: Config\ncontexts: []\nclusters: []\nusers: []\n")
    report = tmp_path / "startup.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        str(preferences),
        "--kubeconfig",
        str(kubeconfig),
        "--mode",
        mode,
        "--initial",
        initial,
        "--updates-endpoint",
        f"http://127.0.0.1:{server.server_port}/latest",
        "--owned-api-port",
        str(server.server_port),
    ]
    try:
        with TerminalSession(command, tmp_path, size=(120, 36)) as terminal:
            if mode == "observe":
                wait_for_paint_observation(report, terminal)
                terminal.wait_for(b"9.9.9")
                terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("startup-owned-release-" + (initial or "default"))
        observed = json.loads(report.read_text())
        assert observed["violations"] == [] and observed["sdk_before_paint"] == []
        assert observed["sdk_models_at_exit"] == 0 and observed["client_closed"]
        assert observed["events"][0] == {"kind": "paint", "painted": True}
        assert all(event["painted"] for event in observed["events"])
        if mode == "observe":
            assert any(event["kind"] == "network" for event in observed["events"])
            assert requests == ["/latest"]
            assert report.with_suffix(".update-cache.json").is_file()
        else:
            assert observed["events"] == [{"kind": "paint", "painted": True}]
            assert requests == [] and not report.with_suffix(".update-cache.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize("initial,mode", [("quit", "observe"), ("", "cancel")])
def test_quit_or_shutdown_before_refresh_cannot_strand_or_start_a_connection(
    tmp_path, initial, mode
):
    path = config(tmp_path / "owned-config", "http://127.0.0.1:9", {"token": "synthetic-pty"})
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    report = tmp_path / "startup.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        str(preferences),
        "--kubeconfig",
        str(path),
        "--initial",
        initial,
        "--mode",
        mode,
    ]
    with TerminalSession(command, tmp_path) as terminal:
        terminal.finish()
        terminal.save_evidence("startup-" + (initial or mode))
    observed = json.loads(report.read_text())
    assert observed["client_closed"] and observed["violations"] == []
    assert observed["sdk_models_at_exit"] == 0
    assert all(event["kind"] == "paint" for event in observed["events"])


def test_public_context_replacement_before_refresh_uses_the_latest_owned_context(tmp_path):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        tmp_path / "owned-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    contents = yaml.safe_load(path.read_text())
    contents["contexts"].append(
        {"name": "owned-replacement", "context": {"cluster": "owned", "user": "owned"}}
    )
    path.write_text(yaml.safe_dump(contents))
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    report = tmp_path / "startup.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        str(preferences),
        "--kubeconfig",
        str(path),
        "--replace-context",
        "owned-replacement",
        "--mode",
        "observe",
    ]
    command.extend(("--owned-api-port", str(server.server_port)))
    try:
        with TerminalSession(command, tmp_path, size=(120, 36)) as terminal:
            terminal.wait_for_screen("Context: owned-replacement")
            terminal.wait_for_screen("State: Connected")
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("startup-context-replacement")
        observed = json.loads(report.read_text())
        assert observed["violations"] == [] and observed["client_closed"]
        assert observed["last_context"] == "owned-replacement"
        assert observed["sdk_before_paint"] == []
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_measurement_probe_records_ordered_public_lifecycle_phases_without_a_speed_claim(tmp_path):
    report = tmp_path / "startup.json"
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    kubeconfig = tmp_path / "empty-kubeconfig.yaml"
    kubeconfig.write_text("apiVersion: v1\nkind: Config\ncontexts: []\nclusters: []\nusers: []\n")
    command = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        str(preferences),
        "--kubeconfig",
        str(kubeconfig),
        "--measure",
    ]
    with TerminalSession(command, tmp_path, size=(120, 36)) as terminal:
        terminal.finish()
    observed = json.loads(report.read_text())
    phases = [
        observed[name]
        for name in (
            "imports_finished_ns",
            "constructor_started_ns",
            "constructor_finished_ns",
            "mount_started_ns",
            "mount_returned_ns",
            "first_paint_ns",
        )
    ]
    assert all(type(moment) is int and moment > 0 for moment in phases)
    assert phases == sorted(phases) and len(set(phases)) == len(phases)
    assert observed["painted"] and observed["shown_tables"] == ["resources"]
    assert observed["viewport"] == [120, 36] and observed["client_closed"]
    assert observed["sdk_before_paint"] == [] and observed["violations"] == []
    assert observed["events"] == [{"kind": "paint", "painted": True}]
