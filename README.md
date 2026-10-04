# Kubetrol

A keyboard-driven Kubernetes terminal UI, built with Python and Textual.

Inspired by [K9s](https://k9scli.io/). Built by Python enthusiasts.

Kubetrol aims to make browsing resources, investigating failures, following logs,
and managing workloads comfortable from your terminal, including over SSH.
It is an independent project and is not affiliated with K9s.
All Kubetrol capabilities will be open source under MIT, with no paid feature tiers.

## Project status

**The development CLI is installable from this checkout. No public application
release is available yet.**

It currently opens a real terminal workspace with context/namespace indicators,
an empty resource table, filter and command inputs, keyboard/mouse navigation,
help, themes and responsive layouts. It also provides `--help`, `--version`, safe
local `info`, preference initialization/validation and private diagnostic logs.
Kubernetes connections and live resources are upcoming.

The first release, **0.0.1**, will provide a usable resource browser, live pod
updates, filtering, resource details, container logs, and interactive exec.
Linux and macOS are the initial supported operating systems. Textual Web is
outside the product scope.

## Try the development CLI

With [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python
3.12, 3.13, or 3.14, run these commands from the repository:

```sh
uv sync --locked --group dev
uv run kubetrol --help
uv run kubetrol --version
uv run kubetrol info
uv run kubetrol config check
uv run kubetrol
```

The last command opens the terminal window in an interactive terminal. Press
`?` for help, `Esc` to return, and `q` outside an input to quit; Ctrl+Q quits from
anywhere. It does not require a kubeconfig or contact a cluster.
`uv run python -m kubetrol` is also supported.
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

- [First preview checkpoints](docs/first-preview.md)
- [Roadmap and release milestones](docs/roadmap.md)
- [Issue index and implementation order](docs/backlog.md)
- [Complete K9s capability audit](docs/k9s-parity.md)
- [CLI and authentication compatibility](docs/k9s-cli.md)
- [Local configuration and diagnostics](docs/configuration.md)
- [Terminal preview controls](docs/terminal-preview.md)
- [Architecture decisions](docs/architecture.md)
- [Security helpers and test isolation](docs/security-primitives.md)
- [Focused threat model](docs/kubetrol-threat-model.md)
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

Use [GitHub issues](https://github.com/carloshm91/kubetrol/issues) for bugs and
feature proposals. Please read [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Carlos Herrera and Kubetrol contributors.
