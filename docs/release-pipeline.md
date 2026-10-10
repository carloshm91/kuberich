# Approved immutable release pipeline

D02 #36 implements `.github/workflows/release.yml` and
`python -m scripts.release`. This is distribution automation, not a published
version. Development still reports `0.0.1.dev0`. The source repository is public under #155. TestPyPI enrollment, public channel
activation and first qualified 0.1.0 publication remain D10 #89. Main and both
publication environments are now enforced; full release qualification remains pending.

## Qualification and approval

The maintainer dispatches the workflow from `main`, with a complete commit SHA,
canonical `X.Y.Z` or `X.Y.ZrcN`, destination and `dry_run` (default **true**).
Tags normalize to `vX.Y.Z` or `vX.Y.Z-rc.N`. Development/post/local/alpha/beta
versions and noncanonical spellings fail. Release bases below 0.1.0 fail before external publication requests. Reviewed
minor lines map to cumulative phase gates; unreviewed lines fail readiness. Offline canonical candidate
verification remains available. One global release concurrency group
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
- All transitive implementation prerequisites and tracked additional launch issues
  from the pinned source plan are closed in GitHub, including the selected and
  prior qualification gates themselves. Only initial 0.1.0/0.1.0rcN can proceed
  with #89 open; patches and later phases require initial activation complete.
- Successful latest main-dispatch quality and main-push repository runs for that exact commit,
  including **every Linux/macOS Python 3.12/3.13/3.14 job**, not a green aggregate
  or an older successful attempt beside a failed rerun.
  Linux jobs must request `ubuntu-24.04`, macOS jobs `macos-latest`; completed
  successful planner/aggregate/Repository jobs must also request `ubuntu-24.04`.
  A matching display name with a different or missing runner label fails.
  Dispatch Application quality on main before the release workflow; routine
  three/four-environment development runs cannot satisfy this gate.
- The retained `quality-ubuntu-24.04-python-3.12` artifact and complete fresh audit/SBOM/notices
  bound to its wheel/sdist and source/lock/policy inputs.

The Ubuntu release pin does not freeze hosted image revisions or system package
versions. Historical `ubuntu-latest` evidence retains its original identity;
an Ubuntu 26.04 upgrade needs separate future qualification before changing the
current job/artifact contract. See [runner-pin evidence](acceptance/ubuntu-runner-pin.md).

The release workflow consumes the already built/tested quality artifact. Neither
release job rebuilds it. Preparation verifies archive metadata and produces an
exclusive bundle with SHA256SUMS, exact version/commit and every retained byte.
Public preparation also freezes committed authored notes and the exact optional
reviewed generated preview; see [notes preparation](release-notes/README.md).
The optional dispatch `notes_preview` is parsed from a dedicated environment
variable, never interpolated into shell code. The validator stays read-only.
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

The maintainer must enroll/confirm the `kuberich` project or pending publisher
separately on **PyPI and TestPyPI**, using owner `carloshm91`, repository `kuberich`,
workflow `release.yml`, and the corresponding exact environment name above.
GitHub login does not prove index ownership or reserve the name. Use OIDC;
this workflow has no PyPI password/API-token secret or long-lived publisher key.

The source repository is now public and hosted development checks run again.
Main and `release`/`release-test` were configured and independently re-read on
2026-10-10 at 02:09:56 UTC. The actual release-policy protection function passed
against both environment records: required maintainer, protected branches,
`can_admins_bypass=false`, `prevent_self_review=false`. Main has strict
Quality gate/Repository checks bound to GitHub Actions and DCO bound to its app,
admin enforcement, required PRs, linear history and resolved conversations, with
force pushes/deletions disabled. First-publication readiness still requires index
ownership, OIDC/attestation, the full release matrix and public installation/upgrade
evidence under #89. This scoped configuration is not a release qualification. Neither source opening nor the old
temporary local-merge exception bypasses those checks. The workflow must refuse
when any live condition is missing; development CI is not release qualification.

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
original immutable candidate and verifies all bytes again. The validation job
must be completed on the requested `ubuntu-24.04` runner.
A failed publisher does not invalidate the already verified candidate. Audit evidence expires after
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
Retries compare the frozen source/version/tag and complete authored-plus-preview
body, then send only missing files. They never call generate-notes again.
A completed GitHub release is never edited to
accept changed content. If an expired/missing candidate or changed sidecar cannot
be recovered safely, qualify a new patch rather than moving a tag or replacing
published bytes. Follow [release recovery](releases.md#failure-and-recovery) for
incidents/yanks. Publication success is confirmed by external channel checks in
#89, not inferred from local tests.

Sources: [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
[pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[GitHub deployment protection](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[PyPA publisher](https://github.com/pypa/gh-action-pypi-publish),
[GitHub attestations](https://github.com/actions/attest).
