# Development CI policy and observed usage: #109

## Scope

The application remains `0.0.1.dev0`. PR #143 selected explicit event-specific
matrices; the resumed observation below verifies their actual hosted behavior.
Every selected job retains its full test, coverage, artifact and security requirements.
See [quality policy](../quality.md) and [release qualification](../release-pipeline.md).
No runner, billing setting, repository visibility or publication is changed.

## Resumed hosted observation, 2026-10-10

Read-only collection retained **227 Application quality runs** and all latest-attempt
job metadata. The frozen listing ends at main run `38080764309`, created at
`2026-10-10T19:40:57Z`; collection finished at `20:04:39 UTC`. Its three original
listing pages are complete and have matching totals and unique run IDs. The
collector's original query cutoff was lost when its repository request used an
incorrect trailing slash. That failed log/source and all original listing pages
were preserved; the corrected collector reused those pages and completed all
227 job queries without errors. No workflow was rerun or dispatched.

[The captured observation](ci-usage-observation-2026-10-10.json) includes run/attempt
IDs, source commits, original-page/job-response hashes, requested labels,
runner assignment, actual status, timestamps and step counts. Full raw responses
remain in the issue worktree under `artifacts/ci109-original-observation/`.
The historical `/tmp` copy was unavailable after the server restart; reconstruction
through main `7734da2` reproduces all published historical values below exactly:
128 runs, 896 jobs, 22 successes, 104 failures, two cancellations, 87 executed
native jobs per OS, 328 native rounded-minute proxies and 28 aggregate proxies.
This verifies the old totals without inventing a recovery of the old files.

The following **99 subsequent runs** include the policy transition and much
larger product/test workloads. At listing time, 35 succeeded, 53 failed, ten were
cancelled and one was active. A failed run stays failed in this observation.

| Completed allocated work | Jobs | Elapsed seconds | Sum of ceiling elapsed minutes |
| --- | --- | --- | --- |
| Native Linux | 190 | 262,033 | 4,453 |
| Native macOS | 47 | 66,514 | 1,132 |
| Linux planning | 64 | 317 | 64 |
| Linux aggregate | 63 | 296 | 63 |

Two allocated Linux application jobs were still active in their captured job
responses; their final duration is unavailable in this snapshot. Thirty-five
unallocated planner nodes, 35 unallocated aggregate nodes and 35 label-free
unresolved matrix nodes are separate. An unresolved matrix has no established OS;
it is not an additional Linux execution. Runner IDs and step presence agreed
for every record. Completed allocated time includes failing/cancelled work.

Calculate each elapsed duration as `completed_at - started_at`, then sum
`ceil(seconds / 60)` for eligible individual jobs. These are elapsed workload
proxies. The available metadata does not establish charged SKUs, discounts or
processing-time adjustments. The before/after windows and test workloads differ;
their totals do not establish a causal runtime or invoice saving.

## Observed matching-source PR and main pair

[PR run 38069099349](https://github.com/carloshm91/kuberich/actions/runs/38069099349)
and [main run 38074322142](https://github.com/carloshm91/kuberich/actions/runs/38074322142)
both completed successfully. Their sources `99aa316` and `498711a` have identical
Git tree `9cd8e31cc904666143ece6c1e5967642d301494b`.

| Event | Native Linux | Native macOS | Planner/aggregate | Elapsed seconds, all jobs | Rounded proxies, all jobs |
| --- | --- | --- | --- | --- | --- |
| Pull request | 3 | 1 | 2 | 7,110 | 123 |
| Main push | 3 | 0 | 2 | 5,084 | 89 |
| Complete pair | 6 | 1 | 4 | 12,194 | 212 |

The seven native jobs account for 12,174 seconds / 208 proxies; the four short
planner/aggregate jobs account for 20 seconds / four proxies. This directly
verifies the adopted development trigger pattern. The former twelve-native-job
pattern is a structural comparison; there is no measured old-policy run of this
same current workload, so a same-workload dollar/runtime saving is not claimed.
The full six-native main dispatch remains mandatory before release.

## Current charging policy and storage evidence

The source repository is public, as independently re-read for this observation.
GitHub documents free compute for public repositories using standard hosted
runners; larger runners have separate charging rules. The current workflow
requests standard `ubuntu-24.04` and `macos-latest` labels. This establishes the
documented charging policy for the current configuration, rather than an account
invoice. See [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
The public-source change was approved separately in #155; #109 changes no visibility.

A fresh filtered request to the documented
`GET /users/carloshm91/settings/billing/usage/summary`, with API version
`2026-03-10`, October 2026, repository `carloshm91/kuberich` and product `Actions`,
returned HTTP 404 with an explicit missing `user`-scope message. The response hash
and request are retained. Permissions were not expanded. Actual gross/net amounts,
discounts, billed SKUs and accrued storage charges remain unavailable.
See [billing API permissions](https://docs.github.com/en/rest/billing/usage).

At `2026-10-10T20:11:37 UTC`, a complete six-page artifact listing recorded
504 unexpired artifacts, reporting 914,135,014 bytes in total. The cache API
recorded 170 active caches / 7,781,635,185 bytes. These current metadata snapshots
do not establish accrued GB-hours or a billed storage amount. Nothing was deleted,
and cache limits, retention, budgets and account settings were not changed.

## Retained failures and engineering qualification

The older post-PR178 main run `38077802296` failed Linux/Python 3.12 with
4,431 passes and one failed aggregate-runtime case. Its positive uninstrumented
child measured **159.900812 ms** during `warm 2 resource route`, exceeding the
unchanged 150-ms maximum-heartbeat bound. Its main-thread CPU was 158.843167 ms;
ordinary generation-2 collection overlapped for 91.284208 ms. This establishes
overlap, not a complete root-cause proof. The child stopped before refill;
the parent's earlier refill assertion obscured the actionable child failure.
Original artifact `11680530630`, job log and independent diagnostic remain retained.
The [D04 finding](https://github.com/carloshm91/kuberich/issues/40#issuecomment-6101596974)
requires investigation before first-public readiness. A later pass does not
establish a source correction, and the failed run is included in the usage totals.

The subsequent original four-native PR #179 run `38078225050` passed and was
independently reviewed before merging as `f5933bb`. Linux passed 4,437 cases per
minor; macOS passed 4,434 plus three explicit Linux-only skips. The measured
minimums were 99.065732% lines / 96.845600% branches over all 109 production
modules, with all 43 critical modules at 100%. These are that frozen source's
measured results. This observation changes no production source and claims no
new application coverage percentage. Changed executable production lines are N/A.

Current merges require the configured hosted matrix and protected aggregate;
the historical local-only exception applies only while its original startup
block actually exists. Keep failures and incomplete platforms explicit.
D04/D06 engineering, six-native release qualification, ownership/OIDC, installed
public channels and approved publication remain their separate delivery gates.

## Observation verification

On Linux/CPython 3.12.12, independent read-only verification compared every
captured row and response hash, recomputed both time windows, checked the
matching pair's Git trees and recomputed complete artifact/cache totals:
227 runs / 1,367 original job rows passed. The report SHA-256 is
`1301671825ec67fd5092b4acf2ae1c2b41c87b1b2bea0b317dfbf88d63bab1f1`.

The focused command
`uv run --no-sync pytest -q tests/quality/test_ci_policy.py tests/quality/test_quality_gate.py tests/quality/test_release_policy.py`
passed **267 tests**. Ruff and formatting passed over 493 files; strict application
and verification-tool types passed over 133 files, and all four site tools passed
strict types. Plan validation passed 12 epics / 79 tasks / 64 capability families /
26 CLI flags. Site build and link/asset validation passed 49 pages / 1,726 references /
64 files. The original logs and independent report receipt are retained under
`artifacts/ci109-*.log` and `artifacts/ci109-independent-observation-review.json`.
These are local documentation/policy checks; the PR's original protected hosted
checks remain required before merge. No production executable lines changed.

## Historical observation, 2026-10-07

Read-only GitHub API queries collected all 128 Application quality runs in October
through main commit `7734da21aaca9fb400f30bb8e1ea0de737eee9aa`, and their latest
attempts' 896 jobs. Workflow conclusions were 22 successes, 104 failures and
two cancellations. Of those jobs, 694 had no allocated runner; they are not
counted as executed minutes. Runner assignment plus actual steps distinguishes
executed work from startup refusal; a failed workflow count alone is not a bill.

| Observed application jobs | Jobs | Elapsed seconds | Sum of per-job rounded minutes |
| --- | --- | --- | --- |
| Linux | 87 | 7,669 | 168 |
| macOS | 87 | 7,588 | 160 |
| Total application matrix | 174 | 15,257 | 328 |

The 28 executed aggregate jobs add 149 seconds and 28 rounded minutes. These
figures describe this workflow's latest attempts, not every account/repository,
earlier attempts, dependency workflows or storage charges. Raw job observations
and calculation inputs are retained locally under `/tmp/kubetrol-109-evidence/`.

GitHub's read-only user billing endpoint returned HTTP 404 with an explicit
missing `user`-scope message. Account scopes were not expanded. Consequently,
gross charges, included discounts, net charges and artifact/cache storage
allocation are **unavailable**. The maintainer's reported account allowance is
context, not a repository-specific invoice. Job elapsed time also does not prove
which billing SKU/rate was charged. GitHub documents per-job rounding, separate
platform rates, shared account allowances and hourly storage accrual:
[runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing),
[Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## Work reduction, with limits

The old PR-plus-merge pattern selected twelve application jobs, six of them
macOS. The new pattern selects seven application jobs, one of them macOS,
plus two short Linux planning jobs. Full six-environment qualification remains
an explicit main dispatch before release. No selected test subset is reduced.

Applying the new selection to the observed historical application jobs while
holding each old duration fixed would retain 106 jobs and 201 rounded minutes,
instead of 174 jobs and 328 minutes. This is a **counterfactual selection**, not
an observed after-change duration or cost saving. It excludes new planner time,
full manual qualification, changing test workloads and billing discounts/storage.
The historical suite was smaller than the current suite, so it is not a runtime
forecast. No dollar saving or exact invoice allocation is claimed.

## Historical private verification, 2026-10-07

Policy tests exercise each event, supported Linux minor/macOS baseline, unknown
events, wrong refs, absent/corrupted/mismatched planner output, failed/cancelled/
skipped dependencies and actual planner-to-aggregate subprocess behavior.
Release tests and owned HTTP transport reject routine/incomplete matrices,
non-dispatch quality runs, wrong commits/repositories, duplicate/missing/skipped
jobs, failed latest attempts and unavailable artifacts. Workflow contracts retain
the required PR event, stable aggregate, full suite, independent floors, actual
kind rehearsals and immutable release-artifact path.

Fresh Linux checks passed: Python 3.12 ran all 437 quality/packaging/source-PTY
cases in 602.63 seconds. Python 3.13/3.14 each passed the 436-case quality/packaging
suite, then all 43 affected installer/distribution/source-PTY cases after the
navigation probe adjustment (264.16/263.46 seconds). These total 437 unique cases
per interpreter across the applicable runs, not 479 different cases. Ruff,
formatting, strict typing over 85 files, plan/link validation, actionlint 1.7.12,
build, Twine and fresh locked/unlocked runtime security verification passed.

Verification code was frozen at `b9956d6c42cfc1341de8de1b3c46f8ad2953a53d`;
the adjusted test helper was frozen at `7806f7c`. Final scripts/workflow trees
remain `641b3f93d9bf8b1a79a04a2284fceba253c70ef1` /
`ec584e67572666def55c6362187156145c43b9db`; the adjusted tests tree is
`df3b4add491b55cae4ea87b58d8735b7585ecef8`.
The fresh distribution audit covers 27 runtime dependencies per scope without
exceptions, binds all 15 policy inputs, and retains its actual original source
SHA `b9956d6` in provenance. Later documentation/test-only commits are not
relabeled as the artifact source. Runtime source remains
`8469c8625227551ed4acb34c2e499c1b91a51af1`; its previously measured coverage is
6,419/6,451 lines (99.5040%), 1,891/1,936 branches (97.6756%), with all 29 critical
modules at 100% of applicable lines/branches. The independent checker passed
against that unchanged inventory. This previous line,
branch and critical-module evidence remains historical evidence rather than
a newly measured application suite. Changed executable production lines: N/A.

The initial Linux/Python 3.12 quality/packaging run had 435 passes and one failure:
the installed uv-wheel PTY probe missed its command-rejection notice while a
context API was deliberately gated, then that gate timed out. Its log and failed
terminal capture are retained. The isolated unchanged case passed; the shared
probe now confirms visible `:ns` entry before Enter, retaining the rejection,
API-gate and terminal-restoration assertions. Fast typeahead in ordinary commands
is still exercised. Fresh verification of the adjusted probe passed as recorded
above; the original failed run is not reported as successful.

At that historical checkpoint, hosted jobs could not start because of the
quota/billing restriction. #109 stayed open for actual after-change observations
and accessible account reconciliation. The resumed observation above now retains
run IDs, runner/step/timestamp evidence, rounded elapsed proxies, planner overhead
and artifact/cache snapshots. Actual billing remains inaccessible. Full supported
platform engineering qualification stays under #40, with protected and approved
publication under #89.
