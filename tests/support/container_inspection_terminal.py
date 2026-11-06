"""Real source/installed CLI inspector trials against an exclusively owned HTTP API."""

import base64
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from tests.support.container_inspection import (
    CONFIG_PATH,
    NAMESPACE,
    POD_PATH,
    PRIVATE_VALUE,
    InspectionApi,
)
from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.terminal_api import config
from tests.terminal.pty_support import ROOT, TerminalSession

VALUE = "owned-pty-container-value-你好"
_AUDIT = '''"""Restrict the actual CLI to this trial's loopback API and record child launches."""
import json
import os
import sys

_record = os.environ.get("KUBERICH_INSPECTION_AUDIT")
_port = int(os.environ.get("KUBERICH_INSPECTION_PORT", "0"))
if _record and sys.argv[0] != "-c":
    def _write(value):
        descriptor = os.open(_record, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (json.dumps(value) + "\\n").encode())
        finally:
            os.close(descriptor)
    _write({"event": "loaded"})
    def _audit(event, arguments):
        if event == "socket.connect":
            address = arguments[1]
            accepted = isinstance(address, tuple) and address[:2] == ("127.0.0.1", _port)
            _write({"event": event, "accepted": accepted})
            if not accepted:
                raise RuntimeError("Owned container trial refused external network.")
        elif event == "subprocess.Popen":
            _write({"event": event})
            raise RuntimeError("Owned container trial refused a child process.")
    sys.addaudithook(_audit)
    _negative = os.environ.get("KUBERICH_INSPECTION_NEGATIVE")
    if _negative:
        try:
            if _negative == "network":
                import socket
                socket.socket().connect(("127.0.0.1", _port + 1))
            elif _negative == "subprocess":
                import subprocess
                subprocess.run([sys.executable, "-c", "raise SystemExit(99)"], check=True)
            else:
                os._exit(98)
        except RuntimeError:
            _write({"event": "control-denied", "control": _negative})
            os._exit(0)
        os._exit(97)
'''


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        self.server.requests.append(("GET", parsed.path, query))
        assert self.headers.get("Authorization") == "Bearer synthetic-inspector-pty"
        if "watch" in query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.server.stopping.wait(30)
            return
        roots = legacy_roots()
        roots["/api/v1"]["resources"].extend(
            (descriptor("configmaps", kind="ConfigMap"), descriptor("secrets", kind="Secret"))
        )
        if parsed.path in roots:
            value = roots[parsed.path]
        elif parsed.path == "/api/v1/namespaces":
            value = {
                "metadata": {"resourceVersion": "namespace-list"},
                "items": [
                    {
                        "metadata": {
                            "name": NAMESPACE,
                            "uid": "namespace-uid",
                            "resourceVersion": "namespace-version",
                        }
                    }
                ],
            }
        elif parsed.path.endswith("/pods"):
            value = collection(self.server.records[POD_PATH])
        elif parsed.path in self.server.records:
            value = self.server.records[parsed.path]
        else:
            self.send_error(404, "Owned endpoint unavailable")
            return
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def do_POST(self):
        self.server.requests.append(("POST", self.path, {}))
        self.send_error(405)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.stopping = threading.Event()
        self.requests = []
        self.records = InspectionApi().records
        self.records[CONFIG_PATH]["data"]["CONFIG"] = VALUE
        pod = self.records[POD_PATH]
        app = pod["spec"]["containers"][0]
        for field in ("initContainers", "ephemeralContainers"):
            for item in pod["spec"][field]:
                item["envFrom"] = copy.deepcopy(app["envFrom"])
                item["env"] = [{"name": "LITERAL", "value": "owned-pty-literal-marker"}]


def _audit_controls(command, directory, environment):
    controls = {}
    for mode in ("network", "subprocess"):
        audit = directory / ("inspection-audit-negative-" + mode + ".jsonl")
        # Run the same console/module entry point, ending in the startup hook before CLI work.
        controlled = {
            **os.environ,
            **environment,
            "KUBECONFIG": str(directory / "never-use-a-real-cluster"),
            "KUBERICH_INSPECTION_AUDIT": str(audit),
            "KUBERICH_INSPECTION_NEGATIVE": mode,
        }
        result = subprocess.run(
            [*command, "--version"],
            cwd=directory,
            env=controlled,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0 and not result.stdout and not result.stderr
        events = [json.loads(line) for line in audit.read_text().splitlines()]
        assert events[0] == {"event": "loaded"}
        assert events[-1] == {"event": "control-denied", "control": mode}
        if mode == "network":
            assert {"event": "socket.connect", "accepted": False} in events
        else:
            assert {"event": "subprocess.Popen"} in events
        controls[mode] = events
    return controls


def terminal_container_inspection(
    command, directory, *, evidence, size=(100, 30), wheel_sha256=None
):
    """Navigate all families, disclose separately, resize, close and prove restoration."""
    directory.mkdir(parents=True, exist_ok=True)
    output = ROOT / "artifacts" / "terminal"
    output.mkdir(parents=True, exist_ok=True)
    existing = tuple(
        path
        for suffix in (".ansi", ".json", "-inspection.json", "-hidden.txt")
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
    path = config(
        directory / "container-inspection-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-inspector-pty"},
    )
    before = path.read_bytes()
    hooks = directory / "inspection-hooks"
    hooks.mkdir()
    (hooks / "sitecustomize.py").write_text(_AUDIT)
    audit = directory / "inspection-audit.jsonl"
    environment = {
        "PYTHONPATH": str(hooks),
        "KUBERICH_INSPECTION_AUDIT": str(audit),
        "KUBERICH_INSPECTION_PORT": str(server.server_port),
    }
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--readonly", "-n", NAMESPACE],
            directory,
            size=size,
            environment=environment,
        ) as terminal:
            terminal.wait_for_screen("inspection-pod")
            terminal.send(b"\r")
            terminal.wait_for_screen("containers(")
            hidden_frames = []
            for ordinal, _name in enumerate(("app", "init", "sidecar", "debug")):
                if ordinal:
                    terminal.send(b"\x1b[B")
                marker = terminal.send(b"e")
                terminal.wait_for_screen("Values hidden", since=marker)
                hidden = "\n".join(terminal.screen.display)
                assert VALUE not in hidden and PRIVATE_VALUE not in hidden
                hidden_frames.append(hidden)
                marker = terminal.send(b"r")
                terminal.wait_for_screen("Selected value revealed", since=marker)
                terminal.wait_for(VALUE.encode(), since=marker)
                marker = terminal.send(b"r")
                terminal.wait_for_screen("Values hidden", since=marker, absent=(VALUE,))
                if ordinal == 0:
                    marker = terminal.send(b"\x19")
                    terminal.wait_for(b"Selected value copied", since=marker)
                    copied = re.search(rb"\x1b\]52;c;([^\x07]+)\x07", terminal.transcript[marker:])
                    assert copied is not None
                    assert base64.b64decode(copied[1], validate=True).decode() == VALUE
                    marker = terminal.send(b"i")
                    terminal.wait_for_screen("image[6]", since=marker)
                    terminal.resize(100, 30)
                    terminal.wait_for_screen("imagePullPolicy", since=marker)
                    marker = terminal.send(b"s")
                    terminal.wait_for_screen("inspection-config", since=marker)
                    terminal.resize(40, 12)
                    marker = terminal.send(b"e")
                    terminal.wait_for_screen("NAME", since=marker)
                    terminal.resize(100, 30)
                marker = terminal.send(b"\x1b")
                terminal.wait_for_screen(
                    "containers(", since=marker, absent=("Values hidden", VALUE)
                )
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(
                "pods(inspection-team)[1]", since=marker, absent=("containers(",)
            )
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            raw = ROOT / "artifacts" / "terminal" / (evidence + ".ansi")
            raw.chmod(0o600)
            (output / (evidence + "-hidden.txt")).write_text("\n\n".join(hidden_frames))
        assert path.read_bytes() == before
        events = [json.loads(line) for line in audit.read_text().splitlines()]
        assert events[0] == {"event": "loaded"}
        assert any(event["event"] == "socket.connect" for event in events)
        assert all(event.get("accepted", True) for event in events)
        assert all(event["event"] != "subprocess.Popen" for event in events)
        controls = _audit_controls(command, directory, environment)
        allowed = {
            "/api",
            "/apis",
            "/api/v1",
            "/api/v1/namespaces",
            "/api/v1/namespaces/" + NAMESPACE + "/pods",
            *server.records,
        }
        assert all(
            method == "GET" and endpoint in allowed for method, endpoint, _ in server.requests
        )
        receipt = {
            "wheel_sha256": wheel_sha256,
            "kubeconfig_unchanged": True,
            "requests": server.requests,
            "audit": events,
            "audit_controls": controls,
            "entry_command": command,
            "families": ["App", "Init", "Sidecar", "Ephemeral"],
            "source": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "src/kuberich/ui/containers.py",
                    "src/kuberich/ui/container_inspection.py",
                    "src/kuberich/services/container_inspection.py",
                    "src/kuberich/domain/container_inspection.py",
                    "src/kuberich/domain/container_environment.py",
                    "src/kuberich/ui/resource_operations.py",
                    "src/kuberich/ui/workspace_presenter.py",
                    "src/kuberich/ui/app.py",
                    "tests/support/container_inspection_terminal.py",
                    "tests/terminal/test_container_inspection.py",
                    "pyproject.toml",
                    "uv.lock",
                )
            },
        }
        (output / (evidence + "-inspection.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
