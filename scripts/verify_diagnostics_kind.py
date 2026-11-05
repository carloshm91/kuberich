"""Qualify native diagnostics and official Popeye inside one owned disposable kind."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import sysconfig
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.services.access import AccessPolicy
from kuberich.services.processes import ProcessRunner
from scripts.diagnostics_tools import (
    KIND_SHA256,
    RUNTIME_IMAGE,
    sha256_file,
    tool_provenance,
    verify_popeye_binary,
)
from scripts.owned_kind import (
    NODE_IMAGE,
    SHELL_IMAGE,
    OwnedCluster,
    capture_docker,
    owned_cluster,
    run_owned,
)

VERIFY_SECONDS = 600
OUTPUT_BYTES = 8 * 1024 * 1024
OWNER_LABEL = "io.kuberich.diagnostics-owner"


def input_hashes(root: Path) -> dict[str, str]:
    paths = [
        "scripts/verify_diagnostics_kind.py",
        "scripts/diagnostics_kind_runtime.py",
        "scripts/diagnostics_tools.py",
        "scripts/owned_kind.py",
        "uv.lock",
        "pyproject.toml",
        "tests/fixtures/popeye/0.22.1/official-provenance.json",
    ]
    paths.extend(str(path.relative_to(root)) for path in (root / "src/kuberich").rglob("*.py"))
    return {path: sha256_file(root / path) for path in sorted(paths)}


def prerequisites(kind: Path, popeye: Path | None) -> None:
    if sys.version_info[:2] != (3, 12) or sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError(
            "This contained qualification requires Linux amd64 CPython3.12; other platforms remain separate evidence."
        )
    if not kind.is_absolute() or sha256_file(kind) != KIND_SHA256:
        raise ValueError("Use the official checksum-verified kind0.33.0 Linux amd64 fixture.")
    if popeye is None:
        raise ValueError(
            "Official Popeye binary is a required qualification prerequisite; use scripts.diagnostics_tools."
        )
    verify_popeye_binary(popeye)


def container_argv(
    docker: str,
    cluster: OwnedCluster,
    root: Path,
    sites: Path,
    binary: Path,
    evidence: Path,
    passwd: Path,
    nonce: str,
    uid: int,
    gid: int,
) -> list[str]:
    """Mount only owned connection/evidence/runtime inputs, never the account home."""
    argv = [
        docker,
        "create",
        "--name",
        "kuberich-diagnostics-" + nonce,
        "--label",
        OWNER_LABEL + "=" + nonce,
        "--network=host",
        "--read-only",
        "--user",
        f"{uid}:{gid}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=256",
        "--memory=1g",
        "--workdir=/owned/home",
        "--tmpfs",
        f"/owned/home:rw,nosuid,nodev,mode=0700,uid={uid},gid={gid},size=64m",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,mode=1777,size=128m",
        "--env=HOME=/owned/home",
        "--env=USER=popeye-owned",
        "--env=PYTHONDONTWRITEBYTECODE=1",
        "--env=PYTHONPATH=/source/src:/source:/runtime-site",
        "--env=KUBECONFIG=/fixture/kubeconfig",
    ]
    for source, target, readonly in (
        (root / "src", "/source/src", True),
        (root / "scripts", "/source/scripts", True),
        (sites, "/runtime-site", True),
        (binary, "/owned/popeye", True),
        (cluster.path, "/fixture/kubeconfig", True),
        (passwd, "/etc/passwd", True),
        (evidence, "/evidence", False),
    ):
        argv.extend(
            (
                "--mount",
                f"type=bind,source={source},target={target}" + (",readonly" if readonly else ""),
            )
        )
    return [
        *argv,
        RUNTIME_IMAGE,
        "python",
        "-m",
        "scripts.diagnostics_kind_runtime",
        "--kubeconfig",
        "/fixture/kubeconfig",
        "--context",
        cluster.context,
        "--evidence",
        "/evidence",
        "--popeye",
        "/owned/popeye",
    ]


@contextmanager
def contained_runtime(
    argv: list[str],
    docker: str,
    environment: dict[str, str],
    nonce: str,
    receipt: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Remove only the captured labelled ID; stop it before credential/cluster teardown."""
    created: str | None = None

    def members(*, timeout: float = 30) -> list[str]:
        return run_owned(
            [
                docker,
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                "label=" + OWNER_LABEL + "=" + nonce,
                "--format",
                "{{.ID}}",
            ],
            environment,
            timeout=timeout,
        ).splitlines()

    if members():
        raise ValueError("Refusing to adopt an existing diagnostics runtime.")
    try:
        created = run_owned(argv, environment, timeout=60).strip()
        nodes = json.loads(run_owned([docker, "inspect", created], environment))
        if (
            len(nodes) != 1
            or nodes[0]["Id"] != created
            or nodes[0]["Config"]["Labels"].get(OWNER_LABEL) != nonce
            or nodes[0]["Config"]["Image"] != RUNTIME_IMAGE
            or not nodes[0]["HostConfig"]["ReadonlyRootfs"]
            or nodes[0]["HostConfig"]["NetworkMode"] != "host"
        ):
            raise ValueError(
                "Diagnostics container identity or containment differs from its captured request."
            )
        yield created
    finally:
        handlers = {value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)}
        for value in handlers:
            signal.signal(value, signal.SIG_IGN)
        try:
            current = members(timeout=5)
            if current:
                if created is None or current != [created]:
                    raise ValueError(
                        "Diagnostics container membership changed; refusing unrelated deletion."
                    )
                run_owned([docker, "rm", "--force", created], environment, timeout=5)
            if members(timeout=5):
                raise ValueError("Owned diagnostics container remained after cleanup.")
            if receipt is not None:
                receipt["container_deleted"] = True
        finally:
            for value, handler in handlers.items():
                signal.signal(value, handler)


async def attach(docker: str, identifier: str, environment: dict[str, str], evidence: Path) -> None:
    command = capture_command(
        (docker, "start", "--attach", identifier),
        environment=environment,
        directory=evidence,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.PLUGIN,
    )
    async with ProcessRunner(AccessPolicy(False), output_limit=OUTPUT_BYTES) as runner:
        result = await runner.capture(command, timeout=VERIFY_SECONDS)
    (evidence / "runtime-process.json").write_text(
        json.dumps(
            {
                "status": result.status.name,
                "returncode": result.returncode,
                "stdout": sanitize_text(
                    result.stdout.decode("utf-8", errors="replace"), allow_newlines=True
                ),
                "stderr": sanitize_text(
                    result.stderr.decode("utf-8", errors="replace"), allow_newlines=True
                ),
            },
            indent=2,
        )
        + "\n"
    )
    if result.status is not ProcessStatus.SUCCEEDED:
        raise ValueError(
            "Contained diagnostics runtime failed; inspect the retained original process/stage receipts."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--popeye", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.evidence.exists():
        raise ValueError("Use a fresh evidence path; earlier outcomes must remain intact.")
    args.evidence.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root, evidence = Path(__file__).resolve().parents[1], args.evidence.parent.resolve()
    inputs = input_hashes(root)
    initial_environment = dict(os.environ)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": inputs,
        "node_image": NODE_IMAGE,
        "tool_provenance": tool_provenance(),
        "runtime_image": RUNTIME_IMAGE,
        "container_deleted": False,
        "cluster_deleted": False,
        "private_directory_deleted": False,
    }
    started = time.monotonic()
    cluster: OwnedCluster | None = None
    problem: BaseException | None = None
    try:
        prerequisites(args.kind, args.popeye)
        assert args.popeye is not None
        environment = capture_docker(args.docker)
        inventory = run_owned(
            [args.docker, "ps", "--all", "--no-trunc", "--format", "{{.ID}}"], environment
        )
        result["initial_inventory_sha256"] = hashlib.sha256(inventory.encode()).hexdigest()
        for image in (RUNTIME_IMAGE, SHELL_IMAGE):
            try:
                run_owned(
                    [args.docker, "image", "inspect", image, "--format", "{{.Id}}"], environment
                )
            except subprocess.CalledProcessError:
                run_owned([args.docker, "pull", image], environment, timeout=180)
        with owned_cluster(
            str(args.kind),
            docker=args.docker,
            max_restart_period_seconds=2,
            sync_frequency_seconds=1,
        ) as cluster:
            result["cluster"] = cluster.name
            result["owned_node_ids"] = cluster.node_ids
            original_configuration = cluster.path.read_bytes()
            try:
                # This imports only the already pinned local fixture image into our verified node.
                run_owned(
                    [str(args.kind), "load", "docker-image", SHELL_IMAGE, "--name", cluster.name],
                    {**environment, "KUBECONFIG": str(cluster.path)},
                    timeout=120,
                )
                with TemporaryDirectory(prefix="kuberich-diagnostics-runtime-") as temporary:
                    passwd = Path(temporary) / "passwd"
                    uid, gid = os.getuid(), os.getgid()
                    passwd.write_text(
                        f"popeye-owned:x:{uid}:{gid}:Owned fixture:/owned/home:/sbin/nologin\n"
                    )
                    passwd.chmod(0o644)
                    nonce = uuid4().hex
                    argv = container_argv(
                        args.docker,
                        cluster,
                        root,
                        Path(sysconfig.get_path("purelib")),
                        args.popeye,
                        evidence,
                        passwd,
                        nonce,
                        uid,
                        gid,
                    )
                    with contained_runtime(
                        argv, args.docker, environment, nonce, result
                    ) as identifier:
                        result["owned_container_id"] = identifier
                        asyncio.run(attach(args.docker, identifier, environment, evidence))
                    result["container_deleted"] = True
                result["caller_kubeconfig_unchanged"] = (
                    cluster.path.read_bytes() == original_configuration
                )
                runtime = json.loads((evidence / "diagnostics-runtime.json").read_text())
                result["runtime"] = runtime
                if runtime["status"] != "passed":
                    raise ValueError(
                        "Actual runtime did not qualify every diagnostic/Popeye scenario."
                    )
            except BaseException as error:
                problem = error
                result["failure_type"] = type(error).__name__
            finally:
                result["caller_kubeconfig_unchanged"] = (
                    cluster.path.read_bytes() == original_configuration
                )
                runtime_path = evidence / "diagnostics-runtime.json"
                if runtime_path.exists():
                    result["runtime"] = json.loads(runtime_path.read_text())
        result["cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        if problem is not None:
            result["inputs_unchanged"] = input_hashes(root) == inputs
            result["environment_unchanged"] = dict(os.environ) == initial_environment
            raise problem
        after = run_owned(
            [args.docker, "ps", "--all", "--no-trunc", "--format", "{{.ID}}"], environment
        )
        result["unrelated_container_inventory_unchanged"] = sorted(
            inventory.splitlines()
        ) == sorted(after.splitlines())
        result["inputs_unchanged"] = input_hashes(root) == inputs
        result["environment_unchanged"] = dict(os.environ) == initial_environment
        assert all(
            result[key]
            for key in (
                "container_deleted",
                "cluster_deleted",
                "private_directory_deleted",
                "caller_kubeconfig_unchanged",
                "unrelated_container_inventory_unchanged",
                "inputs_unchanged",
                "environment_unchanged",
            )
        )
        result["status"] = "passed"
    except BaseException as error:
        if problem is not None and problem is not error:
            result["cleanup_failure_type"] = type(error).__name__
        result.setdefault("failure_type", type(error).__name__)
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual native diagnostics and contained official Popeye checks passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned diagnostics verification failed ({type(error).__name__}); retain original receipts.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
