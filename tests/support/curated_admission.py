"""Synthetic admission declarations with expression/message disclosure canaries."""

from kuberich.domain.resources import ApiResource, resource_record

GROUP = "admissionregistration.k8s.io"
POLICIES = "validatingadmissionpolicies"
BINDINGS = "validatingadmissionpolicybindings"
MUTATING_POLICIES = "mutatingadmissionpolicies"
MUTATING_BINDINGS = "mutatingadmissionpolicybindings"
KINDS = {
    POLICIES: "ValidatingAdmissionPolicy",
    BINDINGS: "ValidatingAdmissionPolicyBinding",
    MUTATING_POLICIES: "MutatingAdmissionPolicy",
    MUTATING_BINDINGS: "MutatingAdmissionPolicyBinding",
}
CANARIES = (
    "SYNTHETIC_CEL_PAYLOAD_CONCEALED",
    "SYNTHETIC_VALIDATION_MESSAGE_CONCEALED",
    "SYNTHETIC_AUDIT_VALUE_CONCEALED",
    "SYNTHETIC_TYPE_WARNING_CONCEALED",
    "SYNTHETIC_PATCH_VALUE_CONCEALED",
)


def admission_resource(name=POLICIES, version="v1"):
    return ApiResource(
        GROUP, version, name, KINDS[name], False, frozenset({"get", "list", "watch"})
    )


def admission_manifest(name=POLICIES, variant=0, *, version="v1"):
    resource = admission_resource(name, version)
    result = {
        "apiVersion": resource.api_version,
        "kind": resource.kind,
        "metadata": {
            "name": f"owned-{variant}",
            "uid": f"synthetic-{name}-{variant}",
            "resourceVersion": "owned-v1",
            "generation": 2,
        },
    }
    matching = {
        "namespaceSelector": {"matchLabels": {"fixture": "owned"}},
        "objectSelector": {},
        "resourceRules": [
            {
                "operations": ["CREATE", "UPDATE"],
                "apiGroups": [""],
                "apiVersions": ["v1"],
                "resources": ["configmaps"],
                "resourceNames": [],
                "scope": "Namespaced",
            }
        ],
        "excludeResourceRules": [
            {
                "operations": ["UPDATE"],
                "apiGroups": [""],
                "apiVersions": ["v1"],
                "resources": ["configmaps/status"],
            }
        ],
    }
    if name in (POLICIES, MUTATING_POLICIES):
        result["spec"] = {
            "matchConstraints": matching,
            "failurePolicy": "Ignore" if variant else "Fail",
            "paramKind": {"apiVersion": "v1", "kind": "ConfigMap"},
            "matchConditions": [{"name": "owned", "expression": CANARIES[0]}],
            "validations": [{"expression": CANARIES[0], "message": CANARIES[1]}]
            * (2 if variant else 1),
            "variables": [{"name": "owned", "expression": CANARIES[0]}],
            "auditAnnotations": [{"key": "owned", "valueExpression": CANARIES[2]}],
        }
        if name == MUTATING_POLICIES:
            result["spec"].pop("validations")
            result["spec"].pop("auditAnnotations")
            result["spec"].update(
                reinvocationPolicy="Never" if variant else "IfNeeded",
                mutations=[
                    {
                        "patchType": "ApplyConfiguration",
                        "applyConfiguration": {"expression": CANARIES[4]},
                    },
                    {"patchType": "JSONPatch", "jsonPatch": {"expression": CANARIES[4]}},
                ]
                if variant
                else [
                    {
                        "patchType": "ApplyConfiguration",
                        "applyConfiguration": {"expression": CANARIES[4]},
                    },
                    {"patchType": "JSONPatch", "jsonPatch": {"expression": CANARIES[4]}},
                ][:1],
            )
            return result
        result["status"] = {
            "observedGeneration": 1 if variant else 2,
            "typeChecking": {
                "expressionWarnings": [
                    {"fieldRef": "spec.validations[0].expression", "warning": CANARIES[3]}
                ]
            },
            "conditions": [
                {
                    "type": "Accepted",
                    "status": "True",
                    "observedGeneration": 2,
                    "message": CANARIES[1],
                }
            ],
        }
    else:
        if variant:
            matching["resourceRules"].append(
                {
                    "operations": ["UPDATE"],
                    "apiGroups": [""],
                    "apiVersions": ["v1"],
                    "resources": ["secrets"],
                    "scope": "Namespaced",
                }
            )
        result["spec"] = {
            "policyName": "owned-0",
            "validationActions": ["Audit"] if variant else ["Warn", "Audit"],
            "matchResources": matching,
            "paramRef": {"name": "owned-parameters", "parameterNotFoundAction": "Deny"},
        }
        if name == MUTATING_BINDINGS:
            result["spec"].pop("validationActions")
    return result


def admission_record(name=POLICIES, variant=0, *, version="v1", manifest=None):
    resource = admission_resource(name, version)
    return resource, resource_record(
        resource,
        admission_manifest(name, variant, version=version) if manifest is None else manifest,
    )
