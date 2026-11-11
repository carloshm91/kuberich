"""Synthetic benchmark process faults and exact captured API fixtures."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

from aiohttp import web

from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmarks import BenchmarkManager
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from tests.support.port_forwards import executable as forward_executable
from tests.support.resources import reader_fixture
from tests.unit.test_benchmark_targets import POD, SERVICE

REPORT = {
    "latencies": {
        "total": 2000000,
        "mean": 1000000,
        "50th": 1000000,
        "90th": 1000000,
        "95th": 1000000,
        "99th": 1000000,
        "max": 1000000,
        "min": 1000000,
    },
    "bytes_in": {"total": 0, "mean": 0},
    "bytes_out": {"total": 0, "mean": 0},
    "earliest": "2026-11-10T00:00:00Z",
    "latest": "2026-11-10T00:00:01Z",
    "end": "2026-11-10T00:00:01.001Z",
    "duration": 1000000000,
    "wait": 1000000,
    "requests": 2,
    "rate": 2.0,
    "throughput": 2 / 1.001,
    "success": 1.0,
    "status_codes": {"200": 2},
    "errors": [],
}
VERSION = "Version: v12.13.0\nCommit: synthetic\nRuntime: synthetic\nDate: 2026-11-10\n"


def executable(directory: Path, mode: str = "normal") -> Path:
    path = directory / "vegeta-fault-fixture"
    program = f"""#!{sys.executable}
import json,os,signal,subprocess,sys,time
from pathlib import Path
root=Path({str(directory)!r})
mode={mode!r}
phase='version' if sys.argv[1:]==['-version'] else 'attack' if 'attack' in sys.argv else 'report'
receipt={{'pid':os.getpid(),'argv':sys.argv,'environment':dict(os.environ),'phase':phase}}
pending=root/(phase+'.pending')
pending.write_text(json.dumps(receipt));pending.chmod(0o600);pending.replace(root/(phase+'.json'))
if mode==phase+'-flood': os.write(1,b'x'*(3*1024*1024))
if mode==phase+'-sleep': time.sleep(60)
if mode==phase+'-fail':
    print('synthetic-private-token URL?secret=synthetic-private',file=sys.stderr,flush=True)
    raise SystemExit(2)
if mode==phase+'-descendant':
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    pending=root/'descendant.pending';pending.write_text(str(child.pid));pending.replace(root/'descendant.pid')
    raise SystemExit(0)
if phase=='version':
    print({VERSION!r},end='')
elif phase=='attack':
    target=Path(next(arg.split('=',1)[1] for arg in sys.argv if arg.startswith('-targets=')))
    assert target.stat().st_mode&0o777==0o600 and target.parent.stat().st_mode&0o777==0o700
    pending=root/'target.pending';pending.write_bytes(target.read_bytes());pending.chmod(0o600);pending.replace(root/'target.json')
    print('synthetic-private-gob')
else:
    print('invalid synthetic-private-token' if mode=='report-malformed' else {json.dumps(REPORT)!r})
"""
    path.write_text(program)
    path.chmod(0o700)
    return path


async def receipt(path: Path):
    async with asyncio.timeout(10):
        while True:
            try:
                return json.loads(path.read_text())
            except FileNotFoundError:
                await asyncio.sleep(0.01)


async def gone(pid: int):
    async with asyncio.timeout(5):
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            status = Path(f"/proc/{pid}/stat")
            if status.exists() and status.read_text().split()[2] == "Z":
                return
            await asyncio.sleep(0.01)


@asynccontextmanager
async def fixture(
    directory: Path,
    *,
    mode="normal",
    current=lambda: True,
    readonly=False,
    resource="services",
    forward_mode="normal",
    store=None,
    executable_path=None,
):
    service, pod = deepcopy(SERVICE), deepcopy(POD)
    pods = [pod]
    requests = []

    async def response(request):
        requests.append(request.path)
        if request.path.endswith("/services/owned"):
            return web.json_response(service)
        if request.path.endswith("/pods/backend"):
            return web.json_response(pod)
        assert request.path.endswith("/pods")
        return web.json_response(
            {"apiVersion": "v1", "kind": "PodList", "metadata": {}, "items": pods}
        )

    async with reader_fixture(directory, response) as reader:
        policy = AccessPolicy(readonly)
        async with ProcessRunner(policy) as processes:
            forwards = ForwardManager(processes, startup_timeout=0.2, check_interval=0.05)
            store = store or BenchmarkStore(directory / "records")
            manager = BenchmarkManager(forwards, store)
            target = ResourceTarget(
                SessionIdentity(reader.session.context.name, 1),
                "",
                resource,
                "team",
                "owned" if resource == "services" else "backend",
                "service-uid" if resource == "services" else "pod-uid",
            )
            path = executable_path or executable(directory, mode)
            environment = forward_executable(directory, forward_mode)
            owner = None
            try:
                owner = manager.create(
                    reader.session,
                    target,
                    policy,
                    current,
                    settings=BenchmarkSettings(path),
                    environment=environment,
                    directory=directory,
                )
                yield owner, manager, forwards, processes, store, service, pod, requests, pods
            finally:
                await manager.close()
                await forwards.close()
