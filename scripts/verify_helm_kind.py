"""Exercise pinned Helm releases and reviewed rollback in an explicitly owned kind."""

import argparse
import asyncio
import base64
import json
import os
import platform
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client

from kuberich.adapters.helm import HelmAdapter
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import Entry, load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.helm import (
    HelmDocumentKind,
    HelmDriver,
    HelmInspection,
    HelmOutcome,
    HelmProblem,
    HelmReleaseKey,
    HelmRequest,
    HelmRollbackOptions,
    HelmScope,
    HelmSettings,
)
from kuberich.domain.helm_cli import helm_environment, parse_helm_history, parse_helm_list
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from scripts.diagnostics_tools import KIND_SHA256
from scripts.helm_tools import HELM_PINS, HelmPin, sha256_file, verify_helm_binary
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

RELEASE = "owned-demo"
PASSWORD = "synthetic-supplied-password"
VERIFY_SECONDS = 900


def input_hashes(root: Path) -> dict[str, str]:
    paths = {
        root / "scripts/verify_helm_kind.py",
        root / "scripts/helm_tools.py",
        root / "scripts/owned_kind.py",
        root / "uv.lock",
        root / "pyproject.toml",
        *(root / "src/kuberich").rglob("*.py"),
        *(root / "tests/fixtures/helm/tiny-chart").rglob("*"),
    }
    return {
        str(path.relative_to(root)): sha256_file(path) for path in sorted(paths) if path.is_file()
    }


async def fixture_command(
    binary: Path,
    cluster: OwnedCluster,
    environment: dict[str, str],
    namespace: str,
    *arguments: str,
) -> bytes:
    """Install/upgrade/uninstall are fixture preparation, not application features."""
    command = capture_command(
        (
            str(binary),
            *arguments,
            "--kubeconfig=" + str(cluster.path),
            "--kube-context=" + cluster.context,
            "--namespace=" + namespace,
            "--debug=false",
        ),
        environment=environment,
        directory=cluster.directory,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.HELM_READ
        if arguments[0] in {"list", "history"}
        else ProcessPurpose.HELM_MUTATE,
    )
    async with ProcessRunner(AccessPolicy(False)) as runner:
        result = await runner.capture(command, timeout=120)
    if result.status is not ProcessStatus.SUCCEEDED:
        raise AssertionError("Owned Helm fixture command failed: " + arguments[0])
    return result.stdout


async def inspection(
    service: HelmService, request: HelmRequest, namespace: str, *, name: str = RELEASE
) -> HelmInspection:
    listing = await service.list(request)
    assert listing.complete
    release = next(row for row in listing.releases if row.key == HelmReleaseKey(namespace, name))
    return await service.inspect(request, release)


async def verify_forbidden_storage(
    cluster: OwnedCluster,
    connection: KubernetesSession,
    request: ConnectionRequest,
    captured: HelmRequest,
    settings: HelmSettings,
    environment: dict[str, str],
    home: Path,
    namespace: str,
) -> None:
    """An actual list-only identity cannot substitute list permission for revision GET."""
    assert connection.api is not None
    core, rbac = client.CoreV1Api(connection.api), client.RbacAuthorizationV1Api(connection.api)
    name = "helm-list-only"
    metadata = client.V1ObjectMeta(name=name)
    resource = "secrets" if settings.driver is HelmDriver.SECRET else "configmaps"
    await core.create_namespaced_service_account(
        namespace, client.V1ServiceAccount(metadata=metadata)
    )
    await rbac.create_namespaced_role(
        namespace,
        client.V1Role(
            metadata=metadata,
            rules=[client.V1PolicyRule(api_groups=[""], resources=[resource], verbs=["list"])],
        ),
    )
    await rbac.create_namespaced_role_binding(
        namespace,
        client.V1RoleBinding(
            metadata=metadata,
            role_ref=client.V1RoleRef(
                api_group="rbac.authorization.k8s.io", kind="Role", name=name
            ),
            subjects=[client.RbacV1Subject(kind="ServiceAccount", name=name, namespace=namespace)],
        ),
    )
    issued = await core.create_namespaced_service_account_token(
        name,
        namespace,
        client.AuthenticationV1TokenRequest(
            spec=client.V1TokenRequestSpec(audiences=[], expiration_seconds=600)
        ),
    )
    catalog = load_catalog(request, {})
    catalog.users[name] = Entry({"token": issued.status.token}, home)
    catalog.contexts[cluster.context].data["user"] = name
    restricted = KubernetesSession(catalog.select(cluster.context), timeout=15)
    adapter = HelmAdapter(restricted, AccessPolicy(True), settings, environment, home)
    scoped = HelmRequest(HelmScope(captured.scope.session, namespace, settings.driver), 1)
    try:
        await restricted.open()
        async with asyncio.timeout(10):
            while True:
                try:
                    records = await adapter.storage_history(
                        scoped, HelmReleaseKey(namespace, RELEASE), lambda: None
                    )
                    break
                except HelmProblem as error:
                    if error.kind != "forbidden":
                        raise
                    await asyncio.sleep(0.05)
        assert records
        try:
            await adapter.storage_identity(
                scoped, HelmReleaseKey(namespace, RELEASE), 3, lambda: None
            )
        except HelmProblem as error:
            assert error.kind == "forbidden"
        else:
            raise AssertionError("List-only storage identity unexpectedly permits exact GET")
    finally:
        await adapter.close()
        await restricted.close()


async def verify_case(
    cluster: OwnedCluster,
    root: Path,
    binary: Path,
    pin: HelmPin,
    driver: HelmDriver,
    fixture_directory: Path,
) -> dict[str, Any]:
    namespace = f"owned-helm-{pin.version[1]}-{driver.value}"
    other_namespace = namespace + "-other"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    sessions = SessionService(load_catalog(request, {}), request)
    owners: list[HelmService] = []
    home = cluster.directory / namespace
    home.mkdir(mode=0o700)
    # Deliberately hostile ambient Helm destination/auth overrides must not reach either process.
    ambient = {
        "PATH": os.defpath,
        "HOME": str(home),
        "HELM_DRIVER": driver.value,
        "HELM_KUBEAPISERVER": "https://127.0.0.1:1",
        "HELM_KUBETOKEN": "synthetic-incorrect-token",
        "HELM_NAMESPACE": "wrong-namespace",
        "HELM_DEBUG": "true",
        "HELM_MAX_HISTORY": "1",
    }
    environment = dict(helm_environment(ambient, driver, cluster.path))
    chart = root / "tests/fixtures/helm/tiny-chart"
    checks: list[str] = []

    def record(check: str) -> None:
        checks.append(check)
        print(f"{pin.version}/{driver.value}: {check}", flush=True)

    try:
        await sessions.connect(cluster.context)
        connection, identity = sessions.client, sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        core, batch = client.CoreV1Api(connection.api), client.BatchV1Api(connection.api)
        for name in (namespace, other_namespace):
            await core.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=name)))
        for ordinal, color, fail, delay in (
            (1, "blue", "false", "0"),
            (2, "green", "true", "0"),
            (3, "red", "false", "10"),
        ):
            await fixture_command(
                binary,
                cluster,
                environment,
                namespace,
                "install" if ordinal == 1 else "upgrade",
                RELEASE,
                str(chart),
                "--set-string=color=" + color,
                "--set-string=credentials.password=" + PASSWORD,
                "--set=rollbackHooks.fail=" + fail,
                "--set=rollbackHooks.sleepSeconds=" + delay,
                "--history-max=0" if ordinal != 1 else "--wait=false",
            )
        await fixture_command(
            binary, cluster, environment, other_namespace, "install", RELEASE, str(chart)
        )
        fixtures = fixture_directory / (pin.version + "-" + driver.value)
        fixtures.mkdir(parents=True, exist_ok=False)
        fixture_receipts = []
        for label, arguments in (
            (
                "list",
                (
                    "list",
                    *(("--all",) if pin.version.startswith("v3.") else ()),
                    "--max=501",
                    "--offset=0",
                    "--output=json",
                ),
            ),
            ("history", ("history", RELEASE, "--max=201", "--output=json")),
        ):
            data = await fixture_command(binary, cluster, environment, namespace, *arguments)
            assert PASSWORD.encode() not in data
            path = fixtures / (label + ".json")
            with path.open("xb") as output:
                output.write(data)
            if label == "list":
                parsed = parse_helm_list(data, HelmScope(identity, namespace, driver))
                assert len(parsed.releases) == 1 and parsed.releases[0].revision == 3
            else:
                assert [row.revision for row in parse_helm_history(data).revisions] == [3, 2, 1]
            fixture_receipts.append(
                {
                    "kind": label,
                    "argv": list(arguments),
                    "bytes": len(data),
                    "sha256": sha256_file(path),
                }
            )
        (fixtures / "provenance.json").write_text(
            json.dumps(
                {
                    "origin": "Actual owned tiny-chart CLI output; not hand-authored or an upstream golden fixture.",
                    "version": pin.version,
                    "driver": driver.value,
                    "binary_sha256": pin.binary_sha256,
                    "fixtures": fixture_receipts,
                },
                indent=2,
            )
            + "\n"
        )
        settings = HelmSettings(str(binary), driver)
        captured = HelmRequest(HelmScope(identity, None, driver), 1)

        def current(candidate: HelmRequest) -> bool:
            return candidate == captured and sessions.client is connection

        service = HelmService(connection, AccessPolicy(False), settings, ambient, home, current)
        owners.append(service)
        listing = await service.list(captured)
        assert listing.complete
        assert {row.key.namespace for row in listing.releases if row.key.name == RELEASE} >= {
            namespace,
            other_namespace,
        }
        initial = await inspection(service, captured, namespace)
        assert initial.release.revision == 3
        assert [row.revision for row in initial.history.revisions] == [3, 2, 1]
        assert initial.status.notes_present and initial.status.hooks
        checks.extend(
            [
                "all-namespace-duplicate-names",
                "three-actual-storage-revisions",
                "status-metadata-only",
            ]
        )

        for kind in HelmDocumentKind:
            hidden = await service.document(initial.target, 1, kind)
            assert not hidden.disclosed and PASSWORD not in hidden.text
            disclosure = await service.prepare_disclosure(initial.target, 1, kind)
            approval = service.confirm(disclosure)
            revealed = await service.disclose(approval)
            assert revealed.disclosed and PASSWORD in revealed.text
            if kind is HelmDocumentKind.VALUES:
                assert "computed-default" not in revealed.text
            if kind is HelmDocumentKind.ALL_VALUES:
                assert "computed-default" in revealed.text
            try:
                await service.disclose(approval)
            except HelmProblem as error:
                assert error.kind == "stale"
            else:
                raise AssertionError("Disclosure approval replay was accepted")
            record("redacted-and-one-use-disclosed-" + kind.value)

        readonly = HelmService(connection, AccessPolicy(True), settings, ambient, home, current)
        owners.append(readonly)
        read_inspection = await inspection(readonly, captured, namespace)
        try:
            await readonly.prepare_rollback(read_inspection.target, 1, HelmRollbackOptions())
        except AppError:
            pass
        else:
            raise AssertionError("Read-only rollback was accepted")
        assert (await inspection(service, captured, namespace)).release.revision == 3
        record("read-only-no-revision-or-resource-change")
        await verify_forbidden_storage(
            cluster, connection, request, captured, settings, ambient, home, namespace
        )
        record("actual-list-only-rbac-refuses-exact-storage-metadata-get")

        intent = await service.prepare_rollback(initial.target, 1, HelmRollbackOptions())
        result = await service.rollback(service.confirm(intent))
        assert result.outcome is HelmOutcome.SUCCEEDED and result.observed is not None
        assert result.observed.revision == 4
        configmap = await core.read_namespaced_config_map(RELEASE + "-fixture", namespace)
        secret = await core.read_namespaced_secret(RELEASE + "-fixture", namespace)
        assert configmap.data["color"] == "blue"
        assert base64.b64decode(secret.data["password"]).decode() == PASSWORD
        assert not (await batch.list_namespaced_job(namespace)).items
        record("actual-rollback-to-one-observed-revision-four-hooks-disabled")

        latest = await inspection(service, captured, namespace)
        hook_intent = await service.prepare_rollback(
            latest.target, 1, HelmRollbackOptions(run_hooks=True, timeout_seconds=60)
        )
        hook_result = await service.rollback(service.confirm(hook_intent))
        assert hook_result.outcome is HelmOutcome.SUCCEEDED and hook_result.observed is not None
        assert hook_result.observed.revision == 5
        jobs = (await batch.list_namespaced_job(namespace)).items
        assert {job.metadata.name for job in jobs} == {
            RELEASE + "-pre-rollback",
            RELEASE + "-post-rollback",
        }
        assert all(job.status.succeeded == 1 for job in jobs)
        record("reviewed-enabled-pre-and-post-rollback-hooks-actually-completed")

        latest = await inspection(service, captured, namespace)
        stale = await service.prepare_rollback(latest.target, 1, HelmRollbackOptions())
        approval = service.confirm(stale)
        storage_path = f"/api/v1/namespaces/{namespace}/{'secrets' if driver is HelmDriver.SECRET else 'configmaps'}"
        stored = await connection.get_json(storage_path + "/" + stale.selected.storage_name)
        # Replace one actual owned revision object under the same name; new UID must invalidate approval.
        await connection.api.call_api(
            storage_path + "/" + stale.selected.storage_name,
            "DELETE",
            response_types_map={"200": "object", "202": "object"},
            auth_settings=["BearerToken"],
            _return_http_data_only=True,
        )
        metadata = stored["metadata"]
        for key in ("uid", "resourceVersion", "creationTimestamp", "managedFields"):
            metadata.pop(key, None)
        await connection.api.call_api(
            storage_path,
            "POST",
            body=stored,
            response_types_map={"201": "object"},
            header_params={"Content-Type": "application/json"},
            auth_settings=["BearerToken"],
            _return_http_data_only=True,
        )
        stale_result = await service.rollback(approval)
        assert stale_result.outcome is HelmOutcome.STALE and not stale_result.may_have_started
        assert (await inspection(service, captured, namespace)).release.revision == 5
        record("same-name-recreated-revision-refused-before-write")

        latest = await inspection(service, captured, namespace)
        failure = await service.prepare_rollback(
            latest.target, 2, HelmRollbackOptions(run_hooks=True, timeout_seconds=60)
        )
        failed = await service.rollback(service.confirm(failure))
        # Upstream records the new revision before hooks; an early hook error leaves it pending.
        pending = await inspection(service, captured, namespace)
        assert failed.outcome is HelmOutcome.UNKNOWN and failed.may_have_started
        assert pending.release.revision == 6 and pending.release.status == "pending-rollback"
        jobs = (await batch.list_namespaced_job(namespace)).items
        assert any(
            job.metadata.name == RELEASE + "-pre-rollback" and job.status.failed for job in jobs
        )
        try:
            await service.prepare_rollback(pending.target, 1, HelmRollbackOptions())
        except HelmProblem:
            pass
        else:
            raise AssertionError("Pending release incorrectly permits another rollback")
        record("actual-failed-pre-hook-pending-revision-and-no-automatic-retry")

        for name in ("owned-timeout", "owned-cancel"):
            await fixture_command(
                binary,
                cluster,
                environment,
                namespace,
                "install",
                name,
                str(chart),
                "--set=rollbackHooks.sleepSeconds=10",
            )
            await fixture_command(
                binary,
                cluster,
                environment,
                namespace,
                "upgrade",
                name,
                str(chart),
                "--set=rollbackHooks.sleepSeconds=0",
                "--history-max=0",
            )
            selected = await inspection(service, captured, namespace, name=name)
            prepared = await service.prepare_rollback(
                selected.target,
                1,
                HelmRollbackOptions(
                    run_hooks=True, timeout_seconds=1 if name == "owned-timeout" else 60
                ),
            )
            proof = service.confirm(prepared)
            if name == "owned-timeout":
                timed_out = await service.rollback(proof)
                assert timed_out.outcome is HelmOutcome.UNKNOWN and timed_out.may_have_started
                observed = await inspection(service, captured, namespace, name=name)
                assert (
                    observed.release.revision == 3 and observed.release.status == "pending-rollback"
                )
                record("actual-helm-hook-timeout-keeps-outcome-uncertain")
            else:
                operation = asyncio.create_task(service.rollback(proof))
                try:
                    async with asyncio.timeout(30):
                        while not (
                            await batch.list_namespaced_job(
                                namespace, label_selector="kuberich.io/owned-helm-hook=" + name
                            )
                        ).items:
                            await asyncio.sleep(0.05)
                    operation.cancel()
                    try:
                        await operation
                    except asyncio.CancelledError:
                        pass
                    else:
                        raise AssertionError("Launched rollback cancellation was suppressed")
                finally:
                    if not operation.done():
                        operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                assert service.last_rollback is not None
                assert (
                    service.last_rollback.outcome is HelmOutcome.UNKNOWN
                    and service.last_rollback.may_have_started
                )
                assert service.operation_count == 0
                observed = await inspection(service, captured, namespace, name=name)
                assert observed.release.revision == 3
                record("actual-launched-rollback-cancellation-drains-and-records-uncertainty")
        await fixture_command(
            binary,
            cluster,
            environment,
            namespace,
            "install",
            "owned-readiness",
            str(chart),
            "--set=readinessJob.enabled=true",
            "--set-string=color=blue",
        )
        await fixture_command(
            binary,
            cluster,
            environment,
            namespace,
            "upgrade",
            "owned-readiness",
            str(chart),
            "--set=readinessJob.enabled=false",
            "--set-string=color=red",
            "--history-max=0",
        )
        selected = await inspection(service, captured, namespace, name="owned-readiness")
        prepared = await service.prepare_rollback(
            selected.target, 1, HelmRollbackOptions(timeout_seconds=60)
        )
        completed_failure = await service.rollback(service.confirm(prepared))
        assert (
            completed_failure.outcome is HelmOutcome.FAILED and completed_failure.may_have_started
        )
        assert completed_failure.observed is not None and completed_failure.observed.revision == 3
        assert completed_failure.observed.status == "failed"
        configmap = await core.read_namespaced_config_map("owned-readiness-fixture", namespace)
        assert configmap.data["color"] == "blue"
        record(
            "actual-completed-wait-failure-observed-failed-revision-and-partial-resource-effects"
        )
        assert not list(Path(connection.directory.name).glob("helm-*"))
        return {
            "version": pin.version,
            "driver": driver.value,
            "tool": asdict(pin),
            "checks": checks,
        }
    finally:
        for owner in reversed(owners):
            await owner.close()
            assert owner.operation_count == 0
        await sessions.close()


async def verify(
    cluster: OwnedCluster, root: Path, binaries: tuple[Path, ...], fixture_directory: Path
) -> list[dict[str, Any]]:
    before = cluster.path.read_bytes()
    results = []
    async with asyncio.timeout(VERIFY_SECONDS):
        for pin, binary in zip(HELM_PINS, binaries, strict=True):
            for driver in HelmDriver:
                print(f"Verifying {pin.version} / {driver.value}", flush=True)
                results.append(
                    await verify_case(cluster, root, binary, pin, driver, fixture_directory)
                )
    assert cluster.path.read_bytes() == before
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", type=Path, required=True)
    parser.add_argument("--helm3", type=Path, required=True)
    parser.add_argument("--helm4", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("This owned qualification requires Linux amd64.")
    if not args.kind.is_absolute() or sha256_file(args.kind) != KIND_SHA256:
        raise ValueError("Use the pinned official Linux amd64 kind v0.33.0 fixture.")
    binaries = (args.helm3, args.helm4)
    for pin, binary in zip(HELM_PINS, binaries, strict=True):
        verify_helm_binary(binary, pin)
    root = Path(__file__).resolve().parent.parent
    inputs = input_hashes(root)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    if args.evidence.exists():
        raise ValueError("Use a fresh evidence path; previous results are immutable.")
    report: dict[str, Any] = {
        "status": "in-progress",
        "inputs": inputs,
        "node_image": NODE_IMAGE,
        "hook_image": SHELL_IMAGE,
        "scope": "Owned local kind only; no provider or native-platform certification.",
    }
    try:
        with owned_cluster(str(args.kind), docker=args.docker) as cluster:
            report["cases"] = asyncio.run(
                verify(cluster, root, binaries, args.evidence.parent / "cli-fixtures")
            )
        report["owned_cluster_deleted"] = True
        if input_hashes(root) != inputs:
            raise AssertionError("Measured Helm inputs changed during verification")
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        raise
    finally:
        args.evidence.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "cases": len(report["cases"]),
                "evidence": str(args.evidence),
            }
        )
    )


if __name__ == "__main__":
    main()
