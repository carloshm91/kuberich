# Approved immutable release pipeline

D02 #36 implements `.github/workflows/release.yml` and
`python -m scripts.release`. This is distribution automation, not a published
version. Development still reports `0.0.1.dev0`. Publication, TestPyPI enrollment,
visibility changes and the first live release remain D04 #40.

## Qualification and approval

The maintainer dispatches the workflow from `main`, with a complete commit SHA,
canonical `X.Y.Z` or `X.Y.ZrcN`, destination and `dry_run` (default **true**).
Tags normalize to `vX.Y.Z` or `vX.Y.Z-rc.N`. Development/post/local/alpha/beta
versions and noncanonical spellings fail. One global release concurrency group
queues dispatches; it never cancels an in-progress release.

Before preparing or publishing, require all of the following:

- The approved public repository and a commit in its main history.
- Actual enforced main protection: strict Quality gate/Repository checks/DCO,
  PRs, conversation resolution, linear history, admin enforcement, no force pushes
  or branch deletion.
- `release` for PyPI or `release-test` for TestPyPI, with maintainer as required
  reviewer, no admin bypass and protected-branch deployment policy. The initial
  solo-maintainer setup allows the maintainer to approve their own dispatch;
  the workflow never calls an environment-approval API.
- A merged in-repository PR with the same Git tree, successful DCO from its actual
  GitHub App, and the preserved maintainer sign-off on the squash commit.
- All implementation prerequisites of the pinned source plan's applicable release
  milestone are closed in GitHub. The release gate itself stays open until public
  channel verification finishes; a patch uses its established milestone baseline.
- Successful latest main-push quality and repository runs for that exact commit,
  including **every Linux/macOS Python 3.12/3.13/3.14 job**, not a green aggregate
  or an older successful attempt beside a failed rerun.
- The retained Linux 3.12 quality artifact and complete fresh audit/SBOM/notices
  bound to its wheel/sdist and source/lock/policy inputs.

The release workflow consumes the already built/tested quality artifact. Neither
release job rebuilds it. Preparation verifies archive metadata and produces an
exclusive bundle with SHA256SUMS, exact version/commit and every retained byte.
The read-only job uploads that verified candidate. Dry-run stops there.

The requested commit must equal the dispatch event's `GITHUB_SHA`. Checking out
an older ancestor does not change the event identity used by the default signed
provenance predicate. This equality keeps that provenance bound to the source
which produced the candidate.

Publication begins only after environment review. Its separate job owns
`contents: write`, `id-token: write`, and `attestations: write`; the validation
job has only contents/actions reads. Fork PRs cannot dispatch the workflow.
The publisher revalidates the live gates after approval, creates an annotated
production tag without updating any existing ref, and uploads the exact missing
files with pinned PyPA Trusted Publishing. TestPyPI creates no production tag or
GitHub release. Both destinations verify complete matching index digests after
upload. Production then uploads missing original GitHub assets into a draft and
publishes it only after every asset matches. Provenance and audited wheel SBOM
attestations use pinned `actions/attest`; PyPA publish attestations are enabled.

## Owner setup before the first dispatch

The maintainer must enroll/confirm the `kubetrol` project or pending publisher
separately on **PyPI and TestPyPI**, using owner `carloshm91`, repository `kubetrol`,
workflow `release.yml`, and the corresponding exact environment name above.
GitHub login does not prove index ownership or reserve the name. Use OIDC;
this workflow has no PyPI password/API-token secret or long-lived publisher key.

The current private GitHub plan cannot enforce main protection (403), the
existing `release` environment has no required reviewers, and hosted checks
cannot start because of billing/spending. Therefore current hosted dry-run and
publication validation must refuse. The local-merge exception never overrides
release qualification. Live TestPyPI, OIDC/attestation, full-platform CI,
protection configuration and public installation evidence remain #40.

## Local candidate without publication

After building and generating security evidence on a committed development tree:

```sh
uv build
uv run python -m scripts.check_supply_chain
uv run python -m scripts.release prepare --candidate --source . --bundle artifacts/local-release --commit "$(git rev-parse HEAD)" --version 0.0.1.dev0
uv run python -m scripts.release verify --candidate --bundle artifacts/local-release --commit "$(git rev-parse HEAD)" --version 0.0.1.dev0
```

Choose a new output directory for each trial. Preparation refuses an existing
directory. A development candidate is explicitly marked local-only, has no tag,
and cannot enter tag/publish commands. These commands neither contact a cluster
nor publish packages. Source identity, inputs and candidate bytes must remain
unchanged while generating evidence.

## Partial failure and identical-byte retry

Set `reuse_run` to the original release-dispatch run ID. The workflow verifies
its main/repository/workflow identity and successful validation job, downloads its
original immutable candidate and verifies all bytes again. A failed publisher
does not invalidate the already verified candidate. Audit evidence expires after
24 hours; artifact retention alone does not extend qualification.

A new dispatch can reuse that candidate only while main still points at its
source commit. If main has advanced, rerun only the failed jobs of the original
dispatch (`gh run rerun RUN_ID --failed`); its event SHA and successful validation
artifact remain the original ones. Do not rerun successful validation jobs or
rebuild the release to work around this check.

Existing PyPI filenames must have the same SHA-256, be unyanked and belong to the
same version. Existing tags must be annotated and point at the same commit.
Existing GitHub assets must have matching SHA-256 digests. Mismatches, unknown
assets and missing original evidence fail instead of overwriting anything.
Retries send only missing files; a completed GitHub release is never edited to
accept changed content. If an expired/missing candidate or changed sidecar cannot
be recovered safely, qualify a new patch rather than moving a tag or replacing
published bytes. Follow [release recovery](releases.md#failure-and-recovery) for
incidents/yanks. Publication success is confirmed by external channel checks in
#40, not inferred from local tests.

Sources: [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
[pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[GitHub deployment protection](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[PyPA publisher](https://github.com/pypa/gh-action-pypi-publish),
[GitHub attestations](https://github.com/actions/attest).
