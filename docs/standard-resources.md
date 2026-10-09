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
uv run kuberich --context YOUR_CONTEXT --readonly --command 'deploy YOUR_NAMESPACE'
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

Shell and logs remain pod/container actions. [Manifest editing](editing.md),
[workload scale/rollout](workloads.md) and [port forwarding](port-forwards.md) now
have their own implemented contracts. [Deletion and Job operations](resource-operations.md)
use captured confirmation and retained results. Owner drill-down remains O03 #70.
These views do not establish full K9s parity.
Endpoints remains available when served, although modern clusters should
also support the later EndpointSlice view tracked in the networking backlog.

An absent API, denied LIST/WATCH/GET, expired resource version and a successful
empty collection retain their distinct existing states. No fallback guesses a
different API group or silently substitutes an empty list.

`domain/registry.py` holds immutable definitions and pure summaries;
`services/pods.py` shares the owned background projection cache;
`ui/standard.py` renders all these families in one table. Ordinary details use
the existing [inspection policy](resource-inspection.md). Discovery, watch and
context-generation behavior remain in the existing services.

## Generic discovered resources: B06 #53

Browse other discovered APIs, including CRDs, with an unambiguous plural,
singular or short name: `:wdg TEAM` or `:widgets *`. Qualify a family as
`:widgets.example.test`; append `/v1beta1` to select that exact served version.
An omitted version follows discovery's preferred version, including after
`:refresh`. The title shows the actual API group/version and selected scope.
Explicit cluster-scoped namespace arguments are rejected. Built-in command
and standard-resource aliases retain their familiar meaning; `:resource NAME`
selects a discovered alias that overlaps one. `.core` explicitly selects the
core API group, for example `:resource pods.core/v1`.

For initial generic navigation, use an explicit resource command:

```sh
uv run kuberich --context YOUR_CONTEXT --readonly --command 'resource widgets.example.test/v1beta1 YOUR_NAMESPACE'
```

The application connects and discovers APIs before resolving this initial
command. Unknown or ambiguous families keep the available view and report the
error; no endpoint or version is guessed. Completion offers qualified names and
served versions, hiding ambiguous discovered short names. `:refresh` renews
discovery and the owned LIST/WATCH without reloading credentials or replacing
the connected client. Removed APIs remain a failure state; use `:po` or another
available resource command to recover. `r`/`:retry` still reconnects.

Server Table columns appear alongside metadata-backed namespace, name and age.
Numeric, boolean and date columns sort by their types; unknown values sort last.
When Table conversion or malformed printer metadata is unavailable, the view
uses the stable metadata columns and retains full objects for inspection.
Each retained row carries its own printer schema. A renewed schema leaves
incompatible old cells unknown until their objects update, retaining selection
without interpreting old values under a different header.

`:columns` lists the server's positional keys, such as `c2=Level` and
`c3=Enabled`; the server's identity/age columns are omitted. Use
`:columns c3 c2` to choose and order fields, including optional wide-priority
fields. `:columns none` shows metadata only and `:columns default` restores the
server's ordinary columns. Invalid or duplicate keys retain the previous view.
Layouts are transient, bounded to 32 context/GVR entries, and reset when the
server schema changes. Persistent preferences/hotkeys remain U02 #57.

Enter/`d`, `y` and `e` reuse captured-UID details, redacted YAML and related events.
Unknown manifest fields remain in YAML. `/` searches displayed fields;
Alt+Left/Right and the context/namespace workspaces retain resource identity,
version, filter, compatible sort and viewport. Direct `:ns TEAM` preserves an
active generic resource. Generic browser actions are read-only in this
checkpoint; custom editing remains M05 #55, and reactive jump chains U06 #64.
Server headers and strings are displayed literally, sensitive column names and
credential-shaped cells are redacted, and opaque Secret/ConfigMap server cells
are hidden. Arbitrary custom fields are not guaranteed to be confidential;
inspect only resources appropriate for your context and access.

See [generic browser acceptance](acceptance/generic-resource-browser.md).

See [acceptance evidence](acceptance/standard-resources.md) and the
[quickstart](quickstart.md). Field semantics follow the official
[Deployment API](https://kubernetes.io/docs/reference/kubernetes-api/apps/deployment-v1/),
[PersistentVolume API](https://kubernetes.io/docs/reference/kubernetes-api/core/persistent-volume-v1/),
[Endpoints API](https://kubernetes.io/docs/reference/kubernetes-api/core/endpoints-v1/)
and [Quantity definition](https://kubernetes.io/docs/reference/kubernetes-api/definitions/quantity-resource/).
