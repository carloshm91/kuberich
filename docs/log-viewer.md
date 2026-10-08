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
retained line layouts and renders viewport strips; it does not rebuild one giant
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

Aggregated/workload logs remain S06 #54. Native clipboard and SSH/tmux integration
remain B07 #61 / Q02 #33; saved-export browsing and richer export formats remain
O06 #73. CLI buffer/refresh preference integration remains F05 #19. Main table
Vim letter bindings remain B07; this issue scopes them to the log body.

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
