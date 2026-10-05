# Container log transport: S01

The backend can read current or previous output from a captured regular/init
container, independently of resource watches. The terminal log viewer and its
container picker, pause/follow/search controls remain S02. There is no new log
shortcut or launch flag in S01; the live table and inspection controls still work.

`services.logs.LogStream` owns a run with an explicit KubernetesSession,
ResourceTarget, AccessPolicy and current-generation predicate. The target includes
context, namespace, pod name, UID and container. Logs are API reads and work in
read-only mode. The pod's name/UID/container are verified before requesting
`pods/log` and again after response headers, before emitting any output. This
rejects a replacement between the first GET and the log request. The service
never reconnects to a same-name replacement; context changes reject later data.
The API has no UID precondition for logs, so this is guarded read behavior rather
than an atomic server-side UID transaction.

## Query and stream behavior

LogOptions supports follow, previous, timestamps, tailLines, sinceSeconds or an
aware sinceTime. Defaults: follow and timestamps enabled, current logs, tail 1000.
Tail accepts -1 for all or 0–1,000,000; sinceSeconds is 1–2,147,483,647. Time-window
options are mutually exclusive and sinceTime is sent in UTC. Regular and init
containers are supported; ephemeral/debug container browsing remains later work.

HTTP connection/header establishment uses the selected request timeout. Quiet
follow streams have no artificial body deadline; cancelling the owned run closes
the response. Non-follow snapshots retain the request timeout. Graceful EOF is a
normal completion, including a final line without a newline. An abrupt/incomplete
HTTP response reports disconnection; a 403 identifies required pod/pods-log read
access, a 404 identifies unavailable/deleted targets, and previous-instance 400
errors explain that previous output may not exist. Server error bodies, endpoint
credentials and raw TLS errors never enter these messages.

There is no automatic log replay/retry. Reopening explicitly can repeat history
from tail/since options, and timestamps do not uniquely identify each line.
The transport's existing single credential refresh on a rejected HTTP opening
remains a pre-output authentication behavior, not a stream replay.

## Memory, framing and redaction

The adapter reads chunks up to 8 KiB. The incremental decoder handles split UTF-8,
CRLF, blank lines and partial final lines; invalid UTF-8 becomes visible U+FFFD.
An unfinished line retains at most 8,192 characters; longer suffixes are discarded
until newline and the resulting line carries a truncation marker. The decoder
rejects inputs larger than 64 KiB and cannot be reused after finalization.

Delivery awaits each consumer callback. There is no hidden application queue;
slow consumers backpressure the transport rather than growing retained history.
The supplied consumer-owned LogBuffer defaults to at most 5,000 lines AND 4 MiB
of UTF-8 text. Either bound evicts oldest lines, with a dropped-line counter;
individual oversized lines can also be evicted. Transport-library/socket buffers
remain separate from this application history.

Controls are escaped and markup stays literal. Known credential patterns are
redacted before retained output; standard private-key blocks remain hidden across
chunks/lines, including markers in discarded long-line suffixes. Marker scanning
also respects an old end followed by a new begin on the same line. As with the
inspection policy, arbitrary unlabelled sensitive prose is not universally
recognizable. There is no raw-output reveal mode in this backend.

Run the focused contract and deterministic tests with:

```sh
uv run pytest tests/unit/test_logs.py tests/contract/test_logs.py
```

The integration script also exercises snapshots, timestamp/tail options,
cancellable follow and unavailable previous logs on an owned disposable kind
cluster. See [S01 acceptance evidence](acceptance/S01.md).

API semantics follow the [Kubernetes logs reference](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_logs/)
and [aiohttp streaming response contract](https://docs.aiohttp.org/en/stable/client_quickstart.html#streaming-response-content).
