"""Actual CLI node-shell trials on an owned loopback API and child PTY."""

import copy
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession

IMAGE = "owned/diagnostic@sha256:" + "a" * 64
CHILD = r"""
import json,os,signal,stat,sys,termios,tty
from pathlib import Path
root=Path(__file__).parent.parent
args=sys.argv[1:]
credential=Path(args[0].split('=',1)[1])
assert stat.S_IMODE(credential.stat().st_mode)==0o600
config=json.loads(credential.read_text())
assert config['current-context']=='kuberich-test-pty'
assert args[1:7]==['--context=kuberich-test-pty','--namespace=team','exec','--stdin','--tty','--container=diagnostic']
assert args[7].startswith('kuberich-node-shell-') and args[8:]==['--','/bin/sh']
with (root/'node-exec-arguments.jsonl').open('a') as output:
 output.write(json.dumps(args)+'\n')
(root/'node-child-pid').write_text(str(os.getpid()))
(root/'node-caller-pid').write_text(str(os.getppid()))
assert os.tcgetpgrp(0)==os.getpgrp()
mode=termios.tcgetattr(0)
assert mode[3]&termios.ICANON and mode[3]&termios.ECHO
tty.setraw(0)
def resized(*_):
 size=os.get_terminal_size(0)
 os.write(1,f'NODE SIZE {size.columns} {size.lines}\r\n'.encode())
signal.signal(signal.SIGWINCH,resized)
os.write(1,'NODE REMOTE READY café界\r\n'.encode())
scenario=(root/'node-scenario').read_text()
if scenario=='shell_missing': sys.exit(127)
if scenario=='connection_loss': sys.exit(1)
data=b''
while True:
 chunk=os.read(0,4096)
 data+=chunk
 (root/'node-input').write_bytes(data)
 if b'\x03' in chunk: os.write(1,b'NODE REMOTE INTERRUPT\r\n')
 if b'exit\r' in data: break
"""


class NodeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, value=None, *, status=200):
        payload = json.dumps(value or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def node(self):
        return {
            "apiVersion": "v1",
            "kind": "Node",
            "metadata": {
                "name": "owned-pty-node",
                "uid": "owned-node-uid",
                "resourceVersion": "node-version",
            },
            "status": {
                "nodeInfo": {"operatingSystem": "linux", "kubeletVersion": "v1.36.4"},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }

    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if "watch" in query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.server.stopping.wait(30)
            return
        roots = legacy_roots()
        roots["/api/v1"]["resources"].append(descriptor("nodes", kind="Node", namespaced=False))
        if parsed.path in roots:
            self.respond(roots[parsed.path])
        elif parsed.path == "/api/v1/namespaces":
            self.respond(
                {
                    "metadata": {"resourceVersion": "namespace-list"},
                    "items": [
                        {
                            "metadata": {
                                "name": "team",
                                "uid": "owned-namespace-uid",
                                "resourceVersion": "namespace-version",
                            }
                        }
                    ],
                }
            )
        elif parsed.path == "/api/v1/namespaces/team":
            self.respond(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": "team", "uid": "owned-namespace-uid"},
                }
            )
        elif parsed.path == "/api/v1/nodes":
            self.respond({**collection(self.node()), "kind": "NodeList"})
        elif parsed.path == "/api/v1/nodes/owned-pty-node":
            self.respond(self.node())
        elif "/pods/" in parsed.path:
            with self.server.lock:
                pod = copy.deepcopy(self.server.pod)
            if pod is None or parsed.path.rsplit("/", 1)[1] != pod["metadata"]["name"]:
                self.respond(status=404)
            else:
                pod["spec"]["nodeName"] = "owned-pty-node"
                pod["status"] = {
                    "phase": "Running",
                    "containerStatuses": [
                        {"name": "diagnostic", "ready": True, "state": {"running": {}}}
                    ],
                }
                self.respond(pod)
        else:
            self.respond(collection())

    def do_POST(self):
        parsed = urlsplit(self.path)
        assert parsed.path == "/api/v1/namespaces/team/pods"
        query = parse_qs(parsed.query)
        assert query["fieldValidation"] == ["Strict"]
        pod = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if query.get("dryRun") == ["All"]:
            pod["metadata"]["uid"] = "dry-run-uid-never-owned"
        else:
            pod["metadata"]["uid"] = "owned-diagnostic-uid"
            pod["metadata"]["resourceVersion"] = "created-version"
            with self.server.lock:
                self.server.pod = copy.deepcopy(pod)
                self.server.posts.append(copy.deepcopy(pod))
        self.respond(pod, status=201)

    def do_DELETE(self):
        parsed = urlsplit(self.path)
        assert parse_qs(parsed.query) == {"fieldValidation": ["Strict"]}
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["preconditions"] == {"uid": "owned-diagnostic-uid"}
        assert body["gracePeriodSeconds"] == 5
        with self.server.lock:
            pod = self.server.pod
            assert pod is not None
            assert parsed.path == "/api/v1/namespaces/team/pods/" + pod["metadata"]["name"]
            self.server.deletes.append(body)
            self.server.pod = None
        self.respond({"kind": "Status", "status": "Success"})


class NodeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.pod = None
        self.posts, self.deletes = [], []
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        super().__init__(("127.0.0.1", 0), NodeHandler)


def terminal_node_shell(command, directory, scenario, *, evidence):
    directory = directory.resolve()
    child_home, child_state = directory / "node-child-home", directory / "node-state"
    for root in (child_home, child_state):
        root.mkdir(mode=0o700, exist_ok=True)
        root.chmod(0o700)
    server = NodeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kubeconfig = config(
        directory / "node-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = kubeconfig.read_bytes()
    (directory / "preferences.yaml").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "node_shell": {"enabled": True, "image": IMAGE, "namespace": "team"},
            }
        )
    )
    (directory / "node-scenario").write_text(scenario)
    binary = directory / "bin"
    binary.mkdir(exist_ok=True)
    if scenario != "missing":
        executable = binary / "kubectl"
        executable.write_text(f"#!{sys.executable}\n" + CHILD)
        executable.chmod(0o700)
    invocation = [
        *command,
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        "kuberich-test-pty",
        "--command",
        "nodes",
    ]
    try:
        with TerminalSession(
            invocation,
            directory,
            environment={
                "PATH": str(binary),
                "HOME": str(child_home),
                "XDG_STATE_HOME": str(child_state),
            },
            size=(120, 36),
        ) as terminal:
            terminal.wait_for_screen("owned-pty-node")
            attempts = 2 if scenario == "repeat" else 1
            for _ in range(attempts):
                terminal.send(b":node-shell\r")
                terminal.wait_for_screen("Review the exact profile.")
                assert server.pod is None
                terminal.send(b"\x1b[Z\r")
                if scenario == "missing":
                    terminal.wait_for_screen("Install kubectl")
                elif scenario in {"shell_missing", "connection_loss"}:
                    terminal.wait_for_screen("Node shell: closed")
                else:
                    terminal.wait_for_screen("NODE REMOTE READY café界")
                    terminal.wait_for_screen("Node: owned-pty-node")
                    if scenario not in {"shell_missing", "connection_loss"}:
                        terminal.resize(80, 25)
                        terminal.wait_for_screen("NODE SIZE 78 19")
                        if scenario == "ctrl_c":
                            terminal.send(b"\x03")
                            terminal.wait_for_screen("NODE REMOTE INTERRUPT")
                            terminal.send(b"exit\r")
                        elif scenario == "close":
                            terminal.send(b"\x1d")
                        elif scenario == "quit":
                            terminal.send(b"\x11")
                            terminal.finish()
                            break
                        elif scenario == "sigterm":
                            os.kill(
                                int((directory / "node-caller-pid").read_text()), signal.SIGTERM
                            )
                            terminal.finish(expected=143)
                            break
                        else:
                            terminal.send(b"exit\r")
                    terminal.wait_for_screen("Node shell: closed")
                deadline = time.monotonic() + 5
                while server.pod is not None:
                    terminal.read(0.01)
                    assert time.monotonic() < deadline, "Diagnostic Pod cleanup did not finish"
                terminal.resize(120, 36)
                terminal.send(b"\x1b")
                terminal.wait_for_screen("Sort NAME", absent=("Node shell ·",))
            if scenario not in {"quit", "sigterm"}:
                terminal.send(b"\x11")
                terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert kubeconfig.read_bytes() == before
        assert server.pod is None and len(server.posts) == len(server.deletes) == attempts
        for root in (child_home, child_state):
            assert not list(root.rglob("*.json")), f"Node-shell journal remained under {root}"
        captured = directory / "node-exec-arguments.jsonl"
        if scenario == "missing":
            assert not captured.exists()
        else:
            records = [json.loads(line) for line in captured.read_text().splitlines()]
            assert len(records) == attempts
            assert all(not Path(args[0].split("=", 1)[1]).exists() for args in records)
            with pytest.raises(ProcessLookupError):
                os.kill(int((directory / "node-child-pid").read_text()), 0)
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
