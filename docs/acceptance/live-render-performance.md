# Owned workspace projections and row repaint: Refs Q03 #50

The owned workspace avoids repeating identical header/status/empty-state text
updates. Its bounded per-label projection includes plain text, spans, base style,
justification, overflow, wrapping, end and tab size. Rich Text equality alone
ignores base style; an initial local test exposed that mistake before publication.
Inherited native updates, unknown renderables, Text subclasses and external
content mutation retain native behavior. Identity/theme changes still repaint.

Pod/standard/generic tables skip wide value equality for identical immutable
projection rows. Distinct equal values remain equivalent; actual typed changes
still repaint, reorder when needed and preserve the viewport.

Owned resource tables opt into native row-region repaint after an immutable
header-bounded edit. The public native cell/cache update still runs; a temporary
public refresh guard replaces only its whole-widget repaint with the native
public row refresh. The guard resets on failure. Unknown/mutable content, width
changes and fixed rows/columns keep full native repaint. General FrameTable users
retain full repaint by default. No private Textual method or geometry/cache
counter is replaced.

## Local behavior and diagnosis

The focused owned-source cohort passed **53 cases in 27.09 seconds**: width parity,
reused/value-equal/changed rows, literal/styled/mutated labels, all public Text
rendering attributes, identity/theme changes and native pixel comparisons after
scroll/resize/fixed cells. The two-table pixel fixture compares equivalent focus
states; its initial unequal-focus comparison was a fixture failure. Broader
affected, terminal and frozen-head native qualification remain required.

Separate 30-second resource-only diagnoses retain 10,000 dated Pods and an
independently paced 100 events/s source on Linux 6.8/CPython 3.12.12, six CPUs,
100×30 viewport, normal GC and no coverage/tracing/profiling. Earlier working
sources retain their own inventories; their timings are not relabeled as later
source measurements.

An actual CLI/PTY pair with identical source/controller/support inputs except
the intended presentation module measured **202.804 ms** input-to-observed-paint
p95 before scoped row repaint and **140.550 ms** after. Both completed normal
application exit, native terminal attribute/reporting restoration and source
process shutdown, with zero API watches after close and no source overflow.
Those are single observations, not a statistically qualified speed claim or
complete Q03 success. A headless public post-refresh diagnosis of the same
pre-opt-in working correction measured 116.522 ms p95 and a 98.520-ms maximum
heartbeat gap; observed resource version still lagged the independent source.

The final owned-source actual CLI/PTY diagnosis passed normal cleanup/restoration
over 30.290 seconds with 101 observations, measuring **143.156 ms p95**. Its
before/after source inventory is unchanged; this still exceeds the target.

The terminal observer archives the ordered raw byte stream to owned disk while
keeping a bounded in-memory tail. It retains an actual bounded prefix for the
unchanged short-harness entry checks and validates real final restoration.
Initial observer failures (fixture namespace mismatch, the short functional
harness's 2-MiB transcript bound and discarded-prefix verification) are retained
separately. They are not product timing qualification or raised test limits.
The ordinary functional harness and its bounds are unchanged.

Q03 remains open for input p95 below 100 ms, sustained combined 100 resource
events/s and 2,000 logs/s, supported 10,000-line retention, the 30-minute memory
plateau and context/slow-consumer/forward lifecycle checks. No workload,
timing/coverage gate, dependency, version or publication policy is weakened.

## Complete affected source verification

The complete cohort passed **224 UI/domain cases in 481.05 seconds** and **ten
actual owned source-terminal cases in 31.67 seconds**, without failures/errors/
skips. Both driver receipts bind unchanged 528-file tracked inventories before/
after, including all 109 production modules. Later acceptance/preview prose is
the only source change following those tests. The critical Pod domain measured
131/131 lines and 48/48 branches; shared presentation measured 96/96 lines and
18/18 branches, and both resource tables covered every line/branch.
After rebasing only the owned correction onto the actual #175 squash merge,
all **47 changed executable production lines** were covered. Production/test
content is unchanged by that rebase; earlier mixed-ancestry diff output is not
used as the correction's changed-line result.

Driver receipt SHA-256 values are
`468a18204f60bff1efe19242857762b14cd83eb04db9637ece077ebd1bba9d97`
and `9c8c6e83b244c9db2fcb0fb52a4aa79863a089c18388d3e41d4ebea6c1276abc`.
Exact argument vectors, XML, source inventories and scoped coverage remain in
`artifacts/render50/render-*-receipt.json`. These are affected-source receipts,
not whole-package/native/release qualification. Required hosted checks remain
for the signed candidate; no intermediate maintainer trial is requested.

Ruff/all 472-file formatting, configured strict application/tooling types over
133 files and four site files, plan validation, wheel/sdist build/Twine and both
site build/link/digest checks passed (49 pages, 1,726 references, 64 files).

## Original frozen-head qualification

PR #176 head `950f7840d03a0e7748bca46473b4bd45788e21bf`, tree
`a3017db90644914e72704aac8c95b7f4d868c5dc`, run `38036838862` remains unmerged.
Independent original artifact review verified all three Linux interpreters:
4,268 cases each, all 109 production modules, 43 critical modules and 47 changed
executable lines at 100%. Minimum whole line/branch coverage was 99.0944% /
96.8662%; all 111 wheel/sdist payloads, audits, isolated install receipts,
runtime replay and native terminal evidence matched frozen Git bytes.
Compiler-specific presentation statements matched the original 3.12/3.14
coverage data (96/94, with pure annotation lines 21/22 accounting for the difference).

The original macOS job failed at 165.123 ms during round-two full-history input
preparation against the unchanged 150-ms aggregate runtime budget; 4,267 other
cases passed. Its original ZIP/source/heartbeat/log evidence is retained, and
the aggregate Quality gate correctly failed. Three Linux passes do not qualify
this candidate. [Watch pipeline evidence](watch-pipeline-performance.md) preserves
the failure identifiers; [bounded input preparation](aggregate-input-preparation.md)
records the subsequent fixture correction and its limited local evidence.
