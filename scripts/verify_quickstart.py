"""Install a real wheel and rehearse the guide outside the checkout on owned kind."""

import argparse
import hashlib
import json
import os
import shutil
import signal
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FrameType

import yaml

from scripts.owned_kind import SHELL_IMAGE, owned_cluster, run_owned
from tests.support.distribution import clean_environment
from tests.terminal.pty_support import TerminalSession

CONTEXT = "kuberich-quickstart"
ALIAS = "kuberich-quickstart-Alias"
NAMESPACE = "kuberich-quickstart"
POD = "quickstart-pod"


def terminal_trial(
    command: list[str], directory: Path, environment: dict[str, str], *, readonly: bool
) -> None:
    directory.mkdir()
    (directory / "preferences.yaml").write_text("schema_version: 1\nread_only: true\n")
    flag = "--readonly" if readonly else "--write"
    with TerminalSession([*command, flag], directory, environment=environment) as terminal:
        terminal.wait_for_screen(POD, timeout=45)
        if readonly:
            marker = terminal.send(b":ctx\r")
            terminal.wait_for_screen(ALIAS, since=marker)
            marker = terminal.send((":ctx " + ALIAS + "\r").encode())
            terminal.wait_for_screen(POD, since=marker)
            terminal.wait_for_screen(ALIAS)
            marker = terminal.send(b":ns\r")
            terminal.wait_for_screen("Namespaces", since=marker)
            marker = terminal.send(b"/kuberich-quickstart\r")
            # The same name is already in the header. Observe the actual filtered
            # table row before Enter, rather than a pre-list header projection.
            terminal.wait_for_screen(NAMESPACE, row=13, since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for_screen(POD, since=marker)
            marker = terminal.send(b"/quickstart\r")
            terminal.wait_for_screen("Clear filter", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(POD, since=marker, absent=("Clear filter",))
            marker = terminal.send(b"d")
            terminal.wait_for_screen("Details", since=marker)
            terminal.wait_for_screen("scheduling:", since=marker)
            marker = terminal.send(b"y")
            terminal.wait_for_screen("Yaml ·", since=marker)
            terminal.wait_for_screen("kind: Pod", since=marker)
            marker = terminal.send(b"e")
            terminal.wait_for_screen("Events ·", since=marker)
            marker = terminal.send(b"\x1b")
            # Wait for Escape's terminal sequence and the completed return before
            # sending Enter; adjacent ESC/CR bytes otherwise form Alt+Enter.
            terminal.wait_for_screen("Sort NAME", since=marker)
        marker = terminal.send(b"\r")
        terminal.wait_for_screen("Containers", since=marker)
        terminal.wait_for_screen("sidecar", since=marker)
        if readonly:
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("KUBERICH_PREVIEW_LOG", since=marker, timeout=30)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("Containers", since=marker)
            terminal.wait_for_screen("sidecar", since=marker)
            marker = terminal.send(b"s")
            terminal.wait_for_screen("Read-only mode blocks", since=marker)
        else:
            marker = terminal.send(b"s")
            terminal.wait_for_screen("KubeRich · Container shell", since=marker)
            terminal.wait_for_screen("PREVIEW> ", timeout=30)
            marker = terminal.send(b"printf 'QUICKSTART_%s\\n' OK\n")
            terminal.wait_for_screen("QUICKSTART_OK", since=marker)
            marker = terminal.send(b"exit\n")
            terminal.wait_for_screen("Shell closed", since=marker)
            marker = terminal.send(b"s")
            terminal.wait_for_screen("PREVIEW> ", since=marker, timeout=30)
            marker = terminal.send(b"\x1d")
            terminal.wait_for_screen("Shell closed", since=marker)
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("quickstart-installed-" + ("readonly" if readonly else "write"))


def verify(wheel: Path, kind: str, kubectl: Path, evidence: Path) -> None:
    wheel, kubectl, evidence = (
        wheel.resolve(strict=True),
        kubectl.resolve(strict=True),
        evidence.absolute(),
    )
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("uv is required for the owned installer trial.")
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(
            archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA")))
        )
    if metadata["Name"] != "kuberich" or not metadata["Version"]:
        raise ValueError("Use an actual KubeRich wheel.")
    version = str(metadata["Version"])
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    original_directory = Path.cwd()

    def cancel(signum: int, frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    for signum in previous:
        signal.signal(signum, cancel)
    try:
        with TemporaryDirectory(prefix="kuberich-quickstart-") as temporary:
            directory = Path(temporary)
            outside = directory / "outside"
            outside.mkdir()
            os.chdir(outside)
            environment = clean_environment(directory)
            environment["HOME"] = str(directory / "home")
            Path(environment["HOME"]).mkdir()
            environment["PATH"] = str(kubectl.parent) + os.pathsep + environment.get("PATH", "")
            preferences = directory / "preferences.yaml"
            preferences.write_text("schema_version: 1\nread_only: true\n")
            before = preferences.read_bytes()
            run_owned(
                [uv, "tool", "install", "--python", sys.executable, str(wheel)],
                environment,
                timeout=180,
            )
            executable = Path(environment["UV_TOOL_BIN_DIR"]) / "kuberich"
            if (
                run_owned([str(executable), "--version"], environment)
                != "kuberich " + version + "\n"
            ):
                raise ValueError("Installed version differs from the candidate.")
            help_text = run_owned([str(executable), "--help"], environment)
            if "--context" not in help_text or "embedded container shells" not in help_text:
                raise ValueError("Installed help does not describe the current guide.")
            run_owned([str(executable), "config", "check"], environment)
            info = json.loads(run_owned([str(executable), "info"], environment))
            if info["version"] != version or not info["preferences"]["read_only"]:
                raise ValueError("Installed info/preferences do not match.")
            client = json.loads(
                run_owned([str(kubectl), "version", "--client", "-o", "json"], environment)
            )
            if client["clientVersion"]["gitVersion"] != "v1.36.4":
                raise ValueError("Use verified kubectl 1.36.4 for this fixture.")
            with owned_cluster(kind) as cluster:
                data = yaml.safe_load(cluster.path.read_text())
                for name in (CONTEXT, ALIAS):
                    data["contexts"].append(
                        {"name": name, "context": dict(data["contexts"][0]["context"])}
                    )
                cluster.path.write_text(yaml.safe_dump(data))
                base = [
                    str(kubectl),
                    "--kubeconfig",
                    str(cluster.path),
                    "--context",
                    cluster.context,
                ]
                run_owned([*base, "create", "namespace", NAMESPACE], environment)
                pod = {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": POD, "namespace": NAMESPACE},
                    "spec": {
                        "containers": [
                            {
                                "name": name,
                                "image": SHELL_IMAGE,
                                "command": [
                                    "/bin/sh",
                                    "-c",
                                    "echo KUBERICH_PREVIEW_LOG; while true; do sleep 60; done",
                                ],
                                "env": [{"name": "PS1", "value": "PREVIEW> "}],
                            }
                            for name in ("app", "sidecar")
                        ]
                    },
                }
                manifest = outside / "pod.yaml"
                manifest.write_text(yaml.safe_dump(pod))
                run_owned([*base, "apply", "-f", str(manifest)], environment)
                run_owned(
                    [
                        *base,
                        "-n",
                        NAMESPACE,
                        "wait",
                        "pod/" + POD,
                        "--for=condition=Ready",
                        "--timeout=180s",
                    ],
                    environment,
                    timeout=200,
                )
                command = [
                    str(executable),
                    "--kubeconfig",
                    str(cluster.path),
                    "--context",
                    CONTEXT,
                    "--namespace",
                    NAMESPACE,
                ]
                for readonly in (True, False):
                    terminal_trial(
                        command,
                        outside / ("readonly" if readonly else "write"),
                        environment,
                        readonly=readonly,
                    )
            run_owned([uv, "tool", "uninstall", "kuberich"], environment)
            if executable.exists() or preferences.read_bytes() != before:
                raise ValueError("Uninstall did not preserve preferences/remove the executable.")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(
                json.dumps(
                    {
                        "result": "passed",
                        "version": version,
                        "wheel_sha256": digest,
                        "python": sys.version.split()[0],
                        "installed_outside_checkout": True,
                        "context_alias_switch": True,
                        "namespace_enter_pods": True,
                        "details_yaml_events": True,
                        "container_logs": True,
                        "readonly_shell_refused": True,
                        "write_override_embedded_shell": True,
                        "shell_exit_and_ctrl_bracket_return": True,
                        "terminal_restored": True,
                        "uninstalled_preferences_preserved": True,
                        "publications": 0,
                    },
                    indent=2,
                )
                + "\n"
            )
    finally:
        os.chdir(original_directory)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--kind", required=True, type=Path)
    parser.add_argument("--kubectl", required=True, type=Path)
    parser.add_argument("--evidence", default="artifacts/quickstart/installed.json", type=Path)
    arguments = parser.parse_args()
    verify(
        arguments.wheel,
        str(arguments.kind.resolve(strict=True)),
        arguments.kubectl,
        arguments.evidence,
    )


if __name__ == "__main__":
    main()
