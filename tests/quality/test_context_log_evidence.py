"""Ready pods still need observable startup logs within the existing time budget."""

import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from kuberich.domain.targets import SessionIdentity
from kuberich.services.logs import LogStream
from scripts.verify_contexts_kind import verify_logs
from tests.support.pods import pod
from tests.support.resources import reader_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("banner", [True, False, "delayed"])
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
        if "tailLines" not in request.query and (
            banner is True or (banner == "delayed" and len(queries) >= 4)
        ):
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
            evidence = tmp_path / "failure-evidence"
            with pytest.raises(TimeoutError):
                await verify_logs(
                    reader, snapshot, sessions, readiness_timeout=0.35, evidence_dir=evidence
                )
            assert len(queries) >= 2 and all(query["previous"] == "false" for query in queries)
            receipt = json.loads(next(evidence.glob("kind-log-failure-*.json")).read_text())
            assert receipt["result"] == "failed" and receipt["pod_ready"]
            assert receipt["error_type"] == "TimeoutError" and not receipt["startup_observed"]
            assert receipt["tail_count"] == receipt["all_count"] == 10
        else:
            result = await verify_logs(reader, snapshot, sessions)
            assert result["real_current_container_log_snapshot"]
            assert result["real_follow_log_cancellation_awaited"]
            assert result["real_previous_log_unavailable"]
            assert queries[0]["tailLines"] == "10" and "tailLines" not in queries[1]
            assert queries[-1]["previous"] == "true"
            assert result["real_log_readiness_attempts"] == (2 if banner == "delayed" else 1)
        assert not reader.session.api.rest_client.pool_manager.connector._acquired


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_evidence", [False, True])
async def test_failed_log_qualification_retains_the_original_error_without_payloads(
    tmp_path, monkeypatch, blocked_evidence
):
    value = pod("coredns-owned", uid="owned")
    value["spec"]["containers"][0]["name"] = "coredns"
    value["status"]["phase"] = "Running"
    value["status"]["containerStatuses"] = [{"name": "coredns", "ready": True}]
    snapshot = SimpleNamespace(
        items=[SimpleNamespace(manifest=value, name="coredns-owned", uid="owned")]
    )
    failure = RuntimeError("opaque-sensitive-log-value")

    async def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(LogStream, "run", broken)
    monkeypatch.setenv("GITHUB_SHA", "untrusted-not-a-commit")
    monkeypatch.setenv("GITHUB_RUN_ID", "untrusted-not-a-run")
    evidence = tmp_path / "failure-evidence"
    if blocked_evidence:
        evidence.symlink_to(tmp_path, target_is_directory=True)

    async def handler(request):
        return web.json_response(value)

    async with reader_fixture(tmp_path, handler) as reader:
        sessions = SimpleNamespace(
            client=reader.session,
            observation=SimpleNamespace(identity=SessionIdentity(reader.session.context.name, 1)),
        )
        with pytest.raises(RuntimeError) as caught:
            await verify_logs(reader, snapshot, sessions, evidence_dir=evidence)
        assert caught.value is failure
    if blocked_evidence:
        assert any("could not be written" in note for note in failure.__notes__)
        assert not list(tmp_path.glob("kind-log-failure-*.json"))
    else:
        text = next(evidence.glob("kind-log-failure-*.json")).read_text()
        assert "opaque-sensitive-log-value" not in text
        receipt = json.loads(text)
        assert receipt["error_type"] == "RuntimeError" and receipt["attempts"] == 1
        assert receipt["workflow_event_sha"] is None and receipt["github_run_id"] is None
        assert len(receipt["verifier_sha256"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, 91])
async def test_log_qualification_cannot_increase_the_readiness_budget(timeout):
    with pytest.raises(ValueError, match="at most 90"):
        await verify_logs(None, None, None, readiness_timeout=timeout)
