"""Optional tools cross the real App/config/process boundary only on explicit commands."""

import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.domain.cluster_diagnostics import DiagnosticSourceKind, DiagnosticStatus
from tests.support.authorization_ui import authorization_api
from tests.support.diagnostic_api import DiagnosticAPI
from tests.support.workspace import wait_for
from tests.ui.test_cluster_diagnostics_app import diagnostics_ready, pods_ready, select
from tests.ui.test_live_preferences import owned_app


class ActionAPI(DiagnosticAPI):
    action_status = 0

    async def handler(self, request):
        if request.path == "/api/v1/namespaces/team/pods/example" and self.action_status:
            return web.Response(status=self.action_status)
        return await super().handler(request)


def tool(tmp_path):
    receipt = tmp_path / "tool-calls.jsonl"
    executable = tmp_path / "owned-popeye"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,sys\nfrom pathlib import Path\n"
        f"with Path({str(receipt)!r}).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1:] == ['version']:\n print('Version: v0.22.1'); raise SystemExit(0)\n"
        "report={'ClusterName':'kuberich-session','ContextName':'kuberich-test-one',"
        "'popeye':{'report_time':'2026-11-05T10:00:00Z','score':75,'grade':'B',"
        "'sections':[{'linter':'pods','gvr':'v1/pods','tally':"
        "{'ok':0,'info':0,'warning':1,'error':0,'score':75},"
        "'issues':{'team/example':[{'group':'app','gvr':'containers','level':2,"
        "'message':'[POP-123] Synthetic container warning'}]}}]}}\n"
        "print(json.dumps(report)); raise SystemExit(1)\n"
    )
    executable.chmod(0o700)
    return executable, receipt


@pytest.mark.asyncio
async def test_missing_optional_tool_opens_informational_native_route_without_installing(tmp_path):
    async with authorization_api(DiagnosticAPI()) as url:
        app, _, _ = owned_app(tmp_path, {}, url=url)
        async with app.run_test():
            await pods_ready(app)
            await app.run_command("popeye")
            await diagnostics_ready(app)
            sources = app.workspace.store.observation.diagnostics.sources
            assert any(
                source.kind is DiagnosticSourceKind.POPEYE
                and source.status is DiagnosticStatus.UNAVAILABLE
                and "optional" in source.detail
                for source in sources
            )
            assert len(app.screen_stack) == 1 and app.state.view_kind == "diagnostics"


@pytest.mark.asyncio
async def test_context_tool_runs_explicitly_keeps_native_times_and_exit_one_findings(tmp_path):
    executable, receipt = tool(tmp_path)
    config = {
        "read_only": True,
        "observability": {
            "popeye": {"executable": "/never-execute-global-default/popeye"},
            "contexts": {
                "kuberich-test-one": {
                    "popeye": {"executable": str(executable), "trusted_read_only": True}
                }
            },
        },
    }
    async with authorization_api(DiagnosticAPI()) as url:
        app, _, _ = owned_app(tmp_path, config, url=url)
        async with app.run_test():
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            native = app.workspace.store.observation.diagnostics
            assert native.findings and not receipt.exists()
            await app.run_command("popeye")
            await diagnostics_ready(app)
            combined = app.workspace.store.observation.diagnostics
            assert all(finding in combined.findings for finding in native.findings)
            assert all(source in combined.sources for source in native.sources)
            findings = tuple(
                item for item in combined.findings if item.source is DiagnosticSourceKind.POPEYE
            )
            assert len(findings) == 1 and findings[0].container == "app"
            assert findings[0].tool_version == "0.22.1" and findings[0].source_code == "POP-123"
            calls = [json.loads(line) for line in receipt.read_text().splitlines()]
            assert len(calls) == 2 and calls[0] == ["version"]
            assert "--context=kuberich-test-one" in calls[1]
            assert "--namespace=team" in calls[1] and "--out=json" in calls[1]
            assert not list(Path(app.sessions.client.directory.name).glob("plugin-*.json"))
            await app.run_command("refresh")
            await diagnostics_ready(app)
            refreshed = app.workspace.store.observation.diagnostics
            assert not any(
                item.source is DiagnosticSourceKind.POPEYE for item in refreshed.findings
            )
            assert not any(item.kind is DiagnosticSourceKind.POPEYE for item in refreshed.sources)
            assert len(receipt.read_text().splitlines()) == 2
            await app.run_command("pods")
            await pods_ready(app)
            await app.run_command("back")
            await diagnostics_ready(app)
            assert not any(
                item.kind is DiagnosticSourceKind.POPEYE
                for item in app.workspace.store.observation.diagnostics.sources
            )
            assert len(receipt.read_text().splitlines()) == 2


@pytest.mark.asyncio
async def test_read_only_untrusted_tool_is_refused_before_version_probe(tmp_path):
    executable, receipt = tool(tmp_path)
    async with authorization_api(DiagnosticAPI()) as url:
        app, _, _ = owned_app(
            tmp_path,
            {"read_only": True, "observability": {"popeye": {"executable": str(executable)}}},
            url=url,
        )
        async with app.run_test():
            await pods_ready(app)
            await app.run_command("popeye")
            await diagnostics_ready(app)
            await wait_for(lambda: not app.workspace.diagnostic_collecting)
            assert any(
                item.kind is DiagnosticSourceKind.POPEYE
                and item.status is DiagnosticStatus.FORBIDDEN
                for item in app.workspace.store.observation.diagnostics.sources
            )
            assert not receipt.exists()


@pytest.mark.asyncio
async def test_root_open_key_reports_replaced_identity_then_opens_exact_current_uid(tmp_path):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app, _, _ = owned_app(tmp_path, {}, url=url)
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            finding = select(app).finding
            subject = finding.subject
            record = api.objects[("", "pods", subject.namespace, subject.name)]
            record["metadata"]["uid"] = "replacement"
            await pilot.press("o")
            await wait_for(lambda: "replaced" in str(app.status.content))
            assert app.state.view_kind == "diagnostics" and not api.log_reads
            record["metadata"]["uid"] = subject.uid
            await pilot.press("o")
            await wait_for(
                lambda: app.state.view_kind == "pods" and app.views.expected_uid == subject.uid
            )
            assert app.state.namespace == subject.namespace
            assert len(app.screen_stack) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_root_open_expected_http_failure_stays_in_live_diagnostic_workspace(tmp_path, status):
    api = ActionAPI()
    async with authorization_api(api) as url:
        app, _, _ = owned_app(tmp_path, {}, url=url)
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            select(app)
            request = app.workspace.diagnostic_request
            api.action_status = status
            await pilot.press("o")
            await wait_for(lambda: f"HTTP {status}" in str(app.status.content))
            assert app.is_running and app.state.view_kind == "diagnostics"
            assert app.workspace.diagnostic_request == request and not api.log_reads
            api.action_status = 0
            await pilot.press("o")
            await wait_for(lambda: app.state.view_kind == "pods")


@pytest.mark.asyncio
async def test_context_change_drains_held_root_object_worker_before_client_private_files(tmp_path):
    api = DiagnosticAPI()
    async with authorization_api(api) as url:
        app, _, _ = owned_app(tmp_path, {}, url=url)
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            select(app)
            old_client = app.sessions.client
            old_directory = Path(old_client.directory.name)
            original_close = app.sessions.before_close
            before_private_close = []

            async def observe_close(client):
                await original_close(client)
                if client is old_client:
                    before_private_close.append(
                        (
                            not any(worker.group == "diagnostic-object" for worker in app.workers),
                            old_directory.exists(),
                        )
                    )

            app.sessions.before_close = observe_close
            api.hold_path = "/api/v1/namespaces/team/pods/example"
            try:
                await pilot.press("o")
                await wait_for(api.started.is_set)
                assert any(worker.group == "diagnostic-object" for worker in app.workers)
                await app.run_command("ctx kuberich-test-Two")
                await wait_for(
                    lambda: (
                        app.state.context == "kuberich-test-Two"
                        and app.sessions.client is not old_client
                    )
                )
                try:
                    await diagnostics_ready(app)
                except TimeoutError:
                    observation = app.workspace.store.observation
                    print(
                        {
                            "state": app.state,
                            "request": app.workspace.diagnostic_request,
                            "snapshot_request": observation.diagnostics.request
                            if observation.diagnostics
                            else None,
                            "collecting": app.workspace.diagnostic_collecting,
                            "table_request": app.diagnostics_table.request,
                            "published": app.diagnostics_table.snapshot == observation.diagnostics,
                            "ownership": app.workspace.ownership,
                            "screen": type(app.screen).__name__,
                            "before_private_close": before_private_close,
                        }
                    )
                    raise
                assert before_private_close == [(True, True)]
                assert not old_directory.exists()
                assert not any(worker.group == "diagnostic-object" for worker in app.workers)
                assert app.is_running and not api.log_reads
            finally:
                api.release.set()
