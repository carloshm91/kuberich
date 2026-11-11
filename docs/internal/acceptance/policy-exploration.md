# Policy exploration acceptance

[A05 #80](https://github.com/carloshm91/kuberich/issues/80) extends the protected
#232 resource implementation from main
`871d95890ddc08afa79631a693317e3858a1631e`. This record separates development
proof from final protected checks and release qualification. Source metadata
remains 0.4.0; no artifact or website publication is performed.

## Implemented behavior

The existing Standard table now covers validating/mutating admission policies and
bindings at exact discovered v1/v1beta1 descriptors. Typed counts, declared match
constraints, exclusions, selectors, parameter identities, actions, mutation types
and generation-qualified validating observations stay separate. Mutating resources
receive no fabricated validating-policy status or webhook reinvocation default.

Policy links filter same-version bindings by exact `spec.policyName`; bindings
read the current named policy through discovery. These are current-name relations,
not historical UID continuity. The existing captured client, source UID/opaque
version anchors, two-GET budget, intent guard and normal Back history remain in use.
All four families stay read-only at effect boundaries, including unknown versions.

The single discovery catalogue retains advertised preference through failed
version discovery. An automatic selection cannot interpret denied/incomplete
higher-preference discovery as absence; explicit discovered versions remain
usable. Unknown/alpha schemas retain metadata fallback and no PSP endpoint is
probed. Existing list/watch/pagination/metadata ownership machinery is reused.

Default inspection and artifact recursion share descriptor-aware admission
concealment for CEL, validation/message/patch/audit/warning payloads and webhook
URL/path/CA bytes. Resource/document/support exports and imported artifacts use
that policy. Deliberately reviewed sensitive resource payloads retain their
existing contract while previews stay concealed. Unrelated resource expression,
message and URL fields retain their existing intentional disclosure behavior.

NetworkPolicy peer scope, webhook match-condition/reinvocation declarations, HPA
behavior/generation provenance and bounded Pod/Node scheduling detail fill the
reviewed existing-family gaps. Quota, LimitRange and PDB observations are retained.
There is no parameter-value reader or admission, CEL, webhook, CNI or scheduler
simulator. Optional Workload/PodGroup API semantics and provider/CNI certification
remain unqualified. Immutable primary-source pins are appended to the
[existing inventory](../curated-resource-inventory.json); #232 history is unchanged.

## Required thin-spine proof

The initial validating-v1 implementation passed the complete path before other
families were added: owned HTTP discovery → Standard table → details/Links →
bindings → current policy → Back at 100×30 and 40×12. Its nine UI cases passed in
11.59 seconds with:

```sh
uv run pytest tests/ui/test_admission_exploration.py -q \
  --basetemp /tmp/kuberich-80-http-spine-2
```

Held source UID/RV changes, a third observed source RV during a held target read,
context replacement, actual HTTP 403, absent policy API and missing object all
refused stale navigation or version downgrade. The first draft's viewport-field
test error was corrected to actual public navigation coordinates; its failed log
is retained in `artifacts/issue80/http-spine-1.log`.

An actual owned kind validating-v1 pair passed in 30.969 seconds. Server defaults
Fail/Equivalent, LIST/WATCH/GET, read-only UI with global read-only disabled,
policy/binding/Back/filter/UID restoration, changed source RV, delete/recreate UID
refusal, actual impersonated 403 and PSP absence were observed. The exact command:

```sh
uv run python -c 'import runpy; runpy.run_path("/home/develop/projects/personal/kubetrol/artifacts/issue80/proof-lane/run_spine.py", run_name="__main__")' \
  /home/develop/projects/personal/kubetrol/artifacts/issue80/proof-lane/spine-002
```

Receipt `proof-lane/spine-002/result.json` retains 325 equal before/after input
hashes, real manifests and an SVG. App/admin/restricted sessions closed, generated
kubeconfig stayed unchanged, the cluster was deleted with absence verified and
its private directory was removed. The first run's receipt attempted to serialize
private record bytes; the verifier now captures explicit public fields and keeps
the strict encoder. Its original failure and cleanup outcome remain retained.
This spine qualifies only its measured working bytes, not the final candidate.

## Focused development evidence

The initial independent admission facts reached 100% lines/branches before the
spine. Expanded versioned controls cover all four families, required omissions,
malformed/duplicate identities, absent/null/empty selectors and collections,
unknown enums, output bounds and concealed payloads. Final measured results are
recorded after the input freeze below.

The shared privacy/inspection/export regression cohort passed 211 cases in
14.25 seconds. An independent public-codec probe reproduced 18 export/preview
leaks before the shared policy and zero afterward across six admission kinds and
48 controls. Original RED and corrected GREEN receipts remain under
`artifacts/issue80/root-audit/`; deliberate sensitive payload and unrelated-group
controls passed. Privacy policy coverage is 10/10 lines and 2/2 branches.

## Frozen implementation evidence

The final pure admission cohort passed 200 cases in 17.84 seconds: 246/246
statements and 58/58 branches. Existing policy/scaling and the scheduling helper
passed 374 focused cases in 25.70 seconds, each at 100% lines/branches:
394/126, 383/124 and 184/74 respectively. Separate privacy/navigation controls
also measured 100% of their new deterministic modules. These are scoped reports,
not the complete-production coverage result.

After composition review, a sensitive selector value was found to re-enter Pod
details through the raw scheduling projection. Passing the already-redacted
manifest corrected the issue; independent RED/GREEN receipts and actual App
canaries preserve this failure and correction. Denied-preferred discovery also
exposed an eager unversioned lookup when opening an explicitly selected beta;
the native-route preference check now preserves that explicit descriptor. Both
fixes passed 113 focused boundary cases in 29.74 seconds. The subsequent full
navigation/curated compatibility cohort passed 304 cases in 64.34 seconds.

The amended real kind command passed all 23 families (22 ordinary plus Events)
in 64.5607 seconds:

```sh
uv run python -m scripts.verify_curated_resources_kind \
  --kind /home/develop/projects/personal/kubetrol/artifacts/qualification-tools-linux-amd64-ewfuxtag/kind \
  --docker /usr/bin/docker \
  --evidence /home/develop/projects/personal/kubetrol/artifacts/issue80/proof-lane/full-kind-002/evidence.json
```

Its 326 source inputs stayed unchanged. The receipt SHA-256 is
`94b7a4c583771566d3c44205c2fe88c501243f17b65d33554b555381b26e6b05`.
The pinned 1.36.4 server advertised only stable v1 for all four admission
families; v1beta1 compatibility is versioned HTTP/pure evidence, not a claim
that this kind served it. Optional Workload/PodGroup APIs were absent. Both policy
kinds followed binding links and Back. Actual Pod/Node inspection showed bounded
affinity/toleration/taint declarations, preserved the unscheduled Pod's missing
nodeName, and concealed sensitive selector values and annotations in default,
managed, details and viewer captures. Every App/session, generated kubeconfig,
owned cluster and private-directory cleanup check passed.

The matching source PTY cohort passed four cases in 41.71 seconds: all 22
ordinary routes, both admission link paths, 100×30 and 40×12 geometry, resize,
Ctrl-Q/Ctrl-C, exact imported-module/source binding, GET-only ledger, no egress
or helper execution, concealed payloads/logs and restored terminal attributes.
Receipts are under `proof-lane/source-pty-002-receipts/`; original pre-fix 001
receipts remain historical. The documentation/site cohort passed 190 cases in
98.17 seconds. Ruff, formatting, the strict workflow target union (61 targets,
380 source files at that check) and changed-boundary strict types passed.

## Clean installed candidate

Signed implementation `da5920fc78327c877d9c44735758d10fccebe7b7` passed four
fresh installed-wheel cases in 66.88 seconds (console/module, families/admission):

```sh
uv run pytest tests/packaging/test_curated_terminal.py -q \
  -k 'families or admission' \
  --basetemp /tmp/kuberich-80-curated-installed-pty-01
```

The wheel SHA-256 is
`4b8b71670eb229ddd4deaeafb47aa1a4486d8a44d92902be4a5798c44911229c`.
All 320 Python payload modules matched source byte-for-byte. Actual imported
paths and cwd were outside the checkout. Every family route, both admission
link paths, Back, resize, interruption, concealed API/log payloads, GET-only
ledger, zero helper/egress and terminal/process/API cleanup checks passed.
Original receipts and the wheel are preserved under
`proof-lane/installed-001-receipts/`; there was no installer failure or retry.
This documentation-only evidence update preserves the measured implementation
commit and receipt identities rather than relabeling them as a later source.

## First hosted attempt and source clarification

The first ordinary Application run
[42943836205](https://github.com/carloshm91/kuberich/actions/runs/42943836205)
on `e34cb5a3f430ea89a065f42829dc23f123c60a13` failed Fast before the expensive
source/native matrices. A legacy Standard-inspection assertion still expected a
partially redacted webhook URL; the intended descriptor-aware default conceals
its complete payload. The corrected assertion requires `[REDACTED]`, rejects
every URL canary and retains the exact Service name/namespace checks.

The same source received a new high CodeQL result for a domain-shaped
`startswith` literal in the Kubernetes apiVersion classifier. Review of the
[official query](https://codeql.github.com/codeql-query-help/python/py-incomplete-url-substring-sanitization/)
identified a syntactic URL-check heuristic; the classifier selects no request
endpoint. The source now explicitly partitions group/version and compares the
exact Kubernetes group and slash. No alert suppression or dismissal was used.
An independent differential review preserved all 378 descriptor combinations,
10 non-document/missing-field cases and 3,024 nested concealment/preservation
checks, including unknown versions and foreign/scheme lookalikes.

The corrected privacy/export/inspection/App cohort passed 246 cases in 52.43
seconds, with 13/13 privacy-helper statements and 4/4 branches, plus Ruff and
strict types. The Standard/curated/inspection-export UI cohort passed 102 cases
in 64.13 seconds with complete URL concealment and retained Service identities.
The original CodeQL/Fast failures and source/native skips remain
retained under `artifacts/issue80/root-audit/codeql-01/` and `hosted-01/`.
Earlier native/installed receipts above retain their original source identities;
the corrected head requires its own genuine CodeQL and complete normal matrix.

## Benchmark browser readiness correction

The corrected source passed CodeQL (including its aggregate), Repository checks
and DCO, but Application run
[42944996063](https://github.com/carloshm91/kuberich/actions/runs/42944996063)
stopped Fast after 6,582 passes and one failure in 316.63 seconds. The saved
benchmark browser test requested another delete after its confirmation modal
left the stack but before Textual delivered that modal's completion callback.
The still-owned operation correctly refused overlap. No source/native matrix
ran, and the original failure remains in
`artifacts/issue80/fast-corrected-head-full.log`.

The browser now exposes `busy` as the same state used by its operation guard.
The test waits for the visible browser and retired operation under its original
five-second deadline. A held-callback control proves that modal disappearance
and an unrelated completed filesystem read do not establish readiness; an early
second delete is refused without deleting a record. After releasing the original
callback, the next fresh delete is admitted. Stored-count, selection/viewport,
restart and cleanup assertions remain intact. The affected UI cohort passed
17 cases in 14.82 seconds; Ruff and strict types passed. No sleeps, larger
deadlines or unchanged retry were substituted for this correction.

## Complete Fast/native evidence and changelog correction

Application run
[42946717824](https://github.com/carloshm91/kuberich/actions/runs/42946717824)
on `2219299c4edb1fc40c4e9a6e17723af2068b9faf` passed the complete Fast selection:
11,787 passed and one skipped in 530.77 seconds, within the unchanged limit.
All four native jobs passed. Independent audits verified their exact 462 build
inputs, provider/archive digests and 24 retained PTY/ANSI restoration receipts,
with actual complete/cancel/missing-tool outcomes and owned cleanup. These are
ordinary-PR native checks; their runtime qualification flag remains false.

The 16 source parts completed with 12 passing and four reporting the same single
changelog style error: the new entry had 26 visible words against the existing
25-word limit. Each failed part otherwise passed 3,486 tests with one skip.
The entry is now shorter, and all five changelog-style cases pass in 0.74
seconds. The rule, source code and test expectations remain unchanged.

Root assembled Linux Python 3.12 coverage diagnostically from all four original,
authenticated part archives using the unmodified combination, runtime, coverage
and changed-line tools. It verified source/nonce/arc-union controls, no exclusions
and all 320 production modules: 44,619/45,303 lines (98.49%), 13,084/13,760
branches (95.09%), all 133 critical modules at 100%, and 575/575 changed executable
lines (100%). Original failed JUnit/statuses remain intact and the diagnostic
receipt explicitly sets source qualification false. No passing source receipt
was fabricated; this failed run still requires a genuine corrected-head matrix.

## Terminal membership observation correction

Application run
[42950685427](https://github.com/carloshm91/kuberich/actions/runs/42950685427)
on `32e0ba135ab995c2c436541d3e60ec0b25ec4051` passed Fast, all four native jobs
and 15 source parts. The remaining macOS part reported one failure, 3,258 passes
and four skips in 790.46 seconds. After successful context/namespace navigation,
the application exited with restored terminal modes, but the harness's subsequent
`ps` membership census exceeded its independent 0.5-second subprocess limit.
The original failure receipt records actual exit zero, unchanged terminal modes
and complete later owner/group/descriptor cleanup. It does not establish that
the failed census would have completed within the overall deadline.

The single census now shares the caller's existing absolute deadline and rejects
any result observed at or after that deadline before acknowledging its owner.
The 15-second finish and three-second cleanup-phase budgets, verified owner,
exact membership and restoration requirements remain unchanged. No observation
retry or uncertain-to-empty fallback was added. A real delayed census reproduces
the former 0.5-second refusal; a separate late-result control reproduces the
former missing expiry check. Hung observation still refuses acknowledgement and
its actual `Popen` child is killed and reaped. Original RED and hosted receipts
remain retained under `artifacts/issue80/hosted-04/`.

The final owned-group/context regression command passed 51 cases in 60.79 seconds:

```sh
uv run pytest -q tests/terminal/test_owner_cleanup.py tests/terminal/test_contexts.py --basetemp=/tmp/kuberich-80-membership-regressions-02
```

Ruff, formatting and strict helper types passed. The changelog/internal-document
cohort passed all 12 cases in 7.24 seconds. A complete corrected-head ordinary
matrix remains required; the failed run is not qualified by these focused checks.

## Remaining qualification at this source freeze

The ordinary 27-job PR matrix, complete independent production/changed-line
coverage and protected delivery are tracked live in
[issue #80](https://github.com/carloshm91/kuberich/issues/80).
No focused cohort substitutes for those checks. The six-environment manual matrix and three repeated release
contracts belong to #82; provider certification remains opt-in #87. Startup and
runtime latency are advisory for 0.x with actual misses retained; RSS, import
boundaries, frames, deadlines, cleanup and coverage remain hard requirements.
