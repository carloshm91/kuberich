# Homebrew source delivery

The public [project tap](https://github.com/kuberich/homebrew-tap) delivers
KubeRich on Linux and macOS. Install with `brew install kuberich/tap/kuberich`;
use `brew upgrade kuberich/tap/kuberich` for an existing installation. See
[installation](installation.md) for prerequisites, upgrades and removal.

Release tooling generates a source formula from the immutable published sdist
and audited dependency hashes, then proposes a tap pull request. Native checks
and maintainer review are required before merging. Source qualification, public
formula activation and bottle activation are separate steps. Version 0.3.0
is available from the source formula and the three bottle targets below.

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
brew trust --formula kuberich/tap/kuberich
brew style kuberich/tap/kuberich
brew audit --strict --online kuberich/tap/kuberich
brew install --build-from-source kuberich/tap/kuberich
brew test kuberich/tap/kuberich
brew uninstall kuberich/tap/kuberich
```

Run these candidate checks against the generated local tap, not an unrelated
installed public version.
Tap CI additionally requires online audit on Linux and macOS. The formula declares
Python 3.14, kubectl and libyaml. Its private environment disables system site
packages; functional tests check CLI/config/info, typing/TCSS assets and dependency
consistency. Source builds need build tools and can take several minutes. Runtime
sources are pinned. Homebrew's standard
helper still resolves isolated build backends, so this is not a fully hermetic
compiler/build environment. Dependency licenses and original notices remain their
own, including Pyte's LGPL source and replacement rights.

## Native qualification budgets

The native installation workflow uses fresh owned Actions hosts for source and
bottle checks on Linux x86_64, macOS Apple Silicon and macOS Intel. It first
prepares the formula's core dependencies on the same host, with a separate
75-minute command limit inside an 80-minute step. Application verification keeps
its own 60-minute source or 90-minute bottle step limit; each source installation
or application build still has a 30-minute command limit. The total job budget
includes these stages and 15 minutes of runner/setup/artifact overhead. A stage
timeout fails qualification.

The retained dependency receipt records the exact source, workflow job,
Homebrew executable/prefix, installed versions before and after preparation,
missing dependencies, commands and elapsed times. Application checks require that
successful receipt from the same source and runner. They retain their own
installation, upgrade, removal and terminal evidence. Preparing dependencies
does not install KubeRich or update the public tap.

Preinstalled dependencies remain labelled as preinstalled. Application build
times and cold/warm bottle pours are reported separately from dependency setup;
none is advertised as an end-to-end cold installation. A cold bottle pour means
the candidate archive was absent from Homebrew's cache, with dependencies
already prepared. Installation latency is advisory for 0.x; incomplete commands,
incorrect installed bytes, failed cleanup and changed caller files remain
failures. The preparation helper refuses personal Homebrew installations.

## Bottles

New bottles target macOS 15 Apple Silicon (`arm64_sequoia`), macOS Intel
(`sequoia`) and Linux x86_64 (`x86_64_linux`). Published 0.2.0 Apple Silicon
bottles retain their original `arm64_sonoma` tag and immutable files. Bottles
are added to a version after its source formula is merged in the tap. The formula
keeps its source URL and resources, so systems without a compatible bottle build
from source.

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

Users install from the tap without extra steps. The tap and native workflows
trust only `kuberich/tap/kuberich` on their temporary hosts before Homebrew
online audit, tests and bottle operations. Scoped formula trust is a prerequisite;
style, strict online audit, source install, test and uninstall checks all remain
required.

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

The existing public tap was initialized from `packaging/homebrew`. Keep
`HOMEBREW_TAP_TOKEN` in the protected release environment. Prefer a short-lived
GitHub App installation token. A fine-grained credential must be limited to that
tap's contents/pull requests. The updater only changes `Formula/kuberich.rb`; it
needs no workflow-write permission or PyPI token. Require Linux/macOS formula
checks, DCO and maintainer review on the tap before merging.

The updater creates Git objects, an immutable version/source branch and a PR.
It never merges, force-pushes or deletes refs. Existing published versions cannot
be downgraded or replaced. Retries verify existing branch bytes and reuse the PR;
a partial failure does not rebuild or replace the branch. A mismatched branch
requires investigation. Each release retains its actual update PR, online audit
and public installation/upgrade verification. Owned local baseline-to-candidate
upgrades remain required separately from fresh installs; later public upgrades
use the real previous published artifact. The first 0.1.0 had no previous public
KubeRich version. Owned HTTP/Git fixtures and a local RC do not establish public
channel ownership or qualify an activated package.

Sources: [Homebrew Python formulae](https://docs.brew.sh/Language-Specific-Formulae),
[installation](https://docs.brew.sh/Installation),
[formula cookbook](https://docs.brew.sh/Formula-Cookbook),
[command reference](https://docs.brew.sh/Manpage).
