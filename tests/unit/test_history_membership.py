"""Exact current owner chains cannot establish historical membership or replacement identity."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.history import current_history_members
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    ResourceSnapshot,
    resource_record,
)
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

SESSION = SessionIdentity("synthetic", 1)
VERBS = frozenset({"get", "list", "watch"})
PODS = ApiResource("", "v1", "pods", "Pod", True, VERBS)
DEPLOYMENTS = ApiResource("apps", "v1", "deployments", "Deployment", True, VERBS)
REPLICASETS = ApiResource("apps", "v1", "replicasets", "ReplicaSet", True, VERBS)
JOBS = ApiResource("batch", "v1", "jobs", "Job", True, VERBS)
CRONJOBS = ApiResource("batch", "v1", "cronjobs", "CronJob", True, VERBS)


def target(resource=DEPLOYMENTS):
    return ResourceTarget(SESSION, resource.group, resource.name, "team", "root", "root-uid")


def record(resource=PODS, name="pod", uid="pod-uid", owner=None, *, namespace="team", owners=None):
    metadata = {
        "name": name,
        "uid": uid,
        "namespace": namespace,
        "resourceVersion": "1",
        "creationTimestamp": "2026-01-01T00:00:00Z",
    }
    if owner is not None:
        metadata["ownerReferences"] = [
            {
                "apiVersion": owner[0].api_version,
                "kind": owner[0].kind,
                "name": owner[1],
                "uid": owner[2],
                "controller": True,
            }
        ]
    if owners is not None:
        metadata["ownerReferences"] = owners
    return resource_record(resource, {"metadata": metadata})


def snapshot(items=(), resource=PODS, **changes):
    return ResourceSnapshot(resource, "team", "1", tuple(items), **changes)


def test_deployment_projection_rechecks_pod_uids_and_exact_intermediate_controller():
    parent = record(REPLICASETS, "replica", "replica-uid", (DEPLOYMENTS, "root", "root-uid"))
    pod = record(owner=(REPLICASETS, "replica", "replica-uid"))
    unrelated = record(name="unrelated", uid="other", owner=(REPLICASETS, "other", "other-uid"))
    pods = snapshot((pod, unrelated))
    evidence = current_history_members(
        target(), DEPLOYMENTS, pods, snapshot((parent,), REPLICASETS), pods
    )
    assert evidence.mode == "current-members" and evidence.status == "current-only"
    assert evidence.observed_at is None and len(evidence.members) == 1
    member = evidence.members[0]
    assert (member.namespace, member.pod, member.uid, member.owner_uid) == (
        "team",
        "pod",
        "pod-uid",
        "replica-uid",
    )
    assert member.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert len(evidence.fingerprint) == 64 and evidence.detail_code == "current-members-projection"
    replaced = replace(pod, uid="replacement")
    changed = current_history_members(
        target(),
        DEPLOYMENTS,
        pods,
        snapshot((parent,), REPLICASETS),
        snapshot((replaced, unrelated)),
    )
    assert (
        changed.status == "partial"
        and changed.members == ()
        and changed.fingerprint != evidence.fingerprint
    )
    assert (
        current_history_members(
            target(),
            DEPLOYMENTS,
            snapshot(reversed(pods.items)),
            snapshot((parent,), REPLICASETS),
            pods,
        ).fingerprint
        == evidence.fingerprint
    )


def test_direct_owner_and_cronjob_chains_have_distinct_current_fingerprints():
    direct = ApiResource("apps", "v1", "statefulsets", "StatefulSet", True, VERBS)
    pod = record(owner=(direct, "root", "root-uid"))
    stable = snapshot((pod,))
    direct_evidence = current_history_members(target(direct), direct, stable, None, stable)
    assert len(direct_evidence.members) == 1
    job = record(JOBS, "job", "job-uid", (CRONJOBS, "root", "root-uid"))
    cron_pod = record(owner=(JOBS, "job", "job-uid"))
    stable = snapshot((cron_pod,))
    evidence = current_history_members(
        target(CRONJOBS), CRONJOBS, stable, snapshot((job,), JOBS), stable
    )
    assert len(evidence.members) == 1 and evidence.fingerprint != direct_evidence.fingerprint
    pod_target = ResourceTarget(SESSION, "", "pods", "team", "pod", "pod-uid")
    assert len(current_history_members(pod_target, PODS, stable, None, stable).members) == 1
    assert (
        current_history_members(
            replace(pod_target, uid="replaced"), PODS, stable, None, stable
        ).members
        == ()
    )
    assert (
        current_history_members(
            replace(pod_target, name="other"), PODS, stable, None, stable
        ).members
        == ()
    )


def test_missing_limited_and_duplicate_reverification_captures_remain_incomplete():
    pods = snapshot((record(owner=(REPLICASETS, "replica", "replica-uid")),))
    assert (
        current_history_members(target(), DEPLOYMENTS, pods, None, pods).detail_code
        == "owners-missing"
    )
    parent = record(REPLICASETS, "replica", "replica-uid", (DEPLOYMENTS, "root", "root-uid"))
    parents = snapshot((parent,), REPLICASETS)
    assert (
        current_history_members(
            target(),
            DEPLOYMENTS,
            replace(pods, collection=CollectionState(False, True)),
            parents,
            pods,
        ).status
        == "partial"
    )
    assert (
        current_history_members(
            target(),
            DEPLOYMENTS,
            pods,
            replace(parents, collection=CollectionState(False, True)),
            pods,
        ).status
        == "partial"
    )
    assert (
        current_history_members(target(), DEPLOYMENTS, pods, parents, snapshot()).status
        == "partial"
    )
    assert (
        current_history_members(
            target(), DEPLOYMENTS, pods, parents, snapshot((*pods.items, *pods.items))
        ).status
        == "partial"
    )
    with pytest.raises(AppError, match="duplicate"):
        current_history_members(
            target(), DEPLOYMENTS, snapshot((*pods.items, *pods.items)), parents, pods
        )
    no_uid = replace(pods.items[0], uid=None)
    assert (
        current_history_members(
            target(), DEPLOYMENTS, snapshot((no_uid,)), parents, snapshot((no_uid,))
        ).status
        == "partial"
    )
    for supplied, after, intermediates, code in [
        (snapshot(pods.items * 257), pods, parents, "member-limit"),
        (pods, snapshot(pods.items * 257), parents, "member-limit"),
        (pods, pods, snapshot(parents.items * 257, REPLICASETS), "owner-limit"),
    ]:
        assert (
            current_history_members(
                target(), DEPLOYMENTS, supplied, intermediates, after
            ).detail_code
            == code
        )


@pytest.mark.parametrize(
    "changes",
    [
        "target",
        "pod-resource",
        "after-resource",
        "pod-namespace",
        "after-namespace",
        "owner-resource",
        "owner-namespace",
    ],
)
def test_membership_requires_the_captured_resource_family_and_scope(changes):
    selected = target()
    resource = DEPLOYMENTS
    pods = snapshot()
    after = pods
    intermediates = snapshot(resource=REPLICASETS)
    if changes == "target":
        selected = replace(selected, group="batch")
    elif changes == "pod-resource":
        pods = replace(pods, resource=DEPLOYMENTS)
    elif changes == "after-resource":
        after = replace(after, resource=DEPLOYMENTS)
    elif changes == "pod-namespace":
        pods = replace(pods, namespace="other")
    elif changes == "after-namespace":
        after = replace(after, namespace="other")
    elif changes == "owner-resource":
        intermediates = replace(intermediates, resource=JOBS)
    else:
        intermediates = replace(intermediates, namespace="other")
    with pytest.raises(AppError):
        current_history_members(selected, resource, pods, intermediates, after)


@pytest.mark.parametrize("owners", ["bad", [{}] * 129])
def test_malformed_controller_evidence_is_a_failure_not_healthy_empty_membership(owners):
    pod = record(owners=owners)
    stable = snapshot((pod,))
    with pytest.raises(AppError, match="owner references"):
        current_history_members(target(REPLICASETS), REPLICASETS, stable, None, stable)


def test_owner_names_and_labels_do_not_replace_exact_uids_or_controller_flags():
    direct = REPLICASETS
    valid = {
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "name": "root",
        "uid": "root-uid",
        "controller": True,
    }
    for changes in (
        {"uid": "other"},
        {"name": "other"},
        {"kind": "Deployment"},
        {"apiVersion": "batch/v1"},
        {"controller": False},
        {"uid": None},
        {"apiVersion": None},
    ):
        pod = record(owners=[{**valid, **changes}])
        stable = snapshot((pod,))
        assert current_history_members(target(direct), direct, stable, None, stable).members == ()
    no_owner = record(owners=[None, {}])
    stable = snapshot((no_owner,))
    assert current_history_members(target(direct), direct, stable, None, stable).members == ()
    wrong_parent = record(REPLICASETS, "replica", "replica-uid", (DEPLOYMENTS, "root", "other"))
    missing_uid = replace(wrong_parent, uid=None)
    stable = snapshot((record(owner=(REPLICASETS, "replica", "replica-uid")),))
    assert (
        current_history_members(
            target(),
            DEPLOYMENTS,
            stable,
            snapshot((wrong_parent, missing_uid), REPLICASETS),
            stable,
        ).members
        == ()
    )
    foreign = record(namespace="other", owner=(REPLICASETS, "root", "root-uid"))
    stable = snapshot((foreign,))
    assert current_history_members(target(direct), direct, stable, None, stable).members == ()


def test_reparented_same_uid_pod_is_not_a_current_verified_member():
    parent = record(REPLICASETS, "replica", "replica-uid", (DEPLOYMENTS, "root", "root-uid"))
    for resource, owner, intermediates in (
        (DEPLOYMENTS, (REPLICASETS, "replica", "replica-uid"), snapshot((parent,), REPLICASETS)),
        (REPLICASETS, (REPLICASETS, "root", "root-uid"), None),
    ):
        pod = record(owner=owner)
        for changed in (
            record(owner=(REPLICASETS, "other", "other-uid")),
            record(owner=(JOBS, owner[1], owner[2])),
        ):
            evidence = current_history_members(
                target(resource), resource, snapshot((pod,)), intermediates, snapshot((changed,))
            )
            assert evidence.status == "partial" and evidence.members == ()
    duplicate = {
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "name": "root",
        "uid": "root-uid",
        "controller": True,
    }
    pod = record(owners=[duplicate, duplicate])
    with pytest.raises(AppError, match="Ambiguous"):
        current_history_members(
            target(REPLICASETS), REPLICASETS, snapshot((pod,)), None, snapshot((pod,))
        )
    # Discovery may advertise additional supported verbs on the same served intermediate.
    extra = replace(REPLICASETS, verbs=VERBS | {"create"})
    pod = record(owner=(REPLICASETS, "replica", "replica-uid"))
    stable = snapshot((pod,))
    assert current_history_members(
        target(), DEPLOYMENTS, stable, snapshot((parent,), extra), stable
    ).members


def test_missing_member_creation_time_is_fingerprinted_without_invention():
    pod = replace(record(owner=(REPLICASETS, "root", "root-uid")), created_at=None)
    stable = snapshot((pod,))
    evidence = current_history_members(target(REPLICASETS), REPLICASETS, stable, None, stable)
    assert evidence.members[0].created_at is None and evidence.fingerprint
