"""Explicit Kubernetes declaration paths; configuration values are never retained."""

from typing import Any

from kuberich.domain.connections import namespace_name
from kuberich.domain.relationships import (
    MAX_RELATIONSHIP_BYTES,
    MAX_RELATIONSHIP_ITEMS,
    DeclaredReference,
    RelationshipRef,
    fact_list,
    fact_mapping,
    fact_name,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, split_api_version
from kuberich.errors import AppError

# These are schema paths, not a recursive search for fields named secretName.
_WORKLOADS = frozenset(
    {
        ("", "pods"),
        ("", "replicationcontrollers"),
        ("apps", "deployments"),
        ("apps", "replicasets"),
        ("apps", "statefulsets"),
        ("apps", "daemonsets"),
        ("batch", "jobs"),
        ("batch", "cronjobs"),
    }
)
REFERENCE_SOURCE_FAMILIES = _WORKLOADS | frozenset(
    {
        ("", "serviceaccounts"),
        ("", "persistentvolumeclaims"),
        ("", "persistentvolumes"),
    }
)
_VOLUME_SECRETS = (
    ("csi", "nodePublishSecretRef", "name"),
    ("cephfs", "secretRef", "name"),
    ("cinder", "secretRef", "name"),
    ("flexVolume", "secretRef", "name"),
    ("iscsi", "secretRef", "name"),
    ("rbd", "secretRef", "name"),
    ("scaleIO", "secretRef", "name"),
    ("storageos", "secretRef", "name"),
    ("azureFile", "secretName"),
)
_PV_SECRETS = (
    ("csi", "controllerPublishSecretRef"),
    ("csi", "controllerExpandSecretRef"),
    ("csi", "nodePublishSecretRef"),
    ("csi", "nodeStageSecretRef"),
    ("csi", "nodeExpandSecretRef"),
    ("cephfs", "secretRef"),
    ("rbd", "secretRef"),
    ("iscsi", "secretRef"),
    ("scaleIO", "secretRef"),
    ("storageos", "secretRef"),
    ("cinder", "secretRef"),
    ("flexVolume", "secretRef"),
)


class _Extraction:
    def __init__(self, namespace: str | None) -> None:
        self.namespace = namespace
        self.items = 0
        self.references: list[DeclaredReference] = []

    def sequence(self, value: Any) -> list[Any]:
        result = fact_list(value)
        self.items += len(result)
        if self.items > MAX_RELATIONSHIP_ITEMS:
            raise AppError("Excessive relationship declaration items.")
        return result

    def add(
        self,
        kind: str,
        name: Any,
        path: str,
        *,
        optional: Any = False,
        namespace: str | None = None,
        defaulted: bool = False,
        uid: Any = None,
    ) -> None:
        if type(optional) is not bool:
            raise AppError("Invalid relationship optional flag.")
        if uid is not None:
            uid = fact_name(uid)
        selected_namespace = namespace if namespace is not None else self.namespace
        if kind in {"PriorityClass", "PersistentVolume"}:
            selected_namespace = None
        elif selected_namespace is None:
            raise AppError("A namespaced declaration requires an explicit namespace.")
        else:
            selected_namespace = namespace_name(fact_name(selected_namespace))
        version = "scheduling.k8s.io/v1" if kind == "PriorityClass" else "v1"
        self.references.append(
            DeclaredReference(
                RelationshipRef(version, kind, selected_namespace, fact_name(name), uid, None),
                path,
                optional,
                defaulted,
            )
        )
        if len(self.references) > MAX_RELATIONSHIP_ITEMS:
            raise AppError("Excessive relationship declarations.")

    def local(self, kind: str, raw: Any, path: str, *, name: str = "name") -> None:
        data = fact_mapping(raw)
        self.add(kind, data.get(name), path + "." + name, optional=data.get("optional", False))

    def containers(self, spec: dict[str, Any], prefix: str) -> None:
        if "containers" not in spec or not spec["containers"]:
            raise AppError("Pod declaration has no containers.")
        for field in ("containers", "initContainers", "ephemeralContainers"):
            for index, raw in enumerate(self.sequence(spec.get(field, []))):
                container = fact_mapping(raw)
                path = f"{prefix}.{field}[{index}]"
                for env_index, raw_env in enumerate(self.sequence(container.get("env", []))):
                    env = fact_mapping(raw_env)
                    if "valueFrom" in env:
                        source = fact_mapping(env["valueFrom"])
                        for field_name, kind in (
                            ("configMapKeyRef", "ConfigMap"),
                            ("secretKeyRef", "Secret"),
                        ):
                            if field_name in source:
                                self.local(
                                    kind,
                                    source[field_name],
                                    f"{path}.env[{env_index}].valueFrom.{field_name}",
                                )
                for env_index, raw_env in enumerate(self.sequence(container.get("envFrom", []))):
                    source = fact_mapping(raw_env)
                    for field_name, kind in (
                        ("configMapRef", "ConfigMap"),
                        ("secretRef", "Secret"),
                    ):
                        if field_name in source:
                            self.local(
                                kind,
                                source[field_name],
                                f"{path}.envFrom[{env_index}].{field_name}",
                            )

    def volumes(self, spec: dict[str, Any], prefix: str) -> None:
        for index, raw in enumerate(self.sequence(spec.get("volumes", []))):
            volume = fact_mapping(raw)
            path = f"{prefix}.volumes[{index}]"
            for field_name, kind, name in (
                ("configMap", "ConfigMap", "name"),
                ("secret", "Secret", "secretName"),
                ("persistentVolumeClaim", "PersistentVolumeClaim", "claimName"),
            ):
                if field_name in volume:
                    self.local(kind, volume[field_name], path + "." + field_name, name=name)
            if "projected" in volume:
                projected = fact_mapping(volume["projected"])
                for source_index, raw_source in enumerate(
                    self.sequence(projected.get("sources", []))
                ):
                    source = fact_mapping(raw_source)
                    for field_name, kind in (("configMap", "ConfigMap"), ("secret", "Secret")):
                        if field_name in source:
                            self.local(
                                kind,
                                source[field_name],
                                f"{path}.projected.sources[{source_index}].{field_name}",
                            )
            for segments in _VOLUME_SECRETS:
                if segments[0] not in volume:
                    continue
                data = fact_mapping(volume[segments[0]])
                if len(segments) == 3:
                    if segments[1] not in data:
                        continue
                    data = fact_mapping(data[segments[1]])
                self.add("Secret", data.get(segments[-1]), path + "." + ".".join(segments))

    def pod(self, spec: dict[str, Any], prefix: str) -> None:
        self.containers(spec, prefix)
        self.volumes(spec, prefix)
        for index, raw in enumerate(self.sequence(spec.get("imagePullSecrets", []))):
            self.local("Secret", raw, f"{prefix}.imagePullSecrets[{index}]")
        name = spec.get("serviceAccountName", spec.get("serviceAccount", ""))
        if (
            "serviceAccount" in spec
            and "serviceAccountName" in spec
            and spec["serviceAccount"] not in ("", name)
        ):
            raise AppError("Conflicting service account declarations.")
        if not isinstance(name, str):
            raise AppError("Invalid service account declaration.")
        self.add(
            "ServiceAccount",
            name or "default",
            prefix + ".serviceAccountName",
            defaulted=not bool(name),
        )
        priority = spec.get("priorityClassName", "")
        if priority:
            self.add("PriorityClass", priority, prefix + ".priorityClassName")
        elif priority != "":
            raise AppError("Invalid priority class declaration.")

    def object_reference(self, kind: str, data: dict[str, Any]) -> None:
        group, _ = split_api_version(data.get("apiVersion", "v1"))
        if group or data.get("kind", kind) != kind:
            raise AppError("Object reference has an invalid declared type.")

    def persistent_volume(self, spec: dict[str, Any]) -> None:
        if "claimRef" in spec:
            data = fact_mapping(spec["claimRef"])
            self.object_reference("PersistentVolumeClaim", data)
            self.add(
                "PersistentVolumeClaim",
                data.get("name"),
                "spec.claimRef",
                namespace=data.get("namespace"),
                uid=data.get("uid"),
            )
        for segments in _PV_SECRETS:
            source = fact_mapping(spec.get(segments[0], {}))
            if segments[1] in source:
                data = fact_mapping(source[segments[1]])
                if segments[0] == "storageos":
                    self.object_reference("Secret", data)
                self.add(
                    "Secret",
                    data.get("name"),
                    "spec." + ".".join(segments) + ".name",
                    namespace=data.get("namespace"),
                    uid=data.get("uid") if segments[0] == "storageos" else None,
                )
        if "azureFile" in spec:
            data = fact_mapping(spec["azureFile"])
            self.add(
                "Secret",
                data.get("secretName"),
                "spec.azureFile.secretName",
                namespace=data.get("secretNamespace"),
            )


def declared_references(
    resource: ApiResource, record: ResourceRecord
) -> tuple[DeclaredReference, ...]:
    """Extract supported declarations, raising when the result cannot be complete.

    ``defaulted`` marks the implicit default ServiceAccount; these declarations do
    not establish that a process has consumed any configuration value. Secret and
    ConfigMap contents, container values and reference keys are never returned.
    """
    family = (resource.group, resource.name)
    supported = family in REFERENCE_SOURCE_FAMILIES
    if not supported:
        return ()
    if record.metadata_only or record.size_bytes > MAX_RELATIONSHIP_BYTES:
        raise AppError("Incomplete or excessive relationship declaration contents.")
    manifest = record.manifest
    extraction = _Extraction(record.namespace)
    if family in _WORKLOADS:
        path = "spec"
        spec = fact_mapping(manifest.get("spec"))
        if resource.name == "cronjobs":
            path += ".jobTemplate.spec"
            spec = fact_mapping(fact_mapping(spec.get("jobTemplate")).get("spec"))
        if resource.name != "pods":
            path += ".template.spec"
            spec = fact_mapping(fact_mapping(spec.get("template")).get("spec"))
        extraction.pod(spec, path)
    elif resource.name == "serviceaccounts":
        for field in ("secrets", "imagePullSecrets"):
            for index, raw in enumerate(extraction.sequence(manifest.get(field, []))):
                data = fact_mapping(raw)
                extraction.object_reference("Secret", data)
                namespace = data.get("namespace", record.namespace)
                if namespace != record.namespace:
                    raise AppError("ServiceAccount Secret reference has invalid namespace.")
                extraction.add(
                    "Secret", data.get("name"), f"{field}[{index}].name", uid=data.get("uid")
                )
    elif resource.name == "persistentvolumeclaims":
        spec = fact_mapping(manifest.get("spec"))
        name = spec.get("volumeName", "")
        if name:
            extraction.add("PersistentVolume", name, "spec.volumeName")
        elif name != "":
            raise AppError("Invalid PersistentVolume declaration.")
    else:
        extraction.persistent_volume(fact_mapping(manifest.get("spec")))
    return tuple(extraction.references)
