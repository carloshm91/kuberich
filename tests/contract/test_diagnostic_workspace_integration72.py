"""Owned WorkspaceService diagnostics with real loopback API and injected external work."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from kuberich.domain.cluster_diagnostics import (
    MAX_DIAGNOSTIC_FINDINGS,
    MAX_DIAGNOSTIC_TEXT_BYTES,
    SOURCE_TEXT_RESERVE,
    DiagnosticScope,
    diagnose_record,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticSourceKind as Kind,
)
from kuberich.domain.cluster_diagnostics import (
    DiagnosticStatus as Status,
)
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.relationships import RelationshipMode, reference_for
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceSelection, ViewStatus
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.support.authorization import auth_request
from tests.support.authorization_ui import authorization_api
from tests.support.connections import catalog_fixture
from tests.support.diagnostic_api import DiagnosticAPI
from tests.support.diagnostic_native import NOW, PODS, record, snapshot, source
from tests.support.workspace import wait_for

pytestmark = pytest.mark.fast


def api_for():
    api = DiagnosticAPI()
    # The shared UI fixture supplies generic specs; native workload projection
    # requires the real Kubernetes template path rather than a Pod-shaped stub.
    for (group, plural, _, _), value in api.objects.items():
        if (
            group == "apps"
            and plural in {"deployments", "replicasets"}
            and "containers" in value["spec"]
        ):
            value["spec"] = {"template": {"spec": value["spec"]}}
    return api


def owner_for(tmp_path, url, **kwargs):
    return WorkspaceService(
        SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()), **kwargs
    )


def overview(owner):
    return DiagnosticScope(
        owner.sessions.observation.identity, owner.store.observation.connection.namespace
    )


def root_scope(owner, api, *, namespace="other", resource="deployments", name="root"):
    group = "apps" if resource != "pods" else ""
    served = owner.discovery.find(resource, group=group)
    obj = api.objects[(group, resource, namespace, name)]
    return DiagnosticScope(
        owner.sessions.observation.identity,
        namespace,
        reference_for(served, resource_record(served, obj)),
    )


def settled(owner):
    value = owner.store.observation.diagnostics
    return value is not None and not value.collecting and not owner.diagnostic_collecting


class External:
    def __init__(self, *, hold=False, cleanup=False, failure=None, wrong_request=False):
        self.calls = []
        self.hold, self.cleanup, self.failure, self.wrong_request = (
            hold,
            cleanup,
            failure,
            wrong_request,
        )
        self.entered, self.cancelled, self.release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

    async def __call__(
        self,
        client,
        discovery,
        request,
        current,
        *,
        max_findings,
        max_text_bytes,
        max_source_text_bytes,
    ):
        self.calls.append(
            (
                client,
                discovery,
                request,
                current,
                max_findings,
                max_text_bytes,
                max_source_text_bytes,
            )
        )
        self.entered.set()
        if self.hold:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                if self.cleanup:
                    await self.release.wait()
                # A late completed result must still fail the captured guard.
        if self.failure is not None:
            raise self.failure
        item = diagnose_record(
            PODS, record(status={"conditions": [{"type": "Ready", "status": "False"}]}), NOW
        )[0]
        finding = replace(
            item,
            key="external-" + str(len(self.calls)),
            source=Kind.POPEYE,
            evidence=tuple(replace(evidence, source=Kind.POPEYE) for evidence in item.evidence),
            tool_version="synthetic-v1",
        )
        result = snapshot(
            request,
            findings=(finding,),
            sources=(
                replace(
                    source(Kind.POPEYE, key="popeye", status=Status.READY),
                    resource=None,
                    namespace=request.scope.namespace,
                ),
            ),
        )
        result = replace(result, native_requests_used=0)
        return (
            replace(result, request=replace(request, revision=request.revision + 1))
            if self.wrong_request
            else result
        )


@pytest.mark.asyncio
async def test_native_enter_refresh_resolve_and_retire_real_sources_without_log_sampling(tmp_path):
    api = api_for()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_now=lambda: NOW)
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            await owner.select_diagnostics(overview(owner))
            await wait_for(lambda: settled(owner))
            value = owner.store.observation.diagnostics
            assert value.native_requests_used == 2 and value.findings
            assert owner.ownership.diagnostics_count == 1
            assert (
                owner.ownership.watch_count
                == owner.ownership.authorization_count
                == owner.ownership.relationships_count
                == owner.ownership.pulse_count
                == owner.ownership.metrics_count
                == 0
            )
            assert not api.log_reads
            ref = value.findings[0].subject
            assert (await owner.resolve_diagnostic(value.request, ref)).uid == ref.uid
            api.objects[("", "pods", ref.namespace, ref.name)]["metadata"]["uid"] = "replacement"
            with pytest.raises(AppError, match="replaced"):
                await owner.resolve_diagnostic(value.request, ref)
            previous = owner.diagnostic_request
            refresh = owner.refresh_diagnostics()
            assert owner.diagnostic_request.revision > previous.revision
            assert not owner.store.observation.diagnostics.findings
            await refresh
            await wait_for(lambda: settled(owner))
            await owner.select_resource(ResourceSelection())
            assert owner.diagnostic_request is None and owner.store.observation.diagnostics is None
            assert owner.ownership.diagnostics_count == 0
            with pytest.raises(AppError, match="obsolete"):
                await owner.resolve_diagnostic(value.request, ref)
        finally:
            await owner.close()
        assert owner.sessions.client is None and owner.ownership.close_complete


@pytest.mark.asyncio
async def test_root_header_history_and_same_namespace_selection_bind_final_generation(tmp_path):
    api = api_for()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            original = root_scope(owner, api)
            await owner.select_diagnostics(original)
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.connection.namespace == "team"
            assert owner.diagnostic_request.scope.namespace == "other"
            assert owner.diagnostic_request.scope.root == original.root
            assert owner.store.observation.diagnostics.findings
            assert all(
                f.subject.namespace == "other" for f in owner.store.observation.diagnostics.findings
            )
            first = owner.diagnostic_request
            await owner.select_namespace(
                "team"
            )  # Explicit reselect still drops root and advances generation.
            await wait_for(lambda: settled(owner))
            assert owner.diagnostic_request.scope.root is None
            assert owner.diagnostic_request.scope.session != first.scope.session
            assert (
                owner.diagnostic_request.scope.session.connection_id
                == first.scope.session.connection_id
            )
            await owner.select_namespace("default")
            await wait_for(lambda: settled(owner))
            restored = replace(original, session=owner.sessions.observation.identity)
            before = restored.session
            await owner.select_diagnostics(restored, header=NamespaceChoice("team"))
            await wait_for(lambda: settled(owner))
            assert owner.diagnostic_request.scope.root == original.root
            assert owner.diagnostic_request.scope.namespace == "other"
            assert owner.store.observation.connection.namespace == "team"
            assert owner.diagnostic_request.scope.session != before
            assert owner.diagnostic_request.scope.session == owner.sessions.observation.identity
            assert owner.store.observation.diagnostics.request == owner.diagnostic_request
            before_reads = len(api.reads)
            with pytest.raises(AppError, match="obsolete"):
                owner.select_diagnostics(original)
            with pytest.raises(AppError, match="header"):
                owner.select_diagnostics(
                    DiagnosticScope(owner.sessions.observation.identity, "other")
                )
            assert len(api.reads) == before_reads
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_explicit_popeye_carries_native_original_times_and_remaining_budget_then_refresh_clears_it(
    tmp_path,
):
    api, external = api_for(), External()
    clock = [NOW]
    async with authorization_api(api) as url:
        owner = owner_for(
            tmp_path,
            url,
            diagnostic_popeye=external,
            diagnostic_now=lambda: clock[0],
            diagnostic_policy=AccessPolicy(True),
        )
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_diagnostics(root_scope(owner, api))
            await wait_for(lambda: settled(owner))
            native = owner.store.observation.diagnostics
            assert native.findings
            clock[0] += timedelta(hours=1)
            for _ in range(2):
                await owner.run_popeye()
                await wait_for(lambda: settled(owner))
                result = owner.store.observation.diagnostics
                assert result.findings[:-1] == native.findings
                assert result.native_requests_used == native.native_requests_used
                assert result.sources[:-1] == native.sources
                assert len([f for f in result.findings if f.source is Kind.POPEYE]) == 1
                call = external.calls[-1]
                assert call[0] is owner.sessions.client and call[1] == owner.discovery
                assert (
                    call[2].scope.namespace == "other"
                    and owner.store.observation.connection.namespace == "team"
                )
                assert call[4] == MAX_DIAGNOSTIC_FINDINGS - len(native.findings)
                assert 0 < call[5] < MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE
                assert call[6] == SOURCE_TEXT_RESERVE // 2
                assert call[3](call[2])
            await owner.refresh_diagnostics()
            await wait_for(lambda: settled(owner))
            assert len(external.calls) == 2
            assert all(
                f.source is not Kind.POPEYE for f in owner.store.observation.diagnostics.findings
            )
            assert all(
                s.kind is not Kind.POPEYE for s in owner.store.observation.diagnostics.sources
            )
            await owner.refresh_discovery()
            await wait_for(lambda: settled(owner))
            assert owner.diagnostic_request.scope.root is not None
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_unconfigured_popeye_opens_current_overview_with_explicit_unavailable_source(
    tmp_path,
):
    api = api_for()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            await owner.run_popeye()
            await wait_for(lambda: settled(owner))
            result = owner.store.observation.diagnostics
            assert result.request.scope.root is None and result.request.scope.namespace == "team"
            assert not result.findings and result.sources[0].kind is Kind.POPEYE
            assert result.sources[0].status is Status.UNAVAILABLE
            assert "not configured" in result.sources[0].detail
            assert "partial/unavailable" in owner.store.observation.message
            assert not api.log_reads
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_cancel_invalidates_synchronously_drains_retains_and_allows_new_native_or_tool_run(
    tmp_path,
):
    api, external = api_for(), External(hold=True, cleanup=True)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external, diagnostic_now=lambda: NOW)
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_diagnostics(overview(owner))
            await wait_for(lambda: settled(owner))
            native = owner.store.observation.diagnostics
            await owner.run_popeye()
            await external.entered.wait()
            old = owner.diagnostic_request
            cancelling = owner.cancel_diagnostics()
            assert owner.diagnostic_request is None
            with pytest.raises(AppError, match="obsolete"):
                await owner.resolve_diagnostic(old, native.findings[0].subject)
            assert not external.calls[0][3](old)
            assert owner.store.observation.diagnostics.findings == native.findings
            assert owner.cancel_diagnostics() is cancelling
            await external.cancelled.wait()
            assert not cancelling.done() and owner.ownership.diagnostics_count == 1
            external.release.set()
            await cancelling
            result = owner.store.observation.diagnostics
            assert (
                owner.diagnostic_request == result.request
                and result.request.revision > old.revision
            )
            assert (
                result.findings == native.findings
                and result.native_requests_used == native.native_requests_used
            )
            assert result.sources[-1].status is Status.CANCELLED
            assert not result.collecting and not owner.diagnostic_collecting
            await owner.refresh_diagnostics()
            await wait_for(lambda: settled(owner))
            await owner.run_popeye()
            await wait_for(lambda: settled(owner))
            assert len(external.calls) == 2
        finally:
            external.release.set()
            await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination",
    [
        "resource",
        "namespace",
        "pulse",
        "authorization",
        "relationships",
        "same-context",
        "other-context",
    ],
)
async def test_departure_rejects_external_late_result_and_never_retargets_captured_scope(
    tmp_path, destination
):
    api, external = api_for(), External(hold=True)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external)
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_diagnostics(overview(owner))
            await wait_for(lambda: settled(owner))
            await owner.run_popeye()
            await external.entered.wait()
            old = owner.diagnostic_request
            if destination == "resource":
                operation = owner.select_resource(ResourceSelection())
            elif destination == "namespace":
                operation = owner.select_namespace("other")
            elif destination == "pulse":
                operation = owner.select_pulse()
            elif destination == "authorization":
                operation = owner.select_authorization(auth_request().intent)
            elif destination == "relationships":
                resource = owner.discovery.find("pods")
                from kuberich.domain.targets import ResourceTarget

                target = ResourceTarget(
                    old.scope.session, "", "pods", "team", "example", "pod-team"
                )
                operation = owner.select_relationships(target, resource, RelationshipMode.XRAY)
            else:
                operation = owner.connect(
                    "kuberich-test-one" if destination == "same-context" else "kuberich-test-Two"
                )
            assert not external.calls[0][3](old)
            await operation
            assert len(external.calls) == 1 and external.calls[0][2].scope.namespace == "team"
            assert owner.ownership.diagnostics_count == (1 if destination == "namespace" else 0)
            if destination == "namespace":
                await wait_for(lambda: settled(owner))
                assert owner.diagnostic_request.scope.namespace == "other"
            else:
                assert (
                    owner.diagnostic_request is None and owner.store.observation.diagnostics is None
                )
        finally:
            external.release.set()
            await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_request", [False, True])
async def test_unexpected_external_failure_invalidates_callbacks_and_refresh_recovers(
    tmp_path, wrong_request
):
    api, errors = api_for(), []
    external = External(
        failure=None if wrong_request else RuntimeError("PRIVATE injected failure"),
        wrong_request=wrong_request,
    )
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external, on_error=errors.append)
        try:
            await owner.connect("kuberich-test-one")
            await owner.run_popeye()
            await wait_for(lambda: bool(errors))
            assert owner.diagnostic_request is None and not owner.diagnostic_collecting
            assert owner.store.observation.status is ViewStatus.FAILED
            assert "PRIVATE" not in str(owner.store.observation.problem)
            assert not external.calls[0][3](external.calls[0][2])
            assert owner.store.observation.diagnostics.collecting  # no fake successful replacement
            await owner.refresh_diagnostics()
            await wait_for(lambda: settled(owner))
            assert (
                owner.diagnostic_request is not None
                and owner.store.observation.diagnostics.findings
            )
            assert len(errors) == 1
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_close_drains_external_cleanup_before_disposing_client_under_repeated_cancel(
    tmp_path,
):
    api, external = api_for(), External(hold=True, cleanup=True)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external)
        await owner.connect("kuberich-test-one")
        await owner.run_popeye()
        await external.entered.wait()
        client = owner.sessions.client
        closing = asyncio.create_task(owner.close())
        try:
            await external.cancelled.wait()
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            assert owner.sessions.client is client and not closing.done()
            assert owner.diagnostic_request is None and owner.store.observation.diagnostics is None
            assert owner.ownership.diagnostics_count == 1
        finally:
            external.release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            await owner.close()
        assert owner.sessions.client is None and owner.ownership.diagnostics_count == 0


@pytest.mark.asyncio
async def test_unselected_closed_stale_scope_and_explicit_stop_have_no_hidden_reads(tmp_path):
    api = api_for()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        for method in [owner.refresh_diagnostics, owner.run_popeye, owner.cancel_diagnostics]:
            with pytest.raises(AppError):
                method()
        await owner.stop_diagnostics()
        await owner.connect("kuberich-test-one")
        with pytest.raises(AppError):
            owner.refresh_diagnostics()
        with pytest.raises(AppError):
            owner.cancel_diagnostics()
        with pytest.raises(AppError):
            owner.select_diagnostics(
                DiagnosticScope(SessionIdentity("kuberich-test-one", 1), "team")
            )
        await owner.select_diagnostics(overview(owner))
        await wait_for(lambda: settled(owner))
        await owner.stop_diagnostics()
        assert owner.diagnostic_request is None and owner.store.observation.diagnostics is None
        assert owner.ownership.diagnostics_count == 0
        await owner.stop_diagnostics()
        await owner.close()
        with pytest.raises(AppError):
            owner.run_popeye()


@pytest.mark.asyncio
async def test_explicit_tool_interrupts_native_event_read_and_retains_partial_source_provenance(
    tmp_path,
):
    api, external = api_for(), External()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external, diagnostic_now=lambda: NOW)
        try:
            await owner.connect("kuberich-test-one")
            api.hold_path = "/api/v1/namespaces/team/events"
            await owner.select_diagnostics(overview(owner))
            await api.started.wait()
            native = owner.store.observation.diagnostics
            assert native.findings and native.collecting
            assert native.native_requests_used == 2  # Includes the charged, held Event attempt.
            await owner.run_popeye()
            await wait_for(lambda: settled(owner))
            result = owner.store.observation.diagnostics
            assert result.findings[:-1] == native.findings
            assert result.native_requests_used == native.native_requests_used
            assert (
                result.sources[-2].kind is Kind.EVENT
                and result.sources[-2].status is Status.CANCELLED
            )
            assert result.sources[-2].observed_at == native.sources[-1].observed_at
            assert result.sources[-1].kind is Kind.POPEYE
        finally:
            api.release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_header_transition_rebinds_external_request_without_carrying_old_generation(tmp_path):
    api, external = api_for(), External()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external)
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_diagnostics(root_scope(owner, api))
            await wait_for(lambda: settled(owner))
            old = owner.diagnostic_request
            assert owner.store.observation.diagnostics.findings
            owner.select_diagnostics(old.scope, header=NamespaceChoice("default"))
            await owner.run_popeye()
            await wait_for(lambda: settled(owner))
            current = owner.diagnostic_request
            assert current.scope.namespace == "other" and current.scope.root == old.scope.root
            assert current.scope.session != old.scope.session
            assert current.scope.session == owner.sessions.observation.identity
            assert owner.store.observation.connection.namespace == "default"
            assert owner.store.observation.diagnostics.native_requests_used == 0
            assert all(
                f.source is Kind.POPEYE for f in owner.store.observation.diagnostics.findings
            )
            assert external.calls[0][4] == MAX_DIAGNOSTIC_FINDINGS
            assert external.calls[0][5] == MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_refresh_supersedes_pending_cancel_without_republishing_old_request(tmp_path):
    api, external = api_for(), External(hold=True, cleanup=True)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external)
        try:
            await owner.connect("kuberich-test-one")
            await owner.run_popeye()
            await external.entered.wait()
            owner.cancel_diagnostics()
            await external.cancelled.wait()
            fresh = owner.refresh_diagnostics()
            wanted = owner.diagnostic_request
            external.release.set()
            await fresh
            await wait_for(lambda: settled(owner))
            assert owner.diagnostic_request == wanted
            assert all(
                s.kind is not Kind.POPEYE for s in owner.store.observation.diagnostics.sources
            )
        finally:
            external.release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_native_unexpected_failure_is_reported_and_late_external_failure_does_not_fault_new_view(
    tmp_path, monkeypatch
):
    from kuberich.services import workspace as workspace_module

    api, errors = api_for(), []
    original = workspace_module.DiagnosticService

    class BrokenNative:
        def __init__(self, *args, **kwargs):
            pass

        async def collect(self, request, publish):
            raise ValueError("PRIVATE native projection failure")

    async with authorization_api(api) as url:
        external = External(hold=True, failure=RuntimeError("PRIVATE late external failure"))
        owner = owner_for(tmp_path, url, diagnostic_popeye=external, on_error=errors.append)
        try:
            await owner.connect("kuberich-test-one")
            monkeypatch.setattr(workspace_module, "DiagnosticService", BrokenNative)
            await owner.select_diagnostics(overview(owner))
            await wait_for(lambda: bool(errors))
            assert (
                owner.diagnostic_request is None
                and owner.store.observation.status is ViewStatus.FAILED
            )
            assert "PRIVATE" not in str(owner.store.observation.problem)
            monkeypatch.setattr(workspace_module, "DiagnosticService", original)
            await owner.run_popeye()
            await external.entered.wait()
            await owner.select_resource(ResourceSelection())
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert len(errors) == 1 and owner.store.observation.diagnostics is None
        finally:
            external.release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_cancel_does_not_rebind_retained_rows_after_session_generation_changes_during_cleanup(
    tmp_path,
):
    api, external = api_for(), External(hold=True, cleanup=True)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url, diagnostic_popeye=external)
        try:
            await owner.connect("kuberich-test-one")
            await owner.run_popeye()
            await external.entered.wait()
            previous = owner.store.observation.diagnostics
            cancelling = owner.cancel_diagnostics()
            await external.cancelled.wait()
            owner.sessions.select_namespace("other")
            external.release.set()
            await cancelling
            assert owner.diagnostic_request is None
            assert owner.store.observation.diagnostics is previous
            assert (
                owner.store.observation.diagnostics.request.scope.session
                != owner.sessions.observation.identity
            )
        finally:
            external.release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_explicit_same_header_submission_advances_generation_and_invalidates_independent_target(
    tmp_path,
):
    from kuberich.domain.targets import ResourceTarget

    api = api_for()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_diagnostics(root_scope(owner, api))
            await wait_for(lambda: settled(owner))
            previous = owner.diagnostic_request
            subject = next(
                f.subject
                for f in owner.store.observation.diagnostics.findings
                if f.subject.resource.name == "pods"
            )
            captured = ResourceTarget(
                previous.scope.session,
                "",
                "pods",
                subject.namespace,
                subject.name,
                subject.uid,
                "app",
            )
            client = owner.sessions.client
            captured.require_current(owner.sessions.observation.identity, uid=subject.uid)
            # The UI picker/command port submits header explicitly, including a
            # same-header choice. It does not call select_namespace first.
            await owner.select_diagnostics(
                DiagnosticScope(previous.scope.session, "team"), header=NamespaceChoice("team")
            )
            await wait_for(lambda: settled(owner))
            current = owner.diagnostic_request
            assert current.scope.session.generation > previous.scope.session.generation
            assert current.scope.session.connection_id == previous.scope.session.connection_id
            assert owner.sessions.client is client
            assert current.scope.root is None and current.scope.namespace == "team"
            assert owner.store.observation.connection.namespace == "team"
            assert current.scope.session == owner.sessions.observation.identity
            with pytest.raises(AppError, match="stale"):
                captured.require_current(current.scope.session, uid=subject.uid)
        finally:
            await owner.close()
