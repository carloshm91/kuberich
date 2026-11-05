# O02 #69: cluster overview and scoped history

## Implemented behavior

Development source adds the native `:pulse`/`:overview` workspace, independent
per-source availability/time/scope, Node/Pod/workload health, capacity and
configured budgets, current usage, and exact typed drill-down predicates.
Pulse preserves context, namespace, selection, filter, sort and variable-height
viewport through ordinary navigation. Aggregate rows are not mutation targets.

The configured per-context Prometheus Service proxy provides real CPU-rate and
memory-working-set `query_range` reads over 15 minutes at 15-second resolution.
Literal selectors, independent backend-scope labeling, bounded matrices,
numeric values, gaps and 60-second expiry are implemented. No external backend
URL or inferred Kubernetes-to-Prometheus cluster-name equality is introduced.

The source starts from protected main
`ced365fd224d1f6c872fda638f5d7c6d8a1d75c8`, which delivered #68 after 27/27 PR
jobs and then 22/22 automatic main jobs. Those results qualify the metrics
baseline, not this later overview source. Source metadata remains 0.3.0; these
capabilities are unreleased work for 0.4.0. Published 0.3.0 notes and channel
records remain unchanged.

## Scoped verification recorded during implementation

| Component | Actual result and limit |
| --- | --- |
| History/configuration | 107 unit and real-HTTP contract cases passed in 2.45 seconds; history 161/161 lines and 62/62 branches, preference parser 46/46 lines and 22/22 branches |
| History I/O | 49/50 lines and 7/8 branches; only the TYPE_CHECKING import branch was unexecuted; no exclusions |
| Preference reload | Eight new/existing UI cases passed in 6.85 seconds, including held-query retirement, unrelated theme retention and invalid-file fallback |
| Pulse domain/service | Final affected cohort passed 174 cases in 14.01 seconds after source/projection timestamp and controller-generation review fixes; domain 250/250 lines and 88/88 branches, collector 99.03% lines and 91.38% branches |
| Pulse UI | 113 focused cases passed in 19.66 seconds; Pulse table/controller measured 100% line coverage and applicable table branches |
| Existing navigation | 162 regression cases passed in 116.37 seconds |
| App-to-history integration | Actual App → HistoryReader → controlled HTTP Service proxy → chart Pilot passed; values, units, missing samples and unverified backend scope were observed |
| Documentation/reference | 209 focused documentation, website, navigation, exact-history, reference-drift and changelog cases passed in 135.34 seconds; observability fields/defaults are extracted from the real parser AST |
| Startup command contract | 186 cases passed in 1.61 seconds, including direct `pulse`, `overview` and `:pulse` startup without loading a context |
| Verification enrollment | 70 qualification/verifier controls passed in 8.88 seconds; 109 existing CI/aggregate-log controls passed in 4.85 seconds after enrolling the new mandatory cluster trial |
| Static integration | Ruff, formatting, private-access and generated references passed; the actual workflow's strict type-check union passed for 246 source files |

Global source/changed coverage and current-head hosted/native/package checks
still require their actual result. These scoped
measurements are not added together as one suite or relabelled as release
qualification. Original failed focused logs remain retained under
`artifacts/issue69/service/` and `artifacts/issue69/ui/`.

Root history evidence is under `artifacts/issue69/history/`, including
`final.xml`, `final-coverage.json` and `live.xml`. UI evidence is under
`artifacts/issue69/ui/`, including `final.log`, `final.xml`,
`coverage-final.json`, regression results and `pulse-history-100x30.svg`.
Documentation evidence is under `artifacts/issue69/docs/`, including
`focused.log`, `focused.xml`, strict helper typing and plan-validation results.

Review exposed two observable failures that were corrected before qualification:
an inherited Errors-only filter could hide healthy objects behind an exact Pulse
count, and retained capacity/budgets could display a later attempt's timestamp.
The unchanged filter regression now passes; navigation restores the saved filter
state. Projection timestamps now remain at the last actual projection while
read attempts have separate timestamps. Original failed logs remain retained.

The first real owned-cluster trial failed with `TimeoutError` while waiting for
scraped history. Its diagnostic observed a live Prometheus with a connection-refused
exporter target and no history samples. The verifier ran for 230.31 seconds;
cluster/private-directory deletion, unchanged frozen inputs and outer process-group
absence were verified. This failure remains recorded in
`artifacts/issue69/kind-final-1/`; it is not a successful history qualification.

Pinned-image preflight then proved that `httpd` was absent, including the
BusyBox applet. A small fixed HTTP responder using the image's available `nc`
was verified with two actual requests, correct exposition MIME/length and
container-absence proof. The second cluster trial reached at least three
finite points in both history series, then failed an assertion before writing
its numeric receipt. Its 97.22-second outcome remains failed and its exact
assertion is not retrospectively established. Cluster/private-directory and
process-group cleanup and unchanged inputs were verified again. The numeric
expectation and failure-evidence ordering require correction before another
cluster attempt; the retained trial is `artifacts/issue69/kind-final-2/`.

Further owned preflight observed the listener's `nc: timeout` exit before the
first scrape. The fixture now keeps that listener alive for its owned container
lifetime. The pinned Prometheus binary independently reported version 3.15.1.
Its [rate implementation](https://github.com/prometheus/prometheus/blob/v3.15.1/promql/functions.go)
also establishes that a new series covering only part of the five-minute window
can have a rate below the original test's 0.5 lower bound. The corrected oracle
requires positive bounded CPU values, the unchanged exact memory gauge, and
equality with raw Prometheus evaluations at the same settled query timestamps.
It retains the requirement for at least three finite points in both series.
Numeric receipts now precede expectations and each expectation has a recorded
stage. Ruff, formatting, strict verifier typing and eight verifier controls
passed before the next owned trial. Failed local preflight setup/timeout
receipts and their cleanup proofs remain separate; none qualifies the product.

## Bounded collection observation

An owned loopback HTTP fixture advertised 12,000 records in each of eight
resource families. The actual `ResourceReader`/`PulseService.run` collected
35,000 records over 350 serialized requests (16,669,413 JSON bytes), emitting
356 incremental observations. Collection took 6.594 seconds; the first summary
appeared after 17.55 ms. Peak combined retention was exactly 10,000 records and
5,597,500 bytes, within the configured 64-MiB retained-input limit. This is not
a bound on total Python process memory.

Each limited family remained visibly partial and incomplete. Missing current
metrics stayed unavailable with no invented usage. The observed worst delay
over a 5-ms heartbeat target was 20.87 ms; latency is advisory for 0.x and no
threshold was changed. Stale scope was rejected before I/O/publication. The
collector, expiry task, heartbeat, HTTP handlers, API client and private inputs
were drained; retained records/bytes returned to zero and source hashes were
unchanged. The actual result and observer source are retained under
`artifacts/issue69/performance/`. This controlled HTTP observation does not
certify provider latency or a real 96,000-object cluster.

## Successful owned-cluster verification

The corrected actual kind trial passed in 100.88 seconds (101.65 seconds
including the outer process). It verified healthy/degraded/completed/pending
resources, real Node capacity and active-pod budgets, every summary predicate's
API query, missing current metrics, partial RBAC, forbidden Service proxy,
missing Service and an empty Prometheus selector. The pinned Prometheus 3.15.1
genuinely scraped the explicitly synthetic counter/gauge. CPU points were
0.04135, 0.09134999999999999 and 0.14135 cores during the fresh five-minute
window; memory was exactly 1,048,576 bytes. Settled values matched independent
raw Prometheus evaluations at the same query timestamps.

The real App displayed `141.35 mCPU` and `1 MiB`, numeric sparklines and gaps.
Keyboard actions opened the exact pending UID set and active-pod CPU sort;
Escape returned through native Pulse history. The caller's generated kubeconfig
was unchanged, collector/watch ownership drained to zero, frozen inputs stayed
unchanged, the cluster/private directory were deleted, and the outer leader was
reaped with its process group absent. These are local synthetic-exporter
contracts, not real cAdvisor or provider certification.

Evidence is retained in `artifacts/issue69/kind-final-3/`. The report SHA-256 is
`e0ffee1dc4e1e9cbdff2a24bc102b875d8582aa24ac374dbada94b4da92d5911`;
the outer process receipt is
`4ea4176f79d5d3933d86b04cb002f2d5cc76b6d83bebc8048719d5ecc4d8d067`.
The real App screenshot is `pulse-real-prometheus.svg`, SHA-256
`3cc87c50577bdefb78dca241325e3d1f3d653779d5ffa932c67e5901180ad7fb`.
Earlier failures and their cleanup evidence remain separate.

## Initial hosted attempt and fixture correction

PR #311 head `9a94478a7172346054d77e6639369bce0287db2b` ran
[Application quality 41965229953](https://github.com/carloshm91/kuberich/actions/runs/41965229953).
Fifteen source test parts, all four standalone targets, Fast tests and planning
passed. macOS Python 3.12 part 1 failed one existing ambiguous-Job-receipt case
(2,308 passed, six platform skips). The subsequent Application aggregation was
skipped and Quality gate correctly failed. This attempt supplies no complete
application coverage result. Repository validation and DCO passed separately.

The failing case retained its deliberately injected 100-ms timeout for a later
normal `prepare()` GET. The fixture now restores its original read timeout after
the ambiguous write and deliberately delays the follow-up response by 200 ms.
The retained original fixture reproduces the same timeout in 1.37 seconds;
all 52 corrected operation contracts pass in 5.45 seconds. The forced ambiguous
write timeout, unchanged Job name, conflict result and no-duplicate assertions
remain in force. No application deadline or production file changed.

Failed hosted logs and reader cleanup are retained under
`artifacts/issue69/hosted-pr311/`; the macOS job log SHA-256 is
`1758936ba33dede3e4440ffe1855448c8eada4b127b30a4ca5e4bf7462a6d352`.
The controlled reproduction and corrected cohort are under
`artifacts/issue69/ci-timeout-repro/` and `artifacts/issue69/final/`.
All 211 product/verifier inputs from the successful owned trial remain identical.
A new exact-head hosted run must pass; the original attempt remains failed.

## Acceptance still requiring final evidence

- The current source's complete required CI, independent global 90% line,
  branch and changed-line gates, designated critical modules at 100%, installed
  artifacts and native-platform checks.
- Reviewed source identities and cleanup for the exact-head integrated checks.

The live #69 overview-chart criterion is preserved. This implementation supplies
the actual overview slice; #231 remains open for broader entities,
network/filesystem history, ranges and the remaining backend matrix. Neither a
future interface nor a planned provider establishes delivered behavior.
