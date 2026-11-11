"""A controlled UI port; native Helm lifecycle evidence belongs to the owned verifier."""

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from textual.app import App
from textual.widgets import Static

from kuberich.domain.helm import (
    HelmApproval,
    HelmDriver,
    HelmOutcome,
    HelmReleaseKey,
    HelmRequest,
    HelmScope,
)
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.helm_lifecycle import (
    HelmLifecycleIntent,
    HelmOperationObservation,
    HelmValuesDisclosureIntent,
    HelmValuesLease,
)
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from tests.support.helm_catalog import chart_package


def ui_chart():
    values = b"message: owned-ui\npassword: owned-private-value\n"
    package = chart_package(values=values)
    return ChartSnapshot(
        "owned-chart",
        "1.0.0",
        "https://owned.invalid/charts",
        hashlib.sha256(package).hexdigest(),
        package,
        values,
    )


class LifecycleTestApp(App):
    def __init__(self, screen):
        super().__init__()
        self.initial_screen = screen

    def compose(self):
        yield Static("Owned Helm UI workspace")

    def on_mount(self):
        self.push_screen(self.initial_screen)


class LifecycleUiPort:
    def __init__(self, *, read_only=False):
        self.policy = AccessPolicy(read_only)
        self.request = HelmRequest(
            HelmScope(SessionIdentity("owned-lifecycle-ui", 1), "team", HelmDriver.SECRET), 1
        )
        self.address = HelmReleaseKey("team", "owned-chart")
        self.current_scope = True
        self.review = None
        self.approval = None
        self.cancellations = 0
        self.preparations = []
        self.values_sources = []
        self.confirmations = 0
        self.admissions = 0
        self.executions = 0
        self.drafts_closed = 0
        self.block_prepare = False
        self.block_execute = False
        self.prepare_entered = asyncio.Event()
        self.execute_entered = asyncio.Event()
        self.release = asyncio.Event()
        self.failure = None
        self.editor_directory = None
        self.editor_intent = None
        self.editor_approval = None
        self.editor_events = []
        self.editor_failure = None
        self.hold_close = False
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()

    def current(self, request):
        return self.current_scope and request == self.request

    def cancel_review(self):
        self.cancellations += 1
        self.review = None
        self.approval = None

    async def create_values(self, request, address, chart, *, source):
        self.policy.require(Action.MUTATE)
        self.values_sources.append(source)
        return HelmValuesLease(uuid4(), hashlib.sha256(b"{}\n").hexdigest(), source)

    async def prepare_lifecycle(self, request, address, operation, *, chart, values, options):
        self.policy.require(Action.MUTATE)
        self.preparations.append((request, address, operation, options, values))
        self.prepare_entered.set()
        if self.block_prepare:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        self.review = HelmLifecycleIntent(
            uuid4(),
            request,
            address,
            operation,
            options,
            ("Owned UI effect; no native execution is simulated by this port.",),
            "live/configmap/owned -> rendered/configmap/owned: safe diff",
            "passed",
        )
        return self.review

    def confirm_lifecycle(self, intent):
        self.policy.require(Action.MUTATE)
        if intent is not self.review:
            raise AppError("Review expired.")
        self.confirmations += 1
        self.approval = HelmApproval(intent.identity, uuid4())
        return self.approval

    def execute_lifecycle(self, approval):
        if approval is not self.approval:
            raise AppError("Approval expired.")
        self.admissions += 1
        self.approval = None
        self.review = None

        async def execute():
            self.executions += 1
            self.execute_entered.set()
            if self.block_execute:
                await self.release.wait()
            return HelmOperationObservation(
                HelmOutcome.SUCCEEDED, "UI port completed", may_have_started=True
            )

        return asyncio.create_task(execute())

    async def close_values_editor(self):
        self.drafts_closed += 1
        self.close_entered.set()
        if self.hold_close:
            await self.close_release.wait()
        self.editor_intent = None
        self.editor_approval = None
        if self.editor_directory is not None:
            (self.editor_directory / "values.yaml").unlink(missing_ok=True)

    async def prepare_values_editor(self, values):
        self.policy.require(Action.MUTATE)
        self.editor_events.append("prepare")
        self.editor_intent = HelmValuesDisclosureIntent(uuid4(), self.request, self.address, values)
        return self.editor_intent

    def confirm_values_editor(self, intent):
        if intent is not self.editor_intent:
            raise AppError("Editor disclosure expired.")
        self.editor_events.append("confirm")
        self.editor_approval = HelmApproval(intent.identity, uuid4())
        return self.editor_approval

    async def open_values_editor(self, approval):
        if approval is not self.editor_approval:
            raise AppError("Editor approval expired.")
        self.editor_approval = None
        self.editor_events.append("open")
        directory = Path(self.editor_directory)
        (directory / "values.yaml").write_text("private: owned-editor-private-value\n")
        if self.editor_failure == "open":
            raise AppError("Owned editor preparation refused.")
        return ProcessCommand(
            ("/bin/true", str(directory / "values.yaml")),
            (),
            directory,
            ProcessMode.FOREGROUND,
            ProcessPurpose.EDITOR,
        )

    def require_values_editor_current(self):
        if not self.current_scope:
            raise AppError("Editor scope expired.")

    async def finish_values_editor(self):
        self.editor_events.append("finish")
        if self.editor_failure == "finish":
            raise AppError("Owned editor output refused.")
        return HelmValuesLease(uuid4(), hashlib.sha256(b"edited: true\n").hexdigest(), "edited")
