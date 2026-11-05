"""Owned authorization fixture, real HTTP receipts, timeout and cleanup contracts."""

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp import web

from kuberich.domain.authorization import (
    EvidenceStatus,
    NonResourceAccess,
    ReviewDecision,
)
from kuberich.domain.connections import HttpProblem
from kuberich.domain.rbac import binding_applies, parse_rbac_binding, parse_rbac_role, rule_matches
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.services.authorization import (
    ACCESS_PATH,
    IDENTITY_PATH,
    RULES_PATH,
    AuthorizationReader,
)
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader
from scripts import verify_authorization_kind as verification
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster
from tests.support.authorization import authorization_session
from tests.support.resources import item, reader_fixture

PLURALS = {
    "Namespace": "namespaces",
    "ServiceAccount": "serviceaccounts",
    "Pod": "pods",
    "ConfigMap": "configmaps",
    "Role": "roles",
    "RoleBinding": "rolebindings",
    "ClusterRole": "clusterroles",
    "ClusterRoleBinding": "clusterrolebindings",
}


def parsed_fixture(manifest):
    cluster = manifest["kind"] in {"Namespace", "ClusterRole", "ClusterRoleBinding"}
    resource = ApiResource(
        verification.RBAC_GROUP if manifest["kind"].startswith(("Role", "ClusterRole")) else "",
        "v1",
        PLURALS[manifest["kind"]],
        manifest["kind"],
        not cluster,
        frozenset({"get", "list", "watch", "patch"}),
    )
    record = resource_record(
        resource,
        {
            **manifest,
            "metadata": {
                **manifest["metadata"],
                "uid": "fixture-" + manifest["metadata"]["name"],
                "resourceVersion": "fixture",
            },
        },
        manifest["metadata"].get("namespace"),
    )
    return resource, record


def test_fixtures_pin_two_namespace_account_identities_and_disable_credential_mounts():
    manifests = verification.fixture_manifests()
    assert {value["metadata"]["name"] for value in manifests if value["kind"] == "Namespace"} == {
        verification.NAMESPACE,
        verification.OTHER_NAMESPACE,
    }
    accounts = [value for value in manifests if value["kind"] == "ServiceAccount"]
    assert {(value["metadata"]["namespace"], value["metadata"]["name"]) for value in accounts} == {
        (verification.NAMESPACE, verification.SERVICEACCOUNT),
        (verification.OTHER_NAMESPACE, verification.SERVICEACCOUNT),
    }
    pods = [value for value in manifests if value["kind"] == "Pod"]
    assert len(pods) == 2 and all(
        value["spec"]["containers"][0]["image"] == SHELL_IMAGE and "@sha256:" in SHELL_IMAGE
        for value in pods
    )
    assert all(
        value["spec"]["serviceAccountName"] == verification.SERVICEACCOUNT
        and value["spec"]["automountServiceAccountToken"] is False
        and value["spec"]["terminationGracePeriodSeconds"] == 0
        for value in pods
    )
    assert all(value["automountServiceAccountToken"] is False for value in accounts)
    assert not any(value["kind"] == "Secret" for value in manifests)
    assert "@sha256:" in NODE_IMAGE


def test_restricted_fixture_grants_named_reads_and_subresources_without_unfiltered_or_write_access():
    manifest = next(
        value
        for value in verification.fixture_manifests()
        if value["kind"] == "Role"
        and value["metadata"]["name"] == verification.ROLE
        and value["metadata"]["namespace"] == verification.NAMESPACE
    )
    resource, record = parsed_fixture(manifest)
    role = parse_rbac_role(resource, record)
    pods = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}))
    question = verification.access(pods, verification.NS, name=verification.POD)
    assert any(rule_matches(rule, question) for rule in role.rules)
    assert any(rule_matches(rule, replace(question, subresource="log")) for rule in role.rules)
    assert any(rule_matches(rule, replace(question, verb="list")) for rule in role.rules)
    assert not any(
        rule_matches(rule, replace(question, verb="list", name=None)) for rule in role.rules
    )
    assert not any(rule_matches(rule, replace(question, verb="patch")) for rule in role.rules)
    assert not any(rule_matches(rule, replace(question, name="owned-other")) for rule in role.rules)


def test_scoped_clusterrole_binding_cannot_grant_cluster_or_nonresource_questions():
    declarations = verification.fixture_manifests()
    manifest = next(
        value
        for value in declarations
        if value["kind"] == "RoleBinding" and value["metadata"]["name"] == "owned-scoped-shared"
    )
    resource, record = parsed_fixture(manifest)
    binding = parse_rbac_binding(resource, record)
    assert binding.role_kind == "ClusterRole" and binding_applies(binding, verification.NS)
    assert not binding_applies(binding, verification.ALL) and not binding_applies(
        binding, verification.CLUSTER
    )
    assert not any(
        value["kind"] == "ClusterRoleBinding" and value["roleRef"]["name"] == "owned-scoped-shared"
        for value in declarations
    )
    cluster_role = next(
        value
        for value in declarations
        if value["kind"] == "ClusterRole" and value["metadata"]["name"] == "owned-scoped-shared"
    )
    resource, record = parsed_fixture(cluster_role)
    role = parse_rbac_role(resource, record)
    assert any(rule_matches(rule, NonResourceAccess("get", "/metrics")) for rule in role.rules)


def test_aggregate_fixture_retains_empty_initial_materialized_rules_and_explicit_contributor():
    declarations = verification.fixture_manifests()
    aggregate = next(
        value
        for value in declarations
        if value["kind"] == "ClusterRole" and value["metadata"]["name"] == verification.AGGREGATE
    )
    contributor = next(
        value
        for value in declarations
        if value["kind"] == "ClusterRole" and value["metadata"]["name"] == verification.CONTRIBUTOR
    )
    assert aggregate["rules"] == []
    assert aggregate["aggregationRule"]["clusterRoleSelectors"] == [
        {"matchLabels": contributor["metadata"]["labels"]}
    ]
    assert contributor["rules"][0]["verbs"] == ["get", "patch"]
    binding = next(
        value
        for value in declarations
        if value["kind"] == "ClusterRoleBinding"
        and value["metadata"]["name"] == verification.AGGREGATE
    )
    assert {value["kind"] for value in binding["subjects"]} == {"User", "Group"}
    assert not any(value["kind"] == "ServiceAccount" for value in binding["subjects"])


def test_review_receipt_allowlist_omits_credentials_unknown_fields_and_private_reasons():
    body = {
        "kind": "SelfSubjectAccessReview",
        "token": "PRIVATE",
        "spec": {
            "resourceAttributes": {
                "verb": "list",
                "resource": "pods",
                "namespace": "synthetic",
                "fieldSelector": {"rawSelector": "metadata.name=owned"},
                "labelSelector": {"rawSelector": "owned=yes"},
                "token": "PRIVATE",
                "extra": {"private": "PRIVATE"},
            },
            "credentials": "PRIVATE",
        },
    }
    receipt = verification.review_receipt(ACCESS_PATH, body)
    assert receipt["spec"]["resourceAttributes"]["fieldSelector"] == {
        "rawSelector": "metadata.name=owned"
    }
    assert receipt["spec"]["resourceAttributes"]["labelSelector"] == {"rawSelector": "owned=yes"}
    assert "PRIVATE" not in json.dumps(receipt)
    assert (
        verification.review_receipt(IDENTITY_PATH, {"kind": "SelfSubjectReview", "spec": {}})[
            "spec"
        ]
        == {}
    )
    assert verification.review_receipt(
        RULES_PATH, {"kind": "SelfSubjectRulesReview", "spec": {"namespace": "synthetic"}}
    )["spec"] == {"namespace": "synthetic"}
    assert verification.review_receipt(
        ACCESS_PATH,
        {
            "spec": {
                "nonResourceAttributes": {"verb": "get", "path": "/version", "secret": "PRIVATE"}
            }
        },
    )["spec"] == {"nonResourceAttributes": {"verb": "get", "path": "/version"}}
    with pytest.raises(AssertionError):
        verification.review_receipt("/arbitrary", body)


@pytest.mark.asyncio
async def test_receipts_wrap_real_owned_http_without_fabricating_status_or_recording_server_reasons(
    tmp_path,
):
    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.method == "POST":
            body = await request.json()
            assert body["spec"]["resourceAttributes"]["name"] == "one"
            return web.json_response(
                {
                    "apiVersion": "authorization.k8s.io/v1",
                    "kind": "SelfSubjectAccessReview",
                    "status": {
                        "allowed": False,
                        "denied": False,
                        "reason": "PRIVATE-server-reason",
                    },
                },
                status=201,
            )
        if request.path.endswith("/denied"):
            return web.json_response({"message": "PRIVATE-server-reason"}, status=403)
        return web.json_response(item())

    receipts = []
    async with authorization_session(tmp_path, handler) as session:
        reader = ResourceReader(session)
        resource = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}))
        with verification.trace_api(receipts):
            read = await reader.get(resource, "one", "team")
            request = verification.question(
                SessionIdentity("owned", 1),
                verification.access(resource, verification.NS, name="one"),
            )
            review = await AuthorizationReader(reader.session).review(request)
            with pytest.raises(HttpProblem) as denied:
                await reader.get(resource, "denied", "team")
            assert denied.value.status == 403
        assert review.decision is ReviewDecision.NO_ALLOW and review.status is EvidenceStatus.READY
        assert read.uid == "owned-one" and len(receipts) == len(calls) == 3
        assert receipts[1]["decision_booleans"] == {"allowed": False, "denied": False}
        assert receipts[2]["http_status"] == 403
        assert receipts[0]["http_success"] and receipts[1]["http_success"]
        assert "PRIVATE" not in json.dumps(receipts)
        await reader.get(resource, "one", "team")
        assert len(receipts) == 3 and len(calls) == 4


@pytest.mark.asyncio
async def test_receipt_bound_refuses_additional_network_work(tmp_path, monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(item())

    monkeypatch.setattr(verification, "MAX_RECEIPTS", 1)
    receipts = [{}]
    async with reader_fixture(tmp_path, handler) as reader:
        resource = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get"}))
        with verification.trace_api(receipts), pytest.raises(AssertionError, match="finite bound"):
            await reader.get(resource, "one", "team")
    assert not calls and len(receipts) == 1


def test_source_hashes_bind_assets_all_production_inputs_and_verifier(tmp_path):
    names = (
        "src/kuberich/domain/authorization.py",
        "src/kuberich/services/authorization.py",
        "src/kuberich/ui/styles.tcss",
        "pyproject.toml",
        "uv.lock",
        "scripts/owned_kind.py",
        "scripts/verify_authorization_kind.py",
    )
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen-source")
    cache = tmp_path / "src/kuberich/__pycache__/generated.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated")
    before = verification.input_hashes(tmp_path)
    assert set(before) == set(names)
    cache.write_bytes(b"other-generated")
    assert verification.input_hashes(tmp_path) == before
    (tmp_path / "src/kuberich/ui/styles.tcss").write_text("changed")
    assert verification.input_hashes(tmp_path) != before


def test_stage_receipt_preserves_actual_failure_observations_before_assertion(tmp_path):
    verification.checkpoint(
        tmp_path, "before-assertion", expected_uid="owned-old", observed_uid="owned-new", rows=0
    )
    verification.checkpoint(tmp_path, "cleanup-observed", private_sessions_deleted=False)
    receipts = [
        json.loads(line)
        for line in (tmp_path / "authorization-stages.jsonl").read_text().splitlines()
    ]
    assert receipts[0]["expected_uid"] != receipts[0]["observed_uid"]
    assert receipts[0]["rows"] == 0 and not receipts[-1]["private_sessions_deleted"]
    assert json.loads((tmp_path / "authorization-stage.json").read_text()) == receipts[-1]


@pytest.mark.asyncio
async def test_cleanup_attempts_every_owner_even_when_a_client_close_fails():
    closed = []

    async def good():
        await asyncio.sleep(0)
        closed.append("good")

    async def bad():
        closed.append("bad")
        raise ValueError("PRIVATE-close-failure")

    async def service():
        closed.append("sessions")

    with pytest.raises(ValueError):
        await verification.close_sessions(
            [SimpleNamespace(close=good), SimpleNamespace(close=bad)],
            SimpleNamespace(close=service),
        )
    assert set(closed) == {"good", "bad", "sessions"}


@pytest.mark.asyncio
async def test_owned_cleanup_drains_through_parent_cancellation():
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def close():
        started.set()
        await release.wait()
        finished.set()

    cleanup = asyncio.create_task(verification.close_sessions([], SimpleNamespace(close=close)))
    waiter = asyncio.create_task(finish_owned(cleanup))
    await started.wait()
    waiter.cancel()
    await asyncio.sleep(0)
    assert not cleanup.cancelled() and not finished.is_set()
    release.set()
    await waiter
    assert finished.is_set() and cleanup.done()


@pytest.mark.asyncio
async def test_outer_verification_deadline_closes_sessions_and_retains_failure_without_cluster_access(
    tmp_path, monkeypatch
):
    config = tmp_path / "owned-kubeconfig"
    config.write_text("synthetic-private-bytes")
    events = []

    class Sessions:
        def __init__(self, catalog, request):
            assert request.kubeconfig == str(config)

        async def connect(self, context):
            events.append("connect")
            await asyncio.Event().wait()

        async def close(self):
            events.append("closed")

    monkeypatch.setattr(verification, "load_catalog", lambda *_: object())
    monkeypatch.setattr(verification, "SessionService", Sessions)
    monkeypatch.setattr(verification, "VERIFY_SECONDS", 0.05)
    monkeypatch.setattr(verification, "CLEANUP_SECONDS", 0.02)
    before = dict(os.environ)
    cluster = OwnedCluster(
        "kuberich-test-fixture", config, tmp_path, "kind-kuberich-test-fixture", ("owned-node",)
    )
    with pytest.raises(TimeoutError):
        await verification.verify(cluster, tmp_path / "evidence")
    assert events == ["connect", "closed"] and config.read_text() == "synthetic-private-bytes"
    assert dict(os.environ) == before
    receipts = [
        json.loads(line)
        for line in (tmp_path / "evidence/authorization-stages.jsonl").read_text().splitlines()
    ]
    assert any(value.get("failure_type") == "TimeoutError" for value in receipts)
    assert receipts[-1]["private_sessions_deleted"]
    assert json.loads((tmp_path / "evidence/authorization-api.json").read_text()) == []


def run_main_fixture(
    tmp_path, monkeypatch, *, fail=False, cleanup_fail=False, source_changed=False
):
    events = []
    private = tmp_path / "private"
    config = private / "owned-kubeconfig"
    evidence = tmp_path / "evidence/authorization.json"

    @contextmanager
    def owned(kind, *, docker):
        assert kind == "/verified/kind" and docker == "/verified/docker"
        private.mkdir()
        config.write_text("PRIVATE-owned-material")
        events.append("created")
        try:
            yield OwnedCluster(
                "kuberich-test-fixture",
                config,
                private,
                "kind-kuberich-test-fixture",
                ("owned-node",),
            )
        finally:
            config.unlink()
            private.rmdir()
            events.append("deleted")
            if cleanup_fail:
                raise RuntimeError("PRIVATE-cleanup-failure")

    async def verify(cluster, directory):
        verification.checkpoint(
            directory,
            "real-observations-before-controlled-test-result",
            expected_uid="owned-old",
            observed_uid="owned-new",
        )
        if fail:
            raise AssertionError("PRIVATE-assertion-message")
        return {"checks": ["fixture-test-control"]}

    calls = []

    def inputs(root):
        calls.append(root)
        return {"source": "changed" if source_changed and len(calls) > 1 else "frozen"}

    monkeypatch.setattr(verification, "owned_cluster", owned)
    monkeypatch.setattr(verification, "verify", verify)
    monkeypatch.setattr(verification, "input_hashes", inputs)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_authorization_kind",
            "--kind",
            "/verified/kind",
            "--docker",
            "/verified/docker",
            "--evidence",
            str(evidence),
        ],
    )
    return events, evidence


@pytest.mark.parametrize("failure", [False, True])
def test_main_verifies_owned_deletion_and_preserves_failure_without_exporting_exception_value(
    tmp_path, monkeypatch, failure
):
    events, evidence = run_main_fixture(tmp_path, monkeypatch, fail=failure)
    if failure:
        with pytest.raises(AssertionError):
            verification.main()
    else:
        verification.main()
    receipt = json.loads(evidence.read_text())
    assert events == ["created", "deleted"]
    assert receipt["status"] == ("failed" if failure else "passed")
    assert (
        receipt["owned_cluster_deleted"]
        and receipt["private_directory_deleted"]
        and receipt["inputs_unchanged"]
    )
    assert receipt["deadline_seconds"] == 600 and receipt["environment_unchanged"]
    assert "PRIVATE" not in evidence.read_text()
    if failure:
        assert receipt["failure_type"] == "AssertionError"


def test_cleanup_failure_never_claims_verified_cluster_absence(tmp_path, monkeypatch):
    events, evidence = run_main_fixture(tmp_path, monkeypatch, cleanup_fail=True)
    with pytest.raises(RuntimeError):
        verification.main()
    receipt = json.loads(evidence.read_text())
    assert events == ["created", "deleted"] and receipt["status"] == "failed"
    assert not receipt["owned_cluster_deleted"] and receipt["private_directory_deleted"]
    assert receipt["failure_type"] == "RuntimeError" and "PRIVATE" not in evidence.read_text()


def test_source_change_after_real_work_cannot_pass(tmp_path, monkeypatch):
    _, evidence = run_main_fixture(tmp_path, monkeypatch, source_changed=True)
    with pytest.raises(AssertionError):
        verification.main()
    assert not json.loads(evidence.read_text())["inputs_unchanged"]


@pytest.mark.parametrize(
    "name",
    [
        "authorization.json",
        "authorization-stage.json",
        "authorization-stages.jsonl",
        "authorization-api.json",
        "authorization-native-role.svg",
    ],
)
def test_prior_outcomes_stages_and_native_receipts_are_never_overwritten(
    tmp_path, monkeypatch, name
):
    evidence = tmp_path / "authorization.json"
    retained = tmp_path / name
    retained.write_text("retained-failure")
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_authorization_kind", "--kind", "/verified/kind", "--evidence", str(evidence)],
    )
    with pytest.raises(ValueError, match="fresh evidence"):
        verification.main()
    assert retained.read_text() == "retained-failure"
    assert not evidence.exists() or evidence == retained


@pytest.mark.asyncio
async def test_actual_review403_receipt_classifies_unknown_without_recording_response_body(
    tmp_path,
):
    async def handler(request):
        return web.json_response({"message": "PRIVATE-forbidden-body"}, status=403)

    receipts = []
    async with authorization_session(tmp_path, handler) as session:
        with verification.trace_api(receipts):
            request = verification.question(
                SessionIdentity("owned", 1), NonResourceAccess("get", "/version")
            )
            result = await AuthorizationReader(session).review(request)
    assert result.decision is ReviewDecision.UNKNOWN and result.status is EvidenceStatus.FORBIDDEN
    assert receipts[0]["http_status"] == 403 and "PRIVATE" not in json.dumps(receipts)


@pytest.mark.asyncio
async def test_cleanup_timeout_cancels_and_drains_every_blocked_owner(monkeypatch):
    cancelled = []

    async def close():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(verification, "CLEANUP_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        await verification.close_sessions(
            [SimpleNamespace(close=close)], SimpleNamespace(close=close)
        )
    assert cancelled == [True, True]


def test_primary_failure_and_cleanup_failure_are_both_preserved(tmp_path, monkeypatch):
    _, evidence = run_main_fixture(tmp_path, monkeypatch, fail=True, cleanup_fail=True)
    with pytest.raises(RuntimeError):
        verification.main()
    receipt = json.loads(evidence.read_text())
    assert receipt["failure_type"] == "AssertionError"
    assert receipt["cleanup_failure_type"] == "RuntimeError"
    assert not receipt["owned_cluster_deleted"]
    assert "PRIVATE" not in evidence.read_text()


def test_invalid_review_kind_and_nonstring_selector_metadata_cannot_leak_into_receipts():
    receipt = verification.review_receipt(
        ACCESS_PATH,
        {
            "kind": {"token": "PRIVATE"},
            "spec": {
                "resourceAttributes": {
                    "verb": "get",
                    "fieldSelector": {"rawSelector": 1},
                    "labelSelector": "PRIVATE",
                }
            },
        },
    )
    assert receipt["kind"] == "invalid" and receipt["spec"] == {
        "resourceAttributes": {"verb": "get"}
    }
    assert "PRIVATE" not in json.dumps(receipt)
