# Current preview

**KubeRich 0.1.0 is published** on [PyPI](https://pypi.org/project/kuberich/0.1.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.1.0) and
[Homebrew](https://github.com/kuberich/homebrew-tap).

```sh
brew install kuberich/tap/kuberich
# Alternative with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
kuberich --version
kuberich config check
```

Choose one installation method. Start with
`kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly`, using
your intended context and namespace. The [installation guide](installation.md)
covers pipx, standalone archives, updates and removal. The
[website](https://kuberich.com/) and [documentation](https://docs.kuberich.com/)
now serve the verified public 0.1.0 content. The maintainer approved the protected
deployment, which passed on 2026-10-13 UTC. Independent custom-domain HTTPS reads
matched all 42 published files and all 26 direct guide URLs to the checked build.
The landing links to the dedicated documentation host; four legacy `/docs`
routes return the expected 301 redirects. Both custom 404 routes passed too.
The former development-version and unavailable-package notices are gone.

Final hosting acceptance remains open for the separately configured `www`
redirect and a measured custom-domain cache detail: five unchanged assets retain
the earlier `noindex, nofollow` response header. Their content and security
headers match the checked build, and fresh query-key requests return the current
indexing header. The HTML pages already serve `index, follow`. Zone-cache cleanup
and a new ordinary-URL read are still needed before claiming every response
header verified on the custom domains.

## Available workflows

The current implementation supports live pods, context and namespace tables,
standard resource views and discovered custom resources. Commands complete
inline, filtering uses `/`, and Vim-style navigation retains the selected
resource as the table refreshes.

Enter on a pod opens its containers; Enter on a container opens its logs.
Current, previous and aggregate logs, embedded shells, pod/Service forwarding,
captured attach and guarded file transfers are implemented. Reviewed changes
include annotation updates, manifest dry-run/Apply, scale/restart/rollback,
deletion and Job/CronJob operations.

Metrics, user plugins and advanced node/debug operations remain planned.
Complete K9s parity and stable 1.0 compatibility are later milestones.
The next planned public phase, 0.2.0, includes themes, configurable navigation
and views, external plugins, deliberate secret editing, terminal refinements
and verified Homebrew bottles to reduce installation compilation. These remain
planned until implemented and qualified; 0.1.0 currently installs from source
through Homebrew.
The [guided workflow](everyday-workflow.md) describes the current controls,
and the [release phases](releases.md) explain what belongs to each version.

## Current validation

The website and documentation contain fictional examples and actual application
renders from owned fixtures. Both generated surfaces passed checks across
57 offline-preview pages, including desktop/mobile navigation, accessibility
and local links. The public build has 30 pages without duplicate guides. Its
exact deployed artifact passed all 30 desktop and 30 mobile browser cases,
keyboard/copy/no-JavaScript navigation and zero automated accessibility
violations. Live custom-domain checks independently matched the served content;
the remaining asset-header cache finding above is retained without a waiver.
Exact main `3dbf9c0118193aa11635baea6ae2a0b36bee4c6e` passed all six source
Python combinations and all four native executables. Original audits and native
provenance passed independent review. Measured coverage was 99.0987–99.1296%
lines and 96.8382–96.9721% branches, with 100% for designated critical modules.
Three fresh consecutive rounds passed all thirteen owned-cluster scenario
families with caller configuration preservation and cleanup.

Actual TestPyPI/PyPI uploads, SBOM/build attestations, immutable annotated tag and
all 24 public GitHub attachment digests passed verification. Public PyPI-by-name
uv and pipx installs passed version/help/default-preference checks, no-op upgrade
and uninstall in owned environments. The public Linux x86_64 archive also passed
CLI checks outside the checkout. The other archive bytes match their native
hosted qualification. The published Homebrew formula passed Linux/macOS style,
online audit, source install, CLI tests and uninstall before protected merge.
There is no prior public release to claim as a version-upgrade baseline.

These safe local commands have been verified against the candidate:

```sh
uv sync --locked --group dev
uv run kuberich --version
uv run kuberich --help
uv run kuberich config check
```

They do not contact Kubernetes or execute authentication helpers. Connecting
requires an explicitly intended kubeconfig/context; see [first launch](quickstart.md).
The default preference permits writes. Use `--readonly` for a first connection;
write actions require the corresponding Kubernetes permissions and their
operation-specific target/review controls.

The [candidate evidence](acceptance/first-release-preparation.md) retains measured
results and limits. [Historical engineering checkpoints](preview-history.md)
remain available separately. Real cloud-provider and physical-terminal
certification still require their later opt-in trials.
