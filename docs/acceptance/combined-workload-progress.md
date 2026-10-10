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

## Incremental retained geometry and fixed-height refresh diagnosis

The subsequent local prototype reuses an exactly matching retained entry prefix
for each of at most two wrap geometries, prunes evicted identities and prepares
only its new tail in cooperative turns. Its first normal observation measured
154.931 ms p95 / 106 controls, with 3,019 events and 60,380 log lines delivered.
That result remained above target; no improvement was inferred from one short
distribution. The exact working sources and original ANSI/receipts are retained.

An intrusive cProfile diagnosis completed 67 controls before its paint-byte
assertion failed. Both owners drained, the profile and failure are preserved,
and this result cannot qualify latency. A separate bounded actual-CLI GC callback
diagnosis left ordinary 700/10/10 policy unchanged and observed 12 generation-two
collections, with a largest 80.482-ms pause. It measured 106.676-ms input p95;
only some slow inputs overlapped a long collection. This is instrumented
diagnosis, not proof that GC explains every input delay.

Inspection found that changing one-row log metadata called native Static updates
with their default whole-layout refresh. The correction requests `layout=False`
for their fixed geometry and skips unchanged heading/frame titles, retaining
native resize, virtual log sizing and literal/sanitized text. The first normal
corrected short run was:

```sh
uv run python -m tests.support.performance_terminal --seconds 30 --output artifacts/incremental50/normal-fixed-height-original
```

It completed 30.166 seconds, 113 controls, **91.190-ms p95**, a 61.662-ms median,
3,017 resource events and 60,340 log lines, all sent without source expiry.
Measured inputs stayed unchanged and both process owners and the terminal
closed normally. Its 3 inputs above 100 ms do not invalidate this percentile;
the 30-minute sustained distribution and memory rule remain required. No full
candidate coverage, native qualification or Q03 completion is claimed.

Ten focused existing layout/literal/live-control/resize cases passed before that
short run. Four added Rich/cancellation cases exercised both entry forms and
partially cancelled wrap warming. Extending their sequence to reorder entries
under an unchanged query found two genuine failing originals: cached matches
included retained entries outside the reused prefix. Matching is now pruned to
that prefix before appending the new order. The corrected 12-case cohort passed;
the original failing sources and logs remain retained. The complete owned log
cohort subsequently passed **36 cases in 223.20 seconds**. Exact workflow
Ruff/formatting checked 492 files and strict types passed over 133 source files.
The later frozen-source sustained observation is recorded below. Full native
and remaining lifecycle qualification are still required.

## Frozen incremental candidate sustained observation

The original immutable source was
`30b6856878d74fd61fab6b7e828157ab003a03e6`, with clean tracked inputs throughout.
The exact command was:

```sh
uv run python -m tests.support.performance_terminal --seconds 1800 --output artifacts/incremental50/frozen-30b6856-soak-original
```

Reference machine: Linux 6.8.0-142/glibc 2.39, Intel i5-8500T at 2.10 GHz,
six available CPUs with affinity 0–5 and 32,113,976 KiB physical memory.
The interpreter was CPython 3.12.12; Textual 8.2.8, kubernetes-asyncio 36.1.0,
pyte 0.8.2 and PyYAML 6.0.3 were installed. Coverage was installed but inactive;
there was no tracing or profiling. Enabled GC retained its ordinary 700/10/10
thresholds, verified against the same isolated executable's defaults.
No local suite, profiler or artifact verifier overlapped the observation.
Lightweight source/status/API reads, preparation of ignored review scripts and
an issue-status update did occur. Native artifact collection started after the
soak process reported its terminal exit.

The 100×30 real CLI/PTY selected the last of 10,000 Pods and retained 10,000
log lines within the existing 4 MiB bound. Public `w` controls alternated actual
wrapped-tail appearance/disappearance, with 200-ms idle between controls.
The independently paced source sent all 180,029 resource events and 3,600,580
log lines during 1,800.285 seconds, without watch/log expiry. This describes
transport delivery; ordinary bounded history eviction still applies.

Independent review recomputed **99.076876-ms p95 across 6,533 controls**, checked
350 process samples and verified all 163 source hashes against Git and disk.
The unchanged 100-ms target passed with only **0.923124 ms** of margin; this is
reference-machine evidence, not a guarantee for every input or machine.

The four predeclared five-minute windows after ten minutes of warmup each had
58 samples. CLI median and p95 RSS values were 162,460 / 162,480 / 162,480 /
162,544 KiB: an 84-KiB range, within the declared 8-MiB allowance. Its 11
descriptors and 13 threads stayed constant. Source and observer also passed
their independently recomputed RSS, descriptor and thread rules. Both process
owners exited zero, terminal attributes were restored and final source watches,
log streams, workers and LIST snapshots were zero.

Original receipt SHA-256:
`f335a9d3c905f60ade287781cc44d887c499a87c54ac9182aa1e6b5148c1f8b4`.
The 89,586,069-byte original ordered ANSI has SHA-256
`8e44c883e55f91d51ba87a565ccc6b7834f38e47c79cb6c4d5a957a9524b32fc`.
The retained independent review accepts only the combined-load latency and
memory subsets; the observer deliberately keeps `runtime_qualified=false`.
The candidate's full native checks and context-churn, slow-consumer and cancelled
forward lifecycle evidence remain required. Q03 remains open. Earlier failures
and their original sources/artifacts are retained without reruns or replacement.

## Repeated owned lifecycle cohort

The preceding production correction is now merged by PR #178 as `e095b28`.
Original required Application run `38074520032` passed 4,432 Linux cases per
Python version and 4,429 on macOS with three explicit Linux-only observer skips.
Independent original review verified at least 99.08% lines, 96.84% branches and
96.15% changed lines, all 43 critical modules at 100%, complete source-linked
package/runtime/terminal/audit evidence and real owned-kind scenarios.
Original Repository run `38074520162` binds 140 source files and 49 desktop plus
49 mobile browser pages. The squash has the qualified source's exact tree and
all 163 original sustained runtime inputs. Full release qualification remains
separate; the following new test-only cohort still needs its own native checks.

The owned HTTP/process cohort uses three warmup and 36 measured cycles for each
of context/forward changes, slow large-watch consumers, forward startup
cancellation and expiry/recovery after a held initial snapshot. Each cycle must
return to exact baseline descriptors, live threads
and pending asyncio task counts. This is resource ownership evidence, not an
additional input-latency or RSS observation. The exact tested command was:

```sh
uv run pytest -q tests/contract/test_performance_lifecycle.py
```

The initial four-case cohort passed in each actual local CPython 3.12.12, 3.13.12
and 3.14.3 interpreter, in 28.29 / 22.82 / 22.88 seconds respectively. The extended
five-case cohort then passed in 47.07 / 38.30 / 38.11 seconds on those same actual
interpreters. Its twelve successful scenario originals each contain 36 measured
samples: descriptor counts stayed
15 on 3.12 and 16 on 3.13/3.14, live thread counts stayed 11 and pending tasks
stayed zero. These absolute descriptor counts include pytest's own capture;
the invariant is the unchanged count within each process.

Context cycles switch two actual owned HTTP clients with 40 retained resources
and 64 large annotation updates per watch. The delayed subscriber holds only the
latest immutable observation. SessionService's close hook stops the real forward,
then the old watch, HTTP pool and private directory are checked drained. The child
is reaped and its bound listener refuses new connections. Closing the workspace
clears discovery, subscriptions and the retained snapshot. Configuration bytes
stay unchanged and forward history saturates at 32 non-client-bearing records.

Slow-consumer cycles offer 128 individually streamed 64-KiB annotation frames.
The first event is held at the sink; parser invocation stays at one through the
hold. Repeated cancellation drains the watch, HTTP connection and source handler.
Startup cycles cancel real children that have not advertised readiness, including
repeated cancellation of the client-change cleanup owner; the process and staged
file must be gone. A fifth case creates a real extra descriptor, thread and task,
checks that all three observations increase, then returns to its baseline.

The additional expiry/recovery cycle stalls a genuine LIST snapshot consumer
while the independently paced source advances beyond its old opaque version.
The owned protocol fixture uses three resources and a three-event replay ring
to trigger expiry quickly; the 10,000-resource performance workload and its
1,000-event replay bound are unchanged. Normal ListWatch receives the actual
410, emits RELISTING with no retained old snapshot, obtains a fresh LIST and
reopens from its current version. Both original watch versions and all three
recovered rows are checked, followed by drained HTTP/source workers, unchanged
configuration and the same resource-count assertions. No recovery method is
mocked or replaced. Its first focused original passed 39 total cycles in 19.57
seconds; its source and original receipts remain retained.

The first context trial failed its thread-count assertion: the native default
executor was still populating lazily after three cycles. Its original failure
and source are retained. A separately labeled diagnostic observed all 39 cycles:
only native `asyncio_0` through `asyncio_9` workers appeared, bounded by the
unchanged ten-worker default, with stable descriptors and zero pending tasks.
The maintained trial now fully populates that existing native pool before its
baseline and records its capacity. It keeps the three-cycle warmup and exact
resource assertions; its actual extra-thread negative control remains required.

Receipts retain interpreter/platform facts, all production and relevant fixture
hashes before/after, cycle samples and cleanup facts under unique filenames in
`artifacts/backend/`. Full native CI for these new cohort sources remains
required before Q03 closes. Existing oversized-frame rejection, bounded source
admission/replay/410 and real-kind forward/context tests remain complementary;
this controlled HTTP/process cohort does not certify a cloud provider or replace
the actual-cluster contracts. No production behavior or performance limit changed.
