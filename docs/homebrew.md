# Homebrew source delivery

D03 #37 prepares a source tap, verified formula generator and immutable update-PR
automation. Native source checks and owned upgrades passed on Linux, macOS ARM
and macOS Intel under #40/#51. No public tap/package exists yet. D10 #89 must approve
public tap creation, publish the immutable artifacts and verify public installation.

## Local candidate

An audited source-only canonical version may be used for private source-install and
version-upgrade qualification. This path accepts only its exact local sdist URL.
It does not qualify or publish native archives. Public generation still rejects
source-only bundles and requires the complete public release verification.

Use an audited canonical version and its exact clean source checkout. The generator
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
`kuberich/tap`, then require these real checks:

```sh
brew style kuberich/tap/kuberich
brew audit --strict kuberich/tap/kuberich
brew install --build-from-source kuberich/tap/kuberich
brew test kuberich/tap/kuberich
brew uninstall kuberich/tap/kuberich
```

These are candidate checks, not currently available public installation commands.
Tap CI additionally requires online audit on Linux and macOS. The formula declares
Python 3.14, kubectl and libyaml. Its private environment disables system site
packages; functional tests check CLI/config/info, typing/TCSS assets and dependency
consistency. Source builds need build tools and can take several minutes. Runtime
sources are pinned. Homebrew's standard
helper still resolves isolated build backends, so this is not a fully hermetic
compiler/build environment. Dependency licenses and original notices remain their
own, including Pyte's LGPL source and replacement rights.

## Bottles

Bottles are prebuilt archives for `arm64_sonoma`, `sequoia` and `x86_64_linux`.
They are added to a version after its source formula is merged in the tap. The
formula keeps its source URL and resources, so other systems build from source.

Before a release, the native installation workflow builds a bottle from the local
candidate on each of the three hosts. On each host it installs the published
previous version from the public tap and runs `brew upgrade`. The upgrade must
pour the candidate bottle without fetching Python resources. The test then runs
the terminal, checks that preferences and the caller's kubeconfig are unchanged,
and measures cold and warm installs. The bottles stay in the run's artifacts and
are never published.

After the source formula for a release is merged, the maintainer runs the
**Homebrew bottles** workflow from main:

1. `operation: build` builds and pours each bottle on its own host and records
   timings and checksums.
2. `operation: publish` does the same, then waits for approval in the `release`
   environment. It runs `scripts.homebrew bottles`, which checks every
   `brew bottle --json` record against its archive and the current tap formula.
   It uploads the archives once to the tap release `kuberich-v<version>` and
   opens a pull request that only adds the `bottle do` block.
3. After that pull request is merged, `operation: verify` installs from the tap
   on each host and requires Homebrew to pour the bottle.

Users install from the tap without extra steps. Newer Homebrew versions run
`brew test` and `brew bottle --merge` on a third-party formula only after
`brew trust`, so the workflows trust the formula on their temporary hosts.

Bottle archives are never replaced. A retry reuses uploaded archives with the same
checksum and refuses different ones. A published bottle release cannot get new
files. Bottles are stored in the tap repository because completed source
releases are immutable.

## Reviewed updates after approved publication

The production release job invokes `scripts.homebrew publish` after complete
matching PyPI/GitHub publication. It rechecks source identity, annotated tag,
version/name and both channels' exact distribution hashes. The public source URL
comes from that verified index response. The target must be the owner-approved
public organization-owned `kuberich/homebrew-tap`, with main. The updater checks
actual repository identity and Organization owner `kuberich`; a same-named
personal repository is refused. Owner control and namespace availability must
be established before activation; a 404 lookup is not a reservation.

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
requires investigation. First live cross-repository PR, online audit and public installation/upgrades
remain D10 #89. Actual owned local baseline-to-candidate upgrades remain D04/D06
requirements, separate from fresh installs. Later public upgrades use the real
previous published artifact; first 0.1.0 has no previous public KubeRich version. Owned HTTP/Git fixtures and a
local RC do not establish public channel ownership.

Sources: [Homebrew Python formulae](https://docs.brew.sh/Language-Specific-Formulae),
[installation](https://docs.brew.sh/Installation),
[formula cookbook](https://docs.brew.sh/Formula-Cookbook).
