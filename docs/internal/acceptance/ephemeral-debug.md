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
