# 0033: Keep cluster summaries and history within the selected session

Status: implemented in development source; complete issue acceptance remains pending

## Context

The resource workspace owns one active collection. A cluster overview needs
several resource families, current metrics and optional historical queries while
retaining the same context, frame and navigation controls. A summary row is not
a Kubernetes API object and must not become a mutation target.

History may come from a federated backend. Selecting its endpoint per context
does not establish that every returned series belongs to that Kubernetes cluster.
Historical evaluation time also does not establish scrape freshness.

## Decision

Add an explicit `ViewKind.PULSE` and `PulseController`. Do not create a fictitious
API resource. `WorkspaceService` owns the selected mode and drains the ordinary
watch/metrics owner when switching to Pulse. `PulseService` reuses the captured
Kubernetes client and discovery, reads a fixed family set serially and publishes
one replaceable observation with progressive per-source states and times.

Pure `domain/pulse.py` decisions produce health counts and the typed predicates
used by drill-downs. Navigation keeps the selected API/version, namespace,
predicate, numeric sort and optional UID. The root workspace retains Pulse's
selection, filter and variable-height viewport across Back/Forward. Aggregate
rows expose navigation, not resource mutation or inspection targets.

Retained Node/Pod membership, workload inputs and metric samples share a combined
collection limit. Workload raw records are released after incremental counts.
Partial collections and uncertain budgets cannot establish complete totals.
These retained-payload bounds do not claim a whole-process RSS limit.

`domain/history.py` holds immutable values, explicit availability and a bounded
aggregate-matrix parser. `HistoryReader` performs two internal `query_range`
expressions through a validated relative Kubernetes Service-proxy path. It uses
the selected session's authentication/TLS, rejects redirects and never sends
its Authorization header to a separately configured external URL.

The versioned `observability` preference extension selects Service details and
literal label matchers per exact context. Explicit cluster-label/value settings
declare the operator's binding; otherwise the UI says that backend scope is
unverified. Namespace selection is a separate matcher. Unsupported or conflicting
configuration cannot broaden a query silently.

An independent expiry owner clears current usage and historical values while a
subsequent read is pending. Context changes, replacement and exit invalidate the
generation before draining the collector, history work, expiry and parser workers.
Validated backend reload cancels the previous query and restarts Pulse; unrelated
theme changes keep the collection running.

## Consequences

Current Node usage, active-pod sums and backend historical aggregates remain
separate measurements with visible sources. Missing/forbidden/partial/stale data
does not become a healthy state or measured zero. History has visible numeric
units and gaps, and query time is not presented as scrape time.

This delivery implements overview CPU/memory history through a configured
Prometheus Service. Broader per-entity, network/filesystem, range and provider
support remains separate work. Actual owned Prometheus integration and final
current-head/platform qualification are recorded in the
[acceptance evidence](../internal/acceptance/cluster-overview.md); a contract or
focused test result does not substitute for those measurements.

## Main modules

- [Pulse models](../../src/kuberich/domain/pulse.py) and [history models](../../src/kuberich/domain/history.py)
- [Pulse collector](../../src/kuberich/services/pulse.py), [history reader](../../src/kuberich/services/history.py) and [workspace owner](../../src/kuberich/services/workspace.py)
- [Observability preferences](../../src/kuberich/config/observability.py)
- [Pulse table](../../src/kuberich/ui/pulse.py), [controller](../../src/kuberich/ui/controllers/pulse.py) and [navigation](../../src/kuberich/ui/workspace_navigation.py)
