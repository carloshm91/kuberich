# KubeRich

A keyboard-driven Kubernetes workspace for your terminal, built with Python and Textual.

[Get started](https://github.com/carloshm91/kuberich/blob/main/docs/quickstart.md) · [Installation](https://github.com/carloshm91/kuberich/blob/main/docs/installation.md) · [User guides](https://github.com/carloshm91/kuberich/blob/main/docs/everyday-workflow.md) · [Contribute](https://github.com/carloshm91/kuberich/blob/main/CONTRIBUTING.md)

Browse a cluster, inspect a workload, follow its logs and open a container shell
without losing your place. KubeRich is an independent Apache-2.0 project,
inspired by [K9s](https://k9scli.io/) and built by Python enthusiasts.
All capabilities are open source, with no paid feature tiers.

![KubeRich showing fictional demo pods and inline command completion](https://raw.githubusercontent.com/carloshm91/kuberich/main/website/assets/workspace.svg)

*Actual application render using fictional resources and an owned local API.
No customer contexts, credentials or production resources are used in this demo.*

## First release

**0.1.0 is available** from [PyPI](https://pypi.org/project/kuberich/0.1.0/),
the project Homebrew tap and [GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.1.0).

```sh
brew install kuberich/tap/kuberich
# Alternative with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
```

Choose one method, then run `kuberich --version`. See
[installation and upgrades](https://github.com/carloshm91/kuberich/blob/main/docs/installation.md) for pipx and standalone archives.

Linux and macOS are the initial targets, with CPython 3.12–3.14 for source
installation. Four standalone archives have separate native qualification.
The [installation guide](https://github.com/carloshm91/kuberich/blob/main/docs/installation.md#qualification-scope) states the
actual host/architecture scope and limits. Stable 1.0 compatibility and complete
K9s parity are later milestones.

## What you can do

| Workflow | Available in this phase |
| --- | --- |
| Find a resource | Live pods, namespace/context tables, 15 standard resource families and discovered custom resources |
| Navigate | Inline `:` completion, `/` filtering, Vim keys, typed sorting and retained selection/navigation history |
| Investigate | Redacted details, YAML and events; pod → containers → selected-container logs |
| Read logs | Current/previous and aggregate logs, bounded history, search, pause/follow and guarded export |
| Connect | Embedded kubectl shells with local history/search/copy, managed pod/Service TCP forwarding, captured attach and file transfer |
| Manage a workload | Reviewed annotations, manifest dry-run/Apply, scale/restart/rollback, deletion and Job/CronJob actions |

Use `--readonly` for your first connection; the default preference permits writes.
Effectful actions require captured targets and the corresponding Kubernetes
permissions; reviewed changes also require confirmation. Metrics, user plugins and
advanced node/debug operations remain planned; see the maintained
[resource views](https://github.com/carloshm91/kuberich/blob/main/docs/standard-resources.md) and [release phases](https://github.com/carloshm91/kuberich/blob/main/docs/releases.md).

## Run from source

The next-release source also includes configurable themes and
[navigation, aliases and saved resource views](https://github.com/carloshm91/kuberich/blob/main/docs/navigation-preferences.md).
These additions are not part of the published 0.1.0 packages.

With [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.12,
3.13 or 3.14, run from a trusted checkout:

```sh
uv sync --locked --group dev
uv run kuberich --version
uv run kuberich config check
uv run kuberich --context demo-lab --namespace demo-apps --readonly
```

`demo-lab` and `demo-apps` are fictional example names. Replace them with an
explicitly intended context and namespace. Add `--kubeconfig /absolute/path/to/config`
when needed; `--config` instead selects KubeRich preferences.
Configured authentication helpers are trusted local programs. Version, help,
`info` and `config check` do not connect to a cluster or execute helpers.
The interface needs an interactive terminal; `python -m kuberich` is also supported.

For an isolated PyPI, Homebrew, archive or supplied-wheel installation,
follow [installation and upgrades](https://github.com/carloshm91/kuberich/blob/main/docs/installation.md).

## A few keys to begin

| Key or command | Result |
| --- | --- |
| `:ctx`, `:ns` | Browse contexts or namespaces as tables; Enter selects a row |
| `:pods`, `:deployments`, `:services` | Open the selected resource family |
| `/` | Filter the current table; Enter returns focus, Escape clears the filter |
| Enter on a pod | Open containers; Enter on a container opens its logs |
| `d`, `y`, `e` on a pod | Inspect details, YAML or events |
| `?` | Show actions for the current view |
| Escape | Return through the workspace trail |
| Ctrl+Q | Quit and restore the terminal |

In a live shell, keys go to the remote program. `exit`/Ctrl+D returns to
containers; Ctrl+] closes the owned session. See the
[guided workflow](https://github.com/carloshm91/kuberich/blob/main/docs/everyday-workflow.md) and [shell controls](https://github.com/carloshm91/kuberich/blob/main/docs/container-shell.md).

## Documentation

The maintained Markdown guides generate both website surfaces. CLI/resource
references come from application declarations; authored explanations are reviewed
with the behavior they describe. The public [website](https://kuberich.com/) and
[documentation](https://docs.kuberich.com/) serve the approved 0.1.0 release.
Merged source guides describe subsequent development explicitly; their next
public deployment is qualified and approved separately.

- [Install, upgrade and uninstall](https://github.com/carloshm91/kuberich/blob/main/docs/installation.md)
- [First launch](https://github.com/carloshm91/kuberich/blob/main/docs/quickstart.md) and [guided everyday workflow](https://github.com/carloshm91/kuberich/blob/main/docs/everyday-workflow.md)
- [Contexts and authentication](https://github.com/carloshm91/kuberich/blob/main/docs/context-sessions.md), [EKS](https://github.com/carloshm91/kuberich/blob/main/docs/eks-authentication.md) and [AKS](https://github.com/carloshm91/kuberich/blob/main/docs/aks-authentication.md)
- [Navigation and completion](https://github.com/carloshm91/kuberich/blob/main/docs/command-navigation.md), [logs](https://github.com/carloshm91/kuberich/blob/main/docs/log-viewer.md) and [shells](https://github.com/carloshm91/kuberich/blob/main/docs/container-shell.md)
- [Guarded changes](https://github.com/carloshm91/kuberich/blob/main/docs/mutations.md), [manifest editing](https://github.com/carloshm91/kuberich/blob/main/docs/editing.md) and [workload operations](https://github.com/carloshm91/kuberich/blob/main/docs/workloads.md)
- [Troubleshooting](https://github.com/carloshm91/kuberich/blob/main/docs/troubleshooting.md) and [terminal compatibility](https://github.com/carloshm91/kuberich/blob/main/docs/terminal-compatibility.md)

## Development and quality

Read [CONTRIBUTING.md](https://github.com/carloshm91/kuberich/blob/main/CONTRIBUTING.md), the [architecture](https://github.com/carloshm91/kuberich/blob/main/docs/architecture.md)
and the selected GitHub issue before changing behavior. Work proceeds through
short-lived issue branches, signed-off commits, checked PRs and squash merges.

The [quality policy](https://github.com/carloshm91/kuberich/blob/main/docs/quality.md) enforces at least **90% line and branch
coverage separately**, 90% changed-line coverage and **100%** for designated
critical deterministic modules. Behavioral, actual PTY, owned Kubernetes and
clean-install checks complement coverage. Real-provider and physical-terminal
certification limits remain explicit; a percentage does not prove every environment.

See [current checkpoints](https://github.com/carloshm91/kuberich/blob/main/docs/first-preview.md), [roadmap](https://github.com/carloshm91/kuberich/blob/main/docs/roadmap.md),
[backlog](https://github.com/carloshm91/kuberich/blob/main/docs/backlog.md), [distribution](https://github.com/carloshm91/kuberich/blob/main/docs/distribution.md) and
[release/versioning procedure](https://github.com/carloshm91/kuberich/blob/main/docs/releases.md) for measured progress and delivery.

## Community and license

[Issues](https://github.com/carloshm91/kuberich/issues) welcome bugs and proposals.
Please follow the [code of conduct](https://github.com/carloshm91/kuberich/blob/main/CODE_OF_CONDUCT.md); use the
[security policy](https://github.com/carloshm91/kuberich/blob/main/SECURITY.md) for vulnerability reports.

[Apache-2.0](https://github.com/carloshm91/kuberich/blob/main/LICENSE). Copyright (c) 2026 Carlos Herrera and KubeRich contributors.
[NOTICE](https://github.com/carloshm91/kuberich/blob/main/NOTICE) and the [licensing guide](https://github.com/carloshm91/kuberich/blob/main/docs/licensing.md) explain attribution
and derivative permissions.

The source checkout for the next release adds [deliberate ConfigMap and Secret
data inspection](https://github.com/carloshm91/kuberich/blob/main/docs/configuration-data.md), including guarded Secret editing.
It also adds [theme preview, context palettes, inversion and optional version
notices](https://github.com/carloshm91/kuberich/blob/main/docs/themes.md). These features are not part of the published 0.1.0 package.
