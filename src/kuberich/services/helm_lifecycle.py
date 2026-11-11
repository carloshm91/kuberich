"""One captured Helm owner's immutable reviews, editor leases and observed effects."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from kuberich.adapters.editing import ManifestFile, file_worker
from kuberich.adapters.helm import HelmExecutionCancelled, HelmExecutionProblem
from kuberich.adapters.helm_files import HelmCommandFiles
from kuberich.adapters.helm_live import (
    HelmLiveObject,
    live_objects,
    manifest_destinations,
    namespace_identity,
    require_release_ownership,
)
from kuberich.adapters.manifests import ManifestAdapter
from kuberich.domain.editing import editor_arguments
from kuberich.domain.helm import (
    HelmApproval,
    HelmOutcome,
    HelmProblem,
    HelmReleaseKey,
    HelmRequest,
    HelmStorageIdentity,
)
from kuberich.domain.helm_archive import chart_crd_files
from kuberich.domain.helm_catalog import ChartSnapshot, validate_chart_snapshot
from kuberich.domain.helm_lifecycle import (
    HelmLifecycleIntent,
    HelmLifecycleKind,
    HelmLifecycleOptions,
    HelmOperationObservation,
    HelmRenderedRelease,
    HelmValuesDisclosureIntent,
    HelmValuesLease,
    fingerprint,
    helm_owned_manifest,
    live_diff,
    manifest_objects,
    resource_observation,
    values_bytes,
)
from kuberich.domain.manifests import ManifestCreateIntent, canonical_manifest
from kuberich.domain.mutations import MutationState
from kuberich.domain.processes import ProcessCommand, editor_command
from kuberich.domain.targets import ResourceAddress
from kuberich.errors import AppError
from kuberich.services.access import Action
from kuberich.services.resources import parse_owned

if TYPE_CHECKING:
    from kuberich.services.helm import HelmService


@dataclass(slots=True, repr=False)
class _Plan:
    intent: HelmLifecycleIntent
    namespace_uid: str
    history: tuple[HelmStorageIdentity, ...]
    live: tuple[HelmLiveObject, ...]
    documents: tuple[dict[str, Any], ...]
    desired_paths: frozenset[str]
    files: HelmCommandFiles
    chart: ChartSnapshot | None
    rendered_digest: str
    catalog_generation: int
    create_previews: tuple[tuple[ManifestCreateIntent, str], ...]


def _render_digest(rendered: HelmRenderedRelease | None) -> str:
    return (
        fingerprint(b"")
        if rendered is None
        else fingerprint(
            rendered.manifest
            + b"\0"
            + b"\0".join(rendered.hooks)
            + b"\0"
            + b"\0".join(value.encode() for value in rendered.hook_effects)
            + b"\0"
            + rendered.apply_method.encode()
        )
    )


class HelmLifecycle:
    """A collaborator of HelmService, sharing its client, adapter and task owner."""

    def __init__(self, owner: HelmService, environment: dict[str, str], directory: Path) -> None:
        self.owner, self.environment, self.directory = owner, environment, directory
        self.plan: _Plan | None = None
        self.approval: HelmApproval | None = None
        self.disclosure: HelmValuesDisclosureIntent | None = None
        self.disclosure_approval: HelmApproval | None = None
        self.values: (
            tuple[
                HelmValuesLease,
                HelmRequest,
                HelmReleaseKey,
                bytes,
                str,
                tuple[HelmStorageIdentity, ...],
            ]
            | None
        ) = None
        self.editor: ManifestFile | None = None
        self.editor_request: HelmRequest | None = None
        self.files: set[HelmCommandFiles] = set()
        self.last: HelmOperationObservation | None = None
        self._execution_lock = asyncio.Lock()
        self._admission = ManifestAdapter(owner.client, owner.policy, environment, directory)

    async def _validate_creates(
        self, previews: tuple[tuple[ManifestCreateIntent, str], ...], guard: Any
    ) -> None:
        for create, _ in previews:
            guard()
            validation = await self._admission.validate(create, guard)
            guard()
            if validation.result.state is not MutationState.SUCCEEDED:
                raise HelmProblem(
                    "forbidden"
                    if validation.result.state is MutationState.DENIED
                    else "unavailable",
                    "Kubernetes named-create admission dry-run was refused; no release write was sent.",
                )

    def retire(self) -> None:
        self.plan, self.approval, self.disclosure, self.disclosure_approval = None, None, None, None

    def _check(self, request: HelmRequest) -> None:
        self.owner._check(request, mutate=True)

    async def _history(
        self, request: HelmRequest, address: HelmReleaseKey, guard: Any
    ) -> tuple[HelmStorageIdentity, ...]:
        history = await self.owner._adapter.storage_history(request, address, guard)
        guard()
        if history:
            exact = await self.owner._adapter.storage_identity(
                request, address, history[-1].revision, guard
            )
            if exact != history[-1]:
                raise HelmProblem("stale", "Helm storage changed; prepare a fresh review.")
        return history

    async def _clear_files(self) -> None:
        failures: list[BaseException] = []
        for files in tuple(self.files):
            try:
                await file_worker(files.close)
            except BaseException as error:
                failures.append(error)
            else:
                self.files.discard(files)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("Helm private input cleanup could not be verified.", failures)

    async def prepare(
        self,
        request: HelmRequest,
        address: HelmReleaseKey,
        operation: HelmLifecycleKind,
        chart: ChartSnapshot | None,
        values: HelmValuesLease | None,
        options: HelmLifecycleOptions,
    ) -> HelmLifecycleIntent:
        self._check(request)
        self.owner.require_helm_idle()
        if request.scope.namespace is None and operation is HelmLifecycleKind.INSTALL:
            raise AppError("Choose a concrete namespace before installing a Helm release.")
        if request.scope.namespace not in {None, address.namespace}:
            raise AppError("Helm release address differs from the selected namespace.")
        if not isinstance(operation, HelmLifecycleKind) or not isinstance(
            options, HelmLifecycleOptions
        ):
            raise AppError("Choose a supported Helm operation and reviewed options.")
        catalog_generation = self.owner.catalog.snapshot.generation
        if chart is not None and chart.catalog_generation != catalog_generation:
            raise AppError(
                "Helm chart selection is stale; select its version from the current catalog."
            )
        generation = self.owner._new_intent()
        session_guard = self.owner._guard(request, intent_generation=generation, mutate=True)

        def guard() -> None:
            session_guard()
            if self.owner.catalog.snapshot.generation != catalog_generation:
                raise AppError("Helm catalog changed; select and review a fresh chart.")

        async def run() -> HelmLifecycleIntent:
            guard()
            await self._clear_files()
            await self.owner.catalog.revalidate(catalog_generation)
            guard()
            uid = await namespace_identity(self.owner.client, address.namespace, guard)
            history = await self._history(request, address, guard)
            previous: HelmRenderedRelease | None = None
            if operation is HelmLifecycleKind.INSTALL:
                if history:
                    raise AppError(
                        "Helm release history already exists; choose a new release name."
                    )
                await self.owner._adapter.reserved_storage_absent(request, address, guard)
            else:
                if not history or history[-1].status not in {"deployed", "failed"}:
                    raise AppError(
                        "Upgrade/uninstall requires an exact deployed or failed release head."
                    )
                previous = await self.owner._adapter.release_content(
                    request, address, history[-1].revision, guard
                )
            data = None
            if operation is not HelmLifecycleKind.UNINSTALL:
                if not isinstance(chart, ChartSnapshot):
                    raise AppError("Select an immutable catalog chart before preparing a release.")
                await parse_owned(partial(validate_chart_snapshot, chart))
                data = chart.default_values
                if values is not None:
                    captured = self.values
                    if (
                        captured is None
                        or values is not captured[0]
                        or request != captured[1]
                        or address != captured[2]
                        or chart.sha256 != captured[4]
                        or (captured[5] and captured[5] != history)
                    ):
                        raise AppError("Helm values lease expired; choose a fresh values source.")
                    data = captured[3]
                await parse_owned(partial(values_bytes, data))
            files = await file_worker(
                lambda: HelmCommandFiles(
                    Path(self.owner.client.directory.name),
                    package=chart.package
                    if chart is not None and operation is not HelmLifecycleKind.UNINSTALL
                    else None,
                    values=data,
                ),
                discard=lambda result: result.close(),
            )
            self.files.add(files)
            guard()
            rendered = await self.owner._adapter.lifecycle_preview(
                request, address, operation, options, files, guard
            )
            desired = (
                await parse_owned(partial(manifest_objects, rendered.manifest))
                if rendered is not None
                else ()
            )
            old = (
                await parse_owned(partial(manifest_objects, previous.manifest))
                if previous is not None
                else ()
            )
            # Each address is read once, while duplicate destinations inside either manifest fail.
            desired_live = await live_objects(
                self.owner.client, request, desired, guard, default_namespace=address.namespace
            )
            old_live = await live_objects(
                self.owner.client,
                request,
                old,
                guard,
                default_namespace=address.namespace,
                known=desired_live,
            )
            desired = tuple(
                [
                    await parse_owned(
                        partial(helm_owned_manifest, document, address, item.namespace)
                    )
                    for item, document in zip(desired_live, desired, strict=True)
                ]
            )
            desired_by_path = {
                item.path: (item, document)
                for item, document in zip(desired_live, desired, strict=True)
            }
            all_live = {item.path: item for item in old_live}
            all_live.update({item.path: item for item in desired_live})
            create_previews: list[tuple[ManifestCreateIntent, str]] = []
            create_paths: set[str] = set()
            csa_create = operation is HelmLifecycleKind.INSTALL or (
                previous is not None and previous.apply_method in {"", "csa"}
            )
            if csa_create:
                for item, document in zip(desired_live, desired, strict=True):
                    if item.body is not None:
                        continue
                    if "create" not in item.resource.verbs:
                        raise AppError("Helm destination does not advertise named creation.")
                    body = await parse_owned(partial(canonical_manifest, document))
                    if len(body) > 1024 * 1024:
                        raise AppError(
                            "Named Helm create admission previews support resources of at most 1 MiB."
                        )
                    target = ResourceAddress(
                        request.scope.session,
                        item.resource.group,
                        item.resource.name,
                        item.namespace,
                        item.name,
                    )
                    create_previews.append(
                        (
                            ManifestCreateIntent(
                                identity=uuid4(), target=target, resource=item.resource, body=body
                            ),
                            item.label,
                        )
                    )
                    create_paths.add(item.path)
            await self._validate_creates(tuple(create_previews), guard)
            for item in all_live.values():
                if operation is HelmLifecycleKind.INSTALL and item.body is not None:
                    raise AppError(
                        "A rendered Helm destination already exists; install cannot adopt it."
                    )
                if operation is not HelmLifecycleKind.INSTALL:
                    require_release_ownership(item, address)
            preview = []
            effects = [
                f"{operation.value.capitalize()} release {address.namespace}/{address.name}.",
                "Hooks enabled: reviewed in-cluster code may create additional effects."
                if options.run_hooks
                else "Hooks disabled.",
                "CRDs are skipped and must already be served; CRDs can outlive uninstall.",
                "Native Helm preparation is not complete admission simulation or a transactional patch preview.",
                "Supplemental named-create admission checks are separate dryRun=All POSTs; individual passes do not reserve whole-batch quota. Update/SSA/delete admission is not simulated.",
                "Final rendering, concurrent changes, admission and partial effects remain possible; writes are never retried automatically.",
                f"Per-operation timeout {options.timeout_seconds}s; whole-command deadline is separate.",
                "Automatic rollback, failure cleanup, adoption, dependency downloads and forced conflicts are disabled.",
            ]
            if operation is HelmLifecycleKind.UNINSTALL:
                effects += [
                    "Retain uninstalled release history."
                    if options.keep_history
                    else "Purge release history; later name reuse requires a new review.",
                    f"Deletion propagation: {options.cascade}; finalizers, PVCs and kept resources may remain.",
                ]
            elif rendered is not None:
                effects += [
                    "New Helm 4 installs use explicit client-side apply; upgrades preserve the observed release method."
                ]
            if chart is not None and operation is not HelmLifecycleKind.UNINSTALL:
                crd_files = await parse_owned(
                    partial(
                        chart_crd_files,
                        chart.package,
                        expected_name=chart.name,
                        expected_version=chart.version,
                    )
                )
                effects.extend(
                    "Skip cluster-scoped chart CRD file " + name + "." for name in crd_files
                )
            elif previous is not None:
                effects.append(
                    "Stored release JSON does not expose a complete bundled-subchart CRD inventory; CRDs are never deleted by this uninstall."
                )
            for path, item in all_live.items():
                desired_object = desired_by_path[path][1] if path in desired_by_path else None
                preview.append(
                    await parse_owned(partial(live_diff, item.body, desired_object, item.label))
                )
                effects.append(
                    (
                        "Create "
                        if item.body is None
                        else "Review "
                        if desired_object is not None
                        else "Remove/retain "
                    )
                    + item.label
                    + (
                        " · named-create admission passed"
                        if path in create_paths
                        else " · final update/delete/SSA admission not simulated"
                    )
                )
                effect_body = desired_object if desired_object is not None else item.body
                if effect_body is not None:
                    meta = effect_body["metadata"]
                    annotations = meta.get("annotations", {})
                    if (
                        isinstance(annotations, dict)
                        and annotations.get("helm.sh/resource-policy") == "keep"
                    ):
                        effects.append(
                            "Resource-policy keep can retain " + item.label + " after removal."
                        )
                if item.body is not None and item.body["metadata"].get("finalizers"):
                    effects.append("Finalizers can delay removal of " + item.label + ".")
                if item.resource.kind == "PersistentVolumeClaim":
                    effects.append("PVC data and bound storage can outlive " + item.label + ".")
            hook_release = previous if operation is HelmLifecycleKind.UNINSTALL else rendered
            if hook_release is not None:
                hooks: list[tuple[dict[str, Any], str]] = []
                for hook, details in zip(
                    hook_release.hooks, hook_release.hook_effects, strict=True
                ):
                    hooks.extend(
                        (document, details)
                        for document in await parse_owned(partial(manifest_objects, hook))
                    )
                    if len(hooks) > 256:
                        raise AppError("Helm hook review exceeds its document limit.")
                destinations = await manifest_destinations(
                    self.owner.client,
                    request,
                    tuple(document for document, _ in hooks),
                    guard,
                    default_namespace=address.namespace,
                )
                for destination, (document, details) in zip(destinations, hooks, strict=True):
                    effects.append("Hook " + destination.label + ": " + details)
                    preview.append(
                        "Hook (separate from ordinary resources):\n"
                        + await parse_owned(partial(live_diff, None, document, destination.label))
                    )
            if (
                await namespace_identity(self.owner.client, address.namespace, guard) != uid
                or await self._history(request, address, guard) != history
            ):
                raise AppError(
                    "Helm namespace or storage changed during preparation; review again."
                )
            guard()
            intent = HelmLifecycleIntent(
                uuid4(),
                request,
                address,
                operation,
                options,
                tuple(effects),
                "".join(preview),
                "Native Helm dry-run passed; live desired-state comparison is separate from final Helm apply/admission.",
            )
            self.plan = _Plan(
                intent,
                uid,
                history,
                tuple(all_live.values()),
                tuple(
                    (
                        *desired,
                        *[
                            document
                            for document, item in zip(old, old_live, strict=True)
                            if item.path not in desired_by_path
                        ],
                    )
                ),
                frozenset(desired_by_path),
                files,
                chart,
                _render_digest(rendered),
                catalog_generation,
                tuple(create_previews),
            )
            return intent

        async def serialized() -> HelmLifecycleIntent:
            async with self._execution_lock:
                try:
                    return await run()
                except BaseException:
                    await self._clear_files()
                    raise

        return await self.owner._own(self.owner._bounded(serialized))

    def confirm(self, intent: HelmLifecycleIntent) -> HelmApproval:
        self._check(intent.request)
        self.owner.require_helm_idle()
        if self.plan is None or intent is not self.plan.intent or self.approval is not None:
            raise AppError("Helm lifecycle review expired; prepare it again.")
        self.approval = HelmApproval(intent.identity, uuid4())
        return self.approval

    def execute(self, approval: HelmApproval) -> asyncio.Task[HelmOperationObservation]:
        plan = self.plan
        expected = self.approval
        # Every submission retires pending authority, including a forged token.
        self.owner._retire_intent()
        if plan is None or approval is not expected:
            if plan is not None:
                self.owner.start_helm_cleanup(self._discard_plan(plan))
            raise AppError("Helm lifecycle confirmation is missing or already consumed.")
        try:
            self._check(plan.intent.request)
            self.owner.require_helm_idle()
        except BaseException:
            self.owner.start_helm_cleanup(self._discard_plan(plan))
            raise
        self.last = HelmOperationObservation(
            HelmOutcome.BLOCKED, "Helm operation admitted; no write has been launched."
        )
        task = self.owner.admit_helm_write(self._execute(plan))

        def completed(operation: asyncio.Task[HelmOperationObservation]) -> None:
            # A Task cancelled before its coroutine enters cannot execute finally.
            if plan.files in self.files:
                self.owner.start_helm_cleanup(self._discard_plan(plan))
            if operation.cancelled() and self.last is not None and not self.last.may_have_started:
                self.last = HelmOperationObservation(
                    HelmOutcome.BLOCKED, "Helm operation cancelled before launch."
                )

        task.add_done_callback(completed)
        return task

    async def _discard_plan(self, plan: _Plan) -> None:
        async with self._execution_lock:
            await file_worker(plan.files.close)
            self.files.discard(plan.files)

    async def _execute(self, plan: _Plan) -> HelmOperationObservation:
        async with self._execution_lock:
            return await self._execute_unlocked(plan)

    async def _execute_unlocked(self, plan: _Plan) -> HelmOperationObservation:
        intent = plan.intent
        guard = self.owner._guard(intent.request, mutate=True)
        started = False
        failure: HelmExecutionProblem | None = None
        try:
            async with asyncio.timeout(120):
                if self.owner.catalog.snapshot.generation != plan.catalog_generation:
                    raise AppError("Helm catalog changed; prepare a fresh review.")
                await self.owner.catalog.revalidate(plan.catalog_generation)
                guard()
                if plan.chart is not None:
                    await parse_owned(partial(validate_chart_snapshot, plan.chart))
                if (
                    await namespace_identity(self.owner.client, intent.address.namespace, guard)
                    != plan.namespace_uid
                    or await self._history(intent.request, intent.address, guard) != plan.history
                ):
                    raise AppError("Helm namespace or storage changed; prepare a fresh review.")
                if intent.operation is HelmLifecycleKind.INSTALL:
                    await self.owner._adapter.reserved_storage_absent(
                        intent.request, intent.address, guard
                    )
                fresh = await live_objects(
                    self.owner.client,
                    intent.request,
                    plan.documents,
                    guard,
                    default_namespace=intent.address.namespace,
                )
                before = {item.path: (item.uid, item.resource_version) for item in plan.live}
                if {item.path: (item.uid, item.resource_version) for item in fresh} != before:
                    raise AppError("Helm live state changed; prepare and confirm a fresh diff.")
                preview = await self.owner._adapter.lifecycle_preview(
                    intent.request,
                    intent.address,
                    intent.operation,
                    intent.options,
                    plan.files,
                    guard,
                )
                if _render_digest(preview) != plan.rendered_digest:
                    raise AppError("Helm rendering changed; prepare and confirm a fresh diff.")
                await self._validate_creates(plan.create_previews, guard)
                guard()
            self.last = HelmOperationObservation(
                HelmOutcome.UNKNOWN,
                "Helm operation may have started; cancellation does not undo cluster effects.",
                may_have_started=True,
            )
            started = True
            try:
                await self.owner._adapter.lifecycle_execute(
                    intent.request,
                    intent.address,
                    intent.operation,
                    intent.options,
                    plan.files,
                    guard,
                )
            except HelmExecutionProblem as error:
                started = error.may_have_started
                failure = error
                if not started or not error.completed:
                    return self._outcome(
                        HelmOutcome.UNKNOWN if started else HelmOutcome.BLOCKED,
                        "Helm outcome is uncertain; observe the release without replaying the write."
                        if started
                        else str(error),
                        started,
                    )
            return await self._observe(plan, guard, failure)
        except HelmExecutionCancelled as error:
            self.last = HelmOperationObservation(
                HelmOutcome.UNKNOWN if error.may_have_started else HelmOutcome.BLOCKED,
                "Helm operation cancelled; observe possible effects before another review."
                if error.may_have_started
                else "Helm operation cancelled before launch.",
                may_have_started=error.may_have_started,
            )
            raise
        except asyncio.CancelledError:
            self.last = HelmOperationObservation(
                HelmOutcome.UNKNOWN if started else HelmOutcome.BLOCKED,
                "Helm operation cancelled; observe possible effects before another review."
                if started
                else "Helm operation cancelled before launch.",
                may_have_started=started,
            )
            raise
        except (AppError, TimeoutError):
            return self._outcome(
                HelmOutcome.UNKNOWN if started else HelmOutcome.STALE,
                "Helm outcome could not be verified; observe history before another review."
                if started
                else "Helm inputs, identity, policy or preparation changed; no write was sent. Prepare a fresh review.",
                started,
            )
        finally:
            await file_worker(plan.files.close)
            self.files.discard(plan.files)

    def _outcome(
        self, outcome: HelmOutcome, message: str, started: bool
    ) -> HelmOperationObservation:
        self.last = HelmOperationObservation(outcome, message, may_have_started=started)
        return self.last

    async def _observe(
        self, plan: _Plan, guard: Any, failure: HelmExecutionProblem | None
    ) -> HelmOperationObservation:
        intent = plan.intent
        async with asyncio.timeout(120):
            history = await self._history(intent.request, intent.address, guard)
            observed = None
            if intent.operation is HelmLifecycleKind.UNINSTALL:
                if (
                    intent.options.keep_history
                    and (
                        not history
                        or history[-1].revision != plan.history[-1].revision
                        or history[-1].status != "uninstalled"
                    )
                ) or (not intent.options.keep_history and history):
                    raise AppError("Helm uninstall storage outcome is not verified.")
            else:
                expected = plan.history[-1].revision + 1 if plan.history else 1
                status = "failed" if failure is not None else "deployed"
                listing = await self.owner._adapter.list(intent.request, guard)
                observed = next(
                    (row for row in listing.releases if row.key == intent.address), None
                )
                if (
                    not history
                    or history[-1].revision != expected
                    or history[-1].status != status
                    or observed is None
                    or observed.revision != expected
                    or observed.status != status
                ):
                    raise AppError("Helm resulting revision is not verified.")
            resources = await live_objects(
                self.owner.client,
                intent.request,
                plan.documents,
                guard,
                default_namespace=intent.address.namespace,
            )
            facts = tuple(
                resource_observation(
                    item.label,
                    item.body,
                    intent.address,
                    removed=intent.operation is HelmLifecycleKind.UNINSTALL
                    or item.path not in plan.desired_paths,
                )
                for item in resources
            )
            guard()
            self.last = HelmOperationObservation(
                HelmOutcome.FAILED if failure else HelmOutcome.SUCCEEDED,
                "Helm failed and the resulting failed revision was observed; partial resources may remain."
                if failure
                else "Helm resulting release storage was verified; inspect separate resource retention observations.",
                observed,
                True,
                facts,
            )
            return self.last

    async def create_values(
        self, request: HelmRequest, address: HelmReleaseKey, chart: ChartSnapshot, *, source: str
    ) -> HelmValuesLease:
        self._check(request)
        self.owner.require_helm_idle()
        if chart.catalog_generation != self.owner.catalog.snapshot.generation:
            raise AppError(
                "Helm chart selection is stale; select its version from the current catalog."
            )
        guard = self.owner._guard(request, mutate=True)

        async def run() -> HelmValuesLease:
            await parse_owned(partial(validate_chart_snapshot, chart))
            history: tuple[HelmStorageIdentity, ...] = ()
            if source == "defaults":
                data = chart.default_values
            elif source == "supplied":
                history = await self._history(request, address, guard)
                if not history:
                    raise AppError("Current supplied values require an existing release.")
                content = await self.owner._adapter.release_content(
                    request, address, history[-1].revision, guard
                )
                data = content.values
                if await self._history(request, address, guard) != history:
                    raise AppError("Helm supplied values changed while reading.")
            else:
                raise AppError("Choose chart defaults or fresh current supplied values.")
            await parse_owned(partial(values_bytes, data))
            guard()
            lease = HelmValuesLease(uuid4(), fingerprint(data), source)
            self.values = lease, request, address, data, chart.sha256, history
            self.owner._new_intent()
            return lease

        return await self.owner._own(self.owner._bounded(run))

    async def prepare_editor(self, lease: HelmValuesLease) -> HelmValuesDisclosureIntent:
        self.owner.policy.require(Action.MUTATE)
        if self.values is None or lease is not self.values[0]:
            raise AppError("Choose a fresh Helm values source before editing.")
        self._check(self.values[1])
        self.owner.require_helm_idle()
        self.owner._new_intent()
        intent = HelmValuesDisclosureIntent(uuid4(), self.values[1], self.values[2], lease)
        self.disclosure = intent
        return intent

    def confirm_editor(self, intent: HelmValuesDisclosureIntent) -> HelmApproval:
        self._check(intent.request)
        if intent is not self.disclosure or self.disclosure_approval is not None:
            raise AppError("Helm editor disclosure expired.")
        self.disclosure_approval = HelmApproval(intent.identity, uuid4())
        return self.disclosure_approval

    def open_editor(self, approval: HelmApproval) -> asyncio.Task[ProcessCommand]:
        intent = self.disclosure
        if intent is None or approval is not self.disclosure_approval or self.values is None:
            raise AppError("Fresh one-use editor disclosure is required.")
        self.disclosure, self.disclosure_approval = None, None
        self._check(intent.request)
        self.editor_request = intent.request
        data = self.values[3]

        async def run() -> ProcessCommand:
            async with self._execution_lock:
                await self._close_editor_unlocked(clear_request=False)
                self.editor = await file_worker(
                    lambda: ManifestFile(data), discard=lambda value: value.close()
                )
                self.require_editor_current()
                return editor_command(
                    editor_arguments(self.environment),
                    self.editor.path,
                    environment=self.environment,
                    directory=self.directory,
                )

        return self.owner.start_helm_owned(run())

    def require_editor_current(self) -> None:
        if self.editor_request is None:
            raise AppError("Helm editor lease expired.")
        self._check(self.editor_request)

    async def finish_editor(self) -> HelmValuesLease:
        self.require_editor_current()
        if self.editor is None or self.values is None:
            raise AppError("Open the owned Helm values editor first.")

        async def run() -> HelmValuesLease:
            async with self._execution_lock:
                self.require_editor_current()
                assert self.editor is not None and self.values is not None
                try:
                    data = await file_worker(self.editor.read)
                    await parse_owned(partial(values_bytes, data))
                    self.require_editor_current()
                    prior = self.values
                    lease = HelmValuesLease(uuid4(), fingerprint(data), "edited")
                    self.values = lease, prior[1], prior[2], data, prior[4], prior[5]
                    self.owner._new_intent()
                    return lease
                finally:
                    await self._close_editor_unlocked()

        return await self.owner._own(run())

    async def close_editor(self, *, clear_request: bool = True) -> None:
        self.owner._new_intent()
        async with self._execution_lock:
            await self._close_editor_unlocked(clear_request=clear_request)

    async def _close_editor_unlocked(self, *, clear_request: bool = True) -> None:
        draft, self.editor = self.editor, None
        failures: list[BaseException] = []
        if draft is not None:
            try:
                await file_worker(draft.close)
            except BaseException as error:
                failures.append(error)
        if clear_request:
            self.editor_request = None
        try:
            await self._clear_files()
        except BaseException as error:
            failures.append(error)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup(
                "Helm editor and input cleanup could not be verified.", failures
            )

    async def close(self) -> None:
        self.retire()
        self.values = None
        failures: list[BaseException] = []
        for close in (self.close_editor, self._admission.close):
            try:
                await close()
            except BaseException as error:
                failures.append(error)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup(
                "Helm lifecycle shutdown could not be completely verified.", failures
            )
