"""Independent admission declaration, literal identity, privacy and output contracts."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from kuberich.domain.curated import MAX_CURATED_DETAIL_BYTES, MAX_CURATED_DETAIL_ROWS
from kuberich.domain.curated_admission import FAMILIES, cells, details
from kuberich.domain.curated_navigation import (
    CollectionDestination,
    DeclaredObjectReference,
    PolicyBindingMatch,
    ReferenceDestination,
)
from kuberich.domain.resources import ResourceRecord, resource_record
from kuberich.errors import AppError
from tests.support.curated_admission import (
    BINDINGS,
    CANARIES,
    GROUP,
    KINDS,
    MUTATING_BINDINGS,
    MUTATING_POLICIES,
    POLICIES,
    admission_manifest,
    admission_record,
)


def values(name=POLICIES, manifest=None, variant=0, *, version="v1"):
    return dict(cells(*admission_record(name, variant, manifest=manifest, version=version)).values)


def inspected(name=POLICIES, manifest=None, *, version="v1"):
    return details(*admission_record(name, manifest=manifest, version=version))


def section(result, title):
    return next(item for item in result.sections if item.title == title)


def serialized(name=POLICIES, manifest=None, *, version="v1"):
    resource, record = admission_record(name, manifest=manifest, version=version)
    return json.dumps((asdict(cells(resource, record)), asdict(details(resource, record))))


def test_validating_policy_cells_are_typed_declarations_and_observed_generation():
    result = values()
    assert tuple(result) == (
        "match-rules",
        "match-conditions",
        "failure-policy",
        "param-kind",
        "validations",
        "observation",
    )
    assert [result[key].sort for key in ("match-rules", "match-conditions", "validations")] == [
        1,
        1,
        1,
    ]
    assert result["failure-policy"].text == "Fail"
    assert result["param-kind"].text == "v1 ConfigMap"
    assert result["observation"].text == "current generation"
    other = values(variant=1)
    assert other["validations"].sort == 2
    assert other["failure-policy"].text == "Ignore"
    assert other["observation"].text == "stale generation"
    assert tuple(family.resource for family in FAMILIES) == tuple(KINDS)


def test_binding_actions_are_configured_and_parameter_reference_has_request_scope():
    result = values(BINDINGS)
    assert tuple(result) == ("policy", "actions", "parameters", "match-rules")
    assert [result[key].text for key in ("policy", "actions", "parameters")] == [
        "owned-0",
        "Audit, Warn",
        "name",
    ]
    assert result["match-rules"].sort == 1
    output = inspected(BINDINGS)
    assert section(output, "Parameter reference (declared)").rows == (
        ("name", "owned-parameters", "omitted", "Deny"),
    )
    assert any("never the header namespace" in note for note in output.notices)
    assert any("both apply" in note for note in output.notices)
    assert all("Server-observed" not in item.title for item in output.sections)


def test_declarations_do_not_disclose_executable_or_freeform_admission_payloads():
    for name in KINDS:
        original = admission_manifest(name)
        original["metadata"]["annotations"] = {"owned": "SYNTHETIC_ANNOTATION_HIDDEN"}
        original["spec"]["unknown"] = {"password": "SYNTHETIC_PASSWORD_HIDDEN"}
        before = deepcopy(original)
        output = serialized(name, original)
        assert not any(
            canary in output
            for canary in (*CANARIES, "SYNTHETIC_ANNOTATION_HIDDEN", "SYNTHETIC_PASSWORD_HIDDEN")
        )
        assert "never executed" in output and "not an admission simulator" in output
        assert original == before


def test_policy_binding_links_use_exact_same_version_and_current_named_identity_only():
    policy = inspected()
    link = next(item for item in policy.links if item.key == "bindings")
    assert isinstance(link.destination, CollectionDestination)
    destination = link.destination
    assert (
        destination.group,
        destination.resource,
        destination.version,
        destination.scope,
        destination.namespace,
    ) == (GROUP, BINDINGS, "v1", "cluster", None)
    assert destination.predicate == PolicyBindingMatch(
        f"{GROUP}/v1", BINDINGS, "ValidatingAdmissionPolicyBinding", "owned-0"
    )
    assert "not historical UID continuity" in link.provenance
    binding = next(item for item in inspected(BINDINGS).links if item.key == "policy")
    assert isinstance(binding.destination, ReferenceDestination)
    assert binding.destination.ref == DeclaredObjectReference(
        GROUP, "v1", "ValidatingAdmissionPolicy", None, "owned-0"
    )
    assert not binding.destination.require_uid
    assert not any("param" in item.key for item in policy.links)


@pytest.mark.parametrize("name", tuple(KINDS))
@pytest.mark.parametrize(
    "change", ("version", "group", "kind", "scope", "metadata-only", "contradiction", "normalized")
)
def test_descriptor_gate_rejects_unsupported_identity_and_accepts_normalized_transport(
    name, change
):
    resource, record = admission_record(name)
    if change == "normalized":
        manifest = record.manifest
        del manifest["apiVersion"], manifest["kind"]
        normalized = resource_record(resource, manifest)
        assert cells(resource, normalized) == cells(resource, record)
        assert details(resource, normalized) == details(resource, record)
        return
    if change == "metadata-only":
        record = replace(record, metadata_only=True)
    elif change == "contradiction":
        record = ResourceRecord(
            record.name,
            record.uid,
            record.namespace,
            record.resource_version,
            record.created_at,
            json.dumps({**record.manifest, "kind": "Unrelated"}).encode(),
        )
    else:
        field, value = {
            "version": ("version", "v999"),
            "group": ("group", "unrelated.invalid"),
            "kind": ("kind", "Unrelated"),
            "scope": ("namespaced", True),
        }[change]
        resource = replace(resource, **{field: value})
    with pytest.raises(AppError):
        cells(resource, record)
    with pytest.raises(AppError):
        details(resource, record)


@pytest.mark.parametrize("spec", (None, [], "invalid", False))
@pytest.mark.parametrize("name", tuple(KINDS))
def test_missing_or_malformed_spec_does_not_invent_defaults(name, spec):
    manifest = admission_manifest(name)
    manifest["spec"] = spec
    result = values(name, manifest)
    assert all(value.sort is None for value in result.values())
    assert inspected(name, manifest).links == ()
    assert any("no omitted-field defaults" in note for note in inspected(name, manifest).notices)


def test_omitted_optional_content_and_schema_defaults_are_explicit():
    manifest = admission_manifest()
    manifest["spec"] = {"matchConstraints": {"resourceRules": []}}
    manifest.pop("status")
    result = values(manifest=manifest)
    assert result["failure-policy"].text == "Fail"
    assert result["param-kind"].text == "none declared"
    assert result["validations"].sort == result["match-conditions"].sort == 0
    assert result["observation"].text == "unknown generation"
    output = inspected(manifest=manifest)
    assert ("failurePolicy", "Fail", "API default") in section(
        output, "Policy content (declared; payloads concealed)"
    ).rows
    assert section(output, "matchConstraints selectors").rows[0] == (
        "matchPolicy",
        "Equivalent",
        "API default",
    )
    assert any("resourceRules are required" in note for note in output.notices)
    assert section(output, "Server-observed policy status").rows[0][3:] == ("unavailable", "—")


@pytest.mark.parametrize("matching", (None, False, [], "malformed"))
def test_unavailable_required_policy_constraints_are_unknown(matching):
    manifest = admission_manifest()
    manifest["spec"]["matchConstraints"] = matching
    assert values(manifest=manifest)["match-rules"].sort is None
    assert any("not unrestricted" in note for note in inspected(manifest=manifest).notices)


@pytest.mark.parametrize("matching", (None, {}))
def test_unset_binding_matching_is_zero_additional_rules_without_claiming_policy_match(matching):
    manifest = admission_manifest(BINDINGS)
    manifest["spec"]["matchResources"] = matching
    manifest["spec"].pop("paramRef")
    result = values(BINDINGS, manifest)
    assert result["match-rules"].sort == 0
    assert result["parameters"].text == "none declared"
    assert any(
        "does not mean a parameter lookup failed" in note
        for note in inspected(BINDINGS, manifest).notices
    )


def test_match_rules_preserve_subresources_scope_exclusions_and_names_without_evaluation():
    manifest = admission_manifest()
    matching = manifest["spec"]["matchConstraints"]
    matching["matchPolicy"] = "Exact"
    matching["resourceRules"][0]["resourceNames"] = ["owned-map"]
    output = inspected(manifest=manifest)
    assert section(output, "matchConstraints selectors").rows[0] == (
        "matchPolicy",
        "Exact",
        "declared",
    )
    assert section(output, "matchConstraints rules (declared)").rows == (
        ("include", "0", "CREATE, UPDATE", "core", "v1", "configmaps", "owned-map", "Namespaced"),
        ("exclude", "0", "UPDATE", "core", "v1", "configmaps/status", "all names", "*"),
    )
    assert any("exclusions take precedence" in note for note in output.notices)


@pytest.mark.parametrize("names", (None, {}, [False]))
def test_explicit_malformed_resource_names_do_not_become_an_unrestricted_omission(names):
    manifest = admission_manifest()
    manifest["spec"]["matchConstraints"]["resourceRules"][0]["resourceNames"] = names
    result = inspected(manifest=manifest)
    assert section(result, "matchConstraints rules (declared)").rows[0][6] == "—"
    assert any("safe input bound" in note for note in result.notices)


@pytest.mark.parametrize(
    "field,index", (("operations", 2), ("apiVersions", 4), ("resources", 5), ("resourceNames", 6))
)
def test_empty_rule_strings_are_not_relabelled_as_the_valid_core_api_group(field, index):
    manifest = admission_manifest()
    manifest["spec"]["matchConstraints"]["resourceRules"][0][field] = [""]
    row = section(inspected(manifest=manifest), "matchConstraints rules (declared)").rows[0]
    assert row[index] == "—"
    assert row[3] == "core"


def test_malformed_binding_matching_is_distinct_from_omission():
    manifest = admission_manifest(BINDINGS)
    manifest["spec"]["matchResources"] = []
    result = inspected(BINDINGS, manifest)
    assert values(BINDINGS, manifest)["match-rules"].sort is None
    assert any("not an omitted restriction" in note for note in result.notices)


@pytest.mark.parametrize("field", ("resourceRules", "excludeResourceRules"))
@pytest.mark.parametrize("bad", (None, {}, [False], [{}] * 257))
def test_malformed_rule_collections_remain_unavailable(field, bad):
    manifest = admission_manifest()
    manifest["spec"]["matchConstraints"][field] = bad
    output = inspected(manifest=manifest)
    assert any("safe input bound" in note for note in output.notices)
    if field == "resourceRules":
        assert values(manifest=manifest)["match-rules"].sort is None


@pytest.mark.parametrize("bad", (None, {}, [False], ["x"] * 257))
def test_malformed_rule_string_collections_are_unknown(bad):
    manifest = admission_manifest()
    manifest["spec"]["matchConstraints"]["resourceRules"][0]["operations"] = bad
    assert (
        section(inspected(manifest=manifest), "matchConstraints rules (declared)").rows[0][2] == "—"
    )


def test_unknown_enums_and_malformed_selectors_are_unknown_without_echoing_payloads():
    manifest = admission_manifest()
    manifest["spec"]["failurePolicy"] = "SYNTHETIC_FAILURE_PAYLOAD"
    matching = manifest["spec"]["matchConstraints"]
    matching["matchPolicy"] = "SYNTHETIC_MATCH_PAYLOAD"
    matching["namespaceSelector"] = {"matchLabels": []}
    matching["resourceRules"][0]["scope"] = "SYNTHETIC_SCOPE_PAYLOAD"
    manifest["status"]["conditions"][0]["status"] = "SYNTHETIC_STATUS_PAYLOAD"
    assert values(manifest=manifest)["failure-policy"].sort is None
    output = serialized(manifest=manifest)
    assert not any(
        value in output
        for value in (
            "SYNTHETIC_FAILURE_PAYLOAD",
            "SYNTHETIC_MATCH_PAYLOAD",
            "SYNTHETIC_SCOPE_PAYLOAD",
            "SYNTHETIC_STATUS_PAYLOAD",
        )
    )
    assert "malformed selector" in output


@pytest.mark.parametrize(
    "kind",
    (
        None,
        {},
        {"apiVersion": "v1", "kind": "bad-kind"},
        {"apiVersion": "bad/version/slash", "kind": "ConfigMap"},
    ),
)
def test_parameter_kind_is_absent_or_unknown_without_a_parameter_read(kind):
    manifest = admission_manifest()
    manifest["spec"]["paramKind"] = kind
    result = values(manifest=manifest)["param-kind"]
    assert result.text == "none declared" if kind is None else result.sort is None
    assert not any("param" in item.key for item in inspected(manifest=manifest).links)


def test_noncore_parameter_kind_retains_exact_api_version_and_kind():
    manifest = admission_manifest()
    manifest["spec"]["paramKind"] = {
        "apiVersion": "parameters.invalid/v9",
        "kind": "OwnedParameters",
    }
    assert values(manifest=manifest)["param-kind"].text == "parameters.invalid/v9 OwnedParameters"


@pytest.mark.parametrize(
    "ref,mode,identity,namespace",
    (
        (
            {"selector": {}, "parameterNotFoundAction": "Allow"},
            "selector",
            "empty selector (all within declared scope)",
            "omitted",
        ),
        (
            {"name": "owned", "namespace": "team", "parameterNotFoundAction": "Deny"},
            "name",
            "owned",
            "team",
        ),
        (
            {
                "selector": {"matchLabels": {"tier": "owned"}},
                "namespace": "",
                "parameterNotFoundAction": "Deny",
            },
            "selector",
            "tier In (owned)",
            "omitted",
        ),
        ({"name": "owned", "selector": {}, "parameterNotFoundAction": "Allow"}, "—", "—", "—"),
        ({"selector": {"unknown": True}}, "—", "—", "omitted"),
        ({"name": "owned", "namespace": "bad namespace"}, "—", "—", "—"),
        ({}, "—", "—", "—"),
        ([], "—", "—", "—"),
    ),
)
def test_parameter_name_selector_exclusivity_namespace_and_missing_lookup_action(
    ref, mode, identity, namespace
):
    manifest = admission_manifest(BINDINGS)
    manifest["spec"]["paramRef"] = ref
    result = inspected(BINDINGS, manifest)
    assert section(result, "Parameter reference (declared)").rows[0][:3] == (
        mode,
        identity,
        namespace,
    )
    assert values(BINDINGS, manifest)["parameters"].text == mode
    assert not any("param" in link.key for link in result.links)


@pytest.mark.parametrize(
    "actions", (None, [], {}, ["Deny", "Warn"], ["Audit", "Audit"], ["Unknown"], [["Deny"]])
)
def test_validation_actions_reject_unknown_duplicate_invalid_or_conflicting_sets(actions):
    manifest = admission_manifest(BINDINGS)
    manifest["spec"]["validationActions"] = actions
    assert values(BINDINGS, manifest)["actions"].sort is None
    assert any("no enforcement result" in note for note in inspected(BINDINGS, manifest).notices)


@pytest.mark.parametrize("generation", (None, -1, True, 2**63))
def test_missing_invalid_observed_generation_is_unknown_not_zero(generation):
    manifest = admission_manifest()
    manifest["status"]["observedGeneration"] = generation
    manifest["status"]["typeChecking"] = {}
    result = inspected(manifest=manifest)
    assert values(manifest=manifest)["observation"].text == "unknown generation"
    assert section(result, "Server-observed policy status").rows[0][1:] == (
        "—",
        "unknown generation",
        "reported",
        "0",
    )


@pytest.mark.parametrize(
    "field", ("validations", "matchConditions", "variables", "auditAnnotations")
)
@pytest.mark.parametrize("bad", (None, {}, [False], [{}] * 257))
def test_malformed_content_counts_are_unknown_and_never_retain_content(field, bad):
    manifest = admission_manifest()
    manifest["spec"][field] = bad
    output = inspected(manifest=manifest)
    assert any("safe input bound" in note for note in output.notices)
    if field in ("validations", "matchConditions"):
        key = "validations" if field == "validations" else "match-conditions"
        assert values(manifest=manifest)[key].sort is None


@pytest.mark.parametrize("name", (POLICIES, BINDINGS))
def test_malformed_current_name_disables_navigation_and_never_matches_clipped_identity(name):
    manifest = admission_manifest(name)
    if name == POLICIES:
        manifest["metadata"]["name"] = "[hostile]"
    else:
        manifest["spec"]["policyName"] = "[hostile]"
    output = inspected(name, manifest)
    assert len(output.links) == 1
    assert output.links[0].destination is None and output.links[0].unavailable_reason


def test_literal_control_and_credential_sanitization_precedes_cell_clipping():
    manifest = admission_manifest()
    rule = manifest["spec"]["matchConstraints"]["resourceRules"][0]
    rule["resources"] = ["token=HIDDEN_CREDENTIAL\x1b[31m" + "Z" * 500]
    rule["operations"] = []
    result = inspected(manifest=manifest)
    row = section(result, "matchConstraints rules (declared)").rows[0]
    assert row[2] == "none declared"
    assert "HIDDEN_CREDENTIAL" not in row[5] and "\x1b" not in row[5]
    assert all(len(value) <= 256 for value in row)


def test_output_row_action_and_serialized_byte_bounds_retain_explicit_omissions():
    manifest = admission_manifest()
    matching = manifest["spec"]["matchConstraints"]
    matching["resourceRules"] = [deepcopy(matching["resourceRules"][0]) for _ in range(256)]
    matching["excludeResourceRules"] = []
    result = inspected(manifest=manifest)
    assert (
        sum(len(item.rows) for item in result.sections) + len(result.links)
        <= MAX_CURATED_DETAIL_ROWS
    )
    assert sum(item.omitted_rows for item in result.sections) > 0
    assert any("output bound" in note for note in result.notices)
    assert result.links == ()
    assert len(serialized(manifest=manifest).encode()) <= MAX_CURATED_DETAIL_BYTES


def test_unicode_escaping_and_string_summaries_remain_within_serialized_byte_bound():
    manifest = admission_manifest()
    matching = manifest["spec"]["matchConstraints"]
    rule = matching["resourceRules"][0]
    rule.update(
        {
            key: ["😀" * 300] * 17
            for key in ("operations", "apiGroups", "apiVersions", "resources", "resourceNames")
        }
    )
    matching["resourceRules"] = [deepcopy(rule) for _ in range(256)]
    result = inspected(manifest=manifest)
    assert sum(item.omitted_rows for item in result.sections) > 0
    assert any("first 16" in note for note in result.notices)
    assert len(serialized(manifest=manifest).encode()) <= MAX_CURATED_DETAIL_BYTES


@pytest.mark.parametrize("version", ("v1", "v1beta1"))
@pytest.mark.parametrize("name", tuple(KINDS))
def test_versioned_admission_schemas_have_specific_typed_fields_and_same_version_links(
    name, version
):
    manifest = admission_manifest(name, version=version)
    result = values(name, manifest, version=version)
    expected = {
        POLICIES: (
            "match-rules",
            "match-conditions",
            "failure-policy",
            "param-kind",
            "validations",
            "observation",
        ),
        BINDINGS: ("policy", "actions", "parameters", "match-rules"),
        MUTATING_POLICIES: (
            "match-rules",
            "match-conditions",
            "failure-policy",
            "param-kind",
            "mutations",
            "reinvocation",
        ),
        MUTATING_BINDINGS: ("policy", "parameters", "match-rules"),
    }
    assert tuple(result) == expected[name]
    assert result["match-rules"].sort == 1
    assert all(family.versions == frozenset({"v1", "v1beta1"}) for family in FAMILIES)
    output = inspected(name, manifest, version=version)
    destination = output.links[0].destination
    if name in (POLICIES, MUTATING_POLICIES):
        content = "validations" if name == POLICIES else "mutations"
        assert result[content].sort == 1
        other = values(name, admission_manifest(name, 1, version=version), version=version)
        assert other[content].sort == 2
        assert isinstance(destination, CollectionDestination)
        assert destination.version == version
        assert destination.predicate.api_version == f"{GROUP}/{version}"
        expected_plural = BINDINGS if name == POLICIES else MUTATING_BINDINGS
        assert destination.resource == expected_plural
        assert destination.predicate.kind == KINDS[expected_plural]
        assert destination.predicate.name == "owned-0"
    else:
        other = values(name, admission_manifest(name, 1, version=version), version=version)
        assert other["match-rules"].sort == 2
        assert isinstance(destination, ReferenceDestination)
        assert destination.ref.version == version
        assert destination.ref.kind == (
            "ValidatingAdmissionPolicy" if name == BINDINGS else "MutatingAdmissionPolicy"
        )
        assert destination.ref.namespace is destination.ref.uid is None
    assert all(canary not in serialized(name, manifest, version=version) for canary in CANARIES)


@pytest.mark.parametrize("name", tuple(KINDS))
def test_alpha_schema_is_not_interpreted_even_when_discovered(name):
    resource, record = admission_record(name, version="v1alpha1")
    with pytest.raises(AppError, match="descriptor"):
        cells(resource, record)
    with pytest.raises(AppError, match="descriptor"):
        details(resource, record)


@pytest.mark.parametrize("version", ("v1", "v1beta1"))
def test_mutating_patch_types_and_required_reinvocation_are_declarations_with_no_status(version):
    manifest = admission_manifest(MUTATING_POLICIES, 1, version=version)
    manifest["status"] = admission_manifest()["status"]
    manifest["spec"]["validations"] = [{"expression": CANARIES[0]}]
    manifest["spec"]["auditAnnotations"] = [{"key": "ignored", "valueExpression": CANARIES[2]}]
    output = inspected(MUTATING_POLICIES, manifest, version=version)
    assert section(output, "Mutation declarations (payloads concealed)").rows == (
        ("0", "ApplyConfiguration", "concealed; never executed"),
        ("1", "JSONPatch", "concealed; never executed"),
    )
    content = section(output, "Policy content (declared; payloads concealed)")
    assert ("reinvocationPolicy", "Never", "declared required field") in content.rows
    assert ("mutations", "2", "declared count") in content.rows
    assert not any(row[0] in ("validations", "auditAnnotations") for row in content.rows)
    assert all("Server-observed" not in item.title for item in output.sections)
    assert "observation" not in values(MUTATING_POLICIES, manifest, version=version)
    assert not any(
        canary in serialized(MUTATING_POLICIES, manifest, version=version) for canary in CANARIES
    )


@pytest.mark.parametrize("reinvocation", (None, "", "Sometimes", False))
def test_mutating_policy_missing_or_invalid_reinvocation_does_not_inherit_webhook_default(
    reinvocation,
):
    manifest = admission_manifest(MUTATING_POLICIES)
    if reinvocation is None:
        manifest["spec"].pop("reinvocationPolicy")
    else:
        manifest["spec"]["reinvocationPolicy"] = reinvocation
    result = values(MUTATING_POLICIES, manifest)
    assert result["reinvocation"].sort is None
    assert any(
        "no webhook Never default" in note
        for note in inspected(MUTATING_POLICIES, manifest).notices
    )


@pytest.mark.parametrize("version", ("v1", "v1beta1"))
@pytest.mark.parametrize(
    "state,mutations",
    (
        ("absent", None),
        ("null", None),
        ("mapping", {}),
        ("malformed", [False]),
        ("oversized", [{}] * 257),
        ("empty", []),
    ),
)
def test_mutations_distinguish_empty_required_list_from_unavailable(version, state, mutations):
    manifest = admission_manifest(MUTATING_POLICIES, version=version)
    if state == "absent":
        manifest["spec"].pop("mutations")
    else:
        manifest["spec"]["mutations"] = mutations
    result = values(MUTATING_POLICIES, manifest, version=version)["mutations"]
    assert result.sort == 0 if state == "empty" else result.sort is None
    output = inspected(MUTATING_POLICIES, manifest, version=version)
    assert section(output, "Mutation declarations (payloads concealed)").rows == ()
    content = section(output, "Policy content (declared; payloads concealed)")
    assert ("mutations", "0" if state == "empty" else "—", "declared count") in content.rows
    if state == "empty":
        assert any("mutations are required" in note for note in output.notices)
    else:
        assert any("safe input bound" in note for note in output.notices)


def test_unknown_mutation_patch_type_is_unknown_and_never_retains_patch_payload():
    manifest = admission_manifest(MUTATING_POLICIES)
    manifest["spec"]["mutations"] = [
        {"patchType": "SYNTHETIC_UNKNOWN_PATCH_TYPE", "jsonPatch": {"expression": CANARIES[4]}}
    ]
    output = inspected(MUTATING_POLICIES, manifest)
    assert section(output, "Mutation declarations (payloads concealed)").rows == (
        ("0", "—", "concealed; never executed"),
    )
    assert "SYNTHETIC_UNKNOWN_PATCH_TYPE" not in serialized(MUTATING_POLICIES, manifest)
    assert CANARIES[4] not in serialized(MUTATING_POLICIES, manifest)


def test_mutating_binding_never_fabricates_validation_actions_from_foreign_fields():
    manifest = admission_manifest(MUTATING_BINDINGS)
    manifest["spec"]["validationActions"] = ["Deny"]
    manifest["status"] = admission_manifest()["status"]
    output = inspected(MUTATING_BINDINGS, manifest)
    assert section(output, "Binding declaration").columns == ("Policy name",)
    assert section(output, "Binding declaration").rows == (("owned-0",),)
    assert "actions" not in values(MUTATING_BINDINGS, manifest)
    assert "validationActions" not in serialized(MUTATING_BINDINGS, manifest)
    assert "Server-observed policy status" not in serialized(MUTATING_BINDINGS, manifest)


@pytest.mark.parametrize(
    "field,identity",
    (("matchConditions", "name"), ("variables", "name"), ("auditAnnotations", "key")),
)
@pytest.mark.parametrize(
    "names",
    (
        ("duplicate", "duplicate"),
        (None,),
        ("",),
        ([],),
        ("\x1b[31m",),
        ("A" * 8193,),
        ("token=HIDDEN_NAMED_CREDENTIAL",),
    ),
)
def test_named_content_counts_reject_duplicate_or_missing_identity_without_payload_disclosure(
    field, identity, names
):
    manifest = admission_manifest()
    manifest["spec"][field] = [
        {identity: name, "expression": CANARIES[0], "valueExpression": CANARIES[2]}
        for name in names
    ]
    output = inspected(manifest=manifest)
    assert any("identity; its count is unavailable" in note for note in output.notices)
    if field == "matchConditions":
        assert values(manifest=manifest)["match-conditions"].sort is None
    else:
        assert (field, "—", "declared count") in section(
            output, "Policy content (declared; payloads concealed)"
        ).rows
    assert not any(canary in serialized(manifest=manifest) for canary in CANARIES)
    assert "HIDDEN_NAMED_CREDENTIAL" not in serialized(manifest=manifest)


def test_maximum_valid_condition_count_remains_numeric_and_above_schema_limit_is_unknown():
    manifest = admission_manifest()
    manifest["spec"]["matchConditions"] = [
        {"name": f"owned-{index}", "expression": CANARIES[0]} for index in range(64)
    ]
    assert values(manifest=manifest)["match-conditions"].sort == 64
    manifest["spec"]["matchConditions"].append({"name": "owned-64", "expression": CANARIES[0]})
    assert values(manifest=manifest)["match-conditions"].sort is None


@pytest.mark.parametrize("version", ("v1", "v1beta1"))
@pytest.mark.parametrize("name", (POLICIES, MUTATING_POLICIES))
@pytest.mark.parametrize(
    "state,rules",
    (("absent", None), ("null", None), ("mapping", {}), ("malformed", [False]), ("empty", [])),
)
def test_required_policy_resource_rules_omission_is_unknown_while_explicit_empty_is_declared_zero(
    version, name, state, rules
):
    manifest = admission_manifest(name, version=version)
    matching = manifest["spec"]["matchConstraints"]
    if state == "absent":
        matching.pop("resourceRules")
    else:
        matching["resourceRules"] = rules
    result = values(name, manifest, version=version)["match-rules"]
    assert result.sort == 0 if state == "empty" else result.sort is None
    output = inspected(name, manifest, version=version)
    if state == "empty":
        assert any("Policy resourceRules are required" in note for note in output.notices)
    else:
        assert any("safe input bound" in note for note in output.notices)


@pytest.mark.parametrize("version", ("v1", "v1beta1"))
@pytest.mark.parametrize("name", (BINDINGS, MUTATING_BINDINGS))
def test_omitted_binding_resource_rules_add_no_constraint_but_explicit_null_is_unknown(
    version, name
):
    manifest = admission_manifest(name, version=version)
    matching = manifest["spec"]["matchResources"]
    matching.pop("resourceRules")
    assert values(name, manifest, version=version)["match-rules"].sort == 0
    output = inspected(name, manifest, version=version)
    assert not any("Policy resourceRules are required" in note for note in output.notices)
    assert any("policy constraints both apply" in note for note in output.notices)
    matching["resourceRules"] = None
    assert values(name, manifest, version=version)["match-rules"].sort is None
