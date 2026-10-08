# Versioning and releases

## Current development stage

The installed version is `0.0.1.dev0`; merges collect entries under Unreleased
and do not create GitHub Releases or tags. The workflow below is the required
release procedure. D02 #36 implements the
[approved immutable pipeline](release-pipeline.md); live TestPyPI/OIDC and full
platform/protection qualification, and publishing the first usable `0.0.1`, remain
D04 #40.
The header shows installed package metadata. Automatic new-release notices remain
U01 #56, rather than an inferred claim that this checkout is a published release.

## Publication approval

Keep the repository and GitHub roadmap private until the maintainer explicitly
approves making them public. Prepare the simple landing page and initial user
documentation described in [the roadmap](roadmap.md) before the public launch.
An open-source license, merged implementation task, or proposed release date
does not authorize publication. Prepare tested artifacts and the proposed public
pages for review, then obtain explicit approval for visibility changes, website
publication, and public distribution channels, including PyPI and a Homebrew tap.

## Version rules

The first usable public application release is **0.0.1**. Repository preparation
does not create a release tag. A merged task does not automatically bump a version.

| Change | Version example |
| --- | --- |
| First usable, qualified preview | 0.0.1 |
| Bug/security fixes without a new capability | 0.0.1 -> 0.0.2 |
| New capability milestone | 0.0.x -> 0.1.0 -> 0.2.0 |
| Incompatible change before 1.0 | Next minor, with migration notes |
| Qualified stable contract | 1.0.0 |
| Incompatible change after 1.0 | Next major |

After 1.0 follow Semantic Versioning. Pre-1.0 releases remain usable and tested,
but CLI/config/plugin compatibility can change only with the documented minor
release process. Preserve existing configuration with tested migrations.

pyproject.toml's project.version is the sole release-version source. The CLI
reads installed package metadata. Do not maintain competing version constants.
Stable tags are vX.Y.Z. Release-candidate package versions are X.Y.ZrcN and their
Git tags are vX.Y.Z-rc.N; the release workflow validates normalized equivalence.

## Release sequence

1. Close implementation tasks after their candidate-level checks pass. Open the
   release gate and complete its pre-publication checklist, recording limitations
   and the qualified support matrix. The gate stays open through publication
   and verification of the public installation channels.
2. Open a release PR that updates project.version, uv.lock if affected, the
   changelog, installation documentation, and migration notes. Link the gate issue.
3. Run the required PR checks and merge the release PR through protected main.
   Dispatch Application quality on that exact main commit to run the complete
   Linux/macOS Python 3.12/3.13/3.14 quality, integration, terminal, dependency and
   clean-install matrix. Require every job to pass; routine PR/main matrices do
   not qualify a release. Retain the successful manual run and its artifact IDs.
4. The maintainer dispatches the release workflow with the intended version and
   exact main commit. It validates version/tag agreement, that commit's checks,
   milestone readiness, and that the tag/version has not already been published.
5. Consume the artifacts already built and tested by that exact commit's successful
   manual main quality run. Verify metadata, packaged assets, checksums, clean installs,
   audits and provenance. Retain those tested bytes without rebuilding them in
   the release workflow.
6. After the release environment is approved by the maintainer, create the
   annotated tag and publish those same artifacts to PyPI using OIDC Trusted
   Publishing. Publish a GitHub Release with notes, artifacts, and checksums.
7. Update the Homebrew formula from the published immutable artifact and SHA-256,
   run its CI/audit/install test, and merge the tap PR. Verify install and upgrade.
   [D03 tooling](homebrew.md) proposes the PR inside the approved production job.
   Initialize the reviewed scaffold and limited credential before dispatch; the
   maintainer reviews and merges after tap checks.
8. Close the release gate and milestone only after all required channels work.
   Record the release links. Start the next Unreleased changelog section by PR.

One release workflow owns this sequence. Do not depend on a tag created by the
workflow's GITHUB_TOKEN to trigger a second workflow. Serialize release runs;
grant write/id-token permissions only to the jobs that need them. Fork PRs get
neither publishing privileges nor cluster credentials. Pin third-party actions
to commit SHAs and update them through reviewed dependency PRs.

A channel implementation task (such as D03) can finish with a tested local release
candidate and update automation. Its first live publication and public install
verification belong to the release gate. This avoids requiring an already-published
package before the first release is allowed to publish.

## Failure and recovery

Never move or delete a published release tag, replace a published wheel, or
silently rebuild published bytes. If a retry follows a partial upload, compare
the existing artifacts and checksums and publish only missing identical outputs.
If code or packaging must change, issue a new patch release.

For a defective release, document the incident, yank the affected PyPI release
when appropriate, mark the GitHub Release clearly, and point installation guidance
to a known-good version. Keep provenance/history. Release a tested patch and
verify Homebrew upgrades; do not claim a full rollback if an external channel
cannot undo downloads already made.

## Prerequisites tracked in issues

Before each canonical RC publication, run the exact candidate's contract suite
and all seven owned-cluster rehearsals three times, retaining per-run fault/cleanup
evidence as described in [integration qualification](integration-testing.md).

- PyPI/TestPyPI project ownership and pending Trusted Publisher configuration for
  carloshm91/kubetrol, the exact workflow filename, and its release environment.
- A public carloshm91/homebrew-tap repository and a narrowly scoped mechanism
  for proposing formula updates across repositories.
- Protected main, release-environment rules, immutable release tags, artifact
  retention, and checks that validate the released commit.

PyPI account enrollment is a maintainer action; GitHub authentication does not
prove PyPI ownership. A name lookup returning 404 does not reserve the name.
Do not print installation commands as available until publication is verified.

## Sources

- [Semantic Versioning](https://semver.org/)
- [PyPA publishing from GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
