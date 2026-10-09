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

The final widget correction retains immutable styled segment tuples for every
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

## Qualification limits

The source remains a local implementation candidate until its signed frozen PR
passes all required native/gates and independent review. No provider certification,
user-cluster trial, package/version/tag or website publication occurs here.
Memory bounds apply to application histories/source metadata; transport/socket,
layout and runtime allocation are separate. No overall RSS, synchronized-clock,
maximum-load or secret-recognition guarantee is claimed. Q03 and Q05 retain
sustained performance and optional real-provider certification.
