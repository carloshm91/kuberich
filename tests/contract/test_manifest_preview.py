"""Real helper processes prove preview argv, delegation, bounds and owned cleanup."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from kuberich.domain.mutations import MutationState
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from tests.contract.test_manifest_writes import RESOURCE, SESSION, adapter_fixture, create_intent

HELPER = r"""
import json, os, stat, sys
from pathlib import Path
arguments = sys.argv[1:]
config = Path(next(arg.split('=',1)[1] for arg in arguments if arg.startswith('--kubeconfig=')))
filename = Path(next(arg.split('=',1)[1] for arg in arguments if arg.startswith('--filename=')))
cache = Path(next(arg.split('=',1)[1] for arg in arguments if arg.startswith('--cache-dir=')))
Path(os.environ['FIXTURE_CAPTURE']).write_text(json.dumps({
    'argv': arguments, 'kubeconfig': str(config), 'filename': str(filename), 'cache':str(cache),
    'configuration': json.loads(config.read_text()), 'config_mode': stat.S_IMODE(config.stat().st_mode),
    'file_mode':stat.S_IMODE(filename.stat().st_mode), 'KUBECONFIG':os.environ['KUBECONFIG'],
    'KUBECTL_KUBERC':os.environ['KUBECTL_KUBERC']}))
value = json.loads(Path(os.environ['FIXTURE_BASELINE']).read_text())
mode = os.environ.get('FIXTURE_MODE','normal')
if mode == 'stall':
    import time
    time.sleep(30)
if mode == 'overflow':
    sys.stdout.write('x' * (8*1024*1024+1))
    sys.exit(0)
if mode in {'unauthorized','conflict','notfound','unknown'}:
    reason = {'unauthorized':'Unauthorized','conflict':'Conflict','notfound':'NotFound','unknown':'Other'}[mode]
    sys.stderr.write('Error from server ('+reason+'): private-value-in-error')
    sys.exit(1)
if mode == 'denied':
    sys.stderr.write('Error from server (Forbidden): private-value-in-admission-message')
    sys.exit(1)
if mode == 'bad-json':
    print('private-value-not-json')
    sys.exit(0)
if mode == 'wrong-kind':value['kind'] = 'Secret'
if mode == 'wrong-uid':value['metadata']['uid'] = 'replacement-uid'
if mode == 'wrong-version':value['metadata']['resourceVersion'] = 'changed-version'
if mode == 'wrong-namespace':value['metadata']['namespace'] = 'other-team'
if mode == 'missing-namespace':value['metadata'].pop('namespace')
if mode == 'missing-type':value.pop('apiVersion')
print(json.dumps(value))
"""


def helper_environment(tmp_path, value, mode="normal"):
    executable = tmp_path / "kubectl"
    executable.write_text(f"#!{sys.executable}\n" + HELPER)
    executable.chmod(0o700)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(value))
    return {
        "PATH": str(tmp_path),
        "KUBECONFIG": "ambient-must-not-be-used",
        "KUBECTL_KUBERC": "ambient-true",
        "FIXTURE_BASELINE": str(baseline),
        "FIXTURE_CAPTURE": str(tmp_path / "helper-capture.json"),
        "FIXTURE_MODE": mode,
    }


@pytest.mark.asyncio
async def test_actual_helper_receives_explicit_read_only_apply_scope_and_private_connection(
    tmp_path,
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value)
        result = await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        assert result.result.state is MutationState.SUCCEEDED and result.body
        captured = json.loads((tmp_path / "helper-capture.json").read_text())
        arguments = captured["argv"]
        assert "--context=kuberich-test-one" in arguments and "--namespace=team" in arguments
        for flag in (
            "apply",
            "--server-side=false",
            "--dry-run=server",
            "--validate=strict",
            "--field-manager=kuberich-manifests",
            "--output=json",
        ):
            assert flag in arguments
        assert captured["KUBECONFIG"] == captured["kubeconfig"]
        assert captured["KUBECTL_KUBERC"] == "false"
        assert captured["configuration"]["current-context"] == SESSION.context
        assert captured["config_mode"] == captured["file_mode"] == 0o600
        assert not Path(captured["kubeconfig"]).exists()
        assert not Path(captured["filename"]).exists()
        assert not Path(captured["cache"]).exists()
        assert len(api.requests) == 1 and "private-value" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "wrong-kind",
        "wrong-uid",
        "wrong-version",
        "wrong-namespace",
        "missing-namespace",
        "missing-type",
        "bad-json",
    ],
)
async def test_helper_output_identity_or_json_refusal_is_safe_and_does_not_write(tmp_path, mode):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value, mode)
        with pytest.raises(AppError) as failure:
            await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        assert "private-value" not in str(failure.value)
        captured = json.loads((tmp_path / "helper-capture.json").read_text())
        assert not Path(captured["filename"]).exists() and not Path(captured["kubeconfig"]).exists()
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_helper_admission_refusal_withholds_stderr_and_no_client_fallback(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value, "denied")
        result = await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        assert result.result.state is MutationState.DENIED and result.body is None
        assert "private-value" not in repr(result)
        assert len(api.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,state",
    [
        ("unauthorized", MutationState.AUTH_ERROR),
        ("conflict", MutationState.CONFLICT),
        ("notfound", MutationState.NOT_FOUND),
        ("unknown", MutationState.REJECTED),
        ("overflow", MutationState.REJECTED),
    ],
)
async def test_helper_machine_failure_categories_and_output_bound_never_leak_stderr(
    tmp_path, mode, state
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value, mode)
        result = await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        assert result.result.state is state and result.body is None
        assert "private-value" not in repr(result) and len(api.requests) == 1


@pytest.mark.asyncio
async def test_missing_kubectl_refuses_strict_preview_without_client_fallback(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = {"PATH": str(tmp_path / "no-tools")}
        result = await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        assert result.result.state is MutationState.REJECTED and "kubectl" in result.result.message
        assert len(api.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("close", [False, True])
async def test_helper_cancel_or_owner_close_drains_process_before_private_files_are_removed(
    tmp_path, close
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value, "stall")
        task = asyncio.create_task(
            adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        )
        async with asyncio.timeout(2):
            while not (tmp_path / "helper-capture.json").exists():
                await asyncio.sleep(0.01)
        captured = json.loads((tmp_path / "helper-capture.json").read_text())
        if close:
            await adapter.close()
        else:
            task.cancel()
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not Path(captured["filename"]).exists() and not Path(captured["kubeconfig"]).exists()
        assert adapter.runner.active_count == 0
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_helper_timeout_is_nonpersisting_and_owned_files_are_removed(tmp_path):
    async with adapter_fixture(tmp_path, timeout=0.3) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value, "stall")
        result = await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        assert result.result.state is MutationState.TIMEOUT
        captured = json.loads((tmp_path / "helper-capture.json").read_text())
        assert not Path(captured["filename"]).exists() and not Path(captured["kubeconfig"]).exists()
        assert adapter.runner.active_count == 0 and len(api.requests) == 1


@pytest.mark.asyncio
async def test_cluster_scoped_preview_omits_namespace_flag_and_keeps_exact_group_resource_path(
    tmp_path,
):
    from kuberich.domain.manifests import (
        create_manifest_intent,
        manifest_documents,
        resolve_manifest,
    )
    from kuberich.domain.resources import ApiResource, Discovery

    resource = ApiResource(
        "rbac.authorization.k8s.io",
        "v1",
        "clusterroles",
        "ClusterRole",
        False,
        frozenset({"get", "create", "patch", "delete", "watch"}),
    )
    document = manifest_documents(
        b'{"apiVersion":"rbac.authorization.k8s.io/v1","kind":"ClusterRole","metadata":{"name":"owned-one"},"rules":[]}',
        source_path="clusterrole.yaml",
    )[0]
    from kuberich.domain.manifests import ManifestScope

    _, address, body = resolve_manifest(
        document, Discovery((resource,)), ManifestScope(session=SESSION, namespace=None)
    )
    intent = create_manifest_intent(resource, address, body)
    async with adapter_fixture(tmp_path) as (adapter, api):
        assert (await adapter.execute(intent, lambda: None)).state is MutationState.SUCCEEDED
        assert api.requests[0][1] == "/apis/rbac.authorization.k8s.io/v1/clusterroles"
        baseline = await adapter.read(resource, address, lambda: None)
        target = ResourceTarget(
            SESSION, resource.group, resource.name, None, address.name, baseline.uid
        )
        adapter.environment = helper_environment(tmp_path, api.value)
        result = await adapter.preview_update(resource, target, body, baseline, lambda: None)
        assert result.result.state is MutationState.SUCCEEDED
        captured = json.loads((tmp_path / "helper-capture.json").read_text())
        assert not any(argument.startswith("--namespace=") for argument in captured["argv"])
        assert "namespace" not in json.loads(result.body)["metadata"]
