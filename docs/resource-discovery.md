# Resource discovery and collection snapshots

C02 implements backend reads; C03/C04 own the
[recoverable synchronization loop](resource-watches.md) and active workspace.
C05 #52 extends those contracts to arbitrary discovered resource types and CRDs.
They use an existing explicit context session without loading another kubeconfig
or changing its current context. Standard terminal views are already live;
generic custom-resource commands and their visible columns remain B06 #53.

## Discovery

`ResourceReader.discover()` negotiates stable aggregated discovery v2 at `/api`
and `/apis`, with ordinary JSON as the fallback representation. Current aggregated
versions supply their resource descriptors directly. Legacy directories and stale
aggregated versions are read individually, with at most four concurrent version
requests. Preferred version order is preserved even when a stale version needs
refreshing. There is no disk cache or version guessing.

Each application-owned descriptor contains the API group/version, plural name,
kind, namespace scope, advertised verbs and singular/short aliases. Canonical
names take precedence over aliases. `Discovery.resolve(name, group=None,
version=None)` resolves across API groups, collapses served versions of one
group/resource family and selects the server's preferred version. An ambiguous
short name requires a group and canonical name; no group/version is guessed.
An explicit version must be advertised. `preferred_resources` exposes one
preferred descriptor per group/resource; the existing `find` retains its core
group default for standard views.
Subresources such as `pods/log` are excluded from collection discovery. Verbs
describe API support, not the caller's RBAC authorization.

Forbidden/unavailable groups and malformed discovery responses create explicit
`DiscoveryIssue` entries alongside the descriptors that were actually discovered.
They never establish that a missing resource is absent from the cluster. A 401,
closed session, TLS/network failure or timeout fails discovery; callers must
surface that failure rather than render an empty successful browser.

## Consistent lists

`ResourceReader.list(resource, namespace, page_size=100)` constructs the endpoint
from validated discovery metadata. A namespace on a cluster-scoped resource is
rejected before a request. Omitting a namespace on a namespaced resource requests
all namespaces. An unadvertised list verb fails before I/O; the actual request
still determines authorization.

The reader follows opaque continuation tokens, keeps the same collection
`resourceVersion` on every page, and returns a snapshot only after all pages
succeed. It rejects duplicate identities, changed collection versions, repeated
tokens and scope/type mismatches. A first HTTP 410 discards every collected page
and starts again from the beginning. A second 410 is surfaced, with no further
retry or use of a replacement token from an error body. Other HTTP errors are
not retried except the transport's existing single exec-token refresh on 401
and the explicit unsupported-Table representation fallback below.

`ResourceReader.get(resource, name, namespace)` uses the discovered endpoint,
requires the advertised get verb and validates the returned name, type, scope
and memory bounds. Names are literal validated path segments, never shell text.

Snapshots expose the collection version separately from item versions. Versions
are never compared numerically. Records contain typed metadata (name, namespace,
UID, item version and an aware creation timestamp) and an independent raw
manifest copy with Kubernetes field names. Missing item type metadata is filled
from the discovered endpoint; conflicting explicit type metadata is rejected.
Raw manifests are excluded from object representations and are not logged or
displayed by this service. Future views/exports must use their presentation and
secret-redaction boundaries.

Watchable resources require both collection/item versions and item UIDs.
Non-watch aggregate APIs may legitimately omit those fields: missing values
remain `None`, never invented identifiers or watch versions. Future watch and
mutation services must require the concrete identity/version they need.

## Optional server columns

`ResourceReader(session, tables=True)` negotiates stable `meta.k8s.io/v1` Table
with ordinary JSON as an alternative and requests `includeObject=Object`.
Full manifests remain independent from immutable typed headers/cells; YAML and
mutation consumers do not receive the Table envelope as the resource object.
The service does not evaluate printer JSONPath, execute a formatter or display
untrusted cells. The future generic terminal view must escape/redact them.

HTTP 406/415, unsupported/invalid Table metadata or missing full objects disable
Table negotiation for that exact group/version/resource on that reader. Plain
JSON is accepted directly on the first page. A format change or invalid Table
on a later page discards all earlier pages and restarts the whole collection in
JSON once. HTTP 401/403/404 and server failures remain errors, not formatter
fallback. Wrong identity/scope, inconsistent versions or exceeded snapshot
bounds also remain errors. Fallback does not disable columns for other APIs.

Table watches own a fresh header decoder for every opened stream. The first
Table event supplies headers; later events may omit them. Full ordinary resource
events and Status errors retain the original watch protocol. Unsupported Table
streams close, relist in JSON and reopen from the replacement checkpoint.
Reconnects and cancellation still belong to the existing list/watch owner.

`WorkspaceService.refresh_discovery()` cancels/drains its previous readers and
watch, refreshes the catalogue on the same SDK client and rebinds the current
selection. It preserves pending namespace intent. Unpinned versions follow a
new advertised preference; explicit versions never silently change. Removed or
inaccessible selections fail visibly while the refreshed catalogue still permits
core selection. The `discovery` property hides data during client/context
replacement; `select_discovered` requires that current catalogue. These are
backend contracts; B06 owns terminal navigation and refresh controls.

## Bounds and ownership

These are application limits, not Kubernetes limits:

| Read | Limit |
| --- | --- |
| Discovery | 128 group/versions, 8192 top-level descriptors, 2 MiB per response |
| Collection | 10,000 records, 256 pages, 64 MiB retained manifest and Table bytes |
| Collection response | 8 MiB per page |
| Requested page size | 100 by default; integer 1–500 |
| Continuation token / metadata text | 8192 characters; no terminal controls |
| Server Table | 64 columns, 256 KiB UTF-8 header metadata, 65,536 characters/cell |

Cell types are null, strings/date strings, strict booleans, signed 64-bit
integers and finite numbers. Cells are not coerced. Header memory is counted
conservatively per retained row along with cells/manifests. A missing Table is
not a missing collection; no header schema or resource identity is invented.

Exceeded limits produce errors rather than silent successful truncation.
Discovery and a complete list each have the selected session's total request
deadline. Requests use the same authenticated SDK-owned TLS connector as namespace
discovery, with explicit proxy configuration and no redirects or decompression.
JSON decoding runs in an owned thread task; cancellation waits for decoding to
finish. Task groups cancel and await outstanding discovery reads. Services never
own or close a caller's session; its existing lifecycle owner cancels reads before
closing/replacing it. C04 integrates these snapshots with the generation-bound
resource store and UI workers.

## Verification

Domain tests qualify endpoint/alias/scope decisions and immutable manifests.
Real loopback HTTP contract tests cover both discovery protocols, partial groups,
pagination, 410, permissions, limits, invalid responses, deadlines and cancellation.
The domain resource and Table modules are in the critical 100% line/branch
coverage inventory. See [C05 acceptance evidence](acceptance/custom-resources.md).

With Docker running and the workflow's verified kind v0.33.0 binary:

```sh
uv sync --locked --group dev
uv run python -m scripts.verify_contexts_kind --kind /path/to/verified-kind
uv run python -m scripts.verify_custom_resources_kind --kind /path/to/verified-kind
```

This command creates its own uniquely named kind cluster and temporary kubeconfig,
tests real core/named-group discovery, aliases, paginated namespace/pod/deployment
reads, collection versions and UIDs, then deletes only that owned cluster.
Sanitized evidence is written to `artifacts/cluster/context-sessions.json` and
`artifacts/cluster/custom-resources.json`. CI requires both on Linux/Python 3.12.
C05 verifies real namespaced/cluster CRDs, paged Table LIST/GET/WATCH, version
changes, alias collisions and install/remove refresh. An owned loopback gateway
forces ordinary JSON and legacy discovery representations over that real cluster;
restricted responses come from actual RBAC, not injected status codes. The receipt
labels both representation injections. C03 extends its script with real list/watch
changes and UID recreation. It does not qualify cloud providers, UI resource rows
or performance at the configured maximum dataset size.

Sources: [Kubernetes API discovery](https://kubernetes.io/docs/concepts/overview/kubernetes-api/),
[pagination and resource versions](https://kubernetes.io/docs/reference/using-api/api-concepts/).
