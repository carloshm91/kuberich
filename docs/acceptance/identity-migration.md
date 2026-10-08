# KubeRich identity migration: #149

The maintainer chose KubeRich and confirmed acquiring kuberich.com. The migration
updates the distribution/import/CLI, UI identity, runtime paths, release/Homebrew/
security tooling and current documentation. The `kubetrol` console command delegates
to the same entry point; no duplicate production package is shipped. The private
version remains `0.0.1.dev0`.

## Private repository identity

The existing repository is now `carloshm91/kuberich`, retaining repository ID
`R_kgDOU7ZcRQ`, issue/PR IDs, history and private visibility. Authenticated old/new
API and SSH paths resolve to the same repository and preserved main commit.
The local SSH origin is `git@github.com:carloshm91/kuberich.git`.
Project 3 is now KubeRich roadmap, with the same project ID and private visibility.
No repository recreation, ownership transfer or visibility change occurred.

## Full Linux qualification

Frozen qualified commit: `47a2151800592e873f1b1107ec99925abda05d67`.
Production tree: `7f64b0f1e46acaa60280ef006f6a1bf4ccca70bc`.
Test tree: `52f0a76f8f5b7f7d925b30b1c426d1517a5f451b`.
The delivery documentation does not change either tree.

| CPython | Passed | Duration | Production lines | Production branches | Changed lines |
| --- | --- | --- | --- | --- | --- |
| 3.12.12 | 2,977 | 2110.55 s | 99.2858% | 97.3808% | 100% |
| 3.13.12 | 2,977 | 1584.61 s | 99.2858% | 97.3808% | 100% |
| 3.14.3 | 2,977 | 1157.30 s | 99.2733% | 97.3808% | 100% |

All 90 production modules remain in the denominator. All 34 critical modules
reach 100% lines and branches on every interpreter. Independent line, branch,
critical and changed-line gates passed without exclusions or weakened thresholds.
The CI-declared strict mypy command passed over 107 files. Ruff/formatting, plan/
link validation, whitespace and actionlint passed; actionlint's optional shellcheck
and pyflakes integrations were disabled rather than claimed as verified.

## Behavior, terminal and installation evidence

Focused preference/CLI/log/layout and actual installed-wheel metadata, alias and
migration checks passed 334 cases; independent quality/Homebrew checks passed
345 cases. Owned default-location installed CLI trials retain unknown/private
fields without displaying them, source bytes/read-only settings and effective
relative log destinations. Unit cases cover environment precedence, malformed/
special files, existing destinations, commit races, private permissions and
idempotence. Known legacy log/lock/archive headers remain usable; foreign-file
protections remain enforced. Ordinary loading, info and config check write no
preferences; migration requires an explicit command and never replaces a destination.

Full suites include real PTYs, source/fresh-wheel execution, SSH/tmux, resizing,
keyboard input, embedded-shell return, cancellation and terminal restoration.
Additional actual uv/pipx trials verified both commands execute and both disappear
on uninstall, outside the checkout. Fresh wheel/sdist installs, payload allowlists,
sdist rebuilding, unpublished release-candidate contracts and Homebrew generation/
publication guards passed. No native Homebrew/macOS result is inferred from Linux.

All eight owned Kubernetes rehearsals passed: contexts/discovery/list-watch,
lifecycle/cancellation, shells, forwarding, mutations, editing, workload operations
and the installed quickstart. Mutation/edit/workload rehearsals checked 8/12/12 real
API outcomes respectively. Every owned cluster was deleted and absence verified;
the maintainer's active context was not used. The pinned kind/node/kubectl/image
inputs remain unchanged. Quickstart used the earlier frozen wheel with identical
production content; final artifacts include the current README and passed build/Twine.
Locked/fresh runtime audits each cover 27 dependencies with no advisories or
accepted exceptions; artifact-linked inventories, SBOMs and local provenance were
verified. These local provenance sidecars are unsigned, not hosted attestations.

Final local development artifacts (not published):

- `kuberich-0.0.1.dev0-py3-none-any.whl`: `6bfaf43fcd8bf5c6d3c58a5b54c5a074c4d5a9e61b90e2f11dcd9d7fcbf9feec`
- `kuberich-0.0.1.dev0.tar.gz`: `2aaafb3532713408648112401de3c9b612407f2252fbcff7f6b059899ea1d99a`

## Retained controls and release limits

The initial focused run caught an obsolete help snapshot (326 other cases passed).
Initial matrix attempts caught obsolete single-entry-point and old-ASCII-logo
assertions; they were interrupted and retained. Corrected native terminal checks
passed 10 cases on each interpreter before the final complete green matrix.
An extra strict audit included two legacy untyped integration drivers outside the
existing CI type-check list and reported 61 diagnostics. Its output is retained;
the required typed runtime/tooling command is unchanged in scope and passes.

DCO passed on the signed issue branch. Hosted Actions could not start because of
the account billing restriction; the private local-verification exception applies.
Native macOS/full hosted qualification is mandatory before public release. Real
cloud/provider certification remains deferred to the maintainer's later opt-in
trials in #87; owned-kind synthetic credential contracts do not certify EKS/AKS.
No public artifact, tag, release, website/DNS or organization change was made.

Historical acceptance reports retain their original artifact names, source trees
and measurements. Raw local evidence: `/tmp/kuberich-149-evidence`.
