# Ephemeral debugging acceptance

Issue: [A03 #78](https://github.com/carloshm91/kuberich/issues/78).
Phase: v0.5.0. Implementation starts from protected main
`4a39d458a6801a103bab1ee5b305ed45cbba24b1` on `feat/78-ephemeral-debug`.
Prepared contracts are not actual API, terminal, hosted or release qualification.
Source metadata and published packages remain 0.4.0.

## Contract

A captured core/v1 Pod is read afresh. Subresource discovery, complete container
name membership, target running-instance evidence and an explicitly reviewed
digest image bind the strict server dry-run. A one-use confirmation authorizes
one conditional UID/version append. A fresh GET precedes that write; conflicts
require a new review rather than rebasing or retrying an old approval.

The returned addition identity is separate from admitted-profile validation,
startup, remote session status and local attachment. Uncertain responses remain
uncertain. A disconnected terminal does not establish remote completion. There
is no production Pod deletion, declaration removal, privilege fallback or
automatic attach reconnection. Fresh checks cannot close Kubernetes' final
name-based attach race or certify runtime process-namespace visibility.

## Focused preparation

The command-routing cohort passes 497 tests in 4.53 seconds:

```sh
uv run pytest tests/unit/test_command_catalog.py tests/unit/test_launch_contract.py tests/unit/test_view_actions.py tests/unit/test_navigation.py -q --basetemp=/tmp/kuberich-78-routing-01
```

This verifies readable inspection policy, selected-Pod scope, startup rejection
before effects, argument refusal and canonical completion. It does not establish
any actual ephemeral-container request or product UI delivery.

The documentation/history and cluster-enrollment cohort passes 69 tests in
13.88 seconds with `/tmp/kuberich-78-enrollment-03`. Earlier runs retain old
expected inventory counts (375 documents and 27 cluster stages); the corrected
expectations are 377 and 28, preserving every existing item. The private-access
audit also passes. These are preparation checks rather than API proof.

## Required actual proof

The verifier uses explicit reviewed tools, a new private owned kind cluster and
synthetic fixtures. Before broad interaction work, prove that dry-run persists
nothing, conditional append adds exactly one entry and completed entries cannot
be edited or removed. Exercise real attach completion and detach independently
of remote status. Then cover stale UID/version, repeated names, denied
subresource, target termination/restart and a lost post-commit response.

Record fixture setup separately from production requests. Prove that workload
container/Pod identity, caller kubeconfig/environment and unrelated fixtures
remain unchanged. Every request, parser, terminal, subprocess descendant and
private file must drain before client release; cluster absence is checked.

The prepared invocation is:

```sh
uv run python -m scripts.verify_ephemeral_debug_kind --kind /absolute/path/to/verified/kind --kubectl /absolute/path/to/verified/kubectl --docker /usr/bin/docker --evidence artifacts/ephemeral-debug/early/evidence.json
```

Actual source-bound API/PTY evidence, meaningful fault results, installed-wheel
trials, independent production/changed-line coverage and all protected exact-head
checks remain pending. No tags, packages, hosting or DNS are changed by this work.

## Original actual trial

The first clean candidate, `fe33523d6ab7fe3ecd450bee06d0dc5b855dfd11`,
fails in 33.26 seconds during actual kubectl attachment, before receiving
terminal input. Its retained report is
`artifacts/issue78/early-kind-01/evidence.json`. The recorded production
requests establish successful HTTP 200 strict dry-run and a single conditional
append with the same reviewed UID/version/request digest. The returned Pod
contains the exact nonprivileged declaration. Attachment receives EOF after
core/group discovery; the original receipt does not retain the child error
text, so the cause is not inferred from that result alone.

The original failure preserves unchanged measured inputs, drained owners,
deleted private sessions/directories and verified owned-cluster absence.
Subsequent diagnosis and corrected proof remain pending; this attempt does not
establish attach completion, detach, irreversibility or release qualification.

## Core and ownership checks

The focused core cohort passes 125 cases in 15.50 seconds with a fresh physical
`/tmp/kuberich-78-core-04` base and independent coverage artifacts. The pure model
measures 289/289 lines and 108/108 branches; the append adapter measures 37/37
lines and 10/10 branches. All 29 fixture listeners use owned loopback ports.
This measurement includes unimported production in the report, but is a focused
cohort rather than the full production coverage gate.

Review catches and tests the server's omitted `stdinOnce=false` default, an
invalid-profile receipt becoming a foreign attach, readiness beyond the display
limit, stale deferred executions, a same-Pod request-retargeting hole, a collector
racing terminal preparation and a self-close dependency cycle. Monitor and stage
validation use the owned parser worker. The final service cohort passes 49
cases in 6.19 seconds with `/tmp/kuberich-78-service-07`; that module measures
390/391 lines (99.74%) and 71/74 branches (95.95%). The earlier 42-case result
measured only 59/68 branches (86.76%) and is not a branch-gate pass. No original
failure or coverage report is relabeled. Ruff and focused strict typing pass.

Verifier safety controls pass 15 cases in 1.06 seconds with
`/tmp/kuberich-78-proof-01`. They refuse unsafe tools/source/evidence before
cluster creation and preserve actual failures/cleanup. They do not substitute
for the pending successful real API/PTY proof.

The second committed trial, `f53dbbeb8e2f6510bd6bfa780c0b1e3bb0100198`,
fails in 34.51 seconds at a verifier expectation for the local attach exit code.
Preserving upstream aggregated-discovery Content-Type enables the actual
WebSocket connection (HTTP 101), synthetic input/output marker and remote
`exit 7` command. That original result does not record the child's numeric exit
code before its assertion, so the subsequent correction must measure it and
observe remote termination separately. All cleanup and input-stability checks
pass. The original report remains at `artifacts/issue78/early-kind-02/evidence.json`.

An owned HTTP regression covers discovery GVK parameters. A real local PTY
control also catches an initial-input flush assumption; the corrected bounded
handshake cohort passes 17 cases in 1.35 seconds. These test-harness corrections
do not change the production attach argv or reinterpret local exit as remote
completion. Full actual proof remains pending.

## First complete actual spine

Candidate `21341e19f8caa69fda6fae1d4cd70d2e6a3703e3` passes all 12 real
groups in 37.74 seconds. It uses the invocation above with the explicit reviewed
tools and fresh `artifacts/issue78/early-kind-04/evidence.json`. All 314 measured
inputs remain unchanged, owners drain, private sessions/directories disappear
and the generated cluster is deleted with absence verified.

The observed groups establish strict dry-run with no persistence; one exact
UID/version append; actual attach input/output with local exit zero and a fresh
remote terminated exit seven; server refusal to edit/remove completed entries;
failed UID/version conditions and duplicate names; stale review refusal; actual
detach with the remote process still running; lost post-commit response without
replay/adoption; denied subresource; target-instance invalidation; and no
production deletion or workload-specification changes. The same Pod survives
the target restart from count zero to one. The local terminal is cancelled and
its old review cannot reconnect. This precedes broad UI implementation.

The original third trial passes ten of those groups and then times out in
98.74 seconds waiting for its fixture restart. Its `kill -9 1` was sent inside
the same PID namespace, where namespace-init signal restrictions apply. The
corrected fixture explicitly installs a USR1 handler and records a successful
owned trigger followed by the fresh restart count; production code, Pod
namespaces and deadlines are unchanged. Original early-kind-03 remains failed,
with all cleanup checks passing. Local attach exit is measured independently
from remote process status; neither is inferred from the other.

Successful early service/PTY proof is not product CLI, installed-wheel, complete
platform/coverage or cumulative release qualification. Those gates remain pending.

## Product interaction preparation

After the actual 12-group spine, the source CLI completion case passes in
4.49 seconds with `/tmp/kuberich-78-proof-08`: explicit review and one addition,
separate attach, input/output, local return, fresh remote terminated exit seven,
resize and quit. The helper verifies exact terminal restoration, child reaping
and private connection-file removal. This is an owned loopback API and audited
local kubectl substitute; it does not itself establish a real runtime connection.
The earlier helper attempt retains its failed input-selection expectation;
existing ForwardInput uses Home plus erase-to-end, not select-all.

The first 15-scenario CLI cohort passes 11 and fails four in 49.33 seconds.
Its original ANSI/JSON receipts retain the missing-tool message/return behavior,
partial-result label, wrapped screen text and explicit read-only flag assumptions.
Helper expectations are corrected without changing product policy or hiding
failures. A fresh complete interaction result remains pending.

Generated references pass declaration-drift checks. Both locally built preview
surfaces pass 53 pages, 2,204 local links/assets and 70 files. App and operation
composition pass focused strict typing and Ruff. No site is deployed by these
checks; installed feature, real-CLI-plus-kind, full coverage and hosted gates
remain pending.

The corrected source CLI cohort passes all 15 scenarios in 20.55 seconds with
`/tmp/kuberich-78-proof-11`: completion, interrupt, detach, local close, quit,
SIGTERM, disconnect, missing helper, startup failure, uncertainty, context,
repeat, cancel, denial and read-only inspection. The context scenario changes
context after closing the local terminal/viewer; active-attachment invalidation
is tested separately through Pilot and the service owner. Earlier proof-10
retains 14 passes and one invalid helper spelling (`--read-only` instead of the
actual `--readonly`); the corrected flag does not change product policy.

The separate real-kind CLI driver's owned-HTTP/real-local-PTY preflight passes
in 4.91 seconds with `/tmp/kuberich-78-proof-14`. It verifies explicit selection
among heterogeneous existing/new rows and an audited executable wrapper; its
first failed focus-count assumption is retained. This preflight does not itself
run kind. The final actual verifier now includes a real CLI plus verified
kubectl connection, real attach denial, admission refusal and Pod replacement;
those additional actual results remain pending. Verifier quality passes 19
cases in 1.53 seconds, with strict typing and Ruff passing.

Pilot also exposes a real stale-cause bug: denied Pod reads were immediately
relabelled as generic attachment unavailability, including when no terminal
existed. The narrow service correction preserves denied/not-found/unavailable
through both local stop and terminal-finally publication. Six HTTP regressions
cover 403/404/500 with inspection and actual owned ProcessRunner PTYs, preserving
rows and the last valid observation time while reaping the child and staging.
The final service cohort passes 55 cases in 7.25 seconds with
`/tmp/kuberich-78-service-09`, retaining 390/391 lines and 71/74 branches.
The first added-test attempt retains six test-authoring failures; no production
failures or earlier reports are relabelled.

The first complete 39-case Pilot cohort passes in 70.02 seconds with
`/tmp/kuberich-78-ui-15.EwNq9n`. Independent focused UI coverage is 349/366
lines (95.36%) and 72/86 branches (83.72%); this is not the whole-production
branch gate and is not relabelled as 90%. Cases cover default Cancel at two
viewport sizes, review/edit races, supported/refused options, read-only and
uncertain state, stale rows/viewport, real local PTY input/resize/return,
context/policy/quit drainage, complete-preview bounds and fatal rendering faults.
The repeated-Back regression prevents dismissing the root before delayed
Unmount. Failed waiting-reason and pre-entry cancellation/quit assumptions
remain retained in earlier attempts. Final focused additions remain pending.

## Final actual API and product proof

Clean source `fa2678d8cfbd857e998b5eaac1f11da36009a051` passes all 16 real
groups in 45.10 seconds at `artifacts/issue78/full-kind-03/evidence.json`.
Report SHA-256:
`26a52d16f026dcc3d1f44d2d1146dedd1cb8696ab5e32dffc391f7b490bf69f2`.
All 318 runtime/tool/controller/helper inputs remain unchanged. Owner, process,
private-session/directory and cluster cleanup pass; the owned kubeconfig, caller
sentinel and environment remain unchanged.

Beyond the early 12 groups, this trial proves actual attach RBAC refusal while
the confirmed entry remains running, explicit admission refusal with no addition
or privilege fallback, a real source CLI review/add/verified-kubectl attach/return
and a same-name Pod replacement refusing the original UID before dry-run.
The real CLI's local attach result and the independently read remote exit seven
remain separate. Fixture-only Pod deletion is recorded separately from production
traffic; the product sends no Pod DELETE or declaration removal.

### Retained extended-trial failures

`full-kind-01` fails in 40.46 seconds at the admission readiness assertion after
12 successful groups. Its first accepted fixture probe records HTTP 200, but
the following exception's status was not recorded before the assertion.
The next verifier records every status and permits another bounded setup
dry-run only when HTTP 422 accompanies the same UID and a changed opaque
version. Six owned HTTP/SDK cases verify that rule and refusals; production
requests never gain a retry.

`full-kind-02` fails in 40.51 seconds with fixture probes 200, 200, 422. Its
verified same UID and unchanged version 547 disprove the proposed version-churn
explanation for that attempt. Kubernetes' [pinned validation type](https://github.com/kubernetes/api/blob/v0.36.4/admissionregistration/v1/types.go#L332-L339)
defaults an omitted policy reason to Invalid. The fixture now explicitly chooses
Forbidden to bind its intended HTTP 403; application code and status gates stay
unchanged. The final actual probes are 200, 200, 403. Both original failures
retain successful cleanup and unchanged measured inputs; neither is relabelled.
Verifier quality passes 28 cases, with Ruff, formatting and strict typing passing.

## Installed feature proof

Four outside-checkout wheel cases pass in 24.10 seconds with
`/tmp/kuberich-78-installed-01`, using both console/module completion, console
detach and module uncertain-response flows. All 309 wheel runtime files are
byte-identical to tracked current source. Wheel SHA-256:
`2a139d0fb07dacf56baa2504538136ab320dc33cc643037249be7526fb6fb20b`.
The original wheel/sdist, JUnit and byte-comparison summary are retained under
`artifacts/issue78/installed-01*`. Subsequent controller-only edits do not change
those runtime bytes. This remains installed feature evidence, not the complete
platform matrix or a public package upload.

The final 43-case Pilot cohort passes in 75.08 seconds. Independent focused UI
coverage is 355/368 lines (96.47%) and 78/88 branches (88.64%); the whole-package
line/branch and changed-line gates remain authoritative in the hosted matrix.
Its four final lifecycle/update cases also pass separately in 5.23 seconds.
The full production, all critical modules, exact-head platform and protected
merge checks remain pending. No tags, packages or hosting are published.

## First hosted attempt

Application quality run `42833552212` on head
`844cb69e7ac7a6bc53cd93e8ed6a942d465d7bcd` fails before Fast tests execute.
The private-access audit passes, then the Ubuntu APT update exceeds its unchanged
120-second command deadline (exit 124) while downloading signed package and
Translation-en indexes. The full matrices do not run. Repository validation
`42833552164` and DCO pass independently; they do not qualify the application.
The original job log is retained in `artifacts/issue78/control/hosted-fast-01.log`.

The CI-only correction requests `Acquire::Languages=none`, the documented
[APT setting](https://manpages.ubuntu.com/manpages/noble/man5/apt.conf.5.html#the-acquire-group)
for disabling translation indexes. Package closure, official HTTPS sources,
signature/TLS verification, retries and 120/180-second command deadlines are
unchanged. No local privileged command or APT update is run. The owned-command
bootstrap/qualification cohort passes 124 cases in 8.30 seconds, plus Ruff,
formatting and strict typing. Actual hosted setup and the complete exact-head
matrix must pass on the corrected head before delivery; local argv contracts
do not establish mirror throughput or erase the first failure.
