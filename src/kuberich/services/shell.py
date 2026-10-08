"""Captured container exec with private connection material and owned preparation."""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.schema import shell_arguments
from kuberich.domain.connections import HttpProblem
from kuberich.domain.processes import ProcessCommand, kubectl_exec_command
from kuberich.domain.resources import api_segment, resource_record
from kuberich.domain.shell import verify_shell_target
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.logs import PODS


@dataclass(frozen=True, slots=True, repr=False)
class ShellRequest:
    command: ProcessCommand
    path: Path
    configuration: str


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
        material = capture_delegation(self.client, self.environment, self.directory, prefix="exec")
        command = kubectl_exec_command(
            target,
            (material.path,),
            self.shell,
            environment=dict(material.environment),
            directory=material.directory,
        )
        return ShellRequest(command, material.path, material.configuration)

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
        async with stage_connection(request.path, request.configuration):
            self.require_current()
            yield request.command
