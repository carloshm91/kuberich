"""Execute exact native bytes outside the checkout with owned API/auth/PTY fixtures."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.check_standalone import inspect_bundle, inspect_candidate
from scripts.owned_kind import capture_docker
from scripts.standalone import native_target
from scripts.supply_chain import digest
from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = "ubuntu@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02"


def write_original(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


class Host:
    def __init__(self, bundle: Path, directory: Path, evidence: Path) -> None:
        self.bundle, self.directory, self.evidence = bundle, directory, evidence
        self.linux = platform.system() == "Linux"
        self.names: set[str] = set()
        self.environment = dict(os.environ)
        self.profile: Path | None = None
        self.docker: list[str] = []
        if self.linux:
            docker = shutil.which("docker")
            if docker is None:
                raise ValueError(
                    "Linux native verification needs the controller's Docker executable"
                )
            self.environment = capture_docker(docker)
            self.docker = [docker, "--host", self.environment["DOCKER_HOST"]]
        else:
            # The controller may use Python; the application cannot exec any outside interpreter
            # or read this checkout/venv. This is process isolation, not physical host absence.
            allowed = [
                bundle / "kuberich",
                directory / "tools/owned-auth",
                directory / "tools/kubectl",
                Path("/bin/sh"),
            ]
            predicates = " ".join("(literal " + json.dumps(str(path)) + ")" for path in allowed)
            denied = {ROOT.resolve(), Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
            paths = " ".join("(subpath " + json.dumps(str(path)) + ")" for path in sorted(denied))
            self.profile = directory / "native.sb"
            self.profile.write_text(
                "(version 1)\n(allow default)\n"
                + f"(deny process-exec (require-not (require-any {predicates})))\n"
                + f"(deny file-read* {paths})\n"
            )

    @property
    def executable(self) -> str:
        return "/app/kuberich" if self.linux else str(self.bundle / "kuberich")

    def command(
        self, argv: list[str], environment: dict[str, str], *, tty: bool = False
    ) -> list[str]:
        if not self.linux:
            assert self.profile is not None
            return ["/usr/bin/sandbox-exec", "-f", str(self.profile), *argv]
        name = "kuberich-native-49-" + uuid4().hex
        self.names.add(name)
        command = [*self.docker, "run", "--rm", "--name", name, "--label", "io.kuberich.issue=49"]
        if tty:
            command.append("-it")
        command.extend(
            [
                "--network",
                "host",
                "--mount",
                f"type=bind,src={self.bundle},dst=/app,readonly",
                "--mount",
                f"type=bind,src={self.directory},dst={self.directory}",
            ]
        )
        for key, value in sorted(environment.items()):
            command.extend(["--env", key + "=" + value])
        return [*command, BASE_IMAGE, *argv]

    def observe(
        self, name: str, argv: list[str], environment: dict[str, str], *, success: bool = True
    ) -> str:
        command = self.command(argv, environment)
        actual_environment = {**self.environment, **environment}
        result = subprocess.run(
            command,
            cwd=self.directory,
            env=actual_environment,
            capture_output=True,
            text=True,
            timeout=45,
        )
        write_original(
            self.evidence / (name + ".json"),
            {
                "argv": command,
                "cwd": str(self.directory),
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        if (result.returncode == 0) != success:
            raise ValueError("Native host control failed: " + name)
        return result.stdout

    def close(self) -> None:
        for name in self.names:
            subprocess.run(
                [*self.docker, "rm", "-f", name],
                env=self.environment,
                capture_output=True,
                timeout=30,
                check=False,
            )
        if self.docker:
            result = subprocess.run(
                [*self.docker, "ps", "--all", "--format", "{{.Names}}"],
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            if self.names.intersection(result.stdout.splitlines()):
                raise ValueError("Owned standalone containers were not removed")


def environment(directory: Path, *, helpers: bool, bundle: str) -> dict[str, str]:
    return {
        "HOME": str(directory),
        "PATH": str(directory.parent / "tools") if helpers else str(directory / "no-tools"),
        "TERM": "xterm-256color",
        "KUBERICH_CONFIG": str(directory / "preferences.yaml"),
        "KUBERICH_LOG_FILE": str(directory / "kuberich.log"),
        "KUBECONFIG": str(directory / "never-use-a-real-cluster"),
        "OWNED_NATIVE_EVIDENCE": str(directory),
        "OWNED_NATIVE_BUNDLE": bundle,
    }


def browser(host: Host, directory: Path, evidence: Path, *, helpers: bool) -> dict[str, Any]:
    directory.mkdir()
    (directory / "preferences.yaml").write_text("schema_version: 1\n")
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    server.shell_containers = ("worker",)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        user: dict[str, Any] = {"token": "synthetic-pty"}
        if helpers:
            user = {
                "exec": {
                    "apiVersion": "client.authentication.k8s.io/v1",
                    "command": str(directory.parent / "tools/owned-auth"),
                    "args": [str(directory / "auth-called")],
                    "interactiveMode": "Never",
                    "provideClusterInfo": True,
                }
            }
        kubeconfig = config(
            directory / "kubeconfig", f"http://127.0.0.1:{server.server_port}", user
        )
        before = kubeconfig.read_bytes()
        overrides = environment(
            directory, helpers=helpers, bundle="/app" if host.linux else str(host.bundle)
        )
        argv = [host.executable, "--kubeconfig", str(kubeconfig), "--context", "kuberich-test-pty"]
        command = host.command(argv, overrides, tty=True)
        with TerminalSession(
            command, directory, environment={**host.environment, **overrides}
        ) as terminal:
            terminal.wait_for(b"80 pods", timeout=30)
            if helpers:
                assert "native auth helper called" in (directory / "auth-called").read_text()
            marker = terminal.send(b"\x1b[1;5F")
            terminal.wait_for(b"owned-pty-pod-079", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("Containers", since=marker)
            terminal.wait_for_screen("worker", since=marker)
            terminal.send(b"\x1b[B")
            if helpers:
                terminal.send(b"s")
                terminal.wait_for_screen("SHELL CHILD START", timeout=30)
                assert "private snapshot" in (directory / "exec-called").read_text()
                terminal.send(b"printf 'NATIVE_SHELL_OUTPUT_%s\\n' 17\n")
                terminal.wait_for_screen("NATIVE_SHELL_OUTPUT_17")
                marker = terminal.send(b"exit\n")
                terminal.wait_for(b"Shell closed", since=marker)
                terminal.wait_for_screen("Containers", absent=("Container shell",))
            else:
                marker = terminal.send(b"s")
                terminal.wait_for(b"Install kubectl", since=marker)
                assert b"SHELL CHILD START" not in terminal.transcript
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("Sort NAME", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            name = "standalone-" + native_target() + ("-auth-exec" if helpers else "-missing-tool")
            terminal.save_evidence(name)
            assert b"synthetic-pty" not in terminal.transcript
        assert kubeconfig.read_bytes() == before
        original = ROOT / "artifacts/terminal" / (name + ".json")
        retained = evidence / (name + ".json")
        shutil.copyfile(original, retained)
        receipt = json.loads(retained.read_text())
        if (
            receipt["exit"] != 0
            or not receipt["terminal_mode_restored"]
            or not receipt["alternate_screen_closed"]
            or not receipt["cursor_restored"]
            or not all(receipt["reporting_modes_disabled"].values())
        ):
            raise ValueError("Native PTY did not restore its caller's terminal")
        return {
            "receipt": retained.name,
            "sha256": digest(retained),
            "caller_kubeconfig_unchanged": True,
        }
    finally:
        server.stopping.set()
        server.pod_gate.set()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        if thread.is_alive():
            raise ValueError("Owned standalone API was not reaped")


def verify(source: Path, candidate: Path, evidence: Path) -> dict[str, Any]:
    manifest = inspect_candidate(source, candidate)
    if manifest["target"] != native_target():
        raise ValueError("Native qualification must execute on its actual OS/architecture")
    evidence.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="kuberich-native-runtime-") as temporary:
        directory = Path(temporary).resolve()
        with tarfile.open(candidate / manifest["archive"]["name"], "r:gz") as archive:
            archive.extractall(directory / "unpacked", filter="data")
        bundle = directory / "unpacked/kuberich"
        native = inspect_bundle(bundle, manifest)
        tools = directory / "tools"
        tools.mkdir()
        helper = tools / "owned-auth"
        compilation = subprocess.run(
            [
                "cc",
                "-std=c99",
                "-Wall",
                "-Wextra",
                "-Werror",
                *(["-static"] if platform.system() == "Linux" else []),
                str(ROOT / "tests/support/native_helper.c"),
                "-o",
                str(helper),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        write_original(
            evidence / "helper-compiler.json",
            {
                "exit": compilation.returncode,
                "stdout": compilation.stdout,
                "stderr": compilation.stderr,
            },
        )
        compilation.check_returncode()
        shutil.copyfile(helper, tools / "kubectl")
        (tools / "kubectl").chmod(0o755)
        host = Host(bundle, directory, evidence)
        try:
            cli = directory / "cli"
            cli.mkdir()
            (cli / "preferences.yaml").write_text("schema_version: 1\n")
            overrides = environment(
                cli, helpers=False, bundle="/app" if host.linux else str(bundle)
            )
            if host.linux:
                packages = host.observe(
                    "installed-packages", ["/usr/bin/dpkg-query", "-W"], overrides
                )
                if any("python" in line.split()[0].lower() for line in packages.splitlines()):
                    raise ValueError("Clean native base contains a system Python package")
                host.observe(
                    "missing-system-tools",
                    [
                        "/bin/sh",
                        "-ec",
                        "PATH=/usr/bin:/bin; for tool in python python3 uv pip pip3 kubectl; do if command -v $tool; then exit 1; fi; done",
                    ],
                    overrides,
                )
                glibc = host.observe("actual-glibc", ["/usr/bin/ldd", "--version"], overrides)
                if "2.35" not in glibc:
                    raise ValueError("Native clean host does not match the recorded GLIBC floor")
            else:
                host.observe(
                    "external-python-denied",
                    [sys.executable, "-c", "raise SystemExit(0)"],
                    overrides,
                    success=False,
                )
                host.observe(
                    "system-python-denied",
                    ["/usr/bin/python3", "-c", "raise SystemExit(0)"],
                    overrides,
                    success=False,
                )
            version = host.observe("version", [host.executable, "--version"], overrides)
            if version.strip() != "kuberich " + manifest["version"]:
                raise ValueError("Native CLI version differs from archive metadata")
            host.observe("help", [host.executable, "--help"], overrides)
            info = json.loads(host.observe("info", [host.executable, "info"], overrides))
            if info["version"] != manifest["version"] or info["cluster_connected"] is not False:
                raise ValueError("Native info must report the artifact and avoid cluster access")
            missing = browser(host, directory / "missing", evidence, helpers=False)
            external = browser(host, directory / "external", evidence, helpers=True)
        finally:
            host.close()
        receipt = {
            "schema_version": 1,
            "source_commit": manifest["source_commit"],
            "target": manifest["target"],
            "archive": manifest["archive"]["name"],
            "archive_sha256": manifest["archive"]["sha256"],
            "actual_host": platform.platform(),
            "native": native,
            "system_python_absent": host.linux,
            "external_python_execution_denied": not host.linux,
            "linux_base_image": BASE_IMAGE if host.linux else None,
            "owned_helper_source_sha256": digest(ROOT / "tests/support/native_helper.c"),
            "owned_helper_sha256": digest(helper),
            "missing_optional_tool": missing,
            "auth_and_shell": external,
            "scope": "Exact extracted archive, native CLI, owned loopback API, C credential and kubectl fixtures with real /bin/sh. Not provider or real Kubernetes exec certification.",
            "runtime_qualified": False,
            "publication_performed": False,
        }
        if digest(candidate / manifest["archive"]["name"]) != manifest["archive"]["sha256"]:
            raise ValueError("Original native archive changed during execution")
        write_original(evidence / "host-runtime.json", receipt)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.source.absolute(), args.candidate.absolute(), args.evidence.absolute())
    print(
        json.dumps(
            {
                "target": receipt["target"],
                "archive_sha256": receipt["archive_sha256"],
                "runtime_qualified": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
