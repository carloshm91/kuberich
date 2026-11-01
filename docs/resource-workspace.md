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

## Standard and discovered views

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

## Snapshot inspection and live containers

Details, YAML, and events show a selected resource read snapshot. They do not
silently become a different resource when the parent cursor changes. Ordinary
inspection redacts sensitive values. ConfigMap/Secret reveal is a separate
[deliberate data view](editing.md#inspect-configuration-data).

Enter on a pod opens regular, init, and existing ephemeral containers. Container
state, readiness, restarts, image, probes, declared ports, and requests/limits
come from that pod. The table refreshes from the existing pod watch without a
separate watch per container. Selection follows container name. CPU/memory show
requested/limited quantities rather than measured usage.

Enter on a container opens its logs. Shell and attach open an embedded terminal
with the selected target displayed. Returning restores the parent selection.
Deletion, replacement, or scope changes invalidate the old target.

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
