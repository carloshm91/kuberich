"""The real-HTTP qualification accepts tail truncation but still requires the banner."""

from types import SimpleNamespace

import pytest
from aiohttp import web

from kuberich.domain.targets import SessionIdentity
from scripts.verify_contexts_kind import verify_logs
from tests.support.pods import pod
from tests.support.resources import reader_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("banner", [True, False])
async def test_core_log_qualification_checks_startup_in_all_logs_not_the_recent_tail(
    tmp_path, banner
):
    value = pod("coredns-owned", uid="owned")
    value["metadata"]["namespace"] = "kube-system"
    value["spec"]["containers"][0]["name"] = "coredns"
    value["status"]["phase"] = "Running"
    value["status"]["containerStatuses"] = [{"name": "coredns", "ready": True}]
    queries = []
    recent = "".join(f"2026-10-11T00:00:00Z recent line {index}\n" for index in range(10))

    async def handler(request):
        if not request.path.endswith("/log"):
            return web.json_response(value)
        queries.append(dict(request.query))
        if request.query.get("previous") == "true":
            return web.Response(status=400)
        text = recent
        if "tailLines" not in request.query and banner:
            text = "2026-10-11T00:00:00Z CoreDNS-owned-startup\n" + text
        return web.Response(text=text)

    snapshot = SimpleNamespace(
        items=[SimpleNamespace(manifest=value, name="coredns-owned", uid="owned")]
    )
    async with reader_fixture(tmp_path, handler) as reader:
        sessions = SimpleNamespace(
            client=reader.session,
            observation=SimpleNamespace(identity=SessionIdentity(reader.session.context.name, 1)),
        )
        if not banner:
            with pytest.raises(AssertionError):
                await verify_logs(reader, snapshot, sessions)
            assert len(queries) == 2
        else:
            result = await verify_logs(reader, snapshot, sessions)
            assert result["real_current_container_log_snapshot"]
            assert result["real_follow_log_cancellation_awaited"]
            assert result["real_previous_log_unavailable"]
            assert queries[0]["tailLines"] == "10" and "tailLines" not in queries[1]
            assert queries[-1]["previous"] == "true"
        assert not reader.session.api.rest_client.pool_manager.connector._acquired
