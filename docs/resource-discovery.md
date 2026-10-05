# Resource discovery and collection snapshots

C02 implements the backend reads for resource browsers. C03 adds a
[recoverable synchronization loop](resource-watches.md). Both use an existing
explicit context session; neither loads another kubeconfig, changes the current
context or creates a fallback client. The terminal still displays the C01 namespace
checkpoint. Live pod rows arrive after C03/C04/B02; selecting `:ns NAME` alone
does not populate the table in this checkpoint.

## Discovery

`ResourceReader.discover()` negotiates stable aggregated discovery v2 at `/api`
and `/apis`, with ordinary JSON as the fallback representation. Current aggregated
versions supply their resource descriptors directly. Legacy directories and stale
aggregated versions are read individually, with at most four concurrent version
requests. Preferred version order is preserved even when a stale version needs
refreshing. There is no disk cache or version guessing.

Each application-owned descriptor contains the API group/version, plural name,
kind, namespace scope, advertised verbs and singular/short aliases. Canonical
names take precedence over aliases; ambiguous aliases require a canonical name.
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
not retried except the transport's existing single exec-token refresh on 401.

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

## Bounds and ownership

These are application limits, not Kubernetes limits:

| Read | Limit |
| --- | --- |
| Discovery | 128 group/versions, 8192 top-level descriptors, 2 MiB per response |
| Collection | 10,000 records, 256 pages, 64 MiB retained manifest bytes |
| Collection response | 8 MiB per page |
| Requested page size | 100 by default; integer 1–500 |
| Continuation token / metadata text | 8192 characters; no terminal controls |

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
The domain resource module is in the critical 100% line/branch coverage inventory.

With Docker running and the workflow's verified kind v0.33.0 binary:

```sh
uv sync --locked --group dev
uv run python scripts/verify_contexts_kind.py --kind /path/to/verified-kind
```

This command creates its own uniquely named kind cluster and temporary kubeconfig,
tests real core/named-group discovery, aliases, paginated namespace/pod/deployment
reads, collection versions and UIDs, then deletes only that owned cluster.
Sanitized evidence is written to `artifacts/cluster/context-sessions.json`.
CI requires it on Linux/Python 3.12. C03 extends the script with real list/watch
changes and UID recreation. It does not qualify cloud providers, UI resource rows
or performance at the configured maximum dataset size.

Sources: [Kubernetes API discovery](https://kubernetes.io/docs/concepts/overview/kubernetes-api/),
[pagination and resource versions](https://kubernetes.io/docs/reference/using-api/api-concepts/).
