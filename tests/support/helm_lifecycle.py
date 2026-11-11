"""Owned HTTP and child-process fixtures for public Helm lifecycle contracts."""

import asyncio
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.helm import HelmDriver, HelmReleaseKey, HelmRequest, HelmScope, HelmSettings
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.targets import SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from tests.support.connections import catalog_fixture, namespaces
from tests.support.helm import storage, storage_list
from tests.support.helm_catalog import chart_package, repository_index
from tests.support.resources import descriptor, legacy_roots

ADDRESS = HelmReleaseKey("release-team", "owned-release")
VALUES = b"message: owned-lifecycle\npassword: owned-private-lifecycle-value\n"
MANIFEST = """apiVersion: v1
kind: ConfigMap
metadata:
  name: owned-release-settings
data:
  message: owned-lifecycle
  password: owned-private-lifecycle-value
"""

CLI = r"""import hashlib, json, os, pathlib, sys, time
args = sys.argv[1:]
command = next((part for part in args if not part.startswith('-')), '')
record = pathlib.Path(os.environ['KUBERICH_LIFECYCLE_RECORD'])
entry = {'command': command, 'argv': args, 'pid': os.getpid(), 'cwd': os.getcwd(),
         'sentinel': os.environ.get('KUBERICH_LIFECYCLE_SENTINEL'), 'path': os.environ.get('PATH')}
if command in {'install', 'upgrade'}:
    index = args.index(command)
    chart = pathlib.Path(args[index + 2])
    values = pathlib.Path(next(item.split('=', 1)[1] for item in args if item.startswith('--values=')))
    entry.update(chart=str(chart), values=str(values), inputs_present=chart.is_file() and values.is_file())
    if entry['inputs_present']:
        entry['package_sha256'] = hashlib.sha256(chart.read_bytes()).hexdigest()
        entry['values_sha256'] = hashlib.sha256(values.read_bytes()).hexdigest()
with record.open('a') as stream:
    stream.write(json.dumps(entry) + '\n')
if TRAP:
    pathlib.Path(os.environ['KUBERICH_LIFECYCLE_TRAP']).write_text('wrong executable invoked')
    print('v0.0.0')
    raise SystemExit(0)
if command == 'version':
    print('v3.22.1')
    raise SystemExit(0)
if command == 'list':
    print('[]')
    raise SystemExit(0)
if command in {'install', 'upgrade', 'uninstall'}:
    assert any(item in {'--dry-run=server', '--dry-run=true'} for item in args)
    mode = os.environ['KUBERICH_LIFECYCLE_MODE']
    if mode == 'hold':
        pathlib.Path(os.environ['KUBERICH_LIFECYCLE_ENTERED']).write_text(str(os.getpid()))
        release = pathlib.Path(os.environ['KUBERICH_LIFECYCLE_RELEASE'])
        while not release.exists():
            if command != 'uninstall' and not (chart.is_file() and values.is_file()):
                pathlib.Path(os.environ['KUBERICH_LIFECYCLE_LOST_INPUTS']).write_text('inputs unlinked while preview was active')
                raise SystemExit(25)
            time.sleep(0.01)
    if mode == 'error':
        print('owned-private-lifecycle-value', file=sys.stderr)
        raise SystemExit(9)
    if mode == 'malformed':
        print('owned-private-lifecycle-value: {not structured output')
        raise SystemExit(0)
    if command == 'uninstall':
        print('owned native uninstall preview')
        raise SystemExit(0)
namespace = next(item.split('=', 1)[1] for item in args if item.startswith('--namespace='))
release_name = args[args.index(command) + 1]
print(json.dumps({'name': release_name, 'namespace': namespace,
    'version': 2 if command == 'upgrade' else 1, 'apply_method':'csa',
    'manifest': MANIFEST, 'hooks': [], 'config': {'message':'owned-lifecycle'},
    'info': {'status':'deployed'}}))
"""


class LifecycleApi:
    def __init__(self, package, *, existing):
        self.package = package
        self.packages = {("owned-chart", "1.0.0"): package}
        self.existing = existing
        self.requests = []
        self.mutations = []
        self.validations = []
        self.authorizations = []
        self.hold_index = False
        self.index_started = asyncio.Event()
        self.index_release = asyncio.Event()

    async def handle(self, request):
        self.requests.append((request.method, request.path, dict(request.query)))
        if (
            request.method == "POST"
            and request.path == "/api/v1/namespaces/" + ADDRESS.namespace + "/configmaps"
            and request.query.get("dryRun") == "All"
        ):
            value = await request.json()
            self.validations.append((value, dict(request.query)))
            return web.json_response(value, status=201)
        if request.method != "GET":
            self.mutations.append(request.path)
            return web.json_response({}, status=405)
        if request.path == "/charts/index.yaml":
            self.authorizations.append(request.headers.get("Authorization"))
            self.index_started.set()
            if self.hold_index:
                await self.index_release.wait()
            return web.Response(body=repository_index(self.packages))
        for (name, version), package in self.packages.items():
            if request.path == f"/charts/{name}-{version}.tgz":
                return web.Response(body=package)
        roots = legacy_roots()
        roots["/api/v1"]["resources"] = [
            {
                **descriptor("configmaps", kind="ConfigMap"),
                "verbs": ["get", "list", "watch", "create"],
            },
            descriptor("secrets", kind="Secret"),
            descriptor("namespaces", kind="Namespace", namespaced=False),
        ]
        if request.path in roots:
            return web.json_response(roots[request.path])
        if request.path == "/api/v1/namespaces":
            return namespaces("team", ADDRESS.namespace, "default")
        prefix = "/api/v1/namespaces/" + ADDRESS.namespace
        if request.path == prefix:
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": ADDRESS.namespace,
                        "uid": "owned-release-namespace",
                        "resourceVersion": "namespace-rv",
                    },
                    "status": {"phase": "Active"},
                }
            )
        if request.path == prefix + "/secrets":
            return web.json_response(
                storage_list([storage(1, key=ADDRESS, status="deployed")] if self.existing else [])
            )
        if request.path == prefix + "/secrets/sh.helm.release.v1.owned-release.v1":
            return (
                web.json_response(storage(1, key=ADDRESS, status="deployed"))
                if self.existing
                else web.json_response({}, status=404)
            )
        if request.path == prefix + "/configmaps/owned-release-settings" and self.existing:
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": "owned-release-settings",
                        "namespace": ADDRESS.namespace,
                        "uid": "owned-live-configmap",
                        "resourceVersion": "live-rv",
                        "labels": {"app.kubernetes.io/managed-by": "Helm"},
                        "annotations": {
                            "meta.helm.sh/release-name": ADDRESS.name,
                            "meta.helm.sh/release-namespace": ADDRESS.namespace,
                        },
                    },
                    "data": {
                        "message": "owned-before",
                        "password": "owned-private-lifecycle-value",
                    },
                }
            )
        return web.json_response({}, status=404)


class LifecycleHarness:
    def __init__(self, directory, api, client, service, request, chart, origin, record):
        self.directory, self.api, self.client, self.service = directory, api, client, service
        self.request, self.chart, self.origin, self.record = request, chart, origin, record
        self.release = directory / "preview-release"
        self.entered = directory / "preview-entered"
        self.lost_inputs = directory / "preview-lost-inputs"
        self.auth_called = directory / "auth-called.json"
        self.trap = directory / "wrong-executable"

    def calls(self):
        return (
            [json.loads(line) for line in self.record.read_text().splitlines()]
            if self.record.exists()
            else []
        )

    def previews(self):
        return [
            item for item in self.calls() if item["command"] in {"install", "upgrade", "uninstall"}
        ]

    def input_directories(self):
        return tuple(Path(self.client.directory.name).glob("helm-inputs-*"))


def fixture_executable(path, *, trap=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\nTRAP = {trap!r}\nMANIFEST = {MANIFEST!r}\n" + CLI)
    path.chmod(0o700)


@asynccontextmanager
async def lifecycle_source(
    directory, *, existing=False, namespace=ADDRESS.namespace, mode="", delegated_executable=None
):
    directory.mkdir(parents=True, exist_ok=True)
    package = chart_package(values=VALUES)
    chart = ChartSnapshot(
        "owned-chart",
        "1.0.0",
        "owned-contract-chart",
        hashlib.sha256(package).hexdigest(),
        package,
        VALUES,
    )
    api = LifecycleApi(package, existing=existing)
    application = web.Application()
    application.router.add_route("*", "/{tail:.*}", api.handle)
    http = web.AppRunner(application, shutdown_timeout=0.1)
    await http.setup()
    site = web.TCPSite(http, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{http.addresses[0][1]}"
    app_directory, helper_directory = directory / "application", directory / "helper"
    app_directory.mkdir()
    helper_directory.mkdir()
    record = directory / "helm-calls.jsonl"
    environment = {
        "PATH": os.defpath,
        "KUBERICH_LIFECYCLE_RECORD": str(record),
        "KUBERICH_LIFECYCLE_MODE": mode,
        "KUBERICH_LIFECYCLE_ENTERED": str(directory / "preview-entered"),
        "KUBERICH_LIFECYCLE_RELEASE": str(directory / "preview-release"),
        "KUBERICH_LIFECYCLE_LOST_INPUTS": str(directory / "preview-lost-inputs"),
        "KUBERICH_LIFECYCLE_TRAP": str(directory / "wrong-executable"),
        "KUBERICH_LIFECYCLE_SENTINEL": "captured-helper",
    }
    client_directory = app_directory
    user = None
    executable = app_directory / "owned-helm"
    fixture_executable(executable)
    app_environment = dict(environment)
    if delegated_executable is not None:
        client_directory = helper_directory
        executable = helper_directory / "tools/owned-helm"
        fixture_executable(executable)
        fixture_executable(app_directory / "tools/owned-helm", trap=True)
        helper = helper_directory / "owned-auth.py"
        helper.write_text(
            "import json,os,pathlib\n"
            + f"pathlib.Path({str(directory / 'auth-called.json')!r}).write_text(json.dumps({{'cwd':os.getcwd(),'sentinel':os.environ.get('KUBERICH_LIFECYCLE_SENTINEL')}}))\n"
            + "print(json.dumps({'apiVersion':'client.authentication.k8s.io/v1','kind':'ExecCredential','status':{'token':'synthetic-owned-provider'}}))\n"
        )
        user = {
            "exec": {
                "apiVersion": "client.authentication.k8s.io/v1",
                "command": sys.executable,
                "args": [str(helper)],
                "interactiveMode": "Never",
            }
        }
        environment["PATH"] = "tools"
        app_environment.update(
            PATH=str(app_directory / "tools"), KUBERICH_LIFECYCLE_SENTINEL="wrong-application"
        )
    client = KubernetesSession(
        catalog_fixture(client_directory, origin, user=user).select("kuberich-test-one"), 2
    )
    client.environment = dict(environment)
    await client.open()
    request = HelmRequest(
        HelmScope(SessionIdentity(client.context.name, 1), namespace, HelmDriver.SECRET), 1
    )
    service = HelmService(
        client,
        AccessPolicy(False),
        HelmSettings(delegated_executable or str(executable)),
        app_environment,
        app_directory,
        lambda candidate: candidate == request,
        catalog_directory=directory / "catalog",
    )
    fixture = LifecycleHarness(directory, api, client, service, request, chart, origin, record)
    try:
        yield fixture
    finally:
        fixture.release.touch()
        api.index_release.set()
        await service.close()
        await client.close()
        await http.cleanup()
