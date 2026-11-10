"""Owned loopback debug API and audited helper for source and installed CLI PTYs."""

import copy
import json
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

from scripts.owned_kind import SHELL_IMAGE
from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.tables import server_table
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession

CHILD = r"""
import json,os,stat,sys,time,tty,urllib.request
from pathlib import Path
root=Path(__file__).parent
configuration=Path(sys.argv[1].split('=',1)[1])
assert stat.S_IMODE(configuration.stat().st_mode)==0o600
record={'pid':os.getpid(),'caller_pid':os.getppid(),'argv':sys.argv[1:]}
with (root/'audit.jsonl').open('a') as output:output.write(json.dumps(record)+'\n')
name=next(value.split('=',1)[1] for value in sys.argv if value.startswith('--container='))
def completed(code):
 request=urllib.request.Request(os.environ['DEBUG_CONTROL_URL']+'/owned-helper/'+name,
  data=json.dumps({'exitCode':code}).encode(),headers={'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(request,timeout=2) as response:assert response.status==200
tty.setraw(0)
os.write(1,b'OWNED DEBUG ATTACH READY\r\n')
if os.environ['DEBUG_CASE']=='disconnect':time.sleep(.5);sys.exit(1)
data=b''
while True:
 chunk=os.read(0,4096)
 if not chunk:sys.exit(0)
 data=(data+chunk)[-4096:]
 if b'\x03' in data:completed(130);sys.exit(0)
 if b'\x10\x11' in data:sys.exit(0)
 if b'exit 7' in data:completed(7);sys.exit(0)
 if b'owned-input' in data:os.write(1,b'OWNED DEBUG INPUT OUTPUT\r\n');data=b''
"""


def debug_pod():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "debug-workload",
            "namespace": "team",
            "uid": "owned-debug-pod-uid",
            "resourceVersion": "opaque/debug-v1",
        },
        "spec": {"containers": [{"name": "app", "image": "synthetic-workload"}]},
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": "app",
                    "containerID": "containerd://owned-app-instance",
                    "restartCount": 0,
                    "state": {"running": {"startedAt": "2026-11-10T00:00:00Z"}},
                }
            ],
        },
    }


def debug_roots():
    values = legacy_roots()
    values["/api/v1"]["resources"] = [
        descriptor("pods", kind="Pod"),
        {
            "name": "pods/ephemeralcontainers",
            "kind": "Pod",
            "namespaced": True,
            "verbs": ["get", "patch"],
        },
        {"name": "pods/attach", "kind": "Pod", "namespaced": True, "verbs": ["get", "create"]},
    ]
    return values


class DebugHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, payload=None, *, status=200):
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        self.server.requests.append(("GET", parsed.path, query))
        if "watch" in query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.server.stopping.wait(30)
            return
        values = debug_roots()
        if parsed.path in values:
            self.respond(values[parsed.path])
        elif parsed.path.endswith("/namespaces"):
            self.respond(collection({"metadata": {"name": "team", "uid": "team-uid"}}))
        elif parsed.path.endswith("/pods"):
            pod = copy.deepcopy(self.server.pod)
            self.respond(
                server_table(pod)
                if "as=Table" in self.headers.get("Accept", "")
                else collection(pod)
            )
        elif parsed.path.endswith("/pods/debug-workload"):
            self.respond(copy.deepcopy(self.server.pod))
        else:
            self.respond(collection())

    def do_PATCH(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("PATCH", parsed.path, query, body))
        assert parsed.path == "/api/v1/namespaces/team/pods/debug-workload/ephemeralcontainers"
        assert self.headers["Content-Type"] == "application/json-patch+json"
        assert query.get("fieldValidation") == ["Strict"]
        if self.server.denied:
            self.respond({"kind": "Status", "code": 403}, status=403)
            return
        pod = self.server.pod
        assert body[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": pod["metadata"]["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": pod["metadata"]["resourceVersion"],
            },
        ]
        assert len(body) == 3 and body[2]["op"] == "add"
        entry = body[2]["value"]
        if isinstance(entry, list):
            assert len(entry) == 1 and not pod["spec"].get("ephemeralContainers")
            entry = entry[0]
        value = copy.deepcopy(pod)
        value["spec"].setdefault("ephemeralContainers", []).append(entry)
        if query.get("dryRun") != ["All"]:
            value["metadata"]["resourceVersion"] += "x"
            value["status"].setdefault("ephemeralContainerStatuses", []).append(
                {
                    "name": entry["name"],
                    "containerID": "containerd://owned-debug-" + entry["name"],
                    "restartCount": 0,
                    "state": {"waiting": {"reason": "ErrImagePull"}}
                    if self.server.startup_failure
                    else {"running": {"startedAt": "2026-11-10T00:01:00Z"}},
                }
            )
            self.server.pod = value
            self.server.appended.set()
            if self.server.drop_response:
                self.close_connection = True
                self.connection.close()
                return
        self.respond(value)

    def do_POST(self):
        path = urlsplit(self.path).path
        assert path.startswith("/owned-helper/")
        name = path.rsplit("/", 1)[1]
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert set(body) == {"exitCode"} and body["exitCode"] in {7, 130}
        state = next(
            item
            for item in self.server.pod["status"]["ephemeralContainerStatuses"]
            if item["name"] == name
        )
        state["state"] = {
            "terminated": {"exitCode": body["exitCode"], "finishedAt": "2026-11-10T00:02:00Z"}
        }
        self.server.pod["metadata"]["resourceVersion"] += "s"
        self.respond({"accepted": True})


class DebugServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), DebugHandler)
        self.pod = debug_pod()
        self.requests = []
        self.stopping = threading.Event()
        self.appended = threading.Event()
        self.denied = False
        self.drop_response = False
        self.startup_failure = False


@contextmanager
def debug_api():
    server = DebugServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


def fill_debug_review(terminal, name):
    """Edit the visible supported form through actual terminal keys."""
    deadline = time.monotonic() + 15
    while True:
        enabled, focused = (
            debug_button_cell(terminal, "Review"),
            debug_button_cell(terminal, "Cancel"),
        )
        if enabled is not None and focused is not None and enabled != focused:
            break
        terminal.read(0.1)
        assert terminal.completion is None and time.monotonic() < deadline
    terminal.debug_button_styles = {
        "enabled": enabled,
        "focused": focused,
    }
    terminal.send(b"\x1b[Z" * 8 + SHELL_IMAGE.encode())
    terminal.send(b"\t\x01\x0b" + name.encode() + b'\t\x01\x0b["/bin/sh"]\tapp\t\t\t\t\r')


def click_terminal_text(terminal, text, *, contains=None):
    """Send an ordinary terminal mouse click at one currently visible label."""
    rows = [
        (index, row)
        for index, row in enumerate(terminal.screen.display)
        if text in row and (contains is None or contains in row)
    ]
    assert len(rows) == 1, rows
    row, value = rows[0]
    column = value.index(text) + max(1, len(text) // 2)
    terminal.send(f"\x1b[<0;{column + 1};{row + 1}M\x1b[<0;{column + 1};{row + 1}m".encode())
    terminal.read(0.1)


def debug_button_position(terminal, label):
    siblings = (
        ("Review", "Add permanently")
        if label in {"Review", "Add permanently"}
        else ("Attach", "Cancel")
    )
    rows = [
        (index, row)
        for index, row in enumerate(terminal.screen.display)
        if all(value in row for value in siblings)
    ]
    if not rows:
        return None
    assert len(rows) == 1, rows
    row, value = rows[0]
    return value.index(label) + len(label) // 2, row


def debug_button_cell(terminal, label):
    position = debug_button_position(terminal, label)
    if position is None:
        return None
    column, row = position
    cell = terminal.screen.buffer[row][column]
    return cell.fg, cell.bg, cell.bold, cell.reverse


def activate_debug_attach(terminal):
    """Click once after enabled/non-active paint; focus before releasing if needed."""
    styles = terminal.debug_button_styles
    deadline = time.monotonic() + 15
    while debug_button_cell(terminal, "Attach") not in styles.values():
        terminal.read(0.1)
        assert terminal.completion is None and time.monotonic() < deadline
    position = debug_button_position(terminal, "Attach")
    assert position is not None
    column, row = position
    terminal.send(f"\x1b[<0;{column + 1};{row + 1}M".encode())
    while debug_button_cell(terminal, "Attach") != styles["focused"]:
        terminal.read(0.1)
        assert terminal.completion is None and time.monotonic() < deadline
    terminal.send(f"\x1b[<0;{column + 1};{row + 1}m".encode())


def wait_debug_row(terminal, name, state):
    deadline = time.monotonic() + 15
    while not any(name in row and state in row for row in terminal.screen.display):
        terminal.read(0.1)
        assert terminal.completion is None and time.monotonic() < deadline


def terminal_real_ephemeral_debug(
    command, directory, kubeconfig, context, namespace, kubectl, *, evidence
):
    """Review, append and attach using the actual verified kubectl and owned real API."""
    directory.mkdir(mode=0o700)
    tools = directory / "tools"
    tools.mkdir(mode=0o700)
    binary = tools / "kubectl"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json,os,stat,sys\n"
        "from pathlib import Path\n"
        "configuration=Path(sys.argv[1].split('=',1)[1])\n"
        "assert stat.S_IMODE(configuration.stat().st_mode)==0o600\n"
        "record={'pid':os.getpid(),'caller_pid':os.getppid(),'argv':sys.argv[1:]}\n"
        "with (Path(__file__).parent/'audit.jsonl').open('a') as output:output.write(json.dumps(record)+'\\n')\n"
        f"os.execv({str(kubectl)!r},[{str(kubectl)!r},*sys.argv[1:]])\n"
    )
    binary.chmod(0o700)
    original = kubeconfig.read_bytes()
    invocation = [
        *command,
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        context,
        "--namespace",
        namespace,
        "--write",
    ]
    environment = {**os.environ, "PATH": str(tools), "KUBECONFIG": str(directory / "never-ambient")}
    with TerminalSession(
        invocation, directory, environment=environment, size=(120, 36)
    ) as terminal:
        terminal.wait_for_screen("workload")
        terminal.send(b":debug\r")
        terminal.wait_for_screen("Ephemeral debugging")
        terminal.wait_for_screen("Observation: current")
        fill_debug_review(terminal, "debug-real-cli")
        terminal.wait_for_screen("Server dry-run admitted")
        assert not (tools / "audit.jsonl").exists()
        terminal.send(b"\x1b[Z\r")
        terminal.wait_for_screen("Append/startup result: Succeeded")
        assert not (tools / "audit.jsonl").exists()
        # Select the newly added row explicitly; existing sessions remain in the table.
        wait_debug_row(terminal, "debug-real-cli", "running")
        click_terminal_text(terminal, "debug-real-cli", contains="running")
        activate_debug_attach(terminal)
        terminal.wait_for_screen("Ephemeral debug attach")
        deadline = time.monotonic() + 20
        next_probe = 0.0
        while "OWNED-REAL-CLI" not in "\n".join(terminal.screen.display):
            if time.monotonic() >= next_probe:
                terminal.send(b"printf '%s%s\\n' 'OWNED-' 'REAL-CLI'\r")
                next_probe = time.monotonic() + 0.25
            terminal.read(0.05)
            assert terminal.completion is None and time.monotonic() < deadline
        terminal.resize(90, 28)
        terminal.send(b"exit 7\r")
        terminal.wait_for_screen("Ephemeral debugging")
        wait_debug_row(terminal, "debug-real-cli", "terminated")
        terminal.send(b"\x1b")
        terminal.wait_for_screen(f"pods({namespace})", absent=("Ephemeral debugging",))
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
        restoration = terminal.completion
    records = [json.loads(line) for line in (tools / "audit.jsonl").read_text().splitlines()]
    assert len(records) == 1 and kubeconfig.read_bytes() == original
    record = records[0]
    assert record["argv"][1:4] == [f"--context={context}", f"--namespace={namespace}", "attach"]
    assert "--container=debug-real-cli" in record["argv"]
    delegated = Path(record["argv"][0].split("=", 1)[1])
    assert not delegated.exists() and not delegated.parent.exists()
    try:
        os.kill(record["pid"], 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Real kubectl attach survived application teardown.")
    return {
        "terminal_restored": restoration["before"] == restoration["after"],
        "application_exit": restoration["exit"],
        "real_kubectl_process_reaped": True,
        "private_session_deleted": True,
        "review_add_attach_return_observed": True,
    }


def terminal_ephemeral_debug(command, directory, scenario, *, evidence):
    """Drive public CLI keys; assert effects, remote state and exact host restoration."""
    directory = directory.resolve()
    with debug_api() as api:
        api.denied = scenario == "denied"
        api.drop_response = scenario == "uncertain"
        api.startup_failure = scenario == "startup"
        endpoint = f"http://127.0.0.1:{api.server_port}"
        kubeconfig = config(
            directory / "debug-kubeconfig", endpoint, {"token": "synthetic-debug-token"}
        )
        document = yaml.safe_load(kubeconfig.read_text())
        document["contexts"].append(
            {"name": "kuberich-debug-other", "context": {"cluster": "owned", "user": "owned"}}
        )
        kubeconfig.write_text(yaml.safe_dump(document))
        original = kubeconfig.read_bytes()
        tools = directory / "tools"
        tools.mkdir()
        if scenario != "missing":
            binary = tools / "kubectl"
            binary.write_text(f"#!{sys.executable}\n" + CHILD)
            binary.chmod(0o700)
        environment = {
            **os.environ,
            "PATH": str(tools),
            "DEBUG_CASE": scenario,
            "DEBUG_CONTROL_URL": endpoint,
        }
        invocation = [
            *command,
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "kuberich-test-pty",
            "--namespace",
            "team",
        ]
        invocation.append("--readonly" if scenario == "read-only" else "--write")
        audits = []
        with TerminalSession(
            invocation, directory, environment=environment, size=(120, 36)
        ) as terminal:
            terminal.wait_for_screen("debug-workload")
            terminal.send(b":debug\r")
            terminal.wait_for_screen("Ephemeral debugging")
            terminal.wait_for_screen("Observation: current")
            assert not api.appended.is_set()
            if scenario == "read-only":
                terminal.wait_for_screen("Read-only inspection")
                terminal.send(b"\r")
                terminal.wait_for_screen("pods(team)[1]", absent=("Ephemeral debugging",))
                terminal.send(b"\x11")
                terminal.finish()
            else:
                # Initial Cancel focus; disabled Add/Attach are skipped.
                fill_debug_review(terminal, "debug-pty")
                if scenario == "denied":
                    terminal.wait_for_screen("Review unavailable")
                    assert not api.appended.is_set()
                    terminal.send(b"\x1b\x11")
                    terminal.finish()
                else:
                    terminal.wait_for_screen("Server dry-run admitted")
                    writes = [item for item in api.requests if item[0] == "PATCH"]
                    assert len(writes) == 1 and writes[0][2].get("dryRun") == ["All"]
                    assert not api.appended.is_set()
                    if scenario == "cancel":
                        terminal.send(b"\r")
                        terminal.wait_for_screen("pods(team)[1]", absent=("Ephemeral debugging",))
                        assert not api.appended.is_set()
                        terminal.send(b"\x11")
                        terminal.finish()
                    else:
                        # Review restores default Cancel; previous enabled button is Add.
                        terminal.send(b"\x1b[Z\r")
                        terminal.wait_for_screen("Append/startup result:")
                        assert api.appended.is_set()
                        assert len(api.pod["spec"]["ephemeralContainers"]) == 1
                        assert not (tools / "audit.jsonl").exists()
                        if scenario in {"startup", "uncertain"}:
                            terminal.wait_for_screen(
                                "Partial batch" if scenario == "startup" else "uncertain"
                            )
                            terminal.send(b"\x1b\x11")
                            terminal.finish()
                        else:
                            terminal.send(b"\x1b[Z\r")
                            if scenario == "missing":
                                terminal.wait_for_screen("kubectl is unavailable")
                            else:
                                terminal.wait_for_screen("OWNED DEBUG ATTACH READY")
                                terminal.send(b"owned-input\r")
                                if scenario != "disconnect":
                                    terminal.wait_for_screen("OWNED DEBUG INPUT OUTPUT")
                                audits = [
                                    json.loads(line)
                                    for line in (tools / "audit.jsonl").read_text().splitlines()
                                ]
                                if scenario == "completion":
                                    terminal.send(b"exit 7\r")
                                elif scenario == "interrupt":
                                    terminal.send(b"\x03")
                                elif scenario in {"detach", "repeat"}:
                                    terminal.send(b"\x10\x11")
                                elif scenario == "terminate":
                                    os.kill(audits[-1]["caller_pid"], signal.SIGTERM)
                                elif scenario == "quit":
                                    terminal.send(b"\x11")
                                else:
                                    terminal.send(b"\x1d")
                            if scenario not in {"terminate", "quit"}:
                                terminal.wait_for_screen("Ephemeral debugging")
                                if scenario == "repeat":
                                    terminal.wait_for_screen(
                                        "Local closure does not establish remote"
                                    )
                                    activate_debug_attach(terminal)
                                    terminal.wait_for_screen("OWNED DEBUG ATTACH READY")
                                    terminal.send(b"\x1d")
                                    terminal.wait_for_screen("Ephemeral debugging")
                                    audits = [
                                        json.loads(line)
                                        for line in (tools / "audit.jsonl").read_text().splitlines()
                                    ]
                                    assert len(audits) == 2
                                if scenario in {"completion", "interrupt"}:
                                    terminal.wait_for_screen("terminated")
                                terminal.resize(52, 18)
                                terminal.send(b"\x1b")
                                terminal.wait_for_screen(
                                    "pods(team)[1]", absent=("Ephemeral debugging",)
                                )
                                if scenario == "context":
                                    terminal.resize(120, 36)
                                    terminal.send(b":ctx kuberich-debug-other\r")
                                    terminal.wait_for_screen("kuberich-debug-other")
                                terminal.send(b"\x11")
                            terminal.finish(expected=143 if scenario == "terminate" else 0)
            terminal.save_evidence(evidence)
            assert b"synthetic-debug-token" not in terminal.transcript
        assert kubeconfig.read_bytes() == original
        assert api.pod["metadata"]["uid"] == "owned-debug-pod-uid"
        assert api.pod["spec"]["containers"] == debug_pod()["spec"]["containers"]
        for audit in audits:
            arguments = audit["argv"]
            assert arguments[1:4] == ["--context=kuberich-test-pty", "--namespace=team", "attach"]
            assert arguments[4:] == [
                "--stdin",
                "--tty",
                "--container=debug-pty",
                "--detach-keys=ctrl-p,ctrl-q",
                "--pod-running-timeout=1s",
                "debug-workload",
            ]
            assert not os.path.exists(arguments[0].split("=", 1)[1])
            try:
                os.kill(audit["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Owned debug attach helper survived local teardown.")
        states = api.pod["status"].get("ephemeralContainerStatuses", [])
        if scenario in {"completion", "interrupt"}:
            assert states[0]["state"]["terminated"]["exitCode"] == (
                7 if scenario == "completion" else 130
            )
        elif states and scenario != "startup":
            assert "running" in states[0]["state"]
        writes = [item for item in api.requests if item[0] == "PATCH"]
        expected = 0 if scenario == "read-only" else 1 if scenario in {"cancel", "denied"} else 2
        assert len(writes) == expected
