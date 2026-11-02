# Incremental resource ordering: Refs Q03 #50

The table now reuses its established order when an update changes neither the
selected typed ordering value nor the namespace/name/UID tie, and membership,
context revision and sort selection remain unchanged. Public row add/remove,
clear and native sort operations invalidate the bounded table-owned order marker.
Changes affecting ordering, unknown ages, selection/direction, schema replacement
and interrupted batches retain canonical ordering and stable viewport behavior.
This does not cache a growing list of snapshots or alter generation rejection.

Pod ordering shares its actual typed value with the incremental decision: readiness
fractions, case-folded strings, numeric restarts and known/unknown timestamps keep
the existing semantics. Standard and generic resource views use their selected
column's actual typed value. A changed display string can remain in the same
position while still repainting. No private Textual method is replaced.

## Actual behavior evidence

On the frozen prior source `709bce48e51415b540175ec123e149d2eea9f46b`, the
three actual 1,000-row Pod/standard/generic cases each observed ten full-list
ordering calls for ten unrelated numeric edits. Their expected-failure logs/JUnit
are retained as `artifacts/native50/sort-before-corrected.*`. A preceding launcher
failed fixture import before collection; that is a harness startup error, not
behavior evidence. The current working correction passed 75 focused UI/domain
cases in 15.42 seconds. The critical Pod domain measured 131/131 lines and all
48/48 branches. Three further semantic cases verify equal readiness fractions,
status casing and the distinction between an epoch timestamp and unknown age.

Behavior comparisons check actual ordering, displayed cells and retained
selection/viewport across 1,000 rows, active ascending/descending numeric edits,
stable ties, unknown ages, native reorder, addition/removal, empty/revised data,
sort input during yielding batches and accepted recovery after aborted updates.
Broader affected and final-head native checks remain required.

## Resource-only paired diagnosis

Two separately paced, 30-second owned resource-only diagnoses use the same
source/controller/support inputs on Linux 6.8, CPython 3.12.12, six CPUs and a
100×30 viewport. Each retains 10,000 dated Pods, normal default GC, no tracing,
profiling or coverage and unpatched application dispatch. Independent review
found exactly the four intended production inputs changed; all 161 inputs stayed
unchanged during each run. App/client/watch/render/API/source-process owners closed.

| Observation | Frozen width candidate | Working order correction |
| --- | ---: | ---: |
| Duration | 30.452 s | 30.182 s |
| Independently produced events | 3,034 | 3,013 |
| Selected-UID p95 | 96.202 ms | 96.253 ms |
| Post-refresh p95 | 165.792 ms | 159.318 ms |
| Maximum heartbeat gap | 158.498 ms | 148.170 ms |
| Last observed snapshot version | q03/2065 | q03/2074 |

Raw sample/source receipts have SHA-256
`1017fb646a7332cef7172e6b27d4069833b75b5e7d0d85fa1829f49b0378493e`
and `5ffa749464f7d2626086a8faa0424f56fd7791132dc1e9c45354b0445898095c`.
These observations do not establish a statistically qualified speed improvement
or meet the input-to-paint target. Source sends and snapshot reads are separately
bracketed, so lag is not atomic evidence of dropped events. A public callback
calibration on the prior source measured approximately 164 ms both when registered
before and after observing the changed UID; merely moving callback registration
did not remove the delay. A separate profiling diagnosis remains instrumented,
with nonqualifying timings and retained raw pstats.

Q03 remains open for combined 100 resource events/s and 2,000 logs/s, a supported
10,000-line retained history, p95 input-to-paint below 100 ms, the 30-minute memory
plateau and context/slow-consumer/forward lifecycle checks. No gate, workload,
version, dependency or publication policy is weakened by this partial correction.

## Complete local affected cohort

The complete affected UI/domain cohort passed **173 cases in 293.326 seconds**,
without errors/failures/skips. Actual source-terminal checks passed **three cases
in 8.955 seconds**. Each driver receipt binds unchanged 524-file tracked-source
snapshots before/after; final acceptance/preview prose is the only later change.
All 109 production modules are present in the scoped coverage inventory.

The critical Pod domain measured 131/131 lines and 48/48 branches; shared table
presentation measured 81/81 lines and 14/14 branches. The standard table measured
161/161 lines and 40/40 branches. All **43 changed executable production lines**
against the frozen width source were covered. These are affected-source results,
not a new whole-package/native release coverage claim.

```sh
uv run pytest -q tests/ui/test_pods.py tests/ui/test_standard_table.py tests/ui/test_custom_table.py tests/ui/test_standard_resources.py tests/ui/test_custom_resources.py tests/ui/test_table_widths.py tests/ui/test_table_rendering.py tests/ui/test_aggregate_logs.py tests/ui/test_table_ordering.py tests/unit/test_pods.py --cov=kuberich --cov-branch --cov-report=json:artifacts/sort50/order-consumer-coverage.json --cov-report=xml:artifacts/sort50/order-consumer-coverage.xml --cov-report= --junitxml=artifacts/sort50/order-consumer-ui.xml
uv run diff-cover artifacts/sort50/order-consumer-coverage.xml --compare-branch 709bce48e51415b540175ec123e149d2eea9f46b --fail-under 90 --total-percent-float --format json:artifacts/sort50/order-diff-coverage.json
uv run pytest -q tests/terminal/test_pods.py tests/terminal/test_standard_resources.py tests/terminal/test_custom_resources.py --no-cov --junitxml=artifacts/sort50/order-source-terminals.xml
```

Original driver receipt digests are
`cfba21b9be2c020ed2005d790d25268d345be735aa8ac6311c7eed527dab3320`
and `d6e4379044d962cb18556e53d1543af6fe1da4aee5d082929c4700c7e54a7ada`.
Ruff/all 468-file formatting and configured strict application/tooling mypy over
133 files plus four site files passed. Plan validation retained all 12 epics,
79 tasks, 64 capability families and 26 CLI flags. Wheel/sdist build and Twine
passed. Both static-site builds and link/digest validation passed with 49 pages,
1,726 references and 64 files. These are local preparation checks before
signed-head hosted qualification.
Q03's combined workload, input/memory targets and full release scope stay open.

## Original frozen-head development qualification

[PR #175](https://github.com/carloshm91/kuberich/pull/175) merged as
`26ba91e5f03e04818fdc0c9343c2ae43b56a8832`. Signed source
`640159424b6adfcb8c20ea578df5b876d9aafb65`, actual tested PR checkout
`efc84a986d3bf05ebd2c0d9698e79d724c16dca6` and squash share tree
`9d61dc98e4b9bad43bf093a7056ac1aefc5f7059`. All eight required checks passed.

[Application run 38033288908](https://github.com/carloshm91/kuberich/actions/runs/38033288908)
passed **4,246 cases in each** of the four development environments. Independent
original reviews matched all 109 production modules and all 111 payload files
per distribution. Whole line/branch minima were **99.0920% / 96.8856%**; all 43
critical modules and all 43 changed executable lines met 100%. Pinned compiler/
parser checks matched original 3.12/3.14 presentation inventories exactly.
Original runtime coverage/control, isolated installers, terminal restoration,
dependency audits and configured owned-cluster evidence were verified.

[Repository run 38033288905](https://github.com/carloshm91/kuberich/actions/runs/38033288905)
matched 140 source inputs and 63 payloads. All 49 desktop and 49 mobile pages
passed with no accessibility violations, browser errors or external requests;
npm audit reported zero vulnerabilities. This qualifies the development
correction, not Q03 or the full six-environment release. No tag, package, tap/
organization or new site/DNS was published.
