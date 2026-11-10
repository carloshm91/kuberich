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
