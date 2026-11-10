"""Owned local sources and a public manifest-adapter port for Pilot workflows."""

import asyncio
import copy
import json
from types import SimpleNamespace

from textual.app import App
from textual.widgets import Static

from kuberich.adapters.manifests import ManifestValidation
from kuberich.domain.manifests import ManifestScope, canonical_manifest
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.resources import ApiResource, Discovery, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import MutationManager
from tests.support.workspace import wait_for

RESOURCE = ApiResource(
    "", "v1", "configmaps", "ConfigMap", True, frozenset({"get", "create", "patch", "delete"})
)


class OwnedClient:
    context = SimpleNamespace(name="owned-manifest-ui")


class ManifestTestApp(App):
    def __init__(self, screen):
        super().__init__()
        self.initial_screen = screen

    def compose(self):
        yield Static("Owned manifest test workspace")

    def on_mount(self):
        self.push_screen(self.initial_screen)


class ManifestUiAdapter:
    def __init__(self):
        self.values = {}
        self.reads = []
        self.writes = []
        self.validations = []
        self.validation_state = MutationState.SUCCEEDED
        self.write_states = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.stall = False
        self.stall_validation = False
        self.stall_observation = False
        self.observing = asyncio.Event()
        self.closed = False

    async def read(self, resource, address, guard):
        guard()
        self.reads.append(address)
        if self.stall_observation and self.writes and address.name == self.writes[-1].target.name:
            self.observing.set()
            await self.release.wait()
        value = self.values.get(address.name)
        return resource_record(resource, value, address.namespace) if value is not None else None

    async def preview_update(self, resource, target, desired, baseline, guard):
        guard()
        value = json.loads(desired)
        value["metadata"].update(copy.deepcopy(baseline.manifest["metadata"]))
        value["metadata"].setdefault("labels", {})["example.io/reviewed"] = "yes"
        return ManifestValidation(
            MutationResult(self.validation_state, "Safe helper preview"), canonical_manifest(value)
        )

    async def validate(self, intent, guard):
        guard()
        self.validations.append(intent)
        self.entered.set()
        if self.stall_validation:
            await self.release.wait()
        guard()
        value = json.loads(intent.body)
        if not isinstance(value, dict) or value.get("kind") == "DeleteOptions":
            value = self.values[intent.target.name]
        return ManifestValidation(
            MutationResult(self.validation_state, "Strict dry-run completed"),
            canonical_manifest(value),
        )

    async def execute(self, intent, guard):
        guard()
        self.writes.append(intent)
        self.entered.set()
        if self.stall:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                return MutationResult(
                    MutationState.UNCERTAIN, "Request admitted; inspect before retry."
                )
        return MutationResult(
            self.write_states.pop(0) if self.write_states else MutationState.SUCCEEDED,
            "Owned API outcome",
        )

    async def close(self):
        self.closed = True


async def review_fixture(tmp_path, *, count=1, existing=False, namespace="team", read_only=False):
    for index in range(count):
        (tmp_path / f"{index}.yaml").write_text(
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": f"owned-{index}"},
                    "data": {"private": "manifest-ui-sensitive-value"},
                }
            )
        )
    local = LocalManifestService(AccessPolicy(read_only), {}, tmp_path)
    await local.open_root(tmp_path)
    source = await local.capture("", "directory")
    adapter = ManifestUiAdapter()
    if existing:
        for document in source.documents:
            value = json.loads(document.body)
            value["metadata"].update(
                namespace=namespace or "team",
                uid="uid-" + document.name,
                resourceVersion="opaque-version-7",
            )
            adapter.values[document.name] = value
    current = [True]
    service = ManifestMutationService(
        OwnedClient(),
        ManifestScope(session=SessionIdentity("owned-manifest-ui", 1), namespace=namespace),
        Discovery((RESOURCE,)),
        local.policy,
        source,
        lambda: current[0] and local.current_source is source,
        lambda: local.require_source(source),
        {},
        tmp_path,
        adapter=adapter,
    )
    return local, service, adapter, MutationManager(), current


async def click_ready(app, pilot, button):
    async with asyncio.timeout(5):
        assert await app.screen.wait_for_refresh()
        await wait_for(
            lambda: (
                button.is_attached
                and button.visible
                and not button.disabled
                and not button.has_class("-active")
                and button.region.area > 0
                and app.get_widget_at(*button.region.center)[0] is button
            )
        )
        assert await pilot.click(button)
