"""S07 actual owned attach and bounded kubectl file round trips; never ambient contexts."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.transfers import TransferDirection
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.transfers import TransferService
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster, run_owned
from tests.terminal.pty_support import TerminalSession

NAMESPACE = "kuberich-owned-transfers"
POD = "owned-transfer-pod"


async def verify(cluster: OwnedCluster, kubectl: str) -> dict[str, Any]:
    selected = load_catalog(
        ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context), {}
    ).select(cluster.context)
    connection = KubernetesSession(selected, 15)
    before = cluster.path.read_bytes()
    environment = {
        **os.environ,
        "PATH": str(Path(kubectl).absolute().parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    checks = []
    pending: list[asyncio.Task[str]] = []
    try:
        await connection.open()
        assert connection.api is not None
        core = client.CoreV1Api(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
        )
        await core.create_namespaced_pod(
            NAMESPACE,
            client.V1Pod(
                metadata=client.V1ObjectMeta(name=POD),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    volumes=[
                        client.V1Volume(name="shared", empty_dir=client.V1EmptyDirVolumeSource())
                    ],
                    init_containers=[
                        client.V1Container(
                            name="init",
                            image=SHELL_IMAGE,
                            restart_policy="Always",
                            command=["/bin/sleep", "3600"],
                        )
                    ],
                    containers=[
                        client.V1Container(
                            name="app",
                            image=SHELL_IMAGE,
                            command=["/bin/sh", "-i"],
                            stdin=True,
                            tty=True,
                            env=[client.V1EnvVar(name="PS1", value="OWNED-ATTACH> ")],
                            volume_mounts=[client.V1VolumeMount(name="shared", mount_path="/tmp")],
                        ),
                        client.V1Container(
                            name="no-tar",
                            image=SHELL_IMAGE,
                            command=["/bin/sleep", "3600"],
                            env=[client.V1EnvVar(name="PATH", value="/owned-missing-binaries")],
                        ),
                        client.V1Container(
                            name="slow-copy",
                            image=SHELL_IMAGE,
                            command=["/bin/sleep", "3600"],
                            env=[
                                client.V1EnvVar(
                                    name="PATH",
                                    value="/tmp/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                                )
                            ],
                            volume_mounts=[client.V1VolumeMount(name="shared", mount_path="/tmp")],
                        ),
                    ],
                ),
            ),
        )
        async with asyncio.timeout(120):
            while True:
                value = await core.read_namespaced_pod(POD, NAMESPACE)
                statuses = value.status.container_statuses or []
                if len(statuses) == 3 and all(item.state.running is not None for item in statuses):
                    break
                await asyncio.sleep(0.2)
        uid = value.metadata.uid
        await core.patch_namespaced_pod_ephemeralcontainers(
            POD,
            NAMESPACE,
            {
                "spec": {
                    "ephemeralContainers": [
                        {
                            "name": "debug",
                            "image": SHELL_IMAGE,
                            "command": ["/bin/sleep", "3600"],
                            "targetContainerName": "app",
                        }
                    ]
                }
            },
        )
        async with asyncio.timeout(60):
            while True:
                value = await core.read_namespaced_pod(POD, NAMESPACE)
                if (
                    value.status.ephemeral_container_statuses
                    and value.status.ephemeral_container_statuses[0].state.running is not None
                ):
                    break
                await asyncio.sleep(0.2)
        target = ResourceTarget(
            SessionIdentity(cluster.context, 1), "", "pods", NAMESPACE, POD, uid
        )
        local = cluster.directory / "copy-fixtures"
        local.mkdir()

        def service(readonly: bool = False) -> TransferService:
            return TransferService(
                connection,
                target,
                AccessPolicy(readonly),
                lambda: True,
                environment=environment,
                directory=cluster.directory,
            )

        async def transfer(
            direction: TransferDirection,
            container: str,
            path: Path,
            remote: str,
            *,
            overwrite: bool = False,
        ) -> str:
            owner = service(direction is TransferDirection.DOWNLOAD)
            review = await owner.prepare(
                direction, container, str(path), remote, overwrite=overwrite
            )
            message = await owner.execute(review)
            assert not review.connection.path.exists() and not Path(review.temporary.name).exists()
            return message

        for container in ("app", "init", "debug"):
            source = local / ("source-" + container)
            source.write_bytes(bytes(range(256)) * 127)
            remote = "/tmp/space " + container + ".bin"
            assert "complete" in await transfer(TransferDirection.UPLOAD, container, source, remote)
            output = local / ("result-" + container)
            assert "complete" in await transfer(
                TransferDirection.DOWNLOAD, container, output, remote
            )
            assert output.read_bytes() == source.read_bytes()
            checks.append("actual-binary-space-roundtrip-" + container)
        large = local / "large-source"
        large.write_bytes(bytes(range(256)) * 32768)
        assert "complete" in await transfer(
            TransferDirection.UPLOAD, "app", large, "/tmp/large.bin"
        )
        output = local / "large-result"
        assert "complete" in await transfer(
            TransferDirection.DOWNLOAD, "app", output, "/tmp/large.bin"
        )
        assert output.read_bytes() == large.read_bytes()
        checks.append("actual-8MiB-streaming-roundtrip")
        directory = local / "source-tree"
        directory.mkdir()
        (directory / "empty").mkdir()
        (directory / "space café.bin").write_bytes(b"owned\x00binary")
        assert "complete" in await transfer(
            TransferDirection.UPLOAD, "app", directory, "/tmp/owned-tree"
        )
        output = local / "download-tree"
        assert "complete" in await transfer(
            TransferDirection.DOWNLOAD, "app", output, "/tmp/owned-tree"
        )
        assert (output / "space café.bin").read_bytes() == b"owned\x00binary" and (
            output / "empty"
        ).is_dir()
        checks.append("actual-directory-empty-unicode-roundtrip")
        owner = service()
        review = await owner.prepare(
            TransferDirection.UPLOAD, "app", str(large), "/tmp/large.bin", overwrite=False
        )
        try:
            await owner.execute(review)
            raise AssertionError("Existing remote destination overwritten without intent")
        except AppError as error:
            assert "exists" in str(error)
        assert "complete" in await transfer(
            TransferDirection.UPLOAD, "app", large, "/tmp/large.bin", overwrite=True
        )
        checks.append("actual-remote-overwrite-review-refusal-and-explicit-replacement")
        output = local / "missing-tar"
        result = await transfer(TransferDirection.DOWNLOAD, "no-tar", output, "/tmp/file")
        assert "incomplete" in result and not output.exists()
        checks.append("actual-missing-tar-keeps-local-destination")
        try:
            await service(True).prepare(
                TransferDirection.UPLOAD, "app", str(large), "/tmp/refused", overwrite=False
            )
            raise AssertionError("Readonly upload allowed")
        except AppError as error:
            assert "Read-only" in str(error)
        checks.append("actual-readonly-upload-refused")

        async def remote_exec(arguments: list[str]) -> str:
            return await asyncio.to_thread(
                run_owned,
                [
                    kubectl,
                    "--kubeconfig=" + str(cluster.path),
                    "--context=" + cluster.context,
                    "--namespace=" + NAMESPACE,
                    "exec",
                    "--container=app",
                    POD,
                    "--",
                    *arguments,
                ],
                environment,
            )

        await remote_exec(["/bin/mkdir", "-p", "/tmp/bin"])
        wrapper = local / "slow-tar"
        wrapper.write_text(
            '#!/bin/sh\ncase "$1" in\n'
            'cf) /bin/tar "$@" | { /bin/dd bs=1024 count=1; /bin/sleep 10; /bin/cat; };;\n'
            '*) { /bin/dd bs=1024 count=4; /bin/sleep 10; /bin/cat; } | /bin/tar "$@";;\n'
            "esac\n"
        )
        assert "complete" in await transfer(
            TransferDirection.UPLOAD, "app", wrapper, "/tmp/bin/tar"
        )
        await remote_exec(["/bin/chmod", "700", "/tmp/bin/tar"])
        owner = service(True)
        cancelled = local / "cancelled-download"
        cancelled.write_bytes(b"retained")
        review = await owner.prepare(
            TransferDirection.DOWNLOAD,
            "slow-copy",
            str(cancelled),
            "/tmp/large.bin",
            overwrite=True,
        )
        copying = asyncio.create_task(owner.execute(review))
        pending.append(copying)
        async with asyncio.timeout(30):
            while (
                not (Path(review.temporary.name) / "download.tar").exists()
                or (Path(review.temporary.name) / "download.tar").stat().st_size < 1024
            ):
                if copying.done():
                    raise AssertionError(
                        "Slow download ended before cancellation: " + str(copying.result())
                    )
                await asyncio.sleep(0.01)
        copying.cancel()
        try:
            await copying
            raise AssertionError("Cancelled download completed")
        except asyncio.CancelledError:
            pass
        assert cancelled.read_bytes() == b"retained" and owner.review is None
        assert not Path(review.temporary.name).exists()
        checks.append("actual-interrupted-download-removes-private-partial-and-retains-destination")
        upload = local / "cancel-upload"
        upload.write_bytes(b"x" * (1024 * 1024))
        owner = service()
        review = await owner.prepare(
            TransferDirection.UPLOAD,
            "slow-copy",
            str(upload),
            "/tmp/cancel-upload.bin",
            overwrite=False,
        )
        copying = asyncio.create_task(owner.execute(review))
        pending.append(copying)
        async with asyncio.timeout(20):
            while True:
                if copying.done():
                    raise AssertionError(
                        "Upload ended before interruption: " + str(copying.result())
                    )
                try:
                    size = int(
                        await remote_exec(["/bin/stat", "-c", "%s", "/tmp/cancel-upload.bin"])
                    )
                    if size > 0:
                        break
                except subprocess.CalledProcessError:
                    pass
                await asyncio.sleep(0.01)
        copying.cancel()
        try:
            await copying
            raise AssertionError("Cancelled upload completed")
        except asyncio.CancelledError:
            pass
        size = int(await remote_exec(["/bin/stat", "-c", "%s", "/tmp/cancel-upload.bin"]))
        assert 0 < size < upload.stat().st_size and "remote partial" in owner.last_message
        assert owner.review is None and not Path(review.temporary.name).exists()
        checks.append("actual-interrupted-upload-observed-partial-no-retry")
        await asyncio.to_thread(native_attach, cluster, environment)
        value = await core.read_namespaced_pod(POD, NAMESPACE)
        assert value.metadata.uid == uid and value.status.phase == "Running"
        checks.append("actual-native-attach-detach-reattach-and-restoration")
        assert cluster.path.read_bytes() == before
        assert not list(Path(connection.directory.name).glob("copy-*"))
        assert not list(local.glob(".kuberich-copy-*"))
        checks.extend(("source-config-unchanged", "all-private-copy-state-removed"))
        return {"node_image": NODE_IMAGE, "shell_image": SHELL_IMAGE, "checks": checks}
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await connection.close()


def native_attach(cluster: OwnedCluster, environment: dict[str, str]) -> None:
    directory = cluster.directory / "native-attach"
    directory.mkdir()
    command = [
        sys.executable,
        "-m",
        "kuberich",
        "--kubeconfig",
        str(cluster.path),
        "--context",
        cluster.context,
        "--namespace",
        NAMESPACE,
        "--write",
    ]
    with TerminalSession(command, directory, environment=environment) as terminal:
        terminal.wait_for_screen("pods(" + NAMESPACE + ")[1]", timeout=45)
        terminal.send(b":attach\r")
        terminal.wait_for_screen("Containers")
        # Stable container declaration order keeps app first; init/debug follow.
        terminal.send(b"a")
        terminal.wait_for_screen("OWNED-ATTACH> ", timeout=30)
        terminal.send(b"printf 'OWNED_%s\\n' ATTACH_COMMAND\n")
        terminal.wait_for_screen("OWNED_ATTACH_COMMAND", timeout=20)
        terminal.send(b"\x10\x11")
        terminal.wait_for_screen("Attach closed", timeout=30)
        terminal.send(b"a")
        terminal.wait_for_screen("KubeRich · Attach to existing process")
        terminal.send(b"printf 'OWNED_%s\\n' REATTACHED\n")
        terminal.wait_for_screen("OWNED_REATTACHED", timeout=20)
        terminal.send(b"\x1d")
        terminal.wait_for_screen("Containers")
        terminal.send(b"\x1b")
        terminal.wait_for_screen("pods(" + NAMESPACE + ")[1]")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("owned-kind-attach-transfer")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--evidence", type=Path, default="artifacts/cluster/transfers.json")
    args = parser.parse_args()
    with owned_cluster(args.kind) as cluster:
        result = asyncio.run(verify(cluster, args.kubectl))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind attach and transfer checks passed.", flush=True)


if __name__ == "__main__":
    main()
