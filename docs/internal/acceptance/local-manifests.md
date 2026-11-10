# Local manifest workflow acceptance

Issue: M07 #67. Phase: v0.5.0. Templates remain #234 and Helm lifecycle remains
#233. This is an implementation record, not a completed phase qualification.

## Current status

Source/parser/filesystem, renderer, local editing, cluster batches and public UI
are implemented in the issue branch. Frozen owned-cluster and source/installed
terminal trials pass. The protected PR enforces complete source/platform suites,
production/critical/changed-line coverage, native packaging and repository checks
on its exact final head before merge. Local scoped results below do not replace
those checks. No version/tag/package/hosting/DNS change is made.

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
focused review/history UI cases pass. See the final installed trial below.

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

The correction derives a DELETE validation body containing `dryRun: [All]`,
retain the reviewed UID/version preconditions, and leave the confirmation's
persisting request unchanged. Fake APIs must model the real body-option semantics.
The complete verifier independently GETs both ordinary and finalizer-backed
objects after preparation and prove unchanged stored identity/version/deletion
state before confirmation. The corrected frozen application trial follows.

## Frozen application and installed evidence

Signed-off corrected candidate `d8b484fff9149fea4bce0d5d94e877e75b34d99d`
passes `uv run --locked python -m scripts.verify_manifests_kind --kind VERIFIED_KIND
--kubectl VERIFIED_KUBECTL --docker /usr/bin/docker --evidence FRESH_REPORT`.
The pinned tool hashes are retained in the report. `frozen-kind-02.json` records
58 checks, 293 unchanged measured inputs, preserved owned kubeconfig/sentinel,
drained services/workers/private delegation, and verified owned-node deletion.
Report SHA-256: `0d668fc3ae618be960a03cbf44fe1d168cf05fb9bcc177356a8c3d8d12be801a`.

This includes actual declarative create/update/managed-field removal, unchanged
no-op review, multi-document/directory/local nested Kustomize, explicit mixed
namespace/cluster scope, strict schema/immutable/quota denial, service-account
revocation, UID/version and atomic POST conflicts, partial apply, guarded deletion
and finalizers. A loopback forwarder holds the response after a real API PATCH
commit: Stop retains uncertainty, does not replay it and leaves later targets
unsent. Holding observation after an accepted DELETE retains its accepted result
and stops later deletion. Public Pilot Validate/Confirm controls cause real apply
and delete effects only after their separate reviews.

The final source/installed terminal command passes **9 cases in 28.33 seconds**:

```sh
uv run --locked pytest tests/terminal/test_local_manifests.py tests/packaging/test_distribution.py::test_installed_local_manifest_editor_save_and_terminal_restoration --basetemp=/tmp/kuberich-67-installed-pty-01 -n 0 -q
```

Both console/module wheel entry points run outside the checkout in fresh
environments at 80×24. Source scenarios cover success, no-op, editor failure,
malformed output, Ctrl-C, SIGTERM and repeated editing, including larger viewport
and resize/restoration assertions. `installed-pty-01.log`/XML retain the result.

Ruff passes and formatting checks 1,199 files. The actual workflow target union
passes strict mypy for 341 source files. On each separately selected Python 3.12
and 3.13 environment, 25 CLI/config cases pass. Generated references, plan and
163 focused CLI/documentation/CI/qualifier cases pass; the original catalog-count
failure is retained separately. The critical inventory now contains 121 modules;
whole-production gates enforce every required 100% critical line/branch result.

The frozen startup trial passes its hard output/import/RSS/frame/ownership
contracts. Offline/import targets are met. Five initial frames measure
1,006.49–1,029.17 ms against the unchanged 600 ms advisory 0.x target; the miss
remains in `startup-01/report.json`, with strict negative controls preserved.

The complete local covered run `full-01` was deliberately interrupted with
SIGINT to avoid duplicating the mandatory complete hosted source/platform matrix
after final guide corrections. It exits 2 with **637 passed in 1,056.97 seconds**,
not a passing complete-suite or coverage gate. The original log/XML, partial
coverage, exact tracked input snapshot and interruption reason remain retained;
all owned pytest workers drain. Final authoritative whole-suite coverage and
platform receipts belong to the issue PR's exact-head Application quality run.

These trials do not certify real cloud providers, the operator's cluster, or a
published 0.5 artifact. The cumulative phase qualifier remains #82.
