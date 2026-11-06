"""Finite history ownership rejects replaced identities and obsolete intents."""

import asyncio
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from aiohttp import web

from kuberich.domain.history import (
    BackendCandidate,
    ExternalHistoryBackend,
    HistoryBackend,
    HistoryOptions,
    HistoryRequest,
    HistoryScope,
    HistorySnapshot,
    HistoryStatus,
    history_window,
)
from kuberich.domain.pulse import PulseScope
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services import history as history_service
from kuberich.services.access import AccessPolicy
from kuberich.services.history_workspace import HistoryWorkspace
from tests.support.connections import certificate
from tests.support.history import history_discovery, history_http, matrix, service
from tests.support.resources import item, reader_fixture

NOW = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)
BACKEND = HistoryBackend("team", "metrics")


def request(session, *, options=None, revision=0, scope=None, seconds=900):
    start, end, step = history_window(NOW, seconds)
    return HistoryRequest(
        uuid4(),
        scope or HistoryScope(session, "cluster", "team"),
        options or HistoryOptions(BACKEND),
        start,
        end,
        step,
        ("cpu", "memory"),
        revision,
    )


def owner(client, session, *, observed=None, **kwargs):
    return HistoryWorkspace(
        client,
        history_discovery(),
        session,
        AccessPolicy(False),
        lambda: True,
        observed_session=observed or (lambda: session),
        now=lambda: NOW,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_real_http_cache_is_bounded_ttl_and_rechecks_service_uid(tmp_path):
    calls = []
    uid = ["service-owned"]
    clock = [0.0]

    async def handler(incoming):
        calls.append(incoming.path)
        if incoming.path.endswith("/services/metrics"):
            return web.json_response(service(uid=uid[0]))
        assert incoming.headers["Authorization"] == "Bearer synthetic"
        return web.json_response(matrix(incoming.query))

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session, monotonic=lambda: clock[0])
        first = await workspace.collect(request(session))
        assert first.status in {HistoryStatus.VALID, HistoryStatus.PARTIAL}
        queries = len([path for path in calls if "/proxy/" in path])
        assert queries == 5 and workspace.retained_points > 0
        second = await workspace.collect(request(session))
        assert second.request_id != first.request_id
        assert len([path for path in calls if "/proxy/" in path]) == queries
        assert len([path for path in calls if path.endswith("/services/metrics")]) == 4
        clock[0] = 31
        await workspace.collect(request(session))
        assert len([path for path in calls if "/proxy/" in path]) == queries * 2
        uid[0] = "replacement"
        changed = await workspace.collect(request(session))
        assert changed.status is HistoryStatus.CONFIGURATION_CONFLICT
        assert workspace.retained_points == workspace.retained_bytes == 0
        await workspace.close()
        assert workspace.operation_count == 0
        assert (await reader.session.get_json("/api/v1/namespaces/team/services/metrics"))[
            "kind"
        ] == "Service"


@pytest.mark.asyncio
async def test_connection_generation_and_config_revision_cannot_reuse_cache(tmp_path):
    async def handler(incoming):
        return web.json_response(
            service() if incoming.path.endswith("/services/metrics") else matrix(incoming.query)
        )

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        observed = [session]
        workspace = owner(reader.session, session, observed=lambda: observed[0])
        await workspace.collect(request(session))
        observed[0] = replace(session, generation=2)
        with pytest.raises(AppError):
            await workspace.collect(request(session))
        workspace.invalidate()
        assert workspace.retained_points == 0 and workspace.config_revision == 1
        with pytest.raises(AppError):
            await workspace.collect(request(observed[0]))
        await workspace.collect(request(observed[0], revision=1))
        observed[0] = SessionIdentity("owned", 2)
        with pytest.raises(AppError):
            workspace.require_current(HistoryScope(observed[0], "cluster"))
        await workspace.close()
        with pytest.raises(AppError):
            workspace.require_current(HistoryScope(session, "cluster"))


@pytest.mark.asyncio
async def test_detail_suppresses_only_overview_history_and_close_drains_held_parser(
    tmp_path, monkeypatch
):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = history_service.parse_history_matrix

    def held(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(5)
            return original(*args, **kwargs)
        finally:
            finished.set()

    async def handler(incoming):
        return web.json_response(
            service() if incoming.path.endswith("/services/metrics") else matrix(incoming.query)
        )

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        scope = HistoryScope(session, "cluster", "team")
        workspace.enter_detail(scope)
        paused = await workspace.overview(PulseScope(session, "team"), HistoryOptions(BACKEND))
        assert paused.status is HistoryStatus.UNAVAILABLE and "paused" in paused.detail
        monkeypatch.setattr(history_service, "parse_history_matrix", held)
        task = asyncio.create_task(workspace.collect(request(session, revision=1)))
        assert await asyncio.to_thread(entered.wait, 5)
        close = asyncio.create_task(workspace.close())
        await asyncio.sleep(0)
        close.cancel()
        await asyncio.sleep(0)
        close.cancel()
        assert not close.done()
        release.set()
        await close
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and workspace.operation_count == 0
        assert (await reader.session.get_json("/api/v1/namespaces/team/services/metrics"))[
            "kind"
        ] == "Service"


@pytest.mark.asyncio
async def test_latest_intent_replaces_pending_collection_and_leave_detail_resumes_overview(
    tmp_path,
):
    entered, release = asyncio.Event(), asyncio.Event()
    hold = [True]

    async def handler(incoming):
        if incoming.path.endswith("/services/metrics"):
            return web.json_response(service())
        if hold[0]:
            entered.set()
            await release.wait()
        return web.json_response(matrix(incoming.query))

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        task = asyncio.create_task(workspace.collect(request(session)))
        await asyncio.wait_for(entered.wait(), 5)
        tasks = [
            asyncio.create_task(workspace.collect(request(session, seconds=seconds)))
            for seconds in (1800, 3600, 10800)
        ]
        hold[0] = False
        release.set()
        results = await asyncio.gather(task, *tasks, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert isinstance(results[-1], HistorySnapshot) and results[-1].end - results[
            -1
        ].start == timedelta(seconds=10800)
        await workspace.leave_detail()
        result = await workspace.overview(PulseScope(session, "team"), HistoryOptions(BACKEND))
        assert result.status in {HistoryStatus.VALID, HistoryStatus.PARTIAL}
        assert (
            await workspace.overview(PulseScope(session, "team"), None)
        ).status is HistoryStatus.UNCONFIGURED
        await workspace.close()


@pytest.mark.asyncio
async def test_detection_is_explicit_bounded_and_never_probes_candidates(tmp_path):
    paths = []

    async def handler(incoming):
        paths.append(incoming.path)
        assert incoming.path.endswith("/services")
        return web.json_response(
            {
                "metadata": {"resourceVersion": "owned"},
                "items": [
                    service(name=f"metrics-{index}")
                    | {
                        "metadata": {
                            **service(name=f"metrics-{index}")["metadata"],
                            "uid": f"uid-{index}",
                        }
                    }
                    for index in range(129)
                ],
            }
        )

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        for namespaces in ((), ("team",) * 2, ("a", "b", "c", "d", "e"), ("bad/name",)):
            with pytest.raises(AppError):
                await workspace.detect(namespaces)
        result = await workspace.detect(("team",))
        assert len(result.items) == 16 and not result.complete and len(paths) == 1
        selected = workspace.selected_candidate(result.items[0])
        assert selected.endpoint.service == "metrics-0"
        assert (
            workspace.selected_candidate(
                BackendCandidate("team", "other", "other-uid", 9090), selected
            ).endpoint.service
            == "other"
        )
        await workspace.close()


def test_target_observation_rejects_recreation_creation_change_and_container_removal():
    session = SessionIdentity("owned", 1)
    workspace = owner(None, session)
    resource = history_discovery().find("pods")
    target = ResourceTarget(session, "", "pods", "team", "one", "owned-one", "app")
    scope = HistoryScope(
        session, "container", "team", target, resource, container_field="containers"
    )
    record = resource_record(resource, item())
    workspace.observe_target(scope, record)
    for replacement in (
        None,
        replace(record, uid="recreated"),
        resource_record(resource, {**item(), "spec": {"containers": []}}),
    ):
        with pytest.raises(AppError):
            workspace.observe_target(scope, replacement)
    with pytest.raises(AppError):
        workspace.observe_target(replace(scope, created_at=NOW), record)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "after-query", "cache-hit"])
@pytest.mark.parametrize("change", ["uid", "container"])
async def test_target_rejection_returns_conflict_and_revokes_data_without_cancelling_itself(
    tmp_path, phase, change
):
    target_reads = 0
    reject = [phase != "cache-hit"]
    paths = []

    async def handler(incoming):
        nonlocal target_reads
        paths.append(incoming.path)
        if incoming.path.endswith("/pods/one"):
            target_reads += 1
            changed = reject[0] and (phase == "initial" or target_reads >= 2)
            document = item(uid="replacement" if changed and change == "uid" else "owned-one")
            if changed and change == "container":
                document["spec"]["containers"] = []
            return web.json_response(document)
        if incoming.path.endswith("/services/metrics"):
            return web.json_response(service())
        return web.json_response(
            matrix(
                incoming.query,
                labels={"namespace": "team", "pod": "one", "uid": "owned-one"}
                if incoming.query["query"].startswith("max by(namespace,pod,uid)")
                else {},
            )
        )

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        scope = HistoryScope(
            session,
            "container" if change == "container" else "pod",
            "team",
            ResourceTarget(
                session,
                "",
                "pods",
                "team",
                "one",
                "owned-one",
                "app" if change == "container" else None,
            ),
            history_discovery().find("pods"),
            container_field="containers" if change == "container" else None,
        )
        try:
            if phase == "cache-hit":
                first = await workspace.collect(request(session, scope=scope))
                assert first.status in {
                    HistoryStatus.VALID,
                    HistoryStatus.PARTIAL,
                    HistoryStatus.NO_DATA,
                }
                assert workspace.retained_bytes > 0
                reject[0] = True
                target_reads = 0
                paths.clear()
            revision = workspace.config_revision
            incoming = request(session, scope=scope, revision=revision)
            rejected = await workspace.collect(incoming)
            assert rejected.status is HistoryStatus.CONFIGURATION_CONFLICT
            assert rejected.request_id == incoming.id and not rejected.series
            assert workspace.config_revision == revision + 1
            assert (
                workspace.retained_points
                == workspace.retained_bytes
                == workspace.operation_count
                == 0
            )
            assert workspace.snapshot.status is HistoryStatus.UNCONFIGURED
            assert workspace.snapshot.request_id is None and not workspace.snapshot.series
            assert target_reads == (1 if phase == "initial" else 2)
            assert bool([path for path in paths if "/proxy/" in path]) == (phase == "after-query")
            assert (await reader.session.get_json("/api/v1/namespaces/team/services/metrics"))[
                "kind"
            ] == "Service"
        finally:
            await workspace.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["caller", "observed-target"])
async def test_external_cancellation_or_target_revocation_still_cancels_and_drains_collection(
    tmp_path, revocation
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(incoming):
        if incoming.path.endswith("/pods/one"):
            return web.json_response(item())
        if incoming.path.endswith("/services/metrics"):
            return web.json_response(service())
        entered.set()
        await release.wait()
        return web.json_response(matrix(incoming.query))

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        resource = history_discovery().find("pods")
        scope = HistoryScope(
            session,
            "pod",
            "team",
            ResourceTarget(session, "", "pods", "team", "one", "owned-one"),
            resource,
        )
        task = asyncio.create_task(workspace.collect(request(session, scope=scope)))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if revocation == "caller":
                task.cancel()
            else:
                with pytest.raises(AppError, match="target changed"):
                    workspace.observe_target(
                        scope, resource_record(resource, item(uid="replacement"))
                    )
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (
                workspace.retained_bytes
                == workspace.retained_points
                == workspace.operation_count
                == 0
            )
            assert not workspace.snapshot.series
            assert (await reader.session.get_json("/api/v1/namespaces/team/services/metrics"))[
                "kind"
            ] == "Service"
        finally:
            release.set()
            await workspace.close()
            await asyncio.gather(task, return_exceptions=True)


def test_candidate_selection_preserves_literal_source_and_cluster_bindings():
    session = SessionIdentity("owned", 1)
    workspace = owner(None, session)
    original = HistoryOptions(
        HistoryBackend(
            "team",
            "original",
            matchers=(("job", "cadvisor"),),
            cluster_label="cluster",
            cluster_value="owned",
        ),
        node_matchers=(("job", "node"),),
        state_matchers=(("job", "state"),),
    )
    selected = workspace.selected_candidate(
        BackendCandidate("team", "selected", "owned-service", 9090), original
    )
    assert selected.endpoint.labels("team") == (
        ("cluster", "owned"),
        ("job", "cadvisor"),
        ("namespace", "team"),
    )
    assert (
        selected.node_matchers == original.node_matchers
        and selected.state_matchers == original.state_matchers
    )


@pytest.mark.asyncio
async def test_external_owner_cache_and_auth_rotation_are_independent(tmp_path):
    async def handler(incoming):
        return web.json_response(matrix(incoming.query))

    async with history_http(handler) as origin, reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        options = HistoryOptions(ExternalHistoryBackend(origin + "/select/4/prometheus"))
        result = await workspace.collect(request(session, options=options))
        assert result.endpoint_identity.origin == origin
        assert result.endpoint_identity.prefix == "/select/4/prometheus"
        await workspace.close()


@pytest.mark.asyncio
async def test_external_rotation_invalidates_cached_data_and_changed_endpoint_retires_pool(
    tmp_path,
):
    tls, _ = certificate(tmp_path)
    token = tmp_path / "independent-token"
    token.write_text("synthetic-first")
    token.chmod(0o600)
    calls = []

    async def handler(incoming):
        calls.append((incoming.path, incoming.headers.get("Authorization")))
        return web.json_response(matrix(incoming.query))

    async with (
        history_http(handler, tls=tls) as origin,
        reader_fixture(tmp_path, handler) as reader,
    ):
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        endpoint = ExternalHistoryBackend(
            origin, ca_file=tmp_path / "fixture-cert", bearer_token_file=token
        )
        options = HistoryOptions(endpoint)
        await workspace.collect(request(session, options=options))
        first = len(calls)
        await workspace.collect(request(session, options=options))
        assert len(calls) == first
        token.write_text("synthetic-second")
        await workspace.collect(request(session, options=options))
        assert len(calls) == first * 2 and calls[-1][1] == "Bearer synthetic-second"
        token.chmod(0o644)
        failed = await workspace.collect(request(session, options=options))
        assert (
            failed.status is HistoryStatus.CONFIGURATION_CONFLICT and workspace.retained_bytes == 0
        )
        token.chmod(0o600)
        await workspace.collect(
            request(
                session,
                options=replace(options, endpoint=replace(endpoint, url=origin + "/tenant")),
            )
        )
        assert calls[-1][0].startswith("/tenant/")
        await workspace.close()


@pytest.mark.asyncio
async def test_cache_retention_and_visible_expiry_hold_across_many_windows(tmp_path):
    observed = [NOW]

    async def handler(incoming):
        return web.json_response(
            service() if incoming.path.endswith("/services/metrics") else matrix(incoming.query)
        )

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = HistoryWorkspace(
            reader.session,
            history_discovery(),
            session,
            AccessPolicy(True),
            lambda: True,
            observed_session=lambda: session,
            now=lambda: observed[0],
        )
        for index in range(12):
            spec = request(session, seconds=86400)
            spec = replace(
                spec,
                start=spec.start - timedelta(minutes=index * 2),
                end=spec.end - timedelta(minutes=index * 2),
            )
            await workspace.collect(spec)
            assert (
                workspace.retained_bytes <= 4 * 1024 * 1024 and workspace.retained_points <= 65536
            )
        assert workspace.retained_points < 12 * 1442
        observed[0] += timedelta(seconds=61)
        assert workspace.snapshot.status is HistoryStatus.STALE
        await workspace.close()


@pytest.mark.asyncio
async def test_current_member_capture_reuses_verified_owner_chain_and_stamps_time(tmp_path):
    from kuberich.domain.resources import Discovery, api_resource
    from tests.support.resources import descriptor

    deployment_resource = api_resource("apps/v1", descriptor("deployments", kind="Deployment"))
    replica_resource = api_resource("apps/v1", descriptor("replicasets", kind="ReplicaSet"))
    discovery = Discovery((*history_discovery().resources, deployment_resource, replica_resource))
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "workload",
            "namespace": "team",
            "uid": "workload-uid",
            "resourceVersion": "owned",
        },
    }
    replica = {
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "metadata": {
            "name": "replica",
            "namespace": "team",
            "uid": "replica-uid",
            "resourceVersion": "owned",
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": "workload",
                    "uid": "workload-uid",
                    "controller": True,
                }
            ],
        },
    }
    pod = item()
    pod["metadata"]["ownerReferences"] = [
        {
            "apiVersion": "apps/v1",
            "kind": "ReplicaSet",
            "name": "replica",
            "uid": "replica-uid",
            "controller": True,
        }
    ]
    listed = []

    async def handler(incoming):
        if incoming.path.endswith("/services/metrics"):
            return web.json_response(service())
        if incoming.path.endswith("/deployments/workload"):
            return web.json_response(deployment)
        if incoming.path.endswith("/pods") or incoming.path.endswith("/replicasets"):
            listed.append(incoming.path)
            return web.json_response(
                {
                    "metadata": {"resourceVersion": "owned"},
                    "items": [replica if incoming.path.endswith("/replicasets") else pod],
                }
            )
        return web.json_response(matrix(incoming.query))

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = HistoryWorkspace(
            reader.session,
            discovery,
            session,
            AccessPolicy(False),
            lambda: True,
            observed_session=lambda: session,
            now=lambda: NOW,
        )
        scope = HistoryScope(
            session,
            "workload",
            "team",
            ResourceTarget(session, "apps", "deployments", "team", "workload", "workload-uid"),
            deployment_resource,
            membership="current-members",
        )
        result = await workspace.collect(request(session, scope=scope))
        assert result.membership_evidence.observed_at == NOW
        assert result.membership_evidence.status == "current-only"
        assert result.membership_evidence.members[0].uid == "owned-one"
        assert sum(path.endswith("/pods") for path in listed) == 2
        await workspace.close()


@pytest.mark.asyncio
async def test_detection_denial_unknown_ports_and_external_names_remain_explicit(tmp_path):
    async def handler(incoming):
        if "/denied/" in incoming.path:
            return web.Response(status=403)
        declarations = []
        for index, spec in enumerate(
            (
                {
                    "type": "ExternalName",
                    "externalName": "unselected.example.test",
                    "ports": [{"port": 9090}],
                },
                {"ports": [None, {"port": "bad"}, {"port": 9090, "name": "http-query"}]},
                {"ports": [{"port": 9090, "name": "unknown"}]},
                {"ports": None},
            )
        ):
            declaration = service(name=f"candidate-{index}")
            declaration["metadata"]["uid"] = f"candidate-{index}"
            declaration["metadata"]["labels"] = {}
            declaration["spec"] = spec
            declarations.append(declaration)
        return web.json_response({"metadata": {"resourceVersion": "owned"}, "items": declarations})

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        result = await workspace.detect(("denied", "team"))
        assert not result.complete and result.sources[0] == ("denied", "unavailable")
        assert len(result.items) == 1 and result.items[0].provider_hint == "auto"
        await workspace.close()
        with pytest.raises(AppError):
            await workspace.detect(("team",))
        missing = owner(reader.session, session, observed=lambda: None)
        with pytest.raises(AppError):
            await missing.detect(("team",))
        await missing.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (401, HistoryStatus.UNAUTHORIZED),
        (403, HistoryStatus.FORBIDDEN),
        (404, HistoryStatus.UNAVAILABLE),
    ],
)
async def test_selected_service_api_failure_never_uses_cached_or_external_data(
    tmp_path, code, status
):
    async def handler(incoming):
        return web.Response(status=code, text="synthetic-private-error")

    async with reader_fixture(tmp_path, handler) as reader:
        session = SessionIdentity("owned", 1)
        workspace = owner(reader.session, session)
        result = await workspace.collect(request(session))
        assert result.status is status and not result.series and workspace.retained_bytes == 0
        await workspace.close()
