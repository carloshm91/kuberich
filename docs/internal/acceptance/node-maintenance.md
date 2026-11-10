# Node maintenance acceptance

Issue: [A02 #77](https://github.com/carloshm91/kuberich/issues/77).
Phase: v0.5.0. Implementation starts from
`7c8c7cb1595a3609c2d6a5748087d53917ce9af8` on `feat/77-node-maintenance`.
This record separates prepared contracts from measured behavior; preparation
does not establish delivery, hosted qualification or publication.

## Boundary

One actual core/v1 Node is captured with its session generation, UID and opaque
version. Reviews and one-use confirmation authorize cordon, fixed-set drain or
separate uncordon. Drain uses policy/v1 eviction with both Pod UID and version
preconditions. Unmanaged and emptyDir consents are independent; DaemonSet and
mirror/static Pods remain. Only explicitly refused 429 attempts can retry under
a finite deadline. Accepted/uncertain writes are not replayed. Cancellation stops
new requests without rollback, and a final read separately observes scheduling.

The same-Node read and Pod eviction are separate requests, not a transaction.
Controller identity, PDB status and declared storage do not guarantee workload
health, replacement capacity or storage portability. Pod version churn requires
a fresh review. Cloud/provider certification remains Q05 #87.

## Focused preparation checks

Run from the issue checkout:

```sh
uv run pytest tests/quality/test_owned_kind.py -q --basetemp=/tmp/kuberich-77-proof-03
uv run pytest tests/quality/test_node_maintenance_kind.py -q --basetemp=/tmp/kuberich-77-proof-02
uv run mypy --strict scripts/owned_kind.py scripts/verify_node_maintenance_kind.py scripts/qualification.py
```

The helper cohort passes 72 tests in 60.10 seconds with a fresh outside-checkout
temporary directory. The proof controller passes ten tests in 0.60 seconds.
Strict types and focused Ruff pass. These checks establish tool/evidence/source
refusals, bounded fixture waits, topology/endpoint verification, partial-create
cleanup and foreign/replacement refusal; they do not establish actual Kubernetes
eviction behavior. An earlier default-pytest temporary-directory run passed but
reported four stale-directory cleanup warnings; it is retained as an earlier
attempt, not evidence for the corrected directory coordination.

## Actual API proof

The prepared verifier command is:

```sh
uv run python -m scripts.verify_node_maintenance_kind --kind /absolute/path/to/verified/kind --kubectl /absolute/path/to/verified/kubectl --docker /usr/bin/docker --evidence artifacts/node-maintenance/early/evidence.json
```

It creates one control plane and two workers with the pinned Node image, an
explicit private kubeconfig and local Docker socket capture. The early scenarios
are conditional cordon/conflict/uncordon and a managed Deployment blocked by a
PDB, followed by allowance recovery while the reviewed target Pod version stays
unchanged, original-UID absence and replacement scheduling on the other worker.
The first clean committed trial, `0979f7aba978b661a2d4c9bab3331521b0364ae5`,
fails in 45.49 seconds during PDB allowance recovery. Its evidence is retained at
`artifacts/issue77/early-kind-01/evidence.json`, with the original log and source
snapshot. Conditional cordon/conflict/uncordon and the actual PDB refusal are
reached. The original report does not retain the final wire status, so it does
not prove that specific response value. All three owned nodes are removed and
client/private-file/source/environment cleanup checks pass.

The initial client accepted only HTTP 200 eviction success. The pinned
[API create handler](https://github.com/kubernetes/kubernetes/blob/v1.36.4/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/create.go#L209-L217)
uses HTTP 201 and fills an otherwise empty Status code; the
[eviction implementation](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/registry/core/pod/storage/eviction.go#L274-L287)
returns Status success. An owned HTTP 201 case is retained red before the fix.
The corrected client accepts only HTTP 200/201 with a validated v1 Status success;
a supplied body code must exactly match the observed status, while an omitted
optional code remains valid. Mismatched/invalid receipts stay uncertain and are
not replayed. Node PATCH still expects HTTP 200. The targeted cohort passes 133
cases; strict typing and Ruff/format pass. UID/version request bytes stay fixed.

The second clean committed trial, `787800cb1a6bcbe834087993ce6f741e938a40a4`,
passes all four early real API groups in 47.81 seconds. It observes the actual
PDB 429 refusal, then HTTP 201 on a second attempt using the same reviewed Pod UID
and resourceVersion after a second replica restores allowance. The original UID
is confirmed absent; both replacement UIDs run on the other worker. DaemonSets
remain, the final drain observation is cordoned, and a separate fresh review
explicitly uncordons the Node.

All 308 measured inputs stay unchanged. The caller's synthetic kubeconfig
sentinel, environment and owned kubeconfig are preserved, all service owners
and private sessions drain, and all three owned nodes are deleted with absence
verified. Evidence is `artifacts/issue77/early-kind-02/evidence.json`, SHA-256
`0bdf804328579c209457e859d1ba5af110dc2fe39103374f3ca2c017aeb51de9`.
Both commands use the verified absolute tools above and fresh evidence paths;
`candidate.json` records each immutable commit/tree before execution. Later
source changes require new qualification; these four early groups do not
establish all issue acceptance criteria or release readiness.

## Completion limits

Expanded multi-node scenarios, public UI/PTY behavior, full production/critical/
changed-line coverage and every required hosted exact-head job remain pending.
The ordinary PR matrix has 27 jobs; release-time manual six-environment
qualification and three repetitions remain separate. Published artifacts remain
0.4.0. This issue does not authorize tags, packages, hosting or DNS changes.
