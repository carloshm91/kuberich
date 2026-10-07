# Private CI policy and observed usage: #109

## Scope

The application remains `0.0.1.dev0`, with the previously installed Linux preview
unchanged. This change selects explicit event-specific matrices and preserves
every selected job's full test, coverage, artifact and security requirements.
See [quality policy](../quality.md) and [release qualification](../release-pipeline.md).
No runner, billing setting, repository visibility or publication is changed.

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

## Verification and remaining evidence

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

Hosted jobs still cannot start because of the quota/billing restriction. #109
stays open for an actual after-change hosted observation and, when accessible,
account usage reconciliation. Once jobs resume, retain run IDs, each job's actual
runner/steps/timestamps, rounded minutes, planner overhead, artifact retention
and the account's recorded SKUs/gross/discount/net amounts. Compare matched
workloads and include manual qualification separately; never equate a rejected
startup with a successful zero-cost test. Full supported-platform qualification,
protection and approved publication remain #40.
