# Historical metrics acceptance

Issue: [O08 #231](https://github.com/carloshm91/kuberich/issues/231), milestone
v0.4.0. Protected baseline: `5444b7d9c357d389243147a978cc20b248293edb`.
The later protected-base integration is recorded below. This is an active
implementation record, not whole-source or release acceptance.
Publication remains a separate authorized task.

## Boundaries

- Five entity scopes, four measurement families and seven 15m–24h ranges use
  fixed queries, numeric values, explicit source states and finite collection.
- Service proxy and external HTTPS use distinct credential/transport owners.
  Detection and backend selection are explicit; source and historical-identity
  gaps remain visible rather than becoming zero or a parity claim.
- Context/scope/target/configuration revisions reject late work. Removed screens
  remain owned through cancellation; export review retains the detail claim.
- Actual native provider availability must be distinguished from controlled
  synthetic exporter/query evidence. No ambient/customer context is permitted.

The adopted plan, interface contract and 57-pin source revalidation are retained
under `artifacts/issue231/planning/`. The implementation decision is
[ADR 0039](../../adr/0039-context-owned-metric-history.md). User guidance is in
[cluster health/history](../../cluster-overview.md).

## Evidence in progress

The frozen domain cohort passed 273 cases, with exact 100% lines and branches in
all three deterministic modules. Its source hashes, original failures, query
vectors and strict/static results are in `artifacts/issue231/domain/receipt.json`.
Vectors describe generated query profiles; they do not prove provider execution.

The integrated UI cohort passed 21 cases in 42.88 seconds, exercising the five
scopes, regular/init/sidecar/ephemeral containers, seven ranges, family/device
selection, configuration reload and actual export review. Source PTYs passed at
100×30 and 40×12 in 18.36 seconds, with literal navigation, API audit controls,
resize/back/quit and exact terminal restoration. The subsequent strengthened
source-hash replay is recorded separately; these earlier results do not qualify
later edits. Raw synthetic ANSI stays private in ignored artifacts.

Root action/catalog/key/qualifier/CI tests passed 250 cases after correcting the
property fixture's obsolete safe-key set. The original 240-pass/one-failure
result is retained in `artifacts/issue231/root/static-02-original-failure.json`.
New explicit regressions require a per-history override when a shared `b` or `1`
navigation key conflicts with chart controls. The parser's rejection rule and
quality floors were not weakened.

Actual provider trials, installed console/module PTYs, final complete production
coverage, changed-line coverage and exact-head protected CI are still pending.
Do not close this issue from these focused results alone.

## Reproduce focused source trials

```sh
uv run pytest tests/unit/test_history.py tests/unit/test_history_queries.py tests/unit/test_history_membership.py
uv run pytest tests/unit/test_history_workspace.py tests/unit/test_history_http.py tests/contract/test_history.py tests/contract/test_history_http.py
uv run pytest tests/ui/test_history_screen.py tests/ui/test_history.py
uv run pytest tests/terminal/test_history.py
uv run pytest tests/packaging/test_distribution.py -k installed_metric_history
```

The separate provider verifier is `python -m scripts.verify_history_kind`, using
an explicit checksum-verified kind binary and a fresh evidence directory. Its
receipts bind the chart archives, locked dependencies, rendered manifests,
container digests and measured application source. A prepared inventory is not
an executed cluster result. Preserve original failures before corrections.

## Integrated lifetime and installed checkpoints

The final independent action-owner cohort passed 26 cases in 27.24 seconds on
257 unchanged source/configuration bindings. `HistoryActions` measured 198/215
lines (92.09%) and 66/70 branches (94.29%) with no exclusions. It exercises actual
Pulse collection, owned HTTP cancellation, retained screen drainage, captured
scope generations and genuine parent cancellation. The actual App/export-overlay
regression reproduced backend reload permanently invalidating Pulse history;
the corrected reload keeps the detail claim and health owner alive. Original
failure and exact post-fix evidence remain in `domain/actions/receipt.json`.

Node detection had a separate reproduced failure: a cluster-scoped Node target
has no resource namespace even when a namespace is selected in the header.
Detection now uses a separately selected namespace; host metric queries remain
cluster-scoped. The original actual-App failure, one fixed actual-App case and
three focused compatibility cases are in `ui/node-detect-receipt.json`.

Fresh outside-checkout installed wheel console and module entry points both
passed in 26.24 seconds. Their source hashes, wheel SHA-256, API audits and exact
terminal restoration are retained under
`artifacts/issue231/root/installed-01/terminal/`; the bounded runner reaped its
child and recorded the process group absent. These are Linux Python 3.12 local
checks, not hosted/macOS/native release qualification.

The existing Pulse regression cohort initially passed 200 cases and failed two
outdated fake backends before their proxy handlers were reached. It retained
`root/pulse-01.log` and JUnit. Those fixtures lacked newly required Service
discovery/UID reads and treated contributor probes as ordinary metric values.
Both corrected regressions passed in 3.42 seconds with unchanged five-second
deadlines; `service/pulse-fixtures-001.xml` retains their result. The preserved
assertions cover numeric samples, gaps, scope, held-query cancellation and theme
versus valid/invalid configuration reload. Production bytes were unchanged.

The frozen actual-provider verifier is now running against one owned kind
cluster with checksum-verified kind/kubectl and pinned charts/images. Its result
remains pending; preparation and startup alone do not establish acceptance.

The first real provider trial failed before installation: a chart includes a
`kube-system` object, while the verifier passed the fixture namespace to mixed
manifest apply. The 45.09-second original remains in `root/kind-001/`; inputs
were unchanged, the cluster/private directory were removed and the owned runner
reaped its child with the process group absent. The verifier now preserves
explicit namespaces, supplies the fixture namespace only for unqualified objects
and omits the namespace override only for apply. An exact argv/environment and
mixed-manifest regression passed among eight verifier tests. The fresh second
trial is separate; the original failure is not relabelled.

Read-only triage found the second trial's initial 24h cluster no-data result
consistent with a new backend's aligned grid: its 120-second end was 05:28:00Z,
while the first positive warmup observation was 05:29:46Z. The exact first scrape
time was not independently established. The preceding short-range
CPU/memory chart contained real values; 15m–3h collections retained both sources,
6h/12h retained memory and 24h had no sources yet. Shared CPU/memory/membership
QuerySpecs are identical between two-family and four-family requests; query/read
budgets were not exhausted. This observation remains no data rather than an
invented value or a relaxed assertion.

## Complete local application attempt

The fixed production source cohort selected all unit, contract, UI, terminal and
packaging tests: 8,431 passed, five failed and four skipped in 1,249.19 seconds.
The bounded runner reaped its child and verified its process group absent.
The original JUnit/log, raw coverage and runtime children are preserved under
`artifacts/issue231/root/application-01/`; this attempt remains failed.

Two navigation fixtures still used the newly reserved common `b` binding. One
now supplies the documented history override; the legacy migration fixture uses
an otherwise valid shared key without changing its migration assertions. All
129 related cases passed. With that meaningful append, independent production
coverage measured 31,593/32,050 lines (98.5741%) and 9,540/9,996 branches
(95.4382%) across all 252 modules. All 104 critical modules reached exact 100%;
changed lines measured 97.07%. These floors passed separately, while runtime
qualification remains failed because the successful aggregate-runtime outer
receipt is absent.

Three export-workflow failures require investigation before delivery: the large
retained-log instrumented preview missed its unchanged five-second readiness
wait; an aggregate window transition accessed a removed frame; the offline
artifact browser retained header-width columns and truncated its filename at
100×30. Original cleanup receipts are preserved. A single pure 5,000-record
profile found unnecessary full-preview paging: 2.55 million per-character encode
calls generated ten pages only to keep the first. Its 9.18-second CTracer/cProfile
observation includes profiler overhead and is not a latency qualification.
Read-only investigation and controlled regressions must establish corrections;
coverage percentages do not waive these failures.

The reset verifier follow-up retains the original unknown cause, adds explicit
endpoint readiness/port/scrape contracts and records per-provider observations
and bounded diagnostics. All reset checks now precede long native warmup with
the original 180-second deadline. Fourteen focused verifier tests and static/type
checks passed. A fresh actual trial is pending after application regressions.


## Protected export-fix integration

The prepared four-commit feature was integrated onto protected main
`c6fba0521777bd0a75f660543b0b37e25ad2b258` after PR #318 delivered the independent
export corrections. Integration source `07ebfe0` preserves all four protected
production fixes byte for byte and all 23 feature production files from the
prepared `c3129f2` source. The only merge conflicts were the maintained checkpoint
and two neighboring installed-test additions; both artifact geometry and history
console/module contracts remain enrolled. The fresh isolated environment resolves
the package from this integration checkout.

All 273 deterministic history cases pass in 16.65 seconds, with exact 100% lines
and branches in history (424/116), queries (323/168) and membership (73/40).
The isolated report retains all 252 production modules without exclusions; these
three-module results do not replace complete-source coverage. The six-file
history/Pulse/live-preferences UI group passes 90 cases in 47.39 seconds. A
history export-roundtrip input now waits for public browser refresh and an actual
visible/enabled hit target before asserting real mouse delivery, preserving its
saved numeric, sanitization, lease, view and copy assertions.

The adapter/workspace/configuration/provider-verifier cohort passes 123 cases in
5.52 seconds; the complete strict target union passes 300 source files. Ruff and
formatting pass. Fresh source history PTYs pass both terminal sizes in 18.14
seconds, and outside-checkout installed console/module PTYs pass in 26.11 seconds,
with owned source bindings, API audit controls, resize/navigation, terminal
restoration and process reaping retained. These are focused integration checks.
The fresh actual three-provider kind trial and complete source/platform gates
remain separate requirements. No package, tag, tap or website publication is
implied.


## Three-provider reset observation

The fresh `kind-003` run on source `0925940`, verifier `5e0933`, failed its
unchanged 180-second Thanos reset-readiness wait. Its final record confirms the
owned cluster and private directory were deleted, inputs were unchanged and the
runner/process group were reaped. The measured verifier stage lasted 299.27
seconds; chart preparation and runner lifetime are recorded separately. This
failed trial remains unqualified.

Prometheus and VictoriaMetrics observed positive reset counts and passed their
rate controls. Thanos returned fresh counter values with nine observed wraps
across roughly 178 seconds, a constant gauge of 42, and zero from every recorded
`resets(...[1m])` query. Its source Pod remained ready without restarts, its
scrape target was up and the loopback/Service-DNS observations matched. Sequential
readiness did not simply miss a single reset: the fixture wraps every 20 seconds.
The earlier `kind-002` provider failure remains unattributed because that run
lacked this provider-specific evidence.

Pinned [Thanos query selection](https://github.com/thanos-io/thanos/blob/v0.42.5/pkg/query/querier.go#L239-L257)
routes `resets()` through counter aggregation. Its
[iterator implementation](https://github.com/thanos-io/thanos/blob/v0.42.5/pkg/query/iter.go#L129-L155)
applies reset correction and records the resulting
[upstream limitation](https://github.com/thanos-io/thanos/issues/3644).
That stage precedes deduplication, so disabling deduplication alone is not a
valid correction. The pinned source manifest is retained separately from the
actual provider receipts.

The verifier correction must prove a decrease within one bounded, correctly
identified raw sample series in the current one-minute window, retain the
reported `resets()` diagnostic, and require the unchanged positive bounded
production-profile rate afterward. Prometheus/VM still require their positive
reported reset count; Thanos's known zero cannot substitute for raw reset proof.
The original window, 180-second deadline, provider request parameters, response
bounds and cleanup requirements remain in force. Fresh execution is required;
source review and the failed run do not qualify the corrected verifier.


## Raw reset-proof verifier

The corrected verifier uses the same instant API with an explicit evaluation
`time` and a one-minute range selector for the synthetic counter. A pure parser
requires an exact matrix/metric/fixture identity, unique bounded label sets,
strictly increasing finite timestamps within `(time−60, time]`, a latest sample
at most 30 seconds old, at most eight series and 64 samples per series, and
bounded finite nonnegative values. It detects an adjacent decrease within one
series from the current response, never across series or polling attempts.
Thanos's hintless selector follows its raw-chunk fallback rather than the
reset-normalizing counter iterator; this is not an explicit `Aggr_RAW` request.

Every provider must supply that raw reset witness and a gauge. Prometheus and
VictoriaMetrics additionally retain the positive reported-reset requirement;
Thanos's valid zero stays recorded as an unsupported diagnostic. The unchanged
provider-specific rate function/options must produce `0 < rate < 10` before
readiness is admitted. A legitimate initial `18→0` pair can still have zero
corrected increase: valid empty/zero rates therefore remain unready inside the
same 180-second loop, with fresh raw evidence required on each attempt.
Negative/nonfinite/oversized values and protocol/transport failures still fail;
no window, deadline or production query code changes.

All 70 focused verifier cases pass in 0.66 seconds, including monotonic raw
false positives, cross-series/attempt mixing, wrong/stale/future/oversized data,
zero-rate startup, rate bounds and request-parameter controls. Ruff, formatting
and strict verifier typing pass. Independent review found no remaining material
issue in verifier `6c3612f2dc9eac12211c7ad0728bc611e8e3ea504ec5d2d1bd835be7b7b4ba7b`
and test source `ce728cab9ca1f4d82dfa6d14654a19ef8e1c413f099d0a18e3c58c74d017dd38`.
Those results qualify the correction's local contracts; fresh owned-provider
execution remains required.
