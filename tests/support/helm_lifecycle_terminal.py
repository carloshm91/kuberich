"""Real production Helm values/editor ownership in source or installed interpreters."""

import hashlib
import json
import os
import signal
from pathlib import Path

from tests.support.helm_catalog import chart_package
from tests.terminal.pty_support import TerminalSession

EDITOR = """import json, os, pathlib, signal, stat, sys, termios
path = pathlib.Path(sys.argv[-1])
assert sys.argv[-2] == '--'
assert os.isatty(0)
assert stat.S_IMODE(path.stat().st_mode) == 0o600
assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
assert 'owned-private-values' in path.read_text()
pathlib.Path(sys.argv[1]).write_text(str(path))
print('OWNED HELM EDITOR START', flush=True)
assert sys.stdin.readline().strip() == 'start'
assert os.tcgetpgrp(0) == os.getpgrp()
mode = termios.tcgetattr(0)
assert mode[3] & termios.ICANON and mode[3] & termios.ECHO
mode[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, mode)
signal.signal(signal.SIGINT, signal.SIG_DFL)
print('OWNED HELM EDITOR READY', flush=True)
action = sys.stdin.readline().strip()
if action == 'failure':
    raise SystemExit(9)
if action == 'malformed':
    path.write_text('invalid: [owned-private-values')
elif action == 'success':
    path.write_text('message: owned-edited\\npassword: owned-private-values\\n')
"""


APP = """import asyncio, hashlib, json, os, shlex, sys
from pathlib import Path
from textual.app import App
from textual.binding import Binding
from textual.widgets import Static
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import ContextConfig, Entry
from kuberich.domain.helm import HelmDriver, HelmReleaseKey, HelmRequest, HelmScope, HelmSettings
from kuberich.domain.helm_archive import inspect_chart_package
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.helm_lifecycle import HelmLifecycleKind
from kuberich.domain.targets import SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from kuberich.services.processes import ProcessRunner
from kuberich.ui.helm_lifecycle import HelmLifecycleScreen

directory = Path.cwd()
package = (directory / 'owned-chart.tgz').read_bytes()
defaults = inspect_chart_package(package, expected_name='owned-chart', expected_version='1.0.0')
chart = ChartSnapshot('owned-chart', '1.0.0', 'owned-pty-chart', hashlib.sha256(package).hexdigest(), package, defaults)
context = ContextConfig('owned-helm-editor', 'team', Entry({'server':'http://127.0.0.1:1'}, directory), Entry({}, directory))
client = KubernetesSession(context, 5)
identity = SessionIdentity(context.name, 1)
request = HelmRequest(HelmScope(identity, 'team', HelmDriver.SECRET), 1)
environment = {'PATH': os.defpath, 'KUBERICH_EDITOR': shlex.join([sys.executable, str(directory/'owned-editor.py'), str(directory/'owned-editor-path')])}
policy = AccessPolicy(False)
service = HelmService(client, policy, HelmSettings('missing-owned-helm'), environment, directory, lambda candidate: candidate == request, catalog_directory=directory/'owned-catalog')
runner = ProcessRunner(policy)
screen = HelmLifecycleScreen(service=service, request=request, address=HelmReleaseKey('team','owned-release'), operation=HelmLifecycleKind.INSTALL, chart=chart, runner=runner)
class OwnedHelmApp(App):
    BINDINGS = [Binding('ctrl+q', 'quit', 'Quit', priority=True)]
    def compose(self):
        yield Static('Owned Helm editor workspace')
    def on_mount(self):
        self.push_screen(screen)
    async def on_unmount(self):
        await screen.stop_owned()
        await runner.close()
        await service.close()
        await client.close()

app = OwnedHelmApp()
(directory/'owned-parent.pid').write_text(str(os.getpid()))
try:
    app.run()
finally:
    (directory/'owned-cleanup.json').write_text(json.dumps({'screen_operations':screen.operation_count, 'service_operations':service.operation_count, 'process_operations':runner.active_count, 'session_directory_absent':not Path(client.directory.name).exists()}))
raise SystemExit(app.return_code)
"""


def terminal_helm_values(
    python: Path | str,
    directory: Path,
    evidence: str,
    *,
    scenario: str = "success",
) -> None:
    """No Helm command or cluster request is needed for this actual editor contract."""
    if scenario not in {"success", "noop", "failure", "malformed", "ctrl_c", "sigterm", "repeat"}:
        raise ValueError("Unknown owned Helm editor scenario.")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "owned-editor.py").write_text(EDITOR)
    (directory / "owned-app.py").write_text(APP)
    package = chart_package(values=b"message: owned-first\npassword: owned-private-values\n")
    (directory / "owned-chart.tgz").write_bytes(package)
    marker = directory / "owned-editor-path"
    paths = []
    with TerminalSession([str(python), str(directory / "owned-app.py")], directory) as terminal:
        terminal.wait_for_screen("Review Helm install")
        for _attempt in range(2 if scenario == "repeat" else 1):
            opening = terminal.send(b"\x1b[Z\x1b[Z\x1b[Z\x1b[Z \t\t\r")
            terminal.wait_for(b"OWNED HELM EDITOR START", since=opening)
            ready = terminal.send(b"start\r")
            terminal.wait_for(b"OWNED HELM EDITOR READY", since=ready)
            path = Path(marker.read_text())
            paths.append(path)
            if scenario == "sigterm":
                os.kill(int((directory / "owned-parent.pid").read_text()), signal.SIGTERM)
                terminal.finish(expected=143)
                break
            terminal.resize(80, 24)
            mode = "success" if scenario == "repeat" else scenario
            action = b"\x03" if mode == "ctrl_c" else (mode + "\r").encode()
            completed = terminal.send(action)
            expected = (
                "Editor stopped or failed"
                if mode in {"failure", "ctrl_c"}
                else "Invalid manifest YAML"
                if mode == "malformed"
                else "Edited values accepted privately"
            )
            terminal.wait_for_screen(expected, since=completed)
            assert not path.parent.exists()
            assert b"owned-private-values" not in terminal.transcript
            terminal.resize(100, 30)
        if scenario != "sigterm":
            terminal.send(b"\x1b")
            terminal.wait_for_screen("Owned Helm editor workspace", absent=("Review Helm install",))
            assert all(not path.parent.exists() for path in paths)
            terminal.send(b"\x11")
            terminal.finish()
        terminal.save_evidence(evidence)
        assert b"owned-private-values" not in terminal.transcript
    cleanup = json.loads((directory / "owned-cleanup.json").read_text())
    assert cleanup == {
        "screen_operations": 0,
        "service_operations": 0,
        "process_operations": 0,
        "session_directory_absent": True,
    }
    assert (
        hashlib.sha256((directory / "owned-chart.tgz").read_bytes()).digest()
        == hashlib.sha256(package).digest()
    )
