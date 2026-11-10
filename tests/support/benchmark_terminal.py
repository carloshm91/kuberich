"""Actual Vegeta traffic through an owned proxy, fake API and real terminal."""

import json
import os
import shutil
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from tests.contract.test_benchmark_service import POD, SERVICE
from tests.support.standard_terminal import Handler
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession

PROXY = r"""
import json,os,select,socket,sys,threading,uuid
from pathlib import Path
args=sys.argv[1:]
assert args[args.index('port-forward')+3]=='pod/backend'
assert '--address=127.0.0.1' in args
assert args[-1]=='0:8080'
listener=socket.socket()
listener.bind(('127.0.0.1',0))
listener.listen(8)
record=Path('benchmark-forward.json')
pending=record.with_name('.'+record.name+'.'+str(uuid.uuid4()))
with os.fdopen(os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
    json.dump({'pid':os.getpid(),'port':listener.getsockname()[1],'config':args[0].split('=',1)[1]},stream)
pending.replace(record)
print(f'Forwarding from 127.0.0.1:{listener.getsockname()[1]} -> 8080',flush=True)
def proxy(peer):
    with peer, socket.create_connection(('127.0.0.1',int(os.environ['OWNED_BENCHMARK_PORT'])),timeout=3) as upstream:
        sockets=(peer,upstream)
        while True:
            for source in select.select(sockets,[],[],3)[0]:
                data=source.recv(65536)
                if not data:return
                (upstream if source is peer else peer).sendall(data)
while True:
    peer,_=listener.accept()
    threading.Thread(target=proxy,args=(peer,),daemon=True).start()
"""


class BenchmarkApi(Handler):
    def do_GET(self):
        path = urlsplit(self.path)
        if "watch=true" in path.query:
            return super().do_GET()
        pod = {"apiVersion": "v1", "kind": "Pod", **deepcopy(POD)}
        service = deepcopy(SERVICE)
        service["metadata"]["name"] = "owned-one"
        service["metadata"]["resourceVersion"] = "owned-service-v1"
        responses = {
            "/api/v1/namespaces/team/services": {
                "apiVersion": "v1",
                "kind": "ServiceList",
                "metadata": {"resourceVersion": "list-v1"},
                "items": [service],
            },
            "/api/v1/namespaces/team/services/owned-one": service,
            "/api/v1/namespaces/team/pods": {
                "apiVersion": "v1",
                "kind": "PodList",
                "metadata": {},
                "items": [pod],
            },
            "/api/v1/namespaces/team/pods/backend": pod,
        }
        if path.path not in responses:
            return super().do_GET()
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        body = json.dumps(responses[path.path]).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)


class BenchmarkHttp(BaseHTTPRequestHandler):
    def do_GET(self):
        with self.server.counter_lock:
            self.server.requests += 1
        body = b"owned benchmark response"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextmanager
def benchmark_fixture(directory: Path, vegeta: Path, *, duration=10, kubectl: Path | None = None):
    api = ThreadingHTTPServer(("127.0.0.1", 0), BenchmarkApi)
    api.stopping = threading.Event()
    http = ThreadingHTTPServer(("127.0.0.1", 0), BenchmarkHttp)
    http.requests, http.counter_lock = 0, threading.Lock()
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (api, http)]
    for thread in threads:
        thread.start()
    path = config(
        directory / "fixture-config",
        f"http://127.0.0.1:{api.server_port}",
        {"token": "synthetic-pty"},
    )
    data = yaml.safe_load(path.read_text())
    data["current-context"] = data["contexts"][0]["name"] = "kuberich-test-one"
    data["contexts"][0]["context"]["namespace"] = "team"
    path.write_text(yaml.safe_dump(data))
    binary = directory / "kubectl"
    if kubectl is None:
        binary.write_text(f"#!{sys.executable}\n" + PROXY)
    else:
        shutil.copyfile(kubectl, binary)
    binary.chmod(0o700)
    preferences = {
        "schema_version": 1,
        "benchmarks": {
            "schema_version": 1,
            "defaults": {
                "executable": str(vegeta),
                "load": {"rate": 2, "duration_seconds": duration},
            },
        },
    }
    (directory / "preferences.yaml").write_text(yaml.safe_dump(preferences))
    environment = {
        "PATH": str(directory) + os.pathsep + os.environ.get("PATH", ""),
        "OWNED_BENCHMARK_PORT": str(http.server_port),
        "XDG_STATE_HOME": str(directory / "state"),
    }
    try:
        yield path, environment, http
    finally:
        api.stopping.set()
        for server, thread in zip((api, http), threads, strict=True):
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            assert not thread.is_alive()


def assert_forward_gone(directory):
    record = json.loads((directory / "benchmark-forward.json").read_text())
    try:
        os.kill(record["pid"], 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Benchmark abandoned its owned forwarding child")
    with socket.socket() as peer:
        assert peer.connect_ex(("127.0.0.1", record["port"])) != 0
    assert not Path(record["config"]).exists()


def terminal_benchmark(
    command,
    directory,
    evidence,
    *,
    vegeta: Path,
    stop="escape",
    kubectl: Path | None = None,
    prepare_command: Callable[[list[str], dict[str, str]], list[str]] | None = None,
):
    from scripts.benchmark_tools import verify_benchmark_binary

    executable_sha256 = verify_benchmark_binary(vegeta)
    with benchmark_fixture(
        directory, vegeta, duration=2 if stop == "complete" else 10, kubectl=kubectl
    ) as (
        path,
        environment,
        http,
    ):
        before = path.read_bytes()
        argv = [
            *command,
            "--kubeconfig",
            str(path),
            "--context",
            "kuberich-test-one",
            "--command",
            "svc team",
            "--benchmark-directory",
            str(directory / "saved-results"),
        ]
        if prepare_command is not None:
            argv = prepare_command(argv, environment)
        with TerminalSession(
            argv,
            directory,
            environment=environment,
        ) as terminal:
            terminal.wait_for_screen("services(team)[1]")
            terminal.send(b":benchmark\r")
            terminal.wait_for_screen("Choose a backend, edit request/load")
            terminal.send(b"\x1b[17~")
            terminal.wait_for_screen("Review ready.")
            terminal.wait_for_screen("one captured backend")
            assert http.requests == 0
            terminal.send(b"\x1b[18~")
            terminal.wait_for_screen("State: running")
            deadline = time.monotonic() + 5
            while not http.requests:
                terminal.read()
                assert time.monotonic() < deadline
            if stop == "ctrlc":
                terminal.send(b"\x03\x03")
                terminal.finish()
            elif stop == "sigterm":
                os.killpg(terminal.process.pid, signal.SIGTERM)
                os.killpg(terminal.process.pid, signal.SIGTERM)
                terminal.finish(expected=143)
            else:
                if stop == "complete":
                    terminal.wait_for_screen("State: complete")
                    terminal.wait_for_screen("Estimated latency percentiles")
                elif stop == "cancel":
                    terminal.send(b"\r")
                    terminal.wait_for_screen("State: cancelled")
                else:
                    terminal.resize(40, 12)
                    terminal.wait_for_screen("Cancel")
                marker = terminal.send(b"\x1b")
                terminal.wait_for_screen(
                    "services(team)[1]", since=marker, absent=("HTTP benchmark",)
                )
                assert_forward_gone(directory)
                terminal.send(b"\x11")
                terminal.finish()
            count = http.requests
            assert_forward_gone(directory)
            time.sleep(0.7)
            assert http.requests == count
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
        assert not tuple(directory.glob("benchmark-*/*"))
        terminal_benchmark_browser(
            command,
            directory,
            evidence + "-restart",
            environment=environment,
            completion="complete" if stop == "complete" else "cancelled",
            prepare_command=prepare_command,
        )
        assert http.requests == count
        return {
            "stop": stop,
            "http_requests": count,
            "completion": "complete" if stop == "complete" else "cancelled",
            "vegeta_sha256": executable_sha256,
        }


def terminal_benchmark_browser(
    command,
    directory,
    evidence,
    *,
    environment=None,
    completion="cancelled",
    prepare_command: Callable[[list[str], dict[str, str]], list[str]] | None = None,
):
    """A fresh CLI browses existing state without usable Kubernetes configuration."""
    argv = [
        *command,
        "--command",
        "benchmarks",
        "--readonly",
        "--benchmark-directory",
        str(directory / "saved-results"),
    ]
    if prepare_command is not None:
        argv = prepare_command(argv, environment or {})
    with TerminalSession(argv, directory, environment=environment) as terminal:
        terminal.wait_for_screen("Saved HTTP benchmarks")
        terminal.wait_for_screen(completion.replace("_", " "))
        terminal.send(b"\r")
        terminal.wait_for_screen("Result: " + completion.replace("_", " "))
        terminal.send(b"\x1b")
        terminal.wait_for_screen("Saved HTTP benchmarks")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(evidence)


def terminal_benchmark_missing_tool(
    command,
    directory,
    evidence,
    *,
    kubectl: Path | None = None,
    prepare_command: Callable[[list[str], dict[str, str]], list[str]] | None = None,
):
    assert not (directory / "benchmark-forward.json").exists()
    assert not (directory / "missing-vegeta").exists()
    with benchmark_fixture(directory, directory / "missing-vegeta", kubectl=kubectl) as (
        path,
        environment,
        http,
    ):
        argv = [
            *command,
            "--kubeconfig",
            str(path),
            "--context",
            "kuberich-test-one",
            "--command",
            "svc team",
            "--benchmark-directory",
            str(directory / "saved-results"),
        ]
        if prepare_command is not None:
            argv = prepare_command(argv, environment)
        with TerminalSession(
            argv,
            directory,
            environment=environment,
        ) as terminal:
            terminal.wait_for_screen("services(team)[1]")
            terminal.send(b":benchmark\r")
            terminal.wait_for_screen("Choose a backend, edit request/load")
            terminal.send(b"\x1b[17~")
            terminal.wait_for_screen("Review ready.")
            terminal.send(b"\x1b[18~")
            terminal.wait_for_screen("State: tool failed")
            terminal.wait_for_screen("No trustworthy metrics")
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
        assert not (directory / "benchmark-forward.json").exists() and http.requests == 0
        terminal_benchmark_browser(
            command,
            directory,
            evidence + "-restart",
            environment=environment,
            completion="tool_failed",
            prepare_command=prepare_command,
        )
        return {"http_requests": 0, "completion": "tool_failed", "forward_started": False}
