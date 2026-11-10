# Local manifest workflow acceptance

Issue: M07 #67. Phase: v0.5.0. Templates remain #234 and Helm lifecycle remains
#233. This is an implementation record, not a completed phase qualification.

## Current status

Source/parser/filesystem, renderer, local editing, cluster batches and public UI
are implemented in the issue branch. Integrated candidate verification is in
progress. No stub or focused test count completes the issue;
full candidate coverage, installed/terminal/owned-cluster checks and required
hosted gates remain pending. No version/tag/package/hosting/DNS change is made.

The issue starts from protected main
`e11236e0a108c4ff4bf79a119648a02bc9a61bdc`, after #66/#334 passed all 27 quality
jobs and the app-bound Repository/DCO checks. Its qualified tree is
`c9df0c5be9405c126d6c6a6c5ef16d79a1a0ae70`. The predecessor merge is not evidence
for this issue's new code.

## Reviewed boundaries

- Physical root, no-follow traversal, finite local dependencies and frozen source
  bytes/hashes; listing and ordinary inspection do not launch helpers.
- Multi-document YAML/JSON and ordinary `List` expansion with cumulative resource,
  file, depth, parser-event and byte limits. Invalid sources are not silently skipped.
- Local builtin rendering only, with private staging/config/cache and no remote
  dependency, executable plugin or Helm expansion. No unrestricted-loader fallback.
- One-use editor disclosure and distinct local save; no implicit cluster effect.
  Generic configuration inspection masks scalar values, including generators and
  inline patches. Save/cancel outcomes retain already committed entry changes.
- Exact discovered destinations and safe fallback namespaces; create addresses
  have no fabricated UID. Existing objects retain UID/version-conditional writes.
- Strict server validation/diff, one-use batch confirmation, per-item revalidation,
  ordered partial/uncertain/unsent outcomes and no blind retry or compensation.
- Owned helper/parser/thread/request lifetime, read-only enforcement and safe
  machine-code admission errors. Raw error messages/request bytes are withheld.

See [ADR 0042](../../adr/0042-local-manifest-batches.md) and the
[user workflow](../../workloads.md#local-manifests-and-kustomize-in-development-source).

## Early actual API proof

The first exploratory trial, `artifacts/issue67/early-kind-01.json`, **failed**
at named-create dry-run receipt validation before any persisting create. Its
source stayed unchanged and its original log/report remain untouched. The
watch-capable ordinary resource parser required a persistent resourceVersion,
while a new dry-run object has none. The fix is confined to parsing that preview;
real successful POST/read/update/delete receipts retain their identity checks.

The first wrapper set its deletion flag only after normal completion, leaving
`false` on the failed trial even though the context manager deleted the cluster.
The original flag is preserved. `early-kind-01-cleanup.json` separately records
an actual Docker query for that exact owned label proving no node remains.

The second exploratory trial, `artifacts/issue67/early-kind-02.json`, **passed
14 checks** on kind 0.33.0/Kubernetes 1.36.4 with actual kubectl 1.36.4. All 287
measured code/helper inputs stayed unchanged. The report records a real generated
dry-run UID with no resourceVersion, followed by a real named POST with both.
Both update previews and exact conditional-patch validations leave the stored
version/data unchanged. Actual writes advance the version and preserve the UID.
Removing a previously managed key preserves a separately added live-only key.
Private delegation and owned kubeconfig invariance pass; cluster deletion and
owned-node absence are verified. Report SHA-256:
`2da9717331dcfee66b12d53208a1876aa69c2164430832c3e926aaca5904d2a5`.

These inputs were deliberately frozen **working-tree** source, including new
files, based on the protected commit above. This proves early API merge semantics,
not complete source/service/UI/cancellation/coverage or release qualification.
Later changes require a fresh final frozen candidate trial. No operator's active
context or customer configuration was used.

## Focused development evidence

The source lane's final critical diagnostic passes 162 cases. Manifest decisions
cover 305/305 lines and 92/92 branches, Kustomize decisions 91/91 and 64/64,
and the existing editing parser 139/139 and 56/56. These are scoped results;
filesystem/renderer/local-service results remain diagnostic profiles, not whole
production coverage. Original failures and their corrections are retained.

The cluster lane reports scoped real HTTP/process and existing mutation
compatibility cases, including one-use/source/scope rejection, exact preconditions,
partial/cancel/uncertain outcomes, helper cleanup and safe error receipts. Its
abstract async protocol arcs remain in coverage; no stub-invocation tests or
exclusions are introduced to inflate percentages.

Independent public service regressions also cover cancellation during accepted
deletion observation, admission consumption before coroutine entry, concurrent
confirmation, complete batch history and already-completed task publication.
Known persisted/accepted requests followed by a stop produce `Partial batch`;
an uncertain request retains precedence. No-op/absent rows do not fabricate
progress. The final source editor PTY set passes seven scenarios; fourteen
focused review/history UI cases pass. Installed entry points remain pending.

## Frozen DELETE dry-run failure and correction

The first complete owned-kind trial of committed candidate
`bcebe6127fb27bf9347376b7a2770ad20d7707ad`,
`artifacts/issue67/frozen-kind-01.json`, **failed** at finalizer-backed deletion
review. Measured source stayed unchanged, all service owners drained, and the
owned cluster was deleted with node absence verified. Earlier merge/Kustomize,
strict admission, quota, identity/conflict, partial-batch and RBAC checks passed;
that does not turn the complete trial into a success.

The failure exposed a request error rather than grounds to loosen receipt
identity. Kubernetes decodes nonempty DELETE `DeleteOptions` bodies instead of
their query options. A query-only `dryRun=All` therefore did not make this request
a simulation. The [pinned upstream handler](https://github.com/kubernetes/kubernetes/blob/v1.36.4/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/delete.go#L78-L117)
confirms this distinction. This new workflow is not integrated or published.

The owned metadata-only diagnostic `delete-receipt-probe-02.json` independently
compares ordinary and finalizer-backed objects. Query-only requests really
delete or mark the owned fixtures for deletion. With `dryRun: [All]` in the body,
both stored objects remain present with unchanged UID/version/finalizers and no
stored deletion timestamp. The finalizer preview retains the baseline version;
no receipt/version guard exception is justified by this observation. All measured
source inputs remain unchanged and owned cluster cleanup passes.

The earlier diagnostic `delete-receipt-probe-01.json` remains failed: an assertion
expected the ordinary fixture to survive a query-only request. Its wrapper set
the cleanup flag only on normal return; the original false flag is preserved.
The original log and separate `delete-receipt-probe-01-cleanup.json` verify exact
owned-node absence. This diagnostic does not qualify the corrected application.

The correction must derive a DELETE validation body containing `dryRun: [All]`,
retain the reviewed UID/version preconditions, and leave the confirmation's
persisting request unchanged. Fake APIs must model the real body-option semantics.
The complete verifier must independently GET both ordinary and finalizer-backed
objects after preparation and prove unchanged stored identity/version/deletion
state before confirmation. Final frozen application execution remains pending.

Final measured commands/results will be appended after the complete implementation
and frozen-candidate verification. The cumulative phase qualifier remains #82.
