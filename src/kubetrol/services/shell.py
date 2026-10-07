"""Captured container exec with private connection material and owned preparation."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.config.schema import shell_arguments
from kubetrol.domain.connections import HttpProblem
from kubetrol.domain.processes import ProcessCommand, kubectl_exec_command
from kubetrol.domain.resources import api_segment, resource_record
from kubetrol.domain.shell import verify_shell_target
from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy, Action
from kubetrol.services.logs import PODS
from kubetrol.services.processes import _finish_owned


@dataclass(frozen=True, slots=True, repr=False)
class ShellRequest:
    command: ProcessCommand
    path: Path
    configuration: str


class _ConnectionFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.created = False

    def write(self, configuration: str) -> None:
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(configuration)

    def remove(self) -> None:
        if self.created:
            self.path.unlink(missing_ok=True)


class ShellService:
    def __init__(
        self,
        client: KubernetesSession,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        shell: tuple[str, ...],
        environment: Mapping[str, str],
        directory: Path,
    ) -> None:
        self.client, self.target, self.policy, self.current = client, target, policy, current
        self.shell = shell_arguments(shell)
        self.environment = dict(environment)
        self.directory = directory.absolute()

    def require_current(self) -> None:
        self.policy.require(Action.EXEC)
        if not self.current():
            raise AppError("The shell target is stale; select the pod and container again.")

    def capture(self, container: str) -> ShellRequest:
        self.require_current()
        target = replace(self.target, container=container)
        if target.session.context != self.client.context.name:
            raise AppError("Shell requires the captured client's context.")
        path = Path(self.client.directory.name) / f"exec-{uuid4().hex}.json"
        environment, directory = self.environment, self.directory
        credentials = self.client.credentials
        if credentials is not None and (credentials.eks or credentials.azure):
            environment = credentials.delegated_environment(environment)
            directory = credentials.entry.directory
        command = kubectl_exec_command(
            target, (path,), self.shell, environment=environment, directory=directory
        )
        try:
            configuration = json.dumps(self.client.delegated_config(), allow_nan=False)
        except (TypeError, ValueError):
            raise AppError(
                "Selected connection cannot be delegated to kubectl. Check kubeconfig extension/credential fields."
            ) from None
        return ShellRequest(command, path, configuration)

    @asynccontextmanager
    async def stage(self, request: ShellRequest) -> AsyncIterator[ProcessCommand]:
        self.require_current()
        target = request.command.target
        if (
            target is None
            or replace(target, container=self.target.container) != self.target
            or request.path.parent != Path(self.client.directory.name)
        ):
            raise AppError("Shell preparation requires this captured pod and private directory.")
        assert target.namespace is not None
        try:
            payload = await self.client.get_json(
                PODS.path(target.namespace) + "/" + api_segment(target.name)
            )
        except HttpProblem as error:
            if error.status == 403:
                raise AppError(
                    "Pod read denied (403). Shell requires get pods and pods/exec permission."
                ) from None
            if error.status == 404:
                raise AppError(
                    "Pod unavailable (404); it may have been deleted. Select the pod again."
                ) from None
            raise
        self.require_current()
        verify_shell_target(target, resource_record(PODS, payload, target.namespace))
        connection_file = _ConnectionFile(request.path)
        writing = asyncio.create_task(
            asyncio.to_thread(connection_file.write, request.configuration)
        )
        try:
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                await _finish_owned(asyncio.gather(writing, return_exceptions=True))
                raise
            except OSError:
                raise AppError(
                    "Cannot prepare private kubectl connection. Check local file permissions."
                ) from None
            self.require_current()
            yield request.command
        finally:
            cleanup = asyncio.create_task(asyncio.to_thread(connection_file.remove))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await _finish_owned(cleanup)
                raise
            except OSError:
                raise AppError(
                    "Cannot remove the private kubectl connection. Check local file permissions."
                ) from None
