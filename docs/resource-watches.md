# Resource synchronization

C03 adds backend list/watch synchronization on top of C02's complete snapshots.
It does not yet populate the terminal table: C04 now implements
[context/scope generations and UI subscriptions](resource-views.md); B02 renders
the first live pod table. CLI refresh options
and advanced connection behavior remain with their existing tasks.

## Data and continuity

`ListWatch.run(resource, namespace, sink)` uses one existing explicit session.
It requires advertised list/watch support, reads a complete collection and opens
WATCH from that collection's opaque `resourceVersion`. A change between LIST and
opening WATCH is received through the API's history. Version `0` is rejected as
a collection checkpoint because it selects different watch semantics.

Application-owned `WatchEvent` values normalize ADDED/MODIFIED/DELETED records and
BOOKMARK checkpoints. ERROR objects retain only a validated status and optional
bounded retry delay. Raw server messages/bodies are not exposed. A bookmark needs
only a version, not a UID/name; requesting bookmarks does not assume their arrival.

`WatchState` keys rows by UID and keeps namespace/name as a separate index. Updates
replace that UID's record; recreation with a new UID replaces the old name entry.
A late deletion of the old UID cannot remove the recreated resource. A UID
cannot move between resource identities. Repeated current item versions and the
last 1024 event identities are idempotent, without rewinding a later checkpoint.
Recent versions also suppress replayed bookmarks. There is no numerical version
comparison or unlimited event/tombstone history. The API must preserve its ordered
watch/resume contract; arbitrary out-of-order versions cannot be sorted as numbers.

Snapshots are independent immutable record tuples. Previously delivered snapshots
stay unchanged. Row sorting, cursor/scroll preservation and rendering are separate
consumer responsibilities. Records retain the existing raw-manifest presentation
and secret-redaction boundaries.

## Recovery and status

| Condition | Behavior |
| --- | --- |
| EOF, timeout, incomplete trailing frame, transport failure | Retain the last state and retry from the last fully applied checkpoint |
| HTTP/in-stream 408, 429, 500, 502, 503, 504 | Retry with bounded delay |
| HTTP/in-stream 410 | Invalidate the old cache, back off, then perform a complete new LIST before WATCH |
| HTTP 401 with exec-token credentials | The shared transport refreshes once; a further rejection stops |
| Other auth/permission errors, missing API, TLS failure, malformed data, limits | Surface the failure and stop automatic retry |

Retries start at 0.25 seconds with ±20% jitter and double up to 30 seconds.
Successful event processing resets the delay. A healthy response lasting at least
`min(1 second, request_timeout / 2)` also resets it, so idle resources do not cause
ever-longer recovery delays. Repeated immediate EOF/410 responses back off.
Decimal Retry-After seconds and Status.details.retryAfterSeconds can raise the
delay up to 300 seconds. Unsupported HTTP-date/invalid header values use ordinary
backoff. There is no automatic retry of mutations: the product loop sends GETs.

The sink receives LOADING, SNAPSHOT, LIVE, RETRYING, RELISTING or FAILED updates.
SNAPSHOT means LIST succeeded; LIVE means the watch opened. RETRYING carries the
last known data and a delay, not a claim of current freshness. RELISTING carries
no usable snapshot. FAILED retains only any still-usable prior snapshot and raises
the safe connection problem. Consumer exceptions propagate rather than being
misclassified as network failures. C04 renders these observations and rejects
late results from previous context/scope generations.

## Bounds and cleanup

The loop pulls one JSON event at a time and awaits the sink. It creates no
background producer or application event queue. A slow consumer applies
backpressure; callers must also bound their own queues and retained snapshots.
At most 10,000 current records and 64 MiB of retained manifest bytes are allowed,
with separate bounded UID/name indexes and 1024 recent event/version entries.
This is not a measured total-RSS guarantee; full workload performance remains Q01.

Watch requests use the existing authenticated/TLS/proxy client, with redirects
and automatic decompression disabled. Each event is limited to 8 MiB; complete
newline-delimited JSON is required. Partial trailing frames are discarded and
retried from the last applied version. HTTP request lifetime is bounded by
`min(request_timeout, 60 seconds)`; the server also receives timeoutSeconds.
JSON decoding and event normalization use owned thread tasks and await them even
on cancellation. Closing/cancelling the loop or a consumer failure closes the
response. Backoff waits and slow consumers remain cancellable. No other context
or client is silently selected, and this service does not close the caller's session.

## Verification

From the checkout:

```sh
uv sync --locked --group dev
uv run pytest tests/unit/test_watches.py tests/contract/test_watches.py
```

The fixtures own numeric-loopback servers and synthetic credentials. Pure tests
qualify normalization, UID/recreation/replay rules, memory bounds and retry
decisions; the domain watch module has a critical 100% line/branch coverage gate.
Actual HTTP tests cover chunks, EOF, 410, denied reads, malformed data, token
refresh, backoff, slow consumers and cancellation, including worker cleanup.

The existing [disposable-kind verification](resource-discovery.md#verification)
also creates an owned namespace/ConfigMap, receives a write made between LIST and
WATCH, modifies/deletes/recreates that name, verifies the changed UID, cancels and
awaits the watch, then removes its fixture and cluster. These writes are test
setup inside the script's newly created local cluster, not application mutation
features. CI requires this on Linux/Python 3.12 and retains sanitized evidence.

Source: [Kubernetes list/watch, bookmarks and expired versions](https://kubernetes.io/docs/reference/using-api/api-concepts/#efficient-detection-of-changes).
