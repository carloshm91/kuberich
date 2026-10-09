# Aggregate container/workload logs: S06 #54

This issue implements the existing viewer controls over independently admitted
regular/init/ephemeral container sources and controller-owned workload Pods.
The [user guide](../log-viewer.md#all-container-and-workload-logs-s06-54) specifies
exact controls, membership, admission, clock, JSON, retention and replay limits.
Pod Enter still opens containers and only selected-container logs. Generic
resources retain their read-only inspection routes. Embedded-shell terminal history
qualification remains open in #123; this issue does not complete it.

## Local preparation receipts

Owned HTTP fixtures exercise actual per-client requests, response framing and
watch delivery. Pilot uses real public controls at 40×12 and 100×30. The corrected
JSON scalar domain cohort passed 84 cases in 4.52 seconds with:

```sh
uv run pytest tests/unit/test_aggregate_logs.py tests/unit/test_logs.py -q --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/domain-coverage.json --cov-report=
```

At that point aggregate decisions measured 169/169 lines and 48/48 branches,
JSON 38/38 and 12/12, and framing 124/124 and 46/46. Startup decisions subsequently
extended aggregate coverage to 195/195 and 62/62. These are independent critical
domain receipts, not whole-production or final-head qualification.

The initial HTTP/Pilot cohort passed 12 cases in 14.45 seconds. Subsequent owned
intermediate-controller and 64-KiB tiny-line/slow-source cases passed three cases
in 2.89 seconds; the tiny-line case also passed with full package branch
instrumentation in 5.71 seconds. The completion deadline permits instrumentation
and host variation; the separately asserted heartbeat gap remains below 150 ms.
New correction cases passed four cases in 6.01 seconds: 70 source-UID/read cycles
with 64 removed-status and retained-source bounds, workload picker UID churn/
expired selection/Space admission, Pending/init/ephemeral start evidence with
pre-open 400 recovery, and detached export drain before context-client cleanup.

Source and fresh wheel console/module native aggregate trials passed three cases
in 18.99 seconds before the final startup/lifecycle changes. They run outside
the source tree for installed cases, resize 100×30→220×30→40×12→100×30, navigate
actual viewer/picker controls, assert private values absent, exit zero and restore
terminal modes. Stable receipts under `artifacts/terminal` are:

- `aggregate-logs.json` and transcript;
- `installed-aggregate-logs-console.json` and transcript;
- `installed-aggregate-logs-module.json` and transcript.

The final pure suite passed 1,996 cases in 41.13 seconds with an independent
owned coverage file. New aggregate decisions measured 207/207 lines and 68/68
branches; JSON measured 38/38 and 12/12, and shared framing 124/124 and 46/46.
The full source inventory is 109 Python files with 43 declared critical modules.
The unit-only suite does not completely cover the existing Pod/session domains;
their complete coverage remains part of mandatory full-suite qualification.

The final-focused command passed 200 cases in 168.18 seconds:

```sh
env COVERAGE_FILE=artifacts/aggregated-logs-54/final-focused.coverage uv run pytest -q tests/unit/test_aggregate_logs.py tests/unit/test_logs.py tests/contract/test_aggregate_logs.py tests/contract/test_logs.py tests/ui/test_aggregate_logs.py tests/ui/test_logs.py tests/terminal/test_aggregate_logs.py tests/packaging/test_distribution.py::test_installed_aggregate_logs_and_terminal_restore tests/quality/test_ci_policy.py --tb=short --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/final-focused-coverage.json --cov-report= --junitxml=artifacts/aggregated-logs-54/final-focused.xml
```

It includes source and fresh-installed aggregate PTYs, old single-log controls,
full 5,000-line rendering/formatting/export heartbeat, protected file refusal,
clipboard bound and real Pending/CrashLoop current/Previous reads. Ruff/format
and both local site digest/link checks pass; the actual browser checked all
49 desktop/mobile pages with zero violations/errors/external requests. Mandatory
frozen four-native/eight-check PR qualification remains separate.

The subsequent footer/lifecycle and malformed-array correction cohort passed
125 cases in 72.61 seconds, including all three real source/fresh-installed PTYs.
The final object/array-boundary cohort passed 120 cases in 4.51 seconds:

```sh
env COVERAGE_FILE=artifacts/aggregated-logs-54/json-boundary.coverage uv run pytest tests/unit/test_aggregate_logs.py tests/unit/test_logs.py -q --tb=short --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/json-boundary-coverage.json --cov-report= --junitxml=artifacts/aggregated-logs-54/json-boundary.xml
```

It measures aggregate decisions 207/207 lines and 68/68 branches, JSON 49/49
and 18/18, and shared framing 124/124 and 46/46. These local correction receipts
supersede the earlier domain shape; full frozen native qualification still follows.

An enlarged diagnostic cohort ended 2,188 passing cases and one failure in
501.17 seconds. Its empty-source UI command preceded usable discovery, now
corrected. Concurrent coverage runs accidentally shared `.coverage`, invalidating
that run's report; it is retained without any passing coverage claim. All later
runs use separate owned `COVERAGE_FILE` paths. Another focused attempt measured
a 151.99-ms heartbeat gap under instrumentation/load; framing now runs in the
existing owned parser, retaining the 150-ms assertion rather than loosening it.
Passive source-picker refresh also erased an admission error; the error now
remains until the next choice. No diagnostic substitutes for frozen qualification.

## Actual disposable Kubernetes receipt

```sh
uv run python -m scripts.verify_aggregate_logs_kind --kind /PATH/TO/OWNED/kind
```

The corrected verifier passed eleven checks on owned cluster
`kuberich-test-7e49fc8ba0e8419b98217ecafc1e98b7`, then deleted it and verified absence.
It uses kind v0.33.0, pinned Kubernetes 1.36.4 node and pinned Alpine container
images through the shared owned-cluster wrapper. Caller kubeconfig bytes remained
unchanged. Actual controller membership excludes a matching-label Pod with another
controller; Deployment→ReplicaSet→Pod and CronJob→Job→Pod are verified against
captured actual UIDs. Regular/init/multiple-Pod logs, decoded JSON/plain output,
live ephemeral enrollment, Pod deletion/replacement, actual Pilot controls and
all reader/watch cleanup before SDK close passed.

The CronJob child uses an eight-second init sleep. The verifier observes its app
source **starting** before app output, then receives app logs without any
`choose`/reopen invocation. This proves enrollment rather than relying on a Pod
that had already started before LIST. `artifacts/cluster/aggregate-logs-kind.json`
records the eleven check names, limits, pins, unique cluster and deletion status;
`aggregate-logs-kind.svg` retains the actual API/Pilot view.
An actual Pod was observed waiting in CrashLoopBackOff with a valid terminated
container ID before opening aggregate readers. Current and Previous both
delivered its first snapshot without manual selection/reopen, then reached EOF.
The first delivered source token is asserted `last-terminated`, so a racing
restart into Running cannot qualify the initial-waiting case. This remains a
local draft receipt until the frozen source runs the mandatory verifier again.

## Discovered failures and corrections

The first kind draft reached CronJob membership but timed out after 120 seconds
waiting for output: admission requested logs before container start, got 400 and
never reconsidered start evidence. Its cluster
`kuberich-test-89c5c0936b80486c992befd7f99ea694` was deleted. A second diagnostic
rehearsal waited for Running and manually reopened, passing nine checks on
`kuberich-test-67eaf5ec554d44cfb041044a9d794be9` and deleting it; that workaround
does not qualify startup. The ten-check startup rehearsal on
`kuberich-test-29c01bc570c540eba64677f4917ff414` replaced that workaround and
deleted its owned cluster; the eleven-check CrashLoop receipt above extends it.

Review reproduced JSON/control expansion exceeding the old line presentation
bound, ordinary bracket logs being withheld, valid object shape lost by pre-parse
redaction, and escaped credentials in top-level JSON strings. Actual decoder→
aggregate/body/export regressions now cover bounded visible truncation, useful
fields and typed scalar/decoded-key redaction without retaining raw secrets.
Malformed first object/array tokens followed by encoded credential keys also
reproduced a plain-text fallback leak; one explicit candidate rule now withholds
those structures while preserving ordinary completed bracket prefixes followed
by prose and keeping whole arrays typed.
Source picker state/column widths and selected identity were corrected after
native/Pilot failures. Selection pruning keeps explicit empty admission when a
Pod disappears, preventing automatic replacement-UID admission.

A public Escape/save/context-change probe reproduced captured SDK cleanup while
a dismissed viewer still drained export work. A bounded ownership registry now
retains that viewer until every task finishes, and before-close drains it even
when absent from the visible screen stack. The corrected behavioral regression
passes. Earlier failed/partial runs are diagnostic, never passing qualification.

An independent context-change probe showed already-drained readers with a stale
footer still reporting reception enabled. Closing/stale presentation now says
reception stopped, reports zero readers and clears draining feedback after
cleanup. The first correction attempted a DOM query during detached unmount,
failing eleven cases in 95.57 seconds; it now updates only the retained mounted
status reference during close. The subsequent 125-case correction cohort passed.

The first frozen hosted source, `b5e6b9cd42557f12f469dfad9ff3ac6bb0ccdb43`,
failed Linux 3.14 job 113971686813 in run 37975199209: four failures and 4,039
passes in 920.90 seconds. The actual tested PR merge checkout was
`8ec5b894890b9b315ccc95791cc5bd44a3c1a26f`. Adding a separate aggregate hint
created thirteen Pod shortcuts in a settled two-column/six-row header and
clipped Help. Three existing real-terminal resize/quit cases and the existing
logo-width/reflow Pilot assertion caught it. A local Pilot reproduced the
failure before correction. Pairing `l/L` as `Logs / aggregate` preserves both
actions, Help and header geometry; the original assertions remain, with added
paired-hint visibility checks. All four original native jobs finished with
failures; none was cancelled or omitted:

| Environment | Job | Passed / failed | Duration |
| --- | --- | --- | --- |
| Linux 3.12 | 113971686903 | 4,038 / 5 | 1,787.83 s |
| Linux 3.13 | 113971686800 | 4,038 / 5 | 1,282.63 s |
| Linux 3.14 | 113971686813 | 4,039 / 4 | 920.90 s |
| macOS 3.12 | 113971686886 | 4,039 / 4 | 1,721.24 s |

Linux 3.12 and 3.13 also exceeded the unchanged 150-ms full-history heartbeat
limit, measuring 275.49 and 297.52 ms respectively. Their logs and failed
receipts remain diagnostic evidence. The repository/browser and DCO checks
passed, but the application quality gate failed. This source cannot qualify
the replacement candidate.

The correction cohort passed sixteen cases in 79.72 seconds, including header
lifetime, the original reflow/three real-PTY quit cases, aggregate UI and all
three source/fresh-installed aggregate PTYs. ReplicaSet F1 help advertises
Shift+L/`:logsall`, then Escape/Shift+L opens the aggregate viewer. Ruff/format and
strict types pass. The replacement commit still needs fresh full native and
whole-production coverage qualification; the failed b5 run is not reused.

A 64-case Python 3.13 navigation/resource/single-log prelude reproduced the
history failure locally. Bounded phase/CPU/GC diagnostics and weak references
showed a 152.88-ms collection reclaiming the preceding closed app while keeping
the current aggregate app alive. Capturing the current Rich style once per
projection removed repeated style construction, but still failed at 155.26 ms.
Collecting prior-fixture garbage before creating the current app was also
insufficient: repeated live-app work still failed at 150.44 ms. Those failed
sequence receipts are preserved, rather than attributed to host noise.

An intermediate correction constructed its styled `Strip` directly through the same public
`Segment.apply_style` transformation, avoiding a temporary Strip and its seven
FIFO caches per row. Existing 40/100-column Pilot controls additionally assert
literal no-query colors and wrapped search colors/reverse/bold. The diagnostic
64-case sequence passed in 197.26 seconds, with both 5,000-row cycles and
Current/Previous transitions completed in one app. Its maximum gap was 147.45 ms;
three measured generation-two collections remained, with normal GC enabled.
The small margin and probe preimports mean this is diagnosis, not coverage or
platform qualification. Ordinary pytest and fresh full native checks follow.
Fixture collection occurs only before current-app construction; no live layout,
mode/timestamp/copy/save, stream transition or teardown collection is moved
outside the unchanged 150-ms measurement. GC settings are unchanged.

Ordinary instrumented pytest then passed the 64-case sequence in 188.24 seconds
at 149.76 ms. That repeat fixture held two independent input histories at once;
the final fixture prepares its second 5,000-record history sequentially through
the existing owned parser while the heartbeat remains active, after the first
Current/Previous cycle clears its data. Public Escape and drained ownership are
also included before the final assertion.

The corrected Python 3.12 affected cohort passed 217 cases in 182.84 seconds:

```sh
env COVERAGE_FILE=artifacts/aggregated-logs-54/corrected-cohort312.coverage uv run pytest tests/unit/test_aggregate_logs.py tests/unit/test_logs.py tests/contract/test_aggregate_logs.py tests/contract/test_logs.py tests/ui/test_aggregate_logs.py tests/ui/test_logs.py tests/ui/test_header_lifecycle.py tests/ui/test_resource_workspace.py::test_shortcuts_reflow_when_logo_width_settles_without_another_header_resize tests/terminal/test_shell.py::test_real_terminal_navigation_resize_and_quit tests/terminal/test_aggregate_logs.py tests/packaging/test_distribution.py::test_installed_aggregate_logs_and_terminal_restore tests/quality/test_ci_policy.py -q --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/corrected-cohort312-coverage.json --cov-report=
```

It covers actual literal/highlighted/wrapped colors, the original header checks,
old/new log controls, HTTP identity/lifetime and all source/fresh-installed
aggregate PTYs. New deterministic domains remain 207/207 lines and 68/68
branches, JSON 49/49 and 18/18, shared framing 124/124 and 46/46. Both sequential
history rounds completed with a 130.77-ms maximum gap and normal enabled GC.
Peak prepared fixture data was 5,000 records; one retained real API line plus
the pending refill briefly totaled 5,001. After public Escape the viewer and
owner were closed, owner tasks/readers/registry/API log streams were zero, and
the original root workspace watch remained at its baseline of one. These local
receipts do not replace full-production/final-platform qualification.

The ordinary Python 3.13 sequential fixture then failed at 150.62 ms in a live
layout, despite fixture isolation and the direct Strip construction. That failure
is retained as `corrected-sequential-prelude313-*`; the 150-ms limit stayed intact.

An intermediate widget correction retained immutable styled segment tuples for every
retained layout and creates actual Textual Strips only for viewed rows. A separate
128-entry LRU holds those Strips, keyed by retained line/subline and checked
against the actual current segment identity. Invalidated or expired projections
lose their cache entries. The same public Rich styling path, wrap heights,
navigation revisions, marks, search and viewport identities remain in use.
Additional layout/cache allocation remains separate from the 4 MiB text bound.

Ordinary Python 3.13 pytest passed the 64-case prelude in 185.98 seconds with
both sequential full-history rounds and public Escape/drain completed. Its
maximum gap was 120.06 ms; live generation-two collections remained measured,
with GC enabled at default thresholds. The expanded Python 3.12 affected cohort
then passed 217 cases in 202.47 seconds at 126.70 ms:

```sh
env COVERAGE_FILE=artifacts/aggregated-logs-54/lightweight-cohort312.coverage uv run pytest tests/unit/test_aggregate_logs.py tests/unit/test_logs.py tests/contract/test_aggregate_logs.py tests/contract/test_logs.py tests/ui/test_aggregate_logs.py tests/ui/test_logs.py tests/ui/test_header_lifecycle.py tests/ui/test_resource_workspace.py::test_shortcuts_reflow_when_logo_width_settles_without_another_header_resize tests/terminal/test_shell.py::test_real_terminal_navigation_resize_and_quit tests/terminal/test_aggregate_logs.py tests/packaging/test_distribution.py::test_installed_aggregate_logs_and_terminal_restore tests/quality/test_ci_policy.py -q --tb=short --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/lightweight-cohort312-coverage.json --cov-report= --junitxml=artifacts/aggregated-logs-54/lightweight-cohort312.xml
```

Both measured rounds completed; peak prepared history was 5,000 records and the
transient retained-plus-refill count was 5,001. After Escape all viewer/owner
tasks, readers, registry entries and API log streams were drained, with only the
original root workspace watch at its baseline. Aggregate/JSON/framing critical
domains again measured 207/68, 49/18 and 124/46 covered lines/branches, all 100%.
The 15,000-line test also saturated the visible cache through public paging,
preserved its resize anchor, pruned stale identities after Head 1000 and asserted
the actual rendered first line. Local receipts do not replace final full native
and whole-production qualification for the replacement commit.

That signed replacement, `23d0dfb67a375daa4a172d97cd447694b615c1c2`, actually
ran [37987629105](https://github.com/carloshm91/kuberich/actions/runs/37987629105)
using checkout `b64152d2c4192e71c30ff78bd02d961908d7b457`, with the same source
tree. It remains failed evidence:

| Environment | Job | Passed / failed | Suite duration | Maximum heartbeat |
| --- | --- | --- | --- | --- |
| Linux 3.12 | 114013515372 | 4,042 / 1 | 1,792.90 s | 238.49 ms |
| Linux 3.13 | 114013515291 | 4,042 / 1 | 1,434.20 s | 207.72 ms |
| Linux 3.14 | 114013515366 | 4,043 / 0 | 1,145.55 s | 34.10 ms |
| macOS 3.12 | 114013515317 | 4,043 / 0 | 1,718.45 s | 131.44 ms |

Both failures were the unchanged 150-ms retained-history contract. Linux 3.12
paused for a 232.30-ms generation-two collection during first-round mode/
timestamp/copy; Linux 3.13 paused for 201.76 ms in second-round initial layout.
They completed zero and one full rounds respectively; neither recorded a passing
after-close receipt. Default runner GC thresholds remained enabled. Headers and
all other cases passed, but neither coverage nor the two successful environments
qualifies this source. Repository and DCO passed; the application gate failed.

A pinned allocation probe found 5,000 retained Segment objects, 5,000 rendered
descriptor objects and 20,002 tuples for a 5,000-row no-wrap layout, plus 10,000
LogEntry/LogLine projection wrappers. Only one base style was retained. An ignored
full-catalogue diagnosis retained all 4,043 collected pytest items and counted
331,273 live tracked setup objects. Its selector initially ran the benchmark
first: 64 selected cases passed in 227.04 s, with a 112.31-ms live generation-two
collection and no preceding closed app reclaimed. That is catalogue-root
diagnosis, not the later ordered prelude or platform qualification.

The next correction uses primitive immutable text, cell-width and highlight-range
descriptions for retained sublines. It keeps eager Rich folding, match IDs,
wrap heights, viewport restoration and navigation generations. Actual styles,
Segments and Strips are constructed only for viewed rows in the same 128-entry
cache, checked against current descriptor identity. Theme-only changes invalidate
visible styles without a new load or reader. Aggregate formatting hands the
widget sanitized `(number, text)` pairs rather than another wrapper object pair.
The ignored pinned-library probe passed 1,080 combinations and 15,200 styled
segments, including wide/combining/ZWJ/VS16, wraps, highlights, widths and crops.
Actual-widget review also passed 40 cases and 185 rendered cropped rows, including
cross-wrap highlights and a theme-only update with no new layout. Primitive
container tuples still have GC tracking; no zero-allocation or total-RSS claim is
made. The ordered catalogue-retaining diagnostic then ran the benchmark last
after navigation, resource workspace and single-log cases: 63 passed and one
failed in 222.26 s, with 3,979 other collected items retained but deselected. Its
second-round mode/timestamp/copy heartbeat reached 182.36 ms, overlapping a
176.93-ms generation-two collection of 5,180 objects. Only the current running
application survived that collection; no prior closed application was reclaimed.
One round completed, and no passing final-drain receipt was recorded. The
outside-measurement setup census counted 525,885 tracked objects. This failed
diagnostic remains preserved.

The subsequent plain, unwrapped, no-query path uses the same public Rich control
sanitizer and cell-width calculation directly, avoiding transient Text objects,
lists and span-boundary sets/generators. Wrapped or highlighted parts retain
Rich's folding and spans; parts without spans avoid boundary expansion. Ordered
diagnosis again failed: 63 passed and one failed in 120.85 s, at 182.63 ms with a
175.87-ms generation-two collection, now triggered by a Pilot callback allocation.
One full round completed, with no passing final-drain receipt. Both failed
diagnostics remain retained. Actual raw-tab rendering also exposed Rich-generated
base-style spans: primitive descriptions now distinguish these from highlights,
preserving their order, cell widths and exact segmentation. Independent actual
widget review passed 80 cases and 510 cropped rows across both input forms,
raw controls, wrapped matches, Unicode and theme changes without a new load.

Outside-heartbeat root attribution found 327,181 retained objects with the full
4,045-item catalogue, including 24,297 Lark trees and 24,297 metadata objects
rooted by the development-only `rfc3987_syntax` grammar. After the actual 65-case
ordered prelude, all 62 apps were gone, but 489,434 roots remained and a normal
collection took 168.13 ms. Textual's Strip/FIFO caches were genuine runtime roots
and were preserved. Production UI imports independently measured 93,501 roots
and roughly 25–27-ms collections; the grammar is absent from locked installed
runtime dependencies. Ordinary targeted Python 3.13 pytest passed the unchanged
two-round benchmark in 7.45 s at 63.83 ms, including a 53.88-ms live collection.
This distinguishes development-catalogue contamination from deployed runtime
behavior; it does not establish platform or sustained-RSS qualification.

The reviewed replacement keeps the required full-suite test node and runs its
performance body in owned positive/negative fresh processes. Four same-app public
Pod/ReplicaSet reopen, source-picker, theme and 40/100-column cycles warm genuine
runtime caches under the same heartbeat before two full 5,000-record rounds.
Normal/default GC, the 150-ms limit, 5,001 combined-record bound, original controls
and public Escape/drain remain required. The negative child injects a deliberate
200-ms callback and must fail specifically that heartbeat assertion. Source/nonce/
import inventories, XML, deadlines, output bounds and process/App/API cleanup are
verified; full-suite functional/audit tests and all coverage gates remain required.
Only the passing child's branch data is merged with the preserved parent data,
with exact inventory/arc-union and provenance checks; negative coverage is never
used. The required local/CI command after pytest is
`uv run python -m scripts.merge_runtime_coverage`.

The first scoped warm pair passed its outer Python 3.13 test in 61.44 s: positive
30.15 s, 133.83-ms maximum, two full rounds and complete drain; negative 25.17 s,
207.54-ms maximum, the exact intended heartbeat failure and complete app cleanup.
Both retained default GC, 1,947 imported modules without the development grammar,
and 162 source input stamps. Original XML/coverage/logs/receipts are preserved as
local diagnostic evidence. After the complete merge helper and its rejection
regressions were in place, a fresh ordinary Python 3.13 pair passed the outer case
in 60.87 s: positive 120.20 ms, two complete rounds and 5,001 combined records;
negative 206.78 ms, the intended heartbeat failure and 5,000 combined records.
Both completed four warm cycles with default GC, 163 source stamps and drained
App/API/process ownership. The actual post-pytest helper verified the exact arc
union across all 109 production modules, preserved the original parent evidence
under the positive nonce and regenerated branch JSON/XML without loading negative
coverage. All 46 receipt/CI regressions passed, including stale/missing/tampered/
negative-only rejection and refusal to overwrite the preserved parent archive.
These local receipts preceded further required checks. The ordinary Python 3.12
affected cohort then failed its required warm child: 245 passed and one failed in
232.08 s. That positive child reached 196.94 ms during public warm navigation,
with zero completed rounds; the fail-closed wrapper did not run a fresh negative
child. Source/fresh-installed PTYs, layout/style and receipt regressions passed
individually, but this cohort is not qualified. Its original child and parent
XML/data/reports remain preserved.

Precise warm subphases and bounded ignored callback profiling located synchronous
CSS reparse/update and compositor work. A profiled traced run failed at 174.54 ms,
with CSS refresh reaching 141.47 ms; an otherwise equivalent untraced diagnostic
passed at 113.88 ms, CSS refresh 75.28 ms. The ordinary paired proof changed only
coverage collection: pinned coverage 7.16.2 with active CTracer/trace callback
failed at 177.48 ms, versus inactive coverage/no trace or profile callback passing
at 112.49 ms in the same default-GC, four-warm-cycle, two-full-round scenario.
Both used identical 163 input hashes and drained App/API/process ownership. This
attributes instrumentation overhead; none of those diagnostics qualifies CI.

The required replacement now owns three children: uninstrumented `positive` and
`negative` runtime checks with unchanged 150-ms assertions, and a successful
`coverage` replay of every warmed/full-history/non-time behavior assertion under
branch instrumentation. Its measured timing is explicitly nonqualifying. All
three require exact source/nonce/XML/import/version/core/trace/profile facts,
default GC and drained ownership. Only the successful coverage replay's database
can merge with the preserved parent; runtime children have no coverage data.
The merge verifies the full 109-module arc union and provenance under a unique
`coverage_nonce`; every existing coverage/native gate remains required.
The first required Python 3.12 trio passed its outer case in 91.05 s. Runtime
positive measured 113.04 ms with two full rounds; the deliberate negative failed
the exact heartbeat at 204.65 ms. Both had inactive coverage and no trace/profile
callback. The CTracer functional replay completed both rounds and every non-time
assertion at a recorded, nonqualifying 176.11 ms. All three retained four warm
cycles, default GC, identical 163 input stamps and drained App/API/process owners.
The real merge verified the complete 109-module parent/replay arc union, preserving
the parent under `coverage_nonce` without reading runtime coverage. All 58
receipt/CI regressions passed, including incorrect instrumentation, missing replay
and rejection of a runtime database as input. The final ordinary Python 3.12 affected
cohort subsequently passed all 258 cases in 290.09 s, including pure/HTTP/Pilot,
source/fresh-installed PTYs, style/cache/Head/header contracts and all 58 receipt/
CI regressions. Its runtime positive measured 115.74 ms across two rounds;
negative failed exactly at 206.98 ms, and the successful traced replay recorded
nonqualifying 193.27-ms timing. The real parent/replay merge verified all 109
module arc unions. The three critical log decisions remained 207/207 lines and
68/68 branches, 49/49 and 18/18, and 124/124 and 46/46. These focused results are
not the whole-package/native matrix qualification, which remains required for
the signed frozen candidate.
No GC,
heartbeat, history or job-deadline limit is changed by this correction.

The signed replacement `b9ecbf3eec95ab311423b0c43e5682077b513478` then
failed its actual required run 38000521236. Actions tested PR merge checkout
`fa22e75696f93c4088a14d488782ed0f65afd707`, with the same candidate tree.
Repository/browser, DCO and three native environments passed, but Linux 3.12
and the aggregate application gate failed:

| Environment | Job | Passed / failed | Suite duration | Runtime maximum |
| --- | --- | --- | --- | --- |
| Linux 3.12 | 114057237827 | 4,083 / 1 | 1,881.63 s | 160.96 ms |
| Linux 3.13 | 114057238018 | 4,084 / 0 | 1,483.58 s | 88.76 ms |
| Linux 3.14 | 114057237840 | 4,084 / 0 | 977.03 s | 38.69 ms |
| macOS 3.12 | 114057237787 | 4,084 / 0 | 2,101.67 s | 118.32 ms |

The failed positive child was uninstrumented with default GC and no trace/profile
callback. Its warm-two resource route measured 160.96-ms wall and 158.89-ms main
CPU, overlapping a 95.44-ms generation-two collection while a table recomputed
its inherited style. Four warm cycles ran but no full-history round completed.
The fail-closed wrapper stopped before negative/replay or the Linux kind checks.
The final child cleanup still recorded app stopped and registry/log/watch counts
zero; the earlier heartbeat's after-close field was null because the assertion
failed. Original artifact 11650435293 and all other native outcomes remain retained.
The three successful environments and their coverage cannot qualify this source.

An independent unchanged-source heap census found genuine Strip/FIFO cache growth
through the four public warm cycles; closed-screen weak references disappeared
after application cleanup and diagnostic collection. The unused prepared history
contributed roughly 10,000 tracked roots during warm-up. That fixture and the
runtime caches remain unchanged. The narrow production correction captures the
inherited table style once within a synchronous `render_lines` frame, shares it
with nested rendering, and restores it in `finally`. Pod, standard/custom and
aggregate source-picker tables use this widget-local helper; subsequent themes
and visibility/layout changes recompute their style normally.
An ignored actual-table prototype preserved exact styled segments/cell lengths
in 48 cases and reduced full inherited-style calculations from 680 to 48. This
is allocation evidence, not a platform latency qualification. The ordinary
Python 3.12 required trio plus three actual table-rendering cases passed four
cases in 97.73 s: positive 112.73 ms/two full rounds, deliberate negative 201.31 ms
with the exact intended heartbeat failure, and successful instrumented replay
with nonqualifying 203.78-ms timing. All children drained and retained the original
warm-up, GC, 150-ms, 5,000/5,001 bounds and controls. The real replay-only merge
verified all 109 module arc unions. New visual helper coverage is 25/25 lines
and 2/2 applicable branches. These are uncommitted local correction receipts;
fresh frozen native qualification remains required.

The broader ordinary Python 3.12 affected cohort passed 353 cases in 546.32 s.
It includes existing Pod/standard/custom table sorting, scrolling, navigation,
details and render contracts, prior aggregate/log/receipt controls, source PTYs
and fresh-installed aggregate/standard console/module trials. Its untraced
runtime child reached 103.87 ms with two full rounds and complete drain; the
deliberate negative failed the exact heartbeat at 205.98 ms. The successful
functional replay retained every non-time behavior assertion, with nonqualifying
178.10-ms timing. The real helper verified the complete 109-module parent/replay
arc union, and the three critical log decisions plus the visual helper remained
100% lines/applicable branches. The original logo-settle reflow regression also
passed separately in 1.15 s. Originals are retained under
`artifacts/aggregated-logs-54/frame-cohort312-evidence/`; execution used the b9ec
checkout with these uncommitted source bytes. They do not establish full/native
qualification of the next signed candidate.

## Qualification limits

The source remains a local implementation candidate until its signed frozen PR
passes all required native/gates and independent review. No provider certification,
user-cluster trial, package/version/tag or website publication occurs here.
Memory bounds apply to application histories/source metadata; transport/socket,
layout and runtime allocation are separate. No overall RSS, synchronized-clock,
maximum-load or secret-recognition guarantee is claimed. Q03 and Q05 retain
sustained performance and optional real-provider certification.
