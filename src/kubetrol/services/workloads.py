"""Captured workload mutations and independently cancellable actual API monitoring."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from kubetrol.domain.connections import HttpProblem
from kubetrol.domain.mutations import MutationIntent, mutation_path, patch_intent
from kubetrol.domain.resources import (
    ApiResource,
    ResourceRecord,
    api_segment,
    resource_object,
    resource_record,
)
from kubetrol.domain.workloads import (
    RolloutProgress,
    WorkloadAction,
    applicable,
    controlled_by,
    replica_count,
    require_rolling,
    restart_intent,
    revision_template,
    rollout_progress,
)
from kubetrol.errors import AppError
from kubetrol.services.access import Action
from kubetrol.services.mutations import MutationService

SCALE_RESOURCE = ApiResource(
    "autoscaling", "v1", "scales", "Scale", True, frozenset({"get", "patch"})
)


class WorkloadService(MutationService):
    operation: WorkloadAction = WorkloadAction.STATUS
    history: tuple[str, str, str] | None = None
    preview = ""
    _scale_storage_delete = False

    def require_current(self) -> None:
        applicable(self.resource, self.operation)
        self.policy.require(Action.MUTATE)
        if not self.current() or self.client.context.name != self.target.session.context:
            raise AppError("Workload target/connection changed. Select it again.")
        if self.operation is not WorkloadAction.STATUS:
            mutation_path(
                self.resource,
                self.target,
                "scale" if self.operation is WorkloadAction.SCALE else None,
            )

    def _require_read(self) -> None:
        self.policy.require(Action.READ)
        applicable(self.resource, WorkloadAction.STATUS)
        if (
            self.target.group != self.resource.group
            or self.target.resource != self.resource.name
            or self.target.container is not None
            or self.target.namespace is None
            or "get" not in self.resource.verbs
        ):
            raise AppError("Rollout status requires an exact readable workload scope.")
        if not self.current() or self.client.context.name != self.target.session.context:
            raise AppError("Workload target/connection changed. Select it again.")

    async def read_parent(self, *, read_only: bool = False) -> ResourceRecord:
        authorize = self._require_read if read_only else self.require_current
        authorize()
        value = await self.client.get_json(
            self.resource.path(self.target.namespace) + "/" + api_segment(self.target.name)
        )
        authorize()
        record = resource_record(self.resource, value, self.target.namespace)
        self.target.require_current(self.target.session, uid=record.uid or "")
        if record.name != self.target.name:
            raise AppError("Workload read returned a different target.")
        return record

    async def _items(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        continuation = ""
        seen: set[str] = set()
        for _ in range(64):
            self.require_current()
            value = await self.client.get_json(
                path,
                params={"limit": "500", **({"continue": continuation} if continuation else {})},
            )
            self.require_current()
            page = value.get("items")
            if not isinstance(page, list) or len(items) + len(page) > 10000:
                raise AppError("Workload related-resource collection is invalid or too large.")
            items.extend(resource_object(item) for item in page)
            continuation = resource_object(value.get("metadata", {})).get("continue", "")
            if (
                not isinstance(continuation, str)
                or len(continuation) > 4096
                or continuation in seen
            ):
                raise AppError("Workload collection continuation is invalid.")
            if not continuation:
                return items
            seen.add(continuation)
        raise AppError("Workload related-resource pagination exceeded its limit.")

    async def _check_hpa(self) -> None:
        namespace = self.target.namespace
        try:
            items = await self._items(
                f"/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers"
            )
        except HttpProblem as error:
            if error.status != 404:
                raise AppError(
                    "Cannot verify HPA ownership. Require list access to namespace HPAs before scaling."
                ) from None
            try:
                items = await self._items(
                    f"/apis/autoscaling/v1/namespaces/{namespace}/horizontalpodautoscalers"
                )
            except HttpProblem as fallback:
                if fallback.status == 404:
                    return
                raise AppError("Cannot verify HPA ownership; no scale request was sent.") from None
        for item in items:
            reference = resource_object(resource_object(item.get("spec")).get("scaleTargetRef"))
            if (
                reference.get("name") == self.target.name
                and reference.get("kind") == self.resource.kind
                and str(reference.get("apiVersion", "")).split("/")[0] == self.resource.group
            ):
                raise AppError(
                    "An HPA controls this workload. Change its policy instead of manual replicas."
                )

    async def _read(self) -> ResourceRecord:
        parent = await self.read_parent()
        if self.operation is WorkloadAction.SCALE:
            spec = resource_object(parent.manifest.get("spec"))
            self._scale_storage_delete = (
                self.resource.name == "statefulsets"
                and resource_object(spec.get("persistentVolumeClaimRetentionPolicy", {})).get(
                    "whenScaled"
                )
                == "Delete"
                and bool(spec.get("volumeClaimTemplates"))
            )
            await self._check_hpa()
            data = await self.client.get_json(mutation_path(self.resource, self.target, "scale"))
            self.require_current()
            record = resource_record(SCALE_RESOURCE, data, self.target.namespace)
            self.target.require_current(self.target.session, uid=record.uid or "")
            if record.name != self.target.name:
                raise AppError("Scale read returned a different target.")
            return record
        if self.operation in {WorkloadAction.RESTART, WorkloadAction.ROLLBACK}:
            require_rolling(parent)
        if self.history is not None:
            path, uid, version = self.history
            data = await self.client.get_json(path)
            self.require_current()
            metadata = resource_object(data.get("metadata"))
            if (
                metadata.get("uid") != uid
                or metadata.get("resourceVersion") != version
                or not controlled_by(data, self.target)
            ):
                raise AppError(
                    "Selected rollback history changed or disappeared. Review a fresh revision."
                )
        return parent

    async def prepare(self, operation: WorkloadAction, argument: str = "") -> MutationIntent:
        self.intent = None
        self._confirmation = self._approved_intent = None
        self.operation, self.history = operation, None
        self.require_current()
        if operation is WorkloadAction.STATUS:
            raise AppError("Status is read-only; no mutation can be prepared.")
        count = (
            replica_count(argument)
            if operation in {WorkloadAction.SCALE, WorkloadAction.ROLLBACK}
            else 0
        )
        if operation is WorkloadAction.ROLLBACK and count == 0:
            raise AppError("Choose an explicit positive rollback revision.")
        record = await self._read()
        if operation is WorkloadAction.SCALE:
            old = resource_object(record.manifest.get("spec")).get("replicas")
            if type(old) is not int or not 0 <= old <= 2147483647:
                raise AppError(
                    "Scale returned an invalid current replica count; no write can be reviewed."
                )
            if old == count:
                raise AppError("Replica count is unchanged; no write is needed.")
            self.preview = f"Scale replicas {old} → {count}. Zero stops all workload replicas."
            if count < old and self._scale_storage_delete:
                self.preview += (
                    " This StatefulSet's retention policy deletes PVCs for scaled-down pods."
                )
            self.intent = patch_intent(
                self.resource,
                self.target,
                record,
                [{"op": "add", "path": "/spec/replicas", "value": count}],
                subresource="scale",
            )
        elif operation is WorkloadAction.RESTART:
            self.preview = "Restart by updating the pod-template timestamp; Kubernetes replaces pods according to its strategy."
            self.intent = restart_intent(self.resource, self.target, record, datetime.now(UTC))
        else:
            family = "replicasets" if self.resource.name == "deployments" else "controllerrevisions"
            root = f"/apis/apps/{self.resource.version}/namespaces/{self.target.namespace}/{family}"
            candidates = []
            for item in await self._items(root):
                if controlled_by(item, self.target):
                    revision, template = revision_template(item, self.resource)
                    if revision == count:
                        candidates.append((item, template))
            if len(candidates) != 1:
                raise AppError(
                    "Rollback revision is absent or ambiguous. Inspect retained controller history."
                )
            item, template = candidates[0]
            if resource_object(record.manifest.get("spec")).get("template") == template:
                raise AppError("Revision template is already current; no write is needed.")
            metadata = resource_object(item.get("metadata"))
            uid, version = metadata.get("uid"), metadata.get("resourceVersion")
            if not isinstance(uid, str) or not uid or not isinstance(version, str) or not version:
                raise AppError("Rollback history requires a UID and resource version.")
            self.history = root + "/" + api_segment(metadata.get("name")), uid, version
            self.preview = f"Restore pod template from explicit revision {count}. Replica count and workload strategy remain current."
            self.intent = patch_intent(
                self.resource,
                self.target,
                record,
                [{"op": "add", "path": "/spec/template", "value": template}],
            )
        return self.intent

    async def monitor(
        self,
        update: Callable[[RolloutProgress], None],
        *,
        timeout: float = 300,
        interval: float = 0.5,
    ) -> RolloutProgress:
        if not 0 < timeout <= 3600 or not 0 < interval <= 30:
            raise AppError("Rollout monitoring requires bounded positive timing.")
        try:
            async with asyncio.timeout(timeout):
                while True:
                    progress = rollout_progress(
                        self.resource, await self.read_parent(read_only=True)
                    )
                    update(progress)
                    if progress.terminal:
                        return progress
                    await asyncio.sleep(interval)
        except TimeoutError:
            progress = RolloutProgress(
                "Timed out", "Monitoring timed out; the server operation was not undone.", True
            )
            update(progress)
            return progress
