"""Synthetic Helm CLI and metadata-only API fixtures; never use ambient clusters."""

import asyncio
import copy
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from aiohttp import web

from kuberich.adapters.helm import HelmAdapter
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.helm import (
    HelmDriver,
    HelmHistory,
    HelmHook,
    HelmList,
    HelmRelease,
    HelmReleaseKey,
    HelmRequest,
    HelmRevision,
    HelmScope,
    HelmSettings,
    HelmStatus,
    HelmStorageIdentity,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from tests.support.connections import catalog_fixture

PRIVATE_VALUE = "synthetic-private-helm-value"
KEY = HelmReleaseKey("team", "demo")


def owned_process_state(pid: int) -> str:
    """Observe only a PID captured from this fixture; never inspect args or environment."""
    if sys.platform == "linux":
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            return "absent"
        return fields[0]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "absent"
    return "exists"


async def wait_owned_process_stopped(
    pid: int, evidence: Path, *, before_cancel: str, timeout: float = 1.0
) -> tuple[str, ...]:
    """Require termination within a fixed observation window, without sending signals.

    Linux closes inherited pipes before exit_notify publishes EXIT_ZOMBIE, so
    draining ProcessRunner's pipes can precede that last observable transition.
    An orphan zombie has finished execution; its adopter owns final reaping.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    observations: list[dict[str, float | str]] = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                state = owned_process_state(pid)
                observations.append({"elapsed_seconds": loop.time() - started, "state": state})
                if state in {"absent", "Z"}:
                    return tuple(str(item["state"]) for item in observations)
                await asyncio.sleep(0.005)
    except TimeoutError:
        raise AssertionError(
            f"Owned descendant {pid} did not terminate within {timeout}s: {observations}"
        ) from None
    finally:
        evidence.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "before_cancel": before_cancel,
                    "timeout_seconds": timeout,
                    "observations": observations,
                },
                indent=2,
            )
            + "\n"
        )


def request(driver: HelmDriver = HelmDriver.SECRET, namespace: str | None = "team") -> HelmRequest:
    return HelmRequest(HelmScope(SessionIdentity("kuberich-test-one", 1), namespace, driver), 1)


def release(
    revision: int = 3, *, key: HelmReleaseKey = KEY, status: str = "deployed"
) -> HelmRelease:
    return HelmRelease(key, revision, status, "tiny-0.1.0", "1.0", "2026-11-09 12:00:00 +0000 UTC")


def storage(revision: int, *, key: HelmReleaseKey = KEY, status: str | None = None) -> dict:
    return {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "PartialObjectMetadata",
        "metadata": {
            "namespace": key.namespace,
            "name": f"sh.helm.release.v1.{key.name}.v{revision}",
            "uid": f"owned-{key.namespace}-{key.name}-{revision}",
            "resourceVersion": f"opaque-{revision}",
            "labels": {
                "owner": "helm",
                "name": key.name,
                "version": str(revision),
                "status": status or ("deployed" if revision == 3 else "superseded"),
            },
        },
    }


def storage_list(
    items: list[dict], *, continuation: str = "", version: str = "collection-opaque"
) -> dict:
    return {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "PartialObjectMetadataList",
        "metadata": {"resourceVersion": version, "continue": continuation},
        "items": items,
    }


class HelmMetadataAPI:
    def __init__(self) -> None:
        self.records = {revision: storage(revision) for revision in (1, 2, 3)}
        self.requests: list[tuple[str, dict[str, str], str]] = []
        self.pages: list[dict] | None = None
        self.status = 200
        self.block = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.rollback_marker: Path | None = None

    async def handle(self, incoming: web.Request) -> web.Response:
        self.requests.append(
            (incoming.path, dict(incoming.query), incoming.headers.get("Accept", ""))
        )
        self.started.set()
        if self.block:
            await self.release.wait()
        if self.status != 200:
            return web.json_response({"message": PRIVATE_VALUE}, status=self.status)
        if self.rollback_marker is not None and self.rollback_marker.exists():
            self.records[3]["metadata"]["labels"]["status"] = "superseded"
            self.records[4] = storage(4, status=self.rollback_marker.read_text() or "deployed")
        if incoming.match_info.get("name"):
            name = incoming.match_info["name"]
            result = next(
                (item for item in self.records.values() if item["metadata"]["name"] == name), None
            )
            return (
                web.json_response(copy.deepcopy(result))
                if result is not None
                else web.json_response({}, status=404)
            )
        if self.pages is not None:
            index = int(incoming.query.get("continue", "0"))
            return web.json_response(copy.deepcopy(self.pages[min(index, len(self.pages) - 1)]))
        return web.json_response(storage_list(copy.deepcopy(list(self.records.values()))))


@asynccontextmanager
async def metadata_api() -> AsyncIterator[tuple[str, HelmMetadataAPI]]:
    api = HelmMetadataAPI()
    app = web.Application()
    app.router.add_get("/api/v1/namespaces/{namespace}/{plural}", api.handle)
    app.router.add_get("/api/v1/namespaces/{namespace}/{plural}/{name}", api.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}", api
    finally:
        api.release.set()
        await runner.cleanup()


def fake_helm(directory: Path, **options) -> tuple[HelmSettings, dict[str, str], Path, Path]:
    """An executable Python process, including owned child-process fault modes."""
    executable, scenario, record = (
        directory / "helm-fixture",
        directory / "helm-scenario.json",
        directory / "helm-calls.jsonl",
    )
    scenario.write_text(json.dumps(options))
    executable.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, pathlib, signal, stat, subprocess, sys, time
scenario_path = pathlib.Path(os.environ["KUBERICH_HELM_FIXTURE_SCENARIO"])
scenario = json.loads(scenario_path.read_text())
args = sys.argv[1:]
command = next((part for part in args if not part.startswith("-")), "")
config = os.environ.get("KUBECONFIG")
entry = {"argv": args, "pid": os.getpid(), "environment": {key: value for key, value in os.environ.items() if key.startswith("HELM_") or key == "KUBECONFIG"}, "config_mode": stat.S_IMODE(pathlib.Path(config).stat().st_mode) if config and pathlib.Path(config).exists() else None}
with open(os.environ["KUBERICH_HELM_FIXTURE_RECORD"], "a") as stream:
    stream.write(json.dumps(entry) + "\\n")
mode = scenario.get("version_mode", "") if command == "version" else scenario.get(command + "_mode", scenario.get("mode", ""))
if mode == "sleep":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
    pathlib.Path(os.environ["KUBERICH_HELM_FIXTURE_RECORD"] + ".child").write_text(str(child.pid))
    time.sleep(60)
if mode == "overflow":
    sys.stdout.write("x" * (9 * 1024 * 1024))
    sys.stdout.flush()
    time.sleep(60)
if mode == "stderr-overflow":
    sys.stderr.write("x" * (9 * 1024 * 1024))
    sys.stderr.flush()
    time.sleep(60)
if mode == "error":
    sys.stderr.write(scenario.get("error", "sensitive arbitrary failure"))
    sys.exit(1)
if command == "version":
    sys.stdout.write(scenario.get("version", "v3.22.1"))
    sys.exit(0)
if mode == "malformed":
    print("not JSON sensitive arbitrary output")
    sys.exit(0)
revision = scenario.get("revision", 3)
if command == "list":
    print(json.dumps(scenario.get("releases", [{"name": "demo", "namespace": "team", "revision": str(revision), "status": scenario.get("status", "deployed"), "chart": "tiny-0.1.0", "app_version": "1.0", "updated": "2026-11-09 12:00:00 +0000 UTC"}])) )
elif command == "history":
    print(json.dumps([{"revision": number, "status": "deployed" if number == revision else "superseded", "chart": "tiny-0.1.0", "app_version": "1.0", "updated": "2026-11-09T12:00:00Z", "description": "synthetic-private-helm-value"} for number in range(1, revision + 1)]))
elif command == "status":
    selected = int(next(part.split("=", 1)[1] for part in args if part.startswith("--revision=")))
    print(json.dumps({"name": "demo", "namespace": "team", "version": selected, "info": {"status": "deployed" if selected == revision else "superseded", "notes": "synthetic-private-helm-value", "description": "synthetic-private-helm-value", "first_deployed": "2026-11-09T12:00:00Z", "last_deployed": "2026-11-09T12:00:00Z"}, "hooks": [{"name": "rollback-job", "kind": "Job", "events": ["pre-rollback"], "manifest": "synthetic-private-helm-value"}], "config": {"token": "synthetic-private-helm-value"}, "manifest": "synthetic-private-helm-value"}))
elif command == "get":
    if "values" in args:
        print(json.dumps({"ordinary": "synthetic-private-helm-value", "nested": {"count": 3}}))
    elif "manifest" in args:
        print("apiVersion: v1\\nkind: Secret\\nmetadata:\\n  name: demo\\ndata:\\n  token: synthetic-private-helm-value")
    else:
        print("NOTES:\\nsynthetic-private-helm-value")
elif command == "rollback":
    scenario["revision"] = revision + 1
    if mode == "rollback-error":
        scenario["status"] = "failed"
    scenario_path.write_text(json.dumps(scenario))
    if "KUBERICH_HELM_FIXTURE_ROLLBACK_MARKER" in os.environ:
        pathlib.Path(os.environ["KUBERICH_HELM_FIXTURE_ROLLBACK_MARKER"]).write_text(scenario.get("status", "deployed"))
    if mode == "rollback-error":
        sys.stderr.write("hook failed: synthetic-private-helm-value")
        sys.exit(1)
    print("raw rollback body is private")
else:
    sys.exit(2)
"""
    )
    executable.chmod(0o700)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "KUBERICH_HELM_FIXTURE_SCENARIO": str(scenario),
        "KUBERICH_HELM_FIXTURE_RECORD": str(record),
    }
    return HelmSettings(str(executable)), environment, scenario, record


def calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []


class ScriptedHelmAdapter:
    """Service fault injection complements, rather than replaces, actual CLI contracts."""

    def __init__(self, captured: HelmRequest) -> None:
        self.request = captured
        self.identities = tuple(
            HelmStorageIdentity(
                KEY,
                captured.scope.driver,
                rev,
                f"sh.helm.release.v1.demo.v{rev}",
                f"owned-{rev}",
                f"opaque-{rev}",
                "deployed" if rev == 3 else "superseded",
            )
            for rev in (1, 2, 3)
        )
        self.calls: list[str] = []
        self.block: str | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.problem: Exception | None = None
        self.after: object = None
        self.closed = False
        self.rollback_effect = True

    async def step(self, operation, guard):
        guard()
        self.calls.append(operation)
        self.started.set()
        if operation == self.block:
            await self.release.wait()
        if callable(self.after):
            self.after(operation)
        guard()
        if self.problem is not None:
            raise self.problem

    async def list(self, request, guard):
        await self.step("list", guard)
        return HelmList((release(self.identities[-1].revision),), True)

    async def storage_history(self, request, key, guard):
        await self.step("storage-history", guard)
        return self.identities

    async def storage_identity(self, request, key, revision, guard):
        await self.step("storage-get", guard)
        return next(item for item in self.identities if item.revision == revision)

    async def status(self, request, key, revision, guard):
        await self.step("status", guard)
        status = next(item.status for item in self.identities if item.revision == revision)
        return HelmStatus(
            key,
            revision,
            status,
            None,
            None,
            True,
            True,
            (HelmHook("rollback-job", "Job", ("pre-rollback",)),),
        )

    async def history(self, request, key, guard):
        await self.step("history", guard)
        return HelmHistory(
            tuple(
                HelmRevision(item.revision, item.status, "tiny", "1.0", None, True, None)
                for item in self.identities
            ),
            True,
        )

    async def document(self, request, key, revision, kind, disclosed, guard):
        await self.step("document", guard)
        return PRIVATE_VALUE if disclosed else "[REDACTED]"

    async def rollback(self, intent, guard):
        await self.step("rollback", guard)
        if self.rollback_effect:
            last = self.identities[-1]
            self.identities = (
                *self.identities[:-1],
                replace(last, status="superseded"),
                replace(
                    last,
                    revision=last.revision + 1,
                    storage_name=f"sh.helm.release.v1.demo.v{last.revision + 1}",
                    uid="new-revision",
                    resource_version="opaque-new",
                ),
            )

    async def close(self):
        self.closed = True


@asynccontextmanager
async def helm_source(
    directory: Path,
    *,
    real_cli: bool = False,
    read_only: bool = False,
    driver: HelmDriver = HelmDriver.SECRET,
):
    async with metadata_api() as (url, api):
        client = KubernetesSession(catalog_fixture(directory, url).select("kuberich-test-one"), 2)
        await client.open()
        captured = request(driver)
        current = [True]
        policy = AccessPolicy(read_only)
        settings, environment, scenario, record = fake_helm(directory)
        settings = replace(settings, driver=driver)
        environment["KUBERICH_HELM_FIXTURE_ROLLBACK_MARKER"] = str(directory / "rollback-effect")
        api.rollback_marker = directory / "rollback-effect"
        adapter = None if real_cli else ScriptedHelmAdapter(captured)
        service = HelmService(
            client,
            policy,
            settings,
            environment,
            directory,
            lambda value: current[0] and value == captured,
            adapter=adapter,
        )
        try:
            yield service, api, adapter, captured, current, scenario, record
        finally:
            api.release.set()
            if adapter is not None:
                adapter.release.set()
            await service.close()
            await client.close()


@asynccontextmanager
async def adapter_source(directory: Path, **options):
    async with metadata_api() as (url, api):
        client = KubernetesSession(catalog_fixture(directory, url).select("kuberich-test-one"), 2)
        await client.open()
        settings, environment, scenario, record = fake_helm(directory, **options)
        adapter = HelmAdapter(client, AccessPolicy(False), settings, environment, directory)
        try:
            yield adapter, client, api, request(), scenario, record
        finally:
            api.release.set()
            await adapter.close()
            await client.close()
