# Versioning and releases

## Current development and source opening

The Apache-2.0 source repository is public by the maintainer's approval in
[#155](https://github.com/carloshm91/kuberich/issues/155). The separate GitHub
project remains private. Source opening did not publish packages, a tap, a
website, tags or GitHub Releases. The first release-preparation PR sets metadata
to `0.1.0`; its TestPyPI/PyPI uploads, immutable tag/GitHub Release and checked
Homebrew activation completed on 2026-10-12. Version 0.2.0, with Homebrew
bottles, was published on 2026-10-21. Site updates for each release need
separate approval.

The maintainer changed the release policy on 2026-10-09 to usable, qualified
**0.x phases**, beginning with **0.1.0**. This supersedes #154's earlier
first-public-1.0-only policy. The core/workload qualifier #51 is complete, and
the first candidate's launch preparation #150 is complete. A phase label, source
version or merged feature does not authorize publication.

The maintainer revised the phase plan on 2026-10-19 ([#221](https://github.com/carloshm91/kuberich/issues/221)):
foundations and a documentation rewrite come before new feature families.

| Public line | Gate (plus every earlier gate) | Phase scope |
| --- | --- | --- |
| 0.1.x | D06 #51, including D04 #40, D05 #49 and Q03 #50 | Core workspace; also #53, #54 and #123 |
| 0.2.x | D07 #65 | Extensibility; also Homebrew bottles #193 |
| 0.3.x | D16 #230 | Foundations and documentation; also #189 and #208 |
| 0.4.x | D08 #75 | Observability and metrics |
| 0.5.x | D09 #82 | Operations, Helm and manifests |
| 0.6.x | D17 #242 | Multi-cluster workspace |
| 0.7.x | D18 #248 | Extensions, security center and AI |
| 0.8.x | D11 #86 | Platforms (Windows) and accessibility; also #124 |
| 0.9.x | D19 #253 | Release candidate, including Q05 #87 and versioned docs |
| 1.0.x | Q06 #88 | Stable release and K9s/Lens parity audit |

The [plan](backlog.md) keeps every dependency. A phase is ready only when its
gate and every earlier gate are closed. An unmapped minor, such as 0.10 or 1.1,
is rejected. Common launch issues #149/#150/#154/#155/#157/#162/#166 stay
required. #81 (K9sAlpha research) was closed as not planned and is no longer a
prerequisite.

[D10 #89](https://github.com/carloshm91/kuberich/issues/89) owns initial public
channel activation and remains open through its real verification. Only initial
0.1.0 or 0.1.0rcN may transact while #89 is open; patches and later phases require
it closed. Opt-in provider certification remains Q05's agreed scope.

The approved development sites are [landing](https://kuberich-site.pages.dev)
and [initial docs](https://kuberich-docs.pages.dev), delivered by #166. Each public
candidate still needs regenerated/verified site bytes under #150 before
publication. #150 owns actual owned/local install/quickstart and candidate
guides/site qualification; #89 owns later public channel/domain/site activation
and public verification. This avoids making a pre-publication gate depend on
its own subsequent publication. Custom domains/DNS and
`www` remain separate owner-approved work.

## Version rules

Compatible 0.x fixes use a patch; new phase capabilities use the reviewed minor.
An intentional incompatible 0.x contract requires a new reviewed minor and clear
migration notes. 1.0 defines stable contracts, followed by Semantic Versioning:
compatible fixes use a patch, compatible capabilities a minor, and incompatible
public changes a major. New minor/major lines need an explicit plan mapping
before the readiness validator permits publication.

`pyproject.toml`'s `project.version` is the sole version source; the CLI reads
installed metadata. A PR does not automatically bump a version. Stable tags are
`vX.Y.Z`; canonical optional candidates are `X.Y.ZrcN`, tagged `vX.Y.Z-rc.N`.
Public tooling refuses bases below 0.1.0. Local development bundles remain usable
without a tag or authored public notes. An RC requires the same target evidence
and explicit approval; it does not replace the phase's stable-release gate.

Every public release PR commits authored per-version notes covering features,
fixes, compatibility/migrations, installation, upgrade/uninstall and known limits.
[The notes contract](release-notes/README.md) freezes these exact source bytes and
an optional owner-reviewed generated preview before publisher approval. Retries
compare the complete body and never regenerate or rewrite published notes.

## Publication approval

Prepare the concrete, tested artifacts, public channel changes and website for
review before requesting approval. The source-opening approval, an open-source
license or a merged implementation PR does not authorize package, website,
public tap/registry or DNS publication. Do not purchase domains or change DNS
without the owner's explicit authorization. The maintainer has purchased
`kuberich.com`; hosting and DNS activation are still separate work.

## Release sequence

1. Finish the selected phase's behavior and cumulative qualification in
   [the backlog](backlog.md). Keep unresolved native/provider evidence explicit;
   opt-in real-provider certification follows Q05 #87's agreed scope.
2. Complete the pre-publication checklist in #89: all transitive implementation
   and engineering prerequisites, selected/cumulative phase gates, identity/site
   preparation and tracked launch refinements must be closed with real evidence. The publication gate
   itself stays open through public channel verification.
3. Open a release-preparation PR for version/lock changes, authored notes, changelog,
   migrations and verified installation/upgrade documentation. Merge through protected main with the preserved
   maintainer sign-off and successful required checks. This PR may belong to
   #150 before that issue closes: its exact version is needed for launch-material
   qualification. All preparation prerequisites still close before publication.
4. Dispatch Application quality on that exact main commit. Require every native
   Linux/macOS CPython 3.12/3.13/3.14 job, independent coverage, critical modules,
   audits, installed artifacts, owned-cluster and terminal checks. Routine
   development matrices do not qualify a release. Retain run/artifact IDs.
5. Run that exact candidate's contracts and all owned-cluster rehearsals three
   consecutive times with fault and cleanup records, as described in
   [integration qualification](integration-testing.md). Include Q03's separate
   performance evidence. Qualify promised standalone/platform outputs too.
6. The maintainer dispatches the release workflow with the exact current main
   commit, canonical version and destination. Read-only validation checks actual
   protection, DCO/origin, live issue readiness and qualified runs. It consumes
   already tested artifacts; it does not rebuild them. Dry-run is the default.
7. After explicit publication approval and protected environment review, publish
   those immutable bytes through PyPI OIDC Trusted Publishing, create the
   annotated production tag and verified GitHub Release/assets/provenance.
   TestPyPI creates no production tag or GitHub Release.
8. Activate the approved Homebrew tap and other promised channels, verify their
   exact artifacts and public install/upgrade/uninstall behavior. Tap automation
   proposes a checked formula PR; the maintainer reviews and merges it after
   native tap checks.
   From 0.2.0, after the source formula is merged, build, publish and verify
   bottles with the Homebrew bottles workflow, as described in
   [Homebrew](homebrew.md#bottles).
9. After verified artifact activation, record the exact published version in
   `docs/published-releases.json` and update installation/upgrade guides through
   a checked PR. Regenerate and browser/quickstart-verify the site for that
   release, then deploy the approved immutable static bytes from GitHub Actions
   to Cloudflare Pages with `public_launch` enabled. Website builds in repository
   CI alone do not update live hosting. Treat documentation activation as part
   of every public release, not an optional later cleanup. Verify that actual
   site/guide notices name the available release and no longer claim unavailable
   packages; retain this evidence alongside domains, HTTPS, headers, links, deployment
   IDs and rollback association; see [website delivery](website.md).
10. Close #89 only after every promised public channel and site is verified.
    Record real links and start the next Unreleased section by PR.

The [observed development matrix](acceptance/private-ci.md) verifies a complete
matching-source PR/main pair with seven native jobs and four planner/aggregate
jobs. That reduced development pattern does not qualify a release. Step 4 still
requires all six supported combinations on the exact main candidate, with true
completed/successful statuses and artifact evidence. Retained failures, including
the warm-route heartbeat finding tracked in #40, need investigation before
engineering readiness; a later passing run is not a source correction.
Unavailable account billing does not authorize changing quotas, budgets,
runner selection or publication settings.

One serialized release workflow owns artifact publication. Do not depend on a
tag created with `GITHUB_TOKEN` to trigger another workflow. Grant publishing
and identity-token permissions only to the approved job. Fork PRs receive no
publication privileges or cluster credentials. Pin third-party actions to SHAs.

A distribution implementation task can finish with local, tested candidates and
update automation. Its public ownership, first publication and public install
verification belong to #89, avoiding a circular dependency on an unpublished
package. A qualification checkpoint closes only after its actual scoped checks.

## Failure and recovery

Never move or delete a published tag, replace a published wheel, or silently
rebuild published bytes. After a partial upload, verify existing digests and
publish only missing identical outputs. Retain original artifact/provenance
identity; expired or changed evidence requires new qualification.

If code or packaging changes, qualify a new patch. Document defective releases,
yank PyPI releases when appropriate, clearly mark GitHub Releases and point users
to a known-good version. Preserve history and verify Homebrew upgrades. Downloads
already made cannot be undone by an external-channel rollback.

## Owner prerequisites

- Configure the repository Actions secret `RELEASE_PROTECTION_TOKEN` before the
  first dry-run. Use a fine-grained token owned by `carloshm91`, select only
  `carloshm91/kuberich`, and grant only repository **Administration: read**
  (Metadata read is automatic). Give it an expiry and renew/revoke it deliberately;
  do not reuse the interactive CLI credential or grant administration write.
  Create it at [GitHub token settings](https://github.com/settings/personal-access-tokens/new)
  and save it directly in [repository Actions secrets](https://github.com/carloshm91/kuberich/settings/secrets/actions).
  Never send its value through chat, issue bodies or command arguments.
  The default Actions token cannot read branch protection. Release steps receive
  the separate credential as `KUBERICH_PROTECTION_TOKEN`; the client sends it only
  to the exact main-protection GET and rejects changes on that route. Other
  validation reads and publication writes keep their job-scoped Actions token.
  A missing credential fails before network/publication with setup instructions;
  failed protection reads still fail the release. A repository-scoped GitHub App
  installation token with the same read permission can replace the fine-grained
  token later. See [required branch-protection permission](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection)
  and [additional Actions token permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token#granting-additional-permissions).
- Confirm PyPI/TestPyPI project ownership and exact pending publisher workflow and
  release environment. GitHub authentication does not prove index ownership;
  a name lookup returning 404 does not reserve it.
- Approve a dedicated public tap and limited cross-repository update credential,
  for brand-owned `kuberich/homebrew-tap`, plus any promised registry/channel accounts.
  Confirm actual organization control before activation; a name lookup is not ownership.
- Main and both publication environments were configured and re-read on
  2026-10-10 at 02:09:56 UTC. Main has strict app-bound required checks, admin
  enforcement, PR/linear-history/conversation controls, no force pushes/deletions;
  `release` and `release-test` require the maintainer, protected branches and no
  admin bypass. Solo self-review remains allowed. Each dispatch revalidates the
  live configuration; this does not establish index ownership or release qualification.
- Approve scoped Cloudflare deployment credentials/projects and concrete DNS
  changes after local site and final-candidate qualification.

Do not advertise installation channels as available before actual verification.

Sources: [Semantic Versioning](https://semver.org/),
[PyPA publishing from GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
