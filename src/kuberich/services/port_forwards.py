"""Owned, bounded port forwards with captured clients and process-backed readiness."""

import asyncio
import socket
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from ipaddress import ip_address
from pathlib import Path
from uuid import UUID, uuid4
from weakref import WeakSet

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import HttpProblem
from kuberich.domain.port_forwards import (
    BoundPort,
    ForwardState,
    PortMapping,
    Readiness,
    bind_address,
    forward_command,
    validate_forward_target,
    verify_forward_target,
)
from kuberich.domain.processes import ProcessCommand
from kuberich.domain.resources import ApiResource, api_segment, resource_record
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.processes import ProcessRunner, ProcessSession, _finish_owned


@dataclass(frozen=True, repr=False)
class ForwardRequest:
    command: ProcessCommand
    path: Path
    configuration: str
    mappings: tuple[PortMapping, ...]
    address: str


def _available(address: str, mappings: tuple[PortMapping, ...]) -> None:
    family = socket.AF_INET6 if ip_address(address).version == 6 else socket.AF_INET
    for mapping in mappings:
        if mapping.local:
            try:
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    # Match kubectl's listener behavior: a closed connection in
                    # TIME_WAIT must not be reported as an active port collision.
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    if family == socket.AF_INET6:
                        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    probe.bind((address, mapping.local))
            except OSError:
                raise AppError(
                    f"Cannot bind local port {mapping.local}. Check address, permissions and existing listeners."
                ) from None


class ForwardService:
    def __init__(
        self,
        client: KubernetesSession,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        environment: Mapping[str, str],
        directory: Path,
    ) -> None:
        self.client, self.target, self.policy, self.current = client, target, policy, current
        self.environment, self.directory = dict(environment), directory.absolute()

    def require_current(self) -> None:
        self.policy.require(Action.PORT_FORWARD)
        validate_forward_target(self.target)
        if not self.current() or self.target.session.context != self.client.context.name:
            raise AppError("Port-forward connection changed; select the resource again.")

    def capture(
        self, mappings: tuple[PortMapping, ...], address: str, *, allow_remote: bool = False
    ) -> ForwardRequest:
        self.require_current()
        address = bind_address(address)
        if not ip_address(address).is_loopback and allow_remote is not True:
            raise AppError(
                "A non-loopback bind requires explicit permission for remote connections."
            )
        material = capture_delegation(
            self.client, self.environment, self.directory, prefix="forward"
        )
        command = forward_command(
            self.target,
            material.path,
            mappings,
            address,
            environment=dict(material.environment),
            directory=material.directory,
        )
        return ForwardRequest(command, material.path, material.configuration, mappings, address)

    async def verify(self) -> None:
        self.require_current()
        target = self.target
        resource = ApiResource(
            "",
            "v1",
            target.resource,
            "Pod" if target.resource == "pods" else "Service",
            True,
            frozenset({"get"}),
        )
        try:
            payload = await self.client.get_json(
                resource.path(target.namespace) + "/" + api_segment(target.name)
            )
        except HttpProblem as error:
            if error.status in {403, 404}:
                raise AppError(
                    "Port-forward target read denied (403). Check get pods/services and pods/portforward permission."
                    if error.status == 403
                    else "Port-forward target unavailable (404); it may have been deleted."
                ) from None
            raise
        self.require_current()
        verify_forward_target(target, resource_record(resource, payload, target.namespace))

    @asynccontextmanager
    async def stage(self, request: ForwardRequest) -> AsyncIterator[ProcessCommand]:
        self.require_current()
        if (
            request.command.target != self.target
            or request.path.parent != Path(self.client.directory.name)
            or request.command
            != forward_command(
                self.target,
                request.path,
                request.mappings,
                request.address,
                environment=dict(request.command.environment),
                directory=request.command.directory,
            )
        ):
            raise AppError(
                "Port-forward preparation requires this captured target and private directory."
            )
        await self.verify()
        probing = asyncio.create_task(
            asyncio.to_thread(_available, request.address, request.mappings)
        )
        try:
            await asyncio.shield(probing)
        except asyncio.CancelledError:
            await _finish_owned(asyncio.gather(probing, return_exceptions=True))
            raise
        self.require_current()
        async with stage_connection(request.path, request.configuration):
            self.require_current()
            yield request.command


@dataclass(frozen=True)
class ForwardInfo:
    identity: UUID
    target: ResourceTarget
    mappings: tuple[PortMapping, ...]
    address: str
    state: ForwardState = ForwardState.STARTING
    ports: tuple[BoundPort, ...] = ()
    message: str = "Starting; waiting for kubectl to bind."
    pid: int | None = None


class _Forward:
    def __init__(
        self,
        source: ForwardService,
        request: ForwardRequest,
        runner: ProcessRunner,
        changed: Callable[[ForwardInfo], None],
        timeout: float,
        interval: float,
    ) -> None:
        self.source, self.request, self.runner = source, request, runner
        self.changed, self.timeout, self.interval = changed, timeout, interval
        self.info = ForwardInfo(uuid4(), source.target, request.mappings, request.address)
        self.reason = "Stopped by operator."
        self.denied = False
        self.task = asyncio.create_task(self._run())

    def _observe(self, process: ProcessSession, readiness: Readiness) -> None:
        stdout, stderr = process.drain_output()
        readiness.feed(stdout)
        self.denied = (
            self.denied or b"forbidden" in stderr.lower() or b"unauthorized" in stderr.lower()
        )

    async def _require_running(self, process: ProcessSession) -> None:
        if not process.running:
            result = await process.wait()
            raise AppError(
                "Port-forward was refused. Check get pods/services and create pods/portforward permission."
                if self.denied
                or b"forbidden" in result.stderr.lower()
                or b"unauthorized" in result.stderr.lower()
                else f"Port-forward ended (exit {result.returncode}). Check target, connectivity and kubectl."
            )

    async def _work(self) -> None:
        readiness = Readiness(
            self.request.mappings, self.request.address, pod=self.source.target.resource == "pods"
        )
        async with AsyncExitStack() as ownership:
            async with asyncio.timeout(self.timeout):
                command = await ownership.enter_async_context(self.source.stage(self.request))
                process = await self.runner.background(command, guard=self.source.require_current)
                ownership.push_async_callback(process.close)
                self.info = replace(self.info, pid=process.pid)
                self.changed(self.info)
                while not readiness.ready:
                    self.source.require_current()
                    self._observe(process, readiness)
                    await self._require_running(process)
                    if not readiness.ready:
                        await asyncio.sleep(0.03)
                await self.source.verify()
                await self._require_running(process)
                self.info = replace(
                    self.info,
                    state=ForwardState.READY,
                    ports=readiness.ports,
                    message="Listening; context changes stop this session.",
                )
                self.changed(self.info)
            check_at = asyncio.get_running_loop().time() + self.interval
            while True:
                self.source.require_current()
                self._observe(process, readiness)
                await self._require_running(process)
                if asyncio.get_running_loop().time() >= check_at:
                    await self.source.verify()
                    check_at = asyncio.get_running_loop().time() + self.interval
                await asyncio.sleep(0.03)

    async def _run(self) -> None:
        try:
            await self._work()
        except asyncio.CancelledError:
            self.info = replace(self.info, state=ForwardState.STOPPED, message=self.reason)
        except TimeoutError:
            self.info = replace(
                self.info,
                state=ForwardState.FAILED,
                message="Port-forward timed out before readiness. Check target and credentials.",
            )
        except AppError as error:
            self.info = replace(
                self.info, state=ForwardState.FAILED, message=sanitize_text(str(error))[:512]
            )
        except Exception:
            self.info = replace(
                self.info,
                state=ForwardState.FAILED,
                message="Port-forward failed unexpectedly; its owned resources were cleaned up.",
            )
        finally:
            self.changed(self.info)

    async def stop(self, reason: str) -> None:
        if not self.task.done():
            self.reason = reason
            self.info = replace(
                self.info,
                state=ForwardState.STOPPING,
                message="Stopping owned port-forward; waiting for cleanup.",
            )
            self.changed(self.info)
            self.task.cancel()
        finishing = asyncio.gather(self.task, return_exceptions=True)
        try:
            await asyncio.shield(finishing)
        except asyncio.CancelledError:
            await _finish_owned(finishing)
            raise
        finally:
            # Cancellation can happen before the coroutine enters its try/finally.
            if self.info.state is ForwardState.STOPPING:
                self.info = replace(self.info, state=ForwardState.STOPPED, message=self.reason)
                self.changed(self.info)


class ForwardManager:
    """One app owner; eight active sessions and at most 32 recent records."""

    def __init__(
        self,
        runner: ProcessRunner,
        *,
        changed: Callable[[], None] = lambda: None,
        startup_timeout: float = 15,
        check_interval: float = 1,
    ) -> None:
        if any(
            type(value) not in {int, float} or not 0 < value <= 60
            for value in (startup_timeout, check_interval)
        ):
            raise AppError(
                "Port-forward startup and target-check intervals must be bounded and positive."
            )
        self.runner, self.changed = runner, changed
        self.timeout, self.interval = startup_timeout, check_interval
        self._records: OrderedDict[UUID, ForwardInfo] = OrderedDict()
        self._live: dict[UUID, _Forward] = {}
        self._retired: WeakSet[KubernetesSession] = WeakSet()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    @property
    def infos(self) -> tuple[ForwardInfo, ...]:
        return tuple(self._records.values())

    @property
    def active_count(self) -> int:
        return sum(not record.task.done() for record in self._live.values())

    def _record_changed(self, info: ForwardInfo) -> None:
        self._records[info.identity] = info
        self.changed()

    def _completed(self, record: _Forward, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
        self._live.pop(record.info.identity, None)
        # Recent history has public status/target data, not credential JSON,
        # captured environment, closed clients or raw process output.
        self._record_changed(record.info)

    def start(
        self,
        source: ForwardService,
        mappings: tuple[PortMapping, ...],
        address: str = "127.0.0.1",
        *,
        allow_remote: bool = False,
    ) -> UUID:
        if self._closed:
            raise AppError("Port-forward manager is closed.")
        source.require_current()
        if source.client in self._retired:
            raise AppError("That client is closing. Connect again before starting a port-forward.")
        if self.active_count >= 8:
            raise AppError("Eight port forwards are already active. Stop a session first.")
        request = source.capture(mappings, address, allow_remote=allow_remote)
        ports = {mapping.local for mapping in request.mappings if mapping.local}
        for record in self._live.values():
            if (
                not record.task.done()
                and record.info.address == request.address
                and ports.intersection(
                    {mapping.local for mapping in record.info.mappings}
                    | {port.local for port in record.info.ports}
                )
            ):
                raise AppError(
                    "An owned port-forward session already reserves a requested local port."
                )
        while len(self._records) >= 32:
            oldest = next(identity for identity in self._records if identity not in self._live)
            del self._records[oldest]
        record = _Forward(
            source, request, self.runner, self._record_changed, self.timeout, self.interval
        )
        self._records[record.info.identity] = record.info
        self._live[record.info.identity] = record
        record.task.add_done_callback(lambda completed: self._completed(record, completed))
        self.changed()
        return record.info.identity

    async def stop(self, identity: UUID) -> None:
        if identity not in self._records:
            raise AppError("That port-forward session is no longer retained.")
        record = self._live.get(identity)
        if record is not None:
            await record.stop("Stopped by operator.")

    async def stop_for_client(self, client: KubernetesSession) -> None:
        self._retired.add(client)
        stopping = asyncio.gather(
            *(
                record.stop("Stopped for connection change.")
                for record in self._live.values()
                if record.source.client is client
            )
        )
        try:
            await asyncio.shield(stopping)
        except asyncio.CancelledError:
            await _finish_owned(stopping)
            raise

    async def _shutdown(self) -> None:
        await asyncio.gather(
            *(record.stop("Stopped on application exit.") for record in self._live.values())
        )

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.create_task(self._shutdown())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await _finish_owned(self._closing)
            raise
