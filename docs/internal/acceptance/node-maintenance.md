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

## Expanded owned-cluster verification

Run from the issue checkout with the same checksum-verified tools:

```sh
uv run python -m scripts.verify_node_maintenance_kind \
  --kind /home/develop/projects/personal/kubetrol/artifacts/qualification-tools-linux-amd64-ewfuxtag/kind \
  --kubectl /home/develop/projects/personal/kubetrol/artifacts/qualification-tools-linux-amd64-ewfuxtag/kubectl \
  --docker /usr/bin/docker \
  --evidence artifacts/issue77/full-kind-04/evidence.json
```

The first fully expanded committed candidate
`1a824b52beea7fc057c84dea6de00c8ab9a0baa2`, tree
`967796c3e7388b55dc5bb29989263b712a1e1360`, passes all 13 real contract groups
in 90.40 seconds. The report SHA-256 is
`c585b31e5974ad43ca99d36c787201f440cdf17adc2e76ac207c94915a607eda`.
`artifacts/issue77/control/full-kind-04-candidate.json` records the clean source
before execution. All 308 measured inputs remain byte-identical throughout.

The actual observations establish:

- Conditional cordon, conflict refusal and separate uncordon; actual PDB 429
  followed by HTTP 201 on unchanged reviewed Pod UID/version bytes, original-UID
  absence and replacement scheduling on the other worker.
- Accepted eviction with a retained finalizer remains pending until absence.
  The deadline leaves the Node observed cordoned without shortening normal
  grace, removing finalizers or automatically uncordoning.
- Independent unmanaged, emptyDir and DaemonSet choices block when missing.
  Both overrides still receive PDB refusal. Real control-plane mirror and
  DaemonSet UIDs remain; other ordinary control-plane Pods stay in the review
  and can progress independently.
- Stop preserves an independently absent Pod and another PDB-refused Pod. The
  observation extends beyond its actual scheduled retry deadline, with zero
  further production requests. A fresh explicit uncordon follows separately.
- Real restricted RBAC refuses eviction after cordon. Separately labelled
  owned HTTP response loss after upstream HTTP 201 remains uncertain without
  replay, even after the original UID becomes absent. This injected fault does
  not claim a real provider/network failure. Production receipts contain no
  direct Pod DELETE or PDB mutation; fixture cleanup is recorded separately.
- A replacement UID is never adopted by an old confirmation. An unreviewed
  arrival prevents complete-drain reporting, and external uncordon stops new
  evictions. The final fresh read matches the selected Node UID and records
  `unschedulable_field: null`, corroborating the SDK's omitted-field default as
  schedulable; explicit `true` is never accepted as schedulable.

Every production write is an exact Node PATCH or policy/v1 eviction POST; each
eviction's UID/version pair belongs to a reviewed intent and uses normal grace.
The unrelated sentinel UID, caller's synthetic kubeconfig sentinel, environment
and owned kubeconfig remain unchanged. All owners and private sessions drain;
all three owned nodes are deleted and absence is verified.

### Retained expanded-trial failures

The original reports and logs remain under `artifacts/issue77/`:

- `full-kind-01` fails in 39.06 seconds because the owned forwarder sends an
  empty byte payload for GET, causing aiohttp to add an octet-stream content
  type that discovery rejects with HTTP 415. A mutual-TLS discovery regression
  reproduces it before the verifier-only correction to a bodyless GET.
- `full-kind-02` fails in 50.78 seconds because the scenario stops immediately
  after one PDB refusal while another reviewed control-plane eviction is in
  flight. The upstream returns HTTP 201; production truthfully reports that
  interrupted write as uncertain. The scenario now uses a reviewed four-second
  deadline and verifies independent outcomes. Explicit Stop is tested later
  after queued writes settle and retry deadlines are still in the future.
- `full-kind-03` fails in 84.60 seconds at its final SDK assertion, which requires
  an explicit `False`. It reaches the behavior observations, including a final
  schedulable state, but does not retain that last SDK field's literal value.
  Its omitted-field explanation remains an inference for that attempt. The
  corrected oracle records the field before asserting; `full-kind-04` supplies
  the actual `null` observation above.

Every failed expanded attempt retains verified source invariance and owned
cluster/private-file/owner cleanup. None is relabelled as a successful run.

## Scoped contracts and terminal evidence

The core cohort passes 186 focused cases, with the deterministic maintenance
domain at 100% lines and applicable branches. These scoped measurements do not
replace full-package coverage or the complete critical inventory. The proof
controller and mutual-TLS forwarder cohort passes 14 cases in 2.16 seconds:

```sh
uv run pytest tests/quality/test_node_maintenance_kind.py -q --basetemp=/tmp/kuberich-77-proof-20
```

The separate installed rehearsal passes eight actual PTY cases in 40.41 seconds:
four source scenarios and console/module entry points for success/uncordon and
context-switch cleanup from a fresh wheel. It checks real terminal behavior
against an owned loopback API, rather than claiming those PTYs use kind.

```sh
uv run pytest tests/terminal/test_node_maintenance.py tests/packaging/test_distribution.py -k node_maintenance -q --basetemp=/tmp/kuberich-77-installed-01
```

`artifacts/issue77/installed-01/wheel-receipt.json` binds all 304 packaged runtime
files byte-for-byte to the frozen source; later changes affect only verifiers.
The wheel SHA-256 is
`c938e164875b9769976199904e69399b99b29ff01b905de1a770ae867d869b63`.
It is a local verification artifact, not a published package.

Ruff/format, the complete strict type target union, private-access, plan and
documentation checks pass. The source/runtime association and individual
cohorts remain separate from complete hosted application qualification.

## Cross-review regressions and corrected candidate

Subsequent independent review identifies two additional core races: a cancelled
response-cleanup await can leave a 429 retry hint after the attempt becomes
uncertain, and the final Node observation can contradict a prior successful
aggregate. Five owned HTTP cases reproduce the failures before source changes,
including an unwanted second Pod POST after Stop/deadline and obsolete success
claims after uncordon, replacement or a failed final GET. The original red log
and XML remain at `artifacts/issue77/core-review-red.log` and
`artifacts/issue77/core-review-red.xml`.

Only a completed REJECTED HTTP 429 now supplies a retry hint. Every receipt
branch publishes its outcome and checks pending cancellation before another
request. A conflicting or unavailable final scheduling observation downgrades
prior success to partial without changing completed Pod outcomes. The corrected
cohort passes 194 cases in 26.80 seconds; the maintenance domain and adapter each
have 100% scoped lines/branches. Independent read-only follow-up confirms both
original control-flow gaps are closed.

A public Pilot regression also reproduces stale Pod/PDB/storage details after a
populated review becomes empty in the same screen. Rebuilding and empty selection
now clear those facts. The complete maintenance/navigation cohort passes 51
cases in 59.09 seconds, including both small and ordinary terminal geometries.
The first hosted Fast job, run `42801828070`, separately fails an old completion
expectation: `:c` correctly includes the new `cordon` command before `ctx`.
Its original 96-pass/one-failure run remains failed; its platform matrix never
runs. The corrected keyboard/choice expectations pass in that focused cohort.
Repository validation run `42801828235` succeeds for the earlier head.

Clean corrected candidate `10ba07d858d7cd7f787d6294ec653a287bd2849f`, tree
`eddb6c3eea055dde32c1804fc58c92ad314ec04b`, repeats all 13 actual kind groups
successfully in 88.71 seconds. All 308 inputs and every cleanup/caller-state
check pass. Evidence is `artifacts/issue77/full-kind-05/evidence.json`, SHA-256
`2fb4e1a938f210a5782d05f897cc75640a6ef26f5c2a43e5603f4e6d75a7f4f7`;
the same verifier invocation above uses this fresh evidence path. Stop observes
zero production requests beyond the actual retry deadline. These kind scenarios
and the controlled HTTP cleanup races are distinct evidence layers.

The fresh installed rehearsal on that corrected source passes eight cases in
39.89 seconds with `--basetemp=/tmp/kuberich-77-installed-02`. Its 304 runtime
files match source; `artifacts/issue77/installed-02/wheel-receipt.json` records
wheel SHA-256
`d67c3be06fb3db2fafd2616efde9ca146272e68a69c13275e8932eb6af554c2c`.
Earlier successful receipts remain valid for their recorded source; they do not
qualify later runtime changes. Complete protected checks on the corrected PR
head are still required.

The second hosted Fast run, `42803716846` on `562ff1f`, also remains failed:
824 cases pass before another stale `:c` expectation in the authorization grammar
test fails. A repository-wide search finds no other old three-choice context
expectation. The corrected authorization/navigation/catalog cohort passes 408
cases in 2.64 seconds; the seven additional completion-related unit files pass
491 cases in 2.69 seconds. These are separate focused runs, not a full-suite or
coverage claim. At `26410ce`, only tests and documentation change after `10ba07d`; all 308
measured inputs still match its successful kind report. The later UI correction
below requires and receives fresh source-bound measurements.

## Denied inventory is distinct from empty

A subsequent owned HTTP 403 regression finds that the new empty-detail label
can describe an incomplete blocked review as complete-empty. Confirmation is
already disabled and stale facts are cleared, but the label is incorrect.
The original one-case failure takes 2.40 seconds at
`/tmp/kuberich-77-ui-pdb-denied-red-01`. The label now requires an unblocked empty
review; a denied inventory leaves details blank and keeps its explicit blocker.
All 19 maintenance Pilot cases pass in 23.54 seconds at
`/tmp/kuberich-77-ui-pdb-denied-green-01`, including exact PDB 403 routing, no old
UID/PDB facts, no empty claim and no write request.

Application run `42804859918` on `26410ce` is deliberately cancelled during Fast
before its source/native matrices to supersede that candidate. Its Quality gate
fails as designed; no partial run becomes qualification. Repository validation
`42804858055` succeeds for that earlier head.

Clean corrected candidate `25382a4dc1dd592890f58f70ff0e1ba1323b180f`, tree
`6396545da24791d759328b0fccd197ba3ee0c90a`, repeats the same 13 actual kind
groups in 85.48 seconds. All 308 measured inputs remain unchanged and every
owned cluster, private-file, owner and caller-state check passes. Evidence:
`artifacts/issue77/full-kind-06/evidence.json`, SHA-256
`bb6695b6dc21d2761c1d8cfc7af7f96d466ae12ced9e77471ca971d3b3d520d8`.
Use the verifier invocation above with this fresh evidence path.

The fresh eight-case source/installed PTY run passes in 39.94 seconds, using
`--basetemp=/tmp/kuberich-77-installed-03`. All 304 wheel runtime files match
this source; `artifacts/issue77/installed-03/wheel-receipt.json` records SHA-256
`17ae25c2c4a885a5ff8f8954a32068d47688375070bfc9a70a8e93c6d0a449ab`.
The older 05/02 receipts remain historical after this runtime change.

## Completion limits

Full production coverage of at least 90% lines and 90% branches, at least 90%
changed-line coverage, all 125 critical modules at 100%, and every required
hosted exact-head job remain pending. The ordinary PR matrix has 27 jobs;
release-time manual six-environment
qualification and three repetitions remain separate. Published artifacts remain
0.4.0. This issue does not authorize tags, packages, hosting or DNS changes.
