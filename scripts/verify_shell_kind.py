"""S04: real CLI/TTY exec inside a newly created, explicitly owned kind cluster."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import yaml
from kubernetes_asyncio import client

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.config.catalog import load_catalog
from kubetrol.domain.connections import ConnectionRequest
from tests.terminal.pty_support import TerminalSession

NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)
SHELL_IMAGE = "alpine@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b"


async def prepare(path: Path, context: str, namespace: str) -> tuple[dict, str]:
    request = ConnectionRequest(kubeconfig=str(path), context=context, namespace=namespace)
    selected = load_catalog(request, {}).select(context)
    session = KubernetesSession(selected, 15)
    try:
        await session.open()
        assert session.api is not None
        api = client.CoreV1Api(session.api)
        await api.create_namespace({"metadata": {"name": namespace}})
        await api.create_namespaced_pod(
            namespace,
            {
                "metadata": {"name": "owned-shell-pod", "namespace": namespace},
                "spec": {
                    "containers": [
                        {
                            "name": name,
                            "image": SHELL_IMAGE,
                            "command": ["/bin/sh", "-c", "while true; do sleep 60; done"],
                            "env": [
                                {"name": "KUBETROL_OWNED_CONTAINER", "value": name},
                                {"name": "PS1", "value": "OWNED-SHELL> "},
                            ],
                        }
                        for name in ["app-a", "app-b"]
                    ]
                },
            },
        )
        async with asyncio.timeout(180):
            while True:
                pod = await api.read_namespaced_pod("owned-shell-pod", namespace)
                if pod.status.container_statuses and all(
                    value.ready for value in pod.status.container_statuses
                ):
                    break
                await asyncio.sleep(0.5)
        await api.create_namespaced_service_account(
            namespace, {"metadata": {"name": "shell-reader"}}
        )
        rbac = client.RbacAuthorizationV1Api(session.api)
        await rbac.create_namespaced_role(
            namespace,
            {
                "metadata": {"name": "shell-reader"},
                "rules": [
                    {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]}
                ],
            },
        )
        await rbac.create_namespaced_role_binding(
            namespace,
            {
                "metadata": {"name": "shell-reader"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "shell-reader",
                },
                "subjects": [
                    {"kind": "ServiceAccount", "name": "shell-reader", "namespace": namespace}
                ],
            },
        )
        token = await api.create_namespaced_service_account_token(
            "shell-reader",
            namespace,
            {"spec": {"expirationSeconds": 1800}},
        )
        return {"uid": pod.metadata.uid, "namespace": namespace}, token.status.token
    finally:
        await session.close()


def trial(
    path: Path, context: str, namespace: str, directory: Path, *, scenario: str, kubectl: Path
) -> None:
    directory.mkdir()
    preferences = {"schema_version": 1}
    if scenario == "configured":
        preferences["shell"] = ["/bin/sh", "-i"]
    if scenario == "missing-shell":
        preferences["shell"] = ["/no-such-owned-shell"]
    (directory / "preferences.yaml").write_text(yaml.safe_dump(preferences))
    wrapper = directory / "launch.py"
    wrapper.write_text(
        "import os,sys\nfrom pathlib import Path\nos.environ['PATH']=str(Path(sys.argv[1]).parent)+os.pathsep+os.environ.get('PATH','')\nos.execv(sys.argv[2],sys.argv[2:])\n"
    )
    command = [
        sys.executable,
        str(wrapper),
        str(kubectl),
        sys.executable,
        "-m",
        "kubetrol",
        "--kubeconfig",
        str(path),
        "--context",
        context,
        "--namespace",
        namespace,
    ]
    before = path.read_bytes()
    attempts = 2 if scenario == "success" else 1
    try:
        with TerminalSession(command, directory) as terminal:
            terminal.wait_for(b"owned-shell-pod", timeout=30)
            terminal.wait_for(b"1 pod", timeout=30)
            if scenario == "success":
                changed = yaml.safe_load(before)
                changed["clusters"][0]["cluster"]["server"] = "https://127.0.0.1:9"
                path.write_text(yaml.safe_dump(changed))
            marker = terminal.send(b":shell\r")
            terminal.wait_for(b"Containers", since=marker)
            terminal.wait_for(b"app-b", since=marker)
            terminal.send(b"\x1b[B")
            for attempt in range(attempts):
                marker = terminal.send(b"s")
                terminal.wait_for_screen("Kubetrol · Container shell", timeout=30)
                terminal.wait_for_screen("Context: kubetrol-test-Alias")
                terminal.wait_for_screen("Pod: kubetrol-shell-test/owned-shell-pod")
                terminal.wait_for_screen("Container: app-b")
                assert b"\x1b[?1049l" not in terminal.transcript[marker:]
                if scenario in {"denied", "missing-shell"}:
                    terminal.wait_for(b"kubectl exec failed", since=marker, timeout=30)
                    terminal.wait_for(b"pods/exec", since=marker)
                    assert b"OWNED-SHELL> " not in terminal.transcript[marker:]
                    break
                terminal.wait_for_screen("OWNED-SHELL> ", timeout=30)
                marker = terminal.send(b"printf 'REMOTE_%s\\n' \"$KUBETROL_OWNED_CONTAINER\"\n")
                terminal.wait_for_screen("REMOTE_app-b")
                marker = terminal.resize(80, 25)
                terminal.wait_for_screen("╰" + "─" * 78 + "╯")
                terminal.send(b"stty size\n")
                terminal.wait_for_screen("19 78")
                if scenario == "success" and attempt == 0:
                    marker = terminal.send(b"vi /tmp/owned-shell-trial\n")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial 1/1")
                    marker = terminal.resize(100, 30)
                    terminal.wait_for_screen("Container: app-b")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial 1/1")
                    marker = terminal.resize(80, 25)
                    terminal.wait_for_screen("- /tmp/owned-shell-trial 1/1")
                    marker = terminal.send(b"iOWNED_REMOTE_EDIT")
                    terminal.wait_for_screen("OWNED_REMOTE_EDIT")
                    marker = terminal.send(b"\x1b")
                    terminal.wait_for_screen("- /tmp/owned-shell-trial")
                    marker = terminal.send(b":wq\r")
                    assert b"\x1b[?1049l" not in terminal.transcript[marker:]
                    terminal.wait_for_screen("OWNED-SHELL> ")
                    marker = terminal.send(b"cat /tmp/owned-shell-trial\n")
                    terminal.wait_for_screen("OWNED_REMOTE_EDIT")
                    marker = terminal.send(b"printf 'SLEEP_%s\\n' READY; sleep 30\n")
                    terminal.wait_for_screen("SLEEP_READY")
                    terminal.send(b"\x03")
                    terminal.wait_for_screen("OWNED-SHELL> ")
                    marker = terminal.send(b"printf 'AFTER_%s\\n' \"$KUBETROL_OWNED_CONTAINER\"\n")
                    terminal.wait_for_screen("AFTER_app-b")
                marker = terminal.send(b"exit\n")
                terminal.wait_for(b"Shell closed", since=marker)
                terminal.resize(100, 30)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Sort NAME", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for(b"Containers", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Sort NAME", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("kind-shell-" + scenario)
    finally:
        path.write_bytes(before)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--evidence", default="artifacts/cluster/shell.json")
    arguments = parser.parse_args()
    kubectl = Path(arguments.kubectl).absolute()
    version = json.loads(
        subprocess.check_output([str(kubectl), "version", "--client", "-o", "json"])
    )["clientVersion"]["gitVersion"]
    assert version == "v1.36.4", "Use the matching verified kubectl 1.36.4 binary for this trial."
    name = "kubetrol-test-" + uuid4().hex[:12]
    namespace = "kubetrol-shell-test"
    with TemporaryDirectory(prefix="kubetrol-shell-kind-") as folder:
        directory = Path(folder)
        path = directory / "owned-kubeconfig"
        environment = {**os.environ, "KUBECONFIG": str(path)}
        try:
            print("Creating owned disposable kind cluster.", flush=True)
            subprocess.run(
                [
                    arguments.kind,
                    "create",
                    "cluster",
                    "--name",
                    name,
                    "--kubeconfig",
                    str(path),
                    "--image",
                    NODE_IMAGE,
                    "--wait",
                    "180s",
                ],
                env=environment,
                check=True,
                timeout=300,
            )
            data = yaml.safe_load(path.read_text())
            context = "kind-" + name
            assert data["current-context"] == context
            data["contexts"].append(
                {"name": "kubetrol-test-Alias", "context": dict(data["contexts"][0]["context"])}
            )
            context = "kubetrol-test-Alias"
            path.write_text(yaml.safe_dump(data))
            print("Preparing owned two-container shell and limited-RBAC fixtures.", flush=True)
            resource, token = asyncio.run(prepare(path, context, namespace))
            for scenario in ["success", "configured", "missing-shell"]:
                trial(
                    path,
                    context,
                    namespace,
                    directory / scenario,
                    scenario=scenario,
                    kubectl=kubectl,
                )
                print("Real shell trial passed: " + scenario, flush=True)
            limited = yaml.safe_load(path.read_text())
            limited["users"] = [{"name": "shell-reader", "user": {"token": token}}]
            for value in limited["contexts"]:
                value["context"]["user"] = "shell-reader"
            restricted = directory / "restricted-config"
            restricted.write_text(yaml.safe_dump(limited))
            restricted.chmod(0o600)
            trial(
                restricted,
                context,
                namespace,
                directory / "denied",
                scenario="denied",
                kubectl=kubectl,
            )
            output = Path(arguments.evidence)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "result": "passed",
                        "kind": "0.33.0",
                        "kubernetes": "1.36.4",
                        "kubectl": version,
                        "node_image": NODE_IMAGE,
                        "shell_image": SHELL_IMAGE,
                        "owned_cluster": name,
                        "resource": resource,
                        "real_two_container_selection": True,
                        "embedded_shell_and_persistent_captured_heading": True,
                        "configured_shell": True,
                        "changed_source_config_does_not_retarget": True,
                        "real_keyboard_resize_ctrl_c": True,
                        "real_fullscreen_vi": True,
                        "repeated_shell_return": True,
                        "missing_shell_actionable": True,
                        "real_rbac_exec_denial": True,
                        "terminal_restored": True,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                "Real Kubernetes shell, fullscreen program, permissions and return passed.",
                flush=True,
            )
        finally:
            subprocess.run(
                [arguments.kind, "delete", "cluster", "--name", name],
                env=environment,
                check=True,
                timeout=90,
            )
            print("Owned disposable cluster deleted.", flush=True)


if __name__ == "__main__":
    main()
