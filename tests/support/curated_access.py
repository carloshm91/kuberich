"""Distinct synthetic access declarations, never real identities or token contents."""

from kuberich.domain.resources import ApiResource, resource_record

CANARY = "PRIVATE_CURATED_ACCESS_CANARY"
KINDS = ("ServiceAccount", "Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding")
_PLURALS = ("serviceaccounts", "roles", "clusterroles", "rolebindings", "clusterrolebindings")


def access_resource(kind="ServiceAccount"):
    return ApiResource(
        "" if kind == "ServiceAccount" else "rbac.authorization.k8s.io",
        "v1",
        _PLURALS[KINDS.index(kind)],
        kind,
        kind not in {"ClusterRole", "ClusterRoleBinding"},
        frozenset({"get", "list"}),
    )


def access_manifest(kind="ServiceAccount", *, variant=0, **changes):
    resource = access_resource(kind)
    metadata = {
        "name": "owned-access-" + str(variant),
        "uid": "owned-uid-" + str(variant),
        "annotations": {"arbitrary": CANARY},
    }
    if resource.namespaced:
        metadata["namespace"] = "team"
    value = {
        "apiVersion": resource.api_version,
        "kind": kind,
        "metadata": metadata,
        "token": CANARY,
        "data": {"private": CANARY},
        "spec": {"private": CANARY},
    }
    if kind == "ServiceAccount":
        value.update(
            automountServiceAccountToken=bool(variant),
            secrets=[{"name": "owned-secret", "uid": "declared-secret-uid"}],
            imagePullSecrets=[],
        )
        if variant:
            value["secrets"].append({"name": "other-secret"})
            value["imagePullSecrets"] = [{"name": "owned-registry"}]
    elif kind in {"Role", "ClusterRole"}:
        value["rules"] = [{"verbs": ["get"], "apiGroups": [""], "resources": ["pods"]}]
        if variant:
            value["rules"].append(
                {"verbs": ["list"], "nonResourceURLs": ["/healthz"]}
                if kind == "ClusterRole"
                else {"verbs": ["watch"], "apiGroups": ["apps"], "resources": ["deployments"]}
            )
            if kind == "ClusterRole":
                value["aggregationRule"] = {
                    "clusterRoleSelectors": [{"matchLabels": {"owned-part": "readers"}}]
                }
    else:
        value["roleRef"] = {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole" if kind == "ClusterRoleBinding" or variant else "Role",
            "name": "owned-role",
        }
        value["subjects"] = [
            {
                "kind": "ServiceAccount",
                "name": "worker",
                **({"namespace": "other"} if kind == "ClusterRoleBinding" else {}),
            }
        ]
        if variant:
            value["subjects"].extend(
                [
                    {"kind": "User", "name": "owned-user"},
                    {"kind": "User", "name": "other-user"},
                    {"kind": "Group", "name": "owned-group"},
                ]
            )
    value.update(changes)
    return value


def access_record(kind="ServiceAccount", **changes):
    return resource_record(access_resource(kind), access_manifest(kind, **changes))
