"""Owned child release effects and HTTP identity faults, never a caller cluster."""

import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.helm import HelmDriver, HelmRequest, HelmScope, HelmSettings
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.targets import SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from tests.support.connections import catalog_fixture
from tests.support.helm import storage, storage_list
from tests.support.helm_catalog import chart_package
from tests.support.helm_lifecycle import ADDRESS, MANIFEST, VALUES, LifecycleApi, LifecycleHarness

CHILD = r"""import hashlib,json,os,pathlib,sys,time
state_path = pathlib.Path(os.environ['KUBERICH_LIFECYCLE_STATE'])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
command = next((part for part in args if not part.startswith('-')), '')
preview = '--dry-run=server' in args or '--dry-run=true' in args
entry={'command':command,'argv':args,'preview':preview,'pid':os.getpid()}
for flag,name in [('--values=','values')]:
    item=next((part.split('=',1)[1] for part in args if part.startswith(flag)),None)
    if item:
        entry[name]=item
        entry[name+'_sha256']=hashlib.sha256(pathlib.Path(item).read_bytes()).hexdigest()
if command in {'install','upgrade'}:
    chart=pathlib.Path(args[args.index(command)+2])
    entry['chart']=str(chart)
    entry['chart_sha256']=hashlib.sha256(chart.read_bytes()).hexdigest()
with open(os.environ['KUBERICH_LIFECYCLE_RECORD'],'a') as output:
    output.write(json.dumps(entry)+'\n')
if command=='version':
    print(state.get('version','v3.22.1'))
    raise SystemExit(0)
revision=state['revision']
if command=='list':
    print(json.dumps([{'name':NAME,'namespace':NAMESPACE,'revision':str(revision),'status':state['status'],'chart':'owned-chart-1.0.0','app_version':'1','updated':'2026-11-11T00:00:00Z'}] if revision else []))
    raise SystemExit(0)
if command in {'install','upgrade','uninstall'} and preview:
    mode=state.get('preview_mode','')
    if mode=='error':
        print('owned-secret-value',file=sys.stderr)
        raise SystemExit(4)
    if mode=='malformed':
        print('owned-secret-value is not structured')
        raise SystemExit(0)
    if mode=='hold':
        pathlib.Path(os.environ['KUBERICH_LIFECYCLE_ENTERED']).touch()
        while not pathlib.Path(os.environ['KUBERICH_LIFECYCLE_RELEASE']).exists():
            time.sleep(.01)
if command in {'install','upgrade','uninstall'} and not preview:
    mode=state.get('write_mode','')
    if mode not in {'no-change','before-error'}:
        if command=='uninstall':
            state['resource']=bool(state.get('retain_resource',False))
            if '--keep-history=true' in args:
                state['status']='uninstalled'
            else:
                state['revision']=0
        else:
            state['revision']=(revision+1 if command=='upgrade' else 1)+(1 if mode=='revision-jump' else 0)
            state['status']='failed' if mode=='apply-error' else 'deployed'
            state['resource']=True
            state['live_version']=str(int(state['live_version'])+1)
        replacement=state_path.with_suffix('.new')
        state.update(state.get('after_write',{}))
        replacement.write_text(json.dumps(state))
        replacement.replace(state_path)
    if mode in {'hold-after','timeout'}:
        pathlib.Path(os.environ['KUBERICH_LIFECYCLE_ENTERED']).touch()
        while not pathlib.Path(os.environ['KUBERICH_LIFECYCLE_RELEASE']).exists():
            time.sleep(.01)
    if mode in {'apply-error','before-error'}:
        print('owned-secret-value',file=sys.stderr)
        raise SystemExit(7)
    print('owned-secret-value raw write output')
    raise SystemExit(0)
if command=='uninstall':
    print('owned native uninstall preview')
    raise SystemExit(0)
print(json.dumps({'name':NAME,'namespace':NAMESPACE,'version':revision if command=='status' else revision+1 if command=='upgrade' else 1,'manifest':state.get('stored_manifest',state.get('rendered_manifest',MANIFEST)) if command=='status' else state.get('rendered_manifest',MANIFEST),'hooks':state.get('hooks',[]),'apply_method':state.get('apply_method','csa'),'config':state.get('values',{'message':'old'}),'info':{'status':state['status']}}))
"""


class EffectApi(LifecycleApi):
    def __init__(self, package, state):
        super().__init__(package, existing=False)
        self.state_path = state

    def state(self):
        return json.loads(self.state_path.read_text())

    async def handle(self, request):
        state = self.state()
        if request.path in state.get("api_overrides", {}):
            self.requests.append((request.method, request.path, dict(request.query)))
            response = state["api_overrides"][request.path]
            return web.json_response(response["body"], status=response.get("status", 200))
        if request.path in state.get("denied_paths", []):
            self.requests.append((request.method, request.path, dict(request.query)))
            return web.json_response({"message": "owned-secret-value"}, status=403)
        prefix = "/api/v1/namespaces/" + ADDRESS.namespace
        if request.path == prefix:
            self.requests.append((request.method, request.path, dict(request.query)))
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": ADDRESS.namespace,
                        "uid": state.get("namespace_uid", "owned-namespace"),
                        "resourceVersion": "ns-rv",
                        **(
                            {"deletionTimestamp": "2026-11-11T00:00:00Z"}
                            if state.get("namespace_terminating")
                            else {}
                        ),
                    },
                    "status": {"phase": state.get("namespace_phase", "Active")},
                }
            )
        if request.path.startswith(prefix + "/secrets") or (
            request.path.startswith(prefix + "/configmaps") and "sh.helm.release" in request.path
        ):
            self.requests.append((request.method, request.path, dict(request.query)))
            rows = [
                storage(
                    number,
                    key=ADDRESS,
                    status=state["status"] if number == state["revision"] else "superseded",
                )
                for number in range(1, state["revision"] + 1)
            ]
            for row in rows:
                row["metadata"]["uid"] += state.get("storage_uid_suffix", "")
            if request.path == prefix + "/secrets":
                return web.json_response(storage_list(rows))
            row = next(
                (row for row in rows if request.path.endswith("/" + row["metadata"]["name"])), None
            )
            return web.json_response(
                row if row is not None else {}, status=200 if row is not None else 404
            )
        if request.path == prefix + "/configmaps/owned-release-settings":
            self.requests.append((request.method, request.path, dict(request.query)))
            if not state["resource"]:
                return web.json_response({}, status=404)
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": "owned-release-settings",
                        "namespace": ADDRESS.namespace,
                        "uid": state.get("live_uid", "owned-live"),
                        "resourceVersion": state["live_version"],
                        "labels": {"app.kubernetes.io/managed-by": "Helm"},
                        "annotations": {
                            "meta.helm.sh/release-name": "foreign"
                            if state.get("foreign_owner")
                            else ADDRESS.name,
                            "meta.helm.sh/release-namespace": ADDRESS.namespace,
                            **(
                                {"helm.sh/resource-policy": "keep"}
                                if state.get("retain_resource")
                                else {}
                            ),
                        },
                        **(
                            {"deletionTimestamp": "2026-11-11T00:00:00Z"}
                            if state.get("deleting_resource")
                            else {}
                        ),
                    },
                    "data": {"message": "actual-effects", "password": "owned-secret-value"},
                }
            )
        return await super().handle(request)


class EffectHarness(LifecycleHarness):
    def state(self):
        return self.api.state()

    def change(self, **updates):
        state = self.state()
        state.update(updates)
        self.api.state_path.write_text(json.dumps(state))

    def writes(self):
        return [
            call
            for call in self.calls()
            if call["command"] in {"install", "upgrade", "uninstall"} and not call["preview"]
        ]


@asynccontextmanager
async def effect_source(
    directory, *, existing=False, read_only=False, namespace=ADDRESS.namespace, **state_changes
):
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / "release-state.json"
    state.write_text(
        json.dumps(
            {
                "revision": 1 if existing else 0,
                "status": "deployed",
                "resource": existing,
                "live_version": "1",
                **state_changes,
            }
        )
    )
    package = chart_package(values=VALUES)
    chart = ChartSnapshot(
        "owned-chart",
        "1.0.0",
        "owned-effects-fixture",
        hashlib.sha256(package).hexdigest(),
        package,
        VALUES,
    )
    api = EffectApi(package, state)
    application = web.Application()
    application.router.add_route("*", "/{tail:.*}", api.handle)
    http = web.AppRunner(application, shutdown_timeout=0.1)
    await http.setup()
    site = web.TCPSite(http, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{http.addresses[0][1]}"
    executable = directory / "helm-effects"
    executable.write_text(
        f"#!{sys.executable}\nNAME={ADDRESS.name!r}\nNAMESPACE={ADDRESS.namespace!r}\nMANIFEST={MANIFEST!r}\n"
        + CHILD
    )
    executable.chmod(0o700)
    record = directory / "calls.jsonl"
    environment = {
        "PATH": os.defpath,
        "KUBERICH_LIFECYCLE_STATE": str(state),
        "KUBERICH_LIFECYCLE_RECORD": str(record),
        "KUBERICH_LIFECYCLE_ENTERED": str(directory / "preview-entered"),
        "KUBERICH_LIFECYCLE_RELEASE": str(directory / "preview-release"),
    }
    client = KubernetesSession(catalog_fixture(directory, origin).select("kuberich-test-one"), 2)
    await client.open()
    request = HelmRequest(
        HelmScope(SessionIdentity(client.context.name, 1), namespace, HelmDriver.SECRET), 1
    )
    service = HelmService(
        client,
        AccessPolicy(read_only),
        HelmSettings(str(executable)),
        environment,
        directory,
        lambda candidate: candidate == request,
        catalog_directory=directory / "catalog",
    )
    fixture = EffectHarness(directory, api, client, service, request, chart, origin, record)
    try:
        yield fixture
    finally:
        fixture.release.touch()
        try:
            await service.close()
        finally:
            try:
                await client.close()
            finally:
                await http.cleanup()
