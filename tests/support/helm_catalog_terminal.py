"""Public CLI Helm catalog/editor proof reusable by installed and native entrypoints."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import stat
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from tests.support.helm_catalog import chart_package, repository_index
from tests.support.resources import descriptor, legacy_roots
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession

CommandWrap = Callable[[list[str], dict[str, str]], list[str]]
PRIVATE_VALUE = "owned-private-shell-values"
TOKEN = "synthetic-owned-catalog-cli"
SHELL_EDITOR = """#!/bin/sh
test "$#" -eq 3 || exit 31
test "$2" = -- || exit 32
test -t 0 || exit 33
marker=$1
draft=$3
printf '%s\\n' "$draft" > "$marker"
printf 'OWNED SHELL EDITOR START\\n'
IFS= read -r starting || exit 34
test "$starting" = start || exit 35
printf 'OWNED SHELL EDITOR READY\\n'
IFS= read -r action || exit 36
case "$action" in
 edit) printf 'message: owned-cli-edited\\npassword: owned-private-shell-values\\n' > "$draft" ;;
 noop) : ;;
 *) exit 37 ;;
esac
"""


class _CatalogHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = cast("_CatalogServer", self.server)
        parsed = urlsplit(self.path)
        server.requests.append((parsed.path, parse_qs(parsed.query)))
        if parsed.path == "/charts/index.yaml":
            server.repository_auth.append(self.headers.get("Authorization"))
            self._reply(server.index, content_type="application/yaml")
            return
        if parsed.path == "/charts/owned-chart-1.0.0.tgz":
            server.repository_auth.append(self.headers.get("Authorization"))
            self._reply(server.package, content_type="application/gzip")
            return
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self._reply({}, status=401)
            return
        roots = legacy_roots()
        roots["/api/v1"]["resources"] = [
            descriptor("namespaces", kind="Namespace", namespaced=False),
            descriptor("configmaps", kind="ConfigMap"),
            descriptor("secrets", kind="Secret"),
        ]
        if parsed.path in roots:
            self._reply(roots[parsed.path])
        elif parsed.path == "/api/v1/namespaces":
            self._reply(
                {
                    "apiVersion": "v1",
                    "kind": "NamespaceList",
                    "metadata": {"resourceVersion": "owned-namespaces"},
                    "items": [
                        {
                            "metadata": {
                                "name": name,
                                "uid": "owned-ns-" + name,
                                "resourceVersion": "owned-ns-rv",
                            },
                            "status": {"phase": "Active"},
                        }
                        for name in ("team", "default")
                    ],
                }
            )
        elif parsed.path == "/api/v1/namespaces/team":
            self._reply(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": "team",
                        "uid": "owned-ns-team",
                        "resourceVersion": "owned-ns-rv",
                    },
                    "status": {"phase": "Active"},
                }
            )
        elif parsed.path == "/api/v1/namespaces/team/secrets":
            self._reply(
                {
                    "apiVersion": "meta.k8s.io/v1",
                    "kind": "PartialObjectMetadataList",
                    "metadata": {"resourceVersion": "owned-storage"},
                    "items": [],
                }
            )
        else:
            self._reply({}, status=404)

    def do_POST(self) -> None:
        cast("_CatalogServer", self.server).writes.append(self.path)
        self._reply({}, status=405)

    def _reply(
        self, value: Any, *, status: int = 200, content_type: str = "application/json"
    ) -> None:
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class _CatalogServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _CatalogHandler)
        self.package = chart_package(
            values=("message: owned-cli-first\npassword: " + PRIVATE_VALUE + "\n").encode()
        )
        self.index = repository_index({("owned-chart", "1.0.0"): self.package})
        self.requests: list[tuple[str, dict[str, list[str]]]] = []
        self.repository_auth: list[str | None] = []
        self.writes: list[str] = []

    def repository_requests(self) -> int:
        return sum(path.startswith("/charts/") for path, _ in self.requests)


def terminal_helm_catalog(
    command: list[str],
    directory: Path,
    evidence: str,
    *,
    wrap: CommandWrap | None = None,
    environment: Mapping[str, str] | None = None,
    controller_environment: Mapping[str, str] | None = None,
    readonly_reopen: bool = True,
) -> dict[str, object]:
    """Drive the actual CLI; only the controller uses Python for its owned HTTP fixture."""
    if not command or not Path(command[0]).is_absolute() or not directory.is_absolute():
        raise ValueError("Use an explicit application entrypoint and absolute owned directory.")
    directory.mkdir(parents=True, exist_ok=True)
    state_names = {
        "HOME": "home",
        "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "TMPDIR": "private",
    }
    owned = {key: directory / name for key, name in state_names.items()}
    for path in (*owned.values(), directory / "no-tools"):
        path.mkdir(mode=0o700)
    editor = directory / "owned-shell-editor.sh"
    editor.write_text(SHELL_EDITOR)
    editor.chmod(0o700)
    marker = directory / "owned-shell-draft"
    preferences = directory / "owned-preferences.yaml"
    preferences.write_text("schema_version: 1\n")
    process_environment = {
        **dict(environment or {}),
        **{key: str(path) for key, path in owned.items()},
        "PATH": str(directory / "no-tools"),
        "HELM_DRIVER": "secret",
        "KUBERICH_CONFIG": str(preferences),
        "KUBERICH_CLIPBOARD": "osc52",
        "KUBERICH_EDITOR": shlex.join(["/bin/sh", str(editor), str(marker)]),
    }
    server = _CatalogServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kubeconfig = config(
        directory / "owned-catalog-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": TOKEN},
    )
    kubeconfig.chmod(0o600)
    original_config = kubeconfig.read_bytes()
    argv = [
        *command,
        "--kubeconfig",
        str(kubeconfig),
        "--namespace",
        "team",
        "--command",
        "helmcharts",
    ]

    def launch(arguments: list[str]) -> list[str]:
        return wrap(arguments, dict(process_environment)) if wrap is not None else arguments

    outside = dict(controller_environment or {})
    if wrap is None:
        outside.update(process_environment)
    paths: list[Path] = []
    receipt: dict[str, object] = {
        "entrypoint": command,
        "wrapped": wrap is not None,
        "editor": "/bin/sh",
        "package_sha256": hashlib.sha256(server.package).hexdigest(),
        "index_sha256": hashlib.sha256(server.index).hexdigest(),
    }
    try:
        with TerminalSession(launch(argv), directory, environment=outside) as terminal:
            terminal.wait_for_screen("0 cached versions")
            assert server.repository_requests() == 0
            terminal.send(b"\t\r")
            terminal.wait_for_screen("Helm repository")
            # Cancel -> Confirm -> download origins -> token origins -> auth -> CA
            # -> loopback -> URL -> kind -> name; disabled credential fields are skipped.
            terminal.send(b"\x1b[Z" * 9)
            terminal.send(b"owned-cli\t\t")
            terminal.send(f"http://127.0.0.1:{server.server_port}/charts".encode())
            terminal.send(b"\t \t\t\t\t\t\r")
            terminal.wait_for_screen("1 cached versions")
            assert server.repository_requests() == 1
            terminal.send(b"\x1b[Z\x1b[Zowned-release\t\r")
            terminal.wait_for_screen("Review Helm install")
            assert server.repository_requests() == 2
            for _attempt in range(2):
                opening = terminal.send(b"\x1b[Z" * 4 + b" \t\t\r")
                terminal.wait_for(b"OWNED SHELL EDITOR START", since=opening)
                ready = terminal.send(b"start\r")
                terminal.wait_for(b"OWNED SHELL EDITOR READY", since=ready)
                draft = Path(marker.read_text().strip())
                paths.append(draft)
                assert draft.resolve().is_relative_to(owned["TMPDIR"].resolve())
                assert stat.S_IMODE(draft.stat().st_mode) == 0o600
                assert stat.S_IMODE(draft.parent.stat().st_mode) == 0o700
                assert PRIVATE_VALUE in draft.read_text()
                terminal.resize(80, 24)
                completed = terminal.send(b"edit\r")
                terminal.wait_for_screen("Edited values accepted privately", since=completed)
                assert not draft.parent.exists()
                terminal.resize(100, 30)
            preparing = terminal.send(b"\x1b[Z\r")
            terminal.wait_for_screen("Helm is unavailable", since=preparing)
            assert server.writes == []
            terminal.send(b"\x1b")
            terminal.wait_for_screen("1 cached versions", absent=("Review Helm install",))
            requests = server.repository_requests()
            terminal.send(b"\t\t\t\r")
            terminal.wait_for_screen("1 cached versions")
            assert server.repository_requests() == requests
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence + "-editor")
            assert (
                PRIVATE_VALUE.encode() not in terminal.transcript
                and TOKEN.encode() not in terminal.transcript
            )
        assert all(not path.parent.exists() for path in paths)
        assert not any(owned["TMPDIR"].iterdir())
        persistent = tuple(
            path
            for root in (owned["HOME"], owned["XDG_STATE_HOME"], owned["XDG_DATA_HOME"])
            for path in root.rglob("*.json")
        )
        assert persistent and all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in persistent)
        if readonly_reopen:
            before = server.repository_requests()
            with TerminalSession(
                launch([*argv, "--readonly"]), directory, environment=outside
            ) as terminal:
                terminal.wait_for_screen("1 cached versions")
                terminal.send(b"\r")
                terminal.resize(40, 12)
                terminal.wait_for_screen("Helm charts")
                terminal.send(b"\x11")
                terminal.finish()
                terminal.save_evidence(evidence + "-cached-readonly")
                assert (
                    PRIVATE_VALUE.encode() not in terminal.transcript
                    and TOKEN.encode() not in terminal.transcript
                )
            assert server.repository_requests() == before and server.writes == []
        assert kubeconfig.read_bytes() == original_config
        assert all(value is None for value in server.repository_auth)
        assert not any(owned["TMPDIR"].iterdir())
        receipt.update(
            repository_requests=server.repository_requests(),
            api_writes=0,
            editor_sessions=len(paths),
            private_files_absent=True,
            cached_readonly_reopened=readonly_reopen,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        for path in owned.values():
            shutil.rmtree(path)
        assert all(not path.exists() for path in owned.values())
    receipt["owned_state_removed"] = True
    (directory / "helm-catalog-cli-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
