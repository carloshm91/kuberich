"""Single-producer cancellation, exact-scope carryover and combined budget contracts."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from kuberich.domain.cluster_diagnostics import DiagnosticSourceKind as Kind
from kuberich.domain.cluster_diagnostics import DiagnosticStatus as Status
from kuberich.domain.cluster_diagnostics import diagnose_record, diagnostic_text_bytes
from kuberich.errors import AppError
from kuberich.services.diagnostic_workspace import DiagnosticWorkspace
from tests.support.diagnostic_native import NOW, PODS, record, ref, request, snapshot, source

pytestmark = pytest.mark.fast


def finding():
    return diagnose_record(
        PODS, record(status={"conditions": [{"type": "Ready", "status": "False"}]}), NOW
    )[0]


async def finish(workspace):
    await workspace.task
    await workspace.stop()


@pytest.mark.asyncio
async def test_owns_one_producer_refuses_undrained_task_and_rejects_old_revision():
    workspace = DiagnosticWorkspace()
    scope = request().scope
    req = workspace.prepare(scope, "native")
    publications = []
    started, release = asyncio.Event(), asyncio.Event()

    async def collect(request, publish):
        publish(snapshot(request, findings=(finding(),), collecting=True))
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Deliberately misbehaving old callback cannot publish after invalidation.
            publish(snapshot(request, findings=(), collecting=False))
            return snapshot(request)
        return snapshot(request)

    workspace.start(req, collect, publications.append)
    await started.wait()
    assert workspace.collecting
    new = workspace.prepare(scope, "popeye")
    with pytest.raises(AppError, match="Drain"):
        workspace.start(new, collect, publications.append)
    assert len(workspace.snapshot.findings) == 1
    await workspace.stop()
    assert publications[-1].findings and len(publications) == 1
    assert workspace.remaining_findings == 999
    assert workspace.remaining_source_text_bytes == 16384
    assert workspace.remaining_text_bytes < 2 * 1024 * 1024 - 32768
    with pytest.raises(AppError, match="stale"):
        workspace.start(req, collect, publications.append)
    assert new.revision > req.revision


@pytest.mark.asyncio
async def test_same_scope_popeye_preserves_native_times_read_count_and_replaces_partition():
    workspace = DiagnosticWorkspace()
    scope = request().scope
    first = workspace.prepare(scope)
    native = snapshot(first, findings=(finding(),), sources=(source(status=Status.PARTIAL),))

    async def native_collect(req, publish):
        return native

    values = []
    workspace.start(first, native_collect, values.append)
    await finish(workspace)
    ext_finding = replace(finding(), key="external", source=Kind.POPEYE)
    for index in range(2):
        req = workspace.prepare(scope, "popeye")
        assert workspace.remaining_findings == 999
        assert workspace.snapshot.native_requests_used == 2

        async def external(req, publish, index=index):
            return replace(
                snapshot(
                    req,
                    findings=(replace(ext_finding, key=str(index)),),
                    sources=(source(Kind.POPEYE, key="external"),),
                ),
                native_requests_used=0,
                observed_at=NOW + timedelta(hours=1),
            )

        workspace.start(req, external, values.append)
        await finish(workspace)
        current = workspace.snapshot
        assert len(current.findings) == 2 and current.findings[0] == native.findings[0]
        assert current.sources[0].observed_at == NOW and current.sources[0].status is Status.PARTIAL
        assert current.native_requests_used == 2
        assert diagnostic_text_bytes(current) <= 2 * 1024 * 1024
    refreshed = workspace.prepare(scope)
    assert workspace.snapshot.findings == ()
    assert workspace.snapshot.request == refreshed


@pytest.mark.asyncio
async def test_different_full_session_namespace_and_root_do_not_carry():
    workspace = DiagnosticWorkspace()
    scope = request().scope
    req = workspace.prepare(scope)

    async def collect(req, publish):
        return snapshot(req, findings=(finding(),))

    for other in [
        replace(scope, session=replace(scope.session, generation=2)),
        replace(scope, session=request().scope.session),
        replace(scope, namespace="other"),
        replace(scope, root=ref()),
        replace(scope, root=replace(ref(), uid="replacement")),
    ]:
        workspace.start(req, collect, lambda _: None)
        await finish(workspace)
        workspace.prepare(other, "popeye")
        assert not workspace.snapshot.findings and workspace.remaining_findings == 1000
        req = workspace.prepare(scope)


@pytest.mark.asyncio
async def test_explicit_cancel_rebinds_new_revision_and_preserves_original_partial_evidence():
    workspace = DiagnosticWorkspace()
    req = workspace.prepare(request().scope)
    started = asyncio.Event()
    values = []

    async def collect(req, publish):
        publish(
            snapshot(
                req,
                findings=(finding(),),
                sources=(source(status=Status.LOADING),),
                collecting=True,
            )
        )
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            publish(snapshot(req))

    workspace.start(req, collect, values.append)
    await started.wait()
    result = await workspace.cancel()
    assert result.request.revision > req.revision
    assert workspace.request == result.request and not workspace.collecting
    assert result.findings[0].evidence[0].observed_at == NOW
    assert (
        result.sources[0].status is Status.CANCELLED and not result.sources[0].collection.complete
    )
    assert len(values) == 1  # caller alone may bind and publish the cancellation result
    new = workspace.prepare(result.request.scope, "popeye")
    assert workspace.snapshot.sources[0].status is Status.CANCELLED
    assert new.revision > result.request.revision
    workspace.invalidate()
    assert await workspace.cancel() is None
    assert await DiagnosticWorkspace().cancel() is None
    await workspace.stop()


@pytest.mark.asyncio
async def test_stop_drains_under_repeated_caller_cancellation():
    workspace = DiagnosticWorkspace()
    req = workspace.prepare(request().scope)
    started, finish_cleanup, cleanup_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def collect(req, publish):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await finish_cleanup.wait()
        return snapshot(req)

    workspace.start(req, collect, lambda _: None)
    await started.wait()
    stop = asyncio.create_task(workspace.stop())
    await cleanup_started.wait()
    stop.cancel()
    await asyncio.sleep(0)
    stop.cancel()
    finish_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await stop
    assert workspace.task is None


def test_no_request_invalid_producer_and_empty_remaining_budget():
    workspace = DiagnosticWorkspace()
    assert workspace.snapshot is None and workspace.remaining_findings == 1000
    assert workspace.remaining_text_bytes == 2 * 1024 * 1024 - 32768
    with pytest.raises(AppError, match="Unknown"):
        workspace.prepare(request().scope, "other")


@pytest.mark.asyncio
async def test_cancel_before_first_publication_has_notice_and_does_not_overwrite_new_prepare():
    workspace = DiagnosticWorkspace()
    req = workspace.prepare(request().scope, "popeye")
    started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def collect(req, publish):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()
            await release.wait()
        return snapshot(req)

    workspace.start(req, collect, lambda _: None)
    await started.wait()
    cancelling = asyncio.create_task(workspace.cancel())
    await cleanup.wait()
    new = workspace.prepare(req.scope)
    release.set()
    assert await cancelling is None and workspace.request == new
    workspace.start(
        new,
        lambda req, publish: asyncio.sleep(0, result=snapshot(req, sources=(), collecting=True)),
        lambda _: None,
    )
    await workspace.task
    result = await workspace.cancel()
    assert result.sources[0].status is Status.CANCELLED
    assert "incomplete" in result.sources[0].detail
