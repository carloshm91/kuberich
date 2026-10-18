"""Explicit plugin review, captured credentials, bounded jobs and owned cleanup."""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from kuberich.adapters.editing import file_worker
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.plugins import Plugin, PluginSelection, plugin_command
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessResult
from kuberich.domain.resources import ApiResource, api_segment, resource_record
from kuberich.errors import AppError
from kuberich.runtime import credential_argv
from kuberich.services.access import AccessPolicy
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.processes import ProcessRunner, _executable, _finish_owned

Handoff = Callable[
    [ProcessRunner, ProcessCommand, Callable[[], None], float], Awaitable[ProcessResult]
]


@dataclass(frozen=True, slots=True, repr=False)
class PluginRequest:
    plugin: Plugin
    command: ProcessCommand
    files: tuple[tuple[Path, str], ...]
    hints: tuple[str, ...]
    nonce: str = field(default_factory=lambda: uuid4().hex)


class PluginSource:
    """One immutable selection; prepared reviews are consumed once by identity."""

    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource | None,
        selection: PluginSelection,
        policy: AccessPolicy,
        current: Callable[[], bool],
        environment: Mapping[str, str],
    ) -> None:
        self.client, self.resource, self.selection = client, resource, selection
        self.policy, self.current = policy, current
        self.environment = dict(environment)
        self._prepared: dict[str, PluginRequest] = {}
        self._preparing = 0
        self._closed = False

    def require(self, plugin: Plugin) -> None:
        plugin.require_access(self.policy.read_only)
        if self._closed or not self.current() or self.client.context.name != self.selection.context:
            raise AppError("Plugin selection is stale; return to the resource and review again.")
        if not plugin.applies(self.selection.resource):
            raise AppError("Plugin does not apply to this resource view.")

    def _capture(self, plugin: Plugin, inputs: Mapping[str, object]) -> PluginRequest:
        material = capture_delegation(
            self.client, self.environment, plugin.directory, prefix="plugin"
        )
        values = dict(self.selection.variables)
        values["KUBECONFIG"] = str(material.path)
        selection = replace(self.selection, variables=tuple(values.items()))
        command = plugin_command(plugin, selection, inputs, self.environment)
        assert command is not None
        configuration = json.loads(material.configuration)
        files: list[tuple[Path, str]] = []
        credentials = self.client.credentials
        if credentials is not None:
            invocation = credentials.invocation(interactive=True)
            executable = _executable(invocation)
            helper_path = material.path.with_name(material.path.stem + "-credential.json")
            environment = dict(invocation.environment)
            environment.pop("KUBERNETES_EXEC_INFO", None)
            files.append(
                (
                    helper_path,
                    json.dumps(
                        {
                            "argv": [executable, *invocation.argv[1:]],
                            "environment": environment,
                            "directory": str(invocation.directory),
                        },
                        allow_nan=False,
                    ),
                )
            )
            helper = configuration["users"][0]["user"]["exec"]
            launcher = credential_argv(helper_path)
            helper.update(command=launcher[0], args=list(launcher[1:]), env=[])
        files.append((material.path, json.dumps(configuration, allow_nan=False)))
        environment = dict(command.environment)
        environment["KUBECONFIG"] = str(material.path)
        environment["KUBERICH_CONTEXT"] = selection.context
        if selection.target is not None:
            environment["KUBERICH_NAMESPACE"] = selection.target.namespace or ""
        hints = [
            value
            for key, value in environment.items()
            if re.search("token|password|secret|credential|key", key, re.I) and len(value) >= 4
        ]
        hints.extend(str(value) for value in inputs.values() if len(str(value)) >= 4)
        if self.client.configuration is not None:
            for value in self.client.configuration.api_key.values():
                hints.extend((value, value.removeprefix("Bearer ")))
        return PluginRequest(
            plugin,
            replace(command, environment=tuple(environment.items())),
            tuple(files),
            tuple(hints),
        )

    async def prepare(
        self, plugin: Plugin, inputs: Mapping[str, object] | None
    ) -> PluginRequest | None:
        self.require(plugin)  # Before helper lookup, filesystem work or input processing.
        if inputs is None:
            return None
        if len(self._prepared) + self._preparing >= 8:
            raise AppError("Too many pending plugin reviews; cancel an older review first.")
        # Literal expansion precedes helper lookup inside the owned worker.
        captured_inputs = dict(inputs)
        self._preparing += 1
        try:
            request = await file_worker(lambda: self._capture(plugin, captured_inputs))
            self.require(plugin)
            self._prepared[request.nonce] = request
            return request
        finally:
            self._preparing -= 1

    def discard(self, request: PluginRequest | None) -> None:
        if request is not None and self._prepared.get(request.nonce) is request:
            del self._prepared[request.nonce]

    def consume(self, request: PluginRequest, confirmed: bool) -> None:
        self.require(request.plugin)
        if self._prepared.get(request.nonce) is not request:
            raise AppError("Plugin review is unavailable or already consumed; review again.")
        if (request.plugin.confirm or request.plugin.dangerous) and not confirmed:
            raise AppError("This unsandboxed local plugin requires explicit confirmation.")
        self.discard(request)

    async def preflight(self, plugin: Plugin) -> None:
        self.require(plugin)
        target, descriptor = self.selection.target, self.resource
        if target is not None:
            if (
                descriptor is None
                or descriptor.name != target.resource
                or descriptor.group != target.group
            ):
                raise AppError("Plugin requires its captured API resource.")
            payload = await self.client.get_json(
                descriptor.path(target.namespace) + "/" + api_segment(target.name)
            )
            self.require(plugin)
            record = resource_record(descriptor, payload, target.namespace)
            if (record.uid, record.name, record.namespace) != (
                target.uid,
                target.name,
                target.namespace,
            ):
                raise AppError("Plugin target was replaced; select and review the resource again.")

    def close(self) -> None:
        self._closed = True
        self._prepared.clear()


@dataclass(slots=True, repr=False)
class PluginJob:
    number: int
    name: str
    mode: ProcessMode
    source: PluginSource
    request: PluginRequest
    runner: ProcessRunner
    task: asyncio.Task[None] | None = None
    status: str = "Starting"
    output: str = ""
    returncode: int | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def wait(self) -> None:
        if self.task is not None:
            await asyncio.shield(self.task)


class PluginManager:
    def __init__(self, policy: AccessPolicy) -> None:
        self.policy = policy
        self.jobs: list[PluginJob] = []
        self._next = 1
        self._closed = False

    def start(
        self,
        source: PluginSource,
        request: PluginRequest,
        *,
        confirmed: bool = False,
        handoff: Handoff | None = None,
    ) -> PluginJob:
        if self._closed or sum(job.running for job in self.jobs) >= 4:
            raise AppError("Plugin runner is closed or its four active jobs are occupied.")
        if source.policy != self.policy:
            raise AppError("Plugin policy differs from the owning application.")
        if request.plugin.mode is ProcessMode.FOREGROUND and any(
            job.running and job.mode is ProcessMode.FOREGROUND for job in self.jobs
        ):
            raise AppError("Another foreground plugin owns the terminal.")
        source.consume(request, confirmed)
        while len(self.jobs) >= 32:
            self.jobs.remove(next(job for job in self.jobs if not job.running))
        job = PluginJob(
            self._next,
            request.plugin.name,
            request.plugin.mode,
            source,
            request,
            ProcessRunner(self.policy, output_limit=request.plugin.output_limit),
        )
        self._next += 1
        self.jobs.append(job)
        job.task = asyncio.create_task(self._run(job, handoff))
        return job

    async def _run(self, job: PluginJob, handoff: Handoff | None) -> None:
        source, request, runner = job.source, job.request, job.runner
        plugin = request.plugin

        def guard() -> None:
            source.require(plugin)

        try:
            await source.preflight(plugin)
            async with AsyncExitStack() as stack:
                for path, content in request.files:
                    await stack.enter_async_context(stage_connection(path, content))
                stack.push_async_callback(runner.close)
                guard()
                job.status = "Running"
                if plugin.mode is ProcessMode.FOREGROUND:
                    if handoff is None:
                        raise AppError(
                            "Foreground plugins require the native terminal application."
                        )
                    result = await handoff(runner, request.command, guard, plugin.timeout)
                elif plugin.mode is ProcessMode.BACKGROUND:
                    session = await runner.background(
                        request.command, timeout=plugin.timeout, guard=guard
                    )
                    result = await session.wait()
                else:
                    result = await runner.capture(
                        request.command, timeout=plugin.timeout, guard=guard
                    )
                job.returncode = result.returncode
                job.status = result.status.name.replace("_", " ").title()

                def redact() -> str:
                    output = (result.stdout + b"\n" + result.stderr).decode(
                        "utf-8", errors="replace"
                    )
                    for hint in sorted(set(request.hints), key=len, reverse=True):
                        if hint:
                            output = output.replace(hint, "[REDACTED]")
                    return sanitize_text(output, allow_newlines=True)[:65536]

                job.output = await file_worker(redact)
        except asyncio.CancelledError:
            job.status = "Cancelled"
        except (AppError, OSError, ConnectionProblem) as error:
            # External transport/errors can contain credentials; retain only the
            # typed class. Process exit/timeout/overflow have explicit statuses.
            job.status = "Error: " + type(error).__name__
            job.output = "Plugin preparation, execution or cleanup failed. Check its executable, captured connection, permissions and working directory. External changes may already have occurred; no automatic retry was made."
        finally:
            cleanup = asyncio.create_task(runner.close())
            await _finish_owned(cleanup)

    async def stop(self, job: PluginJob) -> None:
        if job not in self.jobs:
            raise AppError("Unknown plugin job.")
        if job.task is not None:
            if not job.task.done():
                job.task.cancel()
            await _finish_owned(asyncio.gather(job.task, return_exceptions=True))
            if job.status == "Starting":
                job.status = "Cancelled"

    async def stop_for_client(self, client: KubernetesSession) -> None:
        for job in tuple(self.jobs):
            if job.source.client is client:
                await self.stop(job)
                job.source.close()

    def invalidate(self) -> None:
        for job in self.jobs:
            if job.running and not job.source.current() and job.task is not None:
                job.task.cancel()

    async def close(self) -> None:
        self._closed = True
        for job in tuple(self.jobs):
            await self.stop(job)
            job.source.close()
