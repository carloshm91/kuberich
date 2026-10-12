# First channel activation

The product/site preparation closed #150 with [PR #188](https://github.com/carloshm91/kuberich/pull/188)
and main `c9a50b60ec6e1cae17978ddc9baf2894e45418ff`. Exact-main
[qualification 38164232365](https://github.com/carloshm91/kuberich/actions/runs/38164232365)
passed six source combinations and four native archives. Independent original
reads measured 99.09–99.14% lines, 96.84–96.97% branches, 100% changed lines
and 100% designated critical modules. The selected wheel SHA-256
`4d3db9914c43f5c6351a5393478aa6991a0025cf279796d93d2c8d3c3a812611`
is identical to that used in all three consecutive owned-cluster rehearsals.
The same source's routine main run and originals passed too. Three native
Homebrew upgrade/uninstall rehearsals and 57-page real-browser checks retain
their separate receipts in #150. These are product preparation results, not
public-channel availability.

## Real dry-run permission finding

The read-only owner CLI preflight passed the actual main/DCO/matrix/protection
and live phase gates. The first real Actions
[dry-run 38168361829](https://github.com/carloshm91/kuberich/actions/runs/38168361829)
then failed the preflight GET with HTTP 403. Its Validate job failed; Publish
was skipped. Original full logs/run metadata are retained in the issue worktree.
No release tag, package, tap, final website or DNS publication occurred.

The branch-protection endpoint requires Administration read; the Actions token
does not support that permission. An unauthenticated read also returned 401.
The public environment endpoint remains readable; it does not solve access to
branch protection. See [GitHub's permission contract](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection).

## Correction and remaining qualification

The release workflow passes a separately configured repository Actions secret
`RELEASE_PROTECTION_TOKEN` only to the five release commands that perform
preflight, under `KUBERICH_PROTECTION_TOKEN`. The GitHub client sends it only to
the exact main-protection GET and refuses writes/body-bearing reads there.
Other reads and publication writes use their existing job token. Validation
and publication jobs declare read-only checks, PR and issue permissions needed
by their qualification queries. Contents write, OIDC and attestations remain
confined to the protected Publish job. Missing setup fails before network.

Owned HTTP regressions require the protection-specific authorization, reproduce
the old 403 and verify credential routing across the complete preflight. They
retain source/version, DCO, full matrix, audits and protection refusal cases.
Additional cases reject protection writes before I/O and absent CLI credentials
without exposing token values. Workflow checks preserve read-only validation,
default dry-run, main/owner dispatch, narrow secret exposure and no rebuilding.

Local verification and the issue-linked PR's hosted results must pass before
merge. The owner must configure the single-repository Administration-read
credential using [the release instructions](../releases.md#owner-prerequisites).
Then qualify the merged candidate and rerun the real dry-run; a unit fixture
does not establish that the owner credential or Actions API permissions work.
No hosted success or public availability is claimed before those actual results.

Local correction evidence: 327 release-policy, owned-HTTP transport, notes and
Homebrew-formula regressions passed in 293.38 seconds. Ruff check and the
537-file formatting check passed; strict types passed for both release modules.
The rebuilt site still has 57 pages, 2,336 local references and 72 files, with
manifest SHA-256 `ad38838c5645811e39f72b5d6a3b5c319611716877a5ee10ebb22ab495e5a1f1`,
identical to the already browser-qualified bytes. Application source is unchanged;
no new application coverage measurement is claimed by these controller tests.

PyPI/TestPyPI publisher ownership, approved public tap/scoped credential,
immutable publication, public install/upgrade/uninstall, final Pages/custom
domains and HTTPS/rollback verification remain #89. The separate roadmap
project remains private. This correction does not authorize any publication.

## First approved TestPyPI attempt: SBOM parser boundary

The maintainer configured the repository protection reader, both pending index
publishers, the organization-owned public tap and its scoped update credential.
Exact main `444209b794d17a0bf1aeb7e98e32d8433e5f6e66` passed all six source
and four native jobs in
[38173478727](https://github.com/carloshm91/kuberich/actions/runs/38173478727).
The actual [dry-run 38177380823](https://github.com/carloshm91/kuberich/actions/runs/38177380823)
passed; its original 21-file bundle matched independent preparation byte for byte.

After explicit artifact-channel approval and the maintainer's protected
`release-test` review,
[38191308923](https://github.com/carloshm91/kuberich/actions/runs/38191308923)
failed at **Attest the audited installed wheel SBOM**. Build provenance attestation
had succeeded, but SBOM attestation rejected the report as an unsupported format.
The PyPI upload step was skipped: this attempt uploaded no Python distribution
and created no production tag, GitHub Release or Homebrew formula. The failed
original run/jobs/logs/artifact ZIP and its approval are retained.

The reproducible CycloneDX producer intentionally omits `serialNumber`. That is
valid under its schema, but the
[pinned action parser](https://github.com/actions/attest/blob/1e69f48acb82d1966a394da916b4c1698aa569d6/src/sbom.ts)
requires a nonempty identifier. The earlier schema-only gate missed this consumer
requirement. Artifact attachment now assigns a deterministic UUIDv5 URN from the
complete document after adding wheel/sdist/lock/scope bindings. It excludes the
identifier itself, preserving reproducibility and independence from key order or
a producer-supplied serial. The schema gate rejects missing identifiers before
protected publication; the SBOM remains fully validated CycloneDX 1.6.

Local evidence: 68 policy regressions passed in 3.93 seconds, including missing
or malformed identifiers, stable ordering/preexisting-serial behavior and distinct
identifiers after root/dependency/artifact/lock/scope changes. Ruff, 538-file
formatting and strict types for both supply-chain modules passed. An owned Node
22.13.1 rehearsal ran the unmodified pinned TypeScript parser
(SHA-256 `266f37693d86bfee74d0008944c154aeea62b59002eac18e009e48892bd038b3`):
both original locked/fresh reports were rejected, and both copies with only the
serial added were accepted. This is parser evidence, not a complete hosted
attestation/OIDC upload result. Application source is unchanged. Fresh original
audits, protected PR checks, exact-main qualification and actual approved
publication remain required before claiming channel activation.

## Installed-terminal fixture repair

The first SBOM-correction PR matrix
[38192572191](https://github.com/carloshm91/kuberich/actions/runs/38192572191)
failed on Linux/Python 3.12: 4,802 tests passed, two were skipped and two installed
connection cases failed. The other three source jobs, all four native jobs,
Repository checks and DCO passed. Original logs, terminal transcripts and the
failed Linux artifact ZIP are retained; its SHA-256 is
`f2aebe9cb89756b9d2ce024adfeb914cfb0e46795778d2e177c423be2ff6a2e9`.

The normal connection test used a 250 ms request budget under host load. Its
failed terminal context could terminate the session owner before the actual
child exited, leaving the diagnostic-file lock unavailable for the next case.
The terminal fixture now keeps its owner alive to reap that child, with bounded
forced termination. Each installed case owns a separate state directory. The
normal connection budget is two seconds; an owned delayed LIST response exercises
that path. The separate eight-second quiet-watch renewal limit and all visible
state assertions remain enforced.

Local verification: 35 real-terminal observer/context/shutdown/installation
regressions passed in 58.30 seconds, including delayed and ignored SIGTERM,
released locks, reaped children and closed descriptors after injected failures.
An isolated negative control kept the old owner source unchanged: its child
survived context exit and held the lock; the corrected owner reaped the same
owned child and released the lock. Both controls ignore SIGHUP, and the diagnostic
reaps its own negative-control orphan. Ruff and the 539-file formatting check
passed. Application source remains unchanged. The revised terminal fixtures
require fresh hosted qualification; previous consecutive owned rehearsals remain
historical evidence, not new runs of the revised fixtures. No failed required
check has been waived and no distribution was uploaded by these checks.

## Actual artifact-channel activation: 2026-10-12

The complete exact-main matrix [38198965903](https://github.com/carloshm91/kuberich/actions/runs/38198965903)
passed on `3dbf9c0118193aa11635baea6ae2a0b36bee4c6e`; independent original audits,
coverage/critical gates, native enrollment and canonical preparation passed.
Three fresh revised-fixture owned rehearsals passed all 44 commands and thirteen
scenario families per round, preserving caller configuration and cleanup.
The actual [dry-run 38202631838](https://github.com/carloshm91/kuberich/actions/runs/38202631838)
passed and its original candidate matched independent preparation.

[TestPyPI 38205728318](https://github.com/carloshm91/kuberich/actions/runs/38205728318)
succeeded on attempt 2. Its first attempt passed build/SBOM attestations and
uploaded both distributions, then failed immediate index verification because
not every file was visible. A later actual index read verified both original
digests before the identical-byte retry; the retry skipped already present
uploads and passed the same hosted verification. Both attempts' originals are
retained. This records changed external index state, not a waived check.

[Production 38206308157](https://github.com/carloshm91/kuberich/actions/runs/38206308157)
passed actual protected review, attestations, OIDC upload, immutable annotated
`v0.1.0`, complete matching PyPI verification and GitHub attachment publication.
The [public release](https://github.com/carloshm91/kuberich/releases/tag/v0.1.0)
published at `2026-10-12T05:07:35Z`. All **24** public attachment downloads match
the qualified candidate, including all four native archives and the manifests.
The wheel remains SHA-256
`4d3db9914c43f5c6351a5393478aa6991a0025cf279796d93d2c8d3c3a812611`;
the source distribution is
`c3b4fa5fae7877b19bdcb823e955952d594325827c175b6652f77e2d296cb3f3`.

Actual public PyPI-by-name uv and pipx installations passed version/help, default
preference validation, no-op upgrade and uninstall outside the checkout, with
owned installer/configuration state and no active user kubeconfig. The first uv
probe supplied an explicit missing preference path and correctly returned exit
3; its original diagnostic is retained. The default-preference probe then passed
without changing product code. Public Linux x86_64 archive extraction, CLI checks
and owned-tree removal passed; the other three public archives match their real
hosted native trials. No prior public version upgrade is invented.

[Homebrew PR #1](https://github.com/kuberich/homebrew-tap/pull/1) passed actual
app-bound Linux/macOS formula checks and DCO in
[38206633105](https://github.com/kuberich/homebrew-tap/actions/runs/38206633105).
Both hosts ran style, strict online audit, source installation, CLI tests and
uninstall against the immutable public PyPI source/resources. Protected squash
merge `ec62f339cdb71bf379724fcb2753326dd26ad570` preserves
`carloshm91@gmail.com` and the maintainer sign-off. The actual public main formula
matches the checked PR; SHA-256 is
`4a0696cc1f126deca0cf18706377a7210efdf9f3c92702e733617df8ba63b958`.
Original run/jobs/logs, formula and enforced-protection receipts are retained.

Artifact channels are available. This documentation update changes no published
tag or package bytes, and building its revised website sources does not deploy
them. Final website/custom-domain/HTTPS verification still remains #89; the
separate roadmap project stays private.

## Post-publication launch preparation

The first routine main run after the installation-guide update,
[38211522139](https://github.com/carloshm91/kuberich/actions/runs/38211522139),
failed only its Linux x86_64 native build and dependent aggregate. The actual
error was a ten-second `dpkg-query -S /lib/x86_64-linux-gnu/libgcc_s.so.1` deadline
during original system-library ownership inspection. Original job logs are
retained. This was a build-host metadata lookup, outside application operation;
it does not change the already qualified published 0.1.0 archives.

The query now has a bounded sixty-second metadata budget. Original path/alias
identity, mandatory package ownership and strict missing/failed/ambiguous-query
refusals remain unchanged. An owned real process delayed beyond the former
ten-second bound supplies a negative control and successful corrected lookup;
expiry still aborts provenance. No application performance or coverage gate is
relaxed. Fresh hosted checks remain required.

Local verification passed 271 focused native-build/release-policy tests in
23.15 seconds, Ruff, formatting across 539 files, strict types for both changed
build/release modules, plan validation, and the 57-page/2,338-reference site
check. The regenerated site manifest remains byte-identical to PR #192's
browser-qualified `bac596a5cabb3c7012ce42ca1bb3f0a8775864b4e88e5302319494afb8393f61`.
These owned-process tests establish the deadline behavior, not a reproduction
of the hosted runner's package-database load.

The maintainer requested faster Homebrew bottles specifically for 0.2.0 in #193.
The reviewed phase map now makes that task a cumulative requirement alongside
#124 and D07's existing scope. Actual 0.1.0 upgrade, native relocation and
installation timing evidence remain required; no 0.1.0 package is replaced.
