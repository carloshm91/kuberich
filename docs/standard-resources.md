# Standard resource views

B05 #41 adds 15 resource families to the existing live workspace. Endpoints and
served versions come from the connected cluster's discovery response. Each view
uses the same scoped LIST/WATCH owner, stable UIDs, filter bar and history.

| Command (full resource names also work) | Main columns |
| --- | --- |
| `:deploy` | Ready, desired, updated, available replicas |
| `:rs` | Desired, current, ready replicas |
| `:sts` | Ready, desired, current, updated replicas |
| `:ds` | Desired, current, ready, available nodes |
| `:job` | Outcome, succeeded, completions, active, failed |
| `:cj` | Schedule, suspend, active jobs, last schedule |
| `:svc` | Type, cluster IP, external address, ports |
| `:ep` | Ready/not-ready addresses, ports |
| `:ing` | Class, hosts, published address |
| `:cm` | Counts of data and binary keys |
| `:sec` | Secret type and key count |
| `:no` | Readiness, scheduling disabled, roles, kubelet version |
| `:pvc` | Phase, volume, capacity, access modes, storage class |
| `:pv` | Capacity, access modes, reclaim policy, phase, claim, storage class |
| `:sc` | Provisioner, reclaim policy, binding mode, expansion |

Namespaced tables also show namespace; every table shows name and age. For a
chosen scope, use `:deploy TEAM` or `:svc *`. Nodes, PVs and StorageClasses are
cluster-scoped; a namespace argument is rejected. They preserve the session's
namespace choice for the next namespaced view. Initial commands work too:

```sh
uv run kubetrol --context YOUR_CONTEXT --readonly --command 'deploy YOUR_NAMESPACE'
```

Only run that command against a context you intend to read. `:c` still offers
context commands first; additional resource aliases appear in the same inline
completion. Tab accepts a suggestion. `/` searches displayed summary fields;
Secret and ConfigMap payload values never enter rows or filter text.

Use Enter or `d` for details, `y` for redacted YAML, `e` for UID-associated events,
and Escape to return to the retained table. `s` cycles sort columns, Shift+S
reverses, and clicking a header selects that column. Counts, capacities and times
sort by their typed values. Unknown values stay last in either direction.
Kubernetes may omit zero status counters; a completely missing workload status
remains unknown. `j/k` and `g/G` navigate; Alt+Left/Right restores the prior view,
including scope, filter, sorting and viewport.

Shell and logs remain pod/container actions. Editing, scaling, rollout, deletion,
port forwarding, owner drill-down and generic CRD columns have separate tickets.
This release of the view registry does not establish those behaviors or full K9s
parity. Endpoints remains available when served, although modern clusters should
also support the later EndpointSlice view tracked in the networking backlog.

An absent API, denied LIST/WATCH/GET, expired resource version and a successful
empty collection retain their distinct existing states. No fallback guesses a
different API group or silently substitutes an empty list.

`domain/registry.py` holds immutable definitions and pure summaries;
`services/pods.py` shares the owned background projection cache;
`ui/standard.py` renders all these families in one table. Ordinary details use
the existing [inspection policy](resource-inspection.md). Discovery, watch and
context-generation behavior remain in the existing services.

See [acceptance evidence](acceptance/standard-resources.md) and the
[quickstart](quickstart.md). Field semantics follow the official
[Deployment API](https://kubernetes.io/docs/reference/kubernetes-api/apps/deployment-v1/),
[PersistentVolume API](https://kubernetes.io/docs/reference/kubernetes-api/core/persistent-volume-v1/),
[Endpoints API](https://kubernetes.io/docs/reference/kubernetes-api/core/endpoints-v1/)
and [Quantity definition](https://kubernetes.io/docs/reference/kubernetes-api/definitions/quantity-resource/).
