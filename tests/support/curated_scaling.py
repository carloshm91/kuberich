"""Synthetic served descriptors and full records for the six scaling families."""

from copy import deepcopy
from typing import Any

from kuberich.domain.curated_scaling import FAMILIES
from kuberich.domain.resources import ApiResource, ResourceRecord, resource_record

TARGET = {"apiVersion": "apps/v1", "kind": "Deployment", "name": "owned-workload"}
SAMPLES: dict[str, dict[str, Any]] = {
    "HorizontalPodAutoscaler": {
        "spec": {
            "scaleTargetRef": TARGET,
            "minReplicas": 0,
            "maxReplicas": 5,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {"type": "Utilization", "averageUtilization": 70},
                    },
                }
            ],
        },
        "status": {
            "currentReplicas": 0,
            "desiredReplicas": 2,
            "observedGeneration": 4,
            "currentMetrics": [
                {
                    "type": "Resource",
                    "resource": {"name": "cpu", "current": {"averageUtilization": 30}},
                }
            ],
            "conditions": [{"type": "ScalingActive", "status": "True"}],
        },
    },
    "VerticalPodAutoscaler": {
        "spec": {
            "targetRef": TARGET,
            "updatePolicy": {"updateMode": "Off"},
            "resourcePolicy": {
                "containerPolicies": [
                    {
                        "containerName": "main",
                        "minAllowed": {"cpu": "100m"},
                        "maxAllowed": {"memory": "2Gi"},
                        "controlledResources": ["cpu", "memory"],
                    }
                ]
            },
        },
        "status": {
            "recommendation": {
                "containerRecommendations": [
                    {
                        "containerName": "main",
                        "target": {"cpu": "250m", "memory": "512Mi"},
                        "lowerBound": {"cpu": "100m"},
                        "upperBound": {"cpu": "1"},
                        "uncappedTarget": {"cpu": "2"},
                    }
                ]
            },
            "conditions": [{"type": "RecommendationProvided", "status": "True"}],
        },
    },
    "PodDisruptionBudget": {
        "spec": {"minAvailable": "50%", "selector": {"matchLabels": {"app": "owned"}}},
        "status": {
            "disruptionsAllowed": 0,
            "currentHealthy": 2,
            "desiredHealthy": 1,
            "expectedPods": 2,
            "observedGeneration": 4,
        },
    },
    "PriorityClass": {
        "value": -10,
        "globalDefault": True,
        "preemptionPolicy": "Never",
        "description": "synthetic-description-not-for-default-display",
    },
    "RuntimeClass": {
        "handler": "owned-handler",
        "overhead": {"podFixed": {"cpu": "100m", "memory": "64Mi"}},
        "scheduling": {
            "nodeSelector": {"runtime": "owned"},
            "tolerations": [
                {
                    "key": "runtime",
                    "operator": "Equal",
                    "value": "owned",
                    "effect": "NoSchedule",
                    "tolerationSeconds": 0,
                }
            ],
        },
    },
    "Lease": {
        "spec": {
            "holderIdentity": "synthetic-agent",
            "leaseDurationSeconds": 0,
            "leaseTransitions": 0,
            "acquireTime": "2026-11-06T10:00:00Z",
            "renewTime": "2026-11-06T10:00:01Z",
            "strategy": "OldestEmulationVersion",
            "preferredHolder": "synthetic-candidate",
        }
    },
}


def api(kind: str, version: str | None = None) -> ApiResource:
    family = next(item for item in FAMILIES if item.kind == kind)
    selected = version or ("v2" if kind == "HorizontalPodAutoscaler" else "v1")
    return ApiResource(
        family.group,
        selected,
        family.resource,
        family.kind,
        family.namespaced,
        frozenset({"get", "list", "watch"}),
        family.aliases,
    )


def record(
    resource: ApiResource,
    fields: dict[str, Any] | None = None,
    *,
    sample: bool = True,
    name: str = "owned-one",
    namespace: str = "team",
    metadata: dict[str, Any] | None = None,
) -> ResourceRecord:
    value = deepcopy(SAMPLES[resource.kind]) if sample else {}
    if fields is not None:
        value.update(deepcopy(fields))
    value["metadata"] = {
        "name": name,
        "uid": "synthetic-uid",
        "resourceVersion": "7",
        "generation": 4,
        **({"namespace": namespace} if resource.namespaced else {}),
        **(metadata or {}),
    }
    return resource_record(resource, value)
