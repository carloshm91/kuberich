# Enter navigation acceptance evidence

Qualified on Linux on 2026-10-05 for issue #115 / PR #116. The full matrix
tested frozen commit `2cd4895b9a9c66de0b8b4c4c4762031fd8debd91`. The final
documentation commit preserves these application, test and script trees:

- `src`: `175530aa9b3d5c9f67ddcdac0597a3d9f3c53f1b`
- `tests`: `51dc19a99f940e5b6eccb1634737b4987492d0c9`
- `scripts`: `c4893db3da5afebeae11cd943c8dca2e9d092b04`

## Measured gates

Each environment used locked dependencies and the actual stated interpreter,
specified with `--python` on every uv invocation. All production modules remain
in the coverage denominator; independent gates inspect lines and branches.

| Actual CPython | Tests | Production lines | Production branches | Changed lines |
| --- | ---: | ---: | ---: | ---: |
| 3.12.12 | 1,242 passed | 4,335 / 4,353 (99.59%) | 1,229 / 1,254 (98.01%) | 103 / 103 (100%) |
| 3.13.12 | 1,242 passed | 4,335 / 4,353 (99.59%) | 1,229 / 1,254 (98.01%) | 103 / 103 (100%) |
| 3.14.3 | 1,242 passed | 4,258 / 4,276 (99.58%) | 1,229 / 1,254 (98.01%) | 103 / 103 (100%) |

All **22 critical modules** reach 100% lines and branches independently. The
container screen also reaches 100% lines and branches. Ruff, formatting (167
files), strict mypy (56 sources including gate scripts), plan validation,
independent coverage gates, changed-line gates, wheel/sdist builds and Twine
metadata checks pass. Every interpreter produced 33 UI SVGs and 31 real-PTY
restoration summaries. Each summary confirms terminal attributes, alternate
screen, cursor and reporting-mode restoration. Packaging tests rebuild the
sdist and exercise console/module entry points from fresh installed wheels
outside the checkout.

The server interruption left the completed test runs without their final gate
and build steps. Those steps were completed against the same frozen trees
after command execution was restored; no application or test edits intervened.

## Behavior evidence

The original arrow/Enter regression was reproduced before the fix. Pilot cases
at 40×12 and 100×30 cover namespace prefixes and bare `:ns ` suggestions, command
and case-sensitive context completion, literal Enter, Tab, editing, focus and
scope changes. Arrow selection followed by Enter submits the current suggestion
once instead of reopening a selector for the typed prefix.

Eleven container Pilot cases cover single/multiple containers, regular/init and
restartable init Sidecar labels, compact layouts, scrolling, Enter/l, buttons,
container switching and Esc through both retained parent views. They cover
literal hostile text, delayed duplicate selections, row identity captured before
the cursor moves, scope invalidation, watched UID deletion/replacement and UID
replacement between the captured snapshot and the log request. Existing log
tests still exercise cancellation, failures, redaction and bounded retention.

Source and fresh-installed console/module PTYs send actual Enter bytes through
pods → containers → logs and return with Esc. Namespace PTYs send arrows and
Enter, including bare `:ns `, and verify the requested namespace rather than a
reopened picker. Initial qualification exposed test synchronization assumptions:
the terminal trials now wait for the requested namespace's suggestions/rows,
and the viewport trial explicitly selects its starting row. The controlled
blocked-projection UI case uses paste to keep input inside its fault window.
Independent typing and PTY trials remain. The final full suites above pass.

## Owned Kubernetes qualification

The real API trial passed using kind 0.33.0 and Kubernetes 1.36.4, with node image
`kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`:

```sh
uv run --locked --python 3.12.12 python scripts/verify_contexts_kind.py --kind /tmp/kubetrol-tools/kind --evidence artifacts/cluster/context-sessions.json
```

Only owned cluster `kubetrol-test-2974cc227749` was created and deleted, using an
explicit temporary kubeconfig. The Ready CoreDNS fixture exercises actual
pod → container → log Enter navigation, selected UID, current logs, existing
log controls, both Esc returns and preserved table state. Arrow/Enter selects
the namespace suggestion. Existing backend/TLS/client-certificate, discovery,
pagination, watch/recreation and owned cleanup checks also pass.

This trial ran at `b2bd2cf63ece254dd226ece07bcd7aaab5c984d5`, whose `src` and
`scripts` trees exactly match the final tested commit. The later commit changes
test synchronization only. No developer kubeconfig or user cluster was used.

## Reproduce and retained evidence

Run the [locked quality gates](../quality.md) in separate 3.12/3.13/3.14
environments with explicit interpreters. After merge, compare changed lines to
pre-merge base `ee86615062aa458177da3b0290184cb5d4091265`, rather than current main.
For focused behavior:

```sh
uv run pytest tests/ui/test_navigation.py tests/ui/test_containers.py tests/terminal/test_navigation.py tests/terminal/test_logs.py
```

Evidence is archived at `/tmp/kubetrol-115-evidence`: summary.json,
per-interpreter coverage/diff reports, validation logs, distributions, UI SVGs
and PTY records, plus kind.json/kind.log and four real-cluster SVGs. Initial
qualification evidence is retained separately under `initial`; it is not
reported as the final passing matrix. Temporary local artifacts can be
regenerated. See the [minimal operator trial](../first-preview.md#enter-navigation-feedback-115--current-trial).

## Qualification limits

Hosted Actions run `37361150602`, including job `111935767701`, has zero steps
and the account payment/spending-limit annotation. DCO passed on the tested
head. Delivery uses the maintainer-authorized [temporary local workflow](../quality.md#temporary-private-development-workflow-when-actions-is-unavailable);
hosted failures remain visible. macOS/full hosted qualification is still
required before public release. Actual provider credentials, SSH/tmux, native
clipboard and sustained maximum-load performance retain their qualification
tasks. This work publishes no package, tag or release.

The container table contains names/types from a captured pod snapshot. Live
container health and ephemeral debug containers remain later work. UID checks
reject stale captured targets but do not create an atomic Kubernetes UID
precondition for logs. See the [navigation contract](../container-navigation.md).
