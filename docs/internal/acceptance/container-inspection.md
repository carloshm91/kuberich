# O07: container configuration and image inspection

## Source and scope

Issue #74 starts from protected #73 squash
`b781c793cbb7834d2dfe2c1bbe55c2caef1f7005`, tree
`3b42bfe3154dafd009ee412496dddf88a4dffb20`. Root revalidated the Astra plan's
52 source pins; the single App readiness delta preserves the new first-paint
handoff and changes none of the inspection ports. Three actual GPT-6.1 Sol
owners implemented domain, service and UI paths within this one issue.

The approved October 19 scope covers current API environment declarations,
configuration provenance and image facts. The issue body, O07 plan and OBS06
task mapping now reflect that decision; scanning remains X03 #245. Historical
source URL/hash pins remain unchanged. No real process environment or registry
inspection is claimed. Source version stays 0.3.0 during development of 0.4.0.

## Implemented behavior

The Pod → Containers → `e` route captures the original Pod/client and selected
container family/name. Environment, Image and Sources use a normal nested
workspace. Enter-to-logs remains intact. All environment values start hidden,
including literals and derived values. Image fields keep declared/status origin
and name-matched family status. Collection metadata includes source gaps and
the current-API-only explanation.

The pure resolver retains ordered envFrom and explicit assignments, per-use
optionality, unknown prefix barriers and backward one-pass dependencies. Missing
optional assignments preserve earlier bindings. Fixed field selectors and bounded
two-stage resource quantities are supported; runtime, binary and unsupported
sources stay unresolved. Public snapshots and metadata projections omit values
and binding hashes.

Finite reads use captured discovery and the per-context client. Fresh disclosure
checks Pod/source UID, opaque version and canonical content bindings, including
an observed optional absence. Reveal and copy consume separate one-use intents.
Owned-await publication checks its operation and intent generation. Known stale
bindings retire only their matching snapshot and retain Reload-required UI state;
cursor cancellation preserves valid metadata. Cancellation drains old parser and
transport work before another read or client close.

Metadata export uses the existing reviewed local artifact path. Actual export
after reveal, save, browser, viewer and Ctrl+Y round trip excludes literal,
inherited and derived markers and binding hashes. Application screenshot calls
refuse the inspector anywhere in the stack. Context teardown retains detached
screen owners until cleanup finishes. The new navigation profile reserves its
actual fixed keys and inherits configurable table movement.

## Scoped tests and retained original failures

- The final deterministic cohort passed 184 public-port tests. Both new modules
  measured exact 100% independent lines/branches: records/projection 220/220 and
  20/20; environment resolver 390/390 and 172/172. Full production was included
  in measurement; this is a per-module result, not the whole-package gate.
- Service/owned-verifier contracts passed 69 cases. Service coverage measured
  262/263 lines and 60/64 branches. Ruff, formatting and strict typing passed.
- The UI cohort passed 27 cases. Targeted final source-retirement, viewport,
  disclosure and error follow-ups passed nine cases, then three explicit failed
  reveal/latch cases. The actual artifact round trip passed separately.
- Root's reader-limit/key/profile/resource cohort passed 209 cases. The typed
  HTTP-body-limit and verifier-enrollment/qualification cohort passed 75 cases.
  Actual chunked HTTP aborts at the requested bound; HTTP 500 and malformed JSON
  remain distinct from that typed exhaustion.
- Final owner source PTYs passed at 40×12 and 100×30, with actual allowlisted
  API audit observations, same-entry negative network/subprocess controls,
  all four container families, fresh reveal/copy, resize, Back and exact terminal
  restoration. Root repeated both on its formatted integration source: two cases
  passed in 11.49 seconds. Canonical receipts are under `artifacts/terminal/`;
  deliberately revealed synthetic raw recordings use mode 0600.

Read-only cross-review reproduced and corrected three concrete defects before
qualification. Uppercase decimal `K` was incorrectly accepted in a quantity and
one positive vector; pinned apimachinery accepts `k` and binary `Ki`. Two failing
vectors were retained before the correction. Four actual HTTP handoffs exposed
stale child results returning after invalidation but before the public shielded
caller resumed. Two large-Pod/source-error cases exposed incorrect global budget
inference from ordinary API failures. All six failed before their service fixes.
The typed transport exception and post-await guard correct those distinct paths.

UI trials also exposed initial focus left on a button while the table was
disabled for loading, a transient command-input export lease, and stale hidden
status after revocation. The corrections retain owned cleanup and raw-value
concealment. Fixture/probe corrections include actual alias types, small-terminal
visible rows, native button press feedback and auditing the product entry point
after the intentional session-owner launcher. Original logs and receipts remain
under `artifacts/issue74/{domain,service,ui,root,review}/`; successful retries of
unchanged source are not presented as fixes.

## Actual owned-kind verification

The first actual trial used pinned Kubernetes 1.36.4 and checksum-verified kind
0.33.0. It failed during fixture preparation with an ApiException before product
reads; the original 29.39-second outcome remains unqualified. A separate
phase/status diagnostic trial identified HTTP 409 Conflict at the full-Pod
`PUT /ephemeralcontainers`: normal scheduler/kubelet status updates raced the
fixture resourceVersion. Both failed trials retained all source bindings and
removed the owned cluster, private files and sessions.

The fixture now sends one minimal UID-bound strategic merge PATCH containing
only the ephemeral-container field, without resourceVersion/status or blind
retries. Actual HTTP quality controls verify content type, request shape and
wrong-UID refusal. The corrected actual trial passed seven scenarios in
35.0067 seconds with 128 observed product GETs and all 252 input hashes unchanged:

- Real declaration/source order, prefixes, expansion, secret, field/resource and image facts.
- Regular, init, restartable-init sidecar and pre-created ephemeral identity.
- Updated current API configuration versus unchanged fixture startup values.
- Real denied Secret GET with independent literal resolution preserved.
- Former optional absence becoming present requires Reload.
- Same-name Pod recreation refuses captured-UID rebinding.
- Product reads use exact core object GETs without extra list/watch/exec/log/registry/node/Service access.

Owned kubeconfig/environment bytes remained unchanged; every operation/session
and private client directory drained. The cluster, node and fixture directory
were removed. Original, diagnostic and corrected evidence remains separately
under `artifacts/issue74/kind/trial-{1,2-diagnostic,3}/`.

After restoring the compact container hints described below, a fourth actual
trial passed the same seven scenarios in 35.7932 seconds, with 133 observed
product GETs, all 252 input hashes unchanged and complete owned cleanup. Its
receipt remains under `artifacts/issue74/kind/trial-4/`.

## Integrated verification attempts

An initial complete local suite was stopped gracefully after two failures,
retaining 418 passes and its original 825.59-second run. One failure exposed a
real compact-layout regression: adding environment inspection had removed the
existing shell hint. The compact line now retains environment, shell and logs;
all four existing workspace-size cases passed in 25.28 seconds.

The other failure occurred in the instrumented aggregate-log runtime replay:
the second large-log export review did not become ready within the existing
five-second fixture wait. Its original reports and source patch remain in
`artifacts/issue74/root/full-attempt-1/`. The helper now reports the public
review status and pending operation count if that condition fails. The isolated
three-mode protocol subsequently passed in 101.50 seconds; this diagnostic
result does not establish the cause of the concurrent failure or replace full
hosted qualification. Existing waits, latency controls and coverage policy
remain unchanged.

Fresh outside-checkout installed-wheel console and module PTYs passed both
cases in 22.77 seconds after the hint correction. They exercise all four
container families, separate fresh reveal/copy, allowlisted API traffic,
deliberate forbidden-network/subprocess controls, resize, Back and exact
terminal restoration. The terminal receipts bind their built wheel hash.
Final source PTYs also passed both sizes in 11.42 seconds on the corrected hints.

A subsequent application-coverage run was interrupted by a server restart at
43%, without a final result. Its logs and runtime receipts remain separate.
The replacement run has a bounded independent owner and durable exit/cleanup
receipt so a server restart cannot silently turn an interrupted run into a
successful result.

## Local application and independent coverage gates

The replacement application run completed successfully: 7,648 passed and one
hosted-macOS clipboard case was skipped on Linux, in 593.65 seconds. It includes
every unit, contract and UI case, the successful instrumented large-log replay,
both positive runtime controls and their strict deliberate negative controls.
The independent runner reaped its child and verified the process group absent.
Complete packaging/tooling/platform qualification remains a hosted requirement;
this application selection is not described as the complete repository suite.

The verified runtime-coverage merge covers all 246 production modules. Separate
gates passed with 29,702/30,097 lines (98.6876%) and 8,901/9,316 branches
(95.5453%). All 102 critical modules have exact 100% independent line/branch
coverage. Changed executable lines measured 1,251/1,277 (97.96%) against the
protected issue base, including staged and unstaged changes. No inventory,
exclusion or threshold was relaxed.

Final Ruff and formatting checks passed all 1,032 files; the actual workflow
strict-target union passed 293 source files. Plan, generated-reference,
documentation-source and both-site build/check commands passed: 53 pages,
2,170 local links/assets and 70 files. These are local build results, not a
website deployment. Logs remain under `artifacts/issue74/root/`.

## First hosted candidate and test-only corrections

PR #316 candidate `a958753c65e79617daaf690320fc9e8a9c6bc2ec` passed Fast tests,
Repository checks, DCO and all four native targets. It remains unqualified:
the full source matrix exposed stale kind/documentation enrollment assertions
and a repeat-click fixture race. Original job logs and annotations remain under
`artifacts/issue74/delivery/hosted-pr316-a958753/`.

The workflow now has 19 mandatory owned-cluster stages rather than 18. The
policy test names the inspector verifier and retained evidence explicitly.
Documentation enrollment now has 359 records; exact protected export history
at `b781c793cbb7834d2dfe2c1bbe55c2caef1f7005` preserves all 357 earlier records,
with precisely the new ADR and acceptance record appended. All earlier hash,
history and canonical-page assertions remain in force. The focused workflow
policy/enrollment/verifier cohort passed 48 cases.

On Python 3.14, a second Delete click could arrive while Textual's native button
press feedback still suppressed clicks, even though service work had drained.
An actual paused native feedback Timer reproduced the original five-second
failure. The test now waits for the originating browser, drained operation and
cleared native feedback before clicking again. Controlled held-feedback cases
prove that the file and metadata selection remain intact until the timer resumes,
followed by a fresh named confirmation and actual deletion/refresh. Both Python
3.14.3 and 3.12.12 passed all 13 browser cases, in 8.51 and 11.70 seconds.
The repeated-click flow retains its original five-second bound. No production
code, dependencies or qualified kind input changed.

The complete local quality selection passed 1,807 cases with one skip; two media
capture cases correctly refused the still-dirty source tree. Their unchanged
clean-committed-source precondition must be met before final local capture
verification. This attempt is retained as failed, not as a complete green suite.

## Second hosted candidate and quiet-watch observation boundary

Candidate `44d9bcf997814f9f8fc7ba5affaf76aa10a299fb` passed Repository checks
and DCO but failed Fast tests before the full matrix could start. An existing
quiet-watch contract observed two initial LIST requests while all three watch
resourceVersions matched the expected checkpoints. The hosted log does not
include the intermediate problem type. Its original failure and completed
unqualified result remain under `artifacts/issue74/delivery/hosted-pr316-44d9bcf/`.

A controlled real HTTP fixture held the first finite LIST until the unchanged
0.1-second deadline produced TIMEOUT/RETRYING without a snapshot. That reproduced
the same two-LIST/three-correct-watch observation, followed by successful
renewals. This establishes a concrete startup-timeout path, not certainty about
the original hosted problem type. Earlier probe cleanup-observation failures
remain retained separately.

The test now captures its observation baseline exactly once at the first valid
SNAPSHOT. Every earlier retry must be a TIMEOUT without a snapshot; establishment
and every renewal must retain strict no-LIST/no-backoff/no-stale-transition
assertions. Real HTTP 503 and 410 faults on the second watch must fail those
specific post-baseline assertions. Deliberately delayed initial LIST variants
exercise the normal startup-recovery path. Finite and total deadlines remain
0.1 and five seconds; handlers, client pool and session must drain and fixture
configuration must stay unchanged.

All 63 watch contracts passed on Python 3.12.12 in 19.96 seconds. All six changed
cases passed on Python 3.13.12 and 3.14.3 in 12.67 and 12.72 seconds. Ruff,
formatting and private-access checks passed. No production/helper code,
dependency or qualified kind input changed. Exact source hashes, originals,
negative controls and cleanup receipts remain in `artifacts/issue74/watch-ci/`.

## Remaining qualification

The complete exact-head hosted behavioral/source/native matrix remains required,
including the previously failed concurrent large-log review path. No scoped
percentage, plan, interrupted run or synthetic HTTP result substitutes for those
results. Publication remains separate.
