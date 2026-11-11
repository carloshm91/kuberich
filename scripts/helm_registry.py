"""An exact official registry fixture on one explicitly selected local Docker socket.

Only fixture setup uploads original synthetic chart bytes. Product catalog actions
use their independent GET-only adapter. Nothing reads caller Docker credentials.
"""

import asyncio
import os
import re
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4

import aiohttp

from kuberich.domain.helm_catalog import MAX_CHART_BYTES, oci_chart_path, oci_tag
from kuberich.domain.helm_cli import helm_json
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose, ProcessStatus
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.services.resources import parse_owned
from scripts.owned_kind import local_endpoint
from tests.support.helm_oci import MANIFEST_MEDIA, OciArtifact, content_digest

REGISTRY_VERSION = "3.1.2"
REGISTRY_IMAGE = "docker.io/library/registry@sha256:52b489ad8e6f40d1a676702e3ce398ec796ce38f08fbb786e1f324baa12d84b8"
REGISTRY_INDEX_DIGEST = "sha256:38907510915c3f1604c7e83d6ab602ab3020d092f73bdaed8696773693ff768c"
REGISTRY_IMAGE_ID = "sha256:39a2a88344598be51c03d6829b40dd29fcda04ce1e01ef1f7596b5af744276ce"
REGISTRY_SOURCE = "775973b655bb4b11561db92a1cf50113148ce530"
REGISTRY_RELEASE_ARCHIVE_SHA256 = "40df2224d410f72ae425c3371873b078bbdbda3b8b612be9571f0e6751f3acc8"
OWNER_LABEL = "kuberich.io/owned-helm-registry"
# An empty auth-map would permit Docker/ORAS native-store detection. This inert
# entry disables discovery while carrying no username, password, auth or token.
EMPTY_CONFIG = b'{"auths":{"kuberich-credential-empty.invalid":{}}}\n'


def _failure() -> AppError:
    return AppError(
        "Owned Helm registry setup or identity verification failed; fixture details withheld."
    )


class OwnedHelmRegistry:
    def __init__(self, docker: Path, endpoint: str, directory: Path) -> None:
        if not docker.is_absolute() or not directory.is_absolute() or ".." in directory.parts:
            raise ValueError("Registry fixtures require absolute owned paths.")
        self.docker, self.endpoint = docker, local_endpoint(endpoint)
        self.directory = directory
        self.name = "kuberich-registry-" + uuid4().hex[:16]
        self.owner = uuid4().hex
        self.container_id: str | None = None
        self.origin: str | None = None
        self.receipt: dict[str, Any] = {
            "version": REGISTRY_VERSION,
            "image": REGISTRY_IMAGE,
            "image_id": REGISTRY_IMAGE_ID,
            "index_digest": REGISTRY_INDEX_DIGEST,
            "source_commit": REGISTRY_SOURCE,
            "release_archive_sha256": REGISTRY_RELEASE_ARCHIVE_SHA256,
            "name": self.name,
            "owner": self.owner,
            "seeded": [],
            "cleanup_complete": False,
        }
        self._private: tempfile.TemporaryDirectory[str] | None = None
        self._config: Path | None = None
        self._runner = ProcessRunner(AccessPolicy(False), output_limit=1024 * 1024)
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._create_may_have_started = False

    def _prepare(self) -> None:
        if (
            not self.directory.is_dir()
            or self.directory.is_symlink()
            or self.directory.resolve() != self.directory
        ):
            raise _failure()
        self._private = tempfile.TemporaryDirectory(prefix="owned-registry-", dir=self.directory)
        root = Path(self._private.name)
        config = root / "docker"
        config.mkdir(mode=0o700)
        (root / "home").mkdir(mode=0o700)
        descriptor = os.open(config / "config.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(EMPTY_CONFIG)
        self._config = config

    async def _command(
        self, *arguments: str, runner: ProcessRunner | None = None, timeout: float = 30
    ) -> bytes:
        config, private = self._config, self._private
        if config is None or private is None:
            raise _failure()
        root = Path(private.name)
        command = ProcessCommand(
            (str(self.docker), "--host", self.endpoint, "--config", str(config), *arguments),
            (
                ("PATH", os.defpath),
                ("HOME", str(root / "home")),
                ("DOCKER_CONFIG", str(config)),
                ("DOCKER_HOST", self.endpoint),
                ("LANG", "C.UTF-8"),
                ("NO_COLOR", "1"),
            ),
            root,
            ProcessMode.CAPTURE,
            ProcessPurpose.DOWNLOAD
            if arguments[0] in {"pull", "image", "container", "inspect"}
            else ProcessPurpose.UPLOAD,
        )
        result = await (runner or self._runner).capture(command, timeout=timeout)
        if result.status is not ProcessStatus.SUCCEEDED:
            raise _failure()
        return result.stdout

    async def _owned(self, runner: ProcessRunner | None = None) -> dict[str, Any] | None:
        data = await self._command(
            "container",
            "ls",
            "-aq",
            "--no-trunc",
            "--filter",
            "name=^/" + self.name + "$",
            runner=runner,
        )
        identifiers = data.decode("ascii").split()
        if not identifiers:
            return None
        if len(identifiers) != 1 or re.fullmatch(r"[0-9a-f]{64}", identifiers[0]) is None:
            raise _failure()
        if self.container_id is not None and identifiers[0] != self.container_id:
            raise _failure()
        observed = helm_json(
            await self._command("inspect", identifiers[0], runner=runner), limit=1024 * 1024
        )
        if (
            not isinstance(observed, list)
            or len(observed) != 1
            or not isinstance(observed[0], dict)
        ):
            raise _failure()
        value = observed[0]
        config, host = value.get("Config"), value.get("HostConfig")
        if not isinstance(config, dict) or not isinstance(host, dict):
            raise _failure()
        labels = config.get("Labels")
        if (
            value.get("Id") != identifiers[0]
            or value.get("Name") != "/" + self.name
            or value.get("Image") != REGISTRY_IMAGE_ID
            or config.get("Image") != REGISTRY_IMAGE
            or not isinstance(labels, dict)
            or labels.get(OWNER_LABEL) != self.owner
            or config.get("User") != "65534:65534"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("Binds")
            or host.get("NetworkMode") != "bridge"
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges" not in host.get("SecurityOpt", [])
        ):
            raise _failure()
        self.container_id = identifiers[0]
        return value

    async def start(self, *, pull: bool = True) -> None:
        if self._closed or self._private is not None:
            raise _failure()
        try:
            await parse_owned(self._prepare)
            if pull:
                await self._command(
                    "pull", "--platform", "linux/amd64", REGISTRY_IMAGE, timeout=180
                )
            image = helm_json(
                await self._command("image", "inspect", REGISTRY_IMAGE), limit=1024 * 1024
            )
            if not isinstance(image, list) or len(image) != 1 or not isinstance(image[0], dict):
                raise _failure()
            if (
                image[0].get("Id") != REGISTRY_IMAGE_ID
                or image[0].get("Architecture") != "amd64"
                or image[0].get("Os") != "linux"
            ):
                raise _failure()
            self._create_may_have_started = True
            data = await self._command(
                "create",
                "--name",
                self.name,
                "--label",
                OWNER_LABEL + "=" + self.owner,
                "--user",
                "65534:65534",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "256m",
                "--network",
                "bridge",
                "--publish",
                "127.0.0.1::5000/tcp",
                "--tmpfs",
                "/var/lib/registry:rw,noexec,nosuid,size=67108864,mode=0700,uid=65534,gid=65534",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=8388608,mode=0700,uid=65534,gid=65534",
                "--env",
                "REGISTRY_STORAGE_DELETE_ENABLED=true",
                "--env",
                "REGISTRY_LOG_LEVEL=error",
                "--env",
                "OTEL_TRACES_EXPORTER=none",
                "--env",
                "REGISTRY_HTTP_SECRET=owned-" + self.owner,
                REGISTRY_IMAGE,
            )
            identifier = data.decode("ascii").strip()
            if re.fullmatch(r"[0-9a-f]{64}", identifier) is None:
                raise _failure()
            self.container_id = identifier
            if await self._owned() is None:
                raise _failure()
            await self._command("start", identifier)
            observed = await self._owned()
            if observed is None:
                raise _failure()
            network = observed.get("NetworkSettings")
            ports = network.get("Ports") if isinstance(network, dict) else None
            entries = ports.get("5000/tcp") if isinstance(ports, dict) else None
            if (
                not isinstance(entries, list)
                or len(entries) != 1
                or not isinstance(entries[0], dict)
            ):
                raise _failure()
            port = entries[0].get("HostPort")
            if (
                entries[0].get("HostIp") != "127.0.0.1"
                or not isinstance(port, str)
                or not port.isdecimal()
                or not 1 <= int(port) <= 65535
            ):
                raise _failure()
            self.origin = "http://127.0.0.1:" + port
            self.receipt.update(container_id=identifier, origin=self.origin)
            async with aiohttp.ClientSession(
                trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                timeout=aiohttp.ClientTimeout(total=2),
            ) as client:
                async with asyncio.timeout(30):
                    while True:
                        try:
                            async with client.get(
                                self.origin + "/v2/", allow_redirects=False
                            ) as response:
                                if (
                                    response.status == 200
                                    and len(await response.content.read(1025)) <= 1024
                                ):
                                    break
                        except (aiohttp.ClientError, TimeoutError):
                            pass
                        await asyncio.sleep(0.1)
        except BaseException:
            await finish_owned(asyncio.create_task(self.close()))
            raise

    async def seed(self, artifact: OciArtifact, repository: str) -> None:
        if self._closed or self.origin is None or self.container_id is None:
            raise _failure()
        path, pinned = oci_chart_path(repository)
        if (
            pinned is not None
            or path.rsplit("/", 1)[-1] != artifact.name
            or len(artifact.manifest) > 1024 * 1024
            or any(not 1 <= len(data) <= MAX_CHART_BYTES for data in artifact.blobs.values())
        ):
            raise _failure()
        oci_tag(artifact.tag)
        origin = self.origin

        async def run() -> None:
            if await self._owned() is None:
                raise _failure()
            async with aiohttp.ClientSession(
                trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as client:
                for digest, data in artifact.blobs.items():
                    async with client.post(
                        origin + "/v2/" + path + "/blobs/uploads/", allow_redirects=False
                    ) as response:
                        if response.status != 202:
                            raise _failure()
                        location = response.headers.get("Location", "")
                        await response.content.read(65537)
                    address = urlsplit(urljoin(origin, location))
                    if (
                        len(location) > 8192
                        or address.scheme + "://" + address.netloc != origin
                        or not address.path.startswith("/v2/" + path + "/blobs/uploads/")
                        or address.fragment
                    ):
                        raise _failure()
                    params = parse_qsl(address.query, strict_parsing=True)
                    if any(key == "digest" for key, _ in params):
                        raise _failure()
                    upload = urlunsplit(
                        (
                            address.scheme,
                            address.netloc,
                            address.path,
                            urlencode([*params, ("digest", digest)]),
                            "",
                        )
                    )
                    async with client.put(
                        upload,
                        data=data,
                        headers={"Content-Type": "application/octet-stream"},
                        allow_redirects=False,
                    ) as response:
                        if (
                            response.status != 201
                            or response.headers.get("Docker-Content-Digest", digest) != digest
                        ):
                            raise _failure()
                        if len(await response.content.read(65537)) > 65536:
                            raise _failure()
                async with client.put(
                    origin + "/v2/" + path + "/manifests/" + artifact.tag,
                    data=artifact.manifest,
                    headers={"Content-Type": MANIFEST_MEDIA},
                    allow_redirects=False,
                ) as response:
                    if (
                        response.status != 201
                        or response.headers.get("Docker-Content-Digest", artifact.manifest_digest)
                        != artifact.manifest_digest
                    ):
                        raise _failure()
                    if len(await response.content.read(65537)) > 65536:
                        raise _failure()
            self.receipt["seeded"].append(
                {
                    "repository": path,
                    "name": artifact.name,
                    "version": artifact.version,
                    "manifest_digest": artifact.manifest_digest,
                    "package_digest": content_digest(artifact.package),
                }
            )

        task = asyncio.create_task(run())
        self._tasks.add(task)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            self._tasks.discard(task)

    async def _cleanup(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        await self._runner.close()
        try:
            if self._config is not None and self._create_may_have_started:
                async with ProcessRunner(AccessPolicy(False), output_limit=1024 * 1024) as cleanup:
                    owned = await self._owned(cleanup)
                    if owned is not None:
                        assert self.container_id is not None
                        await self._command(
                            "rm", "--force", "--volumes", self.container_id, runner=cleanup
                        )
                    if await self._owned(cleanup) is not None:
                        raise _failure()
                self.receipt["container_absent"] = True
            else:
                self.receipt.update(container_absent=True, container_not_started=True)
        finally:
            if self._private is not None:
                private = Path(self._private.name)
                await asyncio.to_thread(self._private.cleanup)
                self.receipt["private_files_absent"] = not private.exists()
                self._private = None
            else:
                self.receipt["private_files_absent"] = True
        self.receipt["cleanup_complete"] = bool(
            self.receipt.get("container_absent") and self.receipt.get("private_files_absent")
        )

    async def close(self) -> None:
        self._closed = True
        if self._closing is None:
            self._closing = asyncio.create_task(self._cleanup())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await finish_owned(self._closing)
            raise


@asynccontextmanager
async def owned_helm_registry(
    docker: Path, endpoint: str, directory: Path, *, pull: bool = True
) -> AsyncIterator[OwnedHelmRegistry]:
    registry = OwnedHelmRegistry(docker, endpoint, directory)
    try:
        await registry.start(pull=pull)
        yield registry
    finally:
        await finish_owned(asyncio.create_task(registry.close()))
