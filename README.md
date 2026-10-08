# KubeRich

A keyboard-driven Kubernetes terminal UI, built with Python and Textual.

Inspired by [K9s](https://k9scli.io/). Built by Python enthusiasts.

KubeRich aims to make browsing resources, investigating failures, following logs,
and managing workloads comfortable from your terminal, including over SSH.
It is an independent project and is not affiliated with K9s.
All KubeRich capabilities will be open source under Apache-2.0, with no paid feature tiers.

## Project status

**The development CLI is installable from this checkout. No public application
release is available yet.**

It opens a terminal workspace with isolated context sessions, namespace discovery
and selection, filter/command inputs, help, themes and responsive layouts. It
supports kubeconfig/context/namespace/timeout flags, static token and certificate
authentication and noninteractive exec tokens. The [active view](docs/resource-views.md)
now synchronizes pods and [15 standard resource families](docs/standard-resources.md)
for the selected scope and shows live counts, stale states
and errors using discovery, paginated snapshots and recoverable watches.
The [live pod table](docs/pod-table.md) now displays readiness, health reasons,
restarts and age, with typed sorting, scrolling and selection preserved through
updates. Quiet watch renewal keeps Live; successful empty scopes and denied reads
are distinct. [Commands, Tab suggestions, local text/regex filters and navigation
history](docs/command-navigation.md) are available. [Pod YAML, details and related
events](docs/resource-inspection.md) include search, managedFields visibility and
redacted copying. The [container log viewer](docs/log-viewer.md) provides current/
previous output, container selection, Vim navigation, search, follow/pause,
bounded retention and redacted copy/save. [Embedded container shells](docs/container-shell.md)
use the selected context, pod and container, with a configurable shell and return
to the retained table. [Managed pod/Service TCP forwards](docs/port-forwards.md)
provide validated mappings, observed listeners, an owned session list and deliberate
stop, with cleanup on context changes and exit.
[Guarded annotation changes](docs/mutations.md) add explicit captured confirmation,
atomic UID/version conditions, common read-only enforcement and public outcome
history through `:annotate` / `:writes`. [Manifest editing](docs/editing.md) adds
an explicitly disclosed native editor, redacted diff, strict server dry-run and
separate guarded Apply through `:edit` / Shift+E. [Workload operations](docs/workloads.md)
add reviewed scale/restart/explicit rollback and actual rollout monitoring.
Deletion and Job/CronJob operations retain their separate task.
The [resource workspace](docs/resource-workspace.md) adds a built-in `k9s` theme,
top inputs and view-specific shortcuts, identity/version headers, Escape trails,
and a live namespace table with Enter/Escape navigation. The command bar suggests
completion inline, while resource frames keep their position across these views.
See [context sessions](docs/context-sessions.md) for supported credentials,
connection states and limits. Local diagnostics, read-only command guards,
header/logo/scope visibility and initial view/scope/help commands remain available.
Invocation connection overrides apply consistently to API streams and captured
shells; `--refresh` controls periodic table repaint while watches remain live.
See the [launch contract](docs/k9s-cli.md) for aliases, precedence and limits.
All audited flags are recognized; unimplemented options identify their owning task.

The first public product release will be **1.0.0**, after the planned capabilities
and compatibility checks are qualified. Source development is available before
that release; intermediate milestones are engineering checkpoints.
Linux and macOS are the initial supported operating systems. Textual Web is
outside the product scope.

The initial [landing page and user documentation](docs/website.md) can be built
and reviewed locally. Hosting, DNS and public release remain separate launch steps.

## Try the development CLI

With [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python
3.12, 3.13, or 3.14, run these commands from the repository:

```sh
uv sync --locked --group dev
uv run kuberich --help
uv run kuberich --version
uv run kuberich version --short
uv run kuberich info
uv run kuberich config check
uv run kuberich
```

The last command opens the terminal window in an interactive terminal. Press
`?` for help, `Esc` to return, and `q` outside an input to quit; Ctrl+Q quits from
anywhere. Launch reads your selected/default local kubeconfig and connects to its
current context. Without configuration it opens disconnected. Configured credential
helpers are trusted local programs and may run automatically for authentication.
Help/version/info/config inspection never connects or executes helpers.
Try `uv run kuberich --readonly --headless --command help` to start with help
and a compact header. Read-only command decisions use a shared service guard;
read-only blocks container shells, starting forwards and workload changes before
preparation. Plugins remain upcoming.
`uv run python -m kuberich` is also supported.
`info` and `config check` create no files. `config init` optionally creates default
preferences without overwriting an existing file. See
[configuration and diagnostics](docs/configuration.md) for paths, precedence,
schema, runtime log flags and error codes.
See [the terminal preview](docs/terminal-preview.md) for the available controls
and [first things to try](docs/first-preview.md) for a short feedback trial.

## Public installation

Installation instructions will be published after the first release passes its
release checklist. The planned first-release channels are PyPI (uv/pipx) and
the project's Homebrew tap. Standalone Linux and macOS executables are planned
for 0.1.0. These channels are tracked work, not currently available downloads.

## Development

Start with the [installation and trial guide](docs/quickstart.md) for the current
usable preview, actual controls and public-release limits.

- [First preview checkpoints](docs/first-preview.md)
- [Roadmap and release milestones](docs/roadmap.md)
- [Issue index and implementation order](docs/backlog.md)
- [Complete K9s capability audit](docs/k9s-parity.md)
- [CLI and authentication compatibility](docs/k9s-cli.md)
- [Local configuration and diagnostics](docs/configuration.md)
- [Terminal preview controls](docs/terminal-preview.md)
- [Resource workspace and namespace navigation](docs/resource-workspace.md)
- [Commands, completion, filters and history](docs/command-navigation.md)
- [Architecture decisions](docs/architecture.md)
- [Security helpers and test isolation](docs/security-primitives.md)
- [Focused threat model](docs/kuberich-threat-model.md)
- [Contribution workflow](CONTRIBUTING.md)
- [Testing and coverage policy](docs/quality.md)
- [Versioning, tags, and release procedure](docs/releases.md)
- [Distribution and platform support](docs/distribution.md)
- [Development assistants and skills](docs/agent-setup.md)

Application coverage must reach **at least 90% for lines and branches separately**.
The reviewed critical modules must reach 100%. CI checks the complete production
package, changed executable lines, and critical modules independently, with tests
that demonstrate rejection of regressions. See the quality policy for check names
and the current private-repository branch-protection limitation.

## Community

Use [GitHub issues](https://github.com/carloshm91/kuberich/issues) for bugs and
feature proposals. Please read [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

[Apache-2.0](LICENSE). Copyright (c) 2026 Carlos Herrera and KubeRich contributors.
See [NOTICE](NOTICE) and the [licensing guide](docs/licensing.md) for attribution,
derivative permissions and earlier MIT-licensed copies.
