"""Captured API selection uses actual list shapes without adopting stale identities."""

from copy import deepcopy

import pytest
from aiohttp import web

from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmarks import BenchmarkManager
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from tests.support.resources import reader_fixture

POD = {
    "metadata": {
        "name": "backend",
        "uid": "pod-uid",
        "namespace": "team",
        "labels": {"app": "owned"},
    },
    "spec": {"containers": [{"name": "web", "ports": [{"name": "http", "containerPort": 8080}]}]},
    "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
}
SERVICE = {
    "apiVersion": "v1",
    "kind": "Service",
    "metadata": {"name": "owned", "uid": "service-uid", "namespace": "team"},
    "spec": {"selector": {"app": "owned"}, "ports": [{"port": 80, "targetPort": "http"}]},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "descriptor",
    [{}, {"apiVersion": "v1", "kind": "Pod"}, {"kind": "Service"}, {"apiVersion": "v2"}],
)
async def test_validated_podlist_supplies_only_missing_item_descriptor(tmp_path, descriptor):
    pod = {**deepcopy(POD), **descriptor}

    async def response(request):
        if request.path.endswith("/services/owned"):
            return web.json_response(SERVICE)
        assert request.path.endswith("/pods")
        assert request.query["limit"] == "129" and request.query["labelSelector"] == "app=owned"
        return web.json_response(
            {"apiVersion": "v1", "kind": "PodList", "metadata": {}, "items": [pod]}
        )

    async with reader_fixture(tmp_path, response) as reader:
        policy = AccessPolicy(False)
        async with ProcessRunner(policy) as processes:
            forwards = ForwardManager(processes)
            manager = BenchmarkManager(forwards, BenchmarkStore(tmp_path / "records"))
            target = ResourceTarget(
                SessionIdentity(reader.session.context.name, 1),
                "",
                "services",
                "team",
                "owned",
                "service-uid",
            )
            owner = manager.create(
                reader.session,
                target,
                policy,
                lambda: True,
                settings=BenchmarkSettings(),
                environment={},
                directory=tmp_path,
            )
            try:
                if (
                    descriptor.get("kind", "Pod") != "Pod"
                    or descriptor.get("apiVersion", "v1") != "v1"
                ):
                    with pytest.raises(AppError, match="captured namespaced"):
                        await owner.candidates()
                else:
                    choices = await owner.candidates()
                    assert (
                        len(choices) == 1
                        and choices[0].pod.uid == "pod-uid"
                        and choices[0].pod_port == 8080
                    )
                assert processes.active_count == forwards.active_count == 0
            finally:
                await manager.close()
                await forwards.close()


@pytest.mark.asyncio
async def test_one_use_review_actual_owned_processes_redacted_persistence_and_restart(tmp_path):
    from dataclasses import replace

    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture, gone

    async with fixture(tmp_path) as (owner, manager, forwards, processes, store, *_):
        choices = await owner.candidates()
        with pytest.raises(AppError, match="current backend"):
            await owner.review(replace(choices[0]), RequestOptions(), LoadOptions())
        review = await owner.review(
            choices[0],
            RequestOptions(
                target="/private?key=synthetic-private",
                headers=(("Authorization", "Bearer synthetic-private"),),
                body=b"synthetic-private",
            ),
            LoadOptions(),
        )
        with pytest.raises(AppError, match="exact benchmark review"):
            await owner.run(replace(review))
        result = await owner.run(review)
        assert (
            result.completion == "complete"
            and result.metrics.attempts == 2
            and not owner.save_failed
        )
        assert owner.operation_count == forwards.active_count == processes.active_count == 0
        for pid in owner.process_ids:
            await gone(pid)
        saved = await store.scan()
        assert len(saved) == 1
        assert await BenchmarkStore(store.default_root).read(saved[0].ref) == result
        data = (saved[0].ref.directory.path / saved[0].ref.name).read_bytes()
        assert b"synthetic-private" not in data and b"Authorization" not in data
        with pytest.raises(AppError, match="exact benchmark review"):
            await owner.run(review)
        with pytest.raises(AppError, match="already active"):
            await owner.candidates()
        await owner.stop_owned()
        assert manager.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["service_uid", "pod_uid", "selector", "pod_port", "service_port", "not_ready"]
)
async def test_effect_boundary_rechecks_exact_reviewed_backend_before_any_executable(
    tmp_path, change
):
    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path) as (owner, _, forwards, processes, _, service, pod, *_):
        review = await owner.review((await owner.candidates())[0], RequestOptions(), LoadOptions())
        if change == "service_uid":
            service["metadata"]["uid"] = "replacement"
        elif change == "pod_uid":
            pod["metadata"]["uid"] = "replacement"
        elif change == "selector":
            service["spec"]["selector"] = {"app": "owned", "tier": "added"}
            pod["metadata"]["labels"]["tier"] = "added"
        elif change == "pod_port":
            pod["spec"]["containers"][0]["ports"][0]["containerPort"] = 9090
        elif change == "service_port":
            service["spec"]["ports"][0]["port"] = 81
        else:
            pod["status"]["conditions"][0]["status"] = "False"
        result = await owner.run(review)
        assert (
            result.completion == "target_lost"
            and result.metrics is None
            and result.tool_version is None
        )
        assert (
            not (tmp_path / "version.json").exists()
            and forwards.active_count == processes.active_count == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["context", "read_only", "source_loss", "client_retire", "operator_cancel"]
)
async def test_admitted_load_cancels_and_drains_for_each_owner_invalidation(tmp_path, change):
    import asyncio

    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture, gone, receipt

    current = True
    async with fixture(tmp_path, mode="attack-sleep", current=lambda: current) as (
        owner,
        manager,
        forwards,
        processes,
        *_,
    ):
        review = await owner.review((await owner.candidates())[0], RequestOptions(), LoadOptions())
        task = asyncio.create_task(owner.run(review))
        active = await receipt(tmp_path / "attack.json")
        if change == "context":
            current = False
        elif change == "read_only":
            owner.policy.tighten()
        elif change == "source_loss":
            await forwards.stop(forwards.infos[-1].identity)
        elif change == "client_retire":
            manager.invalidate_for_client(owner.client)
            await owner.cancel()
        else:
            await owner.cancel()
        result = await asyncio.wait_for(task, 5)
        assert (
            result.completion == ("cancelled" if change == "operator_cancel" else "target_lost")
            and result.metrics is None
        )
        await gone(active["pid"])
        assert not tuple(tmp_path.glob("benchmark-*")) and not tuple(
            __import__("pathlib").Path(owner.client.directory.name).glob("benchmark-*")
        )
        assert forwards.active_count == processes.active_count == owner.operation_count == 0


@pytest.mark.asyncio
async def test_readonly_refuses_owner_before_target_reads_or_tool_discovery(tmp_path):
    from tests.support.benchmarks import fixture

    with pytest.raises(AppError, match="Read-only"):
        async with fixture(tmp_path, readonly=True):
            pytest.fail("read-only owner admitted")
    assert not (tmp_path / "version.json").exists()


@pytest.mark.asyncio
async def test_edit_revoke_cancelled_preparation_manager_limit_and_client_retirement(tmp_path):
    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path) as (owner, manager, _, processes, *_):
        backend = (await owner.candidates())[0]
        review = await owner.review(backend, RequestOptions(), LoadOptions())
        owner.revoke_review()
        with pytest.raises(AppError, match="unused exact"):
            await owner.run(review)
        review = await owner.review(backend, RequestOptions(), LoadOptions())
        await owner.cancel()
        with pytest.raises(AppError, match="unused exact"):
            await owner.run(review)
        with pytest.raises(AppError, match="active or draining"):
            manager.create(
                owner.client,
                owner.target,
                owner.policy,
                owner.current,
                settings=owner.settings,
                environment={},
                directory=tmp_path,
            )
        await manager.close_for_client(owner.client)
        assert manager.active_count == processes.active_count == 0
        with pytest.raises(AppError, match="active or draining"):
            manager.create(
                owner.client,
                owner.target,
                owner.policy,
                owner.current,
                settings=owner.settings,
                environment={},
                directory=tmp_path,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,completion",
    [
        ("version-fail", "tool_failed"),
        ("attack-fail", "tool_failed"),
        ("report-malformed", "malformed_output"),
    ],
)
async def test_fixed_tool_failures_are_persisted_incomplete_without_raw_values(
    tmp_path, mode, completion
):
    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path, mode=mode) as (owner, _, forwards, processes, store, *_):
        review = await owner.review((await owner.candidates())[0], RequestOptions(), LoadOptions())
        result = await owner.run(review)
        assert result.completion == completion and result.metrics is None
        assert forwards.active_count == processes.active_count == 0
        assert len(await store.scan()) == 1 and "synthetic-private" not in owner.message


@pytest.mark.asyncio
async def test_failed_local_save_preserves_complete_in_memory_metrics(tmp_path):
    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    class RefusingStore:
        async def save(self, result):
            raise OSError("synthetic-private-disk-path")

    async with fixture(tmp_path, store=RefusingStore()) as (owner, _, forwards, processes, *_):
        result = await owner.run(
            await owner.review((await owner.candidates())[0], RequestOptions(), LoadOptions())
        )
        assert (
            result.completion == "complete" and result.metrics.attempts == 2 and owner.save_failed
        )
        assert "local save failed" in owner.message and "synthetic-private" not in owner.message
        assert forwards.active_count == processes.active_count == 0


@pytest.mark.asyncio
async def test_direct_pod_source_and_exact_owned_forward_start_dedicated_child(tmp_path):
    import asyncio

    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from kuberich.domain.port_forwards import ForwardState, PortMapping
    from kuberich.services.port_forwards import ForwardService
    from tests.support.benchmarks import fixture
    from tests.support.port_forwards import executable

    async with fixture(tmp_path, resource="pods") as (original, manager, forwards, _, store, *_):
        target, client, policy, settings = (
            original.target,
            original.client,
            original.policy,
            original.settings,
        )
        environment = executable(tmp_path)
        source = ForwardService(
            client, target, policy, lambda: True, environment=environment, directory=tmp_path
        )
        identity = forwards.start(source, (PortMapping(0, 8080),))
        async with asyncio.timeout(5):
            while forwards.infos[-1].state is not ForwardState.READY:
                await asyncio.sleep(0.01)
        info = forwards.infos[-1]
        await original.stop_owned()
        owner = manager.create(
            client,
            target,
            policy,
            lambda: True,
            settings=settings,
            environment=environment,
            directory=tmp_path,
            forward=info,
        )
        backend = (await owner.candidates())[0]
        assert backend.service is None and backend.pod_port == 8080
        result = await owner.run(await owner.review(backend, RequestOptions(), LoadOptions()))
        assert result.completion == "complete" and len(forwards.infos) == 2
        assert (
            forwards.infos[0].identity == identity and forwards.infos[0].state is ForwardState.READY
        )
        assert (
            forwards.infos[1].identity != identity
            and forwards.infos[1].state is ForwardState.STOPPED
        )
        assert len(await store.scan()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "selector_mismatch",
        "pending",
        "terminating",
        "not_ready",
        "conditions_invalid",
        "conditions_excessive",
        "too_many_pods",
        "too_many_choices",
    ],
)
async def test_backend_selection_refuses_partial_or_ineligible_candidates(tmp_path, change):
    from copy import deepcopy

    from tests.support.benchmarks import fixture

    async with fixture(tmp_path) as (
        owner,
        _,
        forwards,
        processes,
        _,
        service,
        pod,
        _requests,
        pods,
    ):
        if change == "selector_mismatch":
            pod["metadata"]["labels"] = {"other": "label"}
        elif change == "pending":
            pod["status"]["phase"] = "Pending"
        elif change == "terminating":
            pod["metadata"]["deletionTimestamp"] = "2026-11-10T00:00:00Z"
        elif change == "not_ready":
            pod["status"]["conditions"] = []
        elif change == "conditions_invalid":
            pod["status"]["conditions"] = "invalid"
        elif change == "conditions_excessive":
            pod["status"]["conditions"] = [{}] * 129
        elif change == "too_many_pods":
            pods[:] = [deepcopy(pod)] * 129
        else:
            service["spec"]["ports"] = [
                {"port": number, "targetPort": 8080} for number in range(1, 65)
            ]
            pods[:] = [deepcopy(pod) for _ in range(3)]
        with pytest.raises(AppError):
            await owner.candidates()
        assert (
            processes.active_count == forwards.active_count == 0
            and not (tmp_path / "version.json").exists()
        )


@pytest.mark.asyncio
async def test_read_budget_is_finite_and_does_not_initialize_tools(tmp_path):
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path, resource="pods") as (owner, *_):
        for _ in range(128):
            assert await owner.candidates()
        with pytest.raises(AppError, match="read budget"):
            await owner.candidates()
        assert not (tmp_path / "version.json").exists()


@pytest.mark.asyncio
async def test_ui_listener_failure_does_not_abandon_service_owner(tmp_path):
    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path) as (owner, *_):
        good = []

        def failed():
            raise RuntimeError("synthetic widget fault")

        unsubscribe = owner.subscribe(failed)
        remove = owner.subscribe(lambda: good.append(owner.state))
        backend = (await owner.candidates())[0]
        review = await owner.review(backend, RequestOptions(), LoadOptions())
        assert owner.validate_target()
        result = await owner.run(review)
        assert result.completion == "complete" and good
        unsubscribe()
        remove()


@pytest.mark.asyncio
async def test_missing_tool_and_forward_readiness_failure_keep_incomplete_results(tmp_path):
    from pathlib import Path

    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    for index, options in enumerate(
        [{"executable_path": tmp_path / "absent"}, {"forward_mode": "startup-fail"}]
    ):
        directory = tmp_path / str(index)
        directory.mkdir()
        async with fixture(directory, **options) as (owner, _, forwards, processes, *_):
            result = await owner.run(
                await owner.review((await owner.candidates())[0], RequestOptions(), LoadOptions())
            )
            assert result.completion in {"tool_failed", "target_lost"} and result.metrics is None
            assert forwards.active_count == processes.active_count == 0
            assert not tuple(Path(owner.client.directory.name).glob("benchmark-*"))


@pytest.mark.asyncio
async def test_cancel_before_run_child_enters_has_explicit_cancelled_state_and_no_load(tmp_path):
    import asyncio

    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from kuberich.services.benchmarks import BenchmarkState
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path) as (owner, _, forwards, processes, *_):
        review = await owner.review((await owner.candidates())[0], RequestOptions(), LoadOptions())
        running = asyncio.create_task(owner.run(review))
        await asyncio.sleep(0)
        await owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert owner.state is BenchmarkState.CANCELLED and owner.result is None
        assert not (tmp_path / "version.json").exists()
        assert forwards.active_count == processes.active_count == owner.operation_count == 0


@pytest.mark.asyncio
async def test_policy_refusal_consumes_review_even_if_context_policy_is_later_relaxed(tmp_path):
    from kuberich.domain.benchmarks import LoadOptions, RequestOptions
    from tests.support.benchmarks import fixture

    async with fixture(tmp_path) as (owner, *_):
        backend = (await owner.candidates())[0]
        review = await owner.review(backend, RequestOptions(), LoadOptions())
        owner.policy.restrict(True)
        with pytest.raises(AppError, match="Read-only"):
            await owner.run(review)
        owner.policy.restrict(False)
        with pytest.raises(AppError, match="unused exact"):
            await owner.run(review)
        await owner.review(backend, RequestOptions(), LoadOptions())
        assert not (tmp_path / "version.json").exists()
