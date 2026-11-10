"""Owned HTTP append receipts, conditional wire contract and non-replayed faults."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from kuberich.adapters.ephemeral_debug import append_container
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.ephemeral_debug import prepare_intent
from kuberich.domain.mutations import MutationState
from kuberich.errors import AppError
from tests.support.connections import catalog_fixture
from tests.unit.test_ephemeral_debug import options, pod, target


class EphemeralApi:
    def __init__(self):
        self.value = pod()
        self.requests = []
        self.status = None
        self.mode = "normal"
        self.race = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, request):
        assert request.method == "PATCH"
        assert request.path == "/api/v1/namespaces/team/pods/owned/ephemeralcontainers"
        body = await request.json()
        self.requests.append(
            (request.path, dict(request.query), dict(request.headers), copy.deepcopy(body))
        )
        self.entered.set()
        if self.status is not None:
            return web.Response(status=self.status, text="private-error-body\x1b[31m")
        if self.race:
            self.value["metadata"][self.race] = "raced"
        if body[:2] != [
            {"op": "test", "path": "/metadata/uid", "value": self.value["metadata"]["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": self.value["metadata"]["resourceVersion"],
            },
        ]:
            return web.Response(status=422, text="private-precondition")
        value = copy.deepcopy(self.value)
        operation = body[2]
        if operation["path"].endswith("/-"):
            value["spec"]["ephemeralContainers"].append(operation["value"])
        else:
            value["spec"]["ephemeralContainers"] = operation["value"]
        value["metadata"]["resourceVersion"] = "opaque/after"
        value["spec"]["ephemeralContainers"][-1]["resources"] = {}
        value["spec"]["ephemeralContainers"][-1].pop("stdinOnce")
        if "dryRun" not in request.query:
            self.value = copy.deepcopy(value)
        if self.mode == "drop":
            request.transport.abort()
            return web.Response()
        if self.mode == "stall":
            await self.release.wait()
        if self.mode == "bad-json":
            return web.Response(text="private-invalid-json")
        if self.mode == "oversized":
            return web.Response(body=b"x" * (8 * 1024 * 1024 + 1))
        if self.mode == "truncated":
            response = web.StreamResponse(headers={"Content-Length": "10000"})
            await response.prepare(request)
            await response.write(b'{"apiVersion": "v1"')
            request.transport.abort()
            return response
        if self.mode == "wrong-uid":
            value["metadata"]["uid"] = "foreign"
        if self.mode == "wrong-name":
            value["metadata"]["name"] = "foreign"
        if self.mode == "no-version":
            value["metadata"].pop("resourceVersion")
        if self.mode == "profile":
            value["spec"]["ephemeralContainers"][-1]["securityContext"]["privileged"] = True
        if self.mode == "workload":
            value["spec"]["containers"][0]["image"] = "injected"
        if self.mode == "no-addition":
            value["spec"]["ephemeralContainers"] = []
        return web.json_response(value)


@asynccontextmanager
async def source_fixture(tmp_path, *, timeout=2):
    fixture = EphemeralApi()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", fixture.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    fixture.stop_listener = site.stop
    port = runner.addresses[0][1]
    (tmp_path / "owned-loopback-port").write_text(str(port))
    client = KubernetesSession(
        catalog_fixture(tmp_path, f"http://127.0.0.1:{port}").select("kuberich-test-one"), timeout
    )
    await client.open()
    try:
        yield fixture, client
    finally:
        fixture.release.set()
        await client.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_exact_conditional_wire_dryrun_apply_and_defaulted_receipt(tmp_path):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options(target_container="work"))
        dry = await append_container(client, intent, lambda: None, dry_run=True)
        assert dry.result.state is MutationState.SUCCEEDED and dry.append is None and dry.profile
        assert "ephemeralContainers" not in api.value["spec"]
        applied = await append_container(client, intent, lambda: None, expected_profile=dry.profile)
        assert (
            applied.result.state is MutationState.SUCCEEDED
            and applied.append
            and applied.profile == dry.profile
        )
        assert len(api.requests) == 2 and len(api.value["spec"]["ephemeralContainers"]) == 1
        path, query, headers, body = api.requests[0]
        assert path == intent.path and query == {"fieldValidation": "Strict", "dryRun": "All"}
        assert api.requests[1][1] == {"fieldValidation": "Strict"}
        assert headers["Content-Type"] == "application/json-patch+json"
        assert headers["Authorization"] == "Bearer synthetic"
        assert headers["Accept-Encoding"] == "identity"
        assert body == json.loads(intent.body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [
        (401, MutationState.AUTH_ERROR),
        (403, MutationState.DENIED),
        (404, MutationState.NOT_FOUND),
        (405, MutationState.REJECTED),
        (409, MutationState.CONFLICT),
        (415, MutationState.REJECTED),
        (422, MutationState.REJECTED),
        (429, MutationState.UNCERTAIN),
        (500, MutationState.UNCERTAIN),
        (302, MutationState.UNCERTAIN),
    ],
)
async def test_status_refusal_never_replays_or_exposes_raw_status(tmp_path, status, state):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.status = status
        receipt = await append_container(client, intent, lambda: None)
        assert receipt.result.state is state and receipt.append is None and receipt.profile is None
        assert len(api.requests) == 1 and "ephemeralContainers" not in api.value["spec"]
        assert "private-" not in receipt.result.message and "\x1b" not in receipt.result.message


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["uid", "resourceVersion"])
async def test_server_race_fails_atomic_conditions_without_adding(tmp_path, field):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.race = field
        receipt = await append_container(client, intent, lambda: None)
        assert receipt.result.state is MutationState.REJECTED
        assert len(api.requests) == 1 and "ephemeralContainers" not in api.value["spec"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "drop",
        "truncated",
        "bad-json",
        "oversized",
        "wrong-uid",
        "wrong-name",
        "no-version",
        "no-addition",
    ],
)
async def test_applied_but_unverified_receipt_is_uncertain_without_adoption_or_replay(
    tmp_path, mode
):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.mode = mode
        receipt = await append_container(client, intent, lambda: None)
        assert receipt.result.state is MutationState.UNCERTAIN
        assert receipt.append is None and receipt.profile is None and len(api.requests) == 1
        assert api.value["spec"]["ephemeralContainers"][0]["name"] == "debug-one"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["profile", "workload"])
async def test_confirmed_permanent_append_survives_profile_mismatch_but_cannot_attach(
    tmp_path, mode
):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.mode = mode
        receipt = await append_container(client, intent, lambda: None)
        assert (
            receipt.result.state is MutationState.SUCCEEDED
            and receipt.append
            and receipt.profile is None
        )
        assert "permanent" in receipt.result.message and "blocked" in receipt.result.message
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_exact_reviewed_profile_required_and_dryrun_drift_cannot_approve(tmp_path):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.mode = "profile"
        receipt = await append_container(client, intent, lambda: None, dry_run=True)
        assert (
            receipt.result.state is MutationState.REJECTED
            and receipt.append is None
            and receipt.profile is None
        )
        assert "ephemeralContainers" not in api.value["spec"]
        api.mode = "normal"
        receipt = await append_container(
            client, intent, lambda: None, expected_profile=b"unreviewed"
        )
        assert (
            receipt.result.state is MutationState.SUCCEEDED
            and receipt.append
            and receipt.profile is None
        )


@pytest.mark.asyncio
async def test_policy_and_closed_connection_refuse_before_request(tmp_path):
    def blocked():
        raise AppError("Read-only mode")

    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        receipt = await append_container(client, intent, blocked)
        assert receipt.result.state is MutationState.REJECTED and not api.requests
        await client.close()
        receipt = await append_container(client, intent, lambda: None)
        assert receipt.result.state is MutationState.STALE and not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_sent_cancellation_retains_uncertainty_and_dryrun_is_no_write(tmp_path, dry_run):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.mode = "stall"
        worker = asyncio.create_task(
            append_container(client, intent, lambda: None, dry_run=dry_run)
        )
        await api.entered.wait()
        worker.cancel()
        receipt = await worker
        assert receipt.result.state is (
            MutationState.CANCELLED if dry_run else MutationState.UNCERTAIN
        )
        assert len(api.requests) == 1
        assert ("ephemeralContainers" in api.value["spec"]) is not dry_run


@pytest.mark.asyncio
async def test_request_honors_captured_timeout_and_does_not_retry(tmp_path):
    async with source_fixture(tmp_path, timeout=0.05) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        api.mode = "stall"
        receipt = await append_container(client, intent, lambda: None)
        assert receipt.result.state is MutationState.UNCERTAIN and len(api.requests) == 1


@pytest.mark.asyncio
async def test_connector_failure_is_distinct_from_sent_unknown(tmp_path):
    async with source_fixture(tmp_path) as (api, client):
        intent = prepare_intent(target(), api.value, options())
        # The fixture owns this listening socket; a closed socket proves pre-send failure.
        await api.stop_listener()
        receipt = await append_container(client, intent, lambda: None)
        assert receipt.result.state is MutationState.UNREACHABLE and not api.requests
