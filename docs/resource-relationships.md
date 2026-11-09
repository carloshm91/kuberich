# Follow resource relationships

Use XRay to follow owners, workload pods, service backends and node placement.
Use UsedBy to find supported declarations that refer to a ConfigMap, Secret,
ServiceAccount, PersistentVolumeClaim or PriorityClass. These views are available
from version 0.4.

You need read access to the selected resource and the related resource families.
A graph does not grant additional access. Start in your permitted scope:

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

The context, namespace and resource names in this guide are fictional.

## Open and explore a graph

1. Open a resource table, such as `:deploy` or `:services`, and select a row.
2. Type `:xray` and press Enter. The root identifies the selected object by its
   API resource, namespace, name and UID.
3. Use Right or Enter to expand a relationship. Right on an expanded row moves
   to a child. Left collapses a branch or moves to its parent.
4. Select a readable, current object and press `o` or type `:open` to open its
   ordinary resource view. KubeRich checks its identity again before opening.

Shift+Left and Shift+Right scroll horizontally. Use `/` to filter the visible
relationship rows; matching descendants keep their ancestors visible. The filter
does not scan hidden branches or broaden an API request. Alt+Left/Alt+Right and
`:back`/`:forward` use the normal navigation history, restoring graph expansion,
filter, selection and scroll position. Configured `:jump` routes use that same
history; see [navigation](command-navigation.md#save-favorite-namespaces-and-jumps).

Graph rows explain relationships. They are not mutation targets. Open an ordinary
resource view before using resource inspection or change commands. Source rows
are explanations of collection coverage and cannot be opened as objects.

## Read the evidence

The **RELATION / EVIDENCE** column distinguishes the reason for each edge:

| Relationship | Meaning |
| --- | --- |
| Controller owner / owner | A declared `ownerReference`, with its expected UID checked against the object read from the API |
| Selector | An inferred label match; it does not establish controller ownership |
| Endpoint | A backend reported by an EndpointSlice or legacy Endpoints source |
| Node | Placement declared by a Pod's `spec.nodeName` |
| Reference | A supported static field names another Kubernetes object |

Outgoing edges lead from the current object to its owner, placement or declared
target. Incoming edges identify dependents or declaring objects. A Service's
selector membership and its reported endpoints remain separate evidence.
Endpoint readiness, serving/terminating conditions and ports describe the
reported backend. An address without a target reference does not establish Pod
identity. A valid explicit endpoint target namespace remains distinct from the
Service's namespace.

Names alone do not establish ownership. An owner with a different observed UID
appears as `replaced`; invalid ownership scope appears as `invalid`. A namespaced
owner must share its dependent's namespace, and a cluster-scoped dependent
cannot have a namespaced owner. Discovered custom owner kinds can be followed
without guessing an API plural. API versions are representations of an object,
not separate identities.

A repeated ancestor appears as `cycle` and stops that branch. A shared object
reached through two separate branches can appear in both; sharing does not prove
a cycle. Pod scheduling selectors, affinity and tolerations are constraints,
not placement evidence. A numeric Pod priority does not identify a PriorityClass.

## Find declarations with UsedBy

Select a ConfigMap, Secret, ServiceAccount, PVC or PriorityClass and type
`:usedby`. Read the source rows before interpreting an empty result. For a
namespaced target, scans use its namespace. For a cluster-scoped target such as
a PriorityClass, scans use your selected namespace, or all namespaces when you
selected `*`. That search scope does not give the root object a namespace.
Cluster-scoped source families, including PersistentVolumes, retain their actual
scope and may contain explicit references to namespaced targets.

The supported declaring sources are Pods; Deployment, ReplicaSet, StatefulSet,
DaemonSet, Job, CronJob and ReplicationController pod templates; ServiceAccounts;
PersistentVolumeClaims; and PersistentVolumes. Templates work even with zero
replicas and no live Pods. Pod fields below are relative to `spec`; workload
fields are relative to `spec.template.spec`, or
`spec.jobTemplate.spec.template.spec` for CronJobs. UsedBy reads these supported
paths:

| Source fields | Targets |
| --- | --- |
| `containers[]`, `initContainers[]`, `ephemeralContainers[]`: `env[].valueFrom.configMapKeyRef.name`, `env[].valueFrom.secretKeyRef.name`, `envFrom[].configMapRef.name`, `envFrom[].secretRef.name` | ConfigMaps and Secrets, including optional flags |
| `volumes[].configMap.name`, `volumes[].secret.secretName`, `volumes[].projected.sources[].configMap.name`, `volumes[].projected.sources[].secret.name` | ConfigMaps and Secrets |
| `volumes[].csi.nodePublishSecretRef.name`; `volumes[].{cephfs,cinder,flexVolume,iscsi,rbd,scaleIO,storageos}.secretRef.name`; `volumes[].azureFile.secretName` | Secrets |
| `imagePullSecrets[].name`, `volumes[].persistentVolumeClaim.claimName`, `serviceAccountName`, `priorityClassName` | Secrets, PVCs, ServiceAccounts and PriorityClasses |
| ServiceAccount `secrets[].name`, `imagePullSecrets[].name` | Secrets |
| PVC `spec.volumeName`; PV `spec.claimRef` | PVs and PVCs |
| PV `spec.csi.{controllerPublishSecretRef,controllerExpandSecretRef,nodePublishSecretRef,nodeStageSecretRef,nodeExpandSecretRef}.name`; `spec.{cephfs,cinder,flexVolume,iscsi,rbd,scaleIO,storageos}.secretRef.name`; `spec.azureFile.secretName` | Secrets with explicit namespaces |

A missing Pod/template service-account name uses the default ServiceAccount and
is labelled as defaulted. The deprecated `serviceAccount` field is supported;
conflicting declarations are invalid. Supported ObjectReferences retain an
explicit expected UID. Name-only declarations resolve the currently observed
object, without proving that a process consumed its configuration. Repeated
fields can produce separate rows explaining each declaration path.

UsedBy does not inspect ConfigMap or Secret values, infer consumption from an
image, search arbitrary custom-resource specifications, or enumerate every
possible Kubernetes dependency. A PV AzureFile Secret whose namespace defaults
to an unknown consuming Pod cannot be resolved from the PV alone; that source
remains incomplete instead of borrowing your selected namespace.

## Interpret incomplete results and retry

Read **STATUS** and each **Source** row's collection state. `forbidden`,
`missing`, `replaced`, `invalid`, `unavailable`, `failed`, `stale` and `truncated`
are distinct from a ready result. `loading` means collection is still pending.
A source marked **INCOMPLETE** cannot establish that no matching declaration
exists. Missing permissions, invalid supported fields and unavailable APIs do not
become a successful empty scan. Even a complete supported scan does not prove
that an object is universally unused.

Expansion is limited to depth 8, 512 visible graph rows and 1,024 relationship
edges. Related reads share a 10,000-item and 16-MiB input limit and 64 logical API
read calls across the graph, including pages and relist attempts. Collection
also has a 30-second deadline. A limit leaves an explicit incomplete result.
Large individual label/selector facts have additional text/item limits.

Expanding or collapsing another branch reuses the graph's cached facts and
remaining request budget. It does not start a fresh scan. An explicit refresh
starts a new collection; source observation times describe their own reads, not
one atomic cluster snapshot. Credential refresh can retry each logical read
once, allowing up to 128 underlying API attempts. Discovery and authentication
helpers have separate limits. These bounds do not limit all network traffic or
the application's total memory.

Correct the relevant permission or source problem, then refresh or reopen the
graph. If the selected root was deleted or recreated, return to its ordinary
resource table and select the current object. Changing context retires the old
reads; results from an earlier session cannot replace the current graph.
