"""Disposable identity refusals and actual owned-process cleanup contracts."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.owned_kind import (
    NODE_IMAGE,
    docker_environment,
    local_endpoint,
    owned_cluster,
    run_owned,
    verify_config,
)


def node(name="kuberich-test-owned"):
    return {
        "Id": "owned-node-id",
        "Config": {
            "Image": NODE_IMAGE,
            "Labels": {"io.x-k8s.kind.cluster": name, "io.x-k8s.kind.role": "control-plane"},
        },
        "NetworkSettings": {"Ports": {"6443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "43431"}]}},
    }


def config(name="kuberich-test-owned"):
    identity = "kind-" + name
    return {
        "current-context": identity,
        "contexts": [{"name": identity, "context": {"cluster": identity, "user": identity}}],
        "clusters": [
            {
                "name": identity,
                "cluster": {
                    "server": "https://127.0.0.1:43431",
                    "certificate-authority-data": "owned-fixture",
                },
            }
        ],
        "users": [
            {
                "name": identity,
                "user": {
                    "client-certificate-data": "owned-fixture",
                    "client-key-data": "owned-fixture",
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "ssh://remote",
        "tcp://127.0.0.1:2375",
        "unix://remote/tmp/docker.sock",
        "unix:relative",
        "unix:///tmp/socket?redirect=1",
        "unix:///tmp/socket#other",
        "unix:///tmp/\0socket",
    ],
)
def test_refuse_remote_or_ambiguous_docker_endpoints(endpoint):
    with pytest.raises(ValueError):
        local_endpoint(endpoint)


def test_explicit_local_docker_environment_removes_retargeting_overrides():
    captured = docker_environment(
        {
            "DOCKER_CONTEXT": "remote",
            "DOCKER_HOST": "ssh://remote",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": "/private",
            "PATH": "/owned/bin",
        },
        "unix:///tmp/owned.sock",
    )
    assert captured == {
        "DOCKER_HOST": "unix:///tmp/owned.sock",
        "PATH": "/owned/bin",
        "KIND_EXPERIMENTAL_PROVIDER": "docker",
    }


@pytest.mark.parametrize(
    "fault",
    ["name", "image", "role", "port", "remote", "tls", "helper", "reference", "extra", "empty"],
)
def test_prewrite_config_requires_actual_owned_node_identity(tmp_path, fault):
    data, nodes = config(), [node()]
    if fault in {"name", "image", "role"}:
        key = {"name": "io.x-k8s.kind.cluster", "role": "io.x-k8s.kind.role"}.get(fault)
        if key:
            nodes[0]["Config"]["Labels"][key] = "other"
        else:
            nodes[0]["Config"]["Image"] = "unverified:latest"
    elif fault == "port":
        nodes[0]["NetworkSettings"]["Ports"]["6443/tcp"][0]["HostPort"] = "9999"
    elif fault == "remote":
        data["clusters"][0]["cluster"]["server"] = "https://remote:43431"
    elif fault == "tls":
        data["clusters"][0]["cluster"]["insecure-skip-tls-verify"] = True
    elif fault == "helper":
        data["users"][0]["user"]["exec"] = {"command": "never-execute"}
    elif fault == "reference":
        data["contexts"][0]["context"]["cluster"] = "foreign"
    elif fault == "extra":
        nodes.append(node())
    else:
        nodes.clear()
    path = tmp_path / "generated"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        verify_config(path, "kuberich-test-owned", nodes)


@pytest.fixture
def fake_kind(tmp_path, monkeypatch):
    """Owned executable fixtures; no Docker socket or Kubernetes API is contacted."""
    state = tmp_path / "state.json"
    state.write_text("[]")
    calls = tmp_path / "calls.jsonl"
    program = """import json,os,sys
from pathlib import Path
import yaml
from tests.quality.test_owned_kind import config,node
state=Path(os.environ['OWNED_STATE']);args=sys.argv[1:]
with open(os.environ['OWNED_CALLS'],'a') as f: f.write(json.dumps([Path(sys.argv[0]).name,args,os.environ.get('KUBECONFIG')])+'\\n')
if Path(sys.argv[0]).name=='docker':
 if args[0]=='context': print(json.dumps('unix:///tmp/owned-fixture.sock'))
 elif args[0]=='ps':
  for n in json.loads(state.read_text()): print(n['Id'])
 elif args[0]=='inspect': print(state.read_text())
else:
 if args[0]=='version': print('kind v0.33.0 fixture')
 elif args[0]=='create':
  name=args[args.index('--name')+1];path=Path(args[args.index('--kubeconfig')+1])
  state.write_text(json.dumps([node(name)]));data=config(name)
  if os.environ.get('OWNED_FAULT')=='config': data['clusters'][0]['cluster']['server']='https://foreign:443'
  path.write_text(yaml.safe_dump(data))
  if os.environ.get('OWNED_FAULT')=='create': sys.exit(1)
 elif args[0]=='delete':
  if os.environ.get('OWNED_SECOND_CANCEL'): os.kill(os.getppid(),15)
  state.write_text('[]')
"""
    for name in ("kind", "docker"):
        path = tmp_path / name
        path.write_text("#!" + sys.executable + "\n" + program)
        path.chmod(0o700)
    monkeypatch.setenv("OWNED_STATE", str(state))
    monkeypatch.setenv("OWNED_CALLS", str(calls))
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd()))
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    return tmp_path / "kind", tmp_path / "docker", state, calls


@pytest.mark.parametrize("fault", [None, "body", "config", "create", "cancel", "second-cancel"])
def test_owned_lifecycle_cleans_success_failure_and_cancellation(fake_kind, monkeypatch, fault):
    kind, docker, state, calls = fake_kind
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    if fault in {"config", "create"}:
        monkeypatch.setenv("OWNED_FAULT", fault)
    if fault == "second-cancel":
        monkeypatch.setenv("OWNED_SECOND_CANCEL", "1")
    error = {
        "body": RuntimeError,
        "config": ValueError,
        "create": subprocess.CalledProcessError,
        "cancel": SystemExit,
        "second-cancel": SystemExit,
    }.get(fault)

    def trial():
        with owned_cluster(str(kind), docker=str(docker)) as cluster:
            assert cluster.path.stat().st_mode & 0o777 == 0o600
            assert cluster.context == "kind-" + cluster.name
            assert cluster.node_ids == ("owned-node-id",)
            if fault == "body":
                raise RuntimeError("owned body failure")
            if fault in {"cancel", "second-cancel"}:
                os.kill(os.getpid(), signal.SIGTERM)
        assert not cluster.directory.exists()

    if error:
        with pytest.raises(error):
            trial()
    else:
        trial()
    assert json.loads(state.read_text()) == []
    records = [json.loads(line) for line in calls.read_text().splitlines()]
    creation = next(r for r in records if r[0] == "kind" and r[1][0] == "create")
    deletion = next(r for r in records if r[0] == "kind" and r[1][0] == "delete")
    assert creation[2] == deletion[2] and creation[2] != os.environ["KUBECONFIG"]
    assert deletion[1][-2:] == ["--kubeconfig", deletion[2]]
    assert {s: signal.getsignal(s) for s in before} == before


def test_existing_cluster_is_never_adopted_or_deleted(fake_kind):
    kind, docker, state, calls = fake_kind
    state.write_text(json.dumps([node("foreign")]))
    with pytest.raises(ValueError, match="existing"), owned_cluster(str(kind), docker=str(docker)):
        pytest.fail("must not yield")
    assert json.loads(state.read_text()) == [node("foreign")]
    assert all(
        json.loads(line)[1][0] not in {"create", "delete"}
        for line in calls.read_text().splitlines()
    )


def test_replaced_node_is_never_deleted(fake_kind):
    kind, docker, state, calls = fake_kind
    with (
        pytest.raises(ValueError, match="identity changed"),
        owned_cluster(str(kind), docker=str(docker)),
    ):
        replacement = json.loads(state.read_text())
        replacement[0]["Id"] = "foreign-replacement-id"
        state.write_text(json.dumps(replacement))
    assert json.loads(state.read_text())[0]["Id"] == "foreign-replacement-id"
    assert all(json.loads(line)[1][0] != "delete" for line in calls.read_text().splitlines())


def test_actual_process_group_timeout_terminates_resistant_descendant(tmp_path):
    pid = tmp_path / "child.pid"
    program = tmp_path / "resistant.py"
    program.write_text(
        "import os,signal,time,sys\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nchild=os.fork()\nif child==0:\n Path(sys.argv[1]).write_text(str(os.getpid()))\nwhile True: time.sleep(.05)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable, str(program), str(pid)], dict(os.environ), timeout=1)
    child = int(pid.read_text())
    status = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True, timeout=5
    ).stdout.strip()
    assert not status or status.startswith("Z"), "The owned descendant must not remain running."
