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
