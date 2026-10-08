# Active resource views

C04 connects the context, discovery and list/watch services to the terminal.
It synchronizes **pods** in the selected namespace and displays loading, live,
stale or failed status and the collection count. B02 #26 now renders the
[live pod table](pod-table.md), including health, sorting and stable selection.
Commands and Tab completion are implemented in B03 #27. B05 #41 adds the
[standard resource tables](standard-resources.md) to this same ownership model.

## Ownership and scope

`WorkspaceService` owns one `SessionService`, one `ViewStore`, one active watch
and a replaceable desired selection. Context selection/retry reopens an explicit
client. Namespace changes keep that client and advance its session generation.
Resource changes advance the view revision and use a discovered descriptor;
cluster resources use no namespace while preserving the session's namespace choice.

Each change invalidates the prior snapshot synchronously, before awaiting cleanup.
The current watch is cancelled once and awaited before replacing the session or
starting another watch. Repeated cancellation does not interrupt owned workers
while they finish cleanup. Rapid requests replace one desired selection rather
than building task chains or opening obsolete intermediate clients/watches.
A resource selection following a pending namespace change carries that intent forward.

Results are checked against the captured client, session identity, view revision
and resource/namespace scope. Late pages/events/errors cannot update another
selection, even when the context name is reused. Discovery is cached for the
active client and released on reconnect/exit. No SDK global defaults or kubeconfig
are changed. `domain/views.py` contains pure immutable scope/observation and store
decisions, independently gated at 100% lines/branches. Published failures copy
safe fields without retaining transport traceback frames and old clients.

## Delivery and bounds

Each `ViewSubscription` holds one replaceable pending observation. Its next read
consumes the latest state; intermediate snapshots are coalesced. Unsubscribing
releases the pending snapshot and owner callback and wakes waiting readers.
At most eight subscriptions are allowed per workspace. Callers retaining their
own history must bound it separately.

The owner runs at most one transition driver, one transition operation and one
watch loop. There is no inactive-resource cache or watch producer queue. Closing
invalidates the generation, cancels/awaits work, closes the client/private TLS
material and ends subscriptions. A cancelled close caller still waits for owned
cleanup. Programming errors reach the sanitized application fatal-error boundary;
close failures propagate.

Collection/frame/replay bounds and retry policy remain those of
[resource synchronization](resource-watches.md#bounds-and-cleanup). Structural
bounds do not establish maximum-load/RSS performance; Q01 owns that qualification.

## Terminal states

| State | Data and action |
| --- | --- |
| Disconnected | No active configuration/data; select a configured context |
| Connecting/loading | Previous snapshot is cleared; no zero count is invented before LIST; inputs and quit remain responsive |
| Live | LIST succeeded and WATCH opened; pod rows (or a distinct empty state) and the collection count; normal watch renewals keep this state |
| Stale/reconnecting | Keep the last snapshot with an explicit freshness warning |
| Relisting | Expiration discards the snapshot before loading its replacement |
| Failed | Show the owned error; retained data, if any, remains stale |

Connection and resource states describe separate results. Namespace discovery
can succeed while pod reads are denied. A denied namespace listing can retain
a limited session and permit `:ns ALLOWED_NAMESPACE`; the subsequent pod read
must independently succeed. Denied reads never become a successful empty list or
hot retries. `i` / `:status` opens the full synchronization message, and `r` /
`:retry` reopens the currently requested context. Read-only and insecure-transport
indicators remain visible in the status.

The center distinguishes loading and unavailable data from an empty collection.
A real successful empty pod snapshot shows `Live · 0 pods`.
`:ctx` chooses a context and `:ns` chooses a namespace. Those are keyboard hints;
automatic watch renewal never chooses a different context. Context/namespace
footer labels are written out rather than abbreviated.

## Trial and verification

From an interactive terminal in the development checkout:

```sh
uv sync --locked --group dev
uv run kuberich
```

Use `:ctx` to choose a configured context, then `:ns NAME`. Look for `Live` and
the pod count and rows. Use `:status` for a complete message,
and Ctrl+Q to return to the shell. Launch uses your trusted kubeconfig/helpers;
see [context sessions](context-sessions.md).

For an isolated trial with synthetic clients and no real cluster:

```sh
uv run pytest tests/unit/test_views.py tests/contract/test_workspace.py tests/ui/test_workspace.py
uv run pytest tests/terminal/test_contexts.py
```

Tests cover rapid switches, late callbacks/pages/discovery/errors, client reopening,
cancelled preparation/reconnect, slow consumers, subscription limits, denied reads,
410 replacement, repeated open/close and leak checks. Pilot covers status/details
and scope changes at 40×12 and 100×30. Real CLI PTYs cover stale-to-live recovery,
resize, namespace changes, helper cancellation and terminal restoration.

The disposable-kind script verifies actual pod/namespace watches, scope/resource
switches, coalesced selections, client reopening, generation invalidation,
latest-state delivery and exit cleanup. It creates/deletes only its uniquely owned
local cluster and retains sanitized JSON. No ambient cluster is selected.
See [the real-cluster command](resource-discovery.md#verification).

Sources: [Textual concurrency](https://textual.textualize.io/guide/workers/),
[asyncio cancellation and shielding](https://docs.python.org/3/library/asyncio-task.html#asyncio.shield).
