# 0035: Keep authorization evidence separate from operation permission

Status: implemented in development source; scoped acceptance is recorded separately

## Context

RBAC object reads explain declarations, but effective authorization can include
other authorizers and group membership unavailable to the client. List access,
identity review, rule enumeration and action review can fail independently.
An old allow decision must not become a capability used by a later mutation.

## Decision

Keep immutable authorization questions, reviews and RBAC facts in domain records.
Pure matching implements literal Kubernetes RBAC semantics, namespace binding
scope, resource names, subresources, non-resource URLs and materialized aggregate
rules. Bounded inferred contributors explain aggregation without substituting
for its observed rules. Analysis retains partial results and warnings.

Use one explicit per-context Kubernetes session. Its separate `review_json`
port permits only the three fixed v1 self-review POST endpoints: identity,
action access and namespace rules. Request kinds and API versions must match
their endpoints. Reuse the existing credentials, TLS, proxy, impersonation,
owned decoding and failure sanitization. Keep generic mutation transport and
operation guards unchanged.

Canonicalize a resource question before assigning its request identity. For
list/watch, derive an effective name only from unambiguous actual
`metadata.name` field equality; reject contradictory explicit names/equalities.
Preserve literal selectors. Matching and serialization consume the same
canonical question. A named hypothetical question does not prove permission
for an unfiltered HTTP request. Relationship collection's broad-scan fallback
has no role in an authorization review.

The shared local selector helper accepts presentation whitespace, whereas the
pinned Kubernetes [field parser](https://github.com/kubernetes/apimachinery/blob/v0.36.4/pkg/fields/selector.go#L390-L425)
preserves literal field/value whitespace. Authorization rejects that unsupported
normalization before POST; it never derives a different name and leaves the
original selector unchanged. Valid label-selector whitespace remains supported.

Review HTTP 403 produces unknown/forbidden evidence. Valid server status keeps
allow, explicit deny and no-allow decisions distinct; malformed or contradictory
status stays unknown. Identity is supplemental, and its failure cannot prevent
an independent action review. Incomplete rule enumeration never proves denial.

`WorkspaceService` delegates authorization ownership to a scoped collaborator.
One collection is invalidated before cancellation and drained before client
disposal. Publications check client/session/request and outer view revision.
Owned workers parse and match away from the UI loop. Each new request clears
previous reviews; history recollects instead of caching permission decisions.

The header namespace and the question scope are independent. Atomic selection
can change the header and rescope a namespaced question once. Cluster and
non-resource questions keep cluster intent/access scope even when the header
changes. Preserve ServiceAccount subject identity across scope changes. History
restores its captured header and independent question with `preserve_intent`.
Pending commands and picker parents are invalidated by context/session changes,
newer intent and unrelated navigation; late discovery cannot resurrect them.

Use a typed native route, table/controller and scoped navigation collaborator.
Subject/binding/role drilldowns, filters and viewport share the existing frame.
Observed object Open revalidates UID; aggregate rows never become mutation
targets. Command parsing is pure and discovery resolves actual resource aliases
and versions before service submission.

## Consequences

Who-can describes visible RBAC declarations and their scope/completeness, not
every possible external authorizer or another user's unknown group membership.
Role references legitimately resolve by name, while ordinary object inspection
still requires its observed UID. Materialized aggregate rules and inferred
contributors remain separate evidence.

Collection shares 64 logical reads, 10,000 objects and 16 MiB of facts, with a
30-second deadline. Analysis permits 100,000 comparisons, 1,024 retained
grants/contributors and depth eight. Limits retain deterministic prefixes with
incomplete status. Discovery/authentication and existing one-time 401 refresh
have separate bounds; these are not universal process-memory or HTTP limits.

Review results are information. Existing operation services continue checking
read-only policy, captured identity, confirmation and actual server outcome.
No informational allow can enable a guarded operation.

## Source and verification

- [Domain records](../../src/kuberich/domain/authorization.py), [RBAC matching](../../src/kuberich/domain/rbac.py) and [native rows](../../src/kuberich/domain/authorization_rows.py)
- [Collection and reviews](../../src/kuberich/services/authorization.py), [workspace collaborator](../../src/kuberich/services/authorization_workspace.py) and [command resolution](../../src/kuberich/services/authorization_commands.py)
- [Review transport](../../src/kuberich/adapters/kubernetes.py), [view store](../../src/kuberich/domain/views.py) and [native navigation](../../src/kuberich/ui/authorization_navigation.py)
- [Acceptance record](../internal/acceptance/authorization.md), [active generations](0007-active-view-generations.md) and [guarded writes](0013-reviewed-conditional-writes.md)
- Kubernetes [authorization](https://kubernetes.io/docs/reference/access-authn-authz/authorization/), [RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/) and [identity review](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#api-access-to-authentication-information-for-a-client)
