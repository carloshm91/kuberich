# 0034: Keep relationship evidence and identity within the selected graph

Status: implemented in development source; scoped acceptance is recorded separately

## Context

Relationship navigation joins discovery, owner chains, structured selectors,
reported endpoints and static declarations across several API families. A name
match or selector match cannot establish UID-based controller ownership. Empty
or denied source scans cannot establish that configuration is unused. A graph
also needs independent ownership after its originating resource route closes.

## Decision

Publish frozen, slotted graph records through `ViewObservation.relationships`
and an explicit relationship route. The root `ResourceTarget` retains its actual
namespace; the graph scope separately retains a selected search namespace for
cluster roots. History keeps a minimal bookmark, expansion paths, filter and
viewport, without raw Kubernetes manifests or configuration values.

The pure domain resolves GVK references through actual discovery, with exact
served-version preference and unambiguous same-family fallback. Object identity
uses group/resource/namespace/name/UID, excluding served version. Owner reads
retain their expected UID; replacements and Kubernetes-invalid owner scopes
remain explicit. Path-local ancestor checks detect cycles while allowing shared
diamonds. Declared name references resolve an observed object without claiming
process consumption.

Use fixed schema paths for Pod/workload, ServiceAccount and storage declarations.
Do not recursively search arbitrary custom-resource specifications for similarly
named fields. Native matchLabels and all four match-expression operators remain
independent of the narrower CLI selector grammar. Default service-account
mappings, selector inferences, declared placement and reported endpoints keep
separate explanatory evidence. Valid explicit endpoint/PV reference namespaces
are preserved; they do not inherit owner-reference namespace restrictions.

`WorkspaceService` owns one `RelationshipService` per graph root. Collection and
expansion share compact extracted facts, cumulative request/input budgets and
one cancellation owner. The service checks session/client identity, root UID and
request revision before publication. Selection invalidates the old request
before awaiting retirement; network work and parser/match workers are drained.
The source route's `TargetCapture.current` guard applies only before entry.

The shared Reader budget charges immediately before every logical `get_json`
call, including each page and 410 restart. A graph has 64 such calls, a 30-second
collection deadline, depth 8, 512 visible rows, 1,024 edges, 10,000 retained input
items and 16 MiB of input. Smaller fact/selector ceilings prevent pathological
individual declarations from bypassing aggregate limits. Collapse/expansion
reuse the remaining budget; explicit refresh starts a fresh collection. Existing
401 refresh can retry each logical call once, allowing 128 underlying API
attempts; discovery/helper traffic has separate bounds. These are not universal
network, process-memory or latency guarantees.

The native table publishes row status, direction, evidence and source
completeness without importing transport operations. Enter/arrows change graph
expansion; opening a readable object is a separate identity-checked navigation
operation. Aggregate/source rows cannot become resource mutation targets.

## Consequences

UsedBy reports supported declarations within an explicit scanned scope. A
forbidden, unavailable, invalid, failed or truncated source prevents an
unqualified absence claim. Custom owners and configured jumps integrate with
normal history, but arbitrary CR reference discovery remains unsupported.
Unknown consuming-Pod namespaces, including implicit PV AzureFile Secret scope,
remain incomplete rather than guessed.

Snapshots and bookmarks contain no `ResourceRecord`, mutable object dictionary,
Secret/ConfigMap values, clients or transport exceptions. Cached facts remain
private to the collector and keep their actual source observation times.
Sources are observed separately, not atomically. Scoped test evidence and
App, owned-cluster and complete-current-head qualification are tracked
in the [acceptance record](../internal/acceptance/resource-relationships.md).

## Source and related decisions

- [Relationship records and decisions](../../src/kuberich/domain/relationships.py), [supported declaration fields](../../src/kuberich/domain/reference_fields.py) and [read budget](../../src/kuberich/domain/read_budget.py)
- [Relationship collector](../../src/kuberich/services/relationships.py), [ResourceReader](../../src/kuberich/services/resources.py) and [workspace ownership](../../src/kuberich/services/workspace.py)
- [Native relationship table](../../src/kuberich/ui/relationships.py), [controller](../../src/kuberich/ui/controllers/relationships.py) and [view store](../../src/kuberich/domain/views.py)
- [Discovery identity](0005-discovery-and-printer-schemas.md), [active view generations](0007-active-view-generations.md) and [application composition](app-composition.md)
- Kubernetes [owners](https://kubernetes.io/docs/concepts/overview/working-with-objects/owners-dependents/), [selectors](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/) and [EndpointSlices](https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/)
