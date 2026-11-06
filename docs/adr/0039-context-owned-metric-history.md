# ADR 0039: Context-owned metric history

Status: accepted for the unreleased development implementation.

## Context

Pulse's short CPU/memory overview does not cover a selected entity's longer
history. Historical sources differ in labels, retention and identity evidence.
Neither a Kubernetes target UID nor a compatible query endpoint proves that
historical series belong to that target. External backends also need a transport
boundary separate from Kubernetes credentials.

## Decision

Keep immutable shared records in [history](../../src/kuberich/domain/history.py).
The [query/parser module](../../src/kuberich/domain/history_queries.py) defines
fixed literal selectors and finite matrix extraction. The
[membership module](../../src/kuberich/domain/history_membership.py) reconciles
current API members separately from historical owner evidence. All three modules
require complete deterministic line and branch coverage.

Use one [workspace owner](../../src/kuberich/services/history_workspace.py) per
context connection. Every request also binds the current scope generation,
target, options, interval and configuration revision. Cancellation invalidates
publication before draining HTTP, token loading and parser workers. One active
intent and one latest pending intent avoid an unbounded queue.

Service transport reuses only the selected Kubernetes session's relative proxy.
It verifies the Service UID around a finite request. Kubernetes authenticates
the first hop; the API server strips bearer and impersonation headers before
forwarding. API-server proxy HTTPS does not provide independently verified
backend identity. The separate
[external HTTP adapter](../../src/kuberich/adapters/history_http.py) receives no
Kubernetes session or configuration. It creates its own TLS settings, disables
environment credentials/proxies, cookies and redirects, and reads optional
private HTTPS bearer-token material outside the UI loop. Rotation replaces
credential-bound client state; paths and values stay out of public snapshots.

Container, node-exporter and kube-state-metrics selectors are independent. A
declared cluster selector applies to all sources and joins. CPU calculates
counter rates before aggregation. Pod sandbox network stays shared rather than
being attributed to a container. Filesystem devices/mounts remain separate.
Historical owner names, observed current members and exact UID evidence retain
different labels. Creation/rate-window and ambiguous-identity boundaries produce
gaps. Missing, nonfinite, partial, denied, expired and measured-zero values are
never interchangeable.

Requests cover 15 minutes through 24 hours with at most 721 grid points per
series. The owner enforces two concurrent HTTP requests, twelve query attempts,
64 Kubernetes read attempts, one-MiB response bounds, a 30-second collection
deadline, 32 series and 16,384 samples per result. The eight-entry cache has
separate point/byte limits, at most 30 seconds of reuse and 60-second display
expiry. These are retained-data limits, not total-process RSS guarantees.

The [history screen](../../src/kuberich/ui/history.py) uses the existing frame,
literal input handling, numerical units, ASCII/Unicode sparklines and stable
viewport identity. Its expiry timer changes presentation only. Collection is
finite and explicit. A detail claim pauses Pulse history without stopping its
resource health collection. Export review retains that claim and uses the
originating screen, request, selected family/device/range and configuration
revision as its lease. Backend or target changes invalidate the lease; theme
changes do not.

[History actions](../../src/kuberich/ui/history_actions.py) compose captured
Node/workload/Pod/container and Pulse entries. Removed screens remain owned until
their cancellation drains, and client shutdown awaits every owner before closing
the Kubernetes client. Shift+M and `:history` use the source selection without
turning a history row into a mutation target.

## Consequences and limits

Backends and scrape sources must already exist. Detection is explicit,
namespace-scoped and bounded; candidates are not automatically saved. Compatible
API metadata is not an authenticated product identity. Stock providers may omit
network/filesystem sources. A synthetic exporter demonstrates parser/query
semantics separately from availability of native kubelet metrics.

The new history profile reserves its chart keys. A conflicting common table
override requires a per-profile override, documented as a 0.4 minor migration.
Whole-source/platform, actual provider, terminal and installed-artifact evidence
belong in the [acceptance record](../internal/acceptance/metric-history.md).
Implementation acceptance does not authorize a tag, package or website release.

## Upstream Service-proxy boundary

The pinned Kubernetes implementation separates successful authentication from
backend forwarding: [authentication header removal](https://github.com/kubernetes/kubernetes/blob/bb826b1d48562f110659e64e8ec444327433db95/staging/src/k8s.io/apiserver/pkg/endpoints/filters/authentication.go#L50-L124),
[impersonation removal](https://github.com/kubernetes/kubernetes/blob/bb826b1d48562f110659e64e8ec444327433db95/staging/src/k8s.io/apiserver/pkg/endpoints/filters/impersonation/impersonation.go#L159-L182)
and [the server-owned proxy TLS transport](https://github.com/kubernetes/kubernetes/blob/bb826b1d48562f110659e64e8ec444327433db95/pkg/controlplane/apiserver/config.go#L419-L428)
are distinct from KubeRich's first-hop configuration. The disposable-cluster
receiver verifies runtime behavior separately; a source review is not that test.
