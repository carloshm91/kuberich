# Versioning and releases

## Current development and source opening

The Apache-2.0 source repository is public by the maintainer's approval in
[#155](https://github.com/carloshm91/kuberich/issues/155). The separate GitHub
project remains private. Source opening did not publish packages, a tap, a
website, tags or GitHub Releases. Installed development metadata remains
`0.0.1.dev0`; merges collect entries under Unreleased.

The first public product release is **1.0.0**, after the planned features and
final compatibility, performance, installation and capability qualification.
D04 #40, D06 #51, D07 #65, D08 #75, D09 #82 and D11 #86 are internal engineering
checkpoints. Their original dependencies and exact-artifact, native-platform,
terminal, install and security requirements remain. Deferring those checks does
not complete them. None publishes a public 0.x version.

[D10 #89](https://github.com/carloshm91/kuberich/issues/89) owns first-product
publication, public channel ownership/activation, enforced main/environment
protection and initial website/DNS verification. Delivered identity #149 and
local site preparation #150 are preparation evidence; the site must be regenerated
and qualified against the final candidate before its approved publication.
Expanded versioned documentation remains W02 #90 / W03 #91 after the product.

## Version rules

| Change | Public version example |
| --- | --- |
| First fully qualified product | 1.0.0 |
| Compatible bug or security fix | 1.0.0 → 1.0.1 |
| Compatible new capability | 1.0.0 → 1.1.0 |
| Incompatible public contract change | 1.0.0 → 2.0.0 |
| Explicitly approved candidate for a qualified target | 1.0.0rc1; tag v1.0.0-rc.1 |

Follow Semantic Versioning. A PR does not automatically bump a version.
`pyproject.toml`'s `project.version` is the sole version source; the CLI reads
installed package metadata. Stable tags are `vX.Y.Z`; canonical package release
candidates are `X.Y.ZrcN` and their tags are `vX.Y.Z-rc.N`.

Publication tooling rejects every release base below 1.0.0, including 0.x release
candidates. This applies to production, TestPyPI, tags, GitHub assets and tap
update proposals. Offline preparation can still verify historical canonical
candidates; development bundles are explicitly local-only and have no tag.
A public 1.0.0rcN is optional and requires explicit approval after all target
requirements are qualified; it does not replace the agreed first stable 1.0.0.

## Publication approval

Prepare the concrete, tested artifacts, public channel changes and website for
review before requesting approval. The source-opening approval, an open-source
license or a merged implementation PR does not authorize package, website,
public tap/registry or DNS publication. Do not purchase domains or change DNS
without the owner's explicit authorization. The maintainer has purchased
`kuberich.com`; hosting and DNS activation are still separate work.

## Release sequence

1. Finish product behavior, then the dedicated qualification phase in
   [the backlog](backlog.md). Keep unresolved native/provider evidence explicit;
   opt-in real-provider certification follows Q05 #87's agreed scope.
2. Complete the pre-publication checklist in #89: all transitive implementation
   and engineering prerequisites, Q05/Q06, identity/site preparation and tracked
   launch refinements must be closed with real evidence. The publication gate
   itself stays open through public channel verification.
3. Open a release PR for version/lock changes, changelog, migrations and verified
   installation documentation. Merge through protected main with the preserved
   maintainer sign-off and successful required checks.
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
9. Regenerate and browser/quickstart-verify the initial site from the final
   candidate, then deploy the approved immutable static bytes from GitHub Actions
   to Cloudflare Pages. Verify actual domains, HTTPS, headers, links, deployment
   IDs and rollback association; see [website delivery](website.md).
10. Close #89 only after every promised public channel and site is verified.
    Record real links and start the next Unreleased section by PR.

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

- Confirm PyPI/TestPyPI project ownership and exact pending publisher workflow and
  release environment. GitHub authentication does not prove index ownership;
  a name lookup returning 404 does not reserve it.
- Approve a dedicated public tap and limited cross-repository update credential,
  plus any promised registry/channel accounts.
- Enable and verify enforced main and publication environments, exact required
  checks, immutable tag policy and retained artifacts.
- Approve scoped Cloudflare deployment credentials/projects and concrete DNS
  changes after local site and final-candidate qualification.

Do not advertise installation channels as available before actual verification.

Sources: [Semantic Versioning](https://semver.org/),
[PyPA publishing from GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).
