"""Actual source/installed CLI history against one exclusively owned HTTP API."""

import hashlib
import json
import shutil
import sys
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
                "tests/quality/test_history_terminal.py",
                "pyproject.toml",
                "uv.lock",
            )
        ),
    )
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def return_to_parent(terminal, title, selected, *, absent=("Metric history ·",)):
    """Wait for the actual parent, never a shared name in a partial history paint."""
    deadline = time.monotonic() + 15
    marker = terminal.send(b"\x1b")
    for expected in (title, selected):
        remaining = deadline - time.monotonic()
        assert remaining > 0, "History parent frame exceeded its original 15-second deadline."
        terminal.wait_for_screen(expected, since=marker, absent=absent, timeout=remaining)
    assert time.monotonic() < deadline, "History parent frame exceeded its original deadline."
    display = "\n".join(terminal.screen.display)
    assert title in display and selected in display and all(text not in display for text in absent)
    return {
        "title": title,
        "selected": selected,
        "screen": terminal.screen.display.copy(),
        "timeout_seconds": 15,
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
    parent_witnesses = []
    source = _source_hashes()
    terminal = None
    stage = "terminal-start"
    normal_finish_observed = False
    passed = False
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(kubeconfig), "--readonly", "-n", NAMESPACE],
            directory,
            size=size,
            environment=environment,
        ) as terminal:
            stage = "initial-pod-frame"
            terminal.wait_for_screen(f"pods({NAMESPACE})[1]")
            terminal.wait_for_screen(POD_NAME)

            def open_history(kind):
                nonlocal stage
                stage = "open-history:" + kind
                marker = terminal.send(b"M")
                terminal.wait_for_screen("Metric history ·", since=marker)
                terminal.wait_for_screen("partial", since=marker)
                scopes.append(kind)

            open_history("pod")
            for key, label in zip(
                b"1234567", ("15m", "30m", "1h", "3h", "6h", "12h", "24h"), strict=True
            ):
                stage = "range:" + label
                marker = terminal.send(bytes((key,)))
                terminal.wait_for_screen("partial · " + label + " ·", since=marker)
            terminal.resize(100, 30)
            stage = "network"
            marker = terminal.send(b"n")
            terminal.wait_for_screen("network", since=marker)
            stage = "ascii-mode"
            marker = terminal.send(b"a")
            terminal.wait_for_screen("ASCII", since=marker)
            stage = "filesystem"
            marker = terminal.send(b"f")
            terminal.wait_for_screen("filesystem", since=marker)
            stage = "filesystem-device"
            marker = terminal.send(b"]")
            terminal.wait_for_screen("synthetic-b", since=marker)
            stage = "detect-backends"
            marker = terminal.send(b"d")
            terminal.wait_for_screen("Detected 2 candidates", since=marker)
            stage = "select-backend"
            marker = terminal.send(b"b")
            terminal.wait_for_screen("partial", since=marker)
            stage = "resize-short"
            terminal.resize(40, 12)
            terminal.wait_for_screen("partial")
            terminal.resize(100, 30)
            stage = "back-to-pods-after-resize"
            parent_witnesses.append(return_to_parent(terminal, f"pods({NAMESPACE})[1]", POD_NAME))
            stage = "open-containers"
            marker = terminal.send(b"\r")
            container_title = f"containers({NAMESPACE}/{POD_NAME})[4]"
            terminal.wait_for_screen(container_title, since=marker)
            for ordinal, name in enumerate(("app", "init", "sidecar", "debug")):
                if ordinal:
                    terminal.send(b"\x1b[B")
                open_history("container:" + name)
                stage = "container-network:" + name
                marker = terminal.send(b"n")
                terminal.wait_for_screen("network", since=marker)
                stage = "back-to-container:" + name
                parent_witnesses.append(return_to_parent(terminal, container_title, name))
            stage = "back-to-pods-from-containers"
            parent_witnesses.append(
                return_to_parent(
                    terminal,
                    f"pods({NAMESPACE})[1]",
                    POD_NAME,
                    absent=("Metric history ·", "containers("),
                )
            )
            for route, item, kind, title in (
                (b"nodes", "history-node", "node", "nodes(cluster)[1]"),
                (b"deployments", "history-workload", "workload", f"deployments({NAMESPACE})[1]"),
                (b"pulse", "Pulse", "cluster", f"pulse({NAMESPACE})"),
            ):
                stage = "route:" + kind
                marker = terminal.send(b":" + route + b"\r")
                terminal.wait_for_screen(title, since=marker)
                terminal.wait_for_screen(item, since=marker)
                open_history(kind)
                stage = "back-to-parent:" + kind
                parent_witnesses.append(return_to_parent(terminal, title, item))
            stage = "quit-and-terminal-restoration"
            terminal.send(b"\x11")
            terminal.finish()
            normal_finish_observed = True
            terminal.save_evidence(evidence)
            (output / (evidence + ".ansi")).chmod(0o600)
        stage = "audit-source-and-request-controls"
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
        container_query_counts = {
            name: sum(f'container="{name}"' in query["query"] for query in queries)
            for name in ("app", "init", "sidecar", "debug")
        }
        assert all(container_query_counts.values()), container_query_counts
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
            "container_query_counts": container_query_counts,
            "parent_witnesses": parent_witnesses,
            "ranges": sorted(durations),
            "native_availability": "Explicit synthetic HTTP vectors only",
            "source": source,
        }
        (output / (evidence + "-history.json")).write_text(json.dumps(receipt, indent=2) + "\n")
        passed = True
    finally:
        original_failure = sys.exception()
        try:
            if terminal is not None:
                # Keep named raw evidence even when a wait fails before normal finish.
                raw_path = output / (evidence + ".ansi")
                raw_path.write_bytes(terminal.transcript)
                raw_path.chmod(0o600)
                if not passed:
                    failure = {
                        "result": "failed",
                        "failed_stage": stage,
                        "normal_finish_observed": normal_finish_observed,
                        "screen": terminal.screen.display,
                        "terminal_completion": terminal.completion,
                        "cleanup": terminal.cleanup,
                        "parent_witnesses": parent_witnesses,
                        "source": source,
                    }
                    (output / (evidence + ".json")).write_text(json.dumps(failure, indent=2) + "\n")
        except BaseException as archive_error:
            if original_failure is None:
                raise
            original_failure.add_note(
                "History terminal archive failed: " + type(archive_error).__name__
            )
        finally:
            server.stopping.set()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            assert not thread.is_alive()
