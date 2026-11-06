"""Owned local roundtrips, API-bound consent and cancellation contracts."""

import asyncio
import base64
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import HttpProblem
from kuberich.domain.exports import (
    DocumentSource,
    ExportCapture,
    ExportScope,
    ResourceSource,
    SensitiveApproval,
    SupportSource,
    prepare_capture,
)
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.exports import ExportLease, ExportService, ResourceExportReader
from tests.support.configuration_data import TEXT, data_api
from tests.support.connections import catalog_fixture

NOW = datetime(2026, 11, 5, tzinfo=UTC)
RESOURCE = ApiResource("", "v1", "secrets", "Secret", True, frozenset({"get"}))


def local_lease(text="retained", current=lambda: True, source=None):
    return ExportLease(
        id=uuid4(),
        capture=ExportCapture(
            scope=ExportScope(
                export_at=NOW,
                source_at=NOW,
                context=None,
                header_namespace=None,
                collection_namespace=None,
                namespace_mode="local",
            ),
            source=source or DocumentSource(page="details", text=text),
        ),
        current=current,
        session=None,
    )


def service(
    tmp_path,
    files=None,
    report=lambda: (
        b'{"schema_version":1,"version":"0.3.0","python":"3.12.0","platform":"linux","terminal":{"stdin_tty":false,"stdout_tty":false},"config_check":"missing","recent_log":{"status":"unavailable"}}'
    ),
):
    return ExportService(
        files=files or ArtifactFiles(),
        default_root=tmp_path / "exports",
        report_payload=report,
        clock=lambda: NOW,
        new_id=uuid4,
    )


@asynccontextmanager
async def live_source(tmp_path, *, metadata_only=False):
    async with data_api() as (url, api):
        client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
        await client.open()
        session = SessionIdentity("kuberich-test-one", 1)
        target = ResourceTarget(session, "", "secrets", "team", "owned-one", "owned-data-uid")
        current = [True]
        reader = ResourceExportReader(
            client, RESOURCE, target, AccessPolicy(True), lambda: current[0]
        )
        record = replace(resource_record(RESOURCE, api.value, "team"), metadata_only=metadata_only)
        capture = ExportCapture(
            scope=ExportScope(
                export_at=NOW,
                source_at=NOW,
                context=session.context,
                header_namespace="team",
                collection_namespace="team",
                namespace_mode="one",
                api_version="v1",
                resource="secrets",
                kind="Secret",
                name=record.name,
                uid=record.uid,
                resource_version=record.resource_version,
            ),
            source=ResourceSource(resource=RESOURCE, record=record),
        )
        lease = ExportLease(
            id=uuid4(),
            capture=capture,
            current=lambda: current[0],
            session=session,
            resource_reader=reader,
        )
        owner = service(tmp_path)
        try:
            yield owner, lease, api, current
        finally:
            await owner.close()
            await client.close()


@pytest.mark.asyncio
async def test_offline_scan_no_creation_and_full_local_action_roundtrip(tmp_path):
    owner = service(tmp_path)
    listing = await owner.scan(owner.default_root)
    assert listing.entries == () and listing.notice and not owner.default_root.exists()
    with pytest.raises(AppError):
        await owner.review_destination(tmp_path / "other-missing", "saved.txt")
    lease = local_lease("password=private\nretained")
    assert await owner.resolve(lease) is lease
    preview = await owner.prepare(lease, "screen")
    assert b"private" not in preview.payload
    with pytest.raises(AppError):
        await owner.page(preview, 0)
    with pytest.raises(AppError):
        await owner.copy_text(preview)
    review = await owner.review_destination(owner.default_root, "saved.txt")
    with pytest.raises(AppError, match="destination"):
        await owner.publish(preview, review)
    prepared = await owner.prepare(lease, "screen", destination=review)
    outcome = await owner.publish(prepared, review)
    assert owner.last_outcome == outcome
    with pytest.raises(AppError):
        await owner.publish(prepared, review)
    listing = await owner.scan(owner.default_root)
    assert len(listing.entries) == 1 and listing.entries[0].metadata.format == "screen"
    viewed = await owner.read(outcome.ref)
    page = await owner.page(viewed, 0)
    assert "retained" in page.text and "private" not in page.text
    with pytest.raises(AppError):
        await owner.copy_text(viewed)
    copied = await owner.read(outcome.ref, intent="copy")
    assert "retained" in await owner.copy_text(copied)
    owner.discard(copied)
    with pytest.raises(AppError):
        await owner.copy_text(copied)
    with pytest.raises(AppError, match="confirmation"):
        await owner.delete(outcome.ref, confirmed=False)
    assert (await owner.delete(outcome.ref, confirmed=True)).effect == "deleted"
    assert owner.operation_count == 0
    await owner.close()
    with pytest.raises(AppError, match="closed"):
        await owner.scan(owner.default_root)


@pytest.mark.asyncio
async def test_metadata_only_resolves_once_exact_read_and_sensitive_version_recheck(tmp_path):
    async with live_source(tmp_path, metadata_only=True) as (owner, lease, api, _):
        with pytest.raises(AppError):
            await owner.prepare(lease, "resource-yaml")
        resolved = await owner.resolve(lease)
        assert resolved.id != lease.id and resolved.capture.scope.source_at == NOW
        assert not resolved.capture.source.record.metadata_only and len(api.requests) == 1
        assert await owner.resolve(resolved) is resolved
        review = await owner.review_destination(owner.default_root, "secret.yaml")
        safe = await owner.prepare(resolved, "resource-yaml", destination=review)
        marker = base64.b64encode(TEXT.encode())
        assert marker not in safe.payload
        approval = await owner.approve_sensitive(
            resolved, "resource-yaml", intent="save", destination=review
        )
        sensitive = await owner.prepare(
            resolved, "resource-yaml", approval=approval, destination=review
        )
        assert marker in sensitive.payload and marker.decode() not in sensitive.preview
        assert len(api.requests) == 2
        outcome = await owner.publish(sensitive, review)
        assert outcome.ref.identity.mode & 0o777 == 0o600
        with pytest.raises(AppError):
            await owner.prepare(resolved, "resource-yaml", approval=approval, destination=review)
        default = await owner.read(outcome.ref)
        assert marker not in default.payload
        view_approval = await owner.approve_sensitive(outcome.ref, "resource-yaml", intent="view")
        revealed = await owner.read(outcome.ref, approval=view_approval)
        assert marker in revealed.payload
        with pytest.raises(AppError):
            await owner.copy_text(revealed)
        copy_approval = await owner.approve_sensitive(outcome.ref, "resource-yaml", intent="copy")
        copied = await owner.read(outcome.ref, intent="copy", approval=copy_approval)
        assert marker.decode() in await owner.copy_text(copied)
        assert len(api.requests) == 2  # Local actions never read the cluster.
        save_review = await owner.review_destination(owner.default_root, "copy.yaml")
        save_approval = await owner.approve_sensitive(
            outcome.ref, "resource-yaml", intent="save", destination=save_review
        )
        saved = await owner.read(
            outcome.ref, intent="save", approval=save_approval, destination=save_review
        )
        assert (await owner.publish(saved, save_review)).effect == "published"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "version", "hash", "denied", "missing", "stale"])
async def test_sensitive_attempt_consumed_after_changed_api_and_denial(tmp_path, change):
    async with live_source(tmp_path) as (owner, lease, api, current):
        await owner.resolve(lease)
        review = await owner.review_destination(owner.default_root, "secret.yaml")
        approval = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        if change == "uid":
            api.value["metadata"]["uid"] = "replacement"
        elif change == "version":
            api.value["metadata"]["resourceVersion"] = "other"
        elif change == "hash":
            api.value["data"]["chosen"] = "c3dhcHBlZA=="
        elif change in {"denied", "missing"}:
            api.read_status = 403 if change == "denied" else 404
        else:
            current[0] = False
        with pytest.raises((AppError, HttpProblem)) as error:
            await owner.prepare(lease, "resource-yaml", approval=approval, destination=review)
        if change in {"denied", "missing"}:
            assert error.value.status == api.read_status
        with pytest.raises(AppError, match="approval"):
            await owner.prepare(lease, "resource-yaml", approval=approval, destination=review)
        assert not (owner.default_root / "secret.yaml").exists()


@pytest.mark.asyncio
async def test_consent_forgery_destination_kind_and_session_binding(tmp_path):
    async with live_source(tmp_path) as (owner, lease, _, _):
        await owner.resolve(lease)
        review = await owner.review_destination(owner.default_root, "secret.yaml")
        fake = SensitiveApproval(nonce=uuid4(), binding_sha256="forged")
        with pytest.raises(AppError, match="approval"):
            await owner.prepare(lease, "resource-yaml", approval=fake, destination=review)
        token = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        with pytest.raises(AppError, match="approval"):
            await owner.prepare(
                lease,
                "resource-yaml",
                approval=token,
                destination=replace(review, name="different"),
            )
        with pytest.raises(AppError, match="approval"):
            await owner.prepare(lease, "resource-yaml", approval=token, destination=review)
        token = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        changed_lease = replace(lease, session=SessionIdentity(lease.session.context, 2))
        with pytest.raises(AppError):
            await owner.prepare(changed_lease, "resource-yaml", approval=token, destination=review)
        with pytest.raises(AppError):
            await owner.approve_sensitive(lease, "screen", intent="save", destination=review)
        with pytest.raises(AppError):
            await owner.approve_sensitive(lease, "resource-yaml", intent="view")
        with pytest.raises(AppError):
            await owner.approve_sensitive(lease, "resource-yaml", intent="save")
        token = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        owner.discard(token)
        with pytest.raises(AppError):
            await owner.prepare(lease, "resource-yaml", approval=token, destination=review)
        await owner.close_for_session(lease.session)
        with pytest.raises(AppError):
            await owner.prepare(lease, "resource-yaml")


@pytest.mark.asyncio
async def test_api_reader_refuses_wrong_client_scope_api_and_response(tmp_path):
    async with live_source(tmp_path) as (_, lease, api, current):
        reader = lease.resource_reader
        for target, resource in [
            (replace(reader.target, session=SessionIdentity("other", 1)), RESOURCE),
            (replace(reader.target, namespace=None), RESOURCE),
            (reader.target, replace(RESOURCE, name="configmaps")),
            (reader.target, replace(RESOURCE, verbs=frozenset())),
        ]:
            with pytest.raises(AppError):
                await ResourceExportReader(
                    reader.client, resource, target, AccessPolicy(True), lambda: True
                ).read()
        assert not api.requests
        for key, value in [("apiVersion", "v2"), ("kind", "ConfigMap")]:
            original = api.value[key]
            api.value[key] = value
            with pytest.raises(AppError):
                await reader.read()
            api.value[key] = original
        api.value["metadata"]["name"] = "different"
        with pytest.raises(AppError):
            await reader.read()
        api.value["metadata"]["name"] = "owned-one"
        api.hold = True
        task = asyncio.create_task(reader.read())
        await api.started.wait()
        current[0] = False
        api.release.set()
        with pytest.raises(AppError):
            await task


@pytest.mark.asyncio
async def test_session_close_cancels_and_drains_api_before_return(tmp_path):
    async with live_source(tmp_path, metadata_only=True) as (owner, lease, api, _):
        api.hold = True
        task = asyncio.create_task(owner.resolve(lease))
        await api.started.wait()
        assert owner.operation_count == 1
        await owner.close_for_session(lease.session)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner.operation_count == 0


@pytest.mark.asyncio
async def test_owned_worker_repeated_cancellation_drains_late_commit(tmp_path):
    started, release = threading.Event(), threading.Event()

    class HeldFiles(ArtifactFiles):
        def publish(self, prepared, review, *, cancel):
            outcome = super().publish(prepared, review, cancel=cancel)
            started.set()
            assert release.wait(5)
            return outcome

    owner = service(tmp_path, HeldFiles())
    lease = local_lease()
    review = await owner.review_destination(owner.default_root, "saved.txt")
    prepared = await owner.prepare(lease, "screen", destination=review)
    task = asyncio.create_task(owner.publish(prepared, review))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and owner.operation_count == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert owner.last_outcome.effect == "published" and owner.operation_count == 0
    assert (owner.default_root / "saved.txt").is_file()
    await owner.close()


@pytest.mark.asyncio
async def test_close_cooperatively_stops_precommit_work_and_consumes_preparation(tmp_path):
    started, stopped = threading.Event(), threading.Event()

    class HeldFiles(ArtifactFiles):
        def publish(self, prepared, review, *, cancel):
            started.set()
            assert cancel.wait(5)
            stopped.set()
            return super().publish(prepared, review, cancel=cancel)

    owner = service(tmp_path, HeldFiles())
    lease = local_lease()
    review = await owner.review_destination(owner.default_root, "saved.txt")
    prepared = await owner.prepare(lease, "screen", destination=review)
    task = asyncio.create_task(owner.publish(prepared, review))
    assert await asyncio.to_thread(started.wait, 5)
    await owner.close()
    with pytest.raises(AppError):
        await task
    assert stopped.is_set() and not (owner.default_root / "saved.txt").exists()
    assert owner.last_outcome is None
    await owner.close()


@pytest.mark.asyncio
async def test_support_report_build_runs_off_event_loop(tmp_path):
    loop_thread = threading.get_ident()
    seen = []

    def report():
        seen.append(threading.get_ident())
        return b'{"schema_version":1,"version":"0.3.0","python":"3.12.0","platform":"linux","terminal":{"stdin_tty":false,"stdout_tty":false},"config_check":"missing","recent_log":{"status":"unavailable"}}'

    owner = service(tmp_path, report=report)
    value = await owner.prepare(
        local_lease(source=SupportSource(omissions=("resource not selected",))), "support"
    )
    assert seen and seen[0] != loop_thread and b"resource not selected" in value.payload
    await owner.close()


@pytest.mark.asyncio
async def test_scan_recognized_broken_and_unsupported_files_and_copy_limit(tmp_path):
    owner = service(tmp_path)
    review = await owner.review_destination(owner.default_root, "saved.txt")
    original = await owner.publish(
        await owner.prepare(local_lease(), "screen", destination=review), review
    )
    (owner.default_root / "unrelated").write_text("not an artifact")
    copied = await owner.read(original.ref, intent="copy")
    # Deliberately lower the retained artifact size by preparing a real >1MiB dump.
    big_review = await owner.review_destination(owner.default_root, "large.txt")
    big = await owner.prepare(local_lease("line\n" * 220000), "screen", destination=big_review)
    big_ref = (await owner.publish(big, big_review)).ref
    big_copy = await owner.read(big_ref, intent="copy")
    with pytest.raises(AppError, match="1 MiB"):
        await owner.copy_text(big_copy)
    assert (await owner.scan(owner.default_root)).skipped == 1
    forged = replace(copied, payload=b"forged")
    with pytest.raises(AppError):
        await owner.copy_text(forged)
    await owner.close()


@pytest.mark.asyncio
async def test_local_sensitive_consent_requires_private_resource_and_each_intent(tmp_path):
    owner = service(tmp_path)
    review = await owner.review_destination(owner.default_root, "saved.txt")
    ref = (
        await owner.publish(
            await owner.prepare(local_lease(), "screen", destination=review), review
        )
    ).ref
    with pytest.raises(AppError):
        await owner.approve_sensitive(ref, "screen", intent="view")
    async with live_source(tmp_path) as (live, lease, _, _):
        await live.resolve(lease)
        target = await live.review_destination(live.default_root, "raw.yaml")
        token = await live.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=target
        )
        raw = await live.prepare(lease, "resource-yaml", approval=token, destination=target)
        ref = (await live.publish(raw, target)).ref
        token = await live.approve_sensitive(ref, "resource-yaml", intent="view")
        with pytest.raises(AppError):
            await live.read(ref, intent="copy", approval=token)
        with pytest.raises(AppError):
            await live.read(ref, approval=token)
        (live.default_root / ref.name).chmod(0o644)
        with pytest.raises(AppError):
            await live.approve_sensitive(ref, "resource-yaml", intent="view")
    await owner.close()


@pytest.mark.asyncio
async def test_preparation_lease_collision_unresolved_missing_reader_and_discard(tmp_path):
    owner = service(tmp_path)
    lease = local_lease()
    first = await owner.prepare(lease, "screen")
    with pytest.raises(AppError):
        await owner.prepare(replace(lease), "screen")
    second = await owner.prepare(lease, "screen")
    owner.discard(first)
    owner.discard(second)
    owner.discard(second)
    with pytest.raises(AppError):
        await owner.page(second, 0)
    with pytest.raises(AppError):
        await owner.prepare(lease, "logs")
    async with live_source(tmp_path, metadata_only=True) as (live, live_lease, _, _):
        with pytest.raises(AppError):
            await live.resolve(replace(live_lease, resource_reader=None))
    await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("uid", None), ("resource_version", None), ("uid", "other"), ("resource_version", "other")],
)
async def test_sensitive_approval_requires_complete_capture_scope(tmp_path, field, value):
    async with live_source(tmp_path) as (owner, lease, _, _):
        if value is None:
            source = replace(
                lease.capture.source, record=replace(lease.capture.source.record, **{field: value})
            )
            lease = replace(lease, capture=replace(lease.capture, source=source))
        else:
            lease = replace(
                lease,
                capture=replace(
                    lease.capture, scope=replace(lease.capture.scope, **{field: value})
                ),
            )
        review = await owner.review_destination(owner.default_root, "saved.yaml")
        with pytest.raises(AppError):
            await owner.approve_sensitive(lease, "resource-yaml", intent="save", destination=review)


@pytest.mark.asyncio
async def test_close_revokes_active_approvals_and_sensitive_preparations_only(tmp_path):
    async with live_source(tmp_path) as (owner, lease, _, _):
        unrelated = local_lease()
        local = await owner.prepare(unrelated, "screen")
        review = await owner.review_destination(owner.default_root, "saved.yaml")
        await owner.resolve(lease)
        approval = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        sensitive = await owner.prepare(
            lease, "resource-yaml", approval=approval, destination=review
        )
        approval = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        owner.discard(local)
        # Keep another unrelated local lease active while revoking this session.
        local = await owner.prepare(unrelated, "screen")
        await owner.close_for_session(lease.session)
        with pytest.raises(AppError):
            await owner.publish(sensitive, review)
        with pytest.raises(AppError):
            await owner.prepare(lease, "resource-yaml", approval=approval, destination=review)
        owner.discard(local)


@pytest.mark.asyncio
async def test_close_drains_api_task_under_repeated_caller_cancellation(tmp_path):
    async with live_source(tmp_path, metadata_only=True) as (owner, lease, _, _):
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class HeldReader:
            async def read(self, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()

        lease = replace(lease, resource_reader=HeldReader())
        task = asyncio.create_task(owner.resolve(lease))
        await started.wait()
        closer = asyncio.create_task(owner.close())
        await cleaning.wait()
        closer.cancel()
        await asyncio.sleep(0)
        closer.cancel()
        await asyncio.sleep(0)
        assert not closer.done()
        release.set()
        await closer
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner.operation_count == 0


@pytest.mark.asyncio
async def test_scan_read_failures_and_closed_read_do_not_register_bytes(tmp_path):
    started, release = threading.Event(), threading.Event()

    class HeldFiles(ArtifactFiles):
        hold = False
        broken = False

        def read(self, ref, **kwargs):
            if self.broken:
                raise AppError("owned failure")
            value = super().read(ref, **kwargs)
            if self.hold:
                started.set()
                assert release.wait(5)
            return value

    files = HeldFiles()
    owner = service(tmp_path, files)
    review = await owner.review_destination(owner.default_root, "saved.txt")
    ref = (
        await owner.publish(
            await owner.prepare(local_lease(), "screen", destination=review), review
        )
    ).ref
    files.broken = True
    listing = await owner.scan(owner.default_root)
    assert listing.entries[0].metadata is None and listing.entries[0].problem
    files.broken = False
    with pytest.raises(AppError):
        await owner.scan(tmp_path / "unrelated-missing")
    with pytest.raises(AppError):
        await owner.read(ref, intent="view", destination=review)
    with pytest.raises(AppError):
        await owner.read(ref, approval=SensitiveApproval(nonce=uuid4(), binding_sha256="forged"))
    files.hold = True
    reading = asyncio.create_task(owner.read(ref))
    assert await asyncio.to_thread(started.wait, 5)
    closing = asyncio.create_task(owner.close())
    await asyncio.sleep(0)
    release.set()
    await closing
    with pytest.raises(AppError):
        await reading
    assert owner.operation_count == 0


@pytest.mark.asyncio
async def test_local_hash_approval_detects_changed_bytes_even_with_injected_reader(tmp_path):
    class ReplacedReader(ArtifactFiles):
        swap = False

        def read(self, ref, **kwargs):
            data = super().read(ref, **kwargs)
            return data.replace(b"dmFsdWU=", b"Y2hhbmdl") if self.swap else data

    files = ReplacedReader()
    owner = service(tmp_path, files)
    record = resource_record(
        RESOURCE,
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "one", "namespace": "team", "uid": "uid", "resourceVersion": "1"},
            "data": {"chosen": "dmFsdWU="},
        },
        "team",
    )
    capture = replace(
        local_lease().capture, source=ResourceSource(resource=RESOURCE, record=record)
    )
    raw = prepare_capture(capture, "resource-yaml", artifact_id=uuid4(), sensitive=True)
    directory = files.directory(owner.default_root, create=True, cancel=threading.Event())
    review = files.review(directory, "raw.yaml", replace=False, cancel=threading.Event())
    ref = files.publish(raw, review, cancel=threading.Event()).ref
    approval = await owner.approve_sensitive(ref, "resource-yaml", intent="view")
    files.swap = True
    with pytest.raises(AppError, match="approval"):
        await owner.read(ref, approval=approval)
    with pytest.raises(AppError, match="approval"):
        await owner.read(ref, approval=approval)
    await owner.close()


@pytest.mark.asyncio
async def test_cancelled_codec_job_finishes_without_preparation_or_output(tmp_path):
    started, release = threading.Event(), threading.Event()

    def report():
        started.set()
        assert release.wait(5)
        return b'{"schema_version":1,"version":"0.3.0","python":"3.12.0","platform":"linux","terminal":{"stdin_tty":false,"stdout_tty":false},"config_check":"missing","recent_log":{"status":"unavailable"}}'

    owner = service(tmp_path, report=report)
    task = asyncio.create_task(owner.prepare(local_lease(source=SupportSource()), "support"))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert owner.operation_count == 0 and not owner.default_root.exists()
    await owner.close()


@pytest.mark.asyncio
async def test_legacy_report_prefix_is_provisional_unknown_scope_and_validated_on_use(tmp_path):
    from kuberich.diagnostics.reports import report_payload

    owner = service(tmp_path)
    await owner.review_destination(owner.default_root, "placeholder")
    path = owner.default_root / "report.json"
    path.write_bytes(report_payload(config_status="missing"))
    path.chmod(0o600)
    listing = await owner.scan(owner.default_root)
    entry = listing.entries[0]
    assert entry.metadata.format == "legacy-report" and entry.metadata.scope.context is None
    assert entry.metadata.scope.namespace_mode == "unknown"
    assert "candidate" in entry.metadata.notices[0]
    viewed = await owner.read(entry.ref)
    assert viewed.metadata.format == "legacy-report"
    assert "config_check" in (await owner.page(viewed, 0)).text
    # A forged prefix may be listed, but unsupported extra fields cannot be used.
    body = path.read_text().rstrip()
    path.write_text(body[:-1] + ', "kubeconfig": "DO-NOT-EXPORT"}')
    forged = (await owner.scan(owner.default_root)).entries[0]
    with pytest.raises(AppError):
        await owner.read(forged.ref)
    await owner.close()


@pytest.mark.asyncio
async def test_cancelled_scan_stops_before_any_followup_read(tmp_path):
    class CancelledScan(ArtifactFiles):
        def scan(self, root, *, cancel):
            value = super().scan(root, cancel=cancel)
            cancel.set()
            return value

    files = CancelledScan()
    owner = service(tmp_path, files)
    review = await owner.review_destination(owner.default_root, "saved.txt")
    await owner.publish(await owner.prepare(local_lease(), "screen", destination=review), review)
    with pytest.raises(AppError):
        await owner.scan(owner.default_root)
    await owner.close()


@pytest.mark.asyncio
async def test_close_guarantees_last_outcome_of_completed_transaction(tmp_path):
    started, release = threading.Event(), threading.Event()

    class HeldFiles(ArtifactFiles):
        def publish(self, prepared, review, *, cancel):
            value = super().publish(prepared, review, cancel=cancel)
            started.set()
            assert release.wait(5)
            return value

    owner = service(tmp_path, HeldFiles())
    review = await owner.review_destination(owner.default_root, "saved.txt")
    prepared = await owner.prepare(local_lease(), "screen", destination=review)
    publishing = asyncio.create_task(owner.publish(prepared, review))
    assert await asyncio.to_thread(started.wait, 5)
    closing = asyncio.create_task(owner.close())
    await asyncio.sleep(0)
    release.set()
    await closing
    assert owner.last_outcome.effect == "published" and owner.operation_count == 0
    assert (await publishing).effect == "published"


@pytest.mark.asyncio
async def test_reader_rejects_missing_or_changed_api_namespace(tmp_path):
    async with live_source(tmp_path) as (_, lease, api, _):
        api.value["metadata"].pop("namespace")
        with pytest.raises(AppError):
            await lease.resource_reader.read()
        api.value["metadata"]["namespace"] = "other"
        with pytest.raises(AppError):
            await lease.resource_reader.read()


@pytest.mark.asyncio
async def test_sensitive_result_cannot_start_codec_after_session_revocation(tmp_path):
    async with live_source(tmp_path) as (owner, lease, _, _):
        reader = lease.resource_reader
        closers = []

        class ClosingReader(ResourceExportReader):
            async def read(self, **kwargs):
                record = await super().read(**kwargs)
                closers.append(asyncio.create_task(owner.close_for_session(lease.session)))
                return record

        lease = replace(
            lease,
            resource_reader=ClosingReader(
                reader.client, reader.resource, reader.target, reader.policy, reader.current
            ),
        )
        review = await owner.review_destination(owner.default_root, "saved.yaml")
        approval = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        with pytest.raises(AppError):
            await owner.prepare(lease, "resource-yaml", approval=approval, destination=review)
        await asyncio.gather(*closers)
        assert not (owner.default_root / "saved.yaml").exists()


@pytest.mark.asyncio
async def test_discarded_origin_suppresses_late_preparation(tmp_path):
    started, release = threading.Event(), threading.Event()
    hold = [False]

    def report():
        if hold[0]:
            started.set()
            assert release.wait(5)
        return b'{"schema_version":1,"version":"0.3.0","python":"3.12.0","platform":"linux","terminal":{"stdin_tty":false,"stdout_tty":false},"config_check":"missing","recent_log":{"status":"unavailable"}}'

    owner = service(tmp_path, report=report)
    lease = local_lease(source=SupportSource())
    original = await owner.prepare(lease, "support")
    hold[0] = True
    task = asyncio.create_task(owner.prepare(lease, "support"))
    assert await asyncio.to_thread(started.wait, 5)
    owner.discard(original)
    release.set()
    with pytest.raises(AppError):
        await task
    await owner.close()


@pytest.mark.asyncio
async def test_cancelled_queued_codec_checks_before_starting_cpu_work(tmp_path, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    to_thread = asyncio.to_thread

    async def queued(operation, *args, **kwargs):
        started.set()
        await release.wait()
        return await to_thread(operation, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", queued)
    owner = service(tmp_path)
    task = asyncio.create_task(owner.prepare(local_lease(), "screen"))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert owner.operation_count == 0
    await owner.close()


@pytest.mark.asyncio
async def test_session_close_drains_default_file_transaction_and_preserves_local_approval(tmp_path):
    started = threading.Event()

    class HeldFiles(ArtifactFiles):
        def publish(self, prepared, review, *, cancel):
            value = super().publish(prepared, review, cancel=cancel)
            started.set()
            assert cancel.wait(5)
            return value

    async with live_source(tmp_path) as (live, lease, _, _):
        # First create a private local resource file with an independent owner.
        review = await live.review_destination(live.default_root, "original.yaml")
        token = await live.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        raw = await live.prepare(lease, "resource-yaml", approval=token, destination=review)
        ref = (await live.publish(raw, review)).ref
        local_approval = await live.approve_sensitive(ref, "resource-yaml", intent="view")
        live.discard(SensitiveApproval(nonce=uuid4(), binding_sha256="unknown"))
        owner = service(tmp_path, HeldFiles())
        review = await owner.review_destination(owner.default_root, "copy.yaml")
        safe = await owner.prepare(lease, "resource-yaml", destination=review)
        task = asyncio.create_task(owner.publish(safe, review))
        assert await asyncio.to_thread(started.wait, 5)
        await owner.close_for_session(lease.session)
        assert owner.last_outcome.effect == "published"
        assert (await task).effect == "published"
        # Revoking a client session does not revoke a distinct local-file intent.
        await live.close_for_session(lease.session)
        revealed = await live.read(ref, approval=local_approval)
        assert revealed.metadata.sensitive
        token = await live.approve_sensitive(ref, "resource-yaml", intent="copy")
        live.discard(token)
        with pytest.raises(AppError):
            await live.read(ref, intent="copy", approval=token)
        await owner.close()


@pytest.mark.asyncio
async def test_caller_constructed_copy_of_valid_token_cannot_authorize(tmp_path):
    async with live_source(tmp_path) as (owner, lease, _, _):
        review = await owner.review_destination(owner.default_root, "saved.yaml")
        token = await owner.approve_sensitive(
            lease, "resource-yaml", intent="save", destination=review
        )
        forged = replace(token)
        with pytest.raises(AppError, match="approval"):
            await owner.prepare(lease, "resource-yaml", approval=forged, destination=review)
        with pytest.raises(AppError, match="approval"):
            await owner.prepare(lease, "resource-yaml", approval=token, destination=review)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["resolve", "prepare", "approve"])
async def test_failed_operations_release_capture_guard_without_ui_discard(tmp_path, operation):
    import gc
    import weakref

    class Guard:
        def __call__(self):
            return True

    owner = service(tmp_path)
    guard = Guard()
    retained = weakref.ref(guard)
    lease = local_lease(current=guard)
    if operation == "resolve":
        record = resource_record(
            RESOURCE,
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "one",
                    "namespace": "team",
                    "uid": "uid",
                    "resourceVersion": "1",
                },
            },
            "team",
        )
        lease = replace(
            lease,
            capture=replace(
                lease.capture,
                source=ResourceSource(
                    resource=RESOURCE, record=replace(record, metadata_only=True)
                ),
            ),
        )
        with pytest.raises(AppError):
            await owner.resolve(lease)
    elif operation == "prepare":
        with pytest.raises(AppError):
            await owner.prepare(lease, "logs")
    else:
        review = await owner.review_destination(owner.default_root, "saved.yaml")
        with pytest.raises(AppError):
            await owner.approve_sensitive(lease, "resource-yaml", intent="save", destination=review)
    del guard, lease
    gc.collect()
    assert retained() is None
    await owner.close()


@pytest.mark.asyncio
async def test_connection_close_drains_old_generation_get_and_preserves_other_connections(tmp_path):
    async with live_source(tmp_path, metadata_only=True) as (owner, lease, api, _):
        api.hold = True
        task = asyncio.create_task(owner.resolve(lease))
        await api.started.wait()
        # SessionService increments generation for namespace changes on this client.
        latest = replace(lease.session, generation=lease.session.generation + 1)
        await owner.close_for_session(latest)
        assert owner.operation_count == 1 and not task.done()
        await owner.close_for_connection(latest.connection_id)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner.operation_count == 0
        # Even an old lease first presented after closure cannot start another GET.
        with pytest.raises(AppError):
            await owner.resolve(replace(lease, id=uuid4()))
        requests = len(api.requests)
        with pytest.raises(AppError):
            await owner.prepare(replace(lease, id=uuid4(), session=latest), "resource-yaml")
        assert len(api.requests) == requests
        api.hold = False
        fresh_session = SessionIdentity(lease.session.context, latest.generation + 1)
        reader = lease.resource_reader
        fresh_reader = ResourceExportReader(
            reader.client,
            reader.resource,
            replace(reader.target, session=fresh_session),
            reader.policy,
            reader.current,
        )
        fresh = replace(lease, id=uuid4(), session=fresh_session, resource_reader=fresh_reader)
        assert (await owner.resolve(fresh)).session == fresh_session
        # Registry-only generations are revoked too, and closing a missing ID is safe.
        await owner.prepare(local_lease(), "screen")
        await owner.prepare(
            replace(
                fresh,
                capture=replace(
                    fresh.capture,
                    source=replace(
                        fresh.capture.source,
                        record=replace(fresh.capture.source.record, metadata_only=False),
                    ),
                ),
            ),
            "resource-yaml",
        )
        await owner.close_for_connection(fresh_session.connection_id)
        await owner.close_for_connection(uuid4())


@pytest.mark.asyncio
async def test_connection_close_preserves_local_file_job(tmp_path):
    started, release = threading.Event(), threading.Event()

    class HeldFiles(ArtifactFiles):
        def read(self, ref, **kwargs):
            value = super().read(ref, **kwargs)
            started.set()
            assert release.wait(5)
            return value

    owner = service(tmp_path, HeldFiles())
    review = await owner.review_destination(owner.default_root, "local.txt")
    ref = (
        await owner.publish(
            await owner.prepare(local_lease(), "screen", destination=review), review
        )
    ).ref
    reading = asyncio.create_task(owner.read(ref))
    assert await asyncio.to_thread(started.wait, 5)
    await owner.close_for_connection(uuid4())
    assert owner.operation_count == 1 and not reading.done()
    release.set()
    assert (await reading).metadata.format == "screen"
    await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    ["parent-traversal", "dangling-root", "symlink-ancestor", "control", "group-writable"],
)
async def test_invalid_default_root_is_refused_instead_of_misreported_missing(tmp_path, invalid):
    if invalid == "parent-traversal":
        root = tmp_path / "missing-parent" / ".." / "exports"
    elif invalid == "dangling-root":
        root = tmp_path / "exports"
        root.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    elif invalid == "symlink-ancestor":
        parent = tmp_path / "alias"
        parent.symlink_to(tmp_path / "missing-target", target_is_directory=True)
        root = parent / "exports"
    elif invalid == "control":
        root = tmp_path / "bad\nlocation"
    else:
        root = tmp_path / "exports"
        root.mkdir(mode=0o777)
        root.chmod(0o777)
    owner = ExportService(
        files=ArtifactFiles(cwd=tmp_path),
        default_root=root,
        report_payload=lambda: b"{}",
        clock=lambda: NOW,
        new_id=uuid4,
    )
    try:
        with pytest.raises(AppError):
            await owner.scan(root)
    finally:
        await owner.close()
    assert not (tmp_path / "missing-target").exists()


@pytest.mark.asyncio
async def test_only_genuinely_missing_default_root_returns_empty_without_creating(tmp_path):
    root = tmp_path / "missing-parent" / "exports"
    owner = ExportService(
        files=ArtifactFiles(cwd=tmp_path),
        default_root=root,
        report_payload=lambda: b"{}",
        clock=lambda: NOW,
        new_id=uuid4,
    )
    try:
        listing = await owner.scan(root)
        assert listing.entries == () and listing.notice and not root.exists()
        with pytest.raises(AppError):
            await owner.scan(tmp_path / "other-missing")
    finally:
        await owner.close()
