# Homebrew source delivery

D03 #37 prepares a source tap, verified formula generator and immutable update-PR
automation. No public tap/package exists yet. D10 #89 must qualify macOS, approve
public tap creation, publish the immutable artifacts and verify public installation.

## Local candidate

Use an audited canonical RC and its exact clean source checkout. The generator
verifies metadata, source identity, audits, notices and complete bundle digests:

```sh
uv run --locked python -m scripts.homebrew prepare --source /path/to/qualified-source --bundle /path/to/release-candidate --output /path/to/new-local-tap
```

Output is exclusive. The formula names the verified local sdist and 29 locked
runtime sources with SHA-256. Public source URLs cannot change registry host,
traverse paths, include credentials/query parameters or inject Ruby interpolation.
Development versions are refused. Keep the candidate readable by the owned test
account. Local file URLs never enter the public update path.

Link the generated directory into an owned Homebrew environment as the local
`carloshm91/tap`, then require these real checks:

```sh
brew style carloshm91/tap/kuberich
brew audit --strict carloshm91/tap/kuberich
brew install --build-from-source carloshm91/tap/kuberich
brew test carloshm91/tap/kuberich
brew uninstall carloshm91/tap/kuberich
```

These are candidate checks, not currently available public installation commands.
Tap CI additionally requires online audit on Linux and macOS. The formula declares
Python 3.14, kubectl and libyaml. Its private environment disables system site
packages; functional tests check CLI/config/info, typing/TCSS assets and dependency
consistency. Source builds need build tools and can take several minutes; no bottle
or standalone binary is promised. Runtime sources are pinned. Homebrew's standard
helper still resolves isolated build backends, so this is not a fully hermetic
compiler/build environment. Dependency licenses and original notices remain their
own, including Pyte's LGPL source and replacement rights.

## Reviewed updates after approved publication

The production release job invokes `scripts.homebrew publish` after complete
matching PyPI/GitHub publication. It rechecks source identity, annotated tag,
version/name and both channels' exact distribution hashes. The public source URL
comes from that verified index response. The target must be the owner-approved
public `carloshm91/homebrew-tap`, with main.

Before the approved D10 publication, initialize the tap from `packaging/homebrew` and configure
`HOMEBREW_TAP_TOKEN` in the protected release environment. Prefer a short-lived
GitHub App installation token. A fine-grained credential must be limited to that
tap's contents/pull requests. The updater only changes `Formula/kuberich.rb`; it
needs no workflow-write permission or PyPI token. Require Linux/macOS formula
checks, DCO and maintainer review on the tap before merging.

The updater creates Git objects, an immutable version/source branch and a PR.
It never merges, force-pushes or deletes refs. Existing published versions cannot
be downgraded or replaced. Retries verify existing branch bytes and reuse the PR;
a partial failure does not rebuild or replace the branch. A mismatched branch
requires investigation. First live cross-repository PR, online audit, macOS install
and public version-to-version upgrades remain D10 #89. Owned HTTP/Git fixtures and a
local RC do not establish public channel ownership.

Sources: [Homebrew Python formulae](https://docs.brew.sh/Language-Specific-Formulae),
[installation](https://docs.brew.sh/Installation),
[formula cookbook](https://docs.brew.sh/Formula-Cookbook).
