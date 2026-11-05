# 0036: Preserve diagnostic evidence and own explicit external scans

Status: implemented in development source; application and platform qualification
are recorded separately

## Context

Conditions, container states, Events and storage declarations are observations,
not a universal explanation of a failure. A name can identify a replacement
object, old Events can survive a recovered condition, and unavailable sources
cannot establish health. Optional external tooling introduces another local
program, report schema and collection boundary.

The Diagnostics view needs native resource/log navigation without representing
findings or source notices as Kubernetes objects. Header namespace, selected
root namespace and session generation can differ during history restoration.
Native and external work must share a publication budget and one lifecycle.

## Decision

### Keep evidence and identity explicit

Use immutable diagnostic scope/request/evidence/finding/source/snapshot records
in `domain.cluster_diagnostics`. Reuse `RelationshipRef` and actual discovered
served descriptors; do not introduce a competing resource identity or import
view/navigation types into the domain. The bookmark contains collection namespace
and root only. Existing history owns selection, filter, sort and viewport.

Native finding keys hash canonical subject identity, category and container.
Evidence keys add source, evidence-object identity, field path and reason.
Timestamps are provenance rather than row-key material. Legal repeated PVC
references retain distinct declaration paths while sharing one target GET.
Popeye keys include producer/report identity and duplicate occurrence, and do
not merge with native findings. Container pseudo-resources never become API
identities.

Classification uses finite condition/reason sets. Image-pull/backoff state,
unschedulable conditions, crash-loop waiting state, false/unknown readiness,
volume failure Events and actual workload conditions keep their qualifications.
Generic Event reasons can enrich an already observed condition but cannot select
a cause category. Restart count, Pending phase, zero replicas or a suspended
CronJob do not independently establish the corresponding failures.

Retain local collection time separately from server-reported time. Events older
than an hour are historical; malformed/missing/future Event times are unknown.
A current scheduled condition supersedes an earlier scheduling Event. Collection
age reaches stale after 60 seconds without hidden polling. Old condition
transition time alone does not prove stale state; older observedGeneration does.
Partial acquisition and old age remain independent facts.

### Collect over one captured session

`DiagnosticService` uses an injected per-context reader/discovery/policy and a
request-current callback. Root GET verifies UID before collecting subordinate
objects. Deployment/ReplicaSet and CronJob/Job chains use exact controller
UID/name/kind/group/namespace checks, never label-based ownership. Namespace
mode reads Pods and UID-matched Events; richer workload/PVC evidence requires a
selected root.

Choose one discovered Event API family. Use served events.k8s.io only when core
Events are absent from discovery; a forbidden core read never triggers a second
family to hide denial. Match involvedObject/regarding by exact subject identity
and retain each Event's own served descriptor and UID for navigation.

Use owned workers for extraction/matching and drain them through cancellation.
Allowlist status, condition, event and declaration facts. Do not publish raw
manifests, environment/command values, Secret/ConfigMap values or raw errors.
Apply existing redaction/control escaping before truncating published text.

One native collection shares 64 logical `ResourceReader` charges, 10,000 input
objects and 16 MiB retained input. Reserve half the object/input allowance for
Events. Compact facts have a 2-MiB/10,000-fact ceiling; each resource permits 128
condition/status entries. Limit messages to 4 KiB, evidence to 16 entries per
finding and distinct referenced PVC GETs to 16. Collection has a 30-second
deadline. Publish charged attempts before a transport await, so interruption
cannot omit an in-flight charged read from the counter. Authentication retries
and discovery retain their independent transport limits.

Explicit object resolution has a separate four-read action budget and rechecks
request, client/session, served identity and expected UID. Only actual GET
records become resource targets. Log actions use the existing LogStream and
LogScreen with current/previous mode selected before opening. No diagnostic
collection fetches log bytes. A separately opened log callback depends on its
client/full session/header/target, not a later diagnostic request revision.

### Serialize producers and namespace intent

`DiagnosticWorkspace` owns one native or Popeye producer. Prepare invalidates old
callbacks synchronously and cancellation drains before the next start. The
WorkspaceService selection captures request plus producer and binds the final
SessionIdentity after any namespace transition. Current checks include captured
client identity, complete session UUID/generation, outer store revision, bound
request and usable session state. Unexpected producer errors invalidate current
callbacks, use the sanitized error path and retrieve task exceptions; refresh
can recover using the retained observation scope.

A root's namespace is the collection namespace; the header can remain another
namespace or all. A root-free overview must match the header. Explicit namespace
selection, including reselecting the same namespace, drops the root and advances
the session generation. History submits saved header and root atomically, then
recollects and verifies root UID. Explicit context connection invalidates old
work; an external process is never automatically restored.

Explicit cancellation invalidates before awaits, drains the producer, then binds
the collaborator's new idle request and retained cancelled/incomplete snapshot.
Keep completed rows and observation times. A newer selection during cleanup
prevents the cancellation result from rebinding the old scope.

A same-scope Popeye run carries native findings, source acquisition status,
observation times and `native_requests_used`, replacing its previous external
partition. Native refresh clears both partitions and never silently reruns the
tool. Different scope/session/root carries no rows. Failed/cancelled external
work preserves carried native evidence with an actual failed/cancelled source.

The combined publication permits 1,000 findings and 2 MiB retained UTF-8 text,
counting each stored string occurrence conservatively. Reserve 32 KiB inside that
budget: native source/scope metadata uses one 16-KiB share and external source
summaries the other. Keep native findings first and pass remaining row/text/source
budgets to the external parser before normalization. Do not retain independent
2-MiB producer reports plus a combined duplicate. Source omissions remain visible
with counts and partial status even if no external finding fits.

### Keep the optional executable behind its own boundary

App injects a typed `DiagnosticPopeye` callable into WorkspaceService. Workspace
never reads local settings or constructs tool argv. `config.popeye` validates an
absolute executable path, 1–16 unique canonical linter sections, a 1–120 second
scan deadline and explicit read-only trust classification. Global observability
provides a fallback; an exact context block replaces the whole global block,
including history/tool settings.

`PopeyeService` accepts the pinned v0.22.1 version tuple and strict versioned JSON
layout. Existing ProcessRunner owns the version probe and scan, bounds combined
output, and terminates descendants on timeout, output overflow or cancellation.
Existing delegation stages one private selected-connection configuration with
credentials/TLS/impersonation and removes it only after process/parser drain.
Pass explicit kubeconfig, context, namespace/all-namespaces, sections and JSON
arguments as vectors. No ambient current-context lookup or shell interpolation
belongs to the integration. The read-only trust flag is classification, not an
executable sandbox.

Popeye scans the diagnostic namespace even when a root exists; the root UID is
not an external scan filter. Native64 does not constrain another process's API
reads: discovery, preloads and self-reviews make that count unknown. Probe/scan
status, version, sections, report time, parser identity and limits stay explicit.
Malformed/unsupported reports, missing executables, refusal and nonaccepted
process outcomes never become successful empty scans. Native and external
severity/source remain independent.

## Consequences

Diagnostics explains collected evidence and uncertainty; it neither certifies
health nor performs automatic remediation. Name-only external references can
open the current object after GET, while historical UID identity stays
unverified. Missing/ambiguous served identity remains nonactionable. Fresh Pod,
UID and container checks are required for an explicit current log read; a
name-only report never invents previous-instance evidence.

A partial source can age, an Event can be historical after recovery, and an
empty result can reflect unavailable evidence. Sources and limit notices remain
informational rows and survive filtering. Reconnects, restoration and refresh
use fresh collection rather than a historical report as current truth.

## Source and verification

- [Records/classification](../../src/kuberich/domain/cluster_diagnostics.py) and [literal rows](../../src/kuberich/domain/diagnostic_rows.py)
- [Native service](../../src/kuberich/services/cluster_diagnostics.py), [single producer owner](../../src/kuberich/services/diagnostic_workspace.py) and [workspace integration](../../src/kuberich/services/workspace.py)
- [Popeye settings](../../src/kuberich/config/popeye.py), [versioned parser](../../src/kuberich/domain/popeye.py) and [explicit process service](../../src/kuberich/services/popeye.py)
- [Native navigation](../../src/kuberich/ui/diagnostic_navigation.py), [evidence screen](../../src/kuberich/ui/diagnostic_evidence.py) and [active-generation decision](0007-active-view-generations.md)
- [Pure contracts](../../tests/unit/test_cluster_diagnostics_native.py), [native HTTP](../../tests/contract/test_diagnostic_native_service.py), [producer cancellation](../../tests/contract/test_diagnostic_native_workspace.py) and [workspace scope/drain contracts](../../tests/contract/test_diagnostic_workspace_integration72.py)
- [User guide](../cluster-diagnostics.md) and [verification policy](../quality.md); measured acceptance stays outside user navigation
