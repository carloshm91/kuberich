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
    verified_nodes,
    verify_config,
)


def node(name="kuberich-test-owned", role="control-plane", identity="owned-node-id"):
    return {
        "Id": identity,
        "Config": {
            "Image": NODE_IMAGE,
            "Labels": {"io.x-k8s.kind.cluster": name, "io.x-k8s.kind.role": role},
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
 elif args[0]=='exec': print(state.with_suffix('.kubelet.yaml').read_text())
else:
 if args[0]=='version': print('kind v0.33.0 fixture')
 elif args[0]=='create':
  name=args[args.index('--name')+1];path=Path(args[args.index('--kubeconfig')+1])
  nodes=[node(name)];data=config(name)
  if os.environ.get('OWNED_FAULT')=='config': data['clusters'][0]['cluster']['server']='https://foreign:443'
  path.write_text(yaml.safe_dump(data))
  if '--config' in args:
   setup=yaml.safe_load(Path(args[args.index('--config')+1]).read_text())
   nodes.extend(node(name,'worker','worker-'+str(i)) for i in range(len(setup['nodes'])-1))
   if 'kubeadmConfigPatches' in setup['nodes'][0]:
    kubelet=yaml.safe_load(setup['nodes'][0]['kubeadmConfigPatches'][0])
    if os.environ.get('OWNED_KUBELET_FAULT')=='period': kubelet['crashLoopBackOff']['maxContainerRestartPeriod']='300s'
    if os.environ.get('OWNED_KUBELET_FAULT')=='gate': kubelet['featureGates']['KubeletCrashLoopBackOffMax']=False
    if os.environ.get('OWNED_KUBELET_FAULT')=='sync': kubelet['syncFrequency']='1m'
    if os.environ.get('OWNED_KUBELET_FAULT')=='malformed': kubelet=None
    state.with_suffix('.kubelet.yaml').write_text(yaml.safe_dump(kubelet))
  membership=os.environ.get('OWNED_MEMBERSHIP')
  if membership=='partial-worker': nodes=nodes[-1:]
  if membership=='partial-control-plane': nodes=nodes[:1]
  if membership=='foreign': nodes[-1]['Config']['Labels']['io.x-k8s.kind.cluster']='foreign'
  if membership=='reversed': nodes.reverse()
  state.write_text(json.dumps(nodes))
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
            assert cluster.sync_frequency_seconds is None
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
    assert "--config" not in creation[1]
    assert deletion[1][-2:] == ["--kubeconfig", deletion[2]]
    assert {s: signal.getsignal(s) for s in before} == before


@pytest.mark.parametrize("period", [1, 20, 300])
def test_owned_restart_period_is_applied_and_read_back_from_verified_node(fake_kind, period):
    kind, docker, state, calls = fake_kind
    with owned_cluster(str(kind), docker=str(docker), max_restart_period_seconds=period) as cluster:
        assert cluster.max_restart_period_seconds == period
        records = [json.loads(line) for line in calls.read_text().splitlines()]
        creation = next(row for row in records if row[0] == "kind" and row[1][0] == "create")
        path = Path(creation[1][creation[1].index("--config") + 1])
        configuration = yaml.safe_load(path.read_text())
        patch = yaml.safe_load(configuration["nodes"][0]["kubeadmConfigPatches"][0])
        assert configuration["nodes"][0]["role"] == "control-plane"
        assert patch["kind"] == "KubeletConfiguration"
        assert patch["crashLoopBackOff"]["maxContainerRestartPeriod"] == f"{period}s"
        assert patch["featureGates"]["KubeletCrashLoopBackOffMax"] is True
        assert "syncFrequency" not in patch
        read_back = next(row for row in records if row[0] == "docker" and row[1][0] == "exec")
        assert read_back[1] == ["exec", "owned-node-id", "cat", "/var/lib/kubelet/config.yaml"]
        assert read_back[2] == str(cluster.path)
    assert json.loads(state.read_text()) == []
    assert not path.exists()


@pytest.mark.parametrize("period", [0, 301, -1, True, 20.5, "20s"])
def test_invalid_restart_period_cannot_contact_docker_or_create_a_cluster(fake_kind, period):
    kind, docker, state, calls = fake_kind
    with (
        pytest.raises(ValueError, match="integer from 1 to 300"),
        owned_cluster(str(kind), docker=str(docker), max_restart_period_seconds=period),
    ):
        pytest.fail("invalid configuration must not yield")
    assert not calls.exists() and json.loads(state.read_text()) == []


@pytest.mark.parametrize("fault", ["period", "gate", "malformed"])
def test_unapplied_owned_restart_configuration_fails_and_cleans_without_yield(
    fake_kind, monkeypatch, fault
):
    kind, docker, state, calls = fake_kind
    monkeypatch.setenv("OWNED_KUBELET_FAULT", fault)
    with (
        pytest.raises(ValueError, match="was not applied"),
        owned_cluster(str(kind), docker=str(docker), max_restart_period_seconds=20),
    ):
        pytest.fail("an unverified kubelet setting must not yield")
    assert json.loads(state.read_text()) == []
    assert any(json.loads(line)[1][0] == "delete" for line in calls.read_text().splitlines())


@pytest.mark.parametrize("frequency,period", [(1, None), (60, None), (1, 20)])
def test_owned_sync_frequency_is_explicit_and_verified_before_yield(fake_kind, frequency, period):
    kind, docker, state, calls = fake_kind
    with owned_cluster(
        str(kind),
        docker=str(docker),
        max_restart_period_seconds=period,
        sync_frequency_seconds=frequency,
    ) as cluster:
        assert cluster.sync_frequency_seconds == frequency
        records = [json.loads(line) for line in calls.read_text().splitlines()]
        creation = next(row for row in records if row[0] == "kind" and row[1][0] == "create")
        path = Path(creation[1][creation[1].index("--config") + 1])
        config = yaml.safe_load(path.read_text())
        patch = yaml.safe_load(config["nodes"][0]["kubeadmConfigPatches"][0])
        assert patch["syncFrequency"] == f"{frequency}s"
        assert ("crashLoopBackOff" in patch) == (period is not None)
        read_back = next(row for row in records if row[0] == "docker" and row[1][0] == "exec")
        assert read_back[1] == ["exec", "owned-node-id", "cat", "/var/lib/kubelet/config.yaml"]
    assert json.loads(state.read_text()) == [] and not path.exists()


@pytest.mark.parametrize("frequency", [0, 61, -1, True, 1.5, "1s"])
def test_invalid_sync_frequency_is_rejected_before_any_process(fake_kind, frequency):
    kind, docker, state, calls = fake_kind
    with (
        pytest.raises(ValueError, match="integer from 1 to 60"),
        owned_cluster(str(kind), docker=str(docker), sync_frequency_seconds=frequency),
    ):
        pytest.fail("invalid configuration must not yield")
    assert not calls.exists() and json.loads(state.read_text()) == []


@pytest.mark.parametrize("fault", ["sync", "malformed"])
def test_unapplied_sync_frequency_fails_and_cleans_the_owned_cluster(fake_kind, monkeypatch, fault):
    kind, docker, state, calls = fake_kind
    monkeypatch.setenv("OWNED_KUBELET_FAULT", fault)
    with (
        pytest.raises(ValueError, match="was not applied"),
        owned_cluster(str(kind), docker=str(docker), sync_frequency_seconds=1),
    ):
        pytest.fail("unverified synchronization must not yield")
    assert json.loads(state.read_text()) == []
    assert any(json.loads(line)[1][0] == "delete" for line in calls.read_text().splitlines())


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


def test_multinode_endpoint_binds_control_plane_independent_of_listing_order(tmp_path):
    workers = [node(role="worker", identity=f"worker-{i}") for i in (2, 1)]
    for worker in workers:
        worker["NetworkSettings"]["Ports"] = {}
    nodes = [workers[0], node(), workers[1]]
    path = tmp_path / "generated"
    path.write_text(yaml.safe_dump(config()))
    assert verify_config(path, "kuberich-test-owned", nodes, worker_count=2) == (
        "kind-kuberich-test-owned"
    )
    assert verified_nodes(nodes, "kuberich-test-owned", worker_count=2) == (
        "owned-node-id",
        "worker-1",
        "worker-2",
    )
    nodes[1]["NetworkSettings"]["Ports"]["6443/tcp"][0]["HostPort"] = "9999"
    with pytest.raises(ValueError, match="endpoint"):
        verify_config(path, "kuberich-test-owned", nodes, worker_count=2)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-worker",
        "extra-worker",
        "extra-control-plane",
        "duplicate",
        "image",
        "role",
        "labels",
        "config",
        "id",
    ],
)
def test_multinode_membership_refuses_incomplete_foreign_or_ambiguous_nodes(fault):
    nodes = [
        node(),
        node(role="worker", identity="worker-1"),
        node(role="worker", identity="worker-2"),
    ]
    if fault == "missing-worker":
        nodes.pop()
    elif fault == "extra-worker":
        nodes.append(node(role="worker", identity="worker-3"))
    elif fault == "extra-control-plane":
        nodes.append(node(identity="other-control-plane"))
    elif fault == "duplicate":
        nodes[-1]["Id"] = nodes[0]["Id"]
    elif fault == "image":
        nodes[-1]["Config"]["Image"] = "unverified:latest"
    elif fault == "role":
        nodes[-1]["Config"]["Labels"]["io.x-k8s.kind.role"] = "other"
    elif fault == "labels":
        nodes[-1]["Config"]["Labels"] = None
    elif fault == "config":
        nodes[-1]["Config"] = None
    else:
        nodes[-1]["Id"] = ""
    with pytest.raises(ValueError):
        verified_nodes(nodes, "kuberich-test-owned", worker_count=2, require_complete=True)


def test_multinode_creation_verifies_generated_roles_and_order_independent_cleanup(
    fake_kind, monkeypatch
):
    kind, docker, state, calls = fake_kind
    monkeypatch.setenv("OWNED_MEMBERSHIP", "reversed")
    with owned_cluster(str(kind), docker=str(docker), worker_count=2) as cluster:
        assert cluster.node_ids == ("owned-node-id", "worker-0", "worker-1")
        assert cluster.worker_count == 2
        records = [json.loads(line) for line in calls.read_text().splitlines()]
        creation = next(row for row in records if row[0] == "kind" and row[1][0] == "create")
        path = Path(creation[1][creation[1].index("--config") + 1])
        assert yaml.safe_load(path.read_text())["nodes"] == [
            {"role": "control-plane"},
            {"role": "worker"},
            {"role": "worker"},
        ]
        state.write_text(json.dumps(list(reversed(json.loads(state.read_text())))))
    assert json.loads(state.read_text()) == [] and not path.exists()


@pytest.mark.parametrize("worker_count", [-1, 5, True, 2.5, "2"])
def test_invalid_worker_count_cannot_contact_docker(fake_kind, worker_count):
    kind, docker, state, calls = fake_kind
    with (
        pytest.raises(ValueError, match="worker count"),
        owned_cluster(str(kind), docker=str(docker), worker_count=worker_count),
    ):
        pytest.fail("invalid topology must not yield")
    assert not calls.exists() and json.loads(state.read_text()) == []


@pytest.mark.parametrize("membership", ["partial-worker", "partial-control-plane"])
@pytest.mark.parametrize("create_failed", [False, True])
def test_partial_multinode_creation_cleans_only_verified_owned_members(
    fake_kind, monkeypatch, membership, create_failed
):
    kind, docker, state, calls = fake_kind
    monkeypatch.setenv("OWNED_MEMBERSHIP", membership)
    if create_failed:
        monkeypatch.setenv("OWNED_FAULT", "create")
    expected = subprocess.CalledProcessError if create_failed else ValueError
    with pytest.raises(expected), owned_cluster(str(kind), docker=str(docker), worker_count=2):
        pytest.fail("incomplete topology cannot authorize fixtures")
    assert json.loads(state.read_text()) == []
    assert any(json.loads(line)[1][0] == "delete" for line in calls.read_text().splitlines())


@pytest.mark.parametrize("replacement", [False, True])
def test_multinode_cleanup_refuses_foreign_or_replaced_worker(fake_kind, monkeypatch, replacement):
    kind, docker, state, calls = fake_kind
    if not replacement:
        monkeypatch.setenv("OWNED_MEMBERSHIP", "foreign")
        monkeypatch.setenv("OWNED_FAULT", "create")
    with pytest.raises(ValueError), owned_cluster(str(kind), docker=str(docker), worker_count=2):
        members = json.loads(state.read_text())
        members[-1]["Id"] = "replacement-worker-id"
        state.write_text(json.dumps(members))
    assert json.loads(state.read_text())
    assert all(json.loads(line)[1][0] != "delete" for line in calls.read_text().splitlines())


def test_actual_process_group_timeout_terminates_resistant_descendant(tmp_path):
    pid = tmp_path / "child.pid"
    program = tmp_path / "resistant.py"
    program.write_text(
        "import os,signal,time,sys\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nchild=os.fork()\nif child==0:\n pending=Path(sys.argv[1]+'.pending')\n pending.write_text(str(os.getpid()))\n pending.replace(sys.argv[1])\nwhile True: time.sleep(.05)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable, str(program), str(pid)], dict(os.environ), timeout=1)
    child = int(pid.read_text())
    status = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True, timeout=5
    ).stdout.strip()
    assert not status or status.startswith("Z"), "The owned descendant must not remain running."
