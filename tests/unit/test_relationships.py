"""Identity, ownership, selectors and endpoint evidence keep distinct meanings."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.relationships import (
    MAX_FACT_BYTES,
    MAX_FACT_ITEMS,
    MAX_RELATIONSHIP_BYTES,
    DeclaredReference,
    LabelRequirement,
    RelationDirection,
    RelationKind,
    RelationshipBookmark,
    RelationshipEvidence,
    RelationshipMode,
    RelationshipRequest,
    RelationshipRow,
    RelationshipScope,
    RelationshipSelector,
    RelationshipSnapshot,
    RelationshipSource,
    RelationshipStatus,
    endpoint_references,
    endpoint_service_names,
    fact_list,
    fact_mapping,
    fact_name,
    native_selector,
    node_reference,
    owner_references,
    reference_for,
    reference_status,
    relationship_actionable,
    relationship_cycle,
    relationship_identity,
    relationship_manifest,
    relationship_object_key,
    relationship_path_key,
    resolve_reference,
    resource_labels,
    selector_matches,
)
from kuberich.domain.resources import CollectionState, Discovery
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from tests.support.relationships import (
    CONFIGMAPS,
    DEPLOYMENTS,
    ENDPOINTS,
    NODES,
    PODS,
    SERVICES,
    SLICES,
    descriptor,
    owner,
    record,
    ref,
)


def test_immutable_publication_and_cluster_root_search_namespace_are_independent():
    target = ResourceTarget(
        SessionIdentity("synthetic", 1), "", "nodes", None, "example", "example-uid"
    )
    scope = RelationshipScope(target, NODES, "team", RelationshipMode.XRAY)
    request = RelationshipRequest(scope, 1, frozenset({()}))
    root = ref(NODES)
    row = RelationshipRow((), root, None, None, None, RelationshipStatus.READY, root.uid, (), True)
    instant = datetime.now(UTC)
    source = RelationshipSource(
        "pods", "team", RelationshipStatus.READY, CollectionState(), "1", "Observed", instant
    )
    snapshot = RelationshipSnapshot(request, (row,), (source,), 1, instant)
    bookmark = RelationshipBookmark(root, RelationshipMode.USED_BY, frozenset({()}))
    assert snapshot.request.scope.namespace == "team"
    assert snapshot.request.scope.root.namespace is None
    assert bookmark.root.uid == row.observed_uid
    assert source.observed_at == snapshot.observed_at
    assert (
        RelationshipSource("pods", None, RelationshipStatus.LOADING, None, None, "").observed_at
        is None
    )
    with pytest.raises(FrozenInstanceError):
        row.status = RelationshipStatus.MISSING
    assert not hasattr(snapshot, "__dict__")
    assert {str(value) for value in RelationKind} == {
        "owner",
        "controller_owner",
        "selector",
        "endpoint",
        "node",
        "reference",
    }
    assert str(RelationDirection.INCOMING) == "incoming"
    assert str(RelationshipEvidence.DECLARED) == "declared"


def test_served_versions_share_identity_while_recreated_uids_do_not():
    old = descriptor("widgets", "Widget", "example.test", version="v1beta1")
    new = replace(old, version="v1")
    original, served = ref(old), ref(new)
    assert relationship_identity(original) == relationship_identity(served)
    assert relationship_object_key(original) == relationship_object_key(
        replace(served, uid="replacement")
    )
    assert relationship_identity(original) != relationship_identity(
        replace(served, uid="replacement")
    )
    assert reference_for(old, record(old)) == original
    unresolved = replace(original, resource=None)
    assert relationship_object_key(unresolved)[1] == "kind:Widget"
    assert relationship_cycle(served, (original,))
    assert not relationship_cycle(replace(served, uid="replacement"), (original,))
    assert not relationship_cycle(served, (ref(PODS),))
    assert not relationship_cycle(
        served, ()
    )  # Shared node in a different branch is not an ancestor.
    assert relationship_path_key(("a", "bc")) != relationship_path_key(("ab", "c"))
    assert relationship_path_key(()) == relationship_path_key(())


def test_discovery_exact_version_fallback_unknown_and_ambiguity():
    old = descriptor("widgets", "Widget", "example.test", version="v1beta1")
    new = replace(old, version="v1")
    reference = replace(ref(old), resource=None)
    assert resolve_reference(Discovery((new, old)), reference).resource == old
    assert resolve_reference(Discovery((new,)), reference).resource == new
    assert resolve_reference(Discovery((PODS,)), reference).resource is None
    collision = replace(old, name="otherwidgets")
    with pytest.raises(AppError, match="ambiguous"):
        resolve_reference(Discovery((old, collision)), reference)
    with pytest.raises(AppError, match="ambiguous"):
        resolve_reference(Discovery((new, replace(collision, version="v1"))), reference)
    # Exact GVK isolates unrelated mappings in other served versions.
    assert (
        resolve_reference(Discovery((old, replace(collision, version="v1"))), reference).resource
        == old
    )


@pytest.mark.parametrize(
    "observed,status",
    [
        (None, "missing"),
        (record(name="other"), "invalid"),
        (record(namespace="other"), "invalid"),
        (record(uid="replacement"), "replaced"),
        (record(), "ready"),
    ],
)
def test_reference_observation_preserves_expected_identity(observed, status):
    assert reference_status(ref(), observed) == status
    if observed is not None and observed.name == "example" and observed.namespace == "team":
        assert reference_status(replace(ref(), uid=None), observed) == "ready"


@pytest.mark.parametrize(
    "change,allowed",
    [
        ({}, True),
        ({"status": RelationshipStatus.REPLACED}, False),
        ({"ref": replace(ref(), resource=None)}, False),
        ({"ref": replace(ref(), resource=replace(PODS, verbs=frozenset()))}, False),
        ({"observed_uid": None}, False),
        ({"observed_uid": "replacement"}, False),
        ({"ref": replace(ref(), uid=None)}, True),
    ],
)
def test_navigation_requires_fresh_readable_uid(change, allowed):
    row = RelationshipRow(
        (), ref(), None, None, None, RelationshipStatus.READY, "example-uid", (), False
    )
    assert relationship_actionable(replace(row, **change)) is allowed


def test_owner_custom_chain_cluster_owner_and_noncontroller_keep_provenance():
    custom = descriptor("widgets", "Widget", "example.test")
    child = record(metadata={"ownerReferences": [owner(custom), owner(NODES, controller=False)]})
    owners = owner_references(PODS, child, Discovery((custom, NODES)))
    assert [item.target.resource for item in owners] == [custom, NODES]
    assert [item.target.namespace for item in owners] == ["team", None]
    assert [item.controller for item in owners] == [True, False]
    assert all(item.status == "ready" for item in owners)
    assert owners[0].path == "metadata.ownerReferences[0]"
    assert "expected UID" in owners[0].detail
    unknown = owner_references(PODS, child, Discovery(()))
    assert all(item.status == "unavailable" for item in unknown)
    assert owner_references(PODS, record(), Discovery(())) == ()


@pytest.mark.parametrize(
    "dependent,reference",
    [(PODS, owner(namespace="other")), (NODES, owner()), (PODS, owner(NODES, namespace="team"))],
)
def test_owner_namespace_rules_reject_cross_scope(dependent, reference):
    result = owner_references(
        dependent,
        record(dependent, metadata={"ownerReferences": [reference]}),
        Discovery((DEPLOYMENTS, NODES)),
    )
    assert result[0].status == "invalid"


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"apiVersion": "apps/v1", "kind": "Deployment", "name": "example"},
        owner(uid=None),
        owner(uid=""),
        owner(uid=42),
        owner(controller="true"),
        owner(kind="[red]"),
        owner(apiVersion="bad/group/v1"),
        owner(namespace="../other"),
        owner(name="bad/name"),
    ],
)
def test_invalid_owner_identity_never_turns_into_name_only_ownership(value):
    result = owner_references(
        PODS, record(metadata={"ownerReferences": [value]}), Discovery((DEPLOYMENTS,))
    )
    assert len(result) == 1
    assert result[0].status == "invalid"
    assert result[0].target.uid is None
    assert not result[0].controller
    assert "unproven" in result[0].detail


def test_ambiguous_owner_kind_is_visible_invalid_not_silently_dropped():
    result = owner_references(
        PODS,
        record(metadata={"ownerReferences": [owner()]}),
        Discovery((DEPLOYMENTS, replace(DEPLOYMENTS, name="otherdeployments"))),
    )
    assert result[0].status == "invalid"
    with pytest.raises(AppError, match="owner references"):
        owner_references(PODS, record(metadata={"ownerReferences": [owner()] * 129}), Discovery(()))
    with pytest.raises(AppError, match="list"):
        owner_references(PODS, record(metadata={"ownerReferences": {}}), Discovery(()))


@pytest.mark.parametrize(
    "function,value",
    [
        (fact_mapping, []),
        (fact_mapping, {str(i): 1 for i in range(MAX_FACT_ITEMS + 1)}),
        (fact_list, {}),
        (fact_list, [None] * (MAX_FACT_ITEMS + 1)),
        (fact_name, 3),
        (fact_name, "x" * 254),
        (fact_name, "[red]\n"),
        (fact_name, "../foo"),
    ],
)
def test_fact_validation_rejects_hostile_or_excessive_data(function, value):
    with pytest.raises(AppError):
        function(value)


def test_fact_mapping_list_names_and_manifest_limits():
    assert fact_mapping({}) == {}
    assert fact_list([]) == []
    assert fact_name("valid-name") == "valid-name"
    assert relationship_manifest(record())["kind"] == "Pod"
    for item in (
        replace(record(), metadata_only=True),
        record(metadata={"annotations": {"oversized": "x" * (MAX_RELATIONSHIP_BYTES + 1)}}),
    ):
        with pytest.raises(AppError, match="Incomplete or excessive"):
            relationship_manifest(item)


def test_structured_selector_has_full_operators_and_more_than_cli_eight_terms():
    labels = {f"key{i}": str(i) for i in range(16)}
    raw = {
        "matchLabels": labels,
        "matchExpressions": [
            {"key": "tier", "operator": "In", "values": ["api", "batch"]},
            {"key": "disabled", "operator": "NotIn", "values": ["true"]},
            {"key": "present", "operator": "Exists"},
            {"key": "absent", "operator": "DoesNotExist"},
        ],
    }
    selector = native_selector(DEPLOYMENTS, record(DEPLOYMENTS, spec={"selector": raw}))
    assert len(selector.requirements) == 20
    assert selector_matches(selector, {**labels, "tier": "api", "present": ""})
    assert selector_matches(
        selector, {**labels, "tier": "batch", "present": "yes", "disabled": "false"}
    )
    for missing in ("key0", "tier", "present"):
        actual = {**labels, "tier": "api", "present": ""}
        actual.pop(missing)
        assert not selector_matches(selector, actual)
    assert not selector_matches(selector, {**labels, "tier": "wrong", "present": ""})
    assert not selector_matches(
        selector, {**labels, "tier": "api", "present": "", "disabled": "true"}
    )
    assert not selector_matches(selector, {**labels, "tier": "api", "present": "", "absent": ""})


def test_empty_selector_semantics_and_absent_selectors_are_resource_specific():
    assert native_selector(CONFIGMAPS, record(CONFIGMAPS)) is None
    assert native_selector(DEPLOYMENTS, record(DEPLOYMENTS, spec={})) is None
    assert native_selector(DEPLOYMENTS, record(DEPLOYMENTS, spec={"selector": None})) is None
    for resource, matches in (
        (SERVICES, False),
        (DEPLOYMENTS, True),
        (descriptor("replicationcontrollers", "ReplicationController"), True),
    ):
        selected = native_selector(resource, record(resource, spec={"selector": {}}))
        assert selector_matches(selected, {}) is matches
    selected = native_selector(SERVICES, record(SERVICES, spec={"selector": {"app": ""}}))
    assert selector_matches(selected, {"app": ""})
    assert resource_labels(
        record(metadata={"labels": {"example.test/app": "api", "empty": ""}})
    ) == (("example.test/app", "api"), ("empty", ""))
    assert resource_labels(record()) == ()


@pytest.mark.parametrize(
    "expression",
    [
        {"key": "x", "operator": "Wrong"},
        {"key": "x", "operator": []},
        {"key": "x", "operator": "In", "values": []},
        {"key": "x", "operator": "NotIn"},
        {"key": "x", "operator": "Exists", "values": ["x"]},
        {"key": "x", "operator": "DoesNotExist", "values": ["x"]},
        {"key": "x", "operator": "In", "values": None},
    ],
)
def test_invalid_selector_cannot_prove_no_members(expression):
    with pytest.raises(AppError):
        native_selector(
            DEPLOYMENTS, record(DEPLOYMENTS, spec={"selector": {"matchExpressions": [expression]}})
        )
    with pytest.raises(AppError, match="operator"):
        selector_matches(RelationshipSelector((LabelRequirement("x", "Wrong", ()),)), {})


@pytest.mark.parametrize(
    "labels",
    [
        {"": "x"},
        {"bad/key/again": "x"},
        {"bad key": "x"},
        {"x" * 64: "x"},
        {"x": "x" * 64},
        {"x": 1},
        {"x" * 318: "x"},
        {"/name": "x"},
        {"BAD.EXAMPLE/name": "x"},
        {"example..test/name": "x"},
        {"example-.test/name": "x"},
        {"x" * 254 + "/x": "x"},
    ],
)
def test_invalid_labels_fail_closed(labels):
    with pytest.raises(AppError, match="label"):
        resource_labels(record(metadata={"labels": labels}))


def test_selector_and_label_aggregate_limits():
    labels = {f"label{i}": "x" * 63 for i in range(MAX_FACT_ITEMS)}
    # Valid labels alone can still exceed the input-byte budget.
    assert sum(len(k) + len(v) for k, v in labels.items()) < MAX_FACT_BYTES
    values = ["x" * 63] * MAX_FACT_ITEMS
    expressions = [{"key": "a", "operator": "In", "values": values}] * 2
    with pytest.raises(AppError, match="Excessive relationship selector"):
        native_selector(
            DEPLOYMENTS, record(DEPLOYMENTS, spec={"selector": {"matchExpressions": expressions}})
        )
    with pytest.raises(AppError, match="Excessive relationship selector"):
        native_selector(
            DEPLOYMENTS,
            record(
                DEPLOYMENTS,
                spec={
                    "selector": {
                        "matchLabels": labels,
                        "matchExpressions": [{"key": "x", "operator": "Exists"}],
                    }
                },
            ),
        )
    with pytest.raises(AppError, match="Excessive relationship labels"):
        resource_labels(record(metadata={"labels": {"x" * 200: "x" * MAX_FACT_BYTES}}))


def test_node_placement_uses_only_actual_node_name_and_not_scheduling_constraints():
    assert node_reference(DEPLOYMENTS, record(DEPLOYMENTS)) is None
    assert node_reference(PODS, record(spec={"nodeSelector": {"node": "candidate"}})) is None
    assert node_reference(PODS, record(spec={"nodeName": ""})) is None
    observed = node_reference(PODS, record(spec={"nodeName": "worker"}))
    assert observed == DeclaredReference(
        replace(ref(NODES), name="worker", uid=None, resource=None), "spec.nodeName", False
    )


def test_slice_and_legacy_endpoints_preserve_target_identity_and_port_readiness():
    target = {
        "apiVersion": "v1",
        "kind": "Pod",
        "name": "backend",
        "namespace": "different-valid-namespace",
        "uid": "backend-uid",
    }
    slice_record = record(
        SLICES,
        metadata={"labels": {"kubernetes.io/service-name": "web"}},
        ports=[{"name": "http", "port": 8080}, {"port": None, "protocol": "UDP"}],
        endpoints=[
            {
                "targetRef": target,
                "conditions": {"ready": True, "serving": True, "terminating": False},
            },
            {"targetRef": {**target, "uid": None}, "conditions": {"ready": False}},
            {"addresses": ["192.0.2.1"]},
        ],
    )
    assert endpoint_service_names(SLICES, slice_record) == ("web",)
    refs = endpoint_references(SLICES, slice_record)
    assert refs[0].target.namespace == "different-valid-namespace"
    assert refs[0].target.uid == "backend-uid"
    assert refs[1].target.uid is None
    assert [item.ready for item in refs] == [True, False, None]
    assert refs[2].target is None
    assert refs[0].ports == ("http:8080 / TCP", "-:? / UDP")
    assert "IP alone" in refs[2].details[0]
    assert refs[0].path == "endpoints[0].targetRef"
    assert refs[0].details[-2:] == ("serving=true", "terminating=false")
    assert refs[2].details[-2:] == ("serving=unknown", "terminating=unknown")
    known_pod = endpoint_references(
        SLICES, record(SLICES, endpoints=[{"targetRef": {"kind": "Pod", "name": "known-core"}}])
    )
    assert known_pod[0].target.api_version == "v1"
    legacy = record(
        ENDPOINTS,
        subsets=[
            {
                "ports": [{"port": 443, "protocol": "SCTP"}],
                "addresses": [{"targetRef": target}],
                "notReadyAddresses": [
                    {
                        "targetRef": {
                            key: value for key, value in target.items() if key != "namespace"
                        }
                    }
                ],
            }
        ],
    )
    assert endpoint_service_names(ENDPOINTS, legacy) == (legacy.name,)
    actual = endpoint_references(ENDPOINTS, legacy)
    assert [item.ready for item in actual] == [True, False]
    assert actual[1].target.namespace == "team"
    assert actual[1].ports == ("-:443 / SCTP",)
    assert endpoint_service_names(PODS, record()) == ()
    assert endpoint_service_names(SLICES, record(SLICES)) == ()
    assert endpoint_references(PODS, record()) == ()
    assert endpoint_references(SLICES, record(SLICES)) == ()
    assert endpoint_references(ENDPOINTS, record(ENDPOINTS)) == ()


@pytest.mark.parametrize(
    "fields",
    [
        {"ports": [{"port": 0}]},
        {"ports": [{"port": True}]},
        {"ports": [{"port": 65536}]},
        {"ports": [{"port": 80, "protocol": "HTTP"}]},
        {"ports": [{"port": 80, "protocol": []}]},
        {"ports": [{"name": 5}]},
        {"ports": [{"name": "bad/name"}]},
        {"endpoints": [{"conditions": {"ready": "true"}}]},
        {"endpoints": [{"conditions": {"serving": "true"}}]},
        {"endpoints": [{"conditions": {"terminating": "false"}}]},
        {"endpoints": [{"targetRef": {"kind": "Widget", "name": "unknown-group"}}]},
        {"endpoints": [{"targetRef": {"kind": "Pod", "name": "x", "namespace": "bad namespace"}}]},
        {"endpoints": [{"targetRef": {"name": "ip-is-not-identity"}}]},
        {"endpoints": [{"targetRef": {"apiVersion": "v1", "kind": "[red]", "name": "x"}}]},
    ],
)
def test_malformed_endpoint_evidence_marks_extraction_incomplete(fields):
    with pytest.raises(AppError):
        endpoint_references(SLICES, record(SLICES, **fields))


def test_endpoint_aggregate_limit_is_shared_across_legacy_subsets():
    subsets = [{"addresses": [{}] * 6000}, {"notReadyAddresses": [{}] * 4001}]
    with pytest.raises(AppError, match="Excessive relationship endpoints"):
        endpoint_references(ENDPOINTS, record(ENDPOINTS, subsets=subsets))


def test_unknown_structured_selector_fields_are_incomplete_instead_of_match_all():
    with pytest.raises(AppError, match="selector fields"):
        native_selector(
            DEPLOYMENTS, record(DEPLOYMENTS, spec={"selector": {"unknown": {"app": "api"}}})
        )


def test_selector_requirement_text_has_a_separate_aggregate_byte_bound():
    long_key = "a" * 253 + "/" + "b" * 63
    expressions = [{"key": long_key, "operator": "Exists"}] * 3400
    with pytest.raises(AppError, match="Excessive relationship selector"):
        native_selector(
            DEPLOYMENTS, record(DEPLOYMENTS, spec={"selector": {"matchExpressions": expressions}})
        )
