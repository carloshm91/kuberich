# Read container and workload logs

Read logs in read-only mode with permission to get pods and `pods/log`.
Select a pod, press Enter for containers, then Enter on a container for its logs.
Escape returns through logs → containers → pods. The `l` shortcut on a pod opens
a single regular container directly or offers a container choice.

## Choose the output

Use **Container** (`c`) to change container, **Previous** (`v`) for the previous
instance, and **Window** (`o`) for a tail, head, recent interval, or RFC3339 start
time. Previous output is a finite snapshot. Head stops after the first 1,000
available lines; other windows normally keep the newest output.

Changing container, instance, or window closes the previous read and clears its
history. Reopening can repeat server history. Kubernetes rotation may already
have removed older lines. A quiet open stream shows **Waiting for log output**;
a normal end shows **Stream complete**. Errors need a deliberate reopen rather
than an automatic replay.

Development source keeps an already-open individual container log read active
while the resource table recovers from an expired watch or unfinished list pages.
It preserves the captured Pod identity, output and position during that reload.
A confirmed deletion, replacement or context/namespace change still stops the
old view; select the Pod again to open another read. Reopening checks the Pod's
identity again. Other container actions retain their normal current-selection
checks. A delayed deletion event for a different Pod UID does not stop the
current read merely because its name matches. This continuity change is not
in the installed 0.3.0 release.

## Inspect container environment and image facts

In development source for the next release, select a pod, press Enter for its
containers, then `e` for **Environment / image**. The installed 0.3.0 release
predates this inspector. Enter on a container continues to open its logs.
Read-only mode supports inspection. The API needs GET access to the selected pod
and any referenced ConfigMaps or Secrets; denied sources remain visible.

Use `e` for Environment, `i` for Image and `s` for Sources. Arrows or `j`/`k`
move through rows; `g`/Shift+G and paging keep their normal meaning. Escape
returns to the container list with the preceding selection and scroll position.
Navigation keys use the `container-inspection` profile in [configuration](configuration.md).

Environment rows show declarations, order, source, precedence and resolution.
Values start hidden, including literal values, ConfigMap data and values derived
from another variable. Sources identify exact objects, keys, optional references
and availability. An unavailable or unsupported source stays distinct from a
known empty value. Overridden declarations retain their provenance.

- `r` or Reveal performs a fresh read and reveals the selected value; `r` hides it.
- Ctrl+Y or Copy performs its own fresh read before copying a complete text value.
- Shift+R or Reload collects new metadata and clears any revealed value.

Changing rows or sections, opening another view, reloading or leaving hides
the previous value. A changed source requires Reload before another disclosure;
a replaced pod requires selecting the pod again. Revealing a value does not
authorize a later copy without another freshness check. Clipboard contents remain
outside the application's control after copying. Previews stop at 16,384
characters; copy accepts at most 64 KiB of complete text and rejects NUL.

The result describes **current API configuration**. A running process may still
use older configuration. Image-provided variables, injected Service variables,
runtime IP fields and node-dependent defaults may be unresolved. Binary data,
unsupported field selectors and runtime-file sources do not become invented
empty strings. Dependency expansion uses the declarations available at each
assignment and preserves unresolved references explicitly.

Image shows the declared image and pull policy separately from the name-matched
status image, image ID and container ID. These identifiers retain their API
origin. Regular, init, restartable-init sidecar and ephemeral containers can be
inspected, including when runtime status is absent.

A collection accepts up to 32 referenced objects and 4,096 provenance rows,
with a 2 MiB response bound and 4 MiB combined input bound. Incomplete or oversized
input is labelled. Collection and disclosure have a 30-second deadline; leaving
waits for owned work to drain. The inspector adds no background polling.

`:export` captures only the selected section's metadata, including when a value
was revealed. It omits environment values and private content bindings. Application
screenshots are refused while the inspector remains open. See [local exports](exports.md).

## Follow, pause, and search

- `f` toggles following the newest line. Moving upward leaves follow mode;
  Shift+G resumes it.
- `p` pauses incoming delivery. Following and pausing are independent: `f` or
  Shift+G does not resume a paused stream.
- `g`/Shift+G move to the oldest/newest kept line. Arrows or `j`/`k` scroll;
  Ctrl+B/Ctrl+F move pages and Ctrl+U/Ctrl+D half pages.
- `/`, Enter, then `n`/Shift+N search literally and case-sensitively.
- `w` wraps lines, `t` toggles timestamps, and `h`/`l` scroll horizontally when
  wrap is off. `L` keeps the horizontal offset during automatic follow.
- `m` marks the first visible line; `C` clears history and marks without changing
  the stream. `z` toggles the log view's fullscreen mode.

Press `?` for the complete target, state, and controls when the header is clipped.
Search and movement apply only to kept output. The viewer keeps at most 10,000
lines and 4 MiB of UTF-8 text; either limit discards oldest lines and their marks.
The status reports discarded lines. Arrivals and wrapping preserve your position
unless its line has been discarded.

## Read several sources

Select a Pod, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, or CronJob in
its ordinary resource view and use Shift+L or `:logsall`. Each line identifies
its source, namespace, pod, container, and pod UID. Recreated pods receive new
identities. Workloads are matched through controller references, including
Deployment → ReplicaSet → Pod and CronJob → Job → Pod.

Use `c` for sources:

- At most eight readers run at once. Automatic selection uses a stable source
  order. A waiting container starts only when its own state permits log reads.
- Enter on a waiting row selects only that source. Space toggles an explicit set
  of up to eight; selecting none opens no readers. `a` restores automatic choice.
- `r` explicitly reopens a source and can repeat history. Ended or failed streams
  do not silently reopen. Previous needs an actual last terminated instance.
- `s` filters kept output without changing readers. `J` switches plain prefixed
  text and JSON Lines with source identity.

The source list accepts at most 256 current sources and 64 recent removed
statuses. Each source keeps up to 500 lines and 256 KiB, within the shared
10,000-line/4 MiB limit. Output follows arrival order; timestamps do not establish
a synchronized order across containers.

Aggregate membership needs parent GET and pod LIST/WATCH/GET plus pods/log access.
Deployment and CronJob membership also needs the intermediate ReplicaSet or Job
LIST/WATCH. Explicit generic-resource routes provide inspection rather than
aggregate logs. Narrow the workload if its source count exceeds the limit.

## Copy or save output

Ctrl+Y copies up to 1 MiB of redacted, timestamped kept output. In development
source, Ctrl+S or `:export` opens a review with a frozen retained-log capture,
redacted preview, directory and filename. Existing files need a separate
overwrite confirmation; symlinks are refused. Saved files are private to your
user. In aggregate logs, the source filter and plain/JSON mode apply to export
too. Use `:exports` to browse saved artifacts; see [local exports](exports.md).
The installed 0.3.0 release still uses its new-file-only Save dialog.

Copy and save escape terminal controls and redact recognized credential patterns.
Structured JSON is parsed within depth and size limits; malformed or excessive
structured payload is visibly withheld. Redaction cannot recognize every private
phrase. Inspect an export before sharing it. There is no raw-output reveal switch.
Clipboard receipt depends on [your terminal setup](troubleshooting.md#clipboard).

## Return or recover

Escape leaves an input first, then returns to the preceding view. Closing the
viewer stops its reads and watches; a requested file save may finish during close.
Context replacement or pod deletion/recreation invalidates the old target.

A permission failure, unavailable previous instance, timeout, or deleted pod has a
specific message. Check the selected context, container, and window before
reopening. Changing windows can repeat history; it cannot recover rotated output.
For interactive commands, use [shells and attach](container-shell.md).
