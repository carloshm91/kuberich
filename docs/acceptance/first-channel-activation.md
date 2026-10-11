# First channel activation preparation

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
