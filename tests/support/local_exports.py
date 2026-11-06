"""Source/installed real CLI browser trials with owned files and network refusal evidence."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

import yaml

from kuberich.config.schema import parse_document
from kuberich.config.store import write_config
from kuberich.domain.exports import DocumentSource, ExportCapture, ExportScope, prepare_capture
from tests.terminal.pty_support import ROOT, TerminalSession

_AUDIT = '''"""Owned terminal-test audit hook; refuse every actual network attempt."""
import json
import os
import sys
from pathlib import Path

_record = os.environ.get("KUBERICH_EXPORT_NETWORK_AUDIT")
if _record:
    def _write(event):
        descriptor = os.open(_record, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, (json.dumps(event) + "\\n").encode())
        finally:
            os.close(descriptor)

    _write({"event": "loaded", "program": Path(sys.argv[0]).name})

    def _audit(event, arguments):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            _write({"event": event})
            raise RuntimeError("Owned offline export test refused network access.")

    sys.addaudithook(_audit)
'''

_HELPER = '''"""Explicit synthetic credential sentinel; any invocation fails the trial."""
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text("called\\n")
print(json.dumps({"apiVersion": "client.authentication.k8s.io/v1", "kind": "ExecCredential",
                  "status": {"token": "synthetic-offline-export-credential"}}))
'''


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.calls.append(self.path)
        body = b'{"kind":"NamespaceList","items":[],"metadata":{"resourceVersion":"owned"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.calls = []


def _records(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _source_binding():
    names = (
        "src/kuberich/cli.py",
        "src/kuberich/bootstrap.py",
        "src/kuberich/ui/launch.py",
        "src/kuberich/ui/app.py",
        "src/kuberich/ui/workspace_screen.py",
        "src/kuberich/ui/workspace_navigation.py",
        "src/kuberich/ui/export_actions.py",
        "src/kuberich/ui/artifact_browser.py",
        "src/kuberich/ui/artifact_viewer.py",
        "src/kuberich/services/exports.py",
        "src/kuberich/adapters/artifact_files.py",
        "src/kuberich/domain/exports.py",
        "pyproject.toml",
        "uv.lock",
    )
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def terminal_local_exports(command, directory, *, evidence, size=(100, 30), wheel_sha256=None):
    """Exercise actual CLI input/output; never connect, authenticate or check a release."""
    directory.mkdir(parents=True, exist_ok=True)
    # macOS temporary-directory spellings may start with the /var symlink.
    # Supply the owned physical location that the production no-follow adapter requires.
    directory = directory.resolve(strict=True)
    home, hooks, exports = directory / "owned-home", directory / "audit-hook", directory / "exports"
    for path in (home, hooks, exports):
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    (hooks / "sitecustomize.py").write_text(_AUDIT)
    network_log, negative_log = directory / "network.jsonl", directory / "network-negative.jsonl"
    helper, helper_called = directory / "credential-sentinel.py", directory / "helper-called"
    helper.write_text(_HELPER)
    preferences, kubeconfig = directory / "preferences.yaml", directory / "owned-kubeconfig"
    document = parse_document({"schema_version": 1, "appearance": {"check_updates": True}})
    write_config(preferences, document)
    original_preferences = preferences.read_bytes()
    server = _Server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kubeconfig.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Config",
                "current-context": "owned-export-context",
                "contexts": [
                    {
                        "name": "owned-export-context",
                        "context": {
                            "cluster": "owned-export-cluster",
                            "user": "owned-exec",
                            "namespace": "team",
                        },
                    }
                ],
                "clusters": [
                    {
                        "name": "owned-export-cluster",
                        "cluster": {"server": f"http://127.0.0.1:{server.server_port}"},
                    }
                ],
                "users": [
                    {
                        "name": "owned-exec",
                        "user": {
                            "exec": {
                                "apiVersion": "client.authentication.k8s.io/v1",
                                "command": sys.executable,
                                "args": [str(helper), str(helper_called)],
                                "interactiveMode": "Never",
                            }
                        },
                    }
                ],
            }
        )
    )
    original_kubeconfig = kubeconfig.read_bytes()
    seed = prepare_capture(
        ExportCapture(
            scope=ExportScope(
                export_at=datetime(2026, 11, 5, tzinfo=UTC),
                source_at=None,
                context="owned-saved-context",
                header_namespace=None,
                collection_namespace=None,
                namespace_mode="local",
            ),
            source=DocumentSource(
                page="evidence", text="owned-export-body\nBearer PRIVATE_PTY_EXPORT\n"
            ),
        ),
        "screen",
        artifact_id=UUID("00000000-0000-0000-0000-000000000073"),
    )
    artifact = exports / "owned-export.txt"
    artifact.write_bytes(seed.payload)
    artifact.chmod(0o600)
    environment = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(hooks),
        "KUBERICH_EXPORT_NETWORK_AUDIT": str(network_log),
    }
    terminal = None
    try:
        # Deliberate negative control proves the same child hook observes and
        # refuses a connection, before the actual CLI's separate zero-event run.
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=1)",
                str(server.server_port),
            ],
            cwd=directory,
            env={**os.environ, **environment, "KUBERICH_EXPORT_NETWORK_AUDIT": str(negative_log)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert (
            probe.returncode != 0
            and "Owned offline export test refused network access." in probe.stderr
        )
        negative = _records(negative_log)
        assert any(record["event"].startswith("socket.") for record in negative)
        arguments = [
            *command,
            "--config",
            str(preferences),
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "owned-export-context",
            "--readonly",
            "--command",
            "exports",
            "--screen-dump-dir",
            str(exports),
        ]
        with TerminalSession(arguments, directory, size=size, environment=environment) as terminal:
            terminal.wait_for_screen("Saved artifacts")
            terminal.wait_for_screen("owned-export.txt")
            terminal.wait_for_screen("1 shown")
            assert not server.calls and not helper_called.exists()
            assert not any(
                record["event"].startswith("socket.") for record in _records(network_log)
            )
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("Local artifact", since=marker)
            terminal.wait_for_screen("owned-export-body", since=marker)
            terminal.wait_for_screen("Page 1/1", since=marker)
            assert "PRIVATE_PTY_EXPORT" not in "\n".join(terminal.screen.display)
            marker = terminal.send(b"\x19")
            terminal.wait_for(b"\x1b]52;c;", since=marker)
            terminal.wait_for_screen("Clipboard write requested", since=marker)
            clipboard_payload = base64.b64encode(seed.payload)
            terminal.wait_for(clipboard_payload, since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("Saved artifacts", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(
                "Disconnected", since=marker, absent=("Saved artifacts", "Local artifact")
            )
            assert not server.calls and not helper_called.exists()
            marker = terminal.send(b":exports\r")
            terminal.wait_for_screen("Saved artifacts", since=marker)
            terminal.wait_for_screen("owned-export.txt", since=marker)
            # A newly added owned fixture makes completion of the actual local
            # refresh observable, without relying on an unchanged frame repaint.
            refreshed = exports / "refresh-export.txt"
            refreshed.write_bytes(seed.payload)
            refreshed.chmod(0o600)
            marker = terminal.send(b"\x12")
            terminal.wait_for_screen("2 shown", since=marker)
            # The table initially owns focus. Four visible button steps select
            # Delete; its distinct acknowledgement defaults to Cancel.
            marker = terminal.send(b"\t\t\t\t\r")
            terminal.wait_for_screen("Delete this named local entry?", since=marker)
            assert artifact.is_file()
            marker = terminal.send(b"\x1b[Z\r")
            terminal.wait_for_screen("1 shown", since=marker)
            assert not artifact.exists()
            assert refreshed.read_bytes() == seed.payload
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("Disconnected", since=marker, absent=("Saved artifacts",))
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"PRIVATE_PTY_EXPORT" not in terminal.transcript
            assert b"synthetic-offline-export-credential" not in terminal.transcript
        observed = _records(network_log)
        assert any(record["event"] == "loaded" and record["program"] != "-c" for record in observed)
        assert not any(record["event"].startswith("socket.") for record in observed)
        assert not server.calls and not helper_called.exists()
        assert not list(home.rglob("latest-release.json"))
        assert sorted(path.name for path in exports.iterdir()) == ["refresh-export.txt"]
        assert preferences.read_bytes() == original_preferences
        assert kubeconfig.read_bytes() == original_kubeconfig
        assert terminal.cleanup["status"] == "complete"
        assert terminal.cleanup["owner_reaped"] and terminal.cleanup["descriptors_closed"]
        assert terminal.cleanup["group"] == "gone"
        output = ROOT / "artifacts" / "terminal" / (evidence + "-offline.json")
        output.write_text(
            json.dumps(
                {
                    "source_binding": _source_binding(),
                    "wheel_sha256": wheel_sha256,
                    "api_requests": server.calls,
                    "helper_invocations": 0,
                    "network_audit": observed,
                    "negative_network_control": negative,
                    "preferences_unchanged": True,
                    "kubeconfig_unchanged": True,
                    "artifact_viewed": True,
                    "redacted_clipboard_write_observed": True,
                    "explicit_delete_observed": True,
                    "disconnected_after_back": True,
                    "cleanup": terminal.cleanup,
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
