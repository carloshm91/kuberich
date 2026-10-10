# Bounded table-width work: Refs Q03 #50

This change addresses one measured hot path. Q03 remains open for the combined
10,000-resource / 100-event / 2,000-log workload, input p95 below 100 ms,
10,000 retained log lines, a 30-minute memory plateau and lifecycle qualification.
No workload, coverage, heartbeat, retention or release gate changes.

## Behavior and boundary

The pinned Textual 8.2.8 table recalculates a whole column when an updated cell is
narrower than its current width. A short restart count can therefore measure all
10,000 retained rows even when the column header remains the widest content.

`FrameTable.update_cell` delegates to the public native update method. It skips
width recalculation only for a single-height row and automatic-width column when
the single-line header exactly determines the current width and both old and new
single-line literal text fit within it. Ordinary repaint still occurs. Growth,
content-determined maxima, multiline content, fixed widths, unknown renderables,
custom measurements and invalid keys retain native behavior.

The original immutable, escaped resource cell is shared as `TableCell` in the
presentation module; `ui.pods.PodCell` retains its constructor alias. The shortcut
requires trusted immutable row contents; additions, column defaults and updates
track that condition through public methods. Mutable/custom content or explicitly
unsized edits select native behavior until all rows are cleared. Unknown renderables
and subclasses are evaluated by the native table at its normal time, preserving
deferred rendering and custom measurement. No private Textual method is replaced.

## Retained initial diagnosis

Two sequential 30-second runs used the same owned paginated HTTP LIST/WATCH
fixture and actual application key queue on Linux 6.8, CPython 3.12.12, six CPUs
and a 100×30 viewport. Both retained 10,000 actual resource rows with normal GC
enabled at its default `(700, 10, 10)` thresholds, no tracing/profiling/coverage,
and no runtime monkeypatch. Each recorded source hashes before/after, individual
cursor/repaint samples, heartbeat samples and actual emitted events. The parent
polled a changed selected UID and awaited the public post-refresh callback; Pilot
idle time was excluded from input latency.

| Observation | Original width work | Initial optimized working source |
| --- | ---: | ---: |
| Actual duration | 30.578 s | 30.158 s |
| Emitted events | 1,070 | 2,010 |
| Actual emission rate | 34.993/s | 66.650/s |
| Navigation samples | 52 | 81 |
| Key to selected UID p95 | 254.413 ms | 143.768 ms |
| Key to post-refresh p95 | 474.092 ms | 224.434 ms |
| Maximum heartbeat gap | 725.641 ms | 181.302 ms |

Original receipts are retained under `artifacts/native50` in the isolated native
and performance worktrees. Their SHA-256 digests are
`03e323cf215efb1184c2771a5962fe9955d122127b9d191cbf1a9ff2c9cc4299`
and `7d0a45bbdca8261ee24836255f3017914ff9155bdda5ff4be6d943c12da9d4e6`.
The independent paired review found exactly one changed production input in this
initial comparison, `ui/presentation.py`; the exact pre-review source is archived.
Subsequent ownership refinement moved the unchanged cell implementation into the
shared module and avoids eagerly casting unknown renderables. These initial
timings are not qualification of that later source.

The API emitter shared the application's event loop, so its attempted 100/s
pacing drifted. Observed snapshot versions also lagged emissions. This records a
hot-path improvement and remaining responsiveness failure; it does not certify
100/s throughput, the input target, combined logs or a memory plateau. Both runs
closed the application/client/watch/render owners and left no active API watches.

## Verification scope

The initial implementation passed 27 native-parity cases in 17.47 seconds, with
39/39 lines and 8/8 branches in the then-affected module. The broader seven-file
table/UI cohort passed 80 cases in 168.64 seconds before ownership refinement.
Both are separately scoped working-source results, not final-head whole-package
coverage or native release qualification. Further checks and source receipts
must qualify the final refined implementation before merge.

## Refined working-source verification

The seven-file table/UI cohort passed 83 cases in 158.45 seconds. Its owned
`final-table-cohort-driver.json` binds all 109 production files, seven selected UI
files and project/lock inputs before and after execution; sources were unchanged.
After a formatting-only change and an additional automatic-height parity case,
the focused cohort passed 39 cases in 36.88 seconds:

```sh
uv run pytest -q tests/ui/test_table_widths.py tests/ui/test_table_rendering.py tests/ui/test_pods.py --cov=kuberich --cov-branch --cov-report=json:artifacts/native50/refined-width-all-modules.json --cov-report=xml:artifacts/native50/refined-width-all-modules.xml --cov-report= --junitxml=artifacts/native50/refined-width-final.xml
uv run diff-cover artifacts/native50/refined-width-all-modules.xml --compare-branch origin/main --fail-under 90 --total-percent-float
```

The affected presentation module measured 52/52 lines and 8/8 branches. All 30
changed executable production lines were covered. These scoped reports include
unimported production modules; they do not establish a new whole-package coverage
floor. Native parity includes object/string keys, pending growth/shrink, removed
maxima, fresh headers, fixed/automatic row dimensions, unknown previous/replacement
renderables and subclasses, wide Unicode, style/resize and native key errors.
The repeated actual 1,000-row case retains native widths while eliminating whole
column reads for header-bounded numeric changes.

Ruff, all 461-file formatting checks, strict application/gate mypy over 111 files
and plan validation passed. Source terminal checks passed three cases in 8.89
seconds:

```sh
uv run pytest -q tests/terminal/test_pods.py tests/terminal/test_standard_resources.py tests/terminal/test_custom_resources.py --no-cov --junitxml=artifacts/native50/width-source-terminals.xml
```

Actual owned APIs/PTYS checked live rows, updates/sorting, scope commands,
discovery/columns/details, small screens, exit and terminal restoration. Source
fixtures remained owned and unchanged; no maintainer context was used.

A separate refined-source 30.295-second diagnosis retained 10,000 rows and emitted
2,100 events (69.319/s), with 81 input samples, 129.154-ms selected-UID p95,
231.658-ms post-refresh p95 and 181.021-ms maximum heartbeat. Its receipt digest is
`69fc6563440b958cbd3a5d8dce85599bb9cd1ade672089b4cdf903f490128a06`.
Independent review matched every recorded source input to the current refined
implementation and verified unchanged source/normal GC/no instrumentation and
closed app/client/watch/render/API ownership. Shared-loop pacing, snapshot lag and
absence of combined logs/memory soak retain the same qualification limits above.
This remains above the input target; Q03 and final-head hosted qualification stay
open.

The aggregate source picker also inherits `FrameTable`, so its full owned UI
cohort was verified independently:

```sh
uv run pytest -q tests/ui/test_aggregate_logs.py --no-cov --junitxml=artifacts/native50/width-aggregate-ui.xml
```

All eight cases passed in 109.97 seconds, including source selection/admission,
retained-history controls, the required warmed runtime/control/replay scenario
and cleanup. This extends affected behavior evidence; it does not complete Q03
or qualify final-head native platforms.

## Native width-invalidation follow-up

A further actual native-parity case reproduced a defect in the initial shortcut:
a caller updated one cell with `update_width=False`, then requested width
calculation on a different short cell. The native table discovered the first
cell's 30-character value; the shortcut incorrectly kept the five-character
header width. Original failure JUnit/logs are retained as
`artifacts/native50/unsized-native-before.*`; that source is superseded.

The final bounded trust flag disables the shortcut after explicitly unsized
edits or mutable/custom content introduced through public row/default/update
methods. Clearing all rows resets it. Unknown renderables retain native evaluation
order, and mutable column-default neighbors cannot conceal growth. A Unicode
line-separator header cannot be mistaken for a single-line measurement. Actual
column-read observations verify the shortcut recovers after clear, and the
1,000-row repeated-update behavior remains bounded.

The correction's focused cohort passed 42 cases in 35.24 seconds, measuring
70/70 presentation lines and 14/14 branches. These results supersede the earlier
52-line module result for this source; full affected UI/terminal and frozen-head
native checks remain required. Earlier resource diagnosis receipts bind their
own exact pre-trust source and are not relabeled as timings of this correction.

## Final trusted-source local checks

After rebasing onto qualified phase preparation merge `b6337977f6e72f8688a9efc3f8e8b875f10b7c4e`,
the complete affected eight-file UI cohort passed **95 cases in 275.400 seconds**,
without failures/errors/skips. The presentation module measured 70/70 executable
lines and 14/14 branches; all **48 changed executable production lines** were
covered. The report inventories all 109 production modules, including those not
imported by this scoped run; it is not whole-package coverage qualification.

```sh
uv run pytest -q tests/ui/test_pods.py tests/ui/test_standard_table.py tests/ui/test_custom_table.py tests/ui/test_standard_resources.py tests/ui/test_custom_resources.py tests/ui/test_table_widths.py tests/ui/test_table_rendering.py tests/ui/test_aggregate_logs.py --cov=kuberich --cov-branch --cov-report=json:artifacts/native50/trusted-consumer-coverage.json --cov-report=xml:artifacts/native50/trusted-consumer-coverage.xml --cov-report= --junitxml=artifacts/native50/trusted-consumer-ui.xml
uv run diff-cover artifacts/native50/trusted-consumer-coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float --format json:artifacts/native50/trusted-diff-coverage.json
uv run pytest -q tests/terminal/test_pods.py tests/terminal/test_standard_resources.py tests/terminal/test_custom_resources.py --no-cov --junitxml=artifacts/native50/trusted-source-terminals.xml
```

The three actual owned source-terminal cases passed in **8.850 seconds**, including
updates, discovery, resize/exit and terminal restoration. The driver retained
unchanged 522-file tracked-source snapshots before/after each cohort, with all
109 production modules and current tests/metadata. The receipt digests are
`ef63087a740153e7b7924d8c23907fed159b9cdc8ecf67c6fd5620fbfce6bfdc`
and `0324561f2c98228238ca8a24fd41fedcc23cd8171b7936ecbda30d7ac528c77e`.
Later acceptance/preview prose does not change the verified production/test source.

Ruff and all 466-file formatting checks passed; the complete configured strict
application/tooling mypy invocation covered 133 files, with a separate four-file
site invocation passing. `uv run python scripts/validate_plan.py` retained 12
epics, 79 tasks, 64 capability families and 26 CLI flags. `uv build` and
`uv run twine check dist/*` passed for the wheel/sdist. Both site build and local
link/digest validation passed (49 pages, 1,726 references, 64 files). These local
checks precede final signed-head native qualification; they do not qualify the
full six-environment release, independent combined workload or public channels.
