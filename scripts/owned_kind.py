"""Explicit local kind ownership, pre-write identity and cancellation cleanup."""

import json
import os
import signal
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FrameType
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import yaml

NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)


def run_owned(argv: Sequence[str], environment: Mapping[str, str], timeout: float = 30) -> str:
    """Bound and reap an owned process group, including on signal cancellation."""
    with subprocess.Popen(
        argv, env=dict(environment), stdout=subprocess.PIPE, text=True, start_new_session=True
    ) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, argv)
            return output
        except BaseException:
            for signum in (signal.SIGTERM, signal.SIGKILL):
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signum)
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    continue
                # Reap descendants even when the foreground leader exited first.
                if signum == signal.SIGTERM:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                break
            process.wait(timeout=5)
            raise


def local_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "unix"
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
        or "\x00" in endpoint
    ):
        raise ValueError("Integration requires an explicit local Docker Unix socket.")
    return endpoint


def docker_environment(environment: Mapping[str, str], endpoint: str) -> dict[str, str]:
    captured = {
        key: value
        for key, value in environment.items()
        if key
        not in {
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
    }
    captured.update(DOCKER_HOST=local_endpoint(endpoint), KIND_EXPERIMENTAL_PROVIDER="docker")
    return captured


def verified_nodes(nodes: list[dict[str, Any]], name: str) -> tuple[str, ...]:
    identities = []
    for node in nodes:
        labels = node["Config"].get("Labels", {})
        if (
            labels.get("io.x-k8s.kind.cluster") != name
            or labels.get("io.x-k8s.kind.role") != "control-plane"
            or node["Config"]["Image"] != NODE_IMAGE
            or not isinstance(node["Id"], str)
            or not node["Id"]
        ):
            raise ValueError("Refusing an unverified disposable node.")
        identities.append(node["Id"])
    if len(identities) > 1 or len(set(identities)) != len(identities):
        raise ValueError("Unexpected disposable cluster membership.")
    return tuple(identities)


def verify_config(path: Path, name: str, nodes: list[dict[str, Any]]) -> str:
    """Bind the generated API endpoint to the actual owned Docker node."""
    if len(verified_nodes(nodes, name)) != 1:
        raise ValueError("Disposable cluster needs one verified control plane.")
    data = yaml.safe_load(path.read_text())
    context = "kind-" + name
    if (
        data.get("current-context") != context
        or len(data.get("contexts", [])) != 1
        or len(data.get("clusters", [])) != 1
        or len(data.get("users", [])) != 1
        or data["contexts"][0]["name"] != context
    ):
        raise ValueError("Unexpected generated disposable kubeconfig.")
    selected = data["contexts"][0]["context"]
    cluster, user = data["clusters"][0], data["users"][0]
    if selected["cluster"] != cluster["name"] or selected["user"] != user["name"]:
        raise ValueError("Disposable references do not match.")
    credentials = user["user"]
    if set(credentials) != {"client-certificate-data", "client-key-data"}:
        raise ValueError("Disposable credentials must be generated certificates.")
    settings = cluster["cluster"]
    if set(settings) != {"certificate-authority-data", "server"}:
        raise ValueError("Unexpected disposable TLS configuration.")
    server = urlsplit(settings["server"])
    ports = nodes[0]["NetworkSettings"]["Ports"].get("6443/tcp") or []
    if (
        server.scheme != "https"
        or server.hostname != "127.0.0.1"
        or server.username
        or server.password
        or server.path
        or server.query
        or server.fragment
        or not any(
            p["HostIp"] == server.hostname and p["HostPort"] == str(server.port) for p in ports
        )
    ):
        raise ValueError("Disposable API endpoint does not match its owned node.")
    return context


@dataclass(frozen=True)
class OwnedCluster:
    name: str
    path: Path
    directory: Path
    context: str
    node_ids: tuple[str, ...]


def capture_docker(docker: str = "docker") -> dict[str, str]:
    """Resolve local metadata once, then freeze the Docker destination."""
    inherited = dict(os.environ)
    if inherited.get("DOCKER_CONTEXT") or not inherited.get("DOCKER_HOST"):
        argv = [docker, "context", "inspect"]
        if inherited.get("DOCKER_CONTEXT"):
            argv.append(inherited["DOCKER_CONTEXT"])
        endpoint = json.loads(
            run_owned([*argv, "--format", "{{json .Endpoints.docker.Host}}"], inherited)
        )
    else:
        endpoint = inherited["DOCKER_HOST"]
    return docker_environment(inherited, endpoint)


@contextmanager
def owned_cluster(kind: str, *, docker: str = "docker") -> Iterator[OwnedCluster]:
    """Create no cluster until ownership is explicit; delete only the owned one."""
    environment = capture_docker(docker)
    if not run_owned([kind, "version"], environment).startswith("kind v0.33.0 "):
        raise ValueError("Use verified kind v0.33.0.")
    name = "kubetrol-test-" + uuid4().hex

    def inspect() -> list[dict[str, Any]]:
        ids = run_owned(
            [
                docker,
                "ps",
                "--all",
                "--filter",
                "label=io.x-k8s.kind.cluster=" + name,
                "--format",
                "{{.ID}}",
            ],
            environment,
        ).splitlines()
        if not ids:
            return []
        result: list[dict[str, Any]] = json.loads(run_owned([docker, "inspect", *ids], environment))
        return result

    if inspect():
        raise ValueError("Refusing to adopt an existing disposable cluster.")
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    def cancel(signum: int, frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    with TemporaryDirectory(prefix="kubetrol-owned-kind-") as temporary:
        directory = Path(temporary)
        path = directory / "owned-kubeconfig"
        environment["KUBECONFIG"] = str(path)
        identities: tuple[str, ...] | None = None
        for signum in previous:
            signal.signal(signum, cancel)
        try:
            print("Creating owned disposable kind cluster: " + name, flush=True)
            run_owned(
                [
                    kind,
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
                environment,
                timeout=300,
            )
            nodes = inspect()
            identities = verified_nodes(nodes, name)
            context = verify_config(path, name, nodes)
            path.chmod(0o600)
            yield OwnedCluster(name, path, directory, context, identities)
        finally:
            # A second cancellation must not interrupt deletion or signal restoration.
            for signum in previous:
                signal.signal(signum, signal.SIG_IGN)
            try:
                current = verified_nodes(inspect(), name)
                if identities is not None and current and current != identities:
                    raise ValueError("Owned node identity changed; refusing deletion.")
                if current:
                    run_owned(
                        [kind, "delete", "cluster", "--name", name, "--kubeconfig", str(path)],
                        environment,
                        timeout=90,
                    )
                if inspect():
                    raise ValueError("Owned cluster remained after cleanup.")
                print("Owned disposable cluster deleted and absence verified.", flush=True)
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
