"""Actual source/installed CLI history against one exclusively owned HTTP API."""

import hashlib
import json
import shutil
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from tests.support.container_inspection_terminal import _AUDIT, _audit_controls
from tests.support.history_explorer import NAMESPACE, POD_NAME, HistoryApi
from tests.support.terminal_api import config
from tests.terminal.pty_support import ROOT, TerminalSession


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-history-pty"
        parsed = urlsplit(self.path)
        parameters = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if "watch" in parameters:
            self.server.api.requests.append((parsed.path, parameters))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.server.stopping.wait(30)
            return
        status, payload = self.server.api.response(parsed.path, parameters)
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def do_POST(self):
        self.server.api.requests.append(("REFUSED POST " + self.path, {}))
        self.send_error(405)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.stopping = threading.Event()
        self.api = HistoryApi()


def _source_hashes():
    paths = (
        *ROOT.glob("src/kuberich/**/*.py"),
        *(
            ROOT / name
            for name in (
                "tests/support/history_terminal.py",
                "tests/support/history_explorer.py",
                "tests/support/history.py",
                "tests/support/container_inspection_terminal.py",
                "tests/terminal/test_history.py",
                "pyproject.toml",
                "uv.lock",
            )
        ),
    )
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def terminal_history(command, directory, *, evidence, size=(100, 30), wheel_sha256=None):
    """Exercise real entry scopes/ranges, keyboard, resize, exact modes and reaping."""
    directory.mkdir(parents=True, exist_ok=True)
    output = ROOT / "artifacts" / "terminal"
    output.mkdir(parents=True, exist_ok=True)
    existing = tuple(
        path
        for suffix in (".ansi", ".json", "-history.json")
        if (path := output / (evidence + suffix)).exists()
    )
    if existing:
        archive = output / "preserved" / (evidence + "-" + str(time.time_ns()))
        archive.mkdir(parents=True)
        for path in existing:
            shutil.copy2(path, archive / path.name)
    server = _Server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kubeconfig = config(
        directory / "history-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-history-pty"},
    )
    kubeconfig.chmod(0o600)
    before = kubeconfig.read_bytes()
    (directory / "preferences.yaml").write_text(
        "schema_version: 1\nobservability:\n  history:\n    namespace: team\n    service: metrics\n"
    )
    hooks = directory / "history-hooks"
    hooks.mkdir()
    (hooks / "sitecustomize.py").write_text(_AUDIT)
    audit = directory / "history-audit.jsonl"
    environment = {
        "PYTHONPATH": str(hooks),
        "KUBERICH_INSPECTION_AUDIT": str(audit),
        "KUBERICH_INSPECTION_PORT": str(server.server_port),
    }
    scopes = []
    source = _source_hashes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(kubeconfig), "--readonly", "-n", NAMESPACE],
            directory,
            size=size,
            environment=environment,
        ) as terminal:
            terminal.wait_for_screen(POD_NAME)

            def open_history(kind):
                marker = terminal.send(b"M")
                terminal.wait_for_screen("Metric history ·", since=marker)
                terminal.wait_for_screen("partial", since=marker)
                scopes.append(kind)

            open_history("pod")
            for key, label in zip(
                b"1234567", ("15m", "30m", "1h", "3h", "6h", "12h", "24h"), strict=True
            ):
                marker = terminal.send(bytes((key,)))
                terminal.wait_for_screen("partial · " + label + " ·", since=marker)
            terminal.resize(100, 30)
            marker = terminal.send(b"n")
            terminal.wait_for_screen("network", since=marker)
            marker = terminal.send(b"a")
            terminal.wait_for_screen("ASCII", since=marker)
            marker = terminal.send(b"f")
            terminal.wait_for_screen("filesystem", since=marker)
            marker = terminal.send(b"]")
            terminal.wait_for_screen("synthetic-b", since=marker)
            marker = terminal.send(b"d")
            terminal.wait_for_screen("Detected 2 candidates", since=marker)
            marker = terminal.send(b"b")
            terminal.wait_for_screen("partial", since=marker)
            terminal.resize(40, 12)
            terminal.wait_for_screen("partial")
            terminal.resize(100, 30)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(POD_NAME, since=marker, absent=("Metric history ·",))
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("containers(", since=marker)
            for ordinal, name in enumerate(("app", "init", "sidecar", "debug")):
                if ordinal:
                    terminal.send(b"\x1b[B")
                open_history("container:" + name)
                marker = terminal.send(b"n")
                terminal.wait_for_screen("network", since=marker)
                marker = terminal.send(b"\x1b")
                terminal.wait_for_screen("containers(", since=marker, absent=("Metric history ·",))
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(POD_NAME, since=marker, absent=("containers(",))
            for route, item, kind in (
                (b"nodes", "history-node", "node"),
                (b"deployments", "history-workload", "workload"),
                (b"pulse", "Pulse", "cluster"),
            ):
                marker = terminal.send(b":" + route + b"\r")
                terminal.wait_for_screen(item, since=marker)
                open_history(kind)
                marker = terminal.send(b"\x1b")
                terminal.wait_for_screen(item, since=marker, absent=("Metric history ·",))
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            (output / (evidence + ".ansi")).chmod(0o600)
        assert kubeconfig.read_bytes() == before
        events = [json.loads(line) for line in audit.read_text().splitlines()]
        assert events[0] == {"event": "loaded"}
        assert any(event["event"] == "socket.connect" for event in events)
        assert all(event.get("accepted", True) for event in events)
        assert all(event["event"] != "subprocess.Popen" for event in events)
        controls = _audit_controls(command, directory, environment)
        assert not any(path.startswith("REFUSED") for path, _ in server.api.requests)
        queries = [
            parameters for path, parameters in server.api.requests if path.endswith("query_range")
        ]
        durations = {int(float(query["end"]) - float(query["start"])) for query in queries}
        assert durations >= {900, 1800, 3600, 10800, 21600, 43200, 86400}
        assert any('container="debug"' in query["query"] for query in queries)
        assert any("node_cpu_seconds_total" in query["query"] for query in queries)
        assert any("kube_replicaset_owner" in query["query"] for query in queries)
        assert _source_hashes() == source, "History terminal source changed during the trial."
        receipt = {
            "wheel_sha256": wheel_sha256,
            "kubeconfig_unchanged": True,
            "requests": server.api.requests,
            "audit": events,
            "audit_controls": controls,
            "entry_command": command,
            "scopes": scopes,
            "ranges": sorted(durations),
            "native_availability": "Explicit synthetic HTTP vectors only",
            "source": source,
        }
        (output / (evidence + "-history.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
