"""Actual public creation requests and cancellation through source or native CLIs."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

from tests.support.resources import descriptor, legacy_roots
from tests.support.terminal_api import Handler, Server, config
from tests.terminal.pty_support import TerminalSession

type CommandWrap = Callable[[list[str], dict[str, str]], list[str]]

COLLECTION = "/api/v1/namespaces/team/configmaps"
PRIVATE = "owned-creation-cli-private-value"


class CreationHandler(Handler):
    def reply(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def do_GET(self) -> None:
        server = cast("CreationServer", self.server)
        server.get_requests += 1
        path = urlsplit(self.path).path
        if path == "/api/v1":
            value = legacy_roots()[path]
            value["resources"].append(descriptor("configmaps", kind="ConfigMap"))
            for resource in value["resources"]:
                if resource["name"] == "configmaps":
                    resource["verbs"] = ["get", "list", "watch", "create", "patch", "delete"]
            self.reply(value)
        elif path.startswith(COLLECTION + "/"):
            name = path.rsplit("/", 1)[-1]
            self.reply(
                server.values.get(name, {}),
                200 if name in server.values else 404,
            )
        else:
            super().do_GET()

    def do_POST(self) -> None:
        server = cast("CreationServer", self.server)
        path = urlsplit(self.path)
        assert path.path == COLLECTION
        assert self.headers["Authorization"] == "Bearer synthetic-pty"
        assert self.headers["Content-Type"] == "application/json"
        query = parse_qs(path.query)
        assert query in (
            {"fieldValidation": ["Strict"], "dryRun": ["All"]},
            {"fieldValidation": ["Strict"]},
        )
        dry = query.get("dryRun") == ["All"]
        body = self.rfile.read(int(self.headers["Content-Length"]))
        value = json.loads(body)
        name = value["metadata"]["name"]
        assert value["metadata"]["namespace"] == "team"
        assert "kubectl.kubernetes.io/last-applied-configuration" not in value["metadata"].get(
            "annotations", {}
        )
        server.bodies.append((dry, name, body))
        if name in server.values:
            self.reply({}, 409)
            return
        value["metadata"].setdefault("annotations", {})["example.io/phase"] = (
            "preview" if dry else "persisted"
        )
        value["metadata"]["uid"] = "transient-preview-uid" if dry else "owned-created-uid"
        if not dry:
            value["metadata"]["resourceVersion"] = "owned-created-version"
            server.values[name] = json.loads(json.dumps(value))
            server.committed.set()
            if server.hold:
                assert server.release.wait(20), "Owned creation receipt gate was not released"
        server.requests.append({"method": "POST", "dry_run": dry, "name": name, "status": 201})
        self.reply(value, 201)


class CreationServer(Server):
    def __init__(self, *, hold: bool) -> None:
        super().__init__()
        self.RequestHandlerClass = CreationHandler
        self.pod_table.set()
        self.values: dict[str, dict[str, Any]] = {}
        self.bodies: list[tuple[bool, str, bytes]] = []
        self.requests: list[dict[str, object]] = []
        self.committed, self.release = threading.Event(), threading.Event()
        self.hold = hold
        self.get_requests = 0
        self.handler_threads: list[threading.Thread] = []
        self.handler_lock = threading.Lock()

    def process_request(self, request: Any, client_address: Any) -> None:
        # Register before start, so shutdown cannot miss a scheduled handler.
        request.settimeout(5)
        owner = threading.Thread(
            target=self.process_request_thread, args=(request, client_address), daemon=True
        )
        with self.handler_lock:
            self.handler_threads.append(owner)
        owner.start()

    def drain_handlers(self) -> None:
        deadline = time.monotonic() + 5
        with self.handler_lock:
            owners = tuple(self.handler_threads)
        for owner in owners:
            owner.join(timeout=max(0, deadline - time.monotonic()))
        if any(owner.is_alive() for owner in owners):
            raise ValueError("Owned creation API request handlers were not drained")


def click_visible(terminal: TerminalSession, label: str, *, button: bool = True) -> None:
    """Click the actual rendered public control, without application introspection."""
    labels = (
        "Import file",
        "Edit draft",
        "Review Create",
        "Connect & Review",
        "Validate",
        "Confirm Create",
        "Stop",
        "Previous page",
        "Next page",
        "Back",
    )
    deadline = time.monotonic() + 15
    while True:
        rows = tuple(enumerate(terminal.screen.display))
        # A title/status can mention Validate before the new modal footer paints.
        # Wait for the actual footer's parallel controls, not that earlier text.
        candidates = rows[-6:] if button else rows
        for row, line in reversed(candidates):
            column = line.find(label)
            if column >= 0 and (not button or sum(value in line for value in labels) >= 2):
                x, y = column + len(label) // 2 + 1, row + 1
                terminal.send(f"\x1b[<0;{x};{y}M\x1b[<0;{x};{y}m".encode())
                return
        assert time.monotonic() < deadline, "Public control footer was not rendered"
        terminal.read(0.01)


def terminal_resource_creation_cli(
    command: list[str],
    directory: Path,
    evidence: str,
    *,
    mode: Literal["success", "cancel"] = "success",
    initial_offline: bool = False,
    wrap: CommandWrap | None = None,
    environment: Mapping[str, str] | None = None,
    controller_environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    owned = {
        key: directory / name
        for key, name in {
            "HOME": "home",
            "TMPDIR": "private",
            "XDG_CONFIG_HOME": "config",
            "XDG_DATA_HOME": "data",
            "XDG_STATE_HOME": "state",
            "XDG_CACHE_HOME": "cache",
        }.items()
    }
    for path in (*owned.values(), directory / "no-tools"):
        path.mkdir(mode=0o700)
    preferences = directory / "preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    variables = {
        **dict(environment or {}),
        **{key: str(path) for key, path in owned.items()},
        "PATH": str(directory / "no-tools"),
        "KUBERICH_CONFIG": str(preferences),
        "KUBERICH_LOG_FILE": str(directory / "kuberich.log"),
        "KUBERICH_CLIPBOARD": "osc52",
    }
    source = directory / "owned-create.yaml"
    names = (
        ("owned-created-first",)
        if mode == "success"
        else ("owned-created-first", "owned-created-second")
    )
    source.write_text(
        "\n---\n".join(
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": name},
                    "data": {"message": PRIVATE},
                }
            )
            for name in names
        )
    )
    source.chmod(0o600)
    original = source.read_bytes()
    server = CreationServer(hold=mode == "cancel")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        thread.start()
    except BaseException:
        server.server_close()
        raise
    closed = False

    def close_server() -> None:
        nonlocal closed
        if closed:
            return
        server.release.set()
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        if thread.is_alive():
            raise ValueError("Owned creation API controller was not reaped")
        server.drain_handlers()
        closed = True

    try:
        kubeconfig = config(
            directory / "owned-kubeconfig",
            f"http://127.0.0.1:{server.server_port}",
            {"token": "synthetic-pty"},
        )
        kubeconfig.chmod(0o600)
        original_config = kubeconfig.read_bytes()
        argv = [*command, "--kubeconfig", str(kubeconfig), "--namespace", "team"]
        if initial_offline:
            argv.extend(("--command", "create"))
        launched = wrap(argv, variables) if wrap is not None else argv
        outside = dict(controller_environment or {})
        if wrap is None:
            outside.update(variables)
        with TerminalSession(launched, directory, environment=outside, size=(120, 36)) as terminal:
            if not initial_offline:
                terminal.wait_for_screen("80 pods")
                terminal.send(b":create\r")
            terminal.wait_for_screen("Create resources · offline source")
            click_visible(terminal, "Explicit local manifest file path", button=False)
            terminal.send(b"owned-create.yaml")
            terminal.wait_for_screen("owned-create.yaml")
            click_visible(terminal, "Import file")
            terminal.wait_for_screen("File captured offline")
            assert not server.bodies and PRIVATE not in "\n".join(terminal.screen.display)
            if initial_offline:
                assert server.get_requests == 0
            click_visible(terminal, "Connect & Review" if initial_offline else "Review Create")
            terminal.wait_for_screen("Manifest cluster review")
            click_visible(terminal, "Validate")
            terminal.wait_for_screen("All resources validated")
            assert not server.values and len(server.bodies) == len(names)
            assert all(dry for dry, _, _ in server.bodies)
            click_visible(terminal, "Confirm Create")
            if mode == "cancel":
                deadline = time.monotonic() + 5
                while not server.committed.is_set():
                    terminal.read(0.01)
                    assert time.monotonic() < deadline, "Owned POST never committed"
                click_visible(terminal, "Stop")
                terminal.wait_for_screen("Write outcome uncertain")
                assert "Verified persistent creation receipt" not in "\n".join(
                    terminal.screen.display
                )
                server.release.set()
            else:
                terminal.wait_for_screen("Verified persistent creation receipt")
                terminal.wait_for_screen("owned-created-uid")
                terminal.wait_for_screen("owned-created-version")
            assert set(server.values) == {names[0]}
            requests = [body for dry, _, body in server.bodies if not dry]
            assert len(requests) == 1 and requests[0] == server.bodies[0][2]
            assert PRIVATE not in "\n".join(terminal.screen.display)
            terminal.send(b"\x1b")
            terminal.wait_for_screen(
                "Create resources · offline source", absent=("Manifest cluster review",)
            )
            terminal.send(b"\x1b")
            terminal.wait_for_screen("80 pods", absent=("Create resources · offline source",))
            terminal.send(b"\x11")
            terminal.finish()
            assert PRIVATE.encode() not in terminal.transcript
            terminal.save_evidence(evidence)
        close_server()
        requests = [body for dry, _, body in server.bodies if not dry]
        assert len(requests) == 1 and requests[0] == server.bodies[0][2]
        assert set(server.values) == {names[0]}
        assert sum(dry for dry, _, _ in server.bodies) == len(names)
        assert source.read_bytes() == original and kubeconfig.read_bytes() == original_config
        log = directory / "kuberich.log"
        assert log.is_file() and PRIVATE.encode() not in log.read_bytes()
        receipt: dict[str, object] = {
            "mode": mode,
            "initially_offline": initial_offline,
            "source_capture_network_absent": initial_offline,
            "wrapped": wrap is not None,
            "server_validation": "Owned controlled HTTP fixture, not a Kubernetes schema authority",
            "dry_runs": len(names),
            "persistent_posts": 1,
            "created_uid": server.values[names[0]]["metadata"]["uid"],
            "created_version": server.values[names[0]]["metadata"]["resourceVersion"],
            "application_result": "Succeeded" if mode == "success" else "Write outcome uncertain",
            "known_application_receipt": mode == "success",
            "request_bytes_identical": True,
            "later_item_unsent": mode == "cancel",
            "no_replay": True,
            "source_and_kubeconfig_unchanged": True,
            "external_tool_executed": False,
            "api_handlers_drained": True,
            "complete_ansi_and_log_private_value_absent": True,
        }
        (directory / "creation-cli-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return receipt
    finally:
        close_server()
