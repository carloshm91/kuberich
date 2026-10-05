"""Owned cancellable container log reads; no automatic replay or hidden queue."""

from collections.abc import Awaitable, Callable
from contextlib import aclosing

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kubetrol.domain.logs import LogDecoder, LogLine, LogOptions, log_containers
from kubetrol.domain.resources import ApiResource, api_segment, resource_record
from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy, Action

PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get"}))


class LogStream:
    def __init__(
        self,
        client: KubernetesSession,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        self.client, self.target, self.policy, self.current = client, target, policy, current

    def require_current(self) -> None:
        if not self.current():
            raise AppError("The log target is stale; select the pod and container again.")

    async def _verify(self, path: str) -> None:
        payload = await self.client.get_json(path)
        self.require_current()
        record = resource_record(PODS, payload, self.target.namespace)
        self.target.require_current(self.target.session, uid=record.uid or "")
        if record.name != self.target.name:
            raise AppError("Log API response does not match the captured pod name.")
        if self.target.container not in log_containers(record.manifest):
            raise AppError("Selected regular/init container is unavailable in this pod.")

    async def run(self, options: LogOptions, sink: Callable[[LogLine], Awaitable[None]]) -> int:
        self.policy.require(Action.READ)
        self.require_current()
        if (
            self.target.session.context != self.client.context.name
            or self.target.group != ""
            or self.target.resource != "pods"
            or self.target.namespace is None
            or self.target.container is None
        ):
            raise AppError("Logs require a captured context, pod, namespace and container.")
        path = PODS.path(self.target.namespace) + "/" + api_segment(self.target.name)
        params = options.parameters(self.target.container)
        decoder, count = LogDecoder(), 0
        try:
            await self._verify(path)
            async with aclosing(
                self.client.log_bytes(path + "/log", params, follow=options.follow)
            ) as stream:
                async for chunk in stream:
                    self.require_current()
                    if chunk is None:
                        # Verify after opening too: a name recreation between GET and
                        # the log request must not emit the replacement pod's output.
                        await self._verify(path)
                        continue
                    for line in decoder.feed(chunk):
                        self.require_current()
                        await sink(line)
                        count += 1
                self.require_current()
                for line in decoder.feed(b"", final=True):
                    self.require_current()
                    await sink(line)
                    count += 1
        except HttpProblem as error:
            if error.status == 403:
                raise ConnectionProblem(
                    ConnectionState.LIMITED,
                    "Permission denied (403): logs require pod and pods/log read access.",
                ) from None
            if error.status == 404:
                raise ConnectionProblem(
                    ConnectionState.API_ERROR,
                    "Pod or container logs unavailable (404); the pod may have been deleted.",
                ) from None
            if error.status == 400:
                raise ConnectionProblem(
                    ConnectionState.API_ERROR,
                    "Previous container logs unavailable (400); no previous instance may exist."
                    if options.previous
                    else "Container logs unavailable (400); the selected instance may not have started.",
                ) from None
            raise
        return count
