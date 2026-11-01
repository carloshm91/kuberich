# M04 #46 resource operation acceptance

## Frozen local qualification and delivery status

Local qualification completed on 2026-10-08 at
`f447bc1dea6042359f67f226a47bb7cd5fe09361`, based on public-source main
`d9587f1550baea3fecc34986bed81263c70cc707`.
The qualified production tree is `c9dec27df860f65b53e3a2b7d59c2653214a485c`,
test tree `73cb15c47b09403ab26b3941824f7301ba0c9dc4`, and verifier/script tree
`8dedf781ad12845c99fda553326a34319bebbdbd`.

Prerequisite #157 / PR #158 corrected the native verification defects and merged
with all required Linux/macOS checks passing. This issue requires qualification
of its own rebased delivered head before merging; actual final results and
commit pins are retained in #46 and its linked PR. The initial local evidence
below does not establish native macOS or complete release certification.

## Whole-application gates

Each isolated Linux checkout ran the full suite, with no failures or skips.
Inspection of the retained pytest headers established that all three used
CPython **3.12.12**: `uv run` honored the project `.python-version` and recreated
the two environments originally intended for 3.13/3.14. Directory labels are not
interpreter evidence. These are three actual 3.12 runs, not a supported-version
matrix. Actual 3.13/3.14 qualification belongs to the delivered candidate's
required checks, retained separately in #46 and its linked PR.

| Retained checkout | Actual CPython | Passing cases | Pytest duration |
| --- | --- | --- | --- |
| python312 | 3.12.12 | 3,150 | 2,017.08 seconds |
| python313 | 3.12.12 | 3,150 | 2,019.96 seconds |
| python314 | 3.12.12 | 3,150 | 2,015.08 seconds |

The exact command was
`uv run --locked pytest --cov=kuberich --cov-branch --cov-report=xml:artifacts/qualification/coverage.xml --cov-report=json:artifacts/qualification/coverage.json --junitxml=artifacts/qualification/pytest.xml`.
Separate worktrees and environments retain the logs, JUnit and coverage reports
under `artifacts/operations-46/matrix/python312`, `python313` and `python314`.

All three runs passed the independent coverage gates over **94 production modules**:
**9,312/9,379 lines (99.2856%)** and **2,643/2,718 branches (97.2406%)**.
Every one of the **35 critical modules** reached 100% lines and applicable
branches, including `domain/operations.py`. No source or branch exclusions were
added. Changed executable coverage against the exact main base passed at
**566/570 lines (99.3%)**. Coverage is evidence of exercised code, not a proof
that arbitrary clusters, hardware or future dependencies cannot fail.

Ruff, formatting (377 files) and strict mypy (112 checked source files) passed.
Both distribution builds and Twine metadata checks passed. The audited locked
and fresh installed runtimes each contained 27 dependencies with no accepted
vulnerability exceptions; the exact-artifact supply-chain gate passed.

| Candidate artifact | SHA-256 |
| --- | --- |
| `kuberich-0.0.1.dev0-py3-none-any.whl` | `4ecb4819bad074564d0527c5afcf24308c048403367dac3dc204d3eee6168f7e` |
| `kuberich-0.0.1.dev0.tar.gz` | `ff8ab7faacdaa35a938108a652545e9ae05ec8b6c422e02356ca5540bb44723e` |

Artifacts, audits and digests are retained under
`artifacts/operations-46/qualification/f447bc1`. Nothing was published as a
package, release or tag. The development version remains `0.0.1.dev0`.

## Actual HTTP, UI and terminal behavior

The contract suite uses real owned HTTP/TLS endpoints for UID/resourceVersion
preconditions, mixed RBAC outcomes, finalizers, stale/replaced objects, wrong or
oversized receipts, creation conflicts, cancellation and dropped responses.
An actual applied-but-disconnected DELETE proves exactly one request: public
HTTP middleware suppresses the client's implicit connection replay and retains
an uncertain result instead of issuing another write.

Pilot forms exercise single/batch selection, no default batch selection, exact
`DELETE <count>`, invalidated options/review, default Cancel, separate Confirm,
read-only mode, context closure and retained per-item results at 40x12 and 100x30.
Snapshots are retained in each checkout's `artifacts/ui/operation-*.svg`.
Native source and fresh-wheel PTYs cover deletion and manual Job creation from
both console and module entry points, resizing, history and terminal restoration.
The 100-target history witness preserves the last result beyond a single bounded
display chunk. Confirmed operations remain owned after their modal closes.

## Three consecutive owned-cluster rehearsals

The frozen checkout completed **three consecutive contract rounds** (672 cases
each) and **all nine real Kubernetes rehearsals in each round**, as required
after the shared client write-path change. Each round includes contexts,
lifecycle faults, shells, port forwards, guarded mutations, editing, workloads,
resource operations and the exact installed-wheel quickstart. All **30 stages**
(three contract rounds plus 27 cluster verifiers) returned status 0.
Round durations were 636.327, 617.840 and 633.467 seconds.

The operations verifier established all 13 checks in every round: Foreground,
Background/grace-zero and Orphan/grace deletion, finalizer retention, same-name
replacement and version refusal, mixed successful/denied/pending batch outcomes,
CronJob and Job suspend/resume, actual manual Job completion, duplicate-name
refusal, denied Job creation, read-only refusal and caller-config invariance.
Each verifier removed its own cluster and verified absence. Existing unrelated
clusters were preserved; no trial used the maintainer's active context.

The exact operation command, with N=1,2,3, was
`uv run --locked python -m scripts.verify_operations_kind --kind /home/develop/projects/personal/kubetrol/artifacts/operations-46/tools/kind --evidence /home/develop/projects/personal/kubetrol/artifacts/operations-46/qualification/f447bc1/repeat-N/operations.json`.
Per-stage commands, durations, exit statuses, source/tool/wheel digests and logs
are retained in `repetitions.json` and `repeat-N/`; UI/terminal/cluster artifacts
were archived after every round. Verified tools were kind 0.33.0 and kubectl
1.36.4, with the image/tool digests recorded in integration-testing.md and the
actual JSON reports. Kubernetes evidence is for the pinned 1.36.4 owned cluster.

The updated local site also passed both builds/link checks (39 pages, 54 files,
1,154 references) and real Chrome/Playwright/axe checks with zero automated
accessibility violations. It remains unpublished.

## Limits

After rebasing onto corrected main `b1241827ef9a69fe3077ff947a6a1c2897009242`,
the checkout passed **186 focused operation/mutation/terminal cases** in 35.43
seconds on Linux/CPython 3.12.12. All **13 actual owned-kind operation checks**
passed again, including permissions, finalizers, replacement/version guards,
independent batch outcomes, CronJob manual creation and suspension. The cluster
was deleted and its absence verified. Ruff, formatting (380 files), strict
typing (112 source files), planning and whitespace checks passed. These focused
results do not replace the complete current-head PR and exact-artifact gates;
their final evidence remains with #46 and its linked PR.

Deletion acceptance is distinct from observed removal; neither establishes all
dependent/storage cleanup. Finalizers are never removed. Batch operations have
independent outcomes and no rollback. Source CronJob revalidation and Job creation
are separate API requests; manual Jobs do not enforce scheduled concurrency.
Cloud/provider trials, broader Kubernetes-version certification, physical terminal
checks and the full supported native release matrix remain with their owning
qualification tasks. #46's PR must supply actual delivered-head hosted evidence
before this behavior is marked delivered.
