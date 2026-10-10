# Combined-load progress: Refs Q03 #50

The independently paced loopback source uses 10,000 synthetic Pods, 100 resource
updates/second and 2,000 log lines/second. It runs in a separate owned process;
its deadlines do not depend on terminal rendering. Event replay, log chunks,
LIST snapshots, timing samples and concurrent streams all have explicit bounds.
Expired watch versions emit 410; the source honors watch timeouts. It never
loads a maintainer kubeconfig. Ten actual protocol/process cases passed, including
independent pacing, consistent pagination, expiry and signal-driven cleanup.

Production log history now retains at most 10,000 lines and the unchanged 4 MiB
byte limit. Covered root tables defer projection/age updates until return while
transport, target validation and latest domain state stay live. Log layout keeps
at most two display variants per retained line, prunes both on eviction and
clears both on invalidation. Cold Rich formatting retains sixteen-row cooperative
turns; cheap reused layouts use at most 128 rows per turn. Display controls wake
the log renderer immediately; ordinary incoming data remains batched at 50 ms.
Render/age work stops once the application is no longer running.

## Working-source diagnoses, not completed qualification

Thirty-second actual CLI/PTY observations use normal GC without coverage, tracing
or profiling. The source remains unchanged during each invocation; retained
receipts include hashes for all production modules, support inputs, controller,
ordered ANSI and the raw key-to-painted-tail samples. The key toggles wrapping
of long lines and measures actual visible line content, not only a status label.

| Working source behavior | Samples | Observed p95 | Outcome |
| --- | ---: | ---: | --- |
| Original combined observation | 28 | 928.836 ms | Reader lag expired its watch version; the log target became stale |
| Covered root work deferred | 43 | 914.774 ms | Full 30-second run and normal terminal/process cleanup |
| Two reusable line-layout variants | 65 | 387.496 ms | Full source stream delivered; normal terminal/process cleanup |
| Cached turns, shutdown diagnostic retained | 82 | 251.016 ms | Full run and normal terminal/process cleanup |
| Immediate display-control wake and shutdown guards | 87 | 236.184 ms | Full run and normal terminal/process cleanup |
| Prime previously requested wrapped layouts as new lines arrive | 94 | 175.247 ms | Full source stream delivered; normal terminal/process cleanup |
| Refresh header identity only when its actual fields change | 97 | 172.921 ms | Full source stream delivered; normal terminal/process cleanup |
| Reuse immutable row tuples with their retained layout | 100 | 169.965 ms | Full source stream delivered; normal terminal/process cleanup |
| Place the followed tail before its first repaint | 100 | 160.991 ms | Full source stream delivered; normal terminal/process cleanup |
| Slotted immutable table cells with the immediate tail | 101 | 174.653 ms | Full source stream delivered; normal terminal/process cleanup |
| Reuse cached line widths and format text only when needed | 102 | 148.711 ms | Full source stream delivered; normal terminal/process cleanup; original-artifact collector also active |

These working-source observations are not frozen-head or 30-minute acceptance.
The last p95 still exceeds the unchanged 100-ms target. An earlier cached-turn
invocation also exited with a terminal-interface error after its measurements;
its original failed receipt remains retained and its full cause is unresolved.
A later successful diagnostic does not erase that failure.

An additional printable-ASCII wrapping experiment matched Rich's public
renderer across 20,000 seeded input cases and passed 79 focused tests, but its
normal CLI observation remained at 169.097 ms (99 samples). Its source patch,
added test sources, original ANSI and receipt are retained as diagnostic
history. The experiment was removed because this observation did not establish
a useful whole-CLI improvement. Production wrapping still uses Rich.

The immediate-tail change passed six layout/navigation cases, including the
new first-paint position and a queued restoration that must respect later
manual navigation. Slotted-cell, native sizing/rendering/repaint and those
same layout cases passed together as 48 scoped cases. A CPython 3.12.12
object-size diagnostic over 1,000 equivalent cell instances measured 144
shallow bytes for an ordinary instance plus its dictionary and 56 bytes for
the slotted instance. That result describes object layout only; it does not
qualify process RSS, a memory plateau or reduced GC/latency. The latest normal
input p95 still exceeds the target. The subsequent profiling invocation became
stale before completing; its source hashes, original ANSI/profile and zero final
source workers/streams are retained. It is intrusive diagnostic work and cannot
supply normal-runtime timing evidence. It identifies repeated cached-history
iteration, text formatting and width aggregation as hot paths, without proving
the cause of any earlier unprofiled failure.

Lazy text preparation and cached per-layout maximum cell widths passed 24
layout/log behavior cases with strict types. Its newer ordinary diagnostic
received every paced source record, restored the terminal and drained both
processes normally, but the original-artifact collector also ran locally during
that observation. This is recorded as a competing verification condition,
in addition to the existing nonqualification of all short observations. These
working changes now build on the qualified PR #176 squash `9fa25c9`; no new
complete-suite, 30-minute plateau or full release qualification is claimed.

The immutable local 4,387-case cohort finished with 4,384 passes and three
failures, with all 544 Git input hashes unchanged. It remains unqualified. Two
plain-SSH protocol cases repeated an already active 100x30 terminal geometry,
then required new bytes despite the correct breadcrumb already appearing at row
28. Both original ANSI streams, failure screens and source inventory are retained.
The correction exercises a real 80x25 then 100x30 change after shell exit, with
visible geometry, exit and restoration checks preserved. The third failure
expected a covered root table to repaint. Its replacement checks the live
immutable observation, stale-view copy refusal and the recreated UID on return.

The focused inspection/layout/source-SSH cohort passed 13 cases; identity,
theme and removed-header lifecycle coverage passed 18 cases; both fresh-wheel
SSH and SSH-to-tmux protocol cases passed. These are scoped results for their
recorded working inputs, not a new complete-suite qualification. Current Ruff,
formatting and strict production types pass. The newer profiled invocation
became stale before its observation completed; its original receipt, ANSI and
profile remain retained, and its timings do not qualify the normal runtime.

The final observation preserved terminal modes and exited both CLI and source
normally. Bounded source counters and final zero active workers/log streams/
watches are recorded. These do not prove every application task's lifecycle,
context churn or cancelled-forward behavior. Q03 remains open for the latency
correction, full reference-machine methodology, 30-minute memory plateau and
lifecycle qualification. Headless UI cases separately exercise covered selector,
log and nested views, latest-state restoration, quit while covered, layout reuse,
eviction and invalidation. No maintainer trial or public distribution is requested.

## Reproducible observer and captured membership

`tests.support.performance_terminal` now provides the maintained measurement
entry point, with `--seconds 30` or `--seconds 1800` and a required fresh output
directory. Linux `/proc` samples belong to the actual CLI child, separate paced
source and observer. It records normal GC, interpreter/dependency/CPU/affinity/
memory/cgroup facts, 163 measured source hashes, raw input-to-painted-tail
samples, ordered ANSI and process/terminal cleanup. SIGTERM interrupts owned
work through cleanup; original output directories are never replaced. Sixteen
observer tests passed, including real descriptor changes, interruption and
negative memory/descriptor/thread-growth distributions. They validate the
observer; synthetic distributions are not sustained-memory evidence.

The memory rule is declared in `docs/quality.md` before the first sustained run:
ten-minute warmup, four five-minute late windows, at least 54 samples each,
median/p95 RSS ranges within max(8 MiB, 5% of the minimum median), descriptor
range at most two and constant thread count in each process. A short observation
cannot pass. The collector always leaves runtime qualification false; actual
frozen-source review and independent lifecycle evidence remain required.

The target's membership callback previously scanned the active snapshot for
every log line. It now checks membership once per immutable snapshot, including
cached absence, while client, scope and generation guards run on every call.
Capture retains the revision number without retaining its original observation.
A counted owned-HTTP/Pilot contract exercises 1,000 repeated calls, new
snapshots, deletion, reappearance, missing snapshot and context invalidation.
Membership, observer and inspection checks passed as 28 cases; its final
revision-capture check also passed.
The final generator/covered-view/layout/membership/observer cohort passed 39
cases in 13.90 seconds; Ruff/formatting checked 491 files and strict types passed
over the workflow's exact 133-file inventory. Full native qualification for
this new combined-load candidate remains pending.

The maintained observer explicitly selects `q03-09999`, the last row, through
native Ctrl+End before opening logs. Its first `G` setup failed because PodTable
does not yet map that key; this known navigation surface remains B07 #61.
That unchanged-source failed original has zero generated workload, drained
CLI/source owners and no qualification. The corrected invocation completed
30.111 seconds with **138.680 ms p95 / 101 controls**, all **3,012** resource and
**60,240** log records sent, zero source expiry, seven process samples, constant
11 CLI descriptors, normal terminal/process exit and unchanged input hashes.
It remains a short diagnosis above the 100-ms target.

Earlier isolated first-row observations ranged from 124.566 to 155.393 ms.
Increasing cached turns to 512 rows measured 125.125 ms; in-place map pruning
measured 131.060 ms; exchanging complete cache dictionaries measured 140.374 ms.
The latter experiment passed 32 actual log/aggregate/layout cases but did not
establish a latency improvement. All three trials were removed; their exact
sources, receipts and ANSI remain retained. The simpler 128-row reused-layout
turns remain. There is no claim that first-row and last-row observations with
different controller revisions establish a comparative improvement.

## Original sustained observation and native GC correction

The original frozen `04871e571f3fce37891265ee4755543038b770a2` invocation was:

```sh
uv run python -m tests.support.performance_terminal --seconds 1800 --output artifacts/workload50/frozen-04871e5-soak-original
```

On Linux 6.8 / Intel i5-8500T, six available cores, 32,113,976 KiB physical RAM,
CPython 3.12.12 and Textual 8.2.8, the actual 100×30 CLI/PTY completed 1,800.084
seconds, 5,826 public wrap controls and 349 process samples. Its **168.227-ms
p95 fails the unchanged 100-ms target**. All 180,009 resource events and
3,600,180 log lines were produced and sent, without stream expiry. Retained
source bounds, 10,000 visible retained log lines, process-owner exits and terminal
restoration passed. All 163 measured inputs match Git and stayed unchanged.

The predeclared memory subset passed. Each late five-minute window contained
58 samples. CLI RSS medians were 159,824 / 159,874 / 160,060 / 160,072 KiB;
p95s were 159,824 / 160,060 / 160,072 / 160,072 KiB. The 248-KiB range is below
the predeclared 8-MiB allowance; late CLI descriptors remained 11 and threads
remained constant. Source and observer also passed their RSS/descriptor/thread
rules. This does not qualify context churn or cancelled forwards.

Independent review recomputed percentiles and every memory window from raw
samples, verified PID/start-time continuity and monotonic input/byte counters,
matched all source hashes to the frozen Git tree and checked final delivery,
bounded buffers, zero workers and both process-owner exits. Original receipt
SHA-256 is `dc82dbe032d592a447408554795908a98c5d2d38c7dfbb771641155d942a57de`;
the 177,527,854-byte original ANSI SHA-256 is
`b1f3f32720ffe9d9145a5e7b142a595774007cf774455689629c26a86c5c4d3f`.
The independent receipt is retained beside the original, never replacing it.
No local suite or profiler overlapped; lightweight repository/API reads and two
hosted job text-log downloads occurred during the observation. Ordinary GC
remained enabled at 700/10/10; coverage, tracing and profiling were inactive.

Original Application run 38065880441 on PR #177 found two observer-test failures
in each Linux 3.13/3.14 suite: an early guard assumed 3.12's default GC tuple.
The other 4,423 cases passed in each failing environment. Actual untuned isolated
3.13.12 and 3.14.3 processes return 2000/10/10 and 2000/10/0 respectively.
The correction reads the current executable's isolated default rather than
changing GC policy. Nineteen focused cases passed in each actual local
3.12.12/3.13.12/3.14.3 interpreter, including real disabled/tuned-policy refusal.
An initial locally mislabeled invocation was discovered to have recreated its
3.13/3.14 virtual environments as 3.12; those originals are retained and count
only as 3.12 evidence. Correct native invocations record executable, version,
package source and input hashes. Full corrected native checks remain required;
original failures are preserved and no whole-candidate qualification is claimed.
