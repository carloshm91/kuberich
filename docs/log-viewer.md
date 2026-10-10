# Container log viewer: S02

Select a connected pod and press Enter to open its [container table](container-navigation.md),
then Enter on a container to read its logs. Esc returns logs → containers → pods.

For the direct log shortcut, press `l` on a pod. A single regular container opens directly;
multiple regular/init containers open a selector first. `c` or **Container**
changes the selected container. Logs work in read-only mode and use the captured
context, namespace, pod UID and container, independently of resource watches.
They do not mutate kubeconfig or Kubernetes resources.

The title identifies the container/current-or-previous mode and target. `?` or
**Help** shows the complete context/namespace/pod, state and keyboard controls
when a narrow terminal truncates the header/status. Windows down to 40×12 retain
the target controls, log body, search and status.

## Controls

These keys act in the log body; letters in search/value inputs remain text.

| Key / control | Behavior |
| --- | --- |
| `c` / Container | Choose a regular or init container |
| `v` / Previous | Switch current/previous instance; previous is a finite snapshot |
| `o` / Window | Tail 1000, tail 100, all, head 1000, last 1/5/15/30/60 minutes, or an RFC3339 start time with Z/offset |
| `p` / Pause | Pause/resume delivery into retained history; backpressure the owned stream |
| `f` / Follow | Follow the newest retained output without changing reception pause |
| `g` / `G` (Shift+G) | Oldest/newest retained line; G explicitly resumes viewport follow |
| `j/k`, arrows | Move vertically; upward movement leaves viewport follow |
| Ctrl+F/B, PageDown/PageUp | Move one page |
| Ctrl+D/U | Move half a page |
| `h/l`, left/right | Horizontal movement when wrap is off |
| `w` / Wrap | Toggle wrapping; reflow at current terminal width |
| `t` / Time | Hide/show requested timestamps without reopening the stream |
| `L` | Keep horizontal offset during automatic follow |
| `/`, Enter, `n/N` | Literal case-sensitive search, then next/previous matching retained line |
| `C` | Clear retained history and marks; keep the selected stream |
| `m` | Mark/unmark the first visible retained line; marks expire with evicted lines |
| `z` | Toggle fullscreen |
| Ctrl+Y | Copy retained redacted timestamped output, at most 1 MiB |
| Ctrl+S | Save retained redacted timestamped output to an explicit new file |
| `?` / Help | Read all controls and the complete state |
| Esc / Back | Leave an input, then return to containers (Enter path) or pods (`l` path) |

Reading older output does not pause reception. Pausing reception does not freeze
navigation, search, wrapping or help. G/f do not unpause a paused stream. A paused
stream retains no growing application queue; delivery waits for resume. Socket
and transport buffers remain separately bounded by their libraries. A graceful
end is **Stream complete**, including an empty stream. An opened quiet follow
says **Waiting for log output**. Permission, deleted pod, previous-instance,
network and timeout errors have explicit safe messages; there is no automatic
replay. Reselect the container/window or close and reopen to request history again.

Changing container, instance or read window cancels and awaits the old read, clears
the old history, then opens the captured target with new options. Head 1000 reads
from the oldest available server output and closes after the first 1000 lines;
normal other windows retain the newest output. Kubernetes retention/rotation may
have removed older server output. Since-time is sent in UTC. Reopening can repeat
historical output; timestamps are not unique line identifiers.

## Retention, rendering and target ownership

The consumer retains at most **5,000 lines AND 4 MiB of UTF-8 text**, with a dropped
line counter. Either bound evicts oldest entries and their marks. g/G and search
operate on that retained history; they cannot recover evicted output. Clearing
history resets its eviction counter and keeps monotonically increasing internal
line identities, so marks cannot accidentally select a later reused row.

Rendering is coalesced at 50 ms intervals. The virtualized body caches only
retained primitive text, cell-width and highlight-range descriptions. Actual
styles, segments and viewport strips are constructed on demand. At most 128
rendered Strip entries are cached, independently of terminal height; expired
line identities and replaced projections are pruned; theme changes also invalidate
cached styles without reopening a reader. It does not rebuild one giant
text document on every received line. Layout work yields every 16 entries and
reception every 64 lines. Reflow/search uses an owned serialized layout operation.
The top visible line identity and horizontal offset survive arrivals and reflow;
if that line is evicted, the viewport clamps to the oldest retained output.
Layout/cache memory is bounded additional storage, separate from the 4 MiB text
bound. This is not an overall RSS or maximum-load performance claim; Q03 remains
the sustained responsiveness/memory qualification task.

Scope/client changes and disappearance/recreation of the selected pod invalidate
and clear the viewer, including while a child container/window/save prompt is
open. Display/copy/save require the captured target to remain current. Read,
render and export tasks have lifecycle owners; dismissal stops them before
widgets disappear, and unmount awaits their completion. The underlying pod table
continues its owned watch and preserves surviving selection/filter/sort/viewport
when returning.

The [transport contract](container-log-transport.md) defines UTF-8 framing,
long-line truncation, literal control/markup handling, recognized credential
redaction, safe errors and the API's non-atomic UID limitation. Unlabelled
sensitive prose is not universally recognizable. Copy/save use timestamped
retained sanitized lines, regardless of timestamp visibility/wrap/search/marks;
there is no raw-output reveal switch. Saving creates a complete mode-0600 file
without replacing a file or symlink. The parent directory must exist. File work
runs outside the event loop and is drained on cancellation; an explicitly
requested save can finish while closing the viewer.

Native clipboard and SSH/tmux integration
remain B07 #61 / Q02 #33; saved-export browsing and richer export formats remain
O06 #73. CLI buffer/refresh preference integration remains F05 #19. Main table
Vim letter bindings remain B07; this issue scopes them to the log body.

## All-container and workload logs: S06 #54

Select an ordinary Pod, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job or
CronJob row and press Shift+L (`:logsall`). Pod Enter still opens the container
list; Enter there opens only that selected container. Explicit generic-resource
routes retain read-only inspection and do not open aggregate logs.

Every aggregate line includes a stable source number, namespace, Pod, container
and actual Pod UID. Same-name Pod recreation gets a new source number and UID;
retained output remains distinguishable. Workload membership follows captured
controller UID/kind/API group/name in the same namespace. Deployments require
the Deployment→ReplicaSet→Pod chain; CronJobs require CronJob→Job→Pod. Matching
labels alone never establish ownership. Reading requires parent GET, namespace
Pod LIST/WATCH and Pod/pods-log GET; Deployment/CronJob also require intermediate
ReplicaSet/Job LIST/WATCH. A new container stays **starting** until its own
running/terminated status establishes log availability; Pod readiness and startup
probe success are not required. Waiting/CrashLoop containers can read a valid
last terminated instance; Previous requires that last instance's identity.
Missing previous history appears as **no prior** in the picker. Eligibility follows
the [pinned kubelet's log-state contract](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/kubelet/kubelet_pods.go#L1417-L1474).
A pre-open current-log 400 waits for changed container start evidence,
without polling. An opened, ended or failed stream never automatically replays.

The source picker (`c`) lists current, waiting, starting, failed, ended and recent
removed sources independently of the output filter. At most **eight readers**
run at once; this is KubeRich's limit. Automatic admission uses namespace/Pod/UID
and container order. Inspect a waiting row beyond that limit, then Enter to read
only it, or Space to toggle an explicit set of up to eight. Empty explicit
selection opens zero readers. `r` explicitly reopens that row and can repeat
history; `a` returns to automatic admission. Removed selections are pruned without
selecting a replacement UID. Cursor identity and scroll survive status/churn;
an expired selected row cannot open a different source.

The catalogue refuses more than **256 current sources** before opening excess
readers; choose a narrower Pod/workload view. It retains **64 recent removed
statuses** and at most one expired selected picker row. Ended/current sources
remain visible rather than being silently evicted and replayed. Historical source
identity remains only with bounded retained lines; removed status history beyond
64 is not a complete audit trail.

`s` filters retained output only and makes no reader requests. `J` changes between
plain prefixed lines and JSON Lines envelopes containing source identity, line
identity, timestamp and payload. Valid JSON values preserve their types and useful
fields after decoded credential-key/string redaction; ordinary `[INFO]`, `[1]`
followed by prose, literal markup and date prefixes remain plain text. Whole
`[1]` is a JSON array. Apparently structured malformed,
truncated or excessive JSON is visibly withheld. Structured parsing is limited
to depth 16, 512 values and 8,192 serialized characters; aggregate payloads have
a further **4,096 escaped-character** bound with a visible truncation marker.
There is no raw-secret reveal. Recognized patterns cannot identify every sensitive
phrase; inspect the sanitized export before sharing it.

Each source retains at most **500 lines and 256 KiB**; the aggregate retains at
most **5,000 lines and 4 MiB**. Accounting reserves the larger plain/JSON byte
representation, including identity prefixes and control expansion. Either bound
evicts oldest lines and marks. Lines appear in delivery order with monotonic local
IDs; clocks may differ, timestamps can regress and transport delays can reorder
events. No global timestamp sort or synchronized cluster clock is implied.

The existing pause/follow, search, marks, wrap, column lock, fullscreen, windows,
previous-instance and timestamp controls remain available. Timestamp visibility
and plain/JSON changes reuse history without reopening readers. Changing window
or previous/current explicitly closes the old aggregate and can replay requested
history; head 1000 applies independently to each admitted source. Copy/save use
the current source filter/mode, preserve timestamps and identity, and sanitize
output. Copy is limited to 1 MiB; save uses a new complete mode-0600 file.

Formatting/export runs in owned workers; counters do not serialize the full
history on the event loop. Leave, context change and shutdown drain membership
watches, readers, render and export work before captured client/TLS cleanup.
A closing viewer remains registered until that work completes; another aggregate
waits for it. An explicitly requested save may finish during close.
These are bounded retained-history controls; embedded-shell scrollback/search/copy
qualification remains open in #123, and sustained performance remains Q03.

## Trial

From updated main after this issue is merged:

```sh
uv sync --locked --group dev
uv run kuberich
```

Use `:ctx`, `:ns YOUR_NAMESPACE`, select a pod and press `l`. Choose its container,
try `g` then `G`, `/` plus some visible text, and `p`/`f`. Esc returns to pods.
Report whether output matches `kubectl logs` for the same explicit target/window,
and whether follow, search, resizing and return work in your terminal.
