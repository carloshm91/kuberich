# Understand the workspace

The workspace keeps the selected context, resource scope, and available actions
visible while you move between tables, inspection, logs, and terminals. Different
views share a frame, but their rows and keys have different meanings.

## Identity and focus

The header shows context, cluster/user aliases, namespace, connection state, and
installed version. Credentials stay hidden. Shortcuts change with the focused
view. The command and filter bars sit above resources; inline completion never
covers the table. The bottom trail identifies the parent view and Escape action.

Escape first leaves an input, then clears an active filter, then returns to the
parent view. Letters in an input remain text. In a live embedded terminal, keys
belong to the remote program except the documented local return/quit controls.
The [navigation guide](command-navigation.md) explains concrete keys.

## Local contexts and live resources

Context rows are local kubeconfig entries. Browsing and filtering them makes no
API request; Enter deliberately connects. Resource rows come from the selected
API and scope. Namespaces are a live table too; Enter opens that namespace's pods,
while `0` chooses all namespaces.

Only the active resource view is watched. Its first successful list establishes
the rows, and watch updates change them afterward. Temporary failures keep the
last snapshot with a stale state. A denied list remains an error, not an empty
successful table. Context changes replace the client and reject old results.

Selection follows UID rather than row position or name. Sorting, filtering, and
updates preserve the selected object and viewport where possible. A replacement
with the same name has a different UID and does not inherit an old operation.
Read permissions and cluster capabilities still decide which views are available.

## Large collections and server selectors

Large collections remain live with a deterministic kept subset of at most
10,000 resources and 64 MiB of resource payloads, including server cells.
These are payload limits, not a total-process memory guarantee. Pagination reports
available rows and progress. An **INCOMPLETE** title identifies a limited or still
loading collection, even when a selection notice replaces the status text.
Counts and local filter results describe only those available rows.

Use an explicit command to narrow the API collection:

```text
:server label app=api
:server label app in (api,worker),!disabled
:server field metadata.name=api-one
:ns team
:server
:server clear
```

`:server` shows the active query. Label and field selectors combine; `clear`
removes both selectors and preserves the payload mode. Selector changes restart
the current LIST/WATCH scope. Back/forward retains the server query separately from
the local `/` filter. Typing in `/`, including local `label:` and `field:` filters,
never changes server selectors or sends a request for each keystroke.

Selectors accept up to 256 characters and eight AND terms. Server field
selectors use the existing field allowlist; Kubernetes may reject a field that
the selected resource does not support. Namespace selection is another way to
narrow results. A deletion below the row limit does not prove the missing
rows disappeared: only a fresh complete list clears the incomplete state.

In a generic resource view, `:server compact` requests Table rows with genuine
`PartialObjectMetadata`, keeping identity and server-printer cells while reducing
raw payloads. A server without that representation falls back to full JSON.
`:server full` restores full objects while preserving selectors. Native views and
core Pod/Service views retain full objects for their existing actions. Inspection
always reads a fresh full object; a configured jump needing absent fields asks
for `:server full`. Incomplete event lists and aggregate-log membership also
identify their available subset explicitly.

## Standard and discovered views

Open the native [cluster overview](cluster-overview.md)
through `:pulse` or `:overview`. Its summaries carry their own scope, observation
time and availability. Enter opens the underlying resource list with the same
health/phase predicate; current CPU/memory rows open the corresponding list sorted
by usage. Aggregate rows are navigation entries rather than Kubernetes objects.

Standard views provide resource-specific summaries for workloads, networking,
configuration, nodes, and storage. The generated [resource reference](resource-reference.md)
lists actual aliases and columns. Counts, dates, and quantities sort by their
types; unknown values stay last. Cluster-scoped resources reject a namespace
argument while preserving your namespace choice for later views.

Other APIs, including custom resources, use discovery and server Table columns.
`:resource widgets.example.test/v1` selects a specific family/version; the example
is fictional. An omitted version follows discovery's preferred version.
Ambiguous aliases require qualification. No endpoint or API group is guessed.
`:refresh` renews discovery and the current watch without replacing credentials.

If server Table columns are absent or malformed, metadata columns stay usable.
Changed printer schemas do not reinterpret old cell values as new fields.
`:columns` selects transient server fields; `:views` supports explicit saved
layouts. Layouts affect display rather than confidentiality.

Generic discovered views are read-only inspection views. Ordinary built-in routes
provide their applicable mutation, log, shell, transfer, or forwarding actions.
`:resource pods` deliberately uses generic inspection; `:pods` returns to the pod
workspace. Arbitrary custom fields can contain sensitive information that
redaction does not recognize; inspect resources appropriate to your access.

## Curated read-only views

Version 0.4 adds HPA, VPA, PDB, NetworkPolicy, EndpointSlice, IngressClass,
PriorityClass, RuntimeClass, Lease, ResourceQuota, LimitRange, admission webhook,
ServiceAccount and RBAC tables.
Use their aliases from the [resource reference](resource-reference.md), for example:

```text
:hpa demo-apps
:pdb demo-apps
:netpol demo-apps
:sa demo-apps
:resource horizontalpodautoscalers.autoscaling/v1 demo-apps
```

Each view binds its actual discovered API group, version, kind and scope. A
specific HPA version keeps that version's interpretation rather than silently
switching to another API. Unknown versions and metadata-only responses show
metadata with an explanation instead of interpreting arbitrary printer cells.
`:server compact` requests metadata for these read-only views; `:server full`
restores the complete resource representation. APIs and objects still require
permission. VPA must already be installed in the cluster; KubeRich installs no
autoscaler or other controller.

Details summarize declared configuration and observed status separately.
Unavailable facts stay unknown, while fields with defined API defaults retain
those defaults. Zero, false and an explicitly empty list keep their meanings.
Long sections report omitted entries. Webhook trust bundles, secret values,
annotations and command arguments stay concealed in default views. HPA's metric
configuration is distinct from live CPU/memory usage. A PDB declaration does not
prove an eviction will succeed, and NetworkPolicy declarations do not prove
network reachability.

Use **Links** or Shift+L in an inspector to see declared destinations and their
provenance. Enter follows an available link through the normal resource,
relationship or authorization workspace. Literal selectors, namespace scope and
observed UIDs stay attached to the destination. Missing APIs, ambiguous kinds,
UID mismatches and changed source declarations remain explicit failures.
Declared references without a UID open the current named object after a fresh
read; they do not establish historical continuity.
Changing the parent cursor does not retarget an open inspector. Escape and
Back/Forward preserve the parent selection, filter and scroll position.
Changing a server selector keeps the declared local membership restriction; it
narrows the API request within that scope. Screen exports record the captured
membership type and a bounded identity fingerprint, rather than copying raw
selector values into report metadata. A fingerprint identifies the observation's
scope; it is not a query that can be reconstructed and run later.

These additional tables expose read-only navigation and inspection even when
the application permits writes elsewhere. They do not add scale, edit, delete
or admission/policy mutation commands.

### Events

`:events demo-apps` opens individual Events; `:ev *` selects all namespaces.
KubeRich chooses a discovered `events.k8s.io/v1` API, with core `v1` as a fallback
when that API is absent. An explicit `:resource events.core/v1 demo-apps` or
`:resource events.events.k8s.io/v1 demo-apps` keeps that source. It never combines
both API collections or switches source after a permission error.

Press `w` to switch between warnings and all types, and `t` to group or ungroup.
Groups distinguish type, reason, namespace and referenced object identity.
Objects with the same name and different UIDs remain separate; missing object
UIDs do not imply a match. Enter on a group opens its retained individual Event
members; Escape returns to that group. Enter on an individual Event opens its
details. A referenced-object link requires an observed UID and a fresh matching
read. A group is an aggregate observation, not a resource or mutation target.

Occurrence counts describe the retained observations, not incident duration or
the number of affected Pods. Unknown counts stay separate from known counts.
Reported last-occurrence times are distinct from the displayed **Observed**
snapshot time. Filtering, sorting and a quiet watch do not create a newer source
sample. Partial, stale, denied and limited sources remain visible; filtering
unknown Event types does not establish that there were no warnings. Event
messages and notes are excluded from default summary rows and text matching.
Server-query changes retain the warnings, grouping and member choices. Screen
exports record those choices and, for members, the exact group's identity
fingerprint. Export metadata does not include raw Event messages or notes.

## Snapshot inspection and live containers

Details, YAML, and events show a selected resource read snapshot. They do not
silently become a different resource when the parent cursor changes. Ordinary
inspection redacts sensitive values. ConfigMap/Secret reveal is a separate
[deliberate data view](editing.md#inspect-configuration-data).

Enter on a pod opens regular, init, and existing ephemeral containers. Container
state, readiness, restarts, image, probes, declared ports, and requests/limits
come from that pod. The table refreshes from the existing pod watch without a
separate watch per container. Selection follows container name. The declared
requests/limits stay separate from the current CPU/memory usage columns below.

Enter on a container opens its logs. Shell and attach open an embedded terminal
with the selected target displayed. Returning restores the parent selection.
Deletion, replacement, or scope changes invalidate the old target.

## Current CPU and memory metrics

Native Pod, workload and Node tables read the server's discovered
`metrics.k8s.io` API. A cluster administrator must provide a Metrics API implementation,
such as metrics-server, and grant the relevant read access. KubeRich does not
install one. Namespace Pod metrics and cluster Node metrics have independent
availability and permissions.

`CPU(m)` uses millicores: 1000 m equals one core. `MEM(MiB)` uses mebibytes:
1 MiB equals 1,048,576 bytes. CPU is the average over the reported sampling
window; memory is the sampled working set. Requests, limits, capacity and allocatable use the same
display units. Header percentages name their denominator: `%REQ` means usage /
configured request, `%LIM` means usage / configured limit, and Node `%ALLOC`
means usage / allocatable.
Values can exceed 100%. Zero usage stays `0`; absent or zero denominators show
`N/A`, and an absent container limit shows `unlimited`.

The `METRICS` field distinguishes `valid`, `no sample`, `API unavailable`,
`forbidden`, `stale`, `partial` and `read failed`. A failed read clears old usage;
it never becomes a measured zero. Samples older than 60 seconds expire, including
in an open container screen. Polls run every 15 seconds after the previous batch
finishes, using the selected client and namespace. Scope changes and exit stop
and drain the old poll. Use `:refresh` after changing API installation/discovery.

The main table also expires its cached batch while a subsequent API read is
pending, independently of the AGE refresh preference. The earliest still-usable
sample deadline expires that batch and labels it `metrics cache expired`.
Newer samples in the same batch may therefore lose displayed usage before their
own 60-second age; original sample timestamps/windows and configured budgets
remain intact. This is a maximum cache lifetime, not a promise to retain every
newer sample for 60 seconds. A completed fresh read replaces the expired cache.

CPU/memory quantities, percentages and sampling windows sort by numeric values. `:wide` exposes sample time in UTC,
window in seconds and generic extended resource names; `:views` can hide or
reorder metric fields. Existing saved column layouts keep their chosen fields. Workload sample time is the oldest member timestamp and
window is the largest member window, rather than one shared sampling interval.

Workload totals include actual Pods identified by UID and controller ownership,
including Deployment → ReplicaSet and CronJob → Job chains. Desired replicas
and matching labels never establish totals. Missing samples and incomplete
membership show counts/partial status and suppress full usage percentages.
Requests/limits are complete only when every required member's budget is known.
Node usage comes from Node metrics and includes node processes; its Pod request
sum needs a complete cluster-wide Pod list. Namespace-only RBAC can leave Node
usage/allocatable percentages available while Pod allocations say incomplete.

Pod allocation with init containers, sidecars, overhead or a Pod-level resource
budget is explicitly uncertain: usage stays available,
but effective Pod request/limit totals and their percentages show `N/A (budget)`
or `N/A`. Container percentages still use that container's declared budget.
Known requests/limits describe admitted declarations, rather than proof that a
resize has finished. Matching ordinary Pod/container status fields and omitted
optional telemetry preserve those declarations. Status differences, including
kernel-rounded Pod cgroup values, do not erase configured budgets or their
percentages. They label active allocation unconfirmed; an explicit active or
unconfirmed resize also receives that label. Node Pod-allocation totals become
uncertain when a member's active allocation is unconfirmed, while Node usage /
allocatable stays available. These values do not claim scheduler reservations. Extended resource fields show
vendor-neutral declared requests/limits and Node capacity/allocatable values;
the CPU/memory Metrics API provides no GPU utilization. Collection payload/row
limits still apply. For configured historical charts, select a Node, Pod, workload or container and
press Shift+M. See [metric history](cluster-overview.md#explore-metric-history)
for backend requirements, units and identity limits.

## Connection state and action results

A connected session means connection setup succeeded; each resource request can
still fail independently. Read-only is an application policy, not extra Kubernetes
RBAC. It blocks effectful actions while allowing reads and local preference
changes. Server authorization remains authoritative.

Changes use Review and separate Confirm. A successful API request does not prove
a controller finished reconciling or that dependents finished deleting. A lost
response can leave an uncertain outcome. [Workload operations](workloads.md) and
[resource changes](editing.md) describe those distinctions.

## Compact layouts and themes

The default `k9s` theme uses a dark palette and readable state words. Other
built-in/custom themes, a monochrome theme, and session inversion are available.
The installed version appears in the header; optional update notices require
local opt-in. See [configuration and themes](configuration.md).

Narrow layouts omit secondary aliases and branding while keeping commands,
status, and resources available. Short layouts reduce header rows. Help exposes
secondary controls. Fullscreen/headless controls adjust this session's frame
without changing saved preferences. Font, color, clipboard, and key forwarding
still depend on the terminal and any SSH/tmux layers.
