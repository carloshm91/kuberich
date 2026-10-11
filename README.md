# KubeRich

A keyboard-driven Kubernetes workspace for your terminal, built with Python and Textual.

[Get started](docs/quickstart.md) · [Installation](docs/installation.md) · [User guides](docs/everyday-workflow.md) · [Contribute](CONTRIBUTING.md)

Browse a cluster, inspect a workload, follow its logs and open a container shell
without losing your place. KubeRich is an independent Apache-2.0 project,
inspired by [K9s](https://k9scli.io/) and built by Python enthusiasts.
All capabilities are open source, with no paid feature tiers.

![KubeRich showing fictional demo pods and inline command completion](https://raw.githubusercontent.com/carloshm91/kuberich/main/website/assets/workspace.svg)

*Actual application render using fictional resources and an owned local API.
No customer contexts, credentials or production resources are used in this demo.*

## First release

The first release line is **0.1.0**. Its source candidate is usable; public PyPI,
Homebrew and GitHub download activation remains under the
[release procedure](docs/releases.md).
Use a trusted checkout or supplied wheel while those channels are unavailable.

Linux and macOS are the initial targets, with CPython 3.12–3.14 for source
installation. Four standalone archives have separate native qualification.
The [installation guide](docs/installation.md#qualification-scope) states the
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

Start read-only. Effectful actions require explicit write mode, captured targets
and the Kubernetes permissions for that operation. Metrics, user plugins and
advanced node/debug operations remain planned; see the maintained
[resource views](docs/standard-resources.md) and [release phases](docs/releases.md).

## Run from source

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

For an isolated supplied wheel or future PyPI/Homebrew/archive installation,
follow [installation and upgrades](docs/installation.md). The project-owned
Homebrew target is `brew install kuberich/tap/kuberich` after public activation.

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
[guided workflow](docs/everyday-workflow.md) and [shell controls](docs/container-shell.md).

## Documentation

The maintained Markdown guides generate both website surfaces. CLI/resource
references come from application declarations; authored explanations are reviewed
with the behavior they describe. The current approved development hosts are
[website](https://kuberich-site.pages.dev) and
[docs](https://kuberich-docs.pages.dev); they retain their recorded deployment
until the final candidate is approved for publication.

- [Install, upgrade and uninstall](docs/installation.md)
- [First launch](docs/quickstart.md) and [guided everyday workflow](docs/everyday-workflow.md)
- [Contexts and authentication](docs/context-sessions.md), [EKS](docs/eks-authentication.md) and [AKS](docs/aks-authentication.md)
- [Navigation and completion](docs/command-navigation.md), [logs](docs/log-viewer.md) and [shells](docs/container-shell.md)
- [Guarded changes](docs/mutations.md), [manifest editing](docs/editing.md) and [workload operations](docs/workloads.md)
- [Troubleshooting](docs/troubleshooting.md) and [terminal compatibility](docs/terminal-compatibility.md)

## Development and quality

Read [CONTRIBUTING.md](CONTRIBUTING.md), the [architecture](docs/architecture.md)
and the selected GitHub issue before changing behavior. Work proceeds through
short-lived issue branches, signed-off commits, checked PRs and squash merges.

The [quality policy](docs/quality.md) enforces at least **90% line and branch
coverage separately**, 90% changed-line coverage and **100%** for designated
critical deterministic modules. Behavioral, actual PTY, owned Kubernetes and
clean-install checks complement coverage. Real-provider and physical-terminal
certification limits remain explicit; a percentage does not prove every environment.

See [current checkpoints](docs/first-preview.md), [roadmap](docs/roadmap.md),
[backlog](docs/backlog.md), [distribution](docs/distribution.md) and
[release/versioning procedure](docs/releases.md) for measured progress and delivery.

## Community and license

[Issues](https://github.com/carloshm91/kuberich/issues) welcome bugs and proposals.
Please follow the [code of conduct](CODE_OF_CONDUCT.md); use the
[security policy](SECURITY.md) for vulnerability reports.

[Apache-2.0](LICENSE). Copyright (c) 2026 Carlos Herrera and KubeRich contributors.
[NOTICE](NOTICE) and the [licensing guide](docs/licensing.md) explain attribution
and derivative permissions.
