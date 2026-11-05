# Inspect permissions

Use the authorization views to explore observed roles and bindings, read your
namespace rules, and ask the API server about a specific action. You use the
credentials and impersonation settings of your selected context.

Start with a context you are allowed to inspect:

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

All account, context and resource names on this page are fictional. Listing
roles, bindings and ServiceAccounts requires the corresponding read access.
Individual sources can be forbidden while a permission review still works.

## Browse subjects, bindings and roles

1. Type `:rbac` to list subjects observed in bindings and ServiceAccount reads.
2. Select a subject and press Enter to follow its binding and role evidence.
3. Follow a binding to its referenced role, then inspect rules and aggregation
   contributors. Each row keeps its namespace or cluster scope visible.
4. Use `:open` on a readable RBAC object to open its ordinary resource view.
   KubeRich checks the observed UID again before opening it.

You can start with a different list or a specific subject:

```text
:rbac bindings --namespace demo-apps
:rbac roles --all-namespaces
:rbac roles --cluster
:rbac subject user developer@example.test --namespace demo-apps
:rbac subject group observers --namespace demo-apps
:rbac subject serviceaccount demo-apps reader --namespace demo-apps
```

Kubernetes has no ordinary User or Group inventory API. These lists explain
observed declarations and explicitly selected subjects. A group row does not
enumerate its members. Your current effective identity and groups come from
the server when its identity review is available.

A RoleBinding grants within its own namespace, including when it references a
ClusterRole. ClusterRoleBindings have cluster scope. Aggregated roles show their
observed, materialized rules; selector-matched contributor roles are labelled as
inferred explanations. See Kubernetes' [RBAC documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).

## Check your current permission

Use `:can-i` for an exact question about your current effective identity:

```text
:can-i get pods demo-api --namespace demo-apps
:can-i get pods demo-api --subresource log --namespace demo-apps
:can-i list pods --all-namespaces
:can-i get deployments.apps demo-api --namespace demo-apps
:can-i get nodes --cluster
:can-i get --non-resource-url /healthz
```

Resource names and aliases resolve through the selected cluster's discovery.
KubeRich submits a fresh SelfSubjectAccessReview and displays its observation
time, decision and available explanation. Existing context impersonation is
checked by the server. The result describes the submitted question; a later
resource operation still applies its own checks and can encounter changed
permissions or resource state.

| Result | Meaning |
| --- | --- |
| Allowed | The server returned `allowed: true` |
| Denied | The server returned `denied: true` |
| No allow | The server returned neither an allow nor an explicit deny |
| Unknown | The review could not establish a valid decision |

A forbidden review API produces an unknown result with its forbidden status.
It cannot establish the outcome of the action you wanted to check. Evaluation
errors remain visible as warnings, including when the server also returns an
allow decision. Refresh sends another question rather than restoring an earlier
allow from navigation history. See [Kubernetes authorization](https://kubernetes.io/docs/reference/access-authn-authz/authorization/).

Name-limited `list` and `watch` permission requires the corresponding server
field selector on the actual request. Asking about an explicit name alone does
not authorize an unfiltered list. Local `/` filters affect displayed rows and
do not supply that server selector.

## Read namespace rules and who-can evidence

```text
:rules demo-apps
:who-can get pods demo-api --namespace demo-apps
:who-can get nodes --cluster
:who-can get --non-resource-url /healthz
```

`:rules` requests a SelfSubjectRulesReview for the named namespace. Read its
incomplete flag and warnings. Missing or incomplete rule enumeration cannot
establish that an action is denied; use an individual review for that question.
Kubernetes documents this distinction in the
[rules review API](https://kubernetes.io/docs/reference/kubernetes-api/definitions/self-subject-rules-review-v1-authorization/).

`:who-can` explains matching grants in the RBAC objects KubeRich could read.
It shows declared users, groups and ServiceAccounts with their bindings and
roles. Unknown group membership and additional authorization mechanisms limit
what this analysis can establish. A complete local match describes observed
RBAC evidence; it does not enumerate every possible decision by an external
authorizer. Missing roles, forbidden lists, truncated results and aggregation
limits remain visible even when there are no matching grants.

## Change scope and return

Without an explicit scope, namespaced questions use the namespace you selected.
`--namespace demo-apps` asks about that namespace while preserving the header's
current selection. `--all-namespaces` asks about a cross-namespace action;
namespace-specific grants are not combined into a cluster-wide grant.
Cluster resources and non-resource paths use cluster questions.

Choosing a namespace through `:ns` changes the header and rescopes a namespaced
question together. Cluster questions remain cluster questions. A selected
ServiceAccount retains its own namespace when you change where its permissions
are being examined. Namespace rule enumeration requires one namespace; choosing
all namespaces returns to the subject list with an explanatory notice.

Use `/` to filter the displayed evidence. Use the normal Back/Forward commands
or Alt+Left/Alt+Right to return through lists and details. History restores the
header, question scope, filter and viewport, then collects current evidence.
Changing context cancels previous work and clears previous decisions.
Use `h`/Alt+L to scroll horizontally when long identities or rule details extend
beyond the visible columns.

## Recover from partial or unavailable evidence

Read source status before interpreting an empty result. A forbidden list is
different from a successfully read empty collection. Review failures are
different from a server decision about the requested action.

Narrow the namespace when a scan reaches its limits. A collection uses at most
64 logical reads, 10,000 input objects, 16 MiB of retained facts, 100,000 matching
comparisons and 1,024 displayed results. Aggregation explanations stop at depth
eight, and collection has a 30-second deadline. Authentication retries and
discovery have their own transport limits. Partial results keep their warnings.

If a review or list is forbidden, use an account with the required permission or
ask your administrator about the specific API. If authentication has expired,
follow [context authentication](context-sessions.md#authenticate), then retry.
Authorization views are informational; normal resource changes still require
their usual identity, confirmation, read-only and server permission checks.

For ordinary navigation and resource actions, see
[navigate and search](command-navigation.md) and
[edit and change resources](editing.md).
