"""Actual HTTP finite GET, freshness, disclosure and cancellation contracts."""

import asyncio
import base64
import copy
import json
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.container_inspection import (
    ContainerIdentity,
    ReasonCode,
    metadata_table,
)
from kuberich.domain.resources import Discovery, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.container_inspection import ContainerInspectionService
from tests.support.connections import catalog_fixture
from tests.support.container_inspection import (
    CONFIG_PATH,
    NAMESPACE,
    POD_NAME,
    POD_PATH,
    POD_UID,
    PRIVATE_VALUE,
    SECRET_PATH,
    descriptor,
    discovery,
    inspection_api,
    source_fixture,
)


@asynccontextmanager
async def inspection_source(tmp_path, identity=None, discovered=None):
    async with inspection_api() as (url, api):
        client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
        await client.open()
        current = [True]
        service = ContainerInspectionService(
            client,
            descriptor("Pod"),
            ResourceTarget(
                SessionIdentity("kuberich-test-one", 1), "", "pods", NAMESPACE, POD_NAME, POD_UID
            ),
            identity or ContainerIdentity("containers", "app", "App"),
            discovered or discovery(),
            AccessPolicy(True),
            lambda: current[0],
            now=lambda: datetime.now(UTC),
        )
        try:
            yield service, api, current
        finally:
            api.release.set()
            await service.close()
            await client.close()


def entry(snapshot, name):
    return next(value for value in snapshot.entries if value.name == name)


async def selected(service, snapshot, name, action="reveal"):
    return await service.disclose(service.new_intent(snapshot.id, entry(snapshot, name).id, action))


@pytest.mark.asyncio
async def test_index_and_every_disclosure_are_fresh_exact_serial_gets_without_value_cache(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        assert snapshot.reads == 4 and service.snapshot is snapshot
        assert [path for _, path, _ in api.requests] == [
            POD_PATH,
            CONFIG_PATH,
            SECRET_PATH,
            POD_PATH,
        ]
        assert all(method == "GET" and query == {} for method, _, query in api.requests)
        assert snapshot.image.declared == "synthetic/image:declared"
        assert snapshot.image.status_image == "status/image:v2"
        assert snapshot.image.pull_secret_names == ("image-auth-reference-only",)
        assert PRIVATE_VALUE not in repr(snapshot)
        assert base64.b64encode(PRIVATE_VALUE.encode()).decode() not in repr(snapshot)
        for section in ("environment", "image", "sources"):
            assert PRIVATE_VALUE not in repr(metadata_table(snapshot, section))
            assert snapshot.pod.payload_sha256 not in repr(metadata_table(snapshot, section))
        assert (await selected(service, snapshot, "LITERAL")).text == "synthetic-literal"
        assert (await selected(service, snapshot, "CHOSEN", "copy")).text == PRIVATE_VALUE
        assert (
            await selected(service, snapshot, "EXPANDED")
        ).text == "synthetic-literal/config-current"
        assert len(api.requests) == 16 and service.operation_count == 0
        assert PRIVATE_VALUE not in repr(service) and PRIVATE_VALUE not in repr(service.snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,name,kind",
    [
        ("containers", "app", "App"),
        ("initContainers", "init", "Init"),
        ("initContainers", "sidecar", "Sidecar"),
        ("ephemeralContainers", "debug", "Ephemeral"),
    ],
)
async def test_exact_container_family_including_restartable_init_and_ephemeral(
    tmp_path, field, name, kind
):
    async with inspection_source(tmp_path, ContainerIdentity(field, name, kind)) as (
        service,
        api,
        _,
    ):
        container = next(
            value for value in api.records[POD_PATH]["spec"][field] if value["name"] == name
        )
        container["env"] = [{"name": "FAMILY", "value": kind}]
        snapshot = await service.index()
        assert snapshot.container == ContainerIdentity(field, name, kind)
        assert (await selected(service, snapshot, "FAMILY")).text == kind


@pytest.mark.asyncio
async def test_source_dedup_keeps_reference_provenance_and_optional_flags(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        container = api.records[POD_PATH]["spec"]["containers"][0]
        container["envFrom"].append(
            {"secretRef": {"name": "inspection-secret", "optional": True}, "prefix": "SECOND_"}
        )
        snapshot = await service.index()
        source = next(value for value in snapshot.sources if value.ref.kind == "Secret")
        assert len(source.references) == 3
        assert {value.optional for value in source.references} == {True, False}
        assert {value.prefix for value in source.references} == {"", "PRIVATE_", "SECOND_"}
        assert [path for _, path, _ in api.requests].count(SECRET_PATH) == 1


@pytest.mark.asyncio
async def test_missing_discovery_descriptor_is_explicit_and_literal_still_available(tmp_path):
    async with inspection_source(tmp_path, discovered=Discovery((descriptor("Pod"),))) as (
        service,
        api,
        _,
    ):
        snapshot = await service.index()
        assert {source.state for source in snapshot.sources} == {"unsupported"}
        assert not snapshot.complete
        assert (await selected(service, snapshot, "LITERAL")).text == "synthetic-literal"
        assert [path for _, path, _ in api.requests] == [POD_PATH] * 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state", [(401, "forbidden"), (403, "forbidden"), (404, "not-found"), (500, "invalid")]
)
async def test_source_errors_are_fixed_metadata_and_never_server_payload(tmp_path, status, state):
    async with inspection_source(tmp_path) as (service, api, _):
        api.statuses[SECRET_PATH] = status
        snapshot = await service.index()
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == state
        )
        assert "inspection-private-server-body" not in repr(snapshot)
        result = await selected(service, snapshot, "CHOSEN")
        assert result.text is None and not result.complete
        assert (await selected(service, snapshot, "LITERAL")).text == "synthetic-literal"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "resourceVersion", "content"])
async def test_fresh_source_replacement_version_or_same_version_content_requires_reload(
    tmp_path, change
):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        if change == "content":
            api.records[SECRET_PATH]["data"]["chosen"] = base64.b64encode(b"changed-value").decode()
        else:
            api.records[SECRET_PATH]["metadata"][change] = "changed"
        with pytest.raises(AppError, match="reload"):
            await selected(service, snapshot, "CHOSEN")
        assert service.operation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "resourceVersion", "content"])
async def test_fresh_pod_replacement_version_or_same_version_reference_change_never_rebinds(
    tmp_path, change
):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        if change == "content":
            api.records[POD_PATH]["spec"]["containers"][0]["env"][0]["value"] = "changed"
        else:
            api.records[POD_PATH]["metadata"][change] = "changed"
        with pytest.raises(AppError):
            await selected(service, snapshot, "LITERAL")
        assert len(api.requests) == 5


@pytest.mark.asyncio
async def test_final_pod_check_rejects_changes_during_source_reads(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):

        def change(api, path):
            if path == SECRET_PATH:
                api.records[POD_PATH]["metadata"]["resourceVersion"] = "changed-during-index"

        api.before_response = change
        with pytest.raises(AppError, match="reload"):
            await service.index()
        assert service.snapshot is None


@pytest.mark.asyncio
async def test_formerly_absent_optional_source_becoming_present_requires_reload(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        container = api.records[POD_PATH]["spec"]["containers"][0]
        container["envFrom"] = [{"configMapRef": {"name": "later", "optional": True}}]
        container["env"] = [{"name": "LITERAL", "value": "safe"}]
        snapshot = await service.index()
        assert snapshot.sources[0].state == "not-found"
        assert (await selected(service, snapshot, "LITERAL")).text == "safe"
        path = f"/api/v1/namespaces/{NAMESPACE}/configmaps/later"
        api.records[path] = source_fixture("ConfigMap", "later", {"LITERAL": "newly-present"})
        with pytest.raises(AppError, match="reload"):
            await selected(service, snapshot, "LITERAL")


@pytest.mark.asyncio
async def test_intents_are_one_use_revoked_on_new_intent_and_consumed_on_failed_reads(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        identity = entry(snapshot, "LITERAL").id
        first = service.new_intent(snapshot.id, identity, "reveal")
        second = service.new_intent(snapshot.id, identity, "copy")
        with pytest.raises(AppError, match="expired"):
            await service.disclose(first)
        assert len(api.requests) == 4
        assert (await service.disclose(second)).text == "synthetic-literal"
        with pytest.raises(AppError, match="expired"):
            await service.disclose(second)
        third = service.new_intent(snapshot.id, identity, "reveal")
        api.statuses[POD_PATH] = 403
        with pytest.raises(AppError, match="read failed"):
            await service.disclose(third)
        count = len(api.requests)
        with pytest.raises(AppError, match="expired"):
            await service.disclose(third)
        assert len(api.requests) == count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["current", "context", "version", "group", "kind", "scope", "verbs", "container", "target"],
)
async def test_unsupported_or_changed_capture_fails_before_transport(tmp_path, change):
    async with inspection_source(tmp_path) as (service, api, current):
        if change == "current":
            current[0] = False
        elif change == "context":
            service.target = replace(service.target, session=SessionIdentity("other", 1))
        elif change == "target":
            service.target = replace(service.target, resource="configmaps")
        elif change == "container":
            service.target = replace(service.target, container="other")
        else:
            service.resource = replace(
                service.resource,
                **{
                    "version": {"version": "v2"},
                    "group": {"group": "apps"},
                    "kind": {"kind": "ConfigMap"},
                    "scope": {"namespaced": False},
                    "verbs": {"verbs": frozenset()},
                }[change],
            )
        with pytest.raises(AppError):
            await service.index()
        assert api.requests == []


@pytest.mark.asyncio
async def test_cursor_cancellation_does_not_cancel_metadata_index_but_revokes_disclosure(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        api.held_paths.add(POD_PATH)
        task = asyncio.create_task(service.index())
        await asyncio.wait_for(api.started.wait(), 3)
        service.cancel_disclosure()
        assert service.operation_count == 1
        api.release.set()
        snapshot = await task
        api.release.clear()
        api.started.clear()
        intent = service.new_intent(snapshot.id, entry(snapshot, "LITERAL").id, "reveal")
        task = asyncio.create_task(service.disclose(intent))
        await asyncio.wait_for(api.started.wait(), 3)
        service.cancel_disclosure()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.snapshot_current(snapshot.id) and service.operation_count == 0


@pytest.mark.asyncio
async def test_observed_uid_version_scope_changes_invalidate_without_decoding_manifest(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        record = resource_record(descriptor("Pod"), api.records[POD_PATH], NAMESPACE)
        service.observe_pod(record)
        assert service.snapshot_current(snapshot.id)
        service.observe_pod(
            replace(record, resource_version="watch-new-version", _manifest=b"not-json")
        )
        assert service.snapshot is None
        assert not service.snapshot_current(snapshot.id)
        assert len(api.requests) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("chunked", [False, True])
async def test_individual_transport_cap_includes_chunked_bodies(tmp_path, chunked):
    async with inspection_source(tmp_path) as (service, api, _):
        api.payloads[POD_PATH] = b'{"oversized":"' + b"x" * (2 * 1024 * 1024) + b'"}'
        if chunked:
            api.chunked_paths.add(POD_PATH)
        with pytest.raises(AppError, match="read failed"):
            await service.index()
        assert service.snapshot is None and service.operation_count == 0


@pytest.mark.asyncio
async def test_deadline_cancels_held_socket_and_does_not_publish(tmp_path, monkeypatch):
    monkeypatch.setattr("kuberich.services.container_inspection.MAX_OPERATION_SECONDS", 0.05)
    async with inspection_source(tmp_path) as (service, api, _):
        api.held_paths.add(POD_PATH)
        with pytest.raises(AppError, match="timed out"):
            await service.index()
        assert service.snapshot is None and service.operation_count == 0
        await service.close()
        await service.close()
        with pytest.raises(AppError):
            service.require_current()


@pytest.mark.asyncio
async def test_close_drains_held_parser_under_repeated_cancellation_before_client_close(
    tmp_path, monkeypatch
):
    import kuberich.services.container_inspection as implementation

    original = implementation.reference_plan
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def held(record, identity):
        started.set()
        try:
            assert release.wait(5)
            return original(record, identity)
        finally:
            finished.set()

    monkeypatch.setattr(implementation, "reference_plan", held)
    async with inspection_source(tmp_path) as (service, api, _):
        caller = asyncio.create_task(service.index())
        assert await asyncio.to_thread(started.wait, 3)
        closer = asyncio.create_task(service.close())
        await asyncio.sleep(0)  # Enter the owner before exercising repeated cancellation.
        for _ in range(3):
            caller.cancel()
            closer.cancel()
            await asyncio.sleep(0)
        assert not closer.done() and service.operation_count == 1 and not finished.is_set()
        release.set()
        await closer
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert finished.is_set() and service.operation_count == 0
        assert service.snapshot is None
        assert [path for _, path, _ in api.requests] == [POD_PATH]


@pytest.mark.asyncio
async def test_reference_limit_never_fetches_beyond_first_thirty_two(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        container = api.records[POD_PATH]["spec"]["containers"][0]
        container["envFrom"] = [
            {"configMapRef": {"name": f"source-{index}", "optional": True}} for index in range(40)
        ]
        container["env"] = [{"name": "LITERAL", "value": "synthetic"}]
        snapshot = await service.index()
        assert snapshot.reads == 34 and len(api.requests) == 34
        assert ReasonCode.REFERENCE_LIMIT in snapshot.notices
        result = await selected(service, snapshot, "LITERAL")
        assert result.text is None and not result.complete


@pytest.mark.asyncio
async def test_invalid_source_identity_is_metadata_only_and_unavailable(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        api.records[SECRET_PATH]["metadata"]["uid"] = ""
        snapshot = await service.index()
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == "invalid"
        )
        assert (await selected(service, snapshot, "CHOSEN")).text is None


@pytest.mark.asyncio
async def test_source_failure_and_optional_absence_are_distinct_from_empty_value(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        api.records[SECRET_PATH]["data"]["chosen"] = ""
        snapshot = await service.index()
        result = await selected(service, snapshot, "CHOSEN")
        assert result.complete and result.text == ""
        original = copy.deepcopy(api.records[SECRET_PATH])
        api.statuses[SECRET_PATH] = 403
        with pytest.raises(AppError, match="reload"):
            await selected(service, snapshot, "CHOSEN")
        api.records[SECRET_PATH] = original


@pytest.mark.asyncio
async def test_source_timeout_is_explicit_and_does_not_hide_independent_literal(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        service.client.timeout = 0.05
        api.held_paths.add(SECRET_PATH)
        snapshot = await service.index()
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == "timed-out"
        )
        assert (await selected(service, snapshot, "LITERAL")).text == "synthetic-literal"


@pytest.mark.asyncio
async def test_missing_source_uid_is_rejected_by_owned_binding_parser(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        del api.records[SECRET_PATH]["metadata"]["uid"]
        snapshot = await service.index()
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == "invalid"
        )


@pytest.mark.asyncio
async def test_retained_input_limit_reserves_final_root_and_publishes_incomplete_metadata(
    tmp_path, monkeypatch
):
    async with inspection_source(tmp_path) as (service, api, _):
        root_size = resource_record(descriptor("Pod"), api.records[POD_PATH], NAMESPACE).size_bytes
        source_size = resource_record(
            descriptor("ConfigMap"), api.records[CONFIG_PATH], NAMESPACE
        ).size_bytes
        monkeypatch.setattr(
            "kuberich.services.container_inspection.MAX_INPUT_BYTES", root_size * 2 + source_size
        )
        snapshot = await service.index()
        assert not snapshot.complete and ReasonCode.INPUT_LIMIT in snapshot.notices
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == "not-collected-limit"
        )
        assert [path for _, path, _ in api.requests] == [POD_PATH, CONFIG_PATH, POD_PATH]
        with pytest.raises(AppError, match="reload"):
            await selected(service, snapshot, "LITERAL")


@pytest.mark.asyncio
async def test_remaining_transport_allowance_exhaustion_is_not_reported_as_complete(
    tmp_path, monkeypatch
):
    async with inspection_source(tmp_path) as (service, api, _):
        root_size = resource_record(descriptor("Pod"), api.records[POD_PATH], NAMESPACE).size_bytes
        monkeypatch.setattr(
            "kuberich.services.container_inspection.MAX_INPUT_BYTES", root_size * 2 + 1
        )
        snapshot = await service.index()
        assert not snapshot.complete and ReasonCode.INPUT_LIMIT in snapshot.notices
        assert all(source.state == "invalid" for source in snapshot.sources)


@pytest.mark.asyncio
async def test_invalid_intent_snapshot_entry_and_action_fail_before_reads(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        for identity, selected_entry, action in (
            (uuid4(), entry(snapshot, "LITERAL").id, "reveal"),
            (snapshot.id, ("env", 999, "absent"), "copy"),
            (snapshot.id, entry(snapshot, "LITERAL").id, "unsupported"),
        ):
            with pytest.raises(AppError, match="expired"):
                service.new_intent(identity, selected_entry, action)
        assert len(api.requests) == 4
        await service.close()
        assert not service.snapshot_current(snapshot.id)


@pytest.mark.asyncio
async def test_second_disclosure_consumes_new_intent_while_cancelled_predecessor_drains(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        api.held_paths.add(POD_PATH)
        api.started.clear()
        first = service.new_intent(snapshot.id, entry(snapshot, "LITERAL").id, "reveal")
        caller = asyncio.create_task(service.disclose(first))
        await asyncio.wait_for(api.started.wait(), 3)
        second = service.new_intent(snapshot.id, entry(snapshot, "LITERAL").id, "copy")
        with pytest.raises(AppError, match="busy"):
            await service.disclose(second)
        with pytest.raises(AppError, match="expired"):
            await service.disclose(second)
        with pytest.raises(asyncio.CancelledError):
            await caller


@pytest.mark.asyncio
async def test_reload_cancels_and_drains_previous_held_get_then_publishes_new_snapshot(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        api.held_paths.add(POD_PATH)
        first = asyncio.create_task(service.index())
        await asyncio.wait_for(api.started.wait(), 3)
        second = asyncio.create_task(service.index())
        await asyncio.sleep(0)
        api.release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        snapshot = await second
        assert service.snapshot_current(snapshot.id) and service.operation_count == 0


@pytest.mark.asyncio
async def test_disclosure_final_root_recheck_rejects_midread_change(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()

        def change(api, path):
            if path == SECRET_PATH:
                api.records[POD_PATH]["metadata"]["resourceVersion"] = "mid-disclosure-change"

        api.before_response = change
        with pytest.raises(AppError, match="reload"):
            await selected(service, snapshot, "LITERAL")


@pytest.mark.asyncio
async def test_disclosure_deadline_consumes_token_and_drains_held_get(tmp_path, monkeypatch):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        monkeypatch.setattr("kuberich.services.container_inspection.MAX_OPERATION_SECONDS", 0.05)
        api.held_paths.add(POD_PATH)
        intent = service.new_intent(snapshot.id, entry(snapshot, "LITERAL").id, "reveal")
        with pytest.raises(AppError, match="timed out"):
            await service.disclose(intent)
        assert service.operation_count == 0
        with pytest.raises(AppError, match="expired"):
            await service.disclose(intent)


@pytest.mark.asyncio
async def test_broken_source_body_is_unreachable_and_does_not_disclose_remote_payload(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        api.truncated_paths.add(SECRET_PATH)
        snapshot = await service.index()
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == "unreachable"
        )
        assert "inspection-private" not in repr(snapshot)
        assert (await selected(service, snapshot, "CHOSEN")).text is None


@pytest.mark.asyncio
async def test_cancelled_reload_drains_previous_parser_without_starting_another_read(
    tmp_path, monkeypatch
):
    import kuberich.services.container_inspection as implementation

    original = implementation.reference_plan
    started, release = threading.Event(), threading.Event()

    def held(record, identity):
        started.set()
        assert release.wait(5)
        return original(record, identity)

    monkeypatch.setattr(implementation, "reference_plan", held)
    async with inspection_source(tmp_path) as (service, api, _):
        first = asyncio.create_task(service.index())
        assert await asyncio.to_thread(started.wait, 3)
        reload = asyncio.create_task(service.index())
        await asyncio.sleep(0)
        reload.cancel()
        await asyncio.sleep(0)
        reload.cancel()
        assert service.operation_count == 1
        release.set()
        for caller in (first, reload):
            with pytest.raises(asyncio.CancelledError):
                await caller
        assert service.snapshot is None and service.operation_count == 0
        assert [path for _, path, _ in api.requests] == [POD_PATH]


@pytest.mark.asyncio
async def test_transport_and_normalized_retained_source_bytes_both_obey_the_shared_limit(
    tmp_path, monkeypatch
):
    async with inspection_source(tmp_path) as (service, api, _):
        root_size = resource_record(descriptor("Pod"), api.records[POD_PATH], NAMESPACE).size_bytes
        compact = json.dumps(api.records[CONFIG_PATH], separators=(",", ":")).encode()
        api.payloads[CONFIG_PATH] = compact
        monkeypatch.setattr(
            "kuberich.services.container_inspection.MAX_INPUT_BYTES", root_size * 2 + len(compact)
        )
        snapshot = await service.index()
        assert not snapshot.complete and ReasonCode.INPUT_LIMIT in snapshot.notices
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "ConfigMap")
            == "not-collected-limit"
        )


@pytest.mark.asyncio
async def test_normalized_root_retention_cannot_exceed_the_shared_input_cap(tmp_path, monkeypatch):
    async with inspection_source(tmp_path) as (service, api, _):
        compact = json.dumps(api.records[POD_PATH], separators=(",", ":")).encode()
        api.payloads[POD_PATH] = compact
        monkeypatch.setattr("kuberich.services.container_inspection.MAX_INPUT_BYTES", len(compact))
        with pytest.raises(AppError, match="input limit"):
            await service.index()
        assert service.snapshot is None


@pytest.mark.asyncio
async def test_concurrent_reloads_reject_retired_generation_after_owned_parser_drains(
    tmp_path, monkeypatch
):
    import kuberich.services.container_inspection as implementation

    original = implementation.reference_plan
    started, release = threading.Event(), threading.Event()

    def held(record, identity):
        started.set()
        assert release.wait(5)
        return original(record, identity)

    monkeypatch.setattr(implementation, "reference_plan", held)
    async with inspection_source(tmp_path) as (service, _api, _):
        first = asyncio.create_task(service.index())
        assert await asyncio.to_thread(started.wait, 3)
        second = asyncio.create_task(service.index())
        await asyncio.sleep(0)
        third = asyncio.create_task(service.index())
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(AppError, match="reload"):
            await second
        snapshot = await third
        assert service.snapshot_current(snapshot.id) and service.operation_count == 0


@pytest.mark.asyncio
async def test_completed_index_cannot_publish_after_public_handoff_invalidation(
    tmp_path, monkeypatch
):
    import kuberich.services.container_inspection as implementation

    original = implementation.build_inspection
    returned = threading.Event()

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        returned.set()
        return result

    monkeypatch.setattr(implementation, "build_inspection", observed)
    async with inspection_source(tmp_path) as (service, api, _):
        loop = asyncio.get_running_loop()
        scheduled = False

        def current():
            nonlocal scheduled
            if returned.is_set() and not scheduled:
                scheduled = True
                # The real child publishes and completes before this queued public
                # invalidation runs, before its shield wakes the public caller.
                loop.call_soon(service.invalidate)
            return True

        service.current = current
        with pytest.raises(AppError, match="reload"):
            await service.index()
        assert scheduled and service.snapshot is None and service.operation_count == 0
        assert len(api.requests) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["invalidate", "intent", "scope"])
async def test_completed_disclosure_rechecks_public_handoff_before_return(
    tmp_path, monkeypatch, change
):
    import kuberich.services.container_inspection as implementation

    original = implementation.resolve_selected
    returned = threading.Event()

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        returned.set()
        return result

    monkeypatch.setattr(implementation, "resolve_selected", observed)
    async with inspection_source(tmp_path) as (service, api, current_scope):
        snapshot = await service.index()
        loop = asyncio.get_running_loop()
        scheduled = False

        def changed():
            if change == "invalidate":
                service.invalidate()
            elif change == "intent":
                service.cancel_disclosure()
            else:
                current_scope[0] = False

        def current():
            nonlocal scheduled
            if returned.is_set() and not scheduled:
                scheduled = True
                loop.call_soon(changed)
            return current_scope[0]

        service.current = current
        with pytest.raises(AppError):
            await selected(service, snapshot, "CHOSEN")
        assert scheduled and service.operation_count == 0 and len(api.requests) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http-500", "malformed-json"])
async def test_large_root_does_not_turn_unrelated_source_failure_into_input_exhaustion(
    tmp_path, failure
):
    async with inspection_source(tmp_path) as (service, api, _):
        api.records[POD_PATH]["metadata"]["annotations"] = {
            "synthetic-padding": "x" * (1100 * 1024)
        }
        if failure == "http-500":
            api.statuses[SECRET_PATH] = 500
        else:
            api.payloads[SECRET_PATH] = b"not-valid-json"
        snapshot = await service.index()
        assert (
            next(source.state for source in snapshot.sources if source.ref.kind == "Secret")
            == "invalid"
        )
        assert ReasonCode.INPUT_LIMIT not in snapshot.notices
        assert (await selected(service, snapshot, "LITERAL")).text == "synthetic-literal"
        assert len(api.requests) == 8


@pytest.mark.asyncio
async def test_changed_source_retires_only_old_snapshot_until_successful_reload(tmp_path):
    async with inspection_source(tmp_path) as (service, api, _):
        snapshot = await service.index()
        api.records[SECRET_PATH]["data"]["chosen"] = base64.b64encode(
            b"updated-synthetic-value"
        ).decode()
        with pytest.raises(AppError, match="reload"):
            await selected(service, snapshot, "CHOSEN")
        assert not service.snapshot_current(snapshot.id) and service.snapshot is None
        reads = len(api.requests)
        with pytest.raises(AppError, match="expired"):
            service.new_intent(snapshot.id, entry(snapshot, "CHOSEN").id, "reveal")
        assert len(api.requests) == reads
        refreshed = await service.index()
        assert service.snapshot_current(refreshed.id)
        assert (await selected(service, refreshed, "CHOSEN")).text == "updated-synthetic-value"
        service.cancel_disclosure()
        assert service.snapshot_current(refreshed.id)
