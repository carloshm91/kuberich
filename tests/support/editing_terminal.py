"""Real foreground editor, exact conditional dry-run/apply and native terminal restoration."""

import json
import shlex
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from kubetrol.domain.registry import RESOURCE_ALIASES
from tests.support.editing import apply_patch
from tests.support.mutation_terminal import MutationHandler
from tests.support.standard import manifest
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


class EditingHandler(MutationHandler):
    def do_PATCH(self):
        url = urlsplit(self.path)
        assert url.path == "/api/v1/namespaces/team/configmaps/owned-one"
        query = parse_qs(url.query)
        assert query.get("fieldValidation") == ["Strict"]
        operations = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((operations, query))
        candidate = apply_patch(self.server.value, operations)
        if candidate is None:
            self.reply({}, 422)
            return
        if query.get("dryRun") != ["All"]:
            candidate["metadata"]["resourceVersion"] = "version-8"
            self.server.value = candidate
        self.reply(candidate)


EDITOR = """import json, os, pathlib, stat, sys, yaml
path=pathlib.Path(sys.argv[-1])
assert sys.argv[-2]=="--"
assert os.isatty(0)
assert stat.S_IMODE(path.stat().st_mode)==0o600
assert stat.S_IMODE(path.parent.stat().st_mode)==0o700
value=yaml.safe_load(path.read_text())
assert value["metadata"]["resourceVersion"]=="opaque/version-7"
pathlib.Path(sys.argv[1]).write_text(str(path))
try:
    action=input("OWNED FOREGROUND EDITOR: enter e/n/f/m > ")
except KeyboardInterrupt:
    sys.exit(130)
assert os.tcgetpgrp(0)==os.getpgrp()
if action=="f":
    sys.exit(9)
if action=="m":
    path.write_text("invalid: [sensitive-editor-content")
elif action=="e":
    value["metadata"].setdefault("labels",{})["example.io/edit"]="owned-terminal-label"
    value["data"]["edited"]="sensitive-editor-content"
    path.write_text(json.dumps(value))
"""


def terminal_editing(command, directory, evidence, *, scenario="success"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), EditingHandler)
    server.stopping = threading.Event()
    server.requests = []
    server.value = manifest(RESOURCE_ALIASES["cm"])
    server.value["metadata"]["resourceVersion"] = "opaque/version-7"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kubeconfig = config(
        directory / "owned-edit-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = kubeconfig.read_bytes()
    helper = directory / "owned-editor.py"
    helper.write_text(EDITOR)
    marker = directory / "owned-editor-path"
    environment = {"KUBETROL_EDITOR": shlex.join([sys.executable, str(helper), str(marker)])}
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(kubeconfig), "--command", "cm team"],
            directory,
            environment=environment,
        ) as terminal:
            terminal.wait_for_screen("configmaps(team)[1]")
            terminal.send(b":edit\r")
            terminal.wait_for_screen("Ready · allow local disclosure")
            terminal.send(b"\x1b[Z\x1b[Z \t\r")
            try:
                terminal.wait_for(b"OWNED FOREGROUND EDITOR")
            except AssertionError:
                (directory / "failed-editor-screen.txt").write_text(
                    "\n".join(terminal.screen.display)
                )
                raise AssertionError(
                    "Editor failed to start: " + "\n".join(terminal.screen.display)
                ) from None
            path = Path(marker.read_text())
            action = {
                "success": b"e\r",
                "noop": b"n\r",
                "failure": b"f\r",
                "malformed": b"m\r",
                "ctrl_c": b"\x03",
            }[scenario]
            terminal.send(action)
            needle = {
                "success": "Review the redacted diff",
                "noop": "No semantic changes",
                "failure": "Editor cancelled or failed",
                "malformed": "Invalid manifest YAML",
                "ctrl_c": "Editor cancelled or failed",
            }[scenario]
            terminal.wait_for_screen(needle)
            assert not server.requests and "edited" not in server.value["data"]
            if scenario == "success":
                terminal.wait_for_screen("owned-terminal-label")
                terminal.send(b"\x1b[Z\r")  # Cancel -> Validate; Apply is still disabled.
                terminal.wait_for_screen("Server dry-run passed")
                assert len(server.requests) == 1 and server.requests[0][1]["dryRun"] == ["All"]
                assert "edited" not in server.value["data"]
                terminal.send(b"\x1b[Z\r")  # Separate deliberate Apply after validation.
                terminal.wait_for_screen("API confirmed the guarded patch")
                assert len(server.requests) == 2 and "dryRun" not in server.requests[1][1]
                assert server.requests[0][0] == server.requests[1][0]
                assert server.value["data"]["edited"] == "sensitive-editor-content"
                assert (
                    server.value["metadata"]["labels"]["example.io/edit"] == "owned-terminal-label"
                )
            terminal.resize(40, 12)
            terminal.wait_for_screen("Edit manifest")
            terminal.resize(100, 30)
            terminal.send(b"\x1b")
            terminal.wait_for_screen("configmaps(team)[1]", absent=("Edit manifest",))
            assert not path.parent.exists()
            if scenario == "success":
                terminal.send(b":writes\r")
                terminal.wait_for_screen("last 32 operations")
                terminal.wait_for_screen("API confirmed")
                assert "sensitive-editor-content" not in "\n".join(terminal.screen.display)
                terminal.send(b"\x1b")
                terminal.wait_for_screen("configmaps(team)[1]", absent=("Writes ·",))
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert kubeconfig.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
