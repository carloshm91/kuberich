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

Ctrl+Y copies up to 1 MiB of redacted, timestamped kept output. Ctrl+S saves to an
explicit new file. The parent directory must exist; an existing file or symlink
is refused. A saved file is readable only by your user. In aggregate logs, the
current source filter and plain/JSON mode apply to export too.

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
