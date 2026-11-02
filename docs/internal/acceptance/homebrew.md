# D03 #37 Homebrew source delivery qualification

The formula generator consumes a verified canonical release bundle, pins all
27 runtime source archives and installs them in a private environment. The
production release job verifies matching published bytes before proposing an
immutable, formula-only tap PR. No public tap, package or release was created.

## Executed Linux behavior

An owned Ubuntu container used Homebrew 7.0.8
(`a57af195cf9d7addb48bdb1204c9151313cd0057`) in its standard Linux prefix and
Homebrew Python 3.14.8. The actual local `0.0.1rc1` source formula passed:

- `brew style`, `brew audit --strict` and source installation of all 27 resources;
- `brew test`, CLI help/version, config validation, info, typing/TCSS assets and
  installed dependency consistency;
- an actual formula revision 0→1 upgrade of the same RC, followed by another
  functional test;
- all-version uninstall, with the CLI absent and the owned configuration retained.

The configuration SHA-256 remained
`7e118c9aacd38cd64e5fcc640651969328b40483c1221f2fac1e0f42eb9bf8b8`;
its read-only setting and 1.5-second refresh survived upgrade and uninstall.
This is a revision upgrade, not a public upstream-version upgrade. The private
candidate used the official PyPI host with a scoped alternate simple-path spelling
during a transient endpoint timeout. Runtime archive hashes remained enforced.
Isolated build-backend resolution by Homebrew is not a hermetic toolchain claim.

Owned HTTP and actual bare-Git tests exercise public-channel identity/hash/tag
refusal, scoped cross-repository access, downgrades, altered branches and partial
PR failures/retries. They never force-push, merge or publish a real tap. Actual
canonical RC builds/audits/installations qualify the local bundle contract.

## Complete measured matrix, 2026-10-07

Frozen implementation `c66229e996b9c4ec1cdfa34a53e9e9701dd65f1c`, based on
`5fc0d4ed541b255aadb8d421ef4b76b972211e8e`:

| CPython | Passing tests | Production lines | Production branches |
| --- | --- | --- | --- |
| 3.12.12 | 2,247 | 6419/6451 (99.50%) | 1891/1936 (97.68%) |
| 3.13.12 | 2,247 | 6419/6451 (99.50%) | 1891/1936 (97.68%) |
| 3.14.3 | 2,247 | 6312/6344 (99.50%) | 1891/1936 (97.68%) |

All 29 critical modules reached 100% lines/branches. Every matrix passed Ruff,
formatting, strict types including Homebrew/release tooling, plan validation,
build/Twine, and artifact-linked installed-runtime security gates. Each retained
59 UI SVGs and 140 terminal summaries. Changed application lines are N/A (0);
the production source tree is unchanged.

The first Python 3.14 attempt failed an existing tmux native-handoff readiness
assertion after 885 passing tests. The same frozen code passed the isolated case
and then the complete 2,247-test repetition. Its cause is not established; the
failed log/terminal capture remain separate from successful evidence. Initial
Homebrew setup/style/installation attempts and the ordinary uninstall check also
remain retained. Ordinary uninstall left an older Cellar revision when cleanup
was disabled; `brew uninstall --force` then removed every owned version.

Raw commands, logs, coverage, security bundles, RC artifacts, 29 source-build logs,
configuration digests and failed attempts are retained in
`/tmp/kubetrol-37-evidence`. The final evidence-document commit preserves the
tested executable, test and workflow trees and all release-policy inputs.

## Remaining release qualification

macOS/arm64, strict online audit, live cross-repository update PR, public channel
ownership and public version-to-version upgrade remain D04 #40. Hosted jobs cannot
start under the account billing restriction; DCO and measured private local checks
govern this merge under the temporary quality workflow. Public publication still
requires explicit maintainer approval and all release gates.

See [Homebrew delivery](../homebrew.md) for commands and update policy.
