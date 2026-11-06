"""Explicit synthetic policy-family objects; no enforcement or provider claim."""

from copy import deepcopy

from kuberich.domain.curated_policy import FAMILIES
from kuberich.domain.resources import ApiResource, resource_record

CA_CANARY = "SYNTHETIC-PUBLIC-CA-BYTES-NEVER-DEFAULT-DISPLAY"
URL_CANARIES = ("synthetic-user", "synthetic-password", "private-path-canary", "query-canary")
ANNOTATION_CANARY = "unrelated-annotation-canary"


def policy_resource(name):
    family = next(item for item in FAMILIES if item.resource == name)
    return ApiResource(
        family.group,
        "v1",
        name,
        family.kind,
        family.namespaced,
        frozenset({"get", "list", "watch"}),
    )


def policy_manifest(name, ordinal=0):
    resource = policy_resource(name)
    metadata = {
        "name": f"owned-{ordinal}",
        "uid": f"synthetic-{name}-{ordinal}",
        "resourceVersion": "owned-v1",
        "annotations": {"synthetic.example.test/private": ANNOTATION_CANARY},
    }
    if resource.namespaced:
        metadata["namespace"] = "team"
    result = {"apiVersion": resource.api_version, "kind": resource.kind, "metadata": metadata}
    if name == "networkpolicies":
        result["spec"] = (
            {}
            if ordinal
            else {
                "podSelector": {
                    "matchLabels": {"app": "owned"},
                    "matchExpressions": [{"key": "role", "operator": "In", "values": ["api"]}],
                },
                "ingress": [
                    {
                        "from": [
                            {"podSelector": {}},
                            {"namespaceSelector": {"matchLabels": {"fixture": "owned"}}},
                            {"ipBlock": {"cidr": "192.0.2.0/24", "except": ["192.0.2.1/32"]}},
                        ],
                        "ports": [
                            {"port": 8080, "endPort": 8090},
                            {"port": "http", "protocol": "TCP"},
                        ],
                    }
                ],
                "egress": [{}],
            }
        )
    elif name == "endpointslices":
        result.update(
            addressType="IPv6" if ordinal else "IPv4",
            endpoints=[]
            if ordinal
            else [
                {
                    "addresses": ["192.0.2.1", "192.0.2.2"],
                    "conditions": {"ready": True, "serving": True, "terminating": False},
                    "targetRef": {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "namespace": "team",
                        "name": "owned-pod",
                        "uid": "exact-pod-uid",
                    },
                },
                {
                    "addresses": ["192.0.2.3"],
                    "conditions": {"ready": False, "serving": False, "terminating": True},
                },
                {"addresses": ["192.0.2.4"]},
            ],
            ports=[]
            if ordinal
            else [{"name": "all", "protocol": "UDP"}, {"name": "http", "port": 80}],
        )
        if not ordinal:
            metadata["labels"] = {"kubernetes.io/service-name": "owned-service"}
    elif name == "ingressclasses":
        metadata["annotations"]["ingressclass.kubernetes.io/is-default-class"] = (
            "false" if ordinal else "true"
        )
        result["spec"] = {
            "controller": "synthetic.example.test/other"
            if ordinal
            else "synthetic.example.test/controller",
            "parameters": {
                "apiGroup": "",
                "kind": "ConfigMap",
                "name": "owned-parameters",
                **({} if ordinal else {"scope": "Namespace", "namespace": "team"}),
            },
        }
    elif name == "resourcequotas":
        result["spec"] = {
            "hard": {"cpu": "2", "memory": "2Gi", "pods": "10"},
            "scopes": ["NotBestEffort"],
            "scopeSelector": {
                "matchExpressions": [
                    {"scopeName": "PriorityClass", "operator": "In", "values": ["owned-priority"]}
                ]
            },
        }
        result["status"] = {
            "hard": {
                "cpu": "2" if ordinal else "1000m",
                "memory": "2Gi" if ordinal else "1Gi",
                "pods": "10" if ordinal else "0",
            },
            "used": {
                "cpu": "0" if ordinal else "1500m",
                "memory": "0" if ordinal else "512Mi",
                "pods": "0",
            },
        }
    elif name == "limitranges":
        result["spec"] = {
            "limits": [{"type": "Pod", "max": {"memory": "2Gi"}}]
            if ordinal
            else [
                {
                    "type": "Container",
                    "min": {"cpu": "100m"},
                    "max": {"cpu": "2"},
                    "default": {"cpu": "500m"},
                    "defaultRequest": {"cpu": "250m"},
                    "maxLimitRequestRatio": {"cpu": "2"},
                },
                {
                    "type": "PersistentVolumeClaim",
                    "min": {"storage": "1Gi"},
                    "max": {"storage": "2Gi"},
                },
            ]
        }
    else:
        base = {
            "name": "service.synthetic.example.test",
            "admissionReviewVersions": ["v1", "v1beta1"],
            "failurePolicy": "Ignore",
            "sideEffects": "None",
            "timeoutSeconds": 7,
            "clientConfig": {
                "service": {
                    "namespace": "team",
                    "name": "owned-webhook",
                    "path": "/not-default-displayed",
                },
                "caBundle": CA_CANARY,
            },
            "namespaceSelector": {"matchLabels": {"fixture": "owned"}},
            "rules": [
                {
                    "operations": ["CREATE"],
                    "apiGroups": ["unused.synthetic.example.test"],
                    "apiVersions": ["v1"],
                    "resources": ["widgets"],
                    "scope": "Namespaced",
                }
            ],
        }
        other = deepcopy(base)
        other.update(
            name="url.synthetic.example.test",
            failurePolicy="Fail",
            sideEffects="NoneOnDryRun",
            timeoutSeconds=20,
            clientConfig={
                "url": "https://synthetic-user:synthetic-password@example.test/private-path-canary?token=query-canary",
                "caBundle": CA_CANARY,
            },
        )
        result["webhooks"] = [base] if ordinal else [base, other]
    return result


def policy_record(name, ordinal=0, *, manifest=None):
    resource = policy_resource(name)
    return resource, resource_record(
        resource, policy_manifest(name, ordinal) if manifest is None else manifest
    )
