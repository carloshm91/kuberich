# Phased release preparation: Refs #89

Scope: preparatory tooling/docs for the maintainer's 2026-10-09 phased-release
direction. Development remains `0.0.1.dev0`; #89 stays open. This supersedes
#154's first-public-1.0-only policy, preserving its dated evidence. No version
bump, dispatch, tag, package, organization/tap, website/DNS or source transfer
occurred in this PR.

## Decisions exercised

- The actual 79-task plan preserves all feature dependencies. D10 intentionally
  changes to D06/v0.1.0. Selected/prior qualification gates themselves, transitive
  prerequisites, common launch issues and cumulative phase extras must close.
  0.1 includes #53/#54/#123; closed #53 with open #52 still blocks. Future D07
  scope does not block 0.1. Unknown minors, malformed/duplicate/cyclic plans,
  remapped issue IDs/URLs or wrong repositories fail before any issue request.
- Only initial 0.1.0/RC can transact with #89 open; patches/later phases require
  initial activation closed. Canonical source/package/tag, actual DCO origin,
  six-native release dispatch, audited original artifact and protected approval
  contracts remain.
- Public preparation requires useful committed authored notes with exact bounded
  regular Git-blob bytes, rejects ignored/untracked/link/oversized substitutes,
  and freezes an optional reviewed generated preview through the actual dispatch
  env/CLI paths. Owned HTTP uploads send the exact body, never regenerate it and
  reuse identical bytes after partial failure. Changed body/identity fails before
  upload. Validation remains read-only.
- The prepared Homebrew destination is organization-owned
  `kuberich/homebrew-tap`, yielding `kuberich/tap/kuberich`; same-named User or
  personal/wrong destination is refused. No namespace ownership is established.
- Current guides distinguish fresh installs from real upgrades. D04/D06 retain
  actual manager-supported two-artifact local updates; #89 owns public channels.
  First 0.1 has an identified local baseline, no fictional published predecessor;
  later releases use the actual previous supported public artifact.

## Scoped local evidence

Working-source CPython 3.12.12 commands:

```sh
uv run pytest -q tests/quality/test_release_policy.py tests/quality/test_release_transport.py tests/quality/test_release_notes.py tests/quality/test_homebrew.py --no-cov --junitxml=artifacts/phases-89/notes-policy-transport.xml
uv run pytest -q tests/quality/test_release_notes.py tests/packaging/test_release_candidate.py::test_actual_canonical_rc_build_audit_bundle_and_installed_version tests/packaging/test_release_candidate.py::test_rehashed_authored_notes_cannot_replace_committed_body tests/packaging/test_release_candidate.py::test_actual_cli_dispatch_preview_and_file_retry_preserve_frozen_combined_body --no-cov --junitxml=artifacts/phases-89/committed-notes-cli.xml
```

The first command passed 286 cases in 26.35 seconds before the additional four
Git-object negatives. The second passed 32 cases in 129.75 seconds, including the
real owned canonical build, locked/fresh audits, bundle and installed CLI, exact
preview env/file round trip and rehashed authored-body rejection. The synthetic
1.0.0rc1 fixture remains local and unpublished. Strict typing passed the five
changed release/audit scripts, and standalone plan validation passed 12 epics,
79 tasks, 64 capability families and 26 flags. An earlier targeted test passed a
Version object to a string interface and failed; that fixture was corrected,
and its initial XML is retained as diagnostic evidence.

The final scoped command was:

```sh
uv run pytest -q tests/quality tests/packaging --no-cov --junitxml=artifacts/phases-89/final-focused.xml
```

All 735 cases passed in 713.59 seconds, without errors/skips. Original log/XML and
`focused-source-snapshot.json` remain under `artifacts/phases-89`; the 517-file
snapshot hash is `fe07b8400331f5eec0273a2b333ca367f89aaad9417a9104fb734906401d4d78`.
Files remained stable during that cohort; later receipt/prose corrections are
separate from these working-source results. Complete Ruff/format/plan/diff checks
passed, and strict mypy passed 137 application/development files. No duplicate
full local application suite was used instead of mandatory hosted checks.

The local site build/link checks passed 49 pages and 1,726 local references;
wheel/sdist build and Twine passed. Chrome 143.0.7499.169 checked all 49 desktop
and 49 mobile pages with zero violations, browser failures or external requests.
Keyboard, 320px layout, clipboard and no-JavaScript checks passed; the Node audit
reported zero vulnerabilities. The original browser report binds manifest
`c21f22c5203dd10f16aa69c03a24e09efd567c755ef92dc4468fd4fe8fba6e87` with
140 source digests and 63 payload files. These are working-source local receipts;
the signed-head artifact binding and required hosted checks remain pending.

Final frozen-source/native/package receipts remain pending. Runtime source
inventory stays 109 modules/43 critical; no executable application changes means
production changed-line coverage is N/A. Tooling checks do not establish a new
application coverage percentage.

## Actual protection and remaining owner gates

Root independently configured/re-read source main and both publication
environments at 2026-10-10 02:09:56 UTC, source baseline `422c946`. Main has
strict app-bound Quality gate/Repository checks (GitHub Actions app 15368) and
DCO (app 1861), admin enforcement, PR/linear/conversation controls and disabled
force pushes/deletions. Zero required PR approvals preserves solo delivery.
`release` and `release-test` require maintainer `carloshm91`, protected branches,
`can_admins_bypass=false` and `prevent_self_review=false`. The actual policy
validator passed both returned records. Receipt:
`artifacts/logs54-root/phase89-roadmap/live-protection-review.json`; no secret or
publication changes, full-release-qualified=false. Earlier private HTTP403
evidence stays historical.

Root also reconciled/re-read 18 existing gate/epic/milestone items at
2026-10-10 02:23:31 UTC, preserving all open states and measured history, creating
no tickets. Receipt `artifacts/logs54-root/phase89-roadmap/live-roadmap-migration-receipt.json`;
#89 is now v0.1.0 and remains open.

Later baseline main run 38014888892 failed Linux 3.13: 4,091 passed/1 failed, the separate
backend tiny-line HTTP/retention heartbeat 175.396 ms exceeded unchanged 150 ms.
Linux 3.12/3.14 passed; aggregate failed correctly. The original failure is retained
in `artifacts/logs54-root/phase89-roadmap/main-linux313-failure.log`. A single
source-unchanged full-catalogue/selected-node default-GC/CTracer diagnostic passed
but neither reproduced nor explained it. Existing [Q03 #50 diagnosis](https://github.com/carloshm91/kuberich/issues/50#issuecomment-6092751782)
retains remediation before first-phase qualification. No source/budget/GC change
or retry-only qualification occurs here; prior #54 original green PR receipts
remain identified as historical evidence.

Actual PyPI/TestPyPI ownership/OIDC/attestation, organization/tap control, real
upgrades, all six release environments, three exact-candidate fault rehearsals,
promised standalone/platform outputs and approved public channel/domain/site
activation remain incomplete. #150 qualifies exact-candidate guides/site with
owned/local installation before publication; #89 owns subsequent external
activation/verification. The current initial0.1 issue snapshot has six open
prerequisites (#150/#123/#40/#49/#51/#50), plus #89 activation. No readiness or
product-publication claim follows from this preparatory PR.

## Native prerequisite and rebased preparation

The original frozen phase candidate `5e43489ed51dd1dd9149c92a2e1e1ad5dbe995fc`
failed required run `38018066077`; it was not rerun or merged. Original Linux
3.13 heartbeat and macOS observer/attach failures are retained in
[native verification evidence](native-verification-prerequisites.md).
PR #173 independently qualified its corrections in all four development native
environments and merged as `6c5cb3e358b316feca4754de4ca977b1ef3ce984`. This phase
preparation is rebased onto that actual main commit and requires its own new
head-bound hosted checks. The prior successful local phase tests and native
prerequisite checks remain separately scoped; neither converts the old failed
phase candidate into a success nor completes D10/Q03/publication.

On rebased source `1ae07f046103ce1db034d8695abaacd5bce4fdd3`, the following
scoped command passed 314 cases in 27.15 seconds with no skips/errors:

```sh
uv run pytest -q tests/quality/test_release_policy.py tests/quality/test_release_transport.py tests/quality/test_release_notes.py tests/quality/test_homebrew.py tests/quality/test_ci_policy.py tests/quality/test_backend_heartbeat.py --no-cov --junitxml=artifacts/phases-89/rebased-focused.xml
```

Ruff passed, all 464 Python files were already formatted, and required strict
application/tooling mypy passed 133 files plus the four site scripts. The plan
validator retained 12 epics / 79 tasks / 64 families / 26 flags, and both site
surfaces passed build/link/digest validation (49 pages / 1,726 references /
64 files). These rebase checks do not replace final-head native, package or
browser checks; hosted qualification remains pending on the pushed signed head.
