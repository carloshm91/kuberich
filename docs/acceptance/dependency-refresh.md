# Development and deployment dependency refresh

Issue: [#270](https://github.com/carloshm91/kuberich/issues/270).
Base: `d990a5e0273465874df24e1e790887520abeacff`.
Verification date: 2026-11-01 UTC. Host: Linux x86_64, CPython 3.12.12,
uv 0.10.4, Node 22.13.1, npm 10.9.2.

## Affected graphs and advisory scope

| Tooling path | Locked update | Primary advisories |
| --- | --- | --- |
| Development `pipx` | FileLock 4.0.12 → 4.2.1 | [SQLite lock database paths](https://github.com/advisories/GHSA-v4x8-3wr5-3wq8), [Windows SQLite side files](https://github.com/advisories/GHSA-9vhv-jxww-xfm5) |
| Standalone `PyInstaller` | Setuptools 84.0.0 → 84.1.0 | [Legacy wheel installation path escape](https://github.com/advisories/GHSA-xmj3-9gf7-h52w) |
| Deployment `Wrangler` → `Miniflare` | Undici 7.29.1 → 7.30.1 | [Content encoding denial of service](https://github.com/advisories/GHSA-xjj6-f33q-929c), [Subresource integrity verification](https://github.com/advisories/GHSA-f72v-6w45-q472) |

The FileLock advisories affect SQLite-backed `ReadWriteLock` and
`AsyncReadWriteLock` under local filesystem preconditions. Installed pipx uses
`FileLock` and `BaseFileLock`; its Python sources contain no `ReadWriteLock` use.
The Setuptools advisory concerns Windows legacy `Wheel.install_as_egg`, rather
than the ordinary wheel installation path tested here. PyInstaller's Python
sources contain no call to `install_as_egg`. These observations limit the
demonstrated exposure; they do not justify retaining affected versions.

Both Python updates satisfy the unchanged parent requirements: pipx 1.17.11
requires FileLock ≥4.0.9 and PyInstaller 6.22.3 requires Setuptools ≥42.0.0.
Their patched releases support Python 3.12–3.14. Only these two Python lock
entries change; the application requirements and version stay unchanged.

Wrangler 4.149.0's exact Miniflare pin requires vulnerable Undici 7.29.1.
The parent moves to Wrangler 4.153.0, which pins Miniflare
5.20261023.0-beta and its patched Undici 7.30.1. The preceding Wrangler
4.152.0 still pins a Miniflare release with Undici 7.29.1. Node ≥22 remains
required. This uses the upstream graph without an override; the Miniflare
dependency was already a prerelease. No claim is made that the affected HTTP
or integrity-checking paths are unreachable in deployment tooling.

## Measured checks

- Locked development and standalone synchronization passes in this issue's
  isolated virtual environment. Imports resolve to its own checkout.
- A strict, no-dependency-resolution pip-audit scan of the exact exported
  development, standalone and runtime requirements covers 114 packages with
  zero known findings and zero skipped packages on this host.
- An owned `npm ci --ignore-scripts` installation passes. `npm audit
  --audit-level=low --json` reports zero findings across 91 dependency entries.
  The host installation adds 40 packages; the lockfile audit also includes
  optional entries for other platforms.
- The installed Wrangler reports 4.153.0 and `pages deploy --help` succeeds
  without Cloudflare credentials or publication. `npm ls undici --json`
  confirms the exact patched parent chain, with no overridden node.
- Actual locked and fresh wheel installations each pass the strict runtime
  supply-chain gate for 30 dependencies, with complete SBOMs, original notices,
  bound lock/artifact hashes and zero accepted exceptions. Offline re-verification
  against the original wheel and source archive passes, as does Twine.
- The selected release-policy, supply-chain-policy, standalone-recipe,
  native-verifier, Pages, packaging and isolated-installer tests cover 470 cases.
  The first run passes 469 and correctly rejects a source archive built before
  a concurrent changelog edit. After freezing distribution inputs, all 32
  artifact/supply-chain cases pass in 125.16 seconds; the other 438 cases already
  passed. These include actual uv-tool/pipx wheel and source installations,
  terminal navigation/shell restoration and fail-closed release prerequisites.
- Ruff lint and formatting pass; strict application and release-policy type
  checking passes across 157 source files.
- Plan validation passes for 15 epics, 124 tasks, 63 capability families and 26
  CLI flags. The local site build/check passes for 71 pages and 3,446 links/assets.

The retained local evidence is under `artifacts/dependencies270` and
`artifacts/security` in the isolated issue checkout. The npm checks use distinct
owned user/global configuration files and no Cloudflare credentials. An
answer-only Argon review of the supplied diff and verified advisory metadata
reports no design, dependency-graph or policy blocker; it does not replace the
executed checks.

The final wheel SHA-256 is
`059ac1147471d54152542cd48307970d92b97e12c27e6fc31842690cc13332a6`;
the source archive SHA-256 is
`fa2ad4ad0f649dbd2cf6e3f0eb19c31e7dc116cd6b59f6522e60cc7ae292913a`.
Rebuilding into the owned retained directory reproduces the exact bytes bound
by the successful frozen supply-chain reports, and offline verification passes.
These are local 0.2.0 diagnostic candidates, not a new published version.

## Linux native diagnostic

The owned native build completes with PyInstaller 6.22.3, Setuptools 84.1.0 and
the hash-pinned full CPython 3.12.15 distribution. Its 722 archive entries match
the recorded inventory, including original dependency/interpreter notices and
the replaceable Pyte source. After extraction to an owned temporary directory
outside the checkout, both `--version` and `--help` exit 0 without stderr.

Archive SHA-256:
`f005ae1b8779174f84e3850081d1c0be9025841eb16c33b9caecb7b097bb3d3f`.
This build explicitly records `diagnostic_only: true`, `source_clean: false`
and `runtime_qualified: false`. The host contributes glibc 2.38 symbols, above
the release's 2.35 floor, so `compatible_glibc_floor` is false. A passing local
build and CLI smoke do not override that refusal or qualify a public archive.

## Release and platform limits

The foundations phase lists this maintenance issue as a required extra. The
release-policy regressions reject an unfinished refresh, its omission from the
phase plan, and its omission from later cumulative release qualification.
Earlier 0.1/0.2 phases do not acquire this prerequisite.

No exception, advisory dismissal, license policy change or weaker audit gate is
added. GitHub's alert state must be checked after the parent merges the verified
lockfiles; open default-branch alerts cannot be reported as closed from a local
branch. No application production code changes, so changed production coverage
is not applicable. No full suite, global coverage or performance run is claimed
here. Linux diagnostics do not qualify macOS, arm64, Windows, the full Python
matrix, public artifacts or a future registry/advisory snapshot.
