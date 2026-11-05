"""Supported declarations across zero-replica templates without configuration values."""

from dataclasses import replace

import pytest

from kuberich.domain.reference_fields import REFERENCE_SOURCE_FAMILIES, declared_references
from kuberich.domain.relationships import MAX_RELATIONSHIP_BYTES, MAX_RELATIONSHIP_ITEMS
from kuberich.errors import AppError
from tests.support.relationships import (
    ACCOUNTS,
    CLAIMS,
    CONFIGMAPS,
    DEPLOYMENTS,
    PODS,
    VOLUMES,
    descriptor,
    record,
)

WORKLOADS = [
    PODS,
    descriptor("replicationcontrollers", "ReplicationController"),
    DEPLOYMENTS,
    descriptor("replicasets", "ReplicaSet", "apps"),
    descriptor("statefulsets", "StatefulSet", "apps"),
    descriptor("daemonsets", "DaemonSet", "apps"),
    descriptor("jobs", "Job", "batch"),
    descriptor("cronjobs", "CronJob", "batch"),
]


def workload_spec(resource, pod_spec):
    if resource.name == "pods":
        return pod_spec
    template = {"replicas": 0, "template": {"spec": pod_spec}}
    return {"jobTemplate": {"spec": template}} if resource.name == "cronjobs" else template


def test_supported_source_inventory_is_exact_and_excludes_arbitrary_custom_specs():
    assert {(item.group, item.name) for item in WORKLOADS} | {
        ("", "serviceaccounts"),
        ("", "persistentvolumeclaims"),
        ("", "persistentvolumes"),
    } == REFERENCE_SOURCE_FAMILIES
    assert (
        declared_references(
            CONFIGMAPS, record(CONFIGMAPS, data={"secretName": "not-a-declaration"})
        )
        == ()
    )
    custom = descriptor("widgets", "Widget", "example.test")
    assert (
        declared_references(custom, record(custom, spec={"secretName": "not-a-declaration"})) == ()
    )


@pytest.mark.parametrize("resource", WORKLOADS)
def test_all_workload_templates_including_zero_replicas_preserve_paths_and_default_sa(resource):
    spec = {
        "containers": [{"name": "app", "envFrom": [{"configMapRef": {"name": "settings"}}]}],
        "volumes": [{"persistentVolumeClaim": {"claimName": "storage"}}],
        "priority": 1000,
    }
    extracted = declared_references(resource, record(resource, spec=workload_spec(resource, spec)))
    assert [(item.target.kind, item.target.name) for item in extracted] == [
        ("ConfigMap", "settings"),
        ("PersistentVolumeClaim", "storage"),
        ("ServiceAccount", "default"),
    ]
    prefix = (
        "spec"
        if resource.name == "pods"
        else "spec.jobTemplate.spec.template.spec"
        if resource.name == "cronjobs"
        else "spec.template.spec"
    )
    assert [item.path for item in extracted] == [
        prefix + ".containers[0].envFrom[0].configMapRef.name",
        prefix + ".volumes[0].persistentVolumeClaim.claimName",
        prefix + ".serviceAccountName",
    ]
    assert extracted[-1].defaulted
    assert all(item.target.namespace == "team" for item in extracted)
    assert all(item.target.uid is None for item in extracted)
    assert all(not item.optional for item in extracted)
    assert all(
        item.target.kind != "PriorityClass" for item in extracted
    )  # Numeric priority is not identity.


def test_every_container_family_and_env_reference_has_exact_path_and_optional_flag():
    container = {
        "name": "app",
        "env": [
            {"name": "LITERAL", "value": "NEVER-PUBLISH-LITERAL"},
            {
                "name": "CM",
                "valueFrom": {
                    "configMapKeyRef": {
                        "name": "settings",
                        "key": "NEVER-PUBLISH-KEY",
                        "optional": True,
                    }
                },
            },
            {
                "name": "SECRET",
                "valueFrom": {
                    "secretKeyRef": {"name": "credentials", "key": "NEVER-PUBLISH-PASSWORD"}
                },
            },
            {"name": "FIELD", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
        ],
        "envFrom": [
            {"configMapRef": {"name": "all-settings", "optional": False}},
            {"secretRef": {"name": "all-credentials", "optional": True}},
        ],
    }
    fields = ("containers", "initContainers", "ephemeralContainers")
    extracted = declared_references(
        PODS,
        record(
            spec={
                **{field: [container] for field in fields},
                "serviceAccountName": "runner",
                "priorityClassName": "batch",
            }
        ),
    )
    expected = []
    for field in fields:
        prefix = f"spec.{field}[0]"
        expected.extend(
            [
                (prefix + ".env[1].valueFrom.configMapKeyRef.name", "settings", True),
                (prefix + ".env[2].valueFrom.secretKeyRef.name", "credentials", False),
                (prefix + ".envFrom[0].configMapRef.name", "all-settings", False),
                (prefix + ".envFrom[1].secretRef.name", "all-credentials", True),
            ]
        )
    assert [(item.path, item.target.name, item.optional) for item in extracted[:-2]] == expected
    account, priority = extracted[-2:]
    assert (account.target.kind, account.target.name, account.defaulted) == (
        "ServiceAccount",
        "runner",
        False,
    )
    assert (priority.target.api_version, priority.target.namespace, priority.target.name) == (
        "scheduling.k8s.io/v1",
        None,
        "batch",
    )
    assert "NEVER-PUBLISH" not in repr(extracted)


def test_all_explicit_volume_image_pull_and_projected_fields_are_extracted():
    volumes = [
        {"configMap": {"name": "cm", "optional": True}},
        {"secret": {"secretName": "secret", "optional": True}},
        {"persistentVolumeClaim": {"claimName": "claim"}},
        {
            "projected": {
                "sources": [
                    {"configMap": {"name": "projected-cm"}},
                    {"secret": {"name": "projected-secret", "optional": True}},
                    {"serviceAccountToken": {"path": "token"}},
                    {"downwardAPI": {"items": []}},
                ]
            }
        },
        {"csi": {"nodePublishSecretRef": {"name": "csi"}}},
        *[
            {provider: {"secretRef": {"name": provider}}}
            for provider in (
                "cephfs",
                "cinder",
                "flexVolume",
                "iscsi",
                "rbd",
                "scaleIO",
                "storageos",
            )
        ],
        {"azureFile": {"secretName": "azure"}},
        {"emptyDir": {}},
        {"hostPath": {"path": "/not/a/secretName"}},
        {"csi": {"driver": "no-reference"}},
    ]
    extracted = declared_references(
        PODS,
        record(
            spec={
                "containers": [{"name": "app"}],
                "volumes": volumes,
                "imagePullSecrets": [{"name": "registry"}],
            }
        ),
    )
    assert [(item.target.kind, item.target.name) for item in extracted] == [
        ("ConfigMap", "cm"),
        ("Secret", "secret"),
        ("PersistentVolumeClaim", "claim"),
        ("ConfigMap", "projected-cm"),
        ("Secret", "projected-secret"),
        *[
            ("Secret", name)
            for name in (
                "csi",
                "cephfs",
                "cinder",
                "flexVolume",
                "iscsi",
                "rbd",
                "scaleIO",
                "storageos",
                "azure",
                "registry",
            )
        ],
        ("ServiceAccount", "default"),
    ]
    assert extracted[4].path == "spec.volumes[3].projected.sources[1].secret.name"
    assert extracted[5].path == "spec.volumes[4].csi.nodePublishSecretRef.name"
    assert extracted[-3].path == "spec.volumes[12].azureFile.secretName"
    assert extracted[-2].path == "spec.imagePullSecrets[0].name"
    assert [item.optional for item in extracted[:5]] == [True, True, False, False, True]


@pytest.mark.parametrize(
    "spec,defaulted",
    [
        ({"serviceAccount": "legacy"}, False),
        ({"serviceAccount": "", "serviceAccountName": "current"}, False),
        ({"serviceAccountName": ""}, True),
        ({"serviceAccount": "same", "serviceAccountName": "same"}, False),
    ],
)
def test_service_account_alias_and_explicit_default_flags(spec, defaulted):
    refs = declared_references(PODS, record(spec={"containers": [{"name": "app"}], **spec}))
    assert len(refs) == 1 and refs[0].target.kind == "ServiceAccount"
    assert refs[0].defaulted is defaulted


def test_service_account_secret_objects_preserve_declared_uid_and_never_values():
    extracted = declared_references(
        ACCOUNTS,
        record(
            ACCOUNTS,
            secrets=[{"name": "token", "namespace": "team", "uid": "original-secret"}],
            imagePullSecrets=[{"name": "registry"}],
        ),
    )
    assert [(item.path, item.target.name, item.target.uid) for item in extracted] == [
        ("secrets[0].name", "token", "original-secret"),
        ("imagePullSecrets[0].name", "registry", None),
    ]
    assert declared_references(ACCOUNTS, record(ACCOUNTS)) == ()
    with pytest.raises(AppError, match="invalid namespace"):
        declared_references(
            ACCOUNTS, record(ACCOUNTS, secrets=[{"name": "token", "namespace": "other"}])
        )


def test_pvc_binding_and_pv_claim_keep_explicit_namespace_and_expected_uid():
    extracted = declared_references(CLAIMS, record(CLAIMS, spec={"volumeName": "disk"}))
    assert [(item.target.kind, item.target.name, item.target.namespace) for item in extracted] == [
        ("PersistentVolume", "disk", None)
    ]
    assert extracted[0].path == "spec.volumeName"
    assert declared_references(CLAIMS, record(CLAIMS, spec={})) == ()
    extracted = declared_references(
        VOLUMES,
        record(
            VOLUMES,
            spec={
                "claimRef": {
                    "name": "claim",
                    "namespace": "other-valid-namespace",
                    "uid": "claim-uid",
                }
            },
        ),
    )
    assert (extracted[0].target.namespace, extracted[0].target.uid) == (
        "other-valid-namespace",
        "claim-uid",
    )
    assert extracted[0].path == "spec.claimRef"
    assert declared_references(VOLUMES, record(VOLUMES, spec={})) == ()


def test_persistent_volume_csi_and_legacy_secret_references_use_their_explicit_namespaces():
    csi_fields = (
        "controllerPublishSecretRef",
        "controllerExpandSecretRef",
        "nodePublishSecretRef",
        "nodeStageSecretRef",
        "nodeExpandSecretRef",
    )
    spec = {
        "csi": {name: {"name": name.lower(), "namespace": "csi-namespace"} for name in csi_fields},
        **{
            name: {"secretRef": {"name": name.lower(), "namespace": "legacy-namespace"}}
            for name in ("cephfs", "rbd", "iscsi", "scaleIO", "storageos", "cinder", "flexVolume")
        },
        "azureFile": {"secretName": "azure", "secretNamespace": "azure-namespace"},
    }
    extracted = declared_references(VOLUMES, record(VOLUMES, spec=spec))
    assert len(extracted) == 13
    assert [item.target.namespace for item in extracted] == ["csi-namespace"] * 5 + [
        "legacy-namespace"
    ] * 7 + ["azure-namespace"]
    assert [item.path for item in extracted[:5]] == [f"spec.csi.{name}.name" for name in csi_fields]
    assert all(item.target.kind == "Secret" for item in extracted)


@pytest.mark.parametrize(
    "spec",
    [
        None,
        {},
        {"containers": []},
        {"containers": None},
        {"containers": [None]},
        {"containers": [{"env": None}]},
        {"containers": [{"env": [None]}]},
        {"containers": [{"env": [{"valueFrom": None}]}]},
        {
            "containers": [
                {"env": [{"valueFrom": {"secretKeyRef": {"name": "secret", "optional": "true"}}}]}
            ]
        },
        {"containers": [{"env": [{"valueFrom": {"secretKeyRef": {}}}]}]},
        {"containers": [{"envFrom": None}]},
        {"containers": [{}], "serviceAccountName": None},
        {"containers": [{}], "serviceAccountName": 0},
        {"containers": [{}], "serviceAccountName": "one", "serviceAccount": "other"},
        {"containers": [{}], "priorityClassName": None},
        {"containers": [{}], "volumes": [{"secret": {}}]},
        {"containers": [{}], "volumes": [{"configMap": None}]},
        {"containers": [{}], "volumes": [{"projected": {"sources": None}}]},
        {"containers": [{}], "volumes": [{"csi": {"nodePublishSecretRef": {}}}]},
        {"containers": [{}], "imagePullSecrets": [{"name": "bad/name"}]},
    ],
)
def test_malformed_supported_pod_paths_cannot_establish_unused(spec):
    # Explicit None bypasses the fixture's default valid Pod spec.
    item = record(spec={} if spec is None else spec)
    with pytest.raises(AppError):
        declared_references(PODS, item)


@pytest.mark.parametrize(
    "resource,spec",
    [
        (DEPLOYMENTS, {}),
        (WORKLOADS[-1], {"jobTemplate": {}}),
        (CLAIMS, {"volumeName": None}),
        (VOLUMES, {"claimRef": {"name": "claim"}}),
        (VOLUMES, {"csi": {"nodePublishSecretRef": {"name": "secret"}}}),
        (VOLUMES, {"azureFile": {}}),
    ],
)
def test_missing_template_storage_or_namespace_data_is_observably_incomplete(resource, spec):
    with pytest.raises(AppError):
        declared_references(resource, record(resource, spec=spec))


def test_declared_uid_must_be_well_formed_and_namespaced_sources_have_scope():
    with pytest.raises(AppError):
        declared_references(ACCOUNTS, record(ACCOUNTS, secrets=[{"name": "x", "uid": 1}]))
    with pytest.raises(AppError, match="explicit namespace"):
        declared_references(PODS, replace(record(), namespace=None))


def test_excessive_and_metadata_only_sources_fail_instead_of_looking_unused():
    for item in (
        replace(record(), metadata_only=True),
        record(metadata={"annotations": {"oversized": "x" * (MAX_RELATIONSHIP_BYTES + 1)}}),
    ):
        with pytest.raises(AppError, match="Incomplete or excessive"):
            declared_references(PODS, item)
    # Each list is legal separately; the aggregate source limit still applies.
    with pytest.raises(AppError, match="declaration items"):
        declared_references(
            PODS,
            record(
                spec={
                    "containers": [
                        {
                            "name": "app",
                            "env": [{"value": "ignored"}] * 6000,
                            "envFrom": [{}] * 4000,
                        }
                    ]
                }
            ),
        )
    # One env item may declare both supported reference types: output has its own bound.
    source = {"valueFrom": {"configMapKeyRef": {"name": "cm"}, "secretKeyRef": {"name": "secret"}}}
    with pytest.raises(AppError, match="Excessive relationship declarations"):
        declared_references(
            PODS,
            record(spec={"containers": [{"env": [source] * (MAX_RELATIONSHIP_ITEMS // 2 + 1)}]}),
        )


@pytest.mark.parametrize(
    "resource,options",
    [
        (ACCOUNTS, {"secrets": [{"name": "x", "kind": "ConfigMap"}]}),
        (ACCOUNTS, {"secrets": [{"name": "x", "apiVersion": "example.test/v1"}]}),
        (ACCOUNTS, {"secrets": [{"name": "x", "apiVersion": "bad/group/version"}]}),
        (VOLUMES, {"spec": {"claimRef": {"name": "x", "namespace": "team", "kind": "Secret"}}}),
        (VOLUMES, {"spec": {"claimRef": {"name": "x", "namespace": "bad namespace"}}}),
    ],
)
def test_wrong_object_reference_gvk_or_invalid_explicit_namespace_is_incomplete(resource, options):
    with pytest.raises(AppError):
        declared_references(resource, record(resource, **options))


def test_storageos_pv_secret_object_reference_preserves_expected_uid():
    refs = declared_references(
        VOLUMES,
        record(
            VOLUMES,
            spec={
                "storageos": {
                    "secretRef": {
                        "name": "storage",
                        "namespace": "other",
                        "kind": "Secret",
                        "apiVersion": "v1",
                        "uid": "original-secret",
                    }
                }
            },
        ),
    )
    assert refs[0].target.uid == "original-secret"
    assert refs[0].target.namespace == "other"
    with pytest.raises(AppError, match="declared type"):
        declared_references(
            VOLUMES,
            record(
                VOLUMES,
                spec={
                    "storageos": {
                        "secretRef": {"name": "storage", "namespace": "other", "kind": "ConfigMap"}
                    }
                },
            ),
        )
