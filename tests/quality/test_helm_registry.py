"""Owned child-process control tests for registry setup; no Docker daemon or image pull."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.errors import AppError
from scripts.helm_registry import (
    REGISTRY_IMAGE,
    REGISTRY_IMAGE_ID,
    OwnedHelmRegistry,
    owned_helm_registry,
)
from tests.support.history import history_http


def fake_docker(tmp_path, port, fault=""):
    state = tmp_path / "docker-state.json"
    state.write_text(json.dumps({"created": False, "calls": [], "port": port, "fault": fault}))
    program = tmp_path / "owned-docker"
    script = """import json, os, sys
from pathlib import Path
state = Path(STATE)
value = json.loads(state.read_text())
args = sys.argv[1:]
assert args[:2] == ['--host', 'unix:///owned/docker.sock']
assert args[2] == '--config'
config = Path(args[3])
assert json.loads((config / 'config.json').read_bytes()) == {'auths': {'kuberich-credential-empty.invalid': {}}}
assert os.environ['DOCKER_CONFIG'] == str(config)
assert os.environ['DOCKER_HOST'] == 'unix:///owned/docker.sock'
assert 'DOCKER_CONTEXT' not in os.environ and 'DOCKER_AUTH_CONFIG' not in os.environ
args = args[4:]
value['calls'].append(args)
if value['fault'] == 'hold-image' and args[:2] == ['image', 'inspect']:
    import time
    value['pid'] = os.getpid()
    state.write_text(json.dumps(value))
    state.with_suffix('.entered').touch()
    while True:
        time.sleep(0.05)
identifier = 'a' * 64
if args[:2] == ['image', 'inspect']:
    print(json.dumps([{'Id': IMAGE_ID if value['fault'] != 'image' else 'sha256:wrong', 'Architecture': 'amd64', 'Os': 'linux'}]))
elif args[0] == 'create':
    value['created'] = True
    value['name'] = args[args.index('--name')+1]
    label = args[args.index('--label')+1]
    value['label'], value['owner'] = label.split('=', 1)
    print('bad-id' if value['fault'] == 'create-response' else identifier)
elif args[:2] == ['container', 'ls']:
    if value['created']:
        print(identifier)
elif args[0] == 'inspect':
    labels = {value['label']: value['owner'] if value['fault'] != 'foreign-label' else 'foreign'}
    print(json.dumps([{'Id': identifier, 'Name': '/'+value['name'], 'Image': IMAGE_ID,
      'Config': {'Image': IMAGE, 'User': '65534:65534', 'Labels': labels},
      'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False, 'Binds': None, 'NetworkMode': 'bridge', 'CapDrop':['ALL'], 'SecurityOpt':['no-new-privileges']},
      'NetworkSettings': {'Ports': {'5000/tcp':[{'HostIp':'127.0.0.1','HostPort':str(value['port'])}]}}}]))
elif args[0] == 'rm':
    assert args == ['rm','--force','--volumes', identifier]
    value['created'] = False
elif args[0] not in {'start','pull'}:
    raise AssertionError('unexpected owned command')
state.write_text(json.dumps(value))
"""
    prefix = f"#!{sys.executable}\nSTATE={str(state)!r}\nIMAGE={REGISTRY_IMAGE!r}\nIMAGE_ID={REGISTRY_IMAGE_ID!r}\n"
    program.write_text(prefix + script)
    program.chmod(0o700)
    return program, state


@pytest.mark.asyncio
async def test_registry_helper_uses_explicit_private_socket_config_identity_and_owned_cleanup(
    tmp_path, monkeypatch
):
    async def handler(request):
        return web.json_response({})

    monkeypatch.setenv("DOCKER_CONTEXT", "must-not-import")
    monkeypatch.setenv("DOCKER_AUTH_CONFIG", '{"auths":{"caller":{"auth":"private"}}}')
    async with history_http(handler) as origin:
        docker, state = fake_docker(tmp_path, int(origin.rsplit(":", 1)[1]))
        async with owned_helm_registry(
            docker, "unix:///owned/docker.sock", tmp_path, pull=True
        ) as registry:
            assert registry.origin == origin
            assert registry.container_id == "a" * 64
            assert not registry.receipt["cleanup_complete"]
        await registry.close()
    observed = json.loads(state.read_text())
    assert not observed["created"]
    assert observed["calls"][0] == ["pull", "--platform", "linux/amd64", REGISTRY_IMAGE]
    assert ["rm", "--force", "--volumes", "a" * 64] in observed["calls"]
    assert registry.receipt["cleanup_complete"]
    assert registry.receipt["private_files_absent"] and registry.receipt["container_absent"]
    assert not tuple(tmp_path.glob("owned-registry-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["image", "create-response"])
async def test_registry_failure_drains_and_removes_only_a_matching_owned_container(tmp_path, fault):
    docker, state = fake_docker(tmp_path, 1, fault)
    registry = OwnedHelmRegistry(docker, "unix:///owned/docker.sock", tmp_path)
    with pytest.raises(AppError):
        await registry.start(pull=False)
    assert not json.loads(state.read_text())["created"]
    assert registry.receipt["cleanup_complete"]
    assert not tuple(tmp_path.glob("owned-registry-*"))


@pytest.mark.asyncio
async def test_changed_label_is_not_ownership_and_never_authorizes_deletion(tmp_path):
    docker, state = fake_docker(tmp_path, 1, "foreign-label")
    registry = OwnedHelmRegistry(docker, "unix:///owned/docker.sock", tmp_path)
    with pytest.raises(AppError):
        await registry.start(pull=False)
    observed = json.loads(state.read_text())
    assert observed["created"] and not any(command[0] == "rm" for command in observed["calls"])
    assert not registry.receipt["cleanup_complete"]
    assert registry.receipt["private_files_absent"]
    assert not tuple(tmp_path.glob("owned-registry-*"))


def test_registry_rejects_remote_socket_or_ambient_paths_before_commands(tmp_path):
    with pytest.raises(ValueError):
        OwnedHelmRegistry(Path("relative"), "unix:///owned/docker.sock", tmp_path)
    with pytest.raises(ValueError):
        OwnedHelmRegistry(tmp_path / "unused", "tcp://foreign.invalid:2375", tmp_path)


@pytest.mark.asyncio
async def test_cancelled_owned_child_is_reaped_before_private_config_removal(tmp_path):
    docker, state = fake_docker(tmp_path, 1, "hold-image")
    registry = OwnedHelmRegistry(docker, "unix:///owned/docker.sock", tmp_path)
    task = asyncio.create_task(registry.start(pull=False))

    async def entered():
        while not state.with_suffix(".entered").exists():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(entered(), 3)
    pid = json.loads(state.read_text())["pid"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert registry.receipt["cleanup_complete"] and registry.receipt["container_not_started"]
    assert not tuple(tmp_path.glob("owned-registry-*"))
