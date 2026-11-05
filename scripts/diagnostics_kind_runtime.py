"""Contained actual-API/runtime body for verify_diagnostics_kind; no ambient contexts."""

import argparse
import asyncio
import hashlib
import json
import os
import pwd
import sys
import traceback
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.config.popeye import PopeyeSettings
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.cluster_diagnostics import (
    DiagnosticCategory,
    DiagnosticIdentity,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSnapshot,
    DiagnosticSourceKind,
    DiagnosticStatus,
    diagnostic_text_bytes,
)
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.logs import LogLine, LogOptions
from kuberich.domain.popeye import POPEYE_PARSER_ID, parse_popeye_report, parse_popeye_version
from kuberich.domain.processes import ProcessCommand, ProcessResult
from kuberich.domain.relationships import RelationshipRef, reference_for
from kuberich.domain.resources import Discovery
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services import popeye as popeye_module
from kuberich.services.access import AccessPolicy
from kuberich.services.cluster_diagnostics import DiagnosticService
from kuberich.services.diagnostic_workspace import DiagnosticWorkspace
from kuberich.services.logs import LogStream
from kuberich.services.ownership import finish_owned
from kuberich.services.popeye import PopeyeResult, PopeyeService
from kuberich.services.processes import ProcessRunner, TargetGuard
from kuberich.services.resources import ResourceReader
from scripts.diagnostics_tools import (
    POPEYE_BINARY_SHA256,
    POPEYE_COMMIT,
    tool_provenance,
    verify_popeye_binary,
)
from scripts.owned_kind import SHELL_IMAGE

NAMESPACE = "kuberich-owned-diagnostic-a"
OTHER_NAMESPACE = "kuberich-owned-diagnostic-b"
ACCOUNT = "owned-reader"
IMAGE_POD = "owned-image"
SCHEDULING_POD = "owned-scheduling"
CRASH_POD = "owned-crash"
READY_POD = "owned-readiness"
VOLUME_POD = "owned-volume"
CLAIM_POD = "owned-claim"
CLAIM = "owned-pending-claim"
CANONICAL = frozenset(
    {
        DiagnosticCategory.IMAGE_PULL,
        DiagnosticCategory.SCHEDULING,
        DiagnosticCategory.CRASH_LOOP,
        DiagnosticCategory.READINESS,
        DiagnosticCategory.VOLUME,
    }
)


def fixtures() -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []

    def add(kind: str, name: str, namespace: str | None = None, **fields: Any) -> dict[str, Any]:
        group = (
            "rbac.authorization.k8s.io/v1"
            if kind in {"Role", "RoleBinding"}
            else "apps/v1"
            if kind == "Deployment"
            else "batch/v1"
            if kind in {"Job", "CronJob"}
            else "v1"
        )
        value = {
            "apiVersion": group,
            "kind": kind,
            "metadata": {"name": name, **({"namespace": namespace} if namespace else {})},
            **fields,
        }
        result.append(value)
        return value

    def spec(command: list[str] | None = None, **fields: Any) -> dict[str, Any]:
        return {
            "automountServiceAccountToken": False,
            "terminationGracePeriodSeconds": 0,
            "containers": [
                {
                    "name": "app",
                    "image": SHELL_IMAGE,
                    "imagePullPolicy": "IfNotPresent",
                    "command": command or ["sh", "-c", "echo kuberich-owned-current; sleep 3600"],
                }
            ],
            **fields,
        }

    for namespace in (NAMESPACE, OTHER_NAMESPACE):
        add("Namespace", namespace)
        add(
            "Pod",
            SCHEDULING_POD,
            namespace,
            spec=spec(nodeSelector={"kuberich.invalid/unsatisfiable": "true"}),
        )
    image = spec()
    image["containers"][0].update(
        image="registry.invalid/kuberich-owned/absent:never", imagePullPolicy="Always"
    )
    add("Pod", IMAGE_POD, NAMESPACE, spec=image)
    add(
        "Pod",
        CRASH_POD,
        NAMESPACE,
        spec=spec(["sh", "-c", "echo kuberich-owned-previous; sleep 1; exit 23"]),
    )
    readiness = spec()
    readiness["containers"][0]["readinessProbe"] = {
        "exec": {"command": ["sh", "-c", "exit 1"]},
        "periodSeconds": 1,
        "failureThreshold": 1,
    }
    add("Pod", READY_POD, NAMESPACE, spec=readiness)
    mount = spec(volumes=[{"name": "missing", "configMap": {"name": "owned-missing-config"}}])
    mount["containers"][0]["volumeMounts"] = [{"name": "missing", "mountPath": "/fixture"}]
    add("Pod", VOLUME_POD, NAMESPACE, spec=mount)
    add(
        "PersistentVolumeClaim",
        CLAIM,
        NAMESPACE,
        spec={
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "owned-unavailable-class",
            "resources": {"requests": {"storage": "1Mi"}},
        },
    )
    add(
        "Pod",
        CLAIM_POD,
        NAMESPACE,
        spec=spec(volumes=[{"name": "claim", "persistentVolumeClaim": {"claimName": CLAIM}}]),
    )
    add("ServiceAccount", ACCOUNT, NAMESPACE, automountServiceAccountToken=False)
    add(
        "Role",
        ACCOUNT,
        NAMESPACE,
        rules=[{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}],
    )
    add(
        "RoleBinding",
        ACCOUNT,
        NAMESPACE,
        roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": ACCOUNT},
        subjects=[{"kind": "ServiceAccount", "name": ACCOUNT, "namespace": NAMESPACE}],
    )
    add(
        "Deployment",
        "owned-deployment",
        NAMESPACE,
        spec={
            "replicas": 1,
            "selector": {"matchLabels": {"owned-diagnostics": "deployment"}},
            "template": {
                "metadata": {"labels": {"owned-diagnostics": "deployment"}},
                "spec": spec(nodeSelector={"kuberich.invalid/unsatisfiable": "true"}),
            },
        },
    )
    add(
        "Job",
        "owned-job",
        NAMESPACE,
        spec={
            "template": {
                "spec": spec(
                    restartPolicy="Never", nodeSelector={"kuberich.invalid/unsatisfiable": "true"}
                )
            }
        },
    )
    add(
        "CronJob",
        "owned-cron",
        NAMESPACE,
        spec={
            "schedule": "* * * * *",
            "suspend": False,
            "jobTemplate": {
                "spec": {
                    "template": {
                        "spec": spec(
                            restartPolicy="Never",
                            nodeSelector={"kuberich.invalid/unsatisfiable": "true"},
                        )
                    }
                }
            },
        },
    )
    return tuple(result)


def snapshot_receipt(snapshot: DiagnosticSnapshot) -> dict[str, Any]:
    return {
        "native_requests_used": snapshot.native_requests_used,
        "text_bytes": diagnostic_text_bytes(snapshot),
        "findings": [
            {
                "key": finding.key,
                "category": finding.category.value,
                "severity": finding.severity.value,
                "namespace": finding.subject.namespace if finding.subject else None,
                "name": finding.subject.name if finding.subject else None,
                "uid": finding.subject.uid if finding.subject else None,
                "source": finding.source.value,
                "identity": finding.identity.value,
                "container": finding.container,
                "evidence": [
                    {
                        "name": item.ref.name,
                        "uid": item.ref.uid,
                        "field": item.field_path,
                        "reason": item.reason,
                    }
                    for item in finding.evidence
                ],
            }
            for finding in snapshot.findings
        ],
        "sources": [
            {
                "kind": source.kind.value,
                "resource": source.resource.name if source.resource else None,
                "status": source.status.value,
                "detail": source.detail,
                "omitted_findings": source.omitted_findings,
            }
            for source in snapshot.sources
        ],
    }


async def until(operation: Callable[[], Awaitable[bool]], seconds: float = 150) -> None:
    async with asyncio.timeout(seconds):
        while not await operation():
            await asyncio.sleep(0.1)


async def wait_for_canonical_snapshot(
    collect: Callable[[], Awaitable[DiagnosticSnapshot]],
    retain: Callable[[DiagnosticSnapshot], None],
    *,
    seconds: float = 150,
) -> DiagnosticSnapshot:
    """Wait on one completed native observation; do not combine volatile snapshots.

    Retain before evaluating readiness so a failed requirement keeps the actual
    finding categories and source statuses that were tested, rather than an
    earlier independent Pod GET that may already describe a different instance.
    """
    async with asyncio.timeout(seconds):
        while True:
            snapshot = await collect()
            retain(snapshot)
            if (
                not snapshot.collecting
                and {item.category for item in snapshot.findings} >= CANONICAL
            ):
                return snapshot
            await asyncio.sleep(0.1)


async def qualify(kubeconfig: Path, context: str, binary: Path, evidence: Path) -> dict[str, Any]:
    verify_popeye_binary(binary)
    account = pwd.getpwuid(os.getuid())
    assert (
        account.pw_name == "popeye-owned"
        and account.pw_dir == "/owned/home"
        and os.environ["HOME"] == "/owned/home"
    )
    assert not (Path("/owned/home") / ".kube").exists()
    connection = ConnectionRequest(
        kubeconfig=str(kubeconfig), context=context, namespace=NAMESPACE, timeout=10
    )
    catalog = load_catalog(connection, {})
    admin = KubernetesSession(catalog.select(context), 10)
    clients = [admin]
    private_paths = [Path(admin.directory.name)]
    workspace = DiagnosticWorkspace()
    services: list[PopeyeService] = []
    publications: deque[DiagnosticSnapshot] = deque(maxlen=128)
    stages: list[dict[str, Any]] = []
    checks: list[str] = []
    result: dict[str, Any] = {
        "status": "failed",
        "checks": checks,
        "popeye_binary_sha256": POPEYE_BINARY_SHA256,
        "runtime_python": sys.version,
        "os_user_home": account.pw_dir,
        "external_api_reads": "unknown; outside native64",
        "client_files_deleted": False,
    }

    def stage(name: str, **values: Any) -> None:
        record = {"stage": name, "observed_at": datetime.now(UTC).isoformat(), **values}
        stages.append(record)
        with (evidence / "diagnostics-stages.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        print("Diagnostics stage: " + name, flush=True)

    async def write(path: str, body: dict[str, Any], method: str = "POST") -> Any:
        assert admin.api is not None
        return await admin.api.call_api(
            path,
            method,
            body=body,
            response_types_map={200: "object", 201: "object", 202: "object"},
            auth_settings=["BearerToken"],
            header_params={"Content-Type": "application/json"},
            _return_http_data_only=True,
            _request_timeout=10,
        )

    async def native(
        discovery: Discovery, session: KubernetesSession, scope: DiagnosticScope
    ) -> DiagnosticSnapshot:
        request = workspace.prepare(scope)
        await workspace.stop()
        service = DiagnosticService(
            ResourceReader(session),
            discovery,
            AccessPolicy(True),
            lambda candidate: candidate == workspace.request,
            now=lambda: datetime.now(UTC),
        )
        workspace.start(request, service.collect, publications.append)
        task = workspace.task
        assert task is not None
        await task
        snapshot = workspace.snapshot
        assert snapshot is not None and snapshot.request == request and not snapshot.collecting
        assert (
            snapshot.native_requests_used <= 64
            and diagnostic_text_bytes(snapshot) <= 2 * 1024 * 1024
        )
        return snapshot

    try:
        async with asyncio.timeout(540):
            await admin.open()
            endpoint = urlsplit(admin.configuration.host if admin.configuration is not None else "")
            assert endpoint.scheme == "https" and endpoint.hostname == "127.0.0.1" and endpoint.port
            reader = ResourceReader(admin)
            discovery = await reader.discover()
            pods, events = discovery.find("pods"), discovery.find("events")
            identity = SessionIdentity(context, 1)
            stage("creating-only-owned-synthetic-fixtures")
            for manifest in fixtures():
                resource = next(
                    item
                    for item in discovery.resources
                    if item.kind == manifest["kind"] and item.api_version == manifest["apiVersion"]
                )
                await write(resource.path(manifest["metadata"].get("namespace")), manifest)

            async def collect_five() -> DiagnosticSnapshot:
                return await native(discovery, admin, DiagnosticScope(identity, NAMESPACE))

            def retain_five(observation: DiagnosticSnapshot) -> None:
                result["native_five"] = snapshot_receipt(observation)

            stage("waiting-for-actual-five-category-native-snapshot")
            snapshot = await wait_for_canonical_snapshot(collect_five, retain_five)
            assert {item.category for item in snapshot.findings} >= CANONICAL
            assert all(
                item.subject is None or item.subject.namespace == NAMESPACE
                for item in snapshot.findings
            )
            assert any(
                item.source is DiagnosticSourceKind.EVENT
                for row in snapshot.findings
                for item in row.evidence
            )
            result["native_five"] = snapshot_receipt(snapshot)
            checks.append("actual-image-pull-scheduling-crash-readiness-volume-and-uid-events")
            stage(
                "native-five-categories-qualified",
                categories=sorted(category.value for category in CANONICAL),
                native_requests_used=snapshot.native_requests_used,
            )

            logs: dict[str, list[str]] = {}
            for name, previous, marker in (
                (CRASH_POD, True, "kuberich-owned-previous"),
                (READY_POD, False, "kuberich-owned-current"),
            ):
                record = await reader.get(pods, name, NAMESPACE)
                target = ResourceTarget(
                    identity, "", "pods", NAMESPACE, name, record.uid or "", "app"
                )
                lines: list[str] = []

                async def sink(line: LogLine, captured: list[str] = lines) -> None:
                    captured.append(line.text)

                await LogStream(admin, target, AccessPolicy(True), lambda: True).run(
                    LogOptions(previous=previous, follow=False, tail_lines=20), sink
                )
                assert marker in "\n".join(lines)
                logs[name] = lines
            result["logs"] = logs
            checks.append("actual-uid-checked-previous-crash-and-current-readiness-logs")

            for family, name, expected_kind in (
                ("deployments", "owned-deployment", "Pod"),
                ("jobs", "owned-job", "Pod"),
                ("cronjobs", "owned-cron", "Pod"),
            ):
                resource = discovery.find(
                    family, group="apps" if family == "deployments" else "batch"
                )
                root_record = await reader.get(resource, name, NAMESPACE)
                root_ref = reference_for(resource, root_record)

                async def owned_children(
                    root: RelationshipRef = root_ref, kind: str = expected_kind
                ) -> bool:
                    observed = await native(
                        discovery, admin, DiagnosticScope(identity, NAMESPACE, root)
                    )
                    return any(
                        item.subject is not None
                        and item.subject.kind == kind
                        and item.category is DiagnosticCategory.SCHEDULING
                        for item in observed.findings
                    )

                await until(owned_children, 90 if family == "cronjobs" else 30)
                observed = workspace.snapshot
                assert observed is not None and all(
                    item.subject is None or item.subject.namespace == NAMESPACE
                    for item in observed.findings
                )
                result["root_" + family] = snapshot_receipt(observed)
            checks.append(
                "actual-deployment-replicaset-pod-job-pod-and-cronjob-job-pod-controller-membership"
            )

            issued = await write(
                discovery.find("serviceaccounts").path(NAMESPACE) + "/" + ACCOUNT + "/token",
                {
                    "apiVersion": "authentication.k8s.io/v1",
                    "kind": "TokenRequest",
                    "spec": {"audiences": [], "expirationSeconds": 600},
                },
            )
            token = issued["status"]["token"]
            assert isinstance(token, str) and token
            restricted = KubernetesSession(
                catalog.select(context, ConnectionOverrides(token=token)), 10
            )
            clients.append(restricted)
            private_paths.append(Path(restricted.directory.name))
            await restricted.open()

            # Allow RBAC propagation, retaining only safe status/identity receipts.
            async def permitted_pods() -> bool:
                try:
                    await ResourceReader(restricted).get(pods, CLAIM_POD, NAMESPACE)
                except HttpProblem as error:
                    if error.status == 403:
                        return False
                    raise
                return True

            await until(permitted_pods, 15)
            claim_record = await reader.get(pods, CLAIM_POD, NAMESPACE)
            denied = await native(
                discovery,
                restricted,
                DiagnosticScope(
                    SessionIdentity(context, 2), NAMESPACE, reference_for(pods, claim_record)
                ),
            )
            assert any(
                source.status is DiagnosticStatus.FORBIDDEN
                and source.kind is DiagnosticSourceKind.EVENT
                for source in denied.sources
            )
            assert any(
                source.status is DiagnosticStatus.FORBIDDEN
                and source.resource is not None
                and source.resource.name == "persistentvolumeclaims"
                for source in denied.sources
            )
            result["native_denied"] = snapshot_receipt(denied)
            checks.append("actual-event-and-pvc403-remain-distinct-from-empty-success")
            stage("actual-native-denied-sources-qualified")

            captures: list[tuple[ProcessCommand, ProcessResult]] = []

            class CaptureRunner(ProcessRunner):
                async def capture(
                    self,
                    command: ProcessCommand,
                    *,
                    timeout: float = 30,
                    guard: TargetGuard | None = None,
                ) -> ProcessResult:
                    value = await super().capture(command, timeout=timeout, guard=guard)
                    captures.append((command, value))
                    return value

            popeye_receipts: list[dict[str, Any]] = []
            with patch.object(popeye_module, "ProcessRunner", CaptureRunner):
                for label, selected_client, namespace in (
                    ("namespace-a", admin, NAMESPACE),
                    ("namespace-b", admin, OTHER_NAMESPACE),
                    ("all", admin, None),
                    ("restricted", restricted, NAMESPACE),
                ):
                    scope = DiagnosticScope(
                        SessionIdentity(context, 10 + len(popeye_receipts)), namespace
                    )
                    before_native = len(captures)
                    baseline = await native(discovery, selected_client, scope)
                    assert (
                        len(captures) == before_native
                    )  # Native refresh never runs an external tool.
                    request = workspace.prepare(scope, producer="popeye")
                    await workspace.stop()
                    limits = (
                        workspace.remaining_findings,
                        workspace.remaining_text_bytes,
                        workspace.remaining_source_text_bytes,
                    )

                    def current(
                        candidate: DiagnosticRequest, captured: DiagnosticRequest = request
                    ) -> bool:
                        return candidate == captured and workspace.request == captured

                    service = PopeyeService(
                        selected_client,
                        AccessPolicy(True),
                        PopeyeSettings(binary, trusted_read_only=True),
                        dict(os.environ),
                        Path("/owned/home"),
                        current,
                        discovery=discovery,
                    )
                    services.append(service)
                    before = len(captures)
                    stage("running-official-popeye-" + label)
                    holder: list[PopeyeResult] = []

                    async def collect_external(
                        candidate: DiagnosticRequest,
                        publish: Callable[[DiagnosticSnapshot], None],
                        selected_service: PopeyeService = service,
                        remaining: tuple[int, int, int] = limits,
                        output: list[PopeyeResult] = holder,
                    ) -> DiagnosticSnapshot:
                        produced = await selected_service.run(
                            candidate,
                            max_findings=remaining[0],
                            max_text_bytes=remaining[1],
                            max_source_text_bytes=remaining[2],
                        )
                        output.append(produced)
                        return DiagnosticSnapshot(
                            candidate,
                            produced.findings,
                            produced.sources,
                            False,
                            0,
                            datetime.now(UTC),
                        )

                    workspace.start(request, collect_external, publications.append)
                    task = workspace.task
                    assert task is not None
                    await task
                    assert len(holder) == 1
                    external = holder[0]
                    combined = workspace.snapshot
                    assert (
                        combined is not None
                        and combined.native_requests_used == baseline.native_requests_used
                    )
                    assert (
                        tuple(
                            item
                            for item in combined.findings
                            if item.source is not DiagnosticSourceKind.POPEYE
                        )
                        == baseline.findings
                    )
                    assert (
                        len(combined.findings) <= 1000
                        and diagnostic_text_bytes(combined) <= 2 * 1024 * 1024
                    )
                    assert len(captures) == before + 2
                    version_command, version_result = captures[before]
                    scan_command, scan_result = captures[before + 1]
                    assert (
                        version_command.argv == (str(binary), "version")
                        and parse_popeye_version(version_result.stdout) == "0.22.1"
                    )
                    assert (
                        scan_command.argv[0] == str(binary)
                        and "--out=json" in scan_command.argv
                        and "--logs=none" in scan_command.argv
                    )
                    assert ("--all-namespaces" in scan_command.argv) is (namespace is None)
                    assert (
                        ("--namespace=" + namespace in scan_command.argv)
                        if namespace is not None
                        else True
                    )
                    assert not any(Path(selected_client.directory.name).glob("plugin-*.json"))
                    entry = {
                        "label": label,
                        "process_status": external.status.name
                        if external.status is not None
                        else None,
                        "returncode": external.returncode,
                        "findings": len(external.findings),
                        "sources": [
                            {"status": source.status.value, "detail": source.detail}
                            for source in external.sources
                        ],
                        "output_bytes": len(scan_result.stdout) + len(scan_result.stderr),
                        "stdout_sha256": hashlib.sha256(scan_result.stdout).hexdigest(),
                        "stderr_sha256": hashlib.sha256(scan_result.stderr).hexdigest(),
                        "stderr_redacted_excerpt": sanitize_text(
                            scan_result.stderr.decode("utf-8", errors="replace"),
                            allow_newlines=True,
                        )[:4096],
                        "native_requests_retained": combined.native_requests_used,
                        "combined_text_bytes": diagnostic_text_bytes(combined),
                    }
                    if label == "restricted":
                        assert not all(
                            source.status is DiagnosticStatus.READY for source in external.sources
                        )
                        assert any(
                            source.status
                            in {
                                DiagnosticStatus.FORBIDDEN,
                                DiagnosticStatus.PARTIAL,
                                DiagnosticStatus.UNAVAILABLE,
                                DiagnosticStatus.FAILED,
                            }
                            for source in external.sources
                        )
                    else:
                        assert (
                            external.returncode in (0, 1)
                            and external.producer_version == "0.22.1"
                            and external.parser_id == POPEYE_PARSER_ID
                        )
                        assert external.findings and all(
                            item.identity
                            in {DiagnosticIdentity.NAME_ONLY, DiagnosticIdentity.UNRESOLVED}
                            for item in external.findings
                        )
                        assert any(
                            item.subject is not None and item.subject.name == SCHEDULING_POD
                            for item in external.findings
                        )
                        assert (
                            all(
                                item.subject is None or item.subject.namespace == namespace
                                for item in external.findings
                            )
                            if namespace is not None
                            else True
                        )
                        parsed = parse_popeye_report(
                            scan_result.stdout,
                            producer_version="0.22.1",
                            request=request,
                            discovery=discovery,
                            observed_at=datetime.now(UTC),
                        )
                        assert len(parsed.findings) == len(external.findings)
                        if label == "namespace-a":
                            # The entire scanned cluster/namespace is synthetic and owned.
                            (evidence / "popeye-actual-owned-pods.json").write_bytes(
                                scan_result.stdout
                            )
                            (evidence / "popeye-actual-owned-metadata.json").write_text(
                                json.dumps(
                                    {
                                        "provenance": tool_provenance(),
                                        "context": context,
                                        "namespace": namespace,
                                        "sha256": hashlib.sha256(scan_result.stdout).hexdigest(),
                                        "report_time": parsed.report_time.isoformat(),
                                        "returncode": external.returncode,
                                        "capture": "Actual official binary output from owned synthetic kind fixtures; not hand-authored.",
                                    },
                                    indent=2,
                                )
                                + "\n"
                            )
                    popeye_receipts.append(entry)
                    await service.close()
            result["popeye"] = popeye_receipts
            result["popeye_version_commit_present"] = (
                POPEYE_COMMIT[:7].encode() in captures[0][1].stdout
            )
            assert result["popeye_version_commit_present"]
            checks.append("official-popeye-version-fixed-namespace-all-scope-and-denied-identity")
            checks.append(
                "actual-workspace-native-carryover-combined-budget-and-no-automatic-external-execution"
            )

            # Real same-name recreation: the old UID never becomes a new action target.
            old_record = await reader.get(pods, READY_POD, NAMESPACE)
            old_ref = reference_for(pods, old_record)
            await write(
                pods.path(NAMESPACE) + "/" + READY_POD,
                {
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "gracePeriodSeconds": 0,
                    "preconditions": {"uid": old_record.uid},
                },
                "DELETE",
            )

            async def absent() -> bool:
                try:
                    await reader.get(pods, READY_POD, NAMESPACE)
                except HttpProblem as error:
                    return error.status == 404
                return False

            await until(absent, 30)
            original_ready = next(
                item
                for item in fixtures()
                if item["kind"] == "Pod" and item["metadata"]["name"] == READY_POD
            )
            await write(pods.path(NAMESPACE), original_ready)
            replacement = await reader.get(pods, READY_POD, NAMESPACE)
            assert replacement.uid != old_record.uid
            stale_request = workspace.prepare(DiagnosticScope(identity, NAMESPACE, old_ref))
            await workspace.stop()
            resolver = DiagnosticService(
                reader,
                discovery,
                AccessPolicy(True),
                lambda candidate: candidate == workspace.request,
                now=lambda: datetime.now(UTC),
            )
            try:
                await resolver.resolve(stale_request, old_ref)
            except AppError:
                pass
            else:
                raise AssertionError("Replaced native UID was accepted as the old object.")
            old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            historical = await write(
                events.path(NAMESPACE),
                {
                    "apiVersion": "v1",
                    "kind": "Event",
                    "metadata": {"name": "owned-old-uid-event", "namespace": NAMESPACE},
                    "involvedObject": {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "name": READY_POD,
                        "namespace": NAMESPACE,
                        "uid": old_record.uid,
                    },
                    "reason": "FailedScheduling",
                    "message": "Synthetic historical event for the retired owned UID.",
                    "type": "Warning",
                    "firstTimestamp": old_time,
                    "lastTimestamp": old_time,
                    "count": 1,
                    "source": {"component": "owned-fixture"},
                },
            )
            fresh = await native(
                discovery,
                admin,
                DiagnosticScope(identity, NAMESPACE, reference_for(pods, replacement)),
            )
            assert all(
                item.ref.uid != historical["metadata"]["uid"]
                for row in fresh.findings
                for item in row.evidence
            )
            result["replacement"] = {
                "old_uid": old_record.uid,
                "current_uid": replacement.uid,
                "historical_event_uid": historical["metadata"]["uid"],
            }
            checks.append("actual-replaced-uid-resolution-and-old-uid-event-exclusion")

            # Hold a completed actual API GET before delivery; a new session intent
            # invalidates and drains that producer before a fresh real collection.
            second = KubernetesSession(catalog.select(context), 10)
            clients.append(second)
            private_paths.append(Path(second.directory.name))
            await second.open()
            started, release = asyncio.Event(), asyncio.Event()
            original_get = KubernetesSession.get_json

            async def held_get(
                client: KubernetesSession, path: str, *args: Any, **kwargs: Any
            ) -> Any:
                value = await original_get(client, path, *args, **kwargs)
                if client is admin and path == pods.path(NAMESPACE) + "/" + READY_POD:
                    started.set()
                    await release.wait()
                return value

            scope = DiagnosticScope(identity, NAMESPACE, reference_for(pods, replacement))
            request = workspace.prepare(scope)
            await workspace.stop()
            delayed = DiagnosticService(
                reader,
                discovery,
                AccessPolicy(True),
                lambda candidate: candidate == workspace.request,
                now=lambda: datetime.now(UTC),
            )
            with patch.object(KubernetesSession, "get_json", held_get):
                workspace.start(request, delayed.collect, publications.append)
                old_task = workspace.task
                await asyncio.wait_for(started.wait(), 10)
                next_request = workspace.prepare(
                    DiagnosticScope(SessionIdentity(context, 100), OTHER_NAMESPACE)
                )
                await workspace.stop()
                assert old_task is not None and old_task.done()
                publications.clear()
                release.set()
                replacement_service = DiagnosticService(
                    ResourceReader(second),
                    discovery,
                    AccessPolicy(True),
                    lambda candidate: candidate == workspace.request,
                    now=lambda: datetime.now(UTC),
                )
                workspace.start(next_request, replacement_service.collect, publications.append)
                task = workspace.task
                assert task is not None
                await task
                assert publications and all(item.request == next_request for item in publications)
            checks.append(
                "actual-read-old-session-invalidated-drained-before-new-scope-publication"
            )
            result["home_cache_created_inside_container"] = (Path("/owned/home") / ".kube").exists()
            result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        latest = workspace.snapshot
        if latest is not None:
            result["latest_snapshot_on_failure"] = snapshot_receipt(latest)
        result["failure_frames"] = [
            {"file": frame.filename, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
        stage("failed-original-runtime", failure_type=type(error).__name__)
        raise
    finally:
        # Close parser/process owners before releasing borrowed credential files.
        async def close() -> None:
            workspace.invalidate()
            await workspace.stop()
            for service in services:
                await service.close()
            for client in reversed(clients):
                await client.close()

        cleanup_task = asyncio.create_task(close())
        await finish_owned(cleanup_task)
        result["client_files_deleted"] = all(not path.exists() for path in private_paths)
        result["workspace_drained"] = workspace.task is None
        result["stages"] = stages
        (evidence / "diagnostics-runtime.json").write_text(json.dumps(result, indent=2) + "\n")
        assert result["client_files_deleted"] and result["workspace_drained"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--popeye", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.kubeconfig != Path("/fixture/kubeconfig") or not arguments.context.startswith(
        "kind-kuberich-test-"
    ):
        raise ValueError("Contained verifier accepts only its host-owned fixture connection.")
    asyncio.run(
        qualify(arguments.kubeconfig, arguments.context, arguments.popeye, arguments.evidence)
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Contained diagnostics failed ({type(error).__name__}); inspect original safe receipts.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
