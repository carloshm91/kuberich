"""Real helper capture, private staging and cancellation with no ambient cluster."""

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.adapters.kustomize import KustomizeRenderer
from kuberich.adapters.manifest_files import ManifestFiles
from kuberich.domain.manifests import manifest_documents
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.processes import ProcessRunner


def capture(tmp_path):
    import threading

    source = tmp_path / "source"
    source.mkdir()
    (source / "kustomization.yaml").write_text("resources: [resource.yaml]\n")
    (source / "resource.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\ndata: {key: source-private-sentinel}\n"
    )
    files = ManifestFiles(cwd=source)
    root = files.root(source, cancel=threading.Event())
    return files.capture(root, "", "kustomize", cancel=threading.Event())


def helper(tmp_path, body):
    executable = tmp_path / "kubectl"
    executable.write_text(f"#!{sys.executable}\n" + body)
    executable.chmod(0o700)
    return executable


@pytest.mark.asyncio
async def test_explicit_render_uses_exact_private_config_cache_and_frozen_tree(tmp_path):
    snapshots = capture(tmp_path)
    record = tmp_path / "record.json"
    helper(
        tmp_path,
        "import json,os,sys\nfrom pathlib import Path\nroot=Path.cwd()\nconfig=Path(sys.argv[1].split('=',1)[1])\njson.dump({'argv':sys.argv[1:],'cwd':str(root),'config':config.read_text(),'config_mode':config.stat().st_mode&511,'file_mode':(root/'source/resource.yaml').stat().st_mode&511,'kuberc':os.environ.get('KUBECTL_KUBERC'),'kubeconfig':os.environ.get('KUBECONFIG')},open(os.environ['RECORD'],'w'))\nprint((root/'source/resource.yaml').read_text())\n",
    )
    renderer = KustomizeRenderer(
        AccessPolicy(True),
        {"PATH": str(tmp_path), "RECORD": str(record), "KUBECONFIG": "ambient-do-not-read"},
        tmp_path,
    )
    assert not record.exists() and renderer.operation_count == 0
    rendered = await renderer.render(snapshots, "", guard=lambda: None)
    assert manifest_documents(rendered, source_path="rendered")[0].name == "owned"
    observed = json.loads(record.read_text())
    root = Path(observed["cwd"])
    assert (
        observed["kuberc"] == "false" and observed["config_mode"] == observed["file_mode"] == 0o600
    )
    assert observed["kubeconfig"] == observed["argv"][0].split("=", 1)[1]
    assert "contexts: []" in observed["config"] and "ambient-do-not-read" not in observed["config"]
    assert observed["argv"][2:] == [
        "kustomize",
        str(root / "source"),
        "--load-restrictor=LoadRestrictionsRootOnly",
        "--enable-alpha-plugins=false",
        "--enable-helm=false",
        "--network=false",
    ]
    assert not root.exists() and renderer.operation_count == 0
    await renderer.close()
    await renderer.close()
    with pytest.raises(AppError):
        await renderer.render(snapshots, "", guard=lambda: None)


@pytest.mark.asyncio
async def test_plain_local_service_render_parses_output_and_retains_source_closure(tmp_path):
    snapshots = capture(tmp_path)
    helper(
        tmp_path,
        "print('apiVersion: v1\\nkind: ConfigMap\\nmetadata: {name: rendered-final}\\ndata: {key: generated-private-sentinel}')\n",
    )
    local = LocalManifestService(AccessPolicy(True), {"PATH": str(tmp_path)}, tmp_path)
    await local.open_root(Path("source"))
    source = await local.capture("", "kustomize")
    assert source.documents[0].name == "rendered-final" and source.files == snapshots
    await local.require_source(source)
    await local.close()
    assert local.operation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["missing", "nonzero", "malformed", "overflow", "timeout"])
async def test_render_failure_is_safe_bounded_and_always_cleans_staging(
    tmp_path, monkeypatch, scenario
):
    snapshots = capture(tmp_path)
    record = tmp_path / "stage-path"
    bodies = {
        "nonzero": "import sys;print('stderr-private-sentinel',file=sys.stderr);sys.exit(2)",
        "malformed": "print('invalid: [')",
        "overflow": "import os;os.write(1,b'x'*(8*1024*1024+1))",
        "timeout": "import time;time.sleep(60)",
    }
    if scenario != "missing":
        helper(
            tmp_path,
            "from pathlib import Path\nimport os\nPath(os.environ['RECORD']).write_text(str(Path.cwd()))\n"
            + bodies[scenario]
            + "\n",
        )
    renderer = KustomizeRenderer(
        AccessPolicy(False), {"PATH": str(tmp_path), "RECORD": str(record)}, tmp_path
    )
    if scenario == "timeout":
        original = ProcessRunner.capture

        async def capture_short(self, command, *, timeout=30, guard=None):
            assert timeout == 30
            return await original(self, command, timeout=0.03, guard=guard)

        monkeypatch.setattr(ProcessRunner, "capture", capture_short)
    if scenario == "malformed":
        output = await renderer.render(snapshots, "", guard=lambda: None)
        with pytest.raises(AppError):
            manifest_documents(output, source_path="rendered")
    else:
        with pytest.raises(AppError) as error:
            await renderer.render(snapshots, "", guard=lambda: None)
        assert "stderr-private-sentinel" not in str(error.value)
    if record.exists():
        assert not Path(record.read_text()).exists()
    await renderer.close()
    assert renderer.operation_count == 0


@pytest.mark.asyncio
async def test_forged_remote_or_incomplete_frozen_closure_never_launches_helper(tmp_path):
    snapshots = capture(tmp_path)
    record = tmp_path / "launched"
    helper(tmp_path, "from pathlib import Path\nPath(" + repr(str(record)) + ").touch()\n")
    renderer = KustomizeRenderer(AccessPolicy(False), {"PATH": str(tmp_path)}, tmp_path)
    config = snapshots[0]
    import hashlib

    for body in (b"resources: [https://example.invalid/base]", b"resources: [missing.yaml]"):
        forged = replace(config, data=body, sha256=hashlib.sha256(body).hexdigest())
        with pytest.raises(AppError):
            await renderer.render((forged,), "", guard=lambda: None)
    for files, relative in [
        ((config, config), ""),
        (snapshots, "../escape"),
        ((replace(config, relative_path="../escape"),), ""),
        ((replace(config, sha256="wrong"),), ""),
        ((), ""),
    ]:
        with pytest.raises(AppError):
            await renderer.render(files, relative, guard=lambda: None)
    assert not record.exists()
    await renderer.close()


@pytest.mark.asyncio
async def test_cancellation_drains_running_helper_before_private_staging_removal(tmp_path):
    snapshots = capture(tmp_path)
    record = tmp_path / "running.json"
    helper(
        tmp_path,
        "import json,os,time\nfrom pathlib import Path\nPath(os.environ['RECORD']).write_text(json.dumps({'pid':os.getpid(),'root':str(Path.cwd())}))\ntime.sleep(60)\n",
    )
    renderer = KustomizeRenderer(
        AccessPolicy(False), {"PATH": str(tmp_path), "RECORD": str(record)}, tmp_path
    )
    rendering = asyncio.create_task(renderer.render(snapshots, "", guard=lambda: None))
    async with asyncio.timeout(5):
        while not record.exists():
            await asyncio.sleep(0.01)
    observed = json.loads(record.read_text())
    assert Path(observed["root"]).exists()
    rendering.cancel()
    await asyncio.sleep(0)
    rendering.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rendering
    assert not Path(observed["root"]).exists()
    with pytest.raises(ProcessLookupError):
        os.kill(observed["pid"], 0)
    await renderer.close()
    assert renderer.operation_count == 0
