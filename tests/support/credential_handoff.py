"""Native generic exec-helper login with synthetic identity and an owned API."""

import base64
import json
import os
import signal
from contextlib import suppress

from cryptography.hazmat.primitives import serialization

from tests.support.azure_handoff import APP
from tests.support.connections import certificate
from tests.support.resources import collection, legacy_roots
from tests.terminal.pty_support import TerminalSession

TOKEN = "synthetic.generic.access-token"


def encrypted_key_terminal_trial(python, parent, server, *, name):
    directory = parent / name
    directory.mkdir()
    _, material = certificate(directory)
    key = serialization.load_pem_private_key(
        base64.b64decode(material["client-key-data"]), password=None
    )
    path = directory / "encrypted-key"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"owned-key-password"),
        )
    )
    path.chmod(0o600)
    (directory / "fixture-config").write_text(
        json.dumps(
            {
                "current-context": "kuberich-test-encrypted",
                "clusters": [{"name": "owned", "cluster": {"server": server}}],
                "users": [
                    {
                        "name": "owned",
                        "user": {
                            "client-certificate-data": material["client-certificate-data"],
                            "client-key": path.name,
                        },
                    }
                ],
                "contexts": [
                    {
                        "name": "kuberich-test-encrypted",
                        "context": {"cluster": "owned", "user": "owned", "namespace": "team"},
                    }
                ],
            }
        )
    )
    with TerminalSession(
        [python, "-m", "kuberich", "--kubeconfig", str(directory / "fixture-config")], directory
    ) as terminal:
        terminal.wait_for_screen("Auth Error")
        terminal.send(b"\x11")
        terminal.finish()
        assert b"Enter PEM pass phrase" not in terminal.transcript
        assert b"owned-key-password" not in terminal.transcript
        terminal.save_evidence(name)


def credential_terminal_trial(python, parent, scenario, *, name):
    directory = parent / name
    directory.mkdir()
    mode = "Always" if scenario == "always" else "Never" if scenario == "never" else "IfAvailable"
    helper = directory / "oidc-helper"
    helper.write_text(
        f"#!{python}\n"
        "import os,json,sys\nfrom pathlib import Path\n"
        "info=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\n"
        "Path('helper.pid').write_text(str(os.getpid()))\n"
        "if not os.isatty(2): sys.exit(1)\n"
        "assert info['spec']['interactive'] is os.isatty(0)\n"
        "print('GENERIC LOGIN READY',file=sys.stderr,flush=True)\n"
        "if info['spec']['interactive']: assert sys.stdin.readline().strip()=='complete'\n"
        f"print(json.dumps({{'apiVersion':'client.authentication.k8s.io/v1','kind':'ExecCredential','status':{{'token':{TOKEN!r}}}}}))\n"
    )
    helper.chmod(0o700)
    data = {
        "current-context": "kuberich-test-generic",
        "clusters": [{"name": "owned", "cluster": {"server": "http://127.0.0.1:1"}}],
        "users": [
            {
                "name": "owned",
                "user": {
                    "exec": {
                        "command": str(helper),
                        "apiVersion": "client.authentication.k8s.io/v1",
                        "interactiveMode": mode,
                    }
                },
            }
        ],
        "contexts": [
            {
                "name": "kuberich-test-generic",
                "context": {"cluster": "owned", "user": "owned", "namespace": "team"},
            }
        ],
    }
    # Share the already qualified native application harness; every file and
    # endpoint belongs to this trial, and its user invokes a generic helper.
    (directory / "azure-config").write_text(json.dumps(data))
    (directory / "azure-api").write_text(
        json.dumps(
            {
                **legacy_roots(),
                "/api/v1/namespaces": {
                    "metadata": {"resourceVersion": "owned-list"},
                    "items": [{"metadata": {"name": "team", "uid": "owned-team"}}],
                },
                "collection": collection(),
            }
        )
    )
    script = directory / "generic-app.py"
    script.write_text(APP.replace("synthetic.azure.access-token", TOKEN))
    with TerminalSession([python, str(script), scenario], directory) as terminal:
        terminal.wait_for_screen("Auth Error")
        marker = terminal.send(b":login\r")
        terminal.wait_for(b"configured credential helper authentication", since=marker)
        terminal.wait_for(b"GENERIC LOGIN READY", since=marker)
        pid = int((directory / "helper.pid").read_text())
        if scenario == "parent_shutdown":
            os.kill(int((directory / "azure-parent.pid").read_text()), signal.SIGTERM)
            terminal.finish(expected=143)
        else:
            if scenario == "cancel":
                os.kill(int((directory / "azure-parent.pid").read_text()), signal.SIGUSR1)
            elif scenario == "ctrl_c":
                terminal.send(b"\x03")
            elif scenario != "never":
                terminal.send(b"complete\n")
            expected = "Auth Error" if scenario in {"cancel", "ctrl_c"} else "Live"
            terminal.wait_for_screen(expected, since=marker)
            terminal.resize(80, 25)
            terminal.send(b"?")
            terminal.wait_for_screen("Keyboard help")
            terminal.send(b"\x1b")
            terminal.wait_for_screen(expected, absent=("Keyboard help",))
            terminal.send(b"\x11")
            terminal.finish()
        with suppress(ProcessLookupError):
            os.kill(pid, 0)
            raise AssertionError("Credential helper survived its owner.")
        assert (
            TOKEN.encode() not in terminal.transcript
            and b'"kind": "ExecCredential"' not in terminal.transcript
        )
        terminal.save_evidence(name)
