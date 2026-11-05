"""O04: exact authorization evidence and native navigation on an explicitly owned kind."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest.mock import patch

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import Entry, KubeCatalog, load_catalog
from kuberich.config.schema import Settings
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationRequest,
    AuthorizationScope,
    AuthorizationScopeKind,
    AuthorizationSnapshot,
    EvidenceStatus,
    NonResourceAccess,
    RbacObjectRef,
    RbacSubject,
    RbacSubjectKind,
    ResourceAccess,
    ReviewDecision,
)
from kuberich.domain.authorization_rows import AuthorizationRow
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, ConnectionState, HttpProblem
from kuberich.domain.mutations import MutationState
from kuberich.domain.rbac import subject_grants
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ApiResource, Discovery, ResourceRecord
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.authorization import (
    ACCESS_PATH,
    IDENTITY_PATH,
    RULES_PATH,
    AuthorizationReader,
    AuthorizationService,
)
from kuberich.services.mutations import MutationService
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.ui.app import KubeRichApp
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

NAMESPACE = "kuberich-owned-auth-a"
OTHER_NAMESPACE = "kuberich-owned-auth-b"
SERVICEACCOUNT = "owned-account"
POD = "owned-named"
CONFIGMAP = "owned-config"
ROLE = "owned-reader"
AGGREGATE = "owned-aggregate"
CONTRIBUTOR = "owned-contributor"
OPEN_ROLE = "owned-open-replacement"
ANALYSIS_USER = "owned-analysis-user"
ANALYSIS_GROUP = "owned-developers"
RBAC_GROUP = "rbac.authorization.k8s.io"
VERIFY_SECONDS = 600
CLEANUP_SECONDS = 45
MAX_RECEIPTS = 20000
NS = AuthorizationScope(AuthorizationScopeKind.NAMESPACE, NAMESPACE)
OTHER = AuthorizationScope(AuthorizationScopeKind.NAMESPACE, OTHER_NAMESPACE)
ALL = AuthorizationScope(AuthorizationScopeKind.ALL_NAMESPACES, None)
CLUSTER = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)


def fixture_manifests() -> tuple[dict[str, Any], ...]:
    """Two distinct owned identities and declarations for every actual review question."""
    manifests: list[dict[str, Any]] = []

    def add(kind: str, name: str, namespace: str | None = None, **fields: Any) -> None:
        manifests.append(
            {
                "apiVersion": RBAC_GROUP + "/v1"
                if kind in {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"}
                else "v1",
                "kind": kind,
                "metadata": {"name": name, **({"namespace": namespace} if namespace else {})},
                **fields,
            }
        )

    def subject(namespace: str) -> list[dict[str, str]]:
        account = {"kind": "ServiceAccount", "name": SERVICEACCOUNT, "namespace": namespace}
        return [
            account,
            dict(account),
            {
                "kind": "User",
                "apiGroup": RBAC_GROUP,
                "name": f"system:serviceaccount:{namespace}:{SERVICEACCOUNT}",
            },
        ]

    for namespace in (NAMESPACE, OTHER_NAMESPACE):
        add("Namespace", namespace)
        add("ServiceAccount", SERVICEACCOUNT, namespace, automountServiceAccountToken=False)
        add(
            "Pod",
            POD,
            namespace,
            spec={
                "serviceAccountName": SERVICEACCOUNT,
                "automountServiceAccountToken": False,
                "terminationGracePeriodSeconds": 0,
                "containers": [
                    {
                        "name": "app",
                        "image": SHELL_IMAGE,
                        "command": ["sh", "-c", "sleep 3600"],
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "8Mi"},
                            "limits": {"cpu": "100m", "memory": "32Mi"},
                        },
                    }
                ],
            },
        )
        add("ConfigMap", CONFIGMAP, namespace, data={"OWNED_VALUE": "synthetic-unchanged"})
        add(
            "Role",
            ROLE,
            namespace,
            rules=[
                {
                    "apiGroups": [""],
                    "resources": ["pods"],
                    "verbs": ["get", "list", "watch"],
                    "resourceNames": [POD],
                },
                {
                    "apiGroups": [""],
                    "resources": ["*/log"],
                    "verbs": ["get"],
                    "resourceNames": [POD],
                },
                {
                    "apiGroups": [""],
                    "resources": ["configmaps"],
                    "verbs": ["get"],
                    "resourceNames": [CONFIGMAP],
                },
                {
                    "apiGroups": [RBAC_GROUP],
                    "resources": ["roles"],
                    "verbs": ["get"],
                    "resourceNames": [ROLE],
                },
            ],
        )
        add(
            "RoleBinding",
            ROLE,
            namespace,
            roleRef={"apiGroup": RBAC_GROUP, "kind": "Role", "name": ROLE},
            subjects=subject(namespace),
        )
    add(
        "Role",
        OPEN_ROLE,
        NAMESPACE,
        rules=[{"apiGroups": [""], "resources": ["pods"], "verbs": ["get"]}],
    )
    add(
        "ClusterRole",
        "owned-scoped-shared",
        rules=[
            {"apiGroups": [""], "resources": ["nodes"], "verbs": ["list"]},
            {"nonResourceURLs": ["/metrics"], "verbs": ["get"]},
        ],
    )
    add(
        "RoleBinding",
        "owned-scoped-shared",
        NAMESPACE,
        roleRef={"apiGroup": RBAC_GROUP, "kind": "ClusterRole", "name": "owned-scoped-shared"},
        subjects=subject(NAMESPACE),
    )
    add(
        "ClusterRole",
        "owned-public-path",
        rules=[{"nonResourceURLs": ["/version"], "verbs": ["get"]}],
    )
    add(
        "ClusterRoleBinding",
        "owned-public-path",
        roleRef={"apiGroup": RBAC_GROUP, "kind": "ClusterRole", "name": "owned-public-path"},
        subjects=subject(NAMESPACE),
    )
    add(
        "ClusterRole",
        CONTRIBUTOR,
        rules=[
            {
                "apiGroups": [""],
                "resources": ["configmaps"],
                "verbs": ["get", "patch"],
                "resourceNames": [CONFIGMAP],
            }
        ],
    )
    manifests[-1]["metadata"]["labels"] = {"owned-aggregate": "contributor"}
    add(
        "ClusterRole",
        AGGREGATE,
        aggregationRule={
            "clusterRoleSelectors": [{"matchLabels": {"owned-aggregate": "contributor"}}]
        },
        rules=[],
    )
    add(
        "ClusterRoleBinding",
        AGGREGATE,
        roleRef={"apiGroup": RBAC_GROUP, "kind": "ClusterRole", "name": AGGREGATE},
        subjects=[
            {"kind": "User", "apiGroup": RBAC_GROUP, "name": ANALYSIS_USER},
            {"kind": "Group", "apiGroup": RBAC_GROUP, "name": ANALYSIS_GROUP},
        ],
    )
    return tuple(manifests)


def checkpoint(directory: Path, stage: str, **receipt: Any) -> None:
    """Retain safe structured observations before acceptance assertions execute."""
    directory.mkdir(parents=True, exist_ok=True)
    entry = {"stage": stage, "observed_at": time.time(), **receipt}
    (directory / "authorization-stage.json").write_text(json.dumps(entry, indent=2) + "\n")
    with (directory / "authorization-stages.jsonl").open("a") as stream:
        stream.write(json.dumps(entry) + "\n")


def review_receipt(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Allowlist request attributes; never copy credentials or arbitrary server reasons."""
    if path not in {ACCESS_PATH, IDENTITY_PATH, RULES_PATH}:
        raise AssertionError("Unexpected review endpoint in owned verification.")
    spec = body.get("spec", {})
    spec = spec if isinstance(spec, dict) else {}
    safe: dict[str, Any] = {}
    for variant, keys in (
        (
            "resourceAttributes",
            ("namespace", "verb", "group", "version", "resource", "subresource", "name"),
        ),
        ("nonResourceAttributes", ("verb", "path")),
    ):
        if isinstance(spec.get(variant), dict):
            attributes = spec[variant]
            safe[variant] = {
                key: sanitize_text(value[:8192])
                for key in keys
                if isinstance(value := attributes.get(key), str)
            }
            for key in ("fieldSelector", "labelSelector"):
                value = attributes.get(key)
                if isinstance(value, dict) and isinstance(value.get("rawSelector"), str):
                    safe[variant][key] = {"rawSelector": sanitize_text(value["rawSelector"][:256])}
    if isinstance(spec.get("namespace"), str):
        safe["namespace"] = sanitize_text(spec["namespace"][:63])
    expected_kind = {
        ACCESS_PATH: "SelfSubjectAccessReview",
        IDENTITY_PATH: "SelfSubjectReview",
        RULES_PATH: "SelfSubjectRulesReview",
    }[path]
    return {
        "path": path,
        "kind": expected_kind if body.get("kind") == expected_kind else "invalid",
        "spec": safe,
    }


@contextmanager
def trace_api(receipts: list[dict[str, Any]]) -> Iterator[None]:
    """Observe public real adapter operations without replacing their behavior."""
    original_get, original_review = KubernetesSession.get_json, KubernetesSession.review_json

    def append(entry: dict[str, Any]) -> None:
        if len(receipts) >= MAX_RECEIPTS:
            raise AssertionError("Owned API receipts exceeded their finite bound.")
        receipts.append(entry)

    async def get(session: KubernetesSession, path: str, **kwargs: Any) -> dict[str, Any]:
        params = kwargs.get("params") or {}
        entry: dict[str, Any] = {
            "method": "GET",
            "path": path,
            "params": {
                key: params[key] for key in ("fieldSelector", "labelSelector") if key in params
            },
        }
        append(entry)
        try:
            result = await original_get(session, path, **kwargs)
        except HttpProblem as problem:
            entry["http_status"] = problem.status
            raise
        entry["http_success"] = True
        return result

    async def review(
        session: KubernetesSession, path: str, body: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        entry = {"method": "POST", **review_receipt(path, body)}
        append(entry)
        try:
            result = await original_review(session, path, body, **kwargs)
        except HttpProblem as problem:
            entry["http_status"] = problem.status
            raise
        entry["http_success"] = True
        status = result.get("status", {})
        entry["decision_booleans"] = {
            key: status[key]
            for key in ("allowed", "denied")
            if isinstance(status, dict) and type(status.get(key)) is bool
        }
        return result

    with (
        patch.object(KubernetesSession, "get_json", get),
        patch.object(KubernetesSession, "review_json", review),
    ):
        yield


async def until(predicate: Callable[[], Awaitable[bool]], *, timeout: float = 30) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.2)


def snapshot_receipt(snapshot: AuthorizationSnapshot) -> dict[str, Any]:
    rbac, analysis = snapshot.rbac, snapshot.analysis
    return {
        "mode": str(snapshot.request.intent.mode),
        "scope": asdict(snapshot.request.intent.scope),
        "collecting": snapshot.collecting,
        "sources": [
            {
                "family": source.family,
                "scope": asdict(source.scope),
                "status": str(source.status),
                "complete": source.collection.complete if source.collection else None,
            }
            for source in rbac.sources
        ]
        if rbac
        else [],
        "grants": len(analysis.grants) if analysis else 0,
        "incomplete": analysis.incomplete if analysis else None,
        "comparisons_used": analysis.comparisons_used if analysis else 0,
        "requests_used": rbac.requests_used if rbac else 0,
        "decision": str(snapshot.review.decision) if snapshot.review else None,
        "review_status": str(snapshot.review.status) if snapshot.review else None,
        "rules_incomplete": snapshot.rules.incomplete if snapshot.rules else None,
    }


def access(
    resource: ApiResource,
    scope: AuthorizationScope,
    *,
    verb: str = "get",
    name: str | None = None,
    subresource: str | None = None,
    query: ResourceQuery | None = None,
) -> ResourceAccess:
    return ResourceAccess(
        verb,
        resource.group,
        resource.version,
        resource.name,
        subresource,
        name,
        scope,
        query or ResourceQuery(),
    )


def question(
    identity: SessionIdentity,
    value: ResourceAccess | NonResourceAccess,
    revision: int = 1,
    *,
    mode: AuthorizationMode = AuthorizationMode.REVIEW,
) -> AuthorizationRequest:
    scope = value.scope if isinstance(value, ResourceAccess) else CLUSTER
    return AuthorizationRequest(identity, revision, AuthorizationIntent(mode, scope, access=value))


async def collect(
    reader: ResourceReader,
    discovery: Discovery,
    identity: SessionIdentity,
    intent: AuthorizationIntent,
) -> AuthorizationSnapshot:
    request = AuthorizationRequest(identity, 1, intent)
    service = AuthorizationService(
        reader,
        AuthorizationReader(reader.session),
        discovery,
        identity,
        lambda actual: actual == request,
    )
    return await service.collect(request, lambda _: None)


def select_row(app: KubeRichApp, predicate: Callable[[AuthorizationRow], bool]) -> AuthorizationRow:
    for key in app.authorization_table.rows:
        row = app.authorization_table.row_at(key.value)
        if row is not None and predicate(row):
            app.authorization_table.move_cursor(row=app.authorization_table.get_row_index(row.key))
            return row
    raise AssertionError("Expected owned authorization evidence row was not rendered.")


async def native_checks(
    cluster: OwnedCluster,
    catalog: KubeCatalog,
    request: ConnectionRequest,
    directory: Path,
    replace_role: Callable[[], Awaitable[ResourceRecord]],
) -> None:
    alias = cluster.context + "-other"
    context = catalog.contexts[cluster.context]
    catalog = replace(
        catalog,
        contexts={
            **catalog.contexts,
            alias: Entry({**context.data, "namespace": OTHER_NAMESPACE}, context.directory),
        },
    )
    private_paths: list[Path] = []
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-authorization", level=100),
        catalog=catalog,
        connection=request,
        environment={},
        directory=cluster.directory,
    )
    async with app.run_test(size=(120, 38)) as pilot:

        async def connected() -> bool:
            return (
                app.state.connection is ConnectionState.CONNECTED
                and app.workspace.discovery is not None
                and app.workspace.store.observation.snapshot is not None
            )

        await until(connected, timeout=60)
        assert app.sessions.client is not None
        private_paths.append(Path(app.sessions.client.directory.name))

        async def ready(mode: AuthorizationMode) -> bool:
            snapshot = app.workspace.store.observation.authorization
            checkpoint(
                directory,
                "waiting-native-authorization",
                expected_mode=mode.value,
                view_kind=app.state.view_kind,
                header_namespace=app.state.namespace,
                collecting=app.workspace.authorization_collecting,
                table_rows=app.authorization_table.row_count,
                snapshot=snapshot_receipt(snapshot) if snapshot else None,
            )
            return (
                app.state.view_kind == "authorization"
                and snapshot is not None
                and snapshot.request.intent.mode is mode
                and not snapshot.collecting
                and not app.workspace.authorization_collecting
                and app.authorization_table.request == snapshot.request
            )

        async def command(text: str, mode: AuthorizationMode) -> None:
            await app.run_command(text)

            async def observed() -> bool:
                return await ready(mode)

            await until(observed)
            checkpoint(
                directory,
                "native-command-" + mode.value,
                view_kind=app.state.view_kind,
                header_namespace=app.state.namespace,
                snapshot=snapshot_receipt(app.workspace.store.observation.authorization)
                if app.workspace.store.observation.authorization
                else None,
                table_rows=app.authorization_table.row_count,
            )

        await command("rbac subjects --namespace " + NAMESPACE, AuthorizationMode.SUBJECTS)
        select_row(
            app,
            lambda row: (
                row.destination is not None
                and row.destination.subject
                == RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, SERVICEACCOUNT, NAMESPACE)
            ),
        )
        await pilot.press("enter")
        await until(lambda: ready(AuthorizationMode.SUBJECT))
        select_row(
            app,
            lambda row: (
                row.destination is not None
                and row.destination.binding is not None
                and row.destination.binding.name == ROLE
            ),
        )
        await pilot.press("enter")
        await until(lambda: ready(AuthorizationMode.BINDING))
        binding_snapshot = app.workspace.store.observation.authorization
        assert binding_snapshot is not None and binding_snapshot.rbac is not None
        binding = next(
            value
            for value in binding_snapshot.rbac.bindings
            if value.ref.name == ROLE and value.ref.namespace == NAMESPACE
        )
        account = RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, SERVICEACCOUNT, NAMESPACE)
        canonical_user = RbacSubject(
            RbacSubjectKind.USER, f"system:serviceaccount:{NAMESPACE}:{SERVICEACCOUNT}", None
        )
        displayed_subjects: list[RbacSubject] = []
        for key in app.authorization_table.rows:
            binding_row = app.authorization_table.row_at(key.value)
            if binding_row is not None and binding_row.destination is not None:
                selected_subject = binding_row.destination.subject
                if selected_subject is not None:
                    displayed_subjects.append(selected_subject)
        checkpoint(
            directory,
            "native-repeated-binding-subjects-preserve-distinct-identities",
            declared_subjects=len(binding.subjects),
            repeated_account_declarations=binding.subjects.count(account),
            displayed_subjects=[asdict(value) for value in displayed_subjects],
        )
        assert len(binding.subjects) == 3 and binding.subjects.count(account) == 2
        assert displayed_subjects == [account, canonical_user]
        select_row(
            app,
            lambda row: (
                row.destination is not None
                and row.destination.role is not None
                and row.destination.role.name == ROLE
            ),
        )
        await pilot.press("enter")
        await until(lambda: ready(AuthorizationMode.ROLE))
        select_row(app, lambda row: row.label.startswith("Rule "))
        await pilot.press("enter")
        assert await ready(AuthorizationMode.ROLE)
        (directory / "authorization-native-role.svg").write_text(app.export_screenshot())
        await command("rbac roles --cluster", AuthorizationMode.ROLES)
        selected = select_row(
            app,
            lambda row: (
                row.destination is not None
                and row.destination.role is not None
                and row.destination.role.name == AGGREGATE
            ),
        )
        await pilot.press("enter")
        await until(lambda: ready(AuthorizationMode.ROLE))
        assert selected.destination is not None and selected.destination.role is not None
        aggregate_uid = selected.destination.role.uid
        select_row(
            app,
            lambda row: (
                row.object_ref is not None
                and row.object_ref.uid == aggregate_uid
                and row.label.startswith("ClusterRole/")
            ),
        )
        before_open = app.authorization_table.capture_viewport()
        await app.run_command("open")

        async def opened() -> bool:
            return (
                app.state.view_kind.startswith("clusterroles")
                and app.state.selected == aggregate_uid
            )

        await until(opened)
        await app.run_command("back")
        await until(lambda: ready(AuthorizationMode.ROLE))
        await pilot.pause()
        assert app.authorization_table.capture_viewport() == before_open
        assert any(
            row.label.startswith("Contributor ")
            for key in app.authorization_table.rows
            if (row := app.authorization_table.row_at(key.value)) is not None
        )
        (directory / "authorization-native-aggregation.svg").write_text(app.export_screenshot())
        await command("rules " + NAMESPACE, AuthorizationMode.SELF_RULES)
        await app.run_command("ns *")
        await until(lambda: ready(AuthorizationMode.SUBJECTS))
        assert app.state.namespace is None
        await app.run_command("ns " + NAMESPACE)
        await until(lambda: ready(AuthorizationMode.SUBJECTS))
        await command("rbac bindings --namespace " + NAMESPACE, AuthorizationMode.BINDINGS)
        await command("rules " + NAMESPACE, AuthorizationMode.SELF_RULES)
        await command(
            "can-i get pods " + POD + " --namespace " + OTHER_NAMESPACE, AuthorizationMode.REVIEW
        )
        independent = app.workspace.authorization_request
        assert (
            independent is not None
            and independent.intent.scope == OTHER
            and app.state.namespace == NAMESPACE
        )
        app.filter_input.value = "allowed"
        await pilot.pause()
        filtered_viewport = app.authorization_table.capture_viewport()
        filtered_count = app.authorization_table.row_count
        assert filtered_count > 0
        await command("rbac roles", AuthorizationMode.ROLES)
        await app.run_command("back")
        await until(lambda: ready(AuthorizationMode.REVIEW))
        await pilot.pause()
        assert (
            app.filter_input.value == "allowed"
            and app.authorization_table.row_count == filtered_count
        )
        assert app.authorization_table.capture_viewport() == filtered_viewport
        assert (
            app.state.namespace == NAMESPACE
            and app.workspace.authorization_request is not None
            and app.workspace.authorization_request.intent == independent.intent
        )
        before_refresh = app.workspace.authorization_request
        assert before_refresh is not None
        await app.run_command("refresh")
        await until(lambda: ready(AuthorizationMode.REVIEW))
        await pilot.pause()
        refreshed = app.workspace.authorization_request
        assert refreshed is not None and refreshed.revision > before_refresh.revision
        assert refreshed.intent == independent.intent and app.state.namespace == NAMESPACE
        assert (
            app.filter_input.value == "allowed"
            and app.authorization_table.capture_viewport() == filtered_viewport
        )
        await app.run_command("forward")
        await until(lambda: ready(AuthorizationMode.ROLES))
        await app.run_command("back")
        await until(lambda: ready(AuthorizationMode.REVIEW))
        await app.run_command("ns")

        async def namespace_picker() -> bool:
            return (
                app.state.view_kind == "namespaces"
                and app.namespace_table.row_count > 1
                and app.workspace.store.observation.snapshot is not None
            )

        await until(namespace_picker)
        assert app.workspace.authorization_request is None
        namespaces = app.workspace.store.observation.snapshot
        assert namespaces is not None
        chosen = next(record for record in namespaces.items if record.name == OTHER_NAMESPACE)
        assert chosen.uid is not None
        app.namespace_table.move_cursor(row=app.namespace_table.get_row_index(chosen.uid))
        await pilot.press("enter")
        await until(lambda: ready(AuthorizationMode.REVIEW))
        assert (
            app.state.namespace == OTHER_NAMESPACE
            and app.workspace.authorization_request is not None
            and app.workspace.authorization_request.intent.scope == OTHER
        )
        await command(
            "who-can get pods " + POD + " --namespace " + NAMESPACE, AuthorizationMode.WHO_CAN
        )
        await command("rbac roles --namespace " + NAMESPACE, AuthorizationMode.ROLES)
        stale = select_row(
            app, lambda row: row.object_ref is not None and row.object_ref.name == OPEN_ROLE
        )
        replacement = await replace_role()
        checkpoint(
            directory,
            "native-object-uid-replaced-before-open",
            expected_uid=stale.object_ref.uid if stale.object_ref else None,
            observed_uid=replacement.uid,
        )
        assert stale.object_ref is not None and stale.object_ref.uid != replacement.uid
        await app.run_command("open")

        async def replacement_observed() -> bool:
            current = app.workspace.store.observation.snapshot
            return (
                app.state.scope is not None
                and app.state.scope.resource.name == "roles"
                and current is not None
                and any(record.uid == replacement.uid for record in current.items)
                and app.views.table.row_count == 0
            )

        await until(replacement_observed)
        assert app.state.selected != replacement.uid
        checkpoint(
            directory,
            "native-uid-safe-open-refused-replacement",
            expected_uid=stale.object_ref.uid,
            observed_uid=replacement.uid,
            displayed_rows=app.views.table.row_count,
        )
        await command(
            "can-i get pods " + POD + " --namespace " + NAMESPACE, AuthorizationMode.REVIEW
        )
        original = KubernetesSession.review_json
        arrived, cancelled = asyncio.Event(), asyncio.Event()
        active = app.sessions.client
        assert active is not None

        async def held(
            client: KubernetesSession, path: str, body: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            result = await original(client, path, body, **kwargs)
            if client is active and path == ACCESS_PATH:
                arrived.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return result

        with patch.object(KubernetesSession, "review_json", held):
            await app.run_command("can-i list pods --all-namespaces")
            await asyncio.wait_for(arrived.wait(), 30)
            retired = app.workspace.authorization_request
            assert retired is not None
            app.navigator.connect(alias)
            await asyncio.wait_for(cancelled.wait(), 30)
            await until(connected, timeout=60)
            assert app.state.context == alias and app.workspace.authorization_request is None
            assert app.sessions.client is not None
            private_paths.append(Path(app.sessions.client.directory.name))
            current = app.workspace.store.observation.authorization
            assert current is None or current.request.session != retired.session
        checkpoint(
            directory,
            "native-held-real-review-cancelled-on-context-switch",
            old_revision=retired.revision,
            cancelled=cancelled.is_set(),
            current_context=app.state.context,
            authorization_retired=app.workspace.authorization_request is None,
        )
    checkpoint(
        directory,
        "native-app-owners-drained",
        ownership=asdict(app.workspace.ownership),
        private_sessions_deleted=all(not path.exists() for path in private_paths),
    )
    assert all(not path.exists() for path in private_paths)
    assert (
        app.workspace.ownership.authorization_count
        == app.workspace.ownership.watch_count
        == app.workspace.ownership.operation_count
        == 0
    )


async def close_sessions(clients: list[KubernetesSession], sessions: SessionService) -> None:
    """Attempt every owned close, retain errors, and bound the complete cleanup group."""
    async with asyncio.timeout(CLEANUP_SECONDS):
        results = await asyncio.gather(
            *(client.close() for client in reversed(clients)),
            sessions.close(),
            return_exceptions=True,
        )
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def verify(cluster: OwnedCluster, evidence_dir: Path) -> dict[str, Any]:
    """Run actual API/service/UI questions; every client uses the verified owned context."""
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    catalog = load_catalog(request, {})
    sessions = SessionService(catalog, request)
    environment = dict(os.environ)
    original_config = cluster.path.read_bytes()
    clients: list[KubernetesSession] = []
    private_paths: list[Path] = []
    receipts: list[dict[str, Any]] = []
    checks: list[str] = []
    result: dict[str, Any] = {}
    try:
        async with asyncio.timeout(VERIFY_SECONDS - CLEANUP_SECONDS):
            with trace_api(receipts):
                checkpoint(evidence_dir, "connecting-explicit-verified-owned-context")
                await sessions.connect(cluster.context)
                admin, identity = sessions.client, sessions.observation.identity
                assert admin is not None and admin.api is not None and identity is not None
                private_paths.append(Path(admin.directory.name))
                sdk = admin.api

                async def write(path: str, body: dict[str, Any], method: str = "POST") -> Any:
                    return await sdk.call_api(
                        path,
                        method,
                        body=body,
                        response_types_map={200: "object", 201: "object", 202: "object"},
                        auth_settings=["BearerToken"],
                        header_params={"Content-Type": "application/json"},
                        _return_http_data_only=True,
                        _request_timeout=15,
                    )

                reader = ResourceReader(admin)
                discovery = await reader.discover()
                for manifest in fixture_manifests():
                    resource = next(
                        item
                        for item in discovery.resources
                        if item.api_version == manifest["apiVersion"]
                        and item.kind == manifest["kind"]
                    )
                    await write(resource.path(manifest["metadata"].get("namespace")), manifest)
                pods, accounts, configs = (
                    discovery.find(name) for name in ("pods", "serviceaccounts", "configmaps")
                )
                pod_a = await reader.get(pods, POD, NAMESPACE)
                pod_b = await reader.get(pods, POD, OTHER_NAMESPACE)
                account_a = await reader.get(accounts, SERVICEACCOUNT, NAMESPACE)
                account_b = await reader.get(accounts, SERVICEACCOUNT, OTHER_NAMESPACE)
                checkpoint(
                    evidence_dir,
                    "two-owned-namespace-identities-observed",
                    pod_uids=[pod_a.uid, pod_b.uid],
                    serviceaccount_uids=[account_a.uid, account_b.uid],
                )
                assert pod_a.uid and pod_b.uid and pod_a.uid != pod_b.uid
                assert account_a.uid and account_b.uid and account_a.uid != account_b.uid
                checks.append("actual-distinct-same-name-pod-and-serviceaccount-identities")
                cluster_roles = discovery.find("clusterroles", group=RBAC_GROUP)

                async def materialized() -> bool:
                    aggregate = await reader.get(cluster_roles, AGGREGATE)
                    rules = aggregate.manifest.get("rules", [])
                    ready = any(
                        "patch" in rule.get("verbs", [])
                        and "configmaps" in rule.get("resources", [])
                        for rule in rules
                    )
                    checkpoint(
                        evidence_dir,
                        "waiting-actual-aggregation-controller",
                        observed_uid=aggregate.uid,
                        rules_count=len(rules),
                        materialized_patch=ready,
                    )
                    return ready

                await until(materialized)
                snapshot = await collect(
                    reader,
                    discovery,
                    identity,
                    AuthorizationIntent(AuthorizationMode.SUBJECTS, ALL),
                )
                assert snapshot.rbac is not None
                assert {
                    entry.subject.namespace
                    for entry in snapshot.rbac.subjects
                    if entry.subject.kind is RbacSubjectKind.SERVICE_ACCOUNT
                    and entry.subject.name == SERVICEACCOUNT
                } == {NAMESPACE, OTHER_NAMESPACE}
                analysis_subject = RbacSubject(RbacSubjectKind.USER, ANALYSIS_USER, None)
                observed = await collect(
                    reader,
                    discovery,
                    identity,
                    AuthorizationIntent(
                        AuthorizationMode.SUBJECT, CLUSTER, subject=analysis_subject
                    ),
                )
                checkpoint(
                    evidence_dir,
                    "controller-materialized-aggregation-and-inferred-provenance",
                    snapshot=snapshot_receipt(observed),
                )
                assert observed.analysis is not None and observed.analysis.aggregations
                assert any(
                    ref.name == CONTRIBUTOR
                    for aggregate in observed.analysis.aggregations
                    for ref in aggregate.contributors
                )
                assert any(
                    grant.evidence.value == "materialized" for grant in observed.analysis.grants
                )
                assert observed.rbac is not None
                other_user = RbacSubject(RbacSubjectKind.USER, "owned-unknown-user", None)
                identity_review = observed.identity
                assert identity_review is not None and identity_review.identity is not None
                unknown = subject_grants(observed.rbac, other_user, identity_review.identity)
                assert not unknown.grants and any(
                    "membership" in warning for warning in unknown.warnings
                )
                candidates = await collect(
                    reader,
                    discovery,
                    identity,
                    AuthorizationIntent(
                        AuthorizationMode.WHO_CAN,
                        NS,
                        access=access(configs, NS, verb="patch", name=CONFIGMAP),
                    ),
                )
                assert candidates.analysis is not None and any(
                    grant.subject.kind is RbacSubjectKind.GROUP
                    and grant.subject.name == ANALYSIS_GROUP
                    for grant in candidates.analysis.grants
                )
                checks.append("actual-materialized-aggregation-and-group-membership-uncertainty")
                issued = await write(
                    accounts.path(NAMESPACE) + "/" + SERVICEACCOUNT + "/token",
                    {
                        "apiVersion": "authentication.k8s.io/v1",
                        "kind": "TokenRequest",
                        "spec": {"audiences": [], "expirationSeconds": 1800},
                    },
                )
                token = issued["status"]["token"]
                assert isinstance(token, str) and token

                async def open_client(overrides: ConnectionOverrides) -> KubernetesSession:
                    client = KubernetesSession(catalog.select(cluster.context, overrides), 15)
                    clients.append(client)
                    private_paths.append(Path(client.directory.name))
                    await client.open()
                    return client

                group_client = await open_client(
                    ConnectionOverrides(as_user=ANALYSIS_USER, as_groups=(ANALYSIS_GROUP,))
                )
                group_request = question(
                    SessionIdentity(cluster.context, identity.generation + 2),
                    access(configs, NS, verb="patch", name=CONFIGMAP),
                )
                current_group = await AuthorizationReader(group_client).identity(group_request)
                assert (
                    current_group.identity is not None
                    and current_group.identity.username == ANALYSIS_USER
                )
                assert ANALYSIS_GROUP in current_group.identity.groups
                current_grants = subject_grants(
                    observed.rbac, analysis_subject, current_group.identity
                )
                uncertain_grants = subject_grants(observed.rbac, other_user, current_group.identity)
                checkpoint(
                    evidence_dir,
                    "actual-reviewed-group-identity-matches-only-selected-current-user",
                    declaration_source="admin-owned-inventory",
                    expanded_groups=sorted(
                        {
                            grant.via_group
                            for grant in current_grants.grants
                            if grant.via_group is not None
                        }
                    ),
                    unrelated_grants=len(uncertain_grants.grants),
                )
                assert any(grant.via_group == ANALYSIS_GROUP for grant in current_grants.grants)
                assert not uncertain_grants.grants
                restricted = await open_client(ConnectionOverrides(token=token))
                restricted_identity = SessionIdentity(cluster.context, identity.generation + 1)
                reviews = AuthorizationReader(restricted)
                restricted_reader = ResourceReader(restricted)

                async def propagated() -> bool:
                    return (
                        await reviews.review(
                            question(restricted_identity, access(pods, NS, name=POD))
                        )
                    ).decision is ReviewDecision.ALLOWED

                await until(propagated)
                other_issued = await write(
                    accounts.path(OTHER_NAMESPACE) + "/" + SERVICEACCOUNT + "/token",
                    {
                        "apiVersion": "authentication.k8s.io/v1",
                        "kind": "TokenRequest",
                        "spec": {"audiences": [], "expirationSeconds": 1800},
                    },
                )
                other_token = other_issued["status"]["token"]
                assert isinstance(other_token, str) and other_token
                other_client = await open_client(ConnectionOverrides(token=other_token))
                other_identity = SessionIdentity(cluster.context, identity.generation + 3)
                current_a = await reviews.identity(
                    question(restricted_identity, access(pods, NS, name=POD))
                )
                current_b = await AuthorizationReader(other_client).identity(
                    question(other_identity, access(pods, OTHER, name=POD))
                )
                assert current_a.identity is not None and current_b.identity is not None
                checkpoint(
                    evidence_dir,
                    "actual-distinct-serviceaccount-current-identities",
                    usernames=[current_a.identity.username, current_b.identity.username],
                )
                assert (
                    current_a.identity.username
                    == f"system:serviceaccount:{NAMESPACE}:{SERVICEACCOUNT}"
                )
                assert (
                    current_b.identity.username
                    == f"system:serviceaccount:{OTHER_NAMESPACE}:{SERVICEACCOUNT}"
                )
                for actual_scope, expected in (
                    (OTHER, ReviewDecision.ALLOWED),
                    (NS, ReviewDecision.NO_ALLOW),
                ):
                    actual = await AuthorizationReader(other_client).review(
                        question(other_identity, access(pods, actual_scope, name=POD))
                    )
                    checkpoint(
                        evidence_dir,
                        "actual-second-namespace-serviceaccount-review",
                        scope=asdict(actual_scope),
                        decision=str(actual.decision),
                        expected=str(expected),
                    )
                    assert actual.decision is expected and actual.status is EvidenceStatus.READY
                questions: tuple[
                    tuple[str, ResourceAccess | NonResourceAccess, ReviewDecision], ...
                ] = (
                    ("named-get", access(pods, NS, name=POD), ReviewDecision.ALLOWED),
                    ("other-name", access(pods, NS, name="owned-other"), ReviewDecision.NO_ALLOW),
                    ("other-namespace", access(pods, OTHER, name=POD), ReviewDecision.NO_ALLOW),
                    (
                        "subresource-wildcard",
                        access(pods, NS, name=POD, subresource="log"),
                        ReviewDecision.ALLOWED,
                    ),
                    ("unnamed-list", access(pods, NS, verb="list"), ReviewDecision.NO_ALLOW),
                    (
                        "named-hypothetical-list",
                        access(pods, NS, verb="list", name=POD),
                        ReviewDecision.ALLOWED,
                    ),
                    (
                        "actual-selected-list-question",
                        access(
                            pods,
                            NS,
                            verb="list",
                            query=ResourceQuery(field_selector="metadata.name=" + POD),
                        ),
                        ReviewDecision.ALLOWED,
                    ),
                    (
                        "all-namespaces-list",
                        access(pods, ALL, verb="list", name=POD),
                        ReviewDecision.NO_ALLOW,
                    ),
                    (
                        "cluster-nodes",
                        access(discovery.find("nodes"), CLUSTER, verb="list"),
                        ReviewDecision.NO_ALLOW,
                    ),
                    (
                        "nonresource-allowed",
                        NonResourceAccess("get", "/version"),
                        ReviewDecision.ALLOWED,
                    ),
                    (
                        "namespaced-nonresource-does-not-grant",
                        NonResourceAccess("get", "/metrics"),
                        ReviewDecision.NO_ALLOW,
                    ),
                    (
                        "patch-no-opinion",
                        access(configs, NS, verb="patch", name=CONFIGMAP),
                        ReviewDecision.NO_ALLOW,
                    ),
                )
                for revision, (name, value, expected) in enumerate(questions, 1):
                    review = await reviews.review(question(restricted_identity, value, revision))
                    checkpoint(
                        evidence_dir,
                        "actual-ssar-" + name,
                        decision=str(review.decision),
                        status=str(review.status),
                        expected=str(expected),
                    )
                    assert review.decision is expected and review.status is EvidenceStatus.READY
                selected = await restricted_reader.list(
                    pods, NAMESPACE, query=ResourceQuery(field_selector="metadata.name=" + POD)
                )
                assert tuple(record.uid for record in selected.items) == (pod_a.uid,)
                try:
                    await restricted_reader.list(pods, NAMESPACE)
                except HttpProblem as problem:
                    checkpoint(
                        evidence_dir,
                        "actual-unfiltered-list-forbidden",
                        http_status=problem.status,
                        selected_uids=[record.uid for record in selected.items],
                    )
                    assert problem.status == 403
                else:
                    raise AssertionError("Unfiltered restricted LIST unexpectedly succeeded.")
                try:
                    await reader.list(
                        pods, NAMESPACE, query=ResourceQuery(field_selector="metadata.name =" + POD)
                    )
                except HttpProblem as problem:
                    checkpoint(
                        evidence_dir,
                        "actual-literal-spaced-selector-invalid",
                        http_status=problem.status,
                    )
                    assert problem.status == 400
                else:
                    raise AssertionError(
                        "Spaced literal field-selector key unexpectedly succeeded."
                    )
                before_reviews = sum(entry["method"] == "POST" for entry in receipts)
                try:
                    question(
                        restricted_identity,
                        access(
                            pods,
                            NS,
                            verb="list",
                            query=ResourceQuery(field_selector="metadata.name =" + POD),
                        ),
                    )
                except AppError:
                    pass
                else:
                    raise AssertionError(
                        "Authorization request normalized a literal field selector."
                    )
                assert sum(entry["method"] == "POST" for entry in receipts) == before_reviews
                checks.append(
                    "actual-ssar-exact-namespace-name-subresource-nonresource-and-http-selector-semantics"
                )
                selected_role = await reader.get(
                    discovery.find("roles", group=RBAC_GROUP), ROLE, NAMESPACE
                )
                limited = await collect(
                    restricted_reader,
                    discovery,
                    restricted_identity,
                    AuthorizationIntent(
                        AuthorizationMode.ROLE,
                        NS,
                        role=RbacObjectRef("Role", ROLE, NAMESPACE, selected_role.uid),
                    ),
                )
                checkpoint(
                    evidence_dir,
                    "actual-forbidden-lists-retain-named-role-and-partial-provenance",
                    snapshot=snapshot_receipt(limited),
                )
                assert (
                    limited.rbac is not None
                    and limited.analysis is not None
                    and limited.analysis.incomplete
                )
                assert any(
                    source.status is EvidenceStatus.FORBIDDEN for source in limited.rbac.sources
                )
                assert any(role.ref.name == ROLE for role in limited.rbac.roles)
                checks.append("actual-forbidden-list-provenance-remains-incomplete-after-named-get")
                anonymous = await open_client(
                    ConnectionOverrides(
                        as_user="owned-review-denied", as_groups=("system:unauthenticated",)
                    )
                )
                try:
                    await anonymous.review_json(
                        ACCESS_PATH,
                        {
                            "apiVersion": "authorization.k8s.io/v1",
                            "kind": "SelfSubjectAccessReview",
                            "spec": {"nonResourceAttributes": {"verb": "get", "path": "/version"}},
                        },
                    )
                except HttpProblem as problem:
                    checkpoint(
                        evidence_dir,
                        "actual-review-api-forbidden-control",
                        http_status=problem.status,
                    )
                    assert problem.status == 403
                else:
                    raise AssertionError(
                        "Synthetic unauthenticated review POST unexpectedly succeeded."
                    )
                denied_review = await AuthorizationReader(anonymous).review(
                    question(restricted_identity, access(pods, NS, name=POD))
                )
                assert (
                    denied_review.decision is ReviewDecision.UNKNOWN
                    and denied_review.status is EvidenceStatus.FORBIDDEN
                )
                impersonating = await open_client(
                    ConnectionOverrides(token=token, as_user="owned-escalation-target")
                )
                impersonation = await AuthorizationReader(impersonating).review(
                    question(restricted_identity, access(pods, NS, name=POD))
                )
                checkpoint(
                    evidence_dir,
                    "actual-low-credential-additional-impersonation-denied-without-fallback",
                    decision=str(impersonation.decision),
                    status=str(impersonation.status),
                )
                assert (
                    impersonation.decision is ReviewDecision.UNKNOWN
                    and impersonation.status is EvidenceStatus.FORBIDDEN
                )
                checks.append(
                    "actual-review403-unknown-and-low-credential-impersonation403-no-fallback"
                )
                config = await reader.get(configs, CONFIGMAP, NAMESPACE)
                assert config.uid is not None
                target = ResourceTarget(
                    identity, configs.group, configs.name, NAMESPACE, CONFIGMAP, config.uid
                )
                policy = AccessPolicy(False)
                mutation = MutationService(admin, configs, target, policy, lambda: True)
                intent = await mutation.prepare_annotation(
                    "owned.kuberich.test/blocked", "synthetic-blocked"
                )
                confirmation = mutation.confirm(intent)
                allow = await AuthorizationReader(admin).review(
                    question(identity, access(configs, NS, verb="patch", name=CONFIGMAP))
                )
                assert allow.decision is ReviewDecision.ALLOWED and candidates.analysis.grants
                policy.tighten()
                guarded = await mutation.execute(confirmation)
                low_target = replace(target, session=restricted_identity)
                denied_mutation = MutationService(
                    restricted, configs, low_target, AccessPolicy(False), lambda: True
                )
                low_intent = await denied_mutation.prepare_annotation(
                    "owned.kuberich.test/blocked", "synthetic-blocked"
                )
                refused = await denied_mutation.execute(denied_mutation.confirm(low_intent))
                after = await reader.get(configs, CONFIGMAP, NAMESPACE)
                checkpoint(
                    evidence_dir,
                    "actual-guarded-write-and-server403-leave-object-unchanged",
                    guarded=guarded.state.name,
                    server_write=refused.state.name,
                    expected_uid=config.uid,
                    observed_uid=after.uid,
                    manifest_unchanged=after.manifest == config.manifest,
                )
                assert (
                    guarded.state is MutationState.BLOCKED and refused.state is MutationState.DENIED
                )
                assert config.manifest == after.manifest and config.uid == after.uid
                checks.append(
                    "actual-confirmed-write-remains-blocked-despite-informational-grants-and-server-denies-restricted-patch"
                )

                async def replace_open_role() -> ResourceRecord:
                    resource = discovery.find("roles", group=RBAC_GROUP)
                    old = await reader.get(resource, OPEN_ROLE, NAMESPACE)
                    await write(
                        resource.path(NAMESPACE) + "/" + OPEN_ROLE,
                        {
                            "apiVersion": "v1",
                            "kind": "DeleteOptions",
                            "preconditions": {"uid": old.uid},
                        },
                        "DELETE",
                    )

                    async def removed() -> bool:
                        try:
                            await reader.get(resource, OPEN_ROLE, NAMESPACE)
                        except HttpProblem as problem:
                            if problem.status == 404:
                                return True
                            raise
                        return False

                    await until(removed)
                    manifest = next(
                        item
                        for item in fixture_manifests()
                        if item["kind"] == "Role" and item["metadata"]["name"] == OPEN_ROLE
                    )
                    await write(resource.path(NAMESPACE), manifest)
                    return await reader.get(resource, OPEN_ROLE, NAMESPACE)

                await native_checks(cluster, catalog, request, evidence_dir, replace_open_role)
                checks.append(
                    "actual-native-command-drilldown-filter-history-atomic-picker-uid-open-and-context-cancellation"
                )
                assert original_config == cluster.path.read_bytes() and environment == dict(
                    os.environ
                )
                result = {
                    "package_versions": {
                        name: version(name)
                        for name in ("kuberich", "textual", "kubernetes-asyncio")
                    },
                    "python_version": sys.version.split()[0],
                    "node_image": NODE_IMAGE,
                    "shell_image": SHELL_IMAGE,
                    "checks": checks,
                    "api_calls_observed": len(receipts),
                    "owned_kubeconfig_unchanged": True,
                    "environment_unchanged": True,
                    "deadline_seconds": VERIFY_SECONDS,
                }
    except BaseException as error:
        checkpoint(
            evidence_dir,
            "verification-failed-before-owned-cleanup",
            failure_type=type(error).__name__,
        )
        raise
    finally:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "authorization-api.json").write_text(json.dumps(receipts, indent=2) + "\n")

        cleanup = asyncio.create_task(
            close_sessions(clients, sessions), name="owned-authorization-close"
        )
        try:
            await finish_owned(cleanup)
        except BaseException as error:
            checkpoint(
                evidence_dir,
                "owned-session-cleanup-failed",
                failure_type=type(error).__name__,
                private_sessions_deleted=all(not path.exists() for path in private_paths),
            )
            raise
        deleted = all(not path.exists() for path in private_paths)
        checkpoint(
            evidence_dir,
            "owned-sessions-and-private-material-drained",
            private_sessions_deleted=deleted,
            environment_unchanged=environment == dict(os.environ),
            kubeconfig_unchanged=original_config == cluster.path.read_bytes(),
        )
        assert (
            deleted
            and environment == dict(os.environ)
            and original_config == cluster.path.read_bytes()
        )
    return result


def input_hashes(root: Path) -> dict[str, str]:
    paths = [
        *sorted(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        root / "pyproject.toml",
        root / "uv.lock",
        root / "scripts/owned_kind.py",
        root / "scripts/verify_authorization_kind.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.evidence.exists()
        or any(args.evidence.parent.glob("authorization-*.json*"))
        or any(args.evidence.parent.glob("authorization-*.svg"))
    ):
        raise ValueError("Use a fresh evidence path; earlier outcomes must be preserved.")
    root = Path(__file__).resolve().parent.parent
    captured = input_hashes(root)
    environment = dict(os.environ)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": captured,
        "owned_cluster_deleted": False,
        "private_directory_deleted": False,
        "deadline_seconds": VERIFY_SECONDS,
    }
    started = time.monotonic()
    problem: BaseException | None = None
    cluster: OwnedCluster | None = None
    try:
        checkpoint(args.evidence.parent, "creating-explicit-owned-disposable-cluster")
        with owned_cluster(args.kind, docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(asyncio.run(verify(cluster, args.evidence.parent)))
            except BaseException as error:
                problem = error
                result["failure_type"] = type(error).__name__
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        result["environment_unchanged"] = environment == dict(os.environ)
        if problem is not None:
            raise problem
        assert (
            result["inputs_unchanged"]
            and result["private_directory_deleted"]
            and result["environment_unchanged"]
        )
        result["status"] = "passed"
        checkpoint(args.evidence.parent, "passed-owned-cluster-absence-verified")
    except BaseException as error:
        if "failure_type" in result and problem is not error:
            result["cleanup_failure_type"] = type(error).__name__
        result.setdefault("failure_type", type(error).__name__)
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        result["environment_unchanged"] = environment == dict(os.environ)
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind authorization and native navigation checks passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned authorization verification failed ({type(error).__name__}); inspect retained safe stage/API receipts.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
